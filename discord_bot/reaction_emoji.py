"""Resolve custom emoji against the current guild's cache."""


def usable_guild_emoji(guild, emoji_id):
    emoji = guild.get_emoji(emoji_id)
    return emoji if emoji is not None and emoji.is_usable() else None
