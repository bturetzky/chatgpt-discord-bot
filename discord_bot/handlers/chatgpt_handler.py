"""OpenAI Responses API integration for the Discord bot."""
import asyncio
import json
import logging
import os
import time
from datetime import datetime

from openai import AsyncOpenAI, OpenAIError

from ..functions.react_to_message import ReactToMessage, ReplyReactions
from .function_handler import CONTEXT_TOOLS, FunctionHandler
from .personality_prompt import build_system_prompt
from .usage_metrics import ChatUsage

GPT_MODEL = os.getenv("OPENAI_MODEL", "gpt-6.1-terra")
MAX_FUNCTION_CALLS = 11
MAX_PAGE_READS = 2
MAX_WEBPAGE_CONTINUATIONS = 4
MAX_INVALID_YOUTUBE_CALLS = 3
YOUTUBE_CONTINUATION_TIMEOUT = 12


def combine_youtube_pages(first, second):
    """Keep first-page evidence and explicitly mark an unsuccessful continuation."""
    merged = dict(first)
    if not isinstance(second, dict) or not second.get("ok") or second.get("source") != "transcript":
        merged["limitations"] = list(first.get("limitations", [])) + [
            "The automatic continuation failed or timed out; only the returned caption range was read."
        ]
        return merged
    entries = list(first.get("transcript", []))
    shift = len(entries)
    entries.extend(second.get("transcript", []))
    merged["transcript"] = entries
    sections = list(first.get("sections", []))
    for section in second.get("sections", []):
        sections.append({**section, "first_segment": section["first_segment"] + shift,
                         "last_segment_exclusive": section["last_segment_exclusive"] + shift})
    merged["sections"] = sections
    merged["next_cursor"] = second.get("next_cursor")
    merged["content_truncated"] = bool(second.get("content_truncated"))
    return merged


class ChatGPTHandler:
    def __init__(self, openai_apikey, send_interim_message_callback=None):
        self.bot_mention = None
        self.client = AsyncOpenAI(api_key=openai_apikey)
        self.send_interim_message = send_interim_message_callback
        self.function_handler = FunctionHandler()

    def get_response_system_prompt_content(self, bot_mention):
        return build_system_prompt(bot_mention, datetime.now())

    async def get_response(self, messages, channel, discord_context=None, *, triggering_message=None):
        # Discord history and retrieved memories are already ordinary role/content
        # messages. Responses accepts these directly; legacy function-role messages
        # must never be constructed.
        conversation = list(messages)
        reactions = ReplyReactions.for_message(triggering_message)
        if reactions is not None:
            discord_context = {**(discord_context or {}), "reply_reactions": reactions}
        tools = [
            {"type": "function", **definition}
            for definition in self.function_handler.api_functions
            if definition["name"] != ReactToMessage.name or reactions is not None
        ]
        instructions = self.get_response_system_prompt_content(self.bot_mention)

        if reactions is not None:
            instructions += (
                " Occasionally use react_to_message for a funny, surprising, or wholesome message "
                "when a reaction feels natural. Skip routine messages and avoid reactions in serious "
                "or sensitive conversations. Always continue with the normal reply, even if the tool fails."
            )

        usage_metrics = ChatUsage(model=GPT_MODEL)
        started = time.monotonic()
        page_reads = 0
        webpage_continuations = 0
        valid_webpage_cursors = set()
        invalid_youtube_calls = 0
        progress_sent = False
        try:
            for attempt in range(MAX_FUNCTION_CALLS + 1):
                response = await self.client.responses.create(
                    model=GPT_MODEL,
                    instructions=instructions,
                    input=conversation,
                    tools=tools,
                    tool_choice="none" if attempt == MAX_FUNCTION_CALLS else "auto",
                )
                usage_metrics.add(getattr(response, "usage", None))
                # Retain all model output, including reasoning items and tool calls,
                # so subsequent tool results have the context they require.
                conversation.extend(
                    item.model_dump(exclude_none=True, mode="json")
                    for item in response.output
                )
                calls = [
                    item for item in response.output
                    if item.type == "function_call"
                ]
                if not calls:
                    reply = response.output_text or ""
                    if self.bot_mention:
                        reply = reply.replace(f"{self.bot_mention}: ", "")
                    return reply.strip() or "Sorry, I couldn't generate a response."

                for call in calls:
                    try:
                        arguments = json.loads(call.arguments)
                        if not isinstance(arguments, dict):
                            raise ValueError("Tool arguments must be an object")
                        update = arguments.get("quick_update")
                        if (not progress_sent and self.send_interim_message
                                and isinstance(update, str) and update.strip()
                                and call.name not in CONTEXT_TOOLS):
                            progress_sent = True
                            await self.send_interim_message(channel, update.strip())
                        is_webpage_continuation = (
                            call.name == "get_webpage_contents" and arguments.get("cursor") is not None
                        )
                        cursor_key = (arguments.get("url"), arguments.get("cursor"))
                        valid_continuation = (
                            is_webpage_continuation and isinstance(cursor_key[0], str)
                            and isinstance(cursor_key[1], str)
                            and cursor_key in valid_webpage_cursors
                        )
                        read_limit_reached = (
                            webpage_continuations >= MAX_WEBPAGE_CONTINUATIONS if valid_continuation
                            else page_reads >= MAX_PAGE_READS
                        )
                        if call.name == "read_youtube" and invalid_youtube_calls >= MAX_INVALID_YOUTUBE_CALLS:
                            result = json.dumps({"ok": False, "error": {"code": "VALIDATION_LIMIT", "message": "Too many invalid YouTube requests in this response."}})
                        elif call.name in ("get_webpage_contents", "read_youtube") and read_limit_reached:
                            result = json.dumps({"ok": False, "error": {"code": "READ_LIMIT", "message": "Page read limit reached for this response."}})
                        else:
                            if valid_continuation:
                                webpage_continuations += 1
                            elif call.name in ("get_webpage_contents", "read_youtube"):
                                page_reads += 1
                            result = await self.function_handler.execute_function(
                                call.name, arguments, context=discord_context
                            ) if call.name in CONTEXT_TOOLS else await self.function_handler.execute_function(
                                call.name, arguments
                            )
                            if call.name == "get_webpage_contents":
                                try:
                                    webpage_result = json.loads(result)
                                except (TypeError, ValueError):
                                    webpage_result = None
                                if isinstance(webpage_result, dict) and webpage_result.get("ok"):
                                    next_cursor = webpage_result.get("next_cursor")
                                    if isinstance(next_cursor, str) and next_cursor:
                                        valid_webpage_cursors.add((arguments.get("url"), next_cursor))
                            if call.name == "read_youtube":
                                try:
                                    parsed_result = json.loads(result)
                                except (TypeError, ValueError):
                                    parsed_result = None
                                error = parsed_result.get("error") if isinstance(parsed_result, dict) else None
                                if (isinstance(parsed_result, dict) and not parsed_result.get("ok")
                                        and isinstance(error, dict) and error.get("code") in ("INVALID_URL", "INVALID_ARGUMENT")):
                                    # These two errors are rejected before any fetch;
                                    # allow a bounded correction without spending a read.
                                    invalid_youtube_calls += 1
                                    page_reads -= 1
                            # An unscoped single-video request reads a second bounded
                            # page automatically. Targeted ranges and multi-tool calls
                            # retain their budget for the model's explicit choices.
                            if (call.name == "read_youtube" and len(calls) == 1 and page_reads < MAX_PAGE_READS
                                    and arguments.get("cursor") is None and arguments.get("end_seconds") is None
                                    and arguments.get("start_seconds") in (None, 0)):
                                try:
                                    first = json.loads(result)
                                except (TypeError, ValueError):
                                    first = None
                                if isinstance(first, dict) and first.get("ok") and first.get("next_cursor"):
                                    page_reads += 1
                                    try:
                                        followup = await asyncio.wait_for(
                                            self.function_handler.execute_function("read_youtube", {
                                                "url": arguments.get("url"), "cursor": first["next_cursor"]
                                            }), timeout=YOUTUBE_CONTINUATION_TIMEOUT)
                                        second = json.loads(followup)
                                    except (asyncio.TimeoutError, TypeError, ValueError):
                                        second = None
                                    result = json.dumps(combine_youtube_pages(first, second))
                    except (ValueError, json.JSONDecodeError) as exc:
                        result = f"Invalid tool arguments: {exc}"
                    conversation.append({
                        "type": "function_call_output",
                        "call_id": call.call_id,
                        "output": str(result),
                    })
            return "Sorry, I reached the limit for tool calls."
        except (OpenAIError, asyncio.TimeoutError) as exc:
            logging.warning('OpenAI request failed: error_type=%s', type(exc).__name__)
            return "Sorry, there was an error processing your request with OpenAI. Please try again later."
        finally:
            usage_metrics.log(elapsed_seconds=time.monotonic() - started)

    async def get_summary(self, messages):
        # Kept for compatibility with the currently disabled summary workflow.
        response = await self.client.responses.create(
            model=GPT_MODEL,
            instructions="Summarize this conversation concisely.",
            input=list(messages),
        )
        return response.output_text
