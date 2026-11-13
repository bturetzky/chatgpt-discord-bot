import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord

from discord_bot.functions.discord_message_function import parse_message_target
from discord_bot.handlers.function_handler import FunctionHandler
from discord_bot.handlers.tool_output import bound_tool_output
from discord_bot.storage import Database
from discord_bot.storage.message_archive import MessageArchive


class DiscordMessageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        database = self.enterContext(Database(str(Path(directory) / "test.db")))
        self.archive = MessageArchive(database)
        self.member, self.bot = object(), object()
        self.permissions = {
            who: SimpleNamespace(view_channel=True, read_message_history=True)
            for who in (self.member, self.bot)
        }
        self.live = SimpleNamespace(
            author=SimpleNamespace(id=7, display_name="Live Author"),
            content="live text", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            attachments=[], reactions=[], reference=None,
        )
        self.channel = SimpleNamespace(
            id=10, permissions_for=self.permissions.__getitem__,
            fetch_message=AsyncMock(return_value=self.live),
        )
        self.members = {}
        self.guild = SimpleNamespace(
            id=1, me=self.bot, text_channels=[self.channel],
            get_channel={10: self.channel}.get, get_member=self.members.get,
        )
        self.context = {"guild": self.guild, "member": self.member, "archive": self.archive}
        with patch("discord_bot.functions.memory_function.VectorHandler"):
            self.handler = FunctionHandler()

    async def lookup(self, args=None, *, include_metadata=False):
        return json.loads(await self.handler.execute_function(
            "get_discord_message", args if args is not None else {
                "channel_id": "10", "message_id": "100", "include_metadata": include_metadata,
            },
            self.context,
        ))

    def archive_message(self, *, guild_id="1", channel_id="10"):
        self.archive.db.execute(
            "INSERT INTO messages(guild_id,channel_id,message_id,author_id,content,created_at) "
            "VALUES (?,?,?,?,?,?)",
            (guild_id, channel_id, "100", "7", "archived text", "2026-01-01T00:00:00+00:00"),
        )

    def test_message_urls(self):
        for host in ("discord.com", "canary.discord.com", "ptb.discord.com", "discordapp.com"):
            with self.subTest(host=host):
                self.assertEqual(parse_message_target(
                    {"message_url": f"<https://{host}/channels/1/10/100>"}), ("1", "10", "100"))

    async def test_invalid_targets(self):
        for args in (
            {}, {"channel_id": "10", "message_id": "0"}, {"channel_id": "10", "message_id": True},
            {"channel_id": "10", "message_id": "١"}, {"channel_id": "10", "message_id": "01"},
            {"channel_id": "10", "message_id": str(2**64)},
            {"message_url": "https://discord.com.evil.test/channels/1/10/100"},
            {"message_url": "https://discord.com/channels/@me/10/100"},
            {"message_url": "https://discord.com/channels/1/10/100", "channel_id": "10"},
        ):
            with self.subTest(args=args):
                self.assertEqual((await self.lookup(args))["error"]["code"], "INVALID_ARGUMENT")
        self.channel.fetch_message.assert_not_awaited()

    async def test_guild_and_channel_isolation(self):
        self.archive_message(guild_id="2")
        result = await self.lookup({"message_url": "https://discord.com/channels/2/10/100"})
        self.assertEqual(result["error"]["code"], "MESSAGE_INACCESSIBLE")
        result = await self.lookup({"channel_id": "11", "message_id": "100"})
        self.assertEqual(result["error"]["code"], "MESSAGE_INACCESSIBLE")
        self.channel.fetch_message.assert_not_awaited()
        self.assertEqual((await self.lookup())["message"]["content"], "live text")

    async def test_permissions_for_both_members(self):
        self.archive_message()
        for who in (self.member, self.bot):
            for permission in ("view_channel", "read_message_history"):
                setattr(self.permissions[who], permission, False)
                self.assertEqual((await self.lookup())["error"]["code"], "MESSAGE_INACCESSIBLE")
                setattr(self.permissions[who], permission, True)
        self.channel.fetch_message.assert_not_awaited()

    async def test_deletion_markers(self):
        self.archive.delete(100)
        self.assertEqual((await self.lookup())["error"]["code"], "MESSAGE_UNAVAILABLE")
        self.archive_message()
        self.archive.db.execute("DELETE FROM deleted_message_ids")
        self.archive.db.execute("UPDATE messages SET deleted_at=CURRENT_TIMESTAMP")
        self.assertEqual((await self.lookup())["error"]["code"], "MESSAGE_UNAVAILABLE")
        self.channel.fetch_message.assert_not_awaited()

    async def test_deletion_during_fetch(self):
        async def delete_before_return(message_id):
            self.archive.delete(message_id)
            return self.live

        self.channel.fetch_message.side_effect = delete_before_return
        self.assertEqual((await self.lookup())["error"]["code"], "MESSAGE_UNAVAILABLE")

    async def test_archive_hit_without_metadata_skips_discord(self):
        self.archive_message()
        self.members[7] = SimpleNamespace(display_name="Cached Author")
        result = (await self.lookup())["message"]
        self.assertEqual(result["content"], "archived text")
        self.assertEqual(result["author_display_name"], "Cached Author")
        self.assertIsNone(result["metadata"])
        self.channel.fetch_message.assert_not_awaited()

    async def test_archive_hit_and_live_metadata(self):
        self.archive_message()
        self.members[7] = SimpleNamespace(display_name="Cached Author")
        self.live.reference = SimpleNamespace(guild_id=1, channel_id=10, message_id=99)
        result = (await self.lookup(include_metadata=True))["message"]
        self.assertEqual(result["content"], "archived text")
        self.assertEqual(result["created_at"], "2026-01-01T00:00:00+00:00")
        self.assertEqual(result["url"], "https://discord.com/channels/1/10/100")
        self.assertEqual(result["author_id"], "7")
        self.assertEqual(result["author_display_name"], "Cached Author")
        self.assertEqual(result["metadata"]["reply_to"]["url"], "https://discord.com/channels/1/10/99")
        self.channel.fetch_message.assert_awaited_once_with(100)

    async def test_live_fallback_and_metadata_limits(self):
        self.live.content = "x" * 5000
        self.live.attachments = [SimpleNamespace(
            filename="a" * 300, content_type=None, size=15, url="https://cdn.discordapp.com/a",
        )] * 12
        self.live.reactions = [SimpleNamespace(emoji="👍", count=2)] * 12
        self.live.reference = SimpleNamespace(guild_id=2, channel_id=10, message_id=99)
        result = (await self.lookup())["message"]
        self.assertEqual(result["author_display_name"], "Live Author")
        self.assertEqual(result["created_at"], "2026-01-01T00:00:00.000000+00:00")
        self.assertEqual(len(result["content"]), 4000)
        self.assertTrue(result["content_truncated"])
        metadata = result["metadata"]
        self.assertEqual(len(metadata["attachments"]), 10)
        self.assertEqual(len(metadata["attachments"][0]["filename"]), 256)
        self.assertEqual(len(metadata["reactions"]), 10)
        self.assertEqual(metadata["reactions"][0], {"emoji": "👍", "count": 2})
        self.assertTrue(metadata["attachments_truncated"])
        self.assertTrue(metadata["reactions_truncated"])
        self.assertIsNone(metadata["reply_to"])

    async def test_permissions_rechecked_after_fetch(self):
        async def revoke_before_return(_message_id):
            self.permissions[self.member].view_channel = False
            return self.live

        self.archive_message()
        self.channel.fetch_message.side_effect = revoke_before_return
        self.assertEqual((await self.lookup(include_metadata=True))["error"]["code"], "MESSAGE_INACCESSIBLE")

    async def test_json_escaping_keeps_result_within_tool_budget(self):
        self.live.content = chr(0) * 4000
        self.live.attachments = [SimpleNamespace(
            filename=chr(0) * 256, content_type=None, size=15, url="https://cdn.discordapp.com/a",
        )] * 10
        raw = await self.handler.execute_function(
            "get_discord_message", {"channel_id": "10", "message_id": "100"}, self.context,
        )
        self.assertEqual(bound_tool_output("get_discord_message", raw), raw)
        self.assertTrue(json.loads(raw)["message"]["content_truncated"])

    async def test_fetch_failures(self):
        self.channel.fetch_message.side_effect = discord.HTTPException(
            SimpleNamespace(status=503, reason="Service unavailable"), "private provider error")
        result = await self.lookup(include_metadata=True)
        self.assertEqual(result["error"]["code"], "DISCORD_FETCH_FAILED")
        self.assertTrue(result["error"]["retryable"])
        self.archive_message()
        result = (await self.lookup(include_metadata=True))["message"]
        self.assertEqual(result["content"], "archived text")
        self.assertIsNone(result["metadata"])
        for exception, status, code in (
            (discord.Forbidden, 403, "MESSAGE_INACCESSIBLE"),
            (discord.NotFound, 404, "MESSAGE_UNAVAILABLE"),
        ):
            self.channel.fetch_message.side_effect = exception(
                SimpleNamespace(status=status, reason="failure"), "private provider error")
            self.assertEqual((await self.lookup(include_metadata=True))["error"]["code"], code)
