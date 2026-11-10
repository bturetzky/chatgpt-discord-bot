"""Small-server autonomous memory worker: SQLite checkpoints, Pinecone memories.

Opt-in via AUTONOMOUS_MEMORY_ENABLED=true. No publication ledger state machine.
Only grounded, unblocked create proposals are published. Other proposals remain
unpublished for future improvements rather than guessing about supersession.
"""
import asyncio
import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone

from openai import AsyncOpenAI

from .extraction_dry_run import dry_run
from .memory_consolidation import preview_consolidation
from .memory_publication_plan import plan_entries
from ..handlers.vector_handler import EMBEDDING_MODEL

LOG = logging.getLogger(__name__)
INTERVAL_SECONDS = 1800


def memory_vector_id(guild_id, scope, participants, summary):
    normalized = " ".join(summary.casefold().split())
    data = json.dumps([str(guild_id), scope, sorted(participants), normalized],
                      separators=(",", ":"), ensure_ascii=False)
    return "auto-memory-v1-" + hashlib.sha256(data.encode("utf-8")).hexdigest()


def eligible(plan):
    return (plan.get("decision") == "review_required"
            and plan.get("operation") == "create"
            and not plan.get("blockers")
            and bool(plan.get("memory", {}).get("summary")))


def _mark(connection, candidate, status):
    connection.execute(
        """UPDATE extraction_candidates SET status=?
           WHERE batch_id=? AND candidate_index=? AND status='proposed'""",
        (status, candidate["batch_id"], candidate["candidate_index"]),
    )


async def run_once(connection, *, guild_id, bot_author_id, model, vector_handler,
                   client=None, now=None):
    """One bounded cycle; no write on invalid evidence or ambiguous consolidation."""
    now = now or datetime.now(timezone.utc)
    until = now - timedelta(minutes=30)
    since = until - timedelta(hours=24)
    counts = await dry_run(
        connection, guild_id=guild_id, since=since, until=until,
        max_windows=50, max_rows=1000, max_messages=40,
        model=model, bot_author_id=bot_author_id, client=client,
    )
    owns_client = client is None
    client = client or AsyncOpenAI()
    published = 0
    skipped = 0
    decisions = {"discard": 0, "review": 0, "blocked_create": 0, "duplicate": 0, "published": 0, "failed": 0}
    try:
        entries = await preview_consolidation(
            connection, guild_id=guild_id, bot_author_id=bot_author_id,
            model=model, limit=20, openai_client=client,
            index=vector_handler.vector_store.index,
        )
        plans = plan_entries(connection, entries, guild_id=guild_id,
                             bot_author_id=bot_author_id)["plans"]
        for plan in plans:
            candidate = plan["candidate"]
            if not eligible(plan):
                operation = plan.get("operation")
                category = ("discard" if operation == "discard" else
                            "review" if operation == "review" else "blocked_create")
                decisions[category] += 1
                skipped += 1
                # Blocked candidates remain proposed for operator inspection.
                continue
            memory = plan["memory"]
            participants = memory["participant_ids"]
            summary = memory["summary"]
            vector_id = memory_vector_id(guild_id, memory["scope"], participants, summary)
            try:
                # Recheck sources at the point of publication; no stale edits.
                from .memory_publication_ledger import _source_snapshot
                _source_snapshot(connection, str(guild_id), memory["source_channel_id"],
                                 participants, memory["source_message_ids"], bot_author_id)
                embedding = await asyncio.wait_for(client.embeddings.create(
                    model=EMBEDDING_MODEL, input=[summary]), timeout=30)
                vector = embedding.data[0].embedding
                # Similar memories are deliberately not blindly overwritten.
                result = await asyncio.to_thread(
                    vector_handler.vector_store.index.query,
                    vector=vector, top_k=5, include_metadata=True,
                    include_values=False,
                )
                matches = result.get("matches", []) if isinstance(result, dict) else getattr(result, "matches", [])
                duplicate = False
                for match in matches or []:
                    score = match.get("score") if isinstance(match, dict) else getattr(match, "score", None)
                    meta = match.get("metadata", {}) if isinstance(match, dict) else getattr(match, "metadata", {})
                    if (isinstance(meta, dict) and isinstance(score, (int, float))
                            and score >= 0.93
                            and (meta.get("guild_id") in (None, str(guild_id)))
                            and (not meta.get("participant_ids") or
                                 sorted(map(str, meta["participant_ids"])) == sorted(participants))):
                        duplicate = True
                        break
                if duplicate:
                    _mark(connection, candidate, "superseded")
                    decisions["duplicate"] += 1
                    skipped += 1
                    continue
                metadata = {
                    "summary": summary, "memory_type": "relationship" if memory["scope"] == "collective" else "fact",
                    "guild_id": str(guild_id), "scope": memory["scope"],
                    "participant_ids": participants, "source_message_ids": memory["source_message_ids"],
                    "source_hash": hashlib.sha256(json.dumps(
                        memory["source_message_ids"], separators=(",", ":")).encode()).hexdigest(),
                    "origin": "autonomous-v1",
                }
                await asyncio.to_thread(
                    vector_handler.vector_store.index.upsert,
                    vectors=[{"id": vector_id, "values": vector, "metadata": metadata}],
                )
                _mark(connection, candidate, "accepted")
                published += 1
                decisions["published"] += 1
            except Exception as exc:
                decisions["failed"] += 1
                LOG.warning("Autonomous memory publication failed: error_type=%s",
                            type(exc).__name__)
        return {**counts, "published": published, "skipped_publication": skipped,
                "publication_decisions": decisions}
    finally:
        if owns_client:
            await client.close()


async def run_forever(archive, vector_handler, *, guild_id, bot_author_id, model, stop_event):
    """Run after gateway ready; failures never crash the Discord bot."""
    while not stop_event.is_set():
        try:
            counts = await run_once(
                archive.db, guild_id=str(guild_id),
                bot_author_id=str(bot_author_id), model=model,
                vector_handler=vector_handler,
            )
            LOG.info("Autonomous memory cycle: %s", counts)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOG.warning("Autonomous memory cycle failed: error_type=%s",
                        type(exc).__name__)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass
