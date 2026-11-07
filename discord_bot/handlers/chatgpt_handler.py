"""OpenAI Responses API integration for the Discord bot."""
import asyncio
import json
import logging
import os
import time
from datetime import datetime

from openai import AsyncOpenAI, OpenAIError

from .function_handler import FunctionHandler
from .personality_prompt import build_system_prompt
from .usage_metrics import ChatUsage

GPT_MODEL = os.getenv("OPENAI_MODEL", "gpt-6.1-terra")
MAX_FUNCTION_CALLS = 11


class ChatGPTHandler:
    def __init__(self, openai_apikey, send_interim_message_callback=None):
        self.bot_mention = None
        self.client = AsyncOpenAI(api_key=openai_apikey)
        self.send_interim_message = send_interim_message_callback
        self.function_handler = FunctionHandler()

    def get_response_system_prompt_content(self, bot_mention):
        return build_system_prompt(bot_mention, datetime.now())

    async def get_response(self, messages, channel):
        # Discord history and retrieved memories are already ordinary role/content
        # messages. Responses accepts these directly; legacy function-role messages
        # must never be constructed.
        conversation = list(messages)
        tools = [
            {"type": "function", **definition}
            for definition in self.function_handler.api_functions
        ]
        instructions = self.get_response_system_prompt_content(self.bot_mention)

        usage_metrics = ChatUsage(model=GPT_MODEL)
        started = time.monotonic()
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
                        if arguments.get("quick_update") and self.send_interim_message:
                            await self.send_interim_message(channel, arguments["quick_update"])
                        result = await self.function_handler.execute_function(call.name, arguments)
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
