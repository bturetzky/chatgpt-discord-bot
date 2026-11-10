"""Transactional, operator-invoked publication ledger operations.

No Pinecone client, scheduler, or automatic promotion. A proposal is not an
authorization: the caller must supply a verified logical memory ID after dedup.
"""
import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager

from .memory_publication_lifecycle import next_revision_state, reconcile_attempt

_ID = re.compile(r"^[0-9]+$")


@contextmanager
def _transaction(connection):
    if connection.in_transaction:
        raise RuntimeError("ledger operations require their own transaction")
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield
        connection.execute("COMMIT")
    except BaseException:
        connection.execute("ROLLBACK")
        raise


def _source_snapshot(connection, guild_id, channel_id, participants, sources, bot_author_id):
    if (not isinstance(sources, list) or not 1 <= len(sources) <= 40
            or len(set(sources)) != len(sources)
            or not all(isinstance(x, str) and _ID.fullmatch(x) for x in sources)
            or not isinstance(participants, list) or not participants
            or len(set(participants)) != len(participants)
            or not all(isinstance(x, str) and _ID.fullmatch(x) for x in participants)
            or not bot_author_id or not _ID.fullmatch(str(bot_author_id))):
        raise ValueError("invalid evidence attribution")
    snapshots = []
    for message_id in sources:
        row = connection.execute(
            """SELECT guild_id, channel_id, author_id, content, created_at,
                      edited_at, deleted_at FROM messages WHERE message_id=?""",
            (message_id,),
        ).fetchone()
        if (row is None or row[0] != guild_id or row[1] != channel_id
                or row[5] is not None or row[6] is not None
                or not row[3].strip() or row[2] == str(bot_author_id)):
            raise ValueError("missing, edited, deleted, bot-authored or cross-channel source")
        snapshots.append((message_id, channel_id, row[2], row[4],
                          hashlib.sha256(row[3].encode("utf-8")).hexdigest()))
    if not set(participants).issubset({r[2] for r in snapshots}):
        raise ValueError("participants not grounded in source authors")
    return sorted(snapshots, key=lambda row: row[0])


def _hash_snapshot(snapshots):
    return hashlib.sha256(json.dumps(
        snapshots, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def stage_create(connection, plan, *, memory_id, bot_author_id):
    """Stage one reviewed CREATE, using a caller-supplied deduplicated memory ID.

    Never derive semantic memory identity from proposal_id. Only create revision 1;
    update/merge and split require separate identity and supersession policy.
    """
    if not isinstance(plan, dict) or plan.get("decision") != "review_required" or plan.get("operation") != "create" or plan.get("blockers"):
        raise ValueError("only unblocked reviewed create plans can be staged")
    memory = plan.get("memory") or {}
    proposal_id = plan.get("proposal_id")
    if not isinstance(proposal_id, str) or not proposal_id.startswith("proposal-v1-") or not isinstance(memory_id, str) or not memory_id.strip():
        raise ValueError("valid proposal and logical memory ID required")
    guild = memory.get("guild_id")
    channel = memory.get("source_channel_id")
    scope = memory.get("scope")
    durability = memory.get("durability")
    summary = memory.get("summary")
    participants = memory.get("participant_ids")
    sources = memory.get("source_message_ids")
    if (not isinstance(guild, str) or not _ID.fullmatch(guild)
            or not isinstance(channel, str) or not _ID.fullmatch(channel)
            or scope not in {"individual", "collective"}
            or durability not in {"durable", "evolving"}
            or not isinstance(summary, str) or not summary.strip()
            or re.search(r"<@!?[0-9]+>", summary)
            or (scope == "individual" and (not isinstance(participants, list) or len(participants) != 1))):
        raise ValueError("invalid staged memory")
    with _transaction(connection):
        snapshots = _source_snapshot(connection, guild, channel, participants, sources, bot_author_id)
        source_hash = _hash_snapshot(snapshots)
        prior = connection.execute(
            "SELECT memory_id, revision, source_hash, summary FROM memory_revisions WHERE proposal_id=?",
            (proposal_id,),
        ).fetchone()
        if prior:
            if prior != (memory_id, 1, source_hash, summary):
                raise ValueError("proposal already staged with different content or identity")
            return {"memory_id": memory_id, "revision": 1, "created": False}
        if connection.execute("SELECT 1 FROM memory_records WHERE memory_id=?", (memory_id,)).fetchone():
            raise ValueError("logical memory already exists; revision policy required")
        connection.execute(
            """INSERT INTO memory_records
               (memory_id, guild_id, scope, participant_ids)
               VALUES (?, ?, ?, ?)""",
            (memory_id, guild, scope, json.dumps(sorted(participants))),
        )
        connection.execute(
            """INSERT INTO memory_revisions
               (memory_id, revision, proposal_id, summary, durability, source_hash)
               VALUES (?, 1, ?, ?, ?, ?)""",
            (memory_id, proposal_id, summary, durability, source_hash),
        )
        connection.executemany(
            """INSERT INTO memory_revision_sources
               (memory_id, revision, message_id, channel_id, author_id,
                source_created_at, content_hash)
               VALUES (?, 1, ?, ?, ?, ?, ?)""",
            [(memory_id, *row) for row in snapshots],
        )
    return {"memory_id": memory_id, "revision": 1, "created": True}


def validate_sources(connection, memory_id, revision, *, bot_author_id):
    """Recheck immutable source snapshots before a future publication attempt."""
    record = connection.execute(
        "SELECT guild_id, participant_ids FROM memory_records WHERE memory_id=?",
        (memory_id,),
    ).fetchone()
    saved = connection.execute(
        """SELECT message_id, channel_id, author_id, source_created_at, content_hash
           FROM memory_revision_sources WHERE memory_id=? AND revision=?
           ORDER BY message_id""",
        (memory_id, revision),
    ).fetchall()
    if not record or not saved:
        return False
    try:
        participants = json.loads(record[1])
        snapshots = _source_snapshot(
            connection, record[0], saved[0][1], participants,
            [row[0] for row in saved], bot_author_id,
        )
    except (ValueError, TypeError):
        return False
    return snapshots == saved


def invalidate_changed_sources(connection, memory_id, revision, *, bot_author_id):
    """Invalidate a staged/failed revision if any source no longer matches."""
    with _transaction(connection):
        if validate_sources(connection, memory_id, revision, bot_author_id=bot_author_id):
            return False
        row = connection.execute(
            "SELECT state FROM memory_revisions WHERE memory_id=? AND revision=?",
            (memory_id, revision),
        ).fetchone()
        if not row:
            raise ValueError("unknown revision")
        if row[0] not in {"staged", "failed"}:
            raise ValueError("active or pending revisions require remote reconciliation")
        next_revision_state(row[0], "invalidated")
        connection.execute(
            "UPDATE memory_revisions SET state='invalidated' WHERE memory_id=? AND revision=?",
            (memory_id, revision),
        )
        connection.execute(
            "UPDATE memory_records SET lifecycle='invalidated', updated_at=CURRENT_TIMESTAMP WHERE memory_id=?",
            (memory_id,),
        )
        return True


def record_attempt(connection, *, attempt_id, memory_id, revision, operation, vector_id):
    """Record an intended operation, never perform it or imply it succeeded."""
    if not all(isinstance(x, str) and x.strip() for x in (attempt_id, memory_id, vector_id)):
        raise ValueError("attempt, memory and vector IDs required")
    if operation not in {"upsert", "delete"}:
        raise ValueError("invalid operation")
    with _transaction(connection):
        row = connection.execute(
            "SELECT state FROM memory_revisions WHERE memory_id=? AND revision=?",
            (memory_id, revision),
        ).fetchone()
        if not row or row[0] != "staged" or operation != "upsert":
            raise ValueError("only staged upsert intents supported")
        if connection.execute(
            """SELECT 1 FROM memory_publication_attempts
               WHERE memory_id=? AND revision=? AND status IN ('pending', 'uncertain')""",
            (memory_id, revision),
        ).fetchone():
            raise ValueError("unresolved publication attempt exists")
        connection.execute(
            """INSERT INTO memory_publication_attempts
               (attempt_id, memory_id, revision, operation, status, vector_id)
               VALUES (?, ?, ?, ?, 'pending', ?)""",
            (attempt_id, memory_id, revision, operation, vector_id),
        )
        connection.execute(
            "UPDATE memory_revisions SET state='pending' WHERE memory_id=? AND revision=?",
            (memory_id, revision),
        )
    return {"attempt_id": attempt_id, "status": "pending", "remote_write_performed": False}


def reconcile_recorded_attempt(connection, attempt_id, *, observation, matching_vector=False):
    """Persist an observation, not a remote write; confirmation needs proof."""
    with _transaction(connection):
        row = connection.execute(
            """SELECT memory_id, revision, status FROM memory_publication_attempts
               WHERE attempt_id=?""", (attempt_id,),
        ).fetchone()
        if not row:
            raise ValueError("unknown attempt")
        if row[2] == "confirmed":
            if observation == "matching" and matching_vector:
                return "confirmed"
            raise ValueError("confirmed attempts cannot be silently reversed")
        status = reconcile_attempt(row[2], observation, matching_vector=matching_vector)
        connection.execute(
            """UPDATE memory_publication_attempts SET status=?, completed_at=CURRENT_TIMESTAMP
               WHERE attempt_id=?""", (status, attempt_id),
        )
        if status == "confirmed":
            current = connection.execute(
                "SELECT state FROM memory_revisions WHERE memory_id=? AND revision=?",
                (row[0], row[1]),
            ).fetchone()[0]
            next_revision_state(current, "published", remote_confirmed=True)
            connection.execute(
                "UPDATE memory_revisions SET state='published' WHERE memory_id=? AND revision=?",
                (row[0], row[1]),
            )
            connection.execute(
                """UPDATE memory_records SET lifecycle='active', current_revision=?,
                   updated_at=CURRENT_TIMESTAMP WHERE memory_id=?""",
                (row[1], row[0]),
            )
        elif status == "failed":
            connection.execute(
                "UPDATE memory_revisions SET state='failed' WHERE memory_id=? AND revision=? AND state='pending'",
                (row[0], row[1]),
            )
    return status
