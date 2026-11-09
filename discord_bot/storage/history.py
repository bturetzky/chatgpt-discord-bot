"""Bounded Discord history reconciliation and operator-initiated backfill."""
import logging
from datetime import datetime, timedelta, timezone

import discord


async def reconcile_recent(client, archive, *, limit_per_channel=100):
    """Replay recent messages on startup; duplicates and tombstones remain safe."""
    for guild in client.guilds:
        for channel in guild.text_channels:
            if not channel.permissions_for(guild.me).read_message_history:
                continue
            count = 0
            try:
                async for message in channel.history(limit=limit_per_channel):
                    archive.upsert(message)
                    count += 1
                logging.info("History reconciliation: channel=%s scanned=%d", channel.id, count)
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                logging.exception("History reconciliation unavailable: channel=%s", channel.id)


async def backfill_channel(channel, archive, *, limit, cutoff, dry_run=False):
    """Continue backward from the last durable cursor, one message at a time."""
    db = archive.db
    channel_id = str(channel.id)
    row = db.execute(
        "SELECT before_message_id FROM backfill_cursors WHERE channel_id=?", (channel_id,)
    ).fetchone()
    before = discord.Object(id=int(row[0])) if row else None
    scanned = 0
    async for message in channel.history(limit=limit, before=before, oldest_first=False):
        if message.created_at < cutoff:
            break
        if not dry_run:
            archive.upsert(message)
            db.execute(
                """INSERT INTO backfill_cursors(channel_id, before_message_id)
                   VALUES (?, ?) ON CONFLICT(channel_id) DO UPDATE SET
                   before_message_id=excluded.before_message_id,
                   updated_at=CURRENT_TIMESTAMP""",
                (channel_id, str(message.id)),
            )
        scanned += 1
    return scanned


async def run_backfill(client, archive, *, days, limit_per_channel, dry_run=False):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    for guild in client.guilds:
        for channel in guild.text_channels:
            if not channel.permissions_for(guild.me).read_message_history:
                continue
            try:
                scanned = await backfill_channel(
                    channel, archive, limit=limit_per_channel, cutoff=cutoff, dry_run=dry_run
                )
                logging.info("Backfill: channel=%s scanned=%d dry_run=%s", channel.id, scanned, dry_run)
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                logging.exception("Backfill unavailable: channel=%s", channel.id)
