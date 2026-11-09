"""Small synchronous archive for the single Discord server connected to this bot."""
from datetime import timezone


class MessageArchive:
    def __init__(self, database):
        self.db = database.connection

    def upsert(self, message):
        if message.guild is None or getattr(message.channel, "parent", None) is not None:
            return
        created = message.created_at.astimezone(timezone.utc).isoformat()
        edited = message.edited_at.astimezone(timezone.utc).isoformat() if message.edited_at else None
        self.db.execute(
            """INSERT INTO messages
                (guild_id, channel_id, message_id, author_id, content, created_at, edited_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(message_id) DO UPDATE SET
                    content=excluded.content, edited_at=excluded.edited_at
                WHERE messages.deleted_at IS NULL""",
            (str(message.guild.id), str(message.channel.id), str(message.id),
             str(message.author.id), message.content or "", created, edited),
        )

    def edit(self, message_id, content):
        self.db.execute(
            """UPDATE messages SET content=?, edited_at=CURRENT_TIMESTAMP
               WHERE message_id=? AND deleted_at IS NULL""",
            (content, str(message_id)),
        )

    def delete(self, message_id):
        self.db.execute(
            """UPDATE messages SET content='', deleted_at=CURRENT_TIMESTAMP
               WHERE message_id=? AND deleted_at IS NULL""", (str(message_id),)
        )
