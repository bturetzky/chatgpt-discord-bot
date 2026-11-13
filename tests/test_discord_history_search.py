import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from discord_bot.storage import Database
from discord_bot.functions.discord_history_function import (SearchDiscordHistory, search_messages,
    GetDiscordConversationContext, get_conversation_context)


class HistorySearchTests(unittest.IsolatedAsyncioTestCase):
    def test_relevance_phrase_normalization_and_bounds(self):
        with tempfile.TemporaryDirectory() as tmp, Database(str(Path(tmp) / "test.db")) as db:
            conn = db.connection
            rows = [
                ("1", "10", "100", "7", "space age space age launch!", "2026-11-01", None),
                ("1", "10", "101", "8", "age of space before launch", "2026-11-02", None),
                ("1", "10", "102", "8", "space age launch", "2026-11-03", "2026-11-04"),
            ]
            rows.extend(("1", "10", str(i), "8", "filler " * 100 + " space age launch",
                         "2026-11-03", None) for i in range(110, 122))
            conn.executemany(
                "INSERT INTO messages(guild_id,channel_id,message_id,author_id,content,created_at,deleted_at) "
                "VALUES (?,?,?,?,?,?,?)", rows)

            def search(query, **options):
                return search_messages(conn, query=query, guild_id="1", channel_ids={"10"}, **options)

            self.assertEqual(search("space age")[0]["message_id"], "100")
            self.assertEqual(search("space age", sort="newest")[0]["message_id"], "121")
            self.assertEqual(len(search('“space-age” launch?!', limit=10)), 10)
            self.assertEqual([hit["message_id"] for hit in search('"age of space" launch')], ["101"])
            self.assertEqual([hit["message_id"] for hit in search('"space-age" launch', limit=2)],
                             ["100", "121"])
            self.assertEqual(search('"space-age launch'), search("space age launch"))
            self.assertEqual(search('("*:")'), [])
            self.assertEqual(search("space OR age"), [])
            hits = search("space-age", sort="newest")
            self.assertEqual(len(hits), 5)
            self.assertTrue(all("space age" in hit["snippet"] and len(hit["snippet"]) <= 350
                                for hit in hits))

    def test_excerpt_keeps_phrase_after_long_url_and_whitespace(self):
        with tempfile.TemporaryDirectory() as tmp, Database(str(Path(tmp) / "test.db")) as db:
            for message_id, prefix in [
                ("100", "https://example.test/" + "x" * 600),
                ("101", "start" + "\n" * 500),
            ]:
                db.connection.execute(
                    "INSERT INTO messages(guild_id,channel_id,message_id,author_id,content,created_at) "
                    "VALUES (?,?,?,?,?,?)",
                    ("1", "10", message_id, "7", prefix + " space age launch", "2026-11-01"),
                )
            hits = search_messages(db.connection, query='"space age launch"', guild_id="1",
                                   channel_ids={"10"})
            self.assertEqual({hit["message_id"] for hit in hits}, {"100", "101"})
            for hit in hits:
                self.assertLessEqual(len(hit["snippet"]), 350)
                self.assertTrue(hit["snippet"].startswith("…"))
                self.assertTrue(hit["snippet"].endswith("space age launch"))

    async def test_channel_attribution_same_cross_and_permission_scope(self):
        from discord_bot.functions.discord_history_function import add_channel_attribution

        class Channel:
            def __init__(self, channel_id, name):
                self.id = channel_id
                self.name = name

        guild = SimpleNamespace(text_channels=[
            Channel(10, "general"), Channel(11, "bot-testing"),
            Channel(12, "private")])
        hits = [{"channel_id": "10"}, {"channel_id": "11"}]
        result = add_channel_attribution(hits, guild, {"10", "11"}, "10")
        self.assertEqual(result[0]["channel_name"], "general")
        self.assertFalse(result[0]["different_channel"])
        self.assertEqual(result[1]["channel_name"], "bot-testing")
        self.assertTrue(result[1]["different_channel"])
        self.assertIsNone(add_channel_attribution(
            [{"channel_id": "12"}], guild, {"10", "11"}, "10")[0]["channel_name"])
        self.assertIsNone(add_channel_attribution(
            [{"channel_id": "11"}], guild, {"10", "11"}, None)[0]["different_channel"])

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
                self.assertEqual(hits[0]["message_id"], "100")
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

                requester, bot = object(), object()

                class Channel:
                    def __init__(self, channel_id, denied=None, deny_view=False):
                        self.id = channel_id
                        self.denied = denied
                        self.deny_view = deny_view

                    def permissions_for(self, member):
                        denied = member is self.denied
                        return SimpleNamespace(view_channel=not (denied and self.deny_view),
                                               read_message_history=not denied or self.deny_view)

                guild = SimpleNamespace(id=1, text_channels=[Channel(10), Channel(11, requester)],
                                        me=bot, get_member={7: SimpleNamespace(display_name="Ada")}.get)
                for channel in [Channel(11, requester), Channel(11, requester, deny_view=True),
                                Channel(11, bot), Channel(11, bot, deny_view=True)]:
                    guild.text_channels[1] = channel
                    context = {"archive": SimpleNamespace(db=conn), "guild": guild, "member": requester}
                    result = json.loads(await SearchDiscordHistory().execute_with_context(
                        {"query": "Factorio", "channel_id": "11"}, context))
                    self.assertEqual(result["results"], [])
                    result = json.loads(await GetDiscordConversationContext().execute_with_context(
                        {"channel_id": "11", "message_id": "101"}, context))
                    self.assertEqual(result["results"], [])
                guild.text_channels[1] = Channel(11)
                result = json.loads(await SearchDiscordHistory().execute_with_context(
                    {"query": "Factorio", "channel_id": "11"}, context))
                self.assertIsNone(result["results"][0]["author_display_name"])
                self.assertEqual(result["results"][0]["author_id"], "8")
                guild.text_channels[1] = Channel(11, bot)
                tool = SearchDiscordHistory()
                result = json.loads(await tool.execute_with_context(
                    {"query": "Factorio"}, {"archive": SimpleNamespace(db=conn),
                    "guild": guild, "member": object()}))
                with self.assertLogs(level="INFO") as logs:
                    cross_channel = json.loads(await tool.execute_with_context(
                        {"query": "Factorio"}, {"archive": SimpleNamespace(db=conn),
                        "guild": guild, "member": object()}))
                self.assertEqual(len(cross_channel["results"]), 1)
                self.assertNotIn("Factorio", logs.output[0])
                self.assertIn("results=1", logs.output[0])
                blank_filters = json.loads(await tool.execute_with_context(
                    {"query": "Factorio", "channel_id": "", "author_id": "",
                     "after": "", "before": ""},
                    {"archive": SimpleNamespace(db=conn), "guild": guild, "member": object()}))
                self.assertTrue(blank_filters["ok"])
                self.assertEqual(len(blank_filters["results"]), 1)
                self.assertTrue(result["ok"])
                self.assertEqual([hit["message_id"] for hit in result["results"]], ["100"])
                self.assertEqual(result["results"][0]["author_display_name"], "Ada")
                self.assertFalse(json.loads(await tool.execute_with_context(
                    {"query": "Factorio"}, {"archive": SimpleNamespace(db=conn),
                    "guild": guild, "member": None}))["ok"])

    async def test_conversation_context_window_permissions_and_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            with Database(str(Path(tmp) / "test.db")) as db:
                conn = db.connection
                for i in range(1, 9):
                    conn.execute(
                        "INSERT INTO messages(guild_id,channel_id,message_id,author_id,content,created_at,deleted_at) "
                        "VALUES (?,?,?,?,?,?,?)",
                        ("1", "10", str(i), "7" if i % 2 else "8",
                         f"message {i}", f"2026-11-01T12:00:{i:02d}+00:00",
                         "2026-11-02" if i == 6 else None))
                conn.execute(
                    "INSERT INTO messages(guild_id,channel_id,message_id,author_id,content,created_at) "
                    "VALUES (?,?,?,?,?,?)",
                    ("1", "11", "99", "7", "private", "2026-11-01T12:00:04+00:00"))
                results = get_conversation_context(
                    conn, guild_id="1", channel_ids={"10"}, channel_id="10",
                    message_id="4", before=2, after=3)
                self.assertEqual([x["url"].split("/")[-1] for x in results],
                                 ["2", "3", "4", "5", "7", "8"])
                self.assertEqual(results[2]["message_id"], "4")
                self.assertEqual([x["anchor"] for x in results],
                                 [False, False, True, False, False, False])
                self.assertEqual(get_conversation_context(
                    conn, guild_id="1", channel_ids={"10"}, channel_id="11",
                    message_id="99"), [])
                self.assertEqual(get_conversation_context(
                    conn, guild_id="1", channel_ids={"10"}, channel_id="10",
                    message_id="6"), [])
                with self.assertRaises(ValueError):
                    get_conversation_context(conn, guild_id="1", channel_ids={"10"},
                                             channel_id="10", message_id="4",
                                             before=10, after=10)

                class Channel:
                    id = 10
                    def permissions_for(self, member):
                        return SimpleNamespace(view_channel=True, read_message_history=True)
                guild = SimpleNamespace(id=1, text_channels=[Channel()], me=object())
                tool = GetDiscordConversationContext()
                payload = json.loads(await tool.execute_with_context(
                    {"channel_id": "10", "message_id": "4", "before": 1, "after": 1},
                    {"archive": SimpleNamespace(db=conn), "guild": guild, "member": object()}))
                self.assertTrue(payload["ok"])
                self.assertEqual(len(payload["results"]), 3)
                blanks = json.loads(await tool.execute_with_context(
                    {"channel_id": "10", "message_id": "4", "before": "", "after": ""},
                    {"archive": SimpleNamespace(db=conn), "guild": guild, "member": object()}))
                self.assertTrue(blanks["ok"])
                self.assertEqual([x["message_id"] for x in blanks["results"]],
                                 ["1", "2", "3", "4", "5", "7", "8"])
