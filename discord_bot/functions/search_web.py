"""Brave Search API integration with model-readable errors and safe logging."""
import asyncio
import json
import logging
import os

import aiohttp

from .base import BaseFunction

SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
MAX_RESULTS = 5
TIMEOUT_SECONDS = 12


def search_error(code, message, retryable=False):
    return json.dumps({"ok": False, "error": {"code": code, "message": message, "retryable": retryable}})


class SearchWeb(BaseFunction):
    name = "search_web"
    description = (
        "Search the public web using Brave Search for current information. "
        "On an ok=false error, do not invent results. If RATE_LIMITED, do not "
        "retry during this turn. If AUTH_ERROR or CONFIG_ERROR, report that "
        "search is unavailable rather than retrying. You may fetch a known "
        "public URL separately, but that is not a substitute for searching."
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
        count = args.get("max_results", 1)
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= MAX_RESULTS:
            return search_error("INVALID_ARGUMENT", "max_results must be an integer from 1 to 5.")

        key = os.environ.get("BRAVE_SEARCH_API_KEY")
        if not key:
            logging.error("Brave search unavailable: missing API key")
            return search_error("CONFIG_ERROR", "Web search is not configured.")

        params = {"q": query, "count": count}
        if args.get("freshness") == "pw":
            params["freshness"] = "pw"
        headers = {"Accept": "application/json", "X-Subscription-Token": key}
        try:
            timeout = aiohttp.ClientTimeout(total=TIMEOUT_SECONDS)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(SEARCH_URL, headers=headers,
                                       params=params) as response:
                    status = response.status
                    if status == 429:
                        logging.warning("Brave search failed: status=429")
                        return search_error("RATE_LIMITED", "Search provider rate limit reached; do not retry immediately.")
                    if status in (401, 403):
                        logging.error("Brave search failed: status=%d", status)
                        return search_error("AUTH_ERROR", "Search provider rejected the API credentials.")
                    if status != 200:
                        logging.warning("Brave search failed: status=%d", status)
                        return search_error("PROVIDER_ERROR", "Search provider is temporarily unavailable.")
                    payload = await response.json()
        except (asyncio.TimeoutError, aiohttp.ServerTimeoutError):
            logging.warning("Brave search failed: timeout")
            return search_error("TIMEOUT", "Search request timed out.")
        except (aiohttp.ClientError, ValueError):
            logging.warning("Brave search failed: transport_or_response_error")
            return search_error("PROVIDER_ERROR", "Search provider request failed.")

        items = payload.get("web", {}).get("results", []) if isinstance(payload, dict) else []
        if not isinstance(items, list):
            return search_error("PROVIDER_ERROR", "Search provider returned an invalid response.")
        results = [
            {"title": item["title"], "url": item["url"]}
            for item in items[:count]
            if isinstance(item, dict) and isinstance(item.get("title"), str)
            and isinstance(item.get("url"), str)
        ]
        if not results:
            logging.info("Brave search completed: results=0")
            return search_error("NO_RESULTS", "No search results found.")
        logging.info("Brave search completed: results=%d", len(results))
        return json.dumps({"ok": True, "results": results})
