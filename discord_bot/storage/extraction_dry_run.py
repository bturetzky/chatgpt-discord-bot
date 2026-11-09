"""Explicit, bounded extraction dry-run. No Pinecone or Discord writes."""
import asyncio
import json
import logging
from datetime import datetime, timezone

from openai import AsyncOpenAI

from .extraction import discover_windows, register_windows
from .extraction_prompt import EXTRACTION_INSTRUCTIONS, EXTRACTOR_VERSION

VALID_TYPES = {"lore", "fact", "relationship", "event"}
VALID_CONFIDENCE = {"high", "medium", "low"}


def parse_candidates(output, window):
    """Reject unsupported model claims and IDs instead of storing them."""
    data = json.loads(output)
    if not isinstance(data, dict) or not isinstance(data.get("candidates"), list):
        raise ValueError("response must contain candidates array")
    if len(data["candidates"]) > 5:
        raise ValueError("too many candidates")
    message_ids = {row[2] for row in window.messages}
    author_ids = {row[3] for row in window.messages}
    result = []
    for item in data["candidates"]:
        if not isinstance(item, dict):
            raise ValueError("candidate must be an object")
        kind, confidence = item.get("memory_type"), item.get("confidence")
        summary, rationale = item.get("summary"), item.get("rationale")
        sources, participants = item.get("source_message_ids"), item.get("participant_ids")
        if kind not in VALID_TYPES or confidence not in VALID_CONFIDENCE:
            raise ValueError("invalid candidate type or confidence")
        if (not isinstance(summary, str) or not summary.strip() or len(summary) > 500
                or not isinstance(rationale, str) or not rationale.strip()
                or len(rationale) > 500):
            raise ValueError("invalid candidate text")
        if (not isinstance(sources, list) or not sources
                or any(not isinstance(x, str) for x in sources)
                or not set(sources) <= message_ids
                or not isinstance(participants, list)
                or any(not isinstance(x, str) for x in participants)
                or not set(participants) <= author_ids):
            raise ValueError("candidate has unsupported source or participant")
        result.append((kind, summary.strip(), json.dumps(participants),
                       json.dumps(sources), confidence, rationale.strip()))
    return result


def _input(window):
    # Never pass arbitrary unbounded text to the model.
    return json.dumps({"guild_id": window.guild_id, "channel_id": window.channel_id,
                       "messages": [
                           {"message_id": row[2], "author_id": row[3],
                            "content": row[4][:1000], "created_at": row[5]}
                           for row in window.messages
                       ]}, ensure_ascii=False)


async def dry_run(
    connection, *, guild_id, since, until, max_windows=5, max_rows=1000,
    max_messages=40, model, api_key=None, client=None,
):
    """Explicit bounded slice; stores proposed candidates locally only.

    No scheduler, automatic checkpoint advancement, or Pinecone calls.
    Callers should use settled, closed time ranges (e.g. ending >=30m ago).
    """
    if not guild_id or not model or max_windows < 1 or max_windows > 50:
        raise ValueError("guild, model and max_windows (1..50) are required")
    if since >= until or until > datetime.now(timezone.utc):
        raise ValueError("invalid historical time range")
    windows = discover_windows(
        connection, guild_id=guild_id, since=since, cutoff=until,
        max_rows=max_rows, max_messages=max_messages,
        extractor_version=EXTRACTOR_VERSION,
    )
    if len(windows) > max_windows:
        raise ValueError("too many conversation windows; narrow the time range")
    register_windows(connection, windows)
    owns_client = client is None
    if client is None:
        client = AsyncOpenAI(api_key=api_key)
    counts = {"windows": len(windows), "processed": 0, "skipped": 0,
              "failed": 0, "candidates": 0, "input_tokens": 0, "output_tokens": 0}
    try:
        for window in windows:
            row = connection.execute(
                "SELECT status FROM extraction_batches WHERE batch_id=?",
                (window.batch_id,),
            ).fetchone()
            if row[0] == "completed":
                counts["skipped"] += 1
                continue
            connection.execute(
                """UPDATE extraction_batches SET status='processing',
                   attempts=attempts+1 WHERE batch_id=?""", (window.batch_id,),
            )
            try:
                response = await asyncio.wait_for(client.responses.create(
                    model=model, instructions=EXTRACTION_INSTRUCTIONS,
                    input=_input(window), max_output_tokens=1200,
                ), timeout=45)
                candidates = parse_candidates(response.output_text, window)
                usage = getattr(response, "usage", None)
                input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
                output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
                connection.execute("BEGIN IMMEDIATE")
                try:
                    connection.execute(
                        "DELETE FROM extraction_candidates WHERE batch_id=?",
                        (window.batch_id,),
                    )
                    for i, candidate in enumerate(candidates):
                        connection.execute(
                            """INSERT INTO extraction_candidates
                               (batch_id, candidate_index, memory_type, summary,
                                participant_ids, source_message_ids, confidence, rationale)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                            (window.batch_id, i, *candidate),
                        )
                    connection.execute(
                        """INSERT INTO extraction_usage
                           (batch_id, model, input_tokens, output_tokens)
                           VALUES (?, ?, ?, ?)
                           ON CONFLICT(batch_id) DO UPDATE SET
                             model=excluded.model, input_tokens=excluded.input_tokens,
                             output_tokens=excluded.output_tokens,
                             evaluated_at=CURRENT_TIMESTAMP""",
                        (window.batch_id, model, input_tokens, output_tokens),
                    )
                    connection.execute(
                        """UPDATE extraction_batches SET status='completed',
                           processed_at=CURRENT_TIMESTAMP, error_category=NULL
                           WHERE batch_id=?""", (window.batch_id,),
                    )
                    connection.execute("COMMIT")
                except Exception:
                    connection.execute("ROLLBACK")
                    raise
                counts["processed"] += 1
                counts["candidates"] += len(candidates)
                counts["input_tokens"] += input_tokens
                counts["output_tokens"] += output_tokens
            except Exception as exc:
                connection.execute(
                    """UPDATE extraction_batches SET status='failed',
                       error_category=? WHERE batch_id=?""",
                    (type(exc).__name__[:80], window.batch_id),
                )
                counts["failed"] += 1
                logging.warning("Culture extraction dry-run failed: type=%s", type(exc).__name__)
    finally:
        if owns_client:
            await client.close()
    return counts
