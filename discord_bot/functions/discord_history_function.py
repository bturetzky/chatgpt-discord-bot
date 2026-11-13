"""Read-only, bounded FTS5 lookup scoped to visible Discord channels."""
import json
import logging
import re
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

from discord_bot.functions.base import BaseFunction, tool_error


def build_match_query(query):
    """Build a literal FTS expression from words and paired double quotes."""
    match_parts = []
    sections = query.replace("“", '"').replace("”", '"').split('"')
    word_count = 0
    for index, section in enumerate(sections):
        words = re.findall(r"[^\W_]+", section)
        word_count += len(words)
        if index % 2 and index < len(sections) - 1 and words:
            match_parts.append('"' + " ".join(words) + '"')
        else:
            match_parts.extend(f'"{word}"' for word in words)
    if word_count > 12:
        raise ValueError("query has too many words")
    return " AND ".join(match_parts)


def bounded_excerpt(snippet, opening, closing):
    """Crop around the first FTS match and remove the internal markers."""
    prefix, _, marked = snippet.partition(opening)
    first_match = marked.partition(closing)[0]
    excerpt = snippet.replace(opening, "").replace(closing, "")
    limit = 350
    if len(excerpt) <= limit:
        return excerpt

    # Reserve space for ellipses and favor keeping a complete match in view.
    width = limit - 2
    leading_context = min(80, max(0, width - len(first_match)))
    start = min(max(0, len(prefix) - leading_context), len(excerpt) - width)
    end = start + width
    return ("…" if start else "") + excerpt[start:end] + ("…" if end < len(excerpt) else "")


def search_messages(db, *, query, guild_id, channel_ids, channel_id=None,
                    author_id=None, after=None, before=None, limit=5, sort=None):
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
    if sort not in (None, "", "relevance", "newest"):
        raise ValueError("sort must be relevance or newest")
    match = build_match_query(query)
    if not match:
        return []
    order = "m.created_at DESC, m.message_id DESC"
    if sort != "newest":
        order = "bm25(messages_fts), " + order
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
    # Per-query markers avoid collisions with literal Discord message text.
    marker = uuid4().hex
    opening, closing = f"<{marker}>", f"</{marker}>"
    rows = db.execute(
        "SELECT m.guild_id,m.channel_id,m.message_id,m.author_id,"
        "snippet(messages_fts, 0, ?, ?, '…', 32),m.created_at "
        "FROM messages_fts JOIN messages m ON m.rowid=messages_fts.rowid "
        "WHERE " + " AND ".join(where) + " ORDER BY " + order + " LIMIT ?",
        (opening, closing, *params, limit),
    ).fetchall()
    return [{"message_id": message, "author_id": author, "channel_id": channel, "created_at": created,
             "snippet": bounded_excerpt(content, opening, closing), "url": f"https://discord.com/channels/{guild}/{channel}/{message}"}
            for guild, channel, message, author, content, created in rows]


def can_read_history(channel, *members):
    for member in members:
        permissions = channel.permissions_for(member)
        if not (permissions.view_channel and permissions.read_message_history):
            return False
    return True


def add_author_attribution(results, guild):
    """Use current guild member display names when cached."""
    get_member = getattr(guild, "get_member", None)
    for item in results:
        member = None
        author_id = item["author_id"]
        if get_member and author_id.isascii() and author_id.isdecimal():
            member = get_member(int(author_id))
        item["author_display_name"] = getattr(member, "display_name", None)


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
                   "Use results as historical evidence. Use get_discord_conversation_context with the result IDs to read the matching message and its surroundings. Mention a different source channel when useful.")
    parameters = {"type": "object", "properties": {
        "query": {"type": "string", "description": "Up to 12 words, all required. Put double quotes around an exact phrase. Punctuation separates words."},
        "channel_id": {"type": "string", "description": "Optional channel ID; omit to search all visible channels."},
        "author_id": {"type": "string", "description": "Optional author ID; omit to search all authors."},
        "after": {"type": "string", "description": "Inclusive ISO 8601 date/time with timezone."},
        "before": {"type": "string", "description": "Inclusive ISO 8601 date/time with timezone."},
        "sort": {"type": "string", "enum": ["relevance", "newest"],
                 "description": "Optional order. Defaults to relevance with newest first on ties."},
        "limit": {"type": "integer", "minimum": 1, "maximum": 10}
    }, "required": ["query"]}

    async def execute(self, args):
        return tool_error("CONTEXT_REQUIRED", "Discord request context required.")

    async def execute_with_context(self, args, context):
        if context is None or context.get("archive") is None or context.get("guild") is None:
            return tool_error("ARCHIVE_UNAVAILABLE", "Discord archive unavailable.")
        guild, member = context["guild"], context.get("member")
        if member is None or guild.me is None:
            return tool_error("PERMISSIONS_UNAVAILABLE", "Discord permissions unavailable.")
        allowed = {str(ch.id) for ch in guild.text_channels
                   if can_read_history(ch, member, guild.me)}
        try:
            hits = search_messages(
                context["archive"].db, query=args.get("query"), guild_id=guild.id,
                channel_ids=allowed, channel_id=args.get("channel_id"),
                author_id=args.get("author_id"), after=args.get("after"),
                before=args.get("before"), limit=args.get("limit", 5), sort=args.get("sort"))
            add_author_attribution(hits, guild)
            logging.info("History search completed: results=%d", len(hits))
            return json.dumps({"ok": True, "results": add_channel_attribution(
                hits, guild, allowed, context.get("channel_id"))})
        except (ValueError, TypeError, sqlite3.Error) as exc:
            logging.warning("History search failed: error_type=%s", type(exc).__name__)
            if isinstance(exc, sqlite3.Error):
                return tool_error("ARCHIVE_ERROR", "Could not read the Discord archive.")
            return tool_error("INVALID_ARGUMENT", "Check the search query and filters.", retryable=True)


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
                   "Use the channel_id and message_id fields from a search result. Set before and after to zero to read only the matching message (up to 1200 characters). "
                   "Mention a different source channel naturally when useful. Do not assume adjacent messages are replies; use author and timestamps.")
    parameters = {"type": "object", "properties": {
        "channel_id": {"type": "string", "description": "Channel ID from a history-search result URL."},
        "message_id": {"type": "string", "description": "Message ID from a history-search result URL."},
        "before": {"type": "integer", "minimum": 0, "maximum": 10, "description": "Optional; omit for 4 earlier messages."},
        "after": {"type": "integer", "minimum": 0, "maximum": 10, "description": "Optional; omit for 4 later messages."}
    }, "required": ["channel_id", "message_id"]}

    async def execute(self, args):
        return tool_error("CONTEXT_REQUIRED", "Discord request context required.")

    async def execute_with_context(self, args, context):
        if context is None or context.get("archive") is None or context.get("guild") is None:
            return tool_error("ARCHIVE_UNAVAILABLE", "Discord archive unavailable.")
        guild, member = context["guild"], context.get("member")
        if member is None or guild.me is None:
            return tool_error("PERMISSIONS_UNAVAILABLE", "Discord permissions unavailable.")
        allowed = {str(ch.id) for ch in guild.text_channels
                   if can_read_history(ch, member, guild.me)}
        try:
            channel_id = str(args.get("channel_id") or "")
            message_id = str(args.get("message_id") or "")
            results = get_conversation_context(
                context["archive"].db, guild_id=guild.id, channel_ids=allowed,
                channel_id=channel_id, message_id=message_id,
                before=args.get("before", 4), after=args.get("after", 4))
            logging.info("History context completed: results=%d", len(results))
            return json.dumps({"ok": True, "results": add_channel_attribution(
                results, guild, allowed, context.get("channel_id"))})
        except (ValueError, TypeError, sqlite3.Error) as exc:
            logging.warning("History context failed: error_type=%s", type(exc).__name__)
            if isinstance(exc, sqlite3.Error):
                return tool_error("ARCHIVE_ERROR", "Could not read the Discord archive.")
            return tool_error("INVALID_ARGUMENT", "Use channel and message IDs from a search result.", retryable=True)
