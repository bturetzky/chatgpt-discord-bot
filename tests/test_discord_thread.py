import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from discord_bot.functions.discord_thread_function import LIVE_REQUEST_LIMIT, MESSAGE_LIMIT
from discord_bot.handlers.function_handler import FunctionHandler
from discord_bot.handlers.tool_output import bound_tool_output
from discord_bot.storage import Database
from discord_bot.storage.message_archive import MessageArchive


class DiscordThreadTests(IsolatedAsyncioTestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.archive = MessageArchive(self.enterContext(Database(str(Path(directory) / "archive.db"))))
        self.requester, self.bot = SimpleNamespace(id=5), SimpleNamespace(id=6)
        self.channels = {}
        self.guild = SimpleNamespace(
            id=1, me=self.bot, get_channel_or_thread=self.channels.get,
            get_member=lambda _: None, fetch_channel=AsyncMock(),
        )
        self.text = self.channel(10)
        self.context = {"guild": self.guild, "member": self.requester, "archive": self.archive}
        with patch("discord_bot.functions.memory_function.VectorHandler"):
            self.handler = FunctionHandler()

    def channel(self, channel_id, cls=discord.TextChannel):
        channel = MagicMock(spec=cls)
        channel.id, channel.guild, channel.parent = channel_id, self.guild, None
        channel.permissions_for.side_effect = lambda _: SimpleNamespace(
            view_channel=True, read_message_history=True, manage_threads=False,
        )
        self.channels[channel_id] = channel
        return channel

    def message(self, message_id, parent=None, *, channel=None, archive=True, content=None):
        channel = self.text if channel is None else channel
        reference = None if parent is None else SimpleNamespace(
            guild_id=1, channel_id=parent[0], message_id=parent[1],
        )
        message = SimpleNamespace(
            id=message_id, guild=self.guild, channel=channel,
            author=SimpleNamespace(id=7, display_name="Author"),
            created_at=datetime.now(timezone.utc), edited_at=None,
            content=content if content is not None else f"message {message_id}",
            type=discord.MessageType.reply if parent else discord.MessageType.default,
            reference=reference,
        )
        if archive:
            self.archive.upsert(message)
        return message

    async def read(self, anchor_id=100, **args):
        raw = await self.handler.execute_function(
            "get_discord_thread", json.dumps(args or {"channel_id": "10", "message_id": str(anchor_id)}),
            self.context,
        )
        self.assertEqual(bound_tool_output("get_discord_thread", raw), raw)
        return json.loads(raw)

    @staticmethod
    def ids(result):
        return [message["message_id"] for message in result["messages"]]

    async def test_reply_chain_includes_sibling_branch_and_excludes_adjacent_messages(self):
        self.message(100)
        self.message(101)
        self.message(102, (10, 100))
        self.message(103, (10, 100))
        self.message(104, (10, 103))
        result = await self.read(102)
        self.assertEqual(self.ids(result), ["100", "102", "103", "104"])
        self.assertEqual(result["messages"][-1]["reply_to"], {"channel_id": "10", "message_id": "103"})
        self.assertEqual(result["messages"][-1]["url"], "https://discord.com/channels/1/10/104")
        self.assertFalse(result["coverage"]["complete"])
        self.text.fetch_message.assert_not_awaited()
        self.text.history.assert_not_called()

    async def test_legacy_anchor_uses_live_reference_and_archive_content(self):
        self.message(99)
        self.message(100)
        self.archive.db.execute("UPDATE messages SET reply_message_id=NULL WHERE message_id='100'")
        self.text.fetch_message.return_value = self.message(
            100, (10, 99), archive=False, content="live text",
        )
        result = await self.read(message_url="https://discord.com/channels/1/10/100")
        self.assertEqual(self.ids(result), ["99", "100"])
        self.assertEqual(result["messages"][-1]["content"], "message 100")
        self.text.fetch_message.assert_awaited_once_with(100)

    async def test_serialized_anchor_and_conflicting_native_target(self):
        self.message(100)
        result = await self.read(channel_id=10, message_id=100, message_url=None, thread_id="")
        self.assertEqual(self.ids(result), ["100"])
        result = await self.read(channel_id=10, message_id=100, thread_id=20)
        self.assertIn("Conflicting fields", result["error"]["message"])
        result = await self.read(thread_id=True)
        self.assertIn("Malformed thread_id", result["error"]["message"])

    async def test_missing_and_deleted_parent(self):
        self.message(100, (10, 99))
        self.text.fetch_message.side_effect = discord.NotFound(
            SimpleNamespace(status=404, reason="Not Found"), "missing",
        )
        for tombstone in (False, True):
            with self.subTest(tombstone=tombstone):
                if tombstone:
                    self.archive.delete(99)
                    self.text.fetch_message.reset_mock()
                result = await self.read()
                self.assertEqual(self.ids(result), ["100"])
                self.assertIn("missing_or_deleted", result["coverage"]["issues"])
                self.assertIsNone(result["messages"][0]["reply_to"])
        self.text.fetch_message.assert_not_awaited()

    async def test_cross_channel_permissions_hide_parents_and_branches_for_each_principal(self):
        hidden = self.channel(11)
        self.message(99, channel=hidden)
        self.message(100, (11, 99))
        self.message(101, (10, 100), channel=hidden)
        for denied in (self.requester, self.bot):
            hidden.permissions_for.side_effect = lambda member: SimpleNamespace(
                view_channel=True, read_message_history=member is not denied,
            )
            result = await self.read()
            self.assertEqual(self.ids(result), ["100"])
            self.assertIsNone(result["messages"][0]["reply_to"])
            self.assertIn("inaccessible", result["coverage"]["issues"])
            self.assertNotIn("message 99", json.dumps(result))
        hidden.fetch_message.assert_not_awaited()

    async def test_cycles_are_reported_and_messages_are_unique(self):
        self.message(100, (10, 101))
        self.message(101, (10, 100))
        result = await self.read()
        self.assertCountEqual(self.ids(result), ["100", "101"])
        self.assertIn("reply_cycle", result["coverage"]["issues"])
        self.assertIsNone(result["messages"][0]["reply_to"])

    async def test_message_and_live_request_limits(self):
        self.message(100)
        for index in range(MESSAGE_LIMIT + 1):
            self.message(101 + index, (10, 100), content=chr(0) * 2000)
        result = await self.read()
        self.assertEqual(len(result["messages"]), MESSAGE_LIMIT)
        self.assertIn("message_limit", result["coverage"]["issues"])

        self.text.fetch_message.side_effect = lambda mid: self.message(mid, (10, mid - 1), archive=False)
        result = await self.read(500)
        self.assertEqual(self.text.fetch_message.await_count, LIVE_REQUEST_LIMIT)
        self.assertIn("live_fetch_limit", result["coverage"]["issues"])

    async def test_native_thread_membership_and_private_access(self):
        thread = self.channel(20, discord.Thread)
        thread.parent = self.text
        thread.is_private.return_value = False
        live = [self.message(202, (20, 200), channel=thread), self.message(201, channel=thread),
                self.message(200, channel=thread)]

        async def history(**_):
            for message in live:
                yield message

        thread.history.side_effect = history
        result = await self.read(thread_id=20, message_url="", channel_id=None, message_id=" ")
        self.assertTrue(result["coverage"]["complete"])
        self.assertEqual(self.ids(result), ["200", "201", "202"])
        self.assertIsNone(result["messages"][1]["reply_to"])
        self.assertEqual(result["messages"][2]["reply_to"]["message_id"], "200")
        thread.history.assert_called_once_with(limit=MESSAGE_LIMIT + 1, oldest_first=False)
        self.text.history.assert_not_called()

        result = await self.read(channel_id="20", message_id="200")
        self.assertIn("thread_window", result["coverage"]["issues"])
        thread.history.reset_mock()
        thread.is_private.return_value = True
        for bot_joined, requester_joined in ((True, False), (False, True)):
            async def membership(member_id):
                joined = bot_joined if member_id == self.bot.id else requester_joined
                if not joined:
                    raise discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "missing")
                return object()

            thread.fetch_member.side_effect = membership
            result = await self.read(thread_id="20")
            self.assertEqual(result["error"]["code"], "THREAD_INACCESSIBLE")
        thread.history.assert_not_called()
        thread.fetch_member.side_effect = None
        thread.fetch_member.return_value = object()
        result = await self.read(thread_id="20")
        self.assertEqual(self.ids(result), ["200", "201", "202"])

    async def test_permission_revoked_during_parent_fetch_disconnects_branch(self):
        other = self.channel(11)
        self.message(100, (11, 99))
        self.message(101, (11, 99), channel=other)
        self.message(99, channel=other)
        self.archive.db.execute("UPDATE messages SET reply_message_id=NULL WHERE message_id='99'")

        async def revoke(_):
            other.permissions_for.return_value = SimpleNamespace(
                view_channel=False, read_message_history=False,
            )
            other.permissions_for.side_effect = None
            return self.message(99, channel=other, archive=False)

        other.fetch_message.side_effect = revoke
        result = await self.read()
        self.assertEqual(self.ids(result), ["100"])
        self.assertIn("inaccessible", result["coverage"]["issues"])
        self.assertIsNone(result["messages"][0]["reply_to"])
