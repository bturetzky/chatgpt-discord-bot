import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from discord_bot.storage import Database
from discord_bot.functions.discord_history_function import SearchDiscordHistory, search_messages


class HistorySearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_scoping_filters_and_deleted_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            with Database(str(Path(tmp) / "test.db")) as db:
                conn = db.connection
                rows = [
                    ("1", "10", "100", "7", "Factorio server works", "2026-11-01T12:00:00.000000+00:00", None),
                    ("1", "11", "101", "8", "Factorio map updated", "2026-11-02T12:00:00.000000+00:00", None),
                    ("2", "10", "102", "7", "Factorio private", "2026-11-03T12:00:00.000000+00:00", None),
                    ("1", "10", "103", "7", "", "2026-11-04T12:00:00.000000+00:00", "2026-11-05"),
                ]
                conn.executemany(
                    "INSERT INTO messages(guild_id,channel_id,message_id,author_id,content,created_at,deleted_at) "
                    "VALUES (?,?,?,?,?,?,?)", rows)
                hits = search_messages(conn, query="Factorio", guild_id="1", channel_ids={"10"})
                self.assertEqual([h["url"].split("/")[-1] for h in hits], ["100"])
                self.assertEqual(len(search_messages(conn, query="Factorio", guild_id="1",
                    channel_ids={"10", "11"}, author_id="8")), 1)
                self.assertEqual(len(search_messages(conn, query="Factorio", guild_id="1",
                    channel_ids={"10", "11"}, after="2026-11-02T00:00:00Z")), 1)
                self.assertEqual(search_messages(conn, query="Factorio", guild_id="1",
                    channel_ids={"10"}, channel_id="11"), [])
                self.assertEqual(len(search_messages(conn, query="Factorio", guild_id="1",
                    channel_ids={"10", "11"}, channel_id="", author_id="", after="", before="")), 2)
                self.assertEqual(len(search_messages(conn, query="Factorio", guild_id="1",
                    channel_ids={"10"}, channel_id="  ", author_id=" ", after=" ", before=" ")), 1)
                self.assertEqual(search_messages(conn, query="Factorio", guild_id="1",
                    channel_ids=set()), [])
                self.assertEqual(search_messages(conn, query="Factorio", guild_id="2",
                    channel_ids={"11"}), [])
                with self.assertRaises(ValueError):
                    search_messages(conn, query="Factorio", guild_id="1", channel_ids={"10"}, limit=100)

                class Channel:
                    id = 10
                    def permissions_for(self, member):
                        return SimpleNamespace(view_channel=True, read_message_history=True)

                guild = SimpleNamespace(id=1, text_channels=[Channel()], me=object())
                tool = SearchDiscordHistory()
                result = json.loads(await tool.execute_with_context(
                    {"query": "Factorio"}, {"archive": SimpleNamespace(db=conn),
                    "guild": guild, "member": object()}))
                with self.assertLogs(level="INFO") as logs:
                    cross_channel = json.loads(await tool.execute_with_context(
                        {"query": "Factorio"}, {"archive": SimpleNamespace(db=conn),
                        "guild": guild, "member": object()}))
                self.assertEqual(len(cross_channel["results"]), 1)
                self.assertIn("permitted_channels=", logs.output[0])
                self.assertIn("results=1", logs.output[0])
                blank_filters = json.loads(await tool.execute_with_context(
                    {"query": "Factorio", "channel_id": "", "author_id": "",
                     "after": "", "before": ""},
                    {"archive": SimpleNamespace(db=conn), "guild": guild, "member": object()}))
                self.assertTrue(blank_filters["ok"])
                self.assertEqual(len(blank_filters["results"]), 1)
                self.assertTrue(result["ok"])
                self.assertEqual(len(result["results"]), 1)
                self.assertFalse(json.loads(await tool.execute_with_context(
                    {"query": "Factorio"}, {"archive": SimpleNamespace(db=conn),
                    "guild": guild, "member": None}))["ok"])
