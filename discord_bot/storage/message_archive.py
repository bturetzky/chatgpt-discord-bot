"""Idempotent message snapshots and gateway edits/deletes for one Discord server."""
from datetime import datetime, timezone

import discord


def utc_iso(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def reply_target(message):
    """Read an explicit reply reference without using its embedded message."""
    if getattr(message, "type", None) != discord.MessageType.reply:
        return None
    reference = message.reference
    if reference is None or reference.message_id is None:
        return None
    if reference.guild_id not in (None, message.guild.id):
        return None
    return str(reference.channel_id), str(reference.message_id)


class MessageArchive:
    def __init__(self, database):
        self.db = database.connection

    def upsert(self, message):
        """Store a Discord snapshot; never replace a newer edit or a tombstone."""
        if message.guild is None or getattr(message.channel, "parent", None) is not None:
            return
        created = utc_iso(message.created_at)
        edited = utc_iso(message.edited_at)
        reply_channel, reply_message = reply_target(message) or (None, "")
        self.db.execute(
            """INSERT INTO messages
                (guild_id, channel_id, message_id, author_id, content, created_at, edited_at,
                 reply_channel_id, reply_message_id)
                SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?
                WHERE NOT EXISTS (SELECT 1 FROM deleted_message_ids WHERE message_id=?)
                ON CONFLICT(message_id) DO UPDATE SET
                    content=excluded.content, edited_at=excluded.edited_at,
                    reply_channel_id=excluded.reply_channel_id,
                    reply_message_id=excluded.reply_message_id
                WHERE messages.deleted_at IS NULL
                  AND (messages.edited_at IS NULL OR
                       (excluded.edited_at IS NOT NULL AND excluded.edited_at > messages.edited_at))
                  AND (excluded.edited_at IS NOT NULL OR messages.edited_at IS NULL)""",
            (str(message.guild.id), str(message.channel.id), str(message.id),
             str(message.author.id), message.content or "", created, edited,
             reply_channel, reply_message, str(message.id)),
        )

    def edit(self, message_id, content, edited_at=None):
        """Apply only a newer edit. Unknown messages can be fetched and upserted by caller."""
        timestamp = utc_iso(edited_at) or utc_iso(datetime.now(timezone.utc))
        self.db.execute(
            """UPDATE messages SET content=?, edited_at=?
               WHERE message_id=? AND deleted_at IS NULL
                 AND (edited_at IS NULL OR edited_at < ?)""",
            (content, timestamp, str(message_id), timestamp),
        )

    def delete(self, message_id):
        """Remember deletes even if their original message has not been indexed."""
        message_id = str(message_id)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.db.execute(
                "INSERT OR IGNORE INTO deleted_message_ids(message_id) VALUES (?)",
                (message_id,),
            )
            self.db.execute(
                """UPDATE messages SET content='', deleted_at=CURRENT_TIMESTAMP
                   WHERE message_id=? AND deleted_at IS NULL""", (message_id,),
            )
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
