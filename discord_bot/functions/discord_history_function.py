"""Read-only, bounded FTS5 lookup scoped to visible Discord channels."""
import json
import logging
import sqlite3
from datetime import datetime, timezone

from discord_bot.functions.base import BaseFunction


def search_messages(db, *, query, guild_id, channel_ids, channel_id=None,
                    author_id=None, after=None, before=None, limit=5):
    if not isinstance(query, str) or not query.strip() or len(query) > 200:
        raise ValueError("query must be 1..200 characters")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 10:
        raise ValueError("limit must be between 1 and 10")
    # Models may supply empty strings for optional tool arguments.
    # Treat blanks as omitted, but never relax a nonblank channel restriction.
    channel_id = channel_id.strip() or None if isinstance(channel_id, str) else channel_id
    author_id = author_id.strip() or None if isinstance(author_id, str) else author_id
    after = after.strip() or None if isinstance(after, str) else after
    before = before.strip() or None if isinstance(before, str) else before
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
    return [{"message_id": message, "author_id": author, "channel_id": channel, "created_at": created,
             "snippet": content[:350], "url": f"https://discord.com/channels/{guild}/{channel}/{message}"}
            for guild, channel, message, author, content, created in rows]


def add_channel_attribution(results, guild, allowed, current_channel_id):
    """Attach source names only for permitted channels."""
    names = {str(ch.id): ch.name for ch in guild.text_channels
             if str(ch.id) in allowed and isinstance(getattr(ch, "name", None), str)}
    current = str(current_channel_id) if current_channel_id is not None else None
    for item in results:
        source = str(item["channel_id"])
        item["channel_name"] = names.get(source)
        item["different_channel"] = source != current if current is not None else None
    return results


class SearchDiscordHistory(BaseFunction):
    name = "search_discord_history"
    description = ("Search archived messages from this Discord server by keywords, including older "
                   "conversations in other channels. Use for questions about what people previously said. "
                   "Results include source channel names and cross-channel flags. Mention a different channel naturally when useful, not for every same-channel hit; don't invent missing context.")
    parameters = {"type": "object", "properties": {
        "query": {"type": "string", "description": "Literal words to find (all words must match)."},
        "channel_id": {"type": "string", "description": "Optional channel ID; omit to search all visible channels."},
        "author_id": {"type": "string", "description": "Optional author ID; omit to search all authors."},
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
            return json.dumps({"ok": False, "error": "Discord permissions unavailable"})
        allowed = {str(ch.id) for ch in guild.text_channels
                   if ch.permissions_for(member).view_channel and
                      ch.permissions_for(member).read_message_history and
                      ch.permissions_for(guild.me).view_channel and
                      ch.permissions_for(guild.me).read_message_history}
        try:
            hits = search_messages(
                context["archive"].db, query=args.get("query"), guild_id=guild.id,
                channel_ids=allowed, channel_id=args.get("channel_id"),
                author_id=args.get("author_id"), after=args.get("after"),
                before=args.get("before"), limit=args.get("limit", 5))
            logging.info("History search: guild=%s query=%r requested_channel=%s permitted_channels=%s results=%d",
                         guild.id, args.get("query"), args.get("channel_id"),
                         sorted(allowed), len(hits))
            return json.dumps({"ok": True, "results": add_channel_attribution(
                hits, guild, allowed, context.get("channel_id"))})
        except (ValueError, TypeError, sqlite3.Error) as exc:
            logging.warning("History search failed: guild=%s query=%r permitted_channels=%s error_type=%s",
                            guild.id, args.get("query"), sorted(allowed), type(exc).__name__)
            return json.dumps({"ok": False, "error": str(exc)[:160]})


def get_conversation_context(db, *, guild_id, channel_ids, channel_id, message_id,
                             before=4, after=4):
    """Read a bounded chronological window around an archived message."""
    if not isinstance(message_id, str) or not message_id.isdecimal():
        raise ValueError("message_id must be a Discord snowflake")
    if not isinstance(channel_id, str) or not channel_id.isdecimal():
        raise ValueError("channel_id must be a Discord snowflake")
    before = 4 if before is None or before == "" else before
    after = 4 if after is None or after == "" else after
    if not all(isinstance(n, int) and not isinstance(n, bool) and 0 <= n <= 10
               for n in (before, after)) or before + after > 16:
        raise ValueError("context window must be 0..10 per side and at most 16 total")
    if channel_id not in channel_ids:
        return []
    anchor = db.execute(
        "SELECT created_at FROM messages WHERE guild_id=? AND channel_id=? "
        "AND message_id=? AND deleted_at IS NULL",
        (str(guild_id), channel_id, message_id)).fetchone()
    if anchor is None:
        return []
    timestamp = anchor[0]
    fields = ("SELECT guild_id,channel_id,message_id,author_id,content,created_at "
              "FROM messages WHERE guild_id=? AND channel_id=? AND deleted_at IS NULL "
              "AND content != '' AND ")
    prior = db.execute(
        fields + "(created_at < ? OR (created_at = ? AND message_id < ?)) "
        "ORDER BY created_at DESC,message_id DESC LIMIT ?",
        (str(guild_id), channel_id, timestamp, timestamp, message_id, before)).fetchall()
    current = db.execute(
        fields + "message_id=? LIMIT 1",
        (str(guild_id), channel_id, message_id)).fetchall()
    following = db.execute(
        fields + "(created_at > ? OR (created_at = ? AND message_id > ?)) "
        "ORDER BY created_at ASC,message_id ASC LIMIT ?",
        (str(guild_id), channel_id, timestamp, timestamp, message_id, after)).fetchall()
    return [
        {"message_id": message, "author_id": author, "channel_id": channel, "created_at": created,
         "content": content[:1200],
         "url": f"https://discord.com/channels/{guild}/{channel}/{message}",
         "anchor": message == message_id}
        for guild, channel, message, author, content, created
        in [*reversed(prior), *current, *following]
    ]


class GetDiscordConversationContext(BaseFunction):
    name = "get_discord_conversation_context"
    description = ("After finding a message with search_discord_history, read nearby archived "
                   "messages in the same channel to understand the actual exchange. "
                   "Use the channel_id and message_id from a search result's Discord URL. "
                   "Mention a different source channel naturally when useful. Do not assume adjacent messages are replies; use author and timestamps.")
    parameters = {"type": "object", "properties": {
        "channel_id": {"type": "string", "description": "Channel ID from a history-search result URL."},
        "message_id": {"type": "string", "description": "Message ID from a history-search result URL."},
        "before": {"type": "integer", "minimum": 0, "maximum": 10, "description": "Optional; omit for 4 earlier messages."},
        "after": {"type": "integer", "minimum": 0, "maximum": 10, "description": "Optional; omit for 4 later messages."}
    }, "required": ["channel_id", "message_id"]}

    async def execute(self, args):
        return json.dumps({"ok": False, "error": "Discord request context required"})

    async def execute_with_context(self, args, context):
        if context is None or context.get("archive") is None or context.get("guild") is None:
            return json.dumps({"ok": False, "error": "Discord archive unavailable"})
        guild, member = context["guild"], context.get("member")
        if member is None or guild.me is None:
            return json.dumps({"ok": False, "error": "Discord permissions unavailable"})
        allowed = {str(ch.id) for ch in guild.text_channels
                   if ch.permissions_for(member).view_channel and
                      ch.permissions_for(member).read_message_history and
                      ch.permissions_for(guild.me).view_channel and
                      ch.permissions_for(guild.me).read_message_history}
        try:
            channel_id = str(args.get("channel_id") or "")
            message_id = str(args.get("message_id") or "")
            results = get_conversation_context(
                context["archive"].db, guild_id=guild.id, channel_ids=allowed,
                channel_id=channel_id, message_id=message_id,
                before=args.get("before", 4), after=args.get("after", 4))
            logging.info("History context: guild=%s channel=%s anchor=%s results=%d",
                         guild.id, channel_id, message_id, len(results))
            return json.dumps({"ok": True, "results": add_channel_attribution(
                results, guild, allowed, context.get("channel_id"))})
        except (ValueError, TypeError, sqlite3.Error) as exc:
            logging.warning("History context failed: guild=%s channel=%r anchor=%r before=%r after=%r error_type=%s error=%s",
                            guild.id, args.get("channel_id"), args.get("message_id"),
                            args.get("before"), args.get("after"), type(exc).__name__, str(exc)[:160])
            return json.dumps({"ok": False, "error": str(exc)[:160]})
