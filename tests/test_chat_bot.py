import asyncio
import imp
import os
import sys
from unittest import TestCase
from unittest.mock import AsyncMock, MagicMock, patch

# NOTE: This is the most straightforward way to patch an env that is
# required at import time. If more of the global variables moved into
# main, that would solve this hackery.
os.environ["DISCORD_TOKEN"] = "potato"
os.environ["OPENAI_API_KEY"] = "banana"

# NOTE: It's just so much easier to update the system modules for a
# global async, especially when it lives in a mutated instance of
# discord.client. Eventually, once this is scope at main or lower,
# this hack can go away.
aiosqlite = AsyncMock()
sys.modules["aiosqlite"] = aiosqlite

import chat_bot


class MockChannel:
    def __init__(self):
        self.end = 1
        self.start = 0

    def __aiter__(self):
        return self

    def history(self, limit):
        return self

    async def __anext__(self):
        if self.start >= self.end:
            raise StopAsyncIteration
        else:
            self.start += 1
            mock_author = MagicMock(display_name="foo")
            mock_message = MagicMock(author=mock_author)
            return mock_message


class TestChatBot(TestCase):
    def setUp(self):
        def kill_patches():
            patch.stopall()
            imp.reload(chat_bot)

        self.addCleanup(kill_patches)
        patch.object(chat_bot.discord.Client, "start", autospec=True).start()
        patch.object(chat_bot.discord.Client, "user", autospec=True).start()
        patch.object(chat_bot.discord.Client, "close", autospec=True).start()
        patch("openai.ChatCompletion", MagicMock()).start()
        imp.reload(chat_bot)

    def test_stub(self):
        pass

    def test_main_interrupted(self):
        with patch("discord.Client.start", side_effect=KeyboardInterrupt):
            with patch("chat_bot.print"):
                with patch("chat_bot.shutdown", AsyncMock()):
                    asyncio.run(chat_bot.main())

    def test_main(self):
        with patch("chat_bot.shutdown", AsyncMock()):
            asyncio.run(chat_bot.main())

    def test_shutdown(self):
        with patch("chat_bot.print"):
            asyncio.run(chat_bot.shutdown())

    def test_chatgpt_response_raises_exception(self):
        messages = MagicMock()
        guild_id = "123"
        with patch("openai.ChatCompletion.create", side_effect=Exception):
            with patch("chat_bot.get_summary"):
                with patch("chat_bot.print"):
                    asyncio.run(chat_bot.chatgpt_response(messages, guild_id))

    def test_chatgpt_response(self):
        messages = MagicMock()
        guild_id = "123"
        with patch("chat_bot.get_summary"):
            with patch("chat_bot.print"):
                asyncio.run(chat_bot.chatgpt_response(messages, guild_id))

    def test_get_message_history_limit_three(self):
        channel = MockChannel()
        limit = 3
        asyncio.run(chat_bot.get_message_history(channel, limit))

    def test_get_message_history_limit_zero(self):
        channel = MockChannel()
        limit = 0
        asyncio.run(chat_bot.get_message_history(channel, limit))

    def test_on_ready(self):
        with patch("chat_bot.print"):
            asyncio.run(chat_bot.on_ready())

    def test_on_message_and_everyone_is_false_timeout(self):
        mock_channel = MagicMock()
        mock_channel.send = AsyncMock()
        message = MagicMock(
            mention_everyone=False,
            channel=mock_channel,
            guild=None,
        )
        with patch("discord.Client.user.mentioned_in", return_value=True):
            with patch("chat_bot.print"):
                with patch("chat_bot.get_summary"):
                    with patch("chat_bot.get_message_history"):
                        with patch(
                            "chat_bot.chatgpt_response",
                            side_effect=asyncio.TimeoutError,
                        ):
                            asyncio.run(chat_bot.on_message(message))

    def test_on_message_and_everyone_is_false(self):
        mock_channel = MagicMock()
        mock_channel.send = AsyncMock()
        message = MagicMock(
            mention_everyone=False,
            channel=mock_channel,
            guild=None,
        )
        with patch("chat_bot.discord.Client.user.mentioned_in", return_value=True):
            with patch("chat_bot.print"):
                with patch("chat_bot.get_summary"):
                    with patch("chat_bot.get_message_history"):
                        with patch("chat_bot.chatgpt_response", return_value=""):
                            asyncio.run(chat_bot.on_message(message))

    def test_on_message_shutdown_event(self):
        message = MagicMock()
        with patch("chat_bot.shutdown_event"):
            asyncio.run(chat_bot.on_message(message))

    def test_on_message(self):
        message = MagicMock()
        with patch("discord.Client.user.mentioned_in", return_value=True):
            asyncio.run(chat_bot.on_message(message))

    def test_get_summary_prompt_content(self):
        bot_mention = "foo"
        result = chat_bot.get_summary_prompt_content(bot_mention)
        self.assertTrue(result)
        self.assertTrue(type(result) is str, type(result))

    def test_get_response_system_prompt_content(self):
        bot_mention = "foo"
        result = chat_bot.get_response_system_prompt_content(bot_mention)
        self.assertTrue(result)
        self.assertTrue(type(result) is str, type(result))

    def test_get_response_priming_prompt_content(self):
        bot_mention = "foo"
        result = chat_bot.get_response_priming_prompt_content(bot_mention)
        self.assertTrue(result)
        self.assertTrue(type(result) is str, type(result))
