import asyncio
import json
from itertools import count
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord

from discord_bot.functions.react_to_message import ReactToMessage, ReplyReactions
from discord_bot.handlers.chatgpt_handler import ChatGPTHandler
from tests.test_responses_api import OutputItem, text_response


class ReplyReactionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.call_ids = count()
        self.custom = SimpleNamespace(name="party_blob", is_usable=Mock(return_value=True))
        self.guild = SimpleNamespace(emojis=[self.custom], get_emoji=Mock(return_value=self.custom))
        self.message = SimpleNamespace(
            guild=self.guild, author=SimpleNamespace(bot=False), webhook_id=None,
            add_reaction=AsyncMock(),
        )
        with patch("discord_bot.functions.memory_function.VectorHandler"):
            self.handler = ChatGPTHandler("test-key", AsyncMock())
        self.handler.client.responses.create = AsyncMock()
        self.context = {"reply_reactions": ReplyReactions.for_message(self.message)}

    async def react(self, **arguments):
        result = await self.handler.function_handler.execute_function(
            "react_to_message", arguments, context=self.context,
        )
        return json.loads(result)

    def model_calls(self, *arguments):
        return SimpleNamespace(output=[
            OutputItem(type="function_call", call_id=f"call-{next(self.call_ids)}", name="react_to_message",
                       arguments=json.dumps(args))
            for args in arguments
        ], output_text="")

    async def test_unicode_reaction_limit_across_batches(self):
        self.handler.client.responses.create.side_effect = [
            self.model_calls({"emoji": "😂"}, {"emoji": "💀"}),
            self.model_calls({"emoji": "👍"}),
            text_response("That was funny."),
        ]
        result = await self.handler.get_response([], None, triggering_message=self.message)
        self.assertEqual(result, "That was funny.")
        self.message.add_reaction.assert_awaited_once_with("😂")
        self.handler.send_interim_message.assert_not_awaited()
        outputs = [json.loads(item["output"]) for item in
                   self.handler.client.responses.create.await_args.kwargs["input"]
                   if item["type"] == "function_call_output"]
        self.assertEqual([item.get("error", {}).get("code") for item in outputs],
                         [None, "reaction_limit", "reaction_limit"])

    async def test_custom_guild_emoji(self):
        for value in ("<a:party_blob:123>", ":party_blob:"):
            with self.subTest(value=value):
                self.context["reply_reactions"] = ReplyReactions.for_message(self.message)
                self.message.add_reaction.reset_mock()
                self.assertEqual(await self.react(emoji=value), {"ok": True})
                self.message.add_reaction.assert_awaited_once_with(self.custom)
        self.guild.get_emoji.assert_called_once_with(123)

    async def test_model_can_skip_reaction(self):
        create = self.handler.client.responses.create
        create.return_value = text_response("Paris.")
        self.assertEqual(await self.handler.get_response([], None, triggering_message=self.message),
                         "Paris.")
        self.assertIn("react_to_message", {tool["name"] for tool in create.await_args.kwargs["tools"]})
        create.assert_awaited_once()
        self.message.add_reaction.assert_not_awaited()

    async def test_concurrent_calls_share_allowance(self):
        async def post(_):
            await asyncio.sleep(0)

        self.message.add_reaction.side_effect = post
        results = await asyncio.gather(self.react(emoji="❤️"), self.react(emoji="🤦"))
        self.assertEqual(sum(item["ok"] for item in results), 1)
        self.message.add_reaction.assert_awaited_once()

    async def test_invalid_and_unavailable_emoji(self):
        self.guild.get_emoji.return_value = None
        self.custom.is_usable.return_value = False
        for value in ("hello", "😂😂", "<:external:123>", ":party_blob:"):
            with self.subTest(value=value):
                self.assertEqual((await self.react(emoji=value))["error"]["code"], "emoji_unavailable")
        self.message.add_reaction.assert_not_awaited()

    async def test_discord_failures_leave_allowance_available(self):
        for kind, status, expected in (
            (discord.Forbidden, 403, "forbidden"),
            (discord.NotFound, 404, "message_or_emoji_unavailable"),
            (discord.HTTPException, 500, "discord_api_error"),
        ):
            with self.subTest(status=status):
                self.message.add_reaction.side_effect = kind(
                    SimpleNamespace(status=status, reason="test"), "test",
                )
                self.assertEqual((await self.react(emoji="👍"))["error"]["code"], expected)
        self.message.add_reaction.side_effect = None
        self.assertEqual(await self.react(emoji="👍"), {"ok": True})

    async def test_ineligible_trigger_hides_tool_and_prevents_post(self):
        for message in (None, SimpleNamespace(guild=None),
                        SimpleNamespace(guild=self.guild, author=SimpleNamespace(bot=True)),
                        SimpleNamespace(guild=self.guild, author=SimpleNamespace(bot=False), webhook_id=123)):
            with self.subTest(message=message):
                create = self.handler.client.responses.create
                create.side_effect = [self.model_calls({"emoji": "👍"}), text_response("Answer.")]
                self.assertEqual(await self.handler.get_response([], None, triggering_message=message),
                                 "Answer.")
                self.assertNotIn("react_to_message", {
                    tool["name"] for tool in create.await_args.kwargs["tools"]
                })
                self.assertEqual(json.loads(create.await_args.kwargs["input"][-2]["output"])["error"]["code"],
                                 "message_unavailable")
        self.message.add_reaction.assert_not_awaited()

    async def test_failed_reaction_preserves_answer_and_stays_silent(self):
        self.message.add_reaction.side_effect = discord.Forbidden(
            SimpleNamespace(status=403, reason="test"), "test",
        )
        create = self.handler.client.responses.create
        create.side_effect = [
            self.model_calls({"emoji": "😂", "quick_update": "Reacting"}, {"emoji": "😂"}),
            text_response("Answer."),
        ]
        self.assertEqual(await self.handler.get_response([], None, triggering_message=self.message),
                         "Answer.")
        self.handler.send_interim_message.assert_not_awaited()
        self.message.add_reaction.assert_awaited_once_with("😂")

    async def test_schema_and_execution_reject_target_arguments(self):
        schema = ReactToMessage.get_parameters()
        self.assertEqual(set(schema["properties"]), {"emoji"})
        self.assertEqual(schema["required"], ["emoji"])
        self.assertFalse(schema["additionalProperties"])
        for field in ("message_id", "channel_id", "guild_id"):
            self.assertEqual((await self.react(emoji="👍", **{field: "123"}))["error"]["code"],
                             "invalid_arguments")
        self.message.add_reaction.assert_not_awaited()
