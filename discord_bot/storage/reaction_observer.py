"""Observed human reaction membership; no proactive reactions or model calls."""
import logging


def emoji_key(emoji):
    custom_id = getattr(emoji, "id", None)
    return f"custom:{custom_id}" if custom_id is not None else f"unicode:{emoji}"


class ReactionObserver:
    def __init__(self, connection):
        self.db = connection

    def add(self, payload, *, bot_user_id):
        if payload.guild_id is None or str(payload.user_id) == str(bot_user_id):
            return
        self.db.execute(
            """INSERT OR IGNORE INTO reaction_members
               (guild_id, channel_id, message_id, emoji_key, user_id)
               VALUES (?, ?, ?, ?, ?)""",
            (str(payload.guild_id), str(payload.channel_id), str(payload.message_id),
             emoji_key(payload.emoji), str(payload.user_id)),
        )

    def remove(self, payload):
        if payload.guild_id is None:
            return
        self.db.execute(
            """DELETE FROM reaction_members
               WHERE guild_id=? AND channel_id=? AND message_id=?
                 AND emoji_key=? AND user_id=?""",
            (str(payload.guild_id), str(payload.channel_id), str(payload.message_id),
             emoji_key(payload.emoji), str(payload.user_id)),
        )

    def clear(self, payload):
        if payload.guild_id is None:
            return
        self.db.execute(
            "DELETE FROM reaction_members WHERE guild_id=? AND channel_id=? AND message_id=?",
            (str(payload.guild_id), str(payload.channel_id), str(payload.message_id)),
        )

    def clear_emoji(self, payload):
        if payload.guild_id is None:
            return
        self.db.execute(
            """DELETE FROM reaction_members
               WHERE guild_id=? AND channel_id=? AND message_id=? AND emoji_key=?""",
            (str(payload.guild_id), str(payload.channel_id), str(payload.message_id),
             emoji_key(payload.emoji)),
        )

    def counts(self, guild_id, channel_id, message_id):
        return self.db.execute(
            """SELECT emoji_key, COUNT(*) FROM reaction_members
               WHERE guild_id=? AND channel_id=? AND message_id=?
               GROUP BY emoji_key ORDER BY emoji_key""",
            (str(guild_id), str(channel_id), str(message_id)),
        ).fetchall()
