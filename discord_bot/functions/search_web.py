"""Web search with explicit, model-readable provider failure outcomes."""
import asyncio
import json
import logging

from duckduckgo_search import AsyncDDGS

from .base import BaseFunction

DDGS_DEFAULT_MAX_RESULTS = 1
MAX_RESULTS = 5


def search_error(code, message, retryable=False):
    return json.dumps({"ok": False, "error": {"code": code, "message": message, "retryable": retryable}})


class SearchWeb(BaseFunction):
    name = "search_web"
    description = (
        "Search the public web for current information. If the tool returns ok=false, "
        "respect the error: on RATE_LIMITED do not retry this search in the same "
        "conversation turn; explain that live search is temporarily unavailable, "
        "and do not invent search results. You may fetch a known public URL with "
        "get_webpage_contents, but that is not a substitute for searching."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Specific search terms."},
            "max_results": {"type": "integer", "minimum": 1, "maximum": MAX_RESULTS,
                            "description": "Number of results, 1 to 5 (default 1)."},
        },
        "required": ["query"],
    }

    async def execute(self, args):
        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            return search_error("INVALID_ARGUMENT", "A nonempty search query is required.")
        try:
            max_results = int(args.get("max_results", DDGS_DEFAULT_MAX_RESULTS))
            if not 1 <= max_results <= MAX_RESULTS:
                raise ValueError()
        except (ValueError, TypeError):
            return search_error("INVALID_ARGUMENT", "max_results must be an integer from 1 to 5.")

        try:
            async with AsyncDDGS() as ddgs:
                # DDG can return an empty result set; try its lightweight backend
                # once in that case. Do not retry rate-limited requests.
                results = await asyncio.wait_for(
                    asyncio.to_thread(ddgs.text, query, max_results=max_results),
                    timeout=15,
                )
                if not results:
                    results = await asyncio.wait_for(
                        asyncio.to_thread(ddgs.text, query, max_results=max_results, backend="lite"),
                        timeout=15,
                    )
        except asyncio.TimeoutError:
            logging.warning("Web search failed: error_type=Timeout")
            return search_error("TIMEOUT", "Web search timed out; results are unavailable.")
        except Exception as exc:
            error_type = type(exc).__name__
            logging.warning("Web search failed: error_type=%s", error_type)
            if "ratelimit" in error_type.lower() or "rate limit" in str(exc).lower() or "202 ratelimit" in str(exc).lower():
                return search_error("RATE_LIMITED", "Search provider is rate limiting requests. Do not retry immediately.")
            return search_error("PROVIDER_ERROR", "Web search provider failed; no search results are available.")

        formatted = [
            f"{item['title']} - {item['href']}"
            for item in (results or [])
            if isinstance(item, dict) and item.get("title") and item.get("href")
        ]
        if not formatted:
            logging.info("Web search completed: results=0")
            return search_error("NO_RESULTS", "No web search results were found.")
        logging.info("Web search completed: results=%d", len(formatted))
        return "\n".join(formatted)
