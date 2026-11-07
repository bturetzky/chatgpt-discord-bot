"""OpenAI Responses API integration for the Discord bot."""
import asyncio
import json
import logging
import os
from datetime import datetime

from openai import AsyncOpenAI, OpenAIError

from .function_handler import FunctionHandler

GPT_MODEL = os.getenv("OPENAI_MODEL", "gpt-6.1-terra")
MAX_FUNCTION_CALLS = 11


class ChatGPTHandler:
    def __init__(self, openai_apikey, send_interim_message_callback=None):
        self.bot_mention = None
        self.client = AsyncOpenAI(api_key=openai_apikey)
        self.send_interim_message = send_interim_message_callback
        self.function_handler = FunctionHandler()

    def get_response_system_prompt_content(self, bot_mention):
        current_date_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return " ".join([
            f"Yo, you're {bot_mention}, the snazzy bro-bot in this Discord server.",
            "Remember, you're among friends here, so keep it real, keep it sassy.",
            f"Today's date and time is {current_date_time}.",
            "You have tools for searching, fetching content, and storing useful memories.",
            "Proactively use store_memory for durable facts, preferences, ongoing projects, plans and decisions useful in future conversations.",
            "Ordinary concrete facts can be worth remembering; retrieval ranks their relevance later. Do not wait for explicit remember requests.",
            "Store standalone specific statements identifying the person or project; avoid vague pronouns and duplicate writes in the same turn.",
            "Never store credentials or secrets.",
            "If something's unclear, ask.",
        ])

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

        try:
            for attempt in range(MAX_FUNCTION_CALLS + 1):
                response = await self.client.responses.create(
                    model=GPT_MODEL,
                    instructions=instructions,
                    input=conversation,
                    tools=tools,
                    tool_choice="none" if attempt == MAX_FUNCTION_CALLS else "auto",
                )
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

    async def get_summary(self, messages):
        # Kept for compatibility with the currently disabled summary workflow.
        response = await self.client.responses.create(
            model=GPT_MODEL,
            instructions="Summarize this conversation concisely.",
            input=list(messages),
        )
        return response.output_text
