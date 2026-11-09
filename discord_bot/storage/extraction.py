"""Deterministic, bounded text-only conversation windows for future memory extraction.

This module makes no model calls and does not schedule extraction.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json


@dataclass(frozen=True)
class ConversationWindow:
    batch_id: str
    guild_id: str
    channel_id: str
    first_message_id: str
    last_message_id: str
    source_hash: str
    extractor_version: str
    messages: tuple


def _parse_timestamp(value):
    timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def discover_windows(
    connection, *, guild_id, cutoff, since=None, idle_minutes=30,
    max_messages=80, extractor_version="v1", max_rows=5000,
):
    """Read a bounded, settled slice of one guild's archived text messages.

    Caller must provide a UTC cutoff and, for incremental runs, a since bound.
    The selected slice must include complete conversation windows; the caller
    should use a lookback/overlap when advancing incremental discovery.
    """
    if max_messages < 1 or max_rows < 1 or idle_minutes < 1:
        raise ValueError("window limits must be positive")
    if cutoff.tzinfo is None or (since is not None and since.tzinfo is None):
        raise ValueError("timestamps must be timezone-aware")
    params = [str(guild_id), cutoff.astimezone(timezone.utc).isoformat()]
    lower = ""
    if since is not None:
        lower = " AND created_at >= ?"
        params.append(since.astimezone(timezone.utc).isoformat())
    # Limit + 1 detects truncation: never process a partial last window.
    rows = connection.execute(
        """SELECT guild_id, channel_id, message_id, author_id, content,
                  created_at, edited_at
           FROM messages
           WHERE guild_id=? AND deleted_at IS NULL AND content <> ''
             AND created_at < ?""" + lower +
        """ ORDER BY channel_id, created_at, message_id LIMIT ?""",
        (*params, max_rows + 1),
    ).fetchall()
    if len(rows) > max_rows:
        raise ValueError("archive slice exceeds max_rows; narrow the time range")
    windows = []
    current = []

    def flush():
        if not current:
            return
        first, last = current[0], current[-1]
        identity = [first[0], first[1], first[2], last[2], extractor_version]
        batch_id = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
        evidence = [[r[2], r[3], r[4], r[5], r[6]] for r in current]
        source_hash = hashlib.sha256(
            json.dumps(evidence, ensure_ascii=False).encode()
        ).hexdigest()
        windows.append(ConversationWindow(
            batch_id, first[0], first[1], first[2], last[2],
            source_hash, extractor_version, tuple(current),
        ))

    for row in rows:
        if current and (
            row[1] != current[-1][1]
            or _parse_timestamp(row[5]) - _parse_timestamp(current[-1][5])
            > timedelta(minutes=idle_minutes)
            or len(current) >= max_messages
        ):
            flush()
            current = []
        current.append(row)
    flush()
    return windows


def register_windows(connection, windows):
    """Idempotently register windows; changed evidence reopens a batch.

    A changed source hash does not silently retain a completed status.
    Reprocessing with a new prompt version uses a different batch ID.
    """
    changed = 0
    for window in windows:
        cursor = connection.execute(
            """INSERT INTO extraction_batches
               (batch_id, guild_id, channel_id, first_message_id,
                last_message_id, source_hash, extractor_version)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(batch_id) DO UPDATE SET
                   source_hash=excluded.source_hash,
                   status='pending', processed_at=NULL, error_category=NULL
               WHERE extraction_batches.source_hash <> excluded.source_hash""",
            (window.batch_id, window.guild_id, window.channel_id,
             window.first_message_id, window.last_message_id,
             window.source_hash, window.extractor_version),
        )
        changed += cursor.rowcount
    return changed
