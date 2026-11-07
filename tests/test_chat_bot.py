"""Behavior tests for the current Discord handler (replaces obsolete chat_bot tests)."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from discord_bot.handlers.discord_handler import DiscordHandler
from tests.test_reliability import make_handler, make_message


class DiscordBehaviorTests(unittest.IsolatedAsyncioTestCase):
    async def test_ignores_unmentioned_guild_messages(self):
        handler, message = make_handler(), make_message()
        handler.client.user.mentioned_in.return_value = False
        await handler.process_message(message)
        handler.chatgpt_handler.get_response.assert_not_awaited()
        message.channel.send.assert_not_awaited()

    async def test_dm_does_not_require_mention(self):
        handler, message = make_handler(), make_message()
        message.guild = None
        handler.client.user.mentioned_in.return_value = False
        with patch("discord_bot.handlers.discord_handler.asyncio.sleep", new_callable=AsyncMock):
            await handler.process_message(message)
        handler.chatgpt_handler.get_response.assert_awaited_once()

    async def test_shutdown_event_prevents_new_requests(self):
        handler, message = make_handler(), make_message()
        handler.shutdown_event.set()
        await handler.process_message(message)
        handler.chatgpt_handler.get_response.assert_not_awaited()

    async def test_history_is_chronological_with_roles(self):
        handler = make_handler()
        author = SimpleNamespace(mention="<@123>")
        bot = handler.client.user
        older = SimpleNamespace(author=author, content="first")
        newer = SimpleNamespace(author=bot, content="second")
        channel = MagicMock()
        async def history():
            for message in (newer, older):
                yield message
        channel.history.return_value = history()
        result = await DiscordHandler.get_message_history(handler, channel, limit=3)
        self.assertEqual(result, [
            {"role": "user", "content": "<@123>: first"},
            {"role": "assistant", "content": f"{bot.mention}: second"},
        ])
        channel.history.assert_called_once_with(limit=3)

    async def test_history_respects_zero_limit(self):
        handler = make_handler()
        channel = MagicMock()
        async def history():
            yield SimpleNamespace(author=handler.client.user, content="ignored")
        channel.history.return_value = history()
        self.assertEqual(await DiscordHandler.get_message_history(handler, channel, limit=0), [])

    async def test_split_message_preserves_short_multiline_text(self):
        handler = make_handler()
        self.assertEqual(handler.split_message("hello\nworld"), ["hello\nworld\n"])

    async def test_split_message_chunks_at_line_boundary(self):
        handler = make_handler()
        self.assertEqual(handler.split_message("abc\ndef", limit=5), ["abc\n", "def\n"])


if __name__ == "__main__":
    unittest.main()
