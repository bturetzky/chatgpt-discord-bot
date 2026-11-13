"""Post an optional emoji reaction to the message that triggered a reply."""
import asyncio
import json
import re

import discord
import emoji

from .base import BaseFunction, tool_error
from ..reaction_emoji import usable_guild_emoji

MAX_REPLY_REACTIONS = 1
CUSTOM_MENTION = re.compile(r"<a?:[A-Za-z0-9_]{2,32}:([0-9]{1,20})>")
CUSTOM_NAME = re.compile(r":([A-Za-z0-9_]{2,32}):")


def resolve_emoji(guild, value):
    if emoji.is_emoji(value):
        return value
    if match := CUSTOM_MENTION.fullmatch(value):
        return usable_guild_emoji(guild, int(match[1]))
    if match := CUSTOM_NAME.fullmatch(value):
        matches = [item for item in guild.emojis if item.name == match[1] and item.is_usable()]
        if len(matches) == 1:
            return matches[0]
    return None


class ReplyReactions:
    """Track successful posts across every tool call in one reply."""

    def __init__(self, message):
        self.message = message
        self.lock = asyncio.Lock()
        self.successes = 0

    @classmethod
    def for_message(cls, message):
        if (message is not None and message.guild is not None
                and not message.author.bot and not message.webhook_id):
            return cls(message)
        return None

    async def add(self, value):
        async with self.lock:
            if self.successes >= MAX_REPLY_REACTIONS:
                return "reaction_limit"
            resolved = resolve_emoji(self.message.guild, value)
            if resolved is None:
                return "emoji_unavailable"
            try:
                await self.message.add_reaction(resolved)
            except discord.NotFound:
                return "message_or_emoji_unavailable"
            except discord.Forbidden:
                return "forbidden"
            except discord.HTTPException:
                return "discord_api_error"
            self.successes += 1
            return None


class ReactToMessage(BaseFunction):
    name = "react_to_message"
    description = (
        "Optionally react to the original message when an emoji fits naturally. "
        "Use sparingly and continue with the normal conversational answer."
    )
    parameters = {
        "type": "object",
        "properties": {
            "emoji": {
                "type": "string",
                "description": "One Unicode emoji or a current guild custom emoji (Discord markup or :name:).",
            },
        },
        "required": ["emoji"],
        "additionalProperties": False,
    }

    @classmethod
    def get_parameters(cls):
        return cls.parameters

    async def execute_with_context(self, args, context):
        if not isinstance(args, dict) or args.keys() != {"emoji"} or not isinstance(args["emoji"], str):
            error = "invalid_arguments"
        elif (reactions := (context or {}).get("reply_reactions")) is None:
            error = "message_unavailable"
        else:
            error = await reactions.add(args["emoji"])
        if error:
            return tool_error(error, "Reaction unavailable. Continue with the normal reply.")
        return json.dumps({"ok": True})
