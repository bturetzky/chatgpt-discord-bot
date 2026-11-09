"""Idempotent message snapshots and gateway edits/deletes for one Discord server."""
from datetime import datetime, timezone


def utc_iso(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


class MessageArchive:
    def __init__(self, database):
        self.db = database.connection

    def upsert(self, message):
        """Store a Discord snapshot; never replace a newer edit or a tombstone."""
        if message.guild is None or getattr(message.channel, "parent", None) is not None:
            return
        created = utc_iso(message.created_at)
        edited = utc_iso(message.edited_at)
        self.db.execute(
            """INSERT INTO messages
                (guild_id, channel_id, message_id, author_id, content, created_at, edited_at)
                SELECT ?, ?, ?, ?, ?, ?, ?
                WHERE NOT EXISTS (SELECT 1 FROM deleted_message_ids WHERE message_id=?)
                ON CONFLICT(message_id) DO UPDATE SET
                    content=excluded.content, edited_at=excluded.edited_at
                WHERE messages.deleted_at IS NULL
                  AND (messages.edited_at IS NULL OR
                       (excluded.edited_at IS NOT NULL AND excluded.edited_at > messages.edited_at))
                  AND (excluded.edited_at IS NOT NULL OR messages.edited_at IS NULL)""",
            (str(message.guild.id), str(message.channel.id), str(message.id),
             str(message.author.id), message.content or "", created, edited, str(message.id)),
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
