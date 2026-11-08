"""Behavior tests for the current Discord handler (replaces obsolete chat_bot tests)."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from discord_bot.handlers.discord_handler import DiscordHandler
from tests.test_reliability import make_handler, make_message


class DiscordBehaviorTests(unittest.IsolatedAsyncioTestCase):
    def test_message_content_intent_is_explicitly_enabled(self):
        handler = DiscordHandler.__new__(DiscordHandler)
        intents = handler.get_discord_intents()
        self.assertTrue(intents.message_content)
        self.assertTrue(intents.messages)
        self.assertTrue(intents.guilds)

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

    async def test_everyone_mention_does_not_trigger_guild_reply(self):
        handler, message = make_handler(), make_message()
        message.mention_everyone = True
        await handler.process_message(message)
        handler.get_message_history.assert_not_awaited()
        handler.chatgpt_handler.get_response.assert_not_awaited()
        message.channel.send.assert_not_awaited()

    async def test_own_message_suppresses_embeds_without_replying(self):
        handler, message = make_handler(), make_message()
        message.author = handler.client.user
        message.edit = AsyncMock()
        with patch("discord_bot.handlers.discord_handler.asyncio.sleep", new_callable=AsyncMock):
            await handler.process_message(message)
        message.edit.assert_awaited_once_with(suppress=True)
        handler.chatgpt_handler.get_response.assert_not_awaited()
        message.channel.send.assert_not_awaited()

    async def test_response_failure_sends_fallback_message(self):
        handler, message = make_handler(), make_message()
        handler.chatgpt_handler.get_response.side_effect = RuntimeError("unavailable")
        await handler.process_message(message)
        message.channel.send.assert_awaited_once_with(
            "friend Sorry, there was an error processing your request. Please try again later."
        )

    async def test_long_response_is_sent_in_order(self):
        handler, message = make_handler(), make_message()
        first_line = "a" * 1000
        second_line = "b" * 1000
        handler.chatgpt_handler.get_response.return_value = f"chatgpt: {first_line}\n{second_line}"
        with patch("discord_bot.handlers.discord_handler.asyncio.sleep", new_callable=AsyncMock):
            await handler.process_message(message)
        self.assertEqual(
            [call.args[0] for call in message.channel.send.await_args_list],
            [first_line + "\n", second_line + "\n"],
        )

    async def test_shutdown_event_prevents_new_requests(self):
        handler, message = make_handler(), make_message()
        handler.shutdown_event.set()
        await handler.process_message(message)
        handler.chatgpt_handler.get_response.assert_not_awaited()

    async def test_history_is_chronological_with_roles(self):
        handler = make_handler()
        author = SimpleNamespace(mention="<@123>", id=123, display_name="Alice")
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
            {"role": "user", "content": "Alice (Discord ID 123): first"},
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
