"""Focused tests for Responses API conversation and tool-call handling."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from discord_bot.handlers.chatgpt_handler import ChatGPTHandler
from discord_bot.handlers.function_handler import FunctionHandler


def text_response(text):
    return SimpleNamespace(
        output=[SimpleNamespace(type="message")],
        output_text=text,
    )


class ResponsesTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        with patch("discord_bot.handlers.chatgpt_handler.FunctionHandler"):
            self.handler = ChatGPTHandler("test-key")
        self.handler.bot_mention = "<@123>"
        self.handler.client = MagicMock()
        self.handler.client.responses.create = AsyncMock()

    async def test_plain_reply_preserves_input_history(self):
        self.handler.client.responses.create.return_value = text_response("Hello!")
        history = [{"role": "user", "content": "hi"}]
        result = await self.handler.get_response(history, None)
        self.assertEqual(result, "Hello!")
        self.assertEqual(history, [{"role": "user", "content": "hi"}])
        kwargs = self.handler.client.responses.create.await_args.kwargs
        self.assertEqual(kwargs["model"], "gpt-6.1-terra")
        self.assertEqual(kwargs["input"][0], history[0])

    async def test_tool_round_trip_uses_call_id(self):
        call = SimpleNamespace(
            type="function_call", call_id="call-123",
            name="get_weather", arguments=json.dumps({"city": "Seattle"}),
        )
        self.handler.client.responses.create.side_effect = [
            SimpleNamespace(output=[call], output_text=""),
            text_response("It's raining."),
        ]
        self.handler.function_handler.api_functions = [
            {"name": "get_weather", "description": "Weather", "parameters": {"type": "object"}}
        ]
        self.handler.function_handler.execute_function = AsyncMock(return_value="Rain")
        result = await self.handler.get_response([{"role": "user", "content": "weather?"}], None)
        self.assertEqual(result, "It's raining.")
        self.handler.function_handler.execute_function.assert_awaited_once_with(
            "get_weather", {"city": "Seattle"}
        )
        second_input = self.handler.client.responses.create.await_args.kwargs["input"]
        self.assertEqual(second_input[-1], {
            "type": "function_call_output", "call_id": "call-123", "output": "Rain"
        })

    async def test_function_handler_awaits_coroutines(self):
        handler = FunctionHandler.__new__(FunctionHandler)
        function = MagicMock()
        function.execute = AsyncMock(return_value="ok")
        handler.functions = {"test": lambda: function}
        self.assertEqual(await handler.execute_function("test", {}), "ok")
        function.execute.assert_awaited_once_with({})
