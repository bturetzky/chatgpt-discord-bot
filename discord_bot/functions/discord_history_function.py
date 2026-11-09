"""Read-only, bounded FTS5 lookup scoped to visible Discord channels."""
import json
import sqlite3
from datetime import datetime, timezone

from discord_bot.functions.base import BaseFunction


def search_messages(db, *, query, guild_id, channel_ids, channel_id=None,
                    author_id=None, after=None, before=None, limit=5):
    if not isinstance(query, str) or not query.strip() or len(query) > 200:
        raise ValueError("query must be 1..200 characters")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 10:
        raise ValueError("limit must be between 1 and 10")
    if channel_id is not None and str(channel_id) not in channel_ids:
        return []
    allowed = [str(channel_id)] if channel_id is not None else list(channel_ids)
    if not allowed:
        return []
    terms = query.split()
    # Quote each literal term; no arbitrary FTS query operators or column selectors.
    if len(terms) > 12:
        raise ValueError("query has too many words")
    match = " AND ".join('"' + term.replace('"', '""') + '"' for term in terms)
    where = ["messages_fts MATCH ?", "m.guild_id=?", "m.deleted_at IS NULL",
             "m.content != ''", "m.channel_id IN (" + ",".join("?" for _ in allowed) + ")"]
    params = [match, str(guild_id), *allowed]
    if author_id is not None:
        where.append("m.author_id=?")
        params.append(str(author_id))
    for key, value, op in (("after", after, ">="), ("before", before, "<=")):
        if value is not None:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError(key + " must include a timezone")
            where.append("m.created_at " + op + " ?")
            params.append(parsed.astimezone(timezone.utc).isoformat(timespec="microseconds"))
    rows = db.execute(
        "SELECT m.guild_id,m.channel_id,m.message_id,m.author_id,m.content,m.created_at "
        "FROM messages_fts JOIN messages m ON m.rowid=messages_fts.rowid "
        "WHERE " + " AND ".join(where) + " ORDER BY m.created_at DESC LIMIT ?",
        (*params, limit),
    ).fetchall()
    return [{"author_id": author, "channel_id": channel, "created_at": created,
             "snippet": content[:350], "url": f"https://discord.com/channels/{guild}/{channel}/{message}"}
            for guild, channel, message, author, content, created in rows]


class SearchDiscordHistory(BaseFunction):
    name = "search_discord_history"
    description = ("Search archived messages from this Discord server by keywords, including older "
                   "conversations in other channels. Use for questions about what people previously said. "
                   "Results contain short excerpts and source links; don't invent missing context.")
    parameters = {"type": "object", "properties": {
        "query": {"type": "string", "description": "Literal words to find (all words must match)."},
        "channel_id": {"type": "string"},
        "author_id": {"type": "string"},
        "after": {"type": "string", "description": "Inclusive ISO 8601 date/time with timezone."},
        "before": {"type": "string", "description": "Inclusive ISO 8601 date/time with timezone."},
        "limit": {"type": "integer", "minimum": 1, "maximum": 10}
    }, "required": ["query"]}

    async def execute(self, args):
        return json.dumps({"ok": False, "error": "Discord request context required"})

    async def execute_with_context(self, args, context):
        if context is None or context.get("archive") is None or context.get("guild") is None:
            return json.dumps({"ok": False, "error": "Discord archive unavailable"})
        guild, member = context["guild"], context["member"]
        if member is None or guild.me is None:
            return json.dumps({"ok": False, "error": "Discord permissions unavailable"})\n        allowed = {str(ch.id) for ch in guild.text_channels
                   if ch.permissions_for(member).view_channel and
                      ch.permissions_for(member).read_message_history and
                      ch.permissions_for(guild.me).read_message_history}
        try:
            hits = search_messages(
                context["archive"].db, query=args.get("query"), guild_id=guild.id,
                channel_ids=allowed, channel_id=args.get("channel_id"),
                author_id=args.get("author_id"), after=args.get("after"),
                before=args.get("before"), limit=args.get("limit", 5))
            return json.dumps({"ok": True, "results": hits})
        except (ValueError, TypeError, sqlite3.Error) as exc:
            return json.dumps({"ok": False, "error": str(exc)[:160]})
