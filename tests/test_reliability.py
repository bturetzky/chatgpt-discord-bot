"""Reliability regressions for Discord routing and blocking integrations."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from discord_bot.handlers.discord_handler import DiscordHandler
from discord_bot.handlers.function_handler import FunctionHandler


def make_handler():
    handler = DiscordHandler.__new__(DiscordHandler)
    handler.client = MagicMock()
    handler.client.user = MagicMock()
    handler.client.user.mention = "<@bot>"
    handler.client.user.mentioned_in.return_value = True
    handler.client.close = AsyncMock()
    handler.shutdown_event = asyncio.Event()
    handler.vector_handler = MagicMock()
    handler.vector_handler.close = AsyncMock()
    handler.chatgpt_handler = MagicMock()
    handler.chatgpt_handler.bot_mention = None
    handler.chatgpt_handler.get_response = AsyncMock(return_value="Hello")
    handler.get_message_history = AsyncMock(return_value=[{"role": "user", "content": "hi"}])
    return handler


def make_message():
    channel = MagicMock()
    channel.send = AsyncMock()
    author = MagicMock()
    author.id = 123
    author.mention = "<@123>"
    author.display_name = "friend"
    return SimpleNamespace(author=author, channel=channel, guild=SimpleNamespace(id=5),
                           content="<@bot> hi", mention_everyone=False)


class DiscordReliabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_shutdown_closes_discord_and_vector_handler(self):
        handler = make_handler()
        await handler.shutdown()
        handler.client.close.assert_awaited_once()
        handler.vector_handler.close.assert_awaited_once()
        self.assertTrue(handler.shutdown_event.is_set())

    async def test_shutdown_closes_vector_handler_if_discord_close_fails(self):
        handler = make_handler()
        handler.client.close.side_effect = RuntimeError("disconnect")
        with self.assertRaises(RuntimeError):
            await handler.shutdown()
        handler.vector_handler.close.assert_awaited_once()

    async def test_history_failure_falls_back_to_current_message(self):
        handler, message = make_handler(), make_message()
        handler.get_message_history.side_effect = RuntimeError("history unavailable")
        handler.vector_handler.vector_store.fetch_context.return_value = []
        with patch("discord_bot.handlers.discord_handler.asyncio.sleep", new_callable=AsyncMock):
            await handler.process_message(message)
        sent_history = handler.chatgpt_handler.get_response.await_args.args[0]
        self.assertEqual(sent_history, [{"role": "user", "content": "friend (Discord ID 123): <@bot> hi"}])
        message.channel.send.assert_awaited()

    async def test_memory_failure_does_not_prevent_reply(self):
        handler, message = make_handler(), make_message()
        handler.vector_handler.vector_store.fetch_context.side_effect = RuntimeError("pinecone unavailable")
        with patch("discord_bot.handlers.discord_handler.asyncio.sleep", new_callable=AsyncMock):
            await handler.process_message(message)
        handler.chatgpt_handler.get_response.assert_awaited_once()
        message.channel.send.assert_awaited()

    async def test_none_memories_does_not_prevent_reply(self):
        handler, message = make_handler(), make_message()
        handler.vector_handler.vector_store.fetch_context.return_value = None
        with patch("discord_bot.handlers.discord_handler.asyncio.sleep", new_callable=AsyncMock):
            await handler.process_message(message)
        handler.chatgpt_handler.get_response.assert_awaited_once()


class ToolReliabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_timeout_returns_error_instead_of_raising(self):
        handler = FunctionHandler.__new__(FunctionHandler)
        async def slow_tool(_args):
            await asyncio.sleep(1)
        tool = MagicMock()
        tool.execute = slow_tool
        handler.functions = {"slow": lambda: tool}
        async def timeout(coro, timeout):
            coro.close()
            raise asyncio.TimeoutError()
        with patch("discord_bot.handlers.function_handler.asyncio.wait_for", side_effect=timeout):
            result = await handler.execute_function("slow", {})
        self.assertIn("error", result.lower())
