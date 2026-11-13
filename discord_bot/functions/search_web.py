"""Brave Search API integration with model-readable errors and safe logging."""
import asyncio
import json
import logging
import os

import aiohttp

from .base import BaseFunction, tool_error

SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
MAX_RESULTS = 5
DEFAULT_RESULTS = 3
MAX_SNIPPET_CHARS = 400
MAX_PAGE_DATE_CHARS = 64
FRESHNESS_OPTIONS = ("pd", "pw", "pm", "py")
TIMEOUT_SECONDS = 12


class SearchWeb(BaseFunction):
    name = "search_web"
    description = (
        "Search the public web using Brave Search for current information. "
        "Results may include untrusted search snippets and a provider page date based on publication "
        "or last modification. Read the source to verify article details and publication dates. "
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
                            "default": DEFAULT_RESULTS,
                            "description": "Number of results, 1 to 5."},
            "freshness": {
                "type": "string", "enum": list(FRESHNESS_OPTIONS),
                "description": "Optional page-age filter: pd (24 hours), pw (7 days), "
                               "pm (31 days), py (365 days). Omit for unrestricted search.",
            },
        },
        "required": ["query"],
    }

    async def execute(self, args):
        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            return tool_error("INVALID_ARGUMENT", "A nonempty search query is required.")
        count = args.get("max_results", DEFAULT_RESULTS)
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= MAX_RESULTS:
            return tool_error("INVALID_ARGUMENT", "max_results must be an integer from 1 to 5.")

        if "freshness" in args and args["freshness"] not in FRESHNESS_OPTIONS:
            return tool_error("INVALID_ARGUMENT", "freshness must be pd, pw, pm, or py.")

        key = os.environ.get("BRAVE_SEARCH_API_KEY")
        if not key:
            logging.error("Brave search unavailable: missing API key")
            return tool_error("CONFIG_ERROR", "Web search is not configured.")

        params = {"q": query, "count": count}
        if "freshness" in args:
            params["freshness"] = args["freshness"]
        headers = {"Accept": "application/json", "X-Subscription-Token": key}
        try:
            timeout = aiohttp.ClientTimeout(total=TIMEOUT_SECONDS)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(SEARCH_URL, headers=headers,
                                       params=params) as response:
                    status = response.status
                    if status == 429:
                        logging.warning("Brave search failed: status=429")
                        return tool_error("RATE_LIMITED", "Search provider rate limit reached; do not retry immediately.")
                    if status in (401, 403):
                        logging.error("Brave search failed: status=%d", status)
                        return tool_error("AUTH_ERROR", "Search provider rejected the API credentials.")
                    if status != 200:
                        logging.warning("Brave search failed: status=%d", status)
                        return tool_error("PROVIDER_ERROR", "Search provider is temporarily unavailable.")
                    payload = await response.json()
        except (asyncio.TimeoutError, aiohttp.ServerTimeoutError):
            logging.warning("Brave search failed: timeout")
            return tool_error("TIMEOUT", "Search request timed out.")
        except (aiohttp.ClientError, ValueError):
            logging.warning("Brave search failed: transport_or_response_error")
            return tool_error("PROVIDER_ERROR", "Search provider request failed.")

        invalid_response = "Search provider returned an invalid response."
        if not isinstance(payload, dict):
            return tool_error("PROVIDER_ERROR", invalid_response)
        web = payload.get("web")
        if web is not None and not isinstance(web, dict):
            return tool_error("PROVIDER_ERROR", invalid_response)
        items = web.get("results", []) if web is not None else []
        if not isinstance(items, list):
            return tool_error("PROVIDER_ERROR", invalid_response)

        results = []
        for item in items[:count]:
            if not isinstance(item, dict) or not all(
                isinstance(item.get(field), str) for field in ("title", "url")
            ):
                continue
            result = {"title": item["title"], "url": item["url"]}
            description = item.get("description")
            if isinstance(description, str) and description.strip():
                result["snippet"] = " ".join(description.split())[:MAX_SNIPPET_CHARS]
            page_date = item.get("page_age")
            if isinstance(page_date, str):
                page_date = page_date.strip()
                if 0 < len(page_date) <= MAX_PAGE_DATE_CHARS:
                    result["page_date"] = page_date
            results.append(result)
        if not results:
            logging.info("Brave search completed: results=0")
            return tool_error("NO_RESULTS", "No search results found.")
        logging.info("Brave search completed: results=%d", len(results))
        return json.dumps({"ok": True, "results": results}, ensure_ascii=False)
