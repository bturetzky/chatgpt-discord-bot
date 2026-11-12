import asyncio
import json
import tempfile
from unittest.mock import AsyncMock, Mock, patch
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import discord

from discord_bot.storage import Database
from discord_bot.storage.database import MIGRATIONS
from discord_bot.handlers.reaction_shadow import ReactionShadow


def model_response(action="ignore", message_id=None, emoji=None):
    return SimpleNamespace(
        output_text=json.dumps(dict(action=action, message_id=message_id, emoji_key=emoji,
                                    reason_category="celebration")),
        usage=SimpleNamespace(input_tokens=42, output_tokens=12),
    )


def live_message(n, *, channel=2, guild=1):
    return SimpleNamespace(
        id=n, guild=SimpleNamespace(id=guild),
        channel=SimpleNamespace(id=channel, type=SimpleNamespace(name="text")),
        author=SimpleNamespace(id=3, bot=False), content=f"message {n}", webhook_id=None,
    )


def archive(db, message):
    db.execute(
        """INSERT INTO messages (guild_id,channel_id,message_id,author_id,content,created_at)
           VALUES (?,?,?,?,?,?)""",
        (str(message.guild.id), str(message.channel.id), str(message.id), str(message.author.id),
         message.content, datetime.now(timezone.utc).isoformat()),
    )


def human_reaction(db, message_id, user_id, emoji="unicode:🔥", channel=2):
    db.execute(
        """INSERT INTO reaction_members (guild_id,channel_id,message_id,emoji_key,user_id)
           VALUES ('1',?,?,?,?)""", (str(channel), str(message_id), emoji, str(user_id)),
    )


class ShadowTests(unittest.IsolatedAsyncioTestCase):
    async def test_posting_outcomes_and_restart(self):
        cases = (
            ("unicode:🔥", "react", None, "posted"),
            ("custom:42", "react", None, "posted"),
            ("unicode:🔥", "ignore", None, "ignored"),
            ("unicode:🔥", "react", "deleted", "unavailable"),
            ("unicode:🔥", "react", "forbidden", "forbidden"),
            ("unicode:🔥", "react", "http", "http_error"),
            ("unicode:🔥", "react", "before_attempt", "failed"),
            ("unicode:🔥", "react", "during_attempt", "uncertain"),
            ("custom:42", "react", "emoji", "emoji_unavailable"),
            ("unicode:🔥", "react", "bot", "not_human_message"),
            ("unicode:🔥", "react", "already", "already_reacted"),
            ("unicode:🔥", "react", "cooldown", "cooldown"),
            ("unicode:🔥", "react", "author_cooldown", "cooldown"),
            ("unicode:🔥", "react", "paced", "paced"),
        )
        for key, decision, problem, expected in cases:
            with self.subTest(key=key, problem=problem), tempfile.TemporaryDirectory() as tmp:
                path = str(Path(tmp) / "bot.sqlite3")
                guild = Mock(id=1)
                custom = guild.get_emoji.return_value
                message = SimpleNamespace(author=SimpleNamespace(id=3, bot=problem == "bot"),
                                          webhook_id=None, guild=guild, reactions=[],
                                          add_reaction=AsyncMock())
                channel = SimpleNamespace(guild=guild, fetch_message=AsyncMock(return_value=message))
                gateway = Mock()
                gateway.get_channel.return_value = channel
                gateway.get_guild.return_value = guild
                if problem == "deleted":
                    channel.fetch_message.side_effect = discord.NotFound(Mock(status=404), "gone")
                if problem == "forbidden":
                    message.add_reaction.side_effect = discord.Forbidden(Mock(status=403), "denied")
                if problem == "http":
                    message.add_reaction.side_effect = discord.HTTPException(Mock(status=500), "error")
                if problem == "before_attempt":
                    gateway.get_channel.side_effect = RuntimeError("unexpected channel failure")
                if problem == "during_attempt":
                    message.add_reaction.side_effect = RuntimeError("unexpected request failure")
                if problem == "emoji":
                    guild.get_emoji.side_effect = [custom, None]
                if problem == "already":
                    message.reactions = [SimpleNamespace(me=True)]

                model = SimpleNamespace(
                    responses=SimpleNamespace(create=AsyncMock(return_value=model_response(decision, "5", key))),
                    close=AsyncMock(),
                )
                with Database(path) as db:
                    db.connection.execute(
                        """INSERT INTO messages (guild_id,channel_id,message_id,author_id,content,created_at)
                           VALUES ('1','2','5','3',?,?)""",
                        ("a hilarious conversation to evaluate", datetime.now(timezone.utc).isoformat()),
                    )
                    if key.startswith("custom:"):
                        db.connection.execute(
                            """INSERT INTO reaction_members (guild_id,channel_id,message_id,emoji_key,user_id)
                               VALUES ('1','2','5',?,'9')""", (key,))
                    if problem == "author_cooldown":
                        archive(db.connection, live_message(100, channel=3))
                    if problem in ("cooldown", "author_cooldown", "paced"):
                        for n in range(12 if problem == "paced" else 1):
                            db.connection.execute(
                                """INSERT INTO shadow_evaluations
                                   (message_id,guild_id,channel_id,trigger,status,posting_outcome,posted_at)
                                   VALUES (?, '1', ?, 'independent', 'completed', 'posted',
                                           datetime('now', ?))""",
                                (str(100 + n), "3" if problem == "author_cooldown" else "2",
                                 "-1 hour" if problem == "paced" else "-1 minute"),
                            )
                    shadow = ReactionShadow(db.connection, guild_id="1", api_key="unused",
                                            discord_client=gateway, client=model)
                    shadow.observe_message(live_message(5))
                    human_reaction(db.connection, 5, 10)
                    human_reaction(db.connection, 5, 11)
                    payload = SimpleNamespace(guild_id=1, channel_id=2, message_id=5)
                    shadow.observe_reaction(payload)
                    shadow.observe_reaction(payload)
                    if problem in ("before_attempt", "during_attempt"):
                        with self.assertLogs(level="ERROR") as logs:
                            await shadow.pending[("2", "5")]
                        self.assertIn("Traceback (most recent call last)", logs.output[0])
                    else:
                        await shadow.pending[("2", "5")]
                    outcome, posted_at = db.connection.execute(
                        "SELECT posting_outcome, posted_at FROM shadow_evaluations WHERE trigger='pile_on'"
                    ).fetchone()
                    self.assertEqual(outcome, expected)
                    self.assertEqual(posted_at is not None, expected == "posted")
                    if expected == "posted":
                        message.add_reaction.assert_awaited_once_with(custom if key.startswith("custom:") else "🔥")
                    elif problem == "during_attempt":
                        message.add_reaction.assert_awaited_once_with("🔥")
                    elif problem not in ("forbidden", "http"):
                        message.add_reaction.assert_not_awaited()
                    await shadow.close()
                with Database(path) as db:
                    shadow = ReactionShadow(db.connection, guild_id="1", api_key="unused",
                                            discord_client=gateway, client=model)
                    shadow.observe_reaction(payload)
                    self.assertFalse(shadow.pending)
                    model.responses.create.assert_awaited_once()
                    await shadow.close()


class WindowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = str(Path(temp.name) / "bot.sqlite3")
        self.database = Database(self.path).open()
        self.addCleanup(self.database.close)
        self.db = self.database.connection
        self.create = AsyncMock(return_value=model_response())
        self.worker = self.new_worker()

    def new_worker(self, **kwargs):
        client = SimpleNamespace(responses=SimpleNamespace(create=self.create), close=AsyncMock())
        worker = ReactionShadow(self.db, guild_id="1", api_key="unused",
                                discord_client=Mock(get_guild=Mock(return_value=None)),
                                client=client, **kwargs)
        self.addAsyncCleanup(worker.close)
        return worker

    def ingest(self, n, *, channel=2, live=True):
        message = live_message(n, channel=channel)
        archive(self.db, message)
        if live:
            self.worker.observe_message(message)

    def age(self, seconds):
        self.db.execute("UPDATE messages SET reaction_queued_at=unixepoch('now')-? "
                        "WHERE reaction_queued_at>0", (seconds,))

    async def drain(self):
        await asyncio.gather(*self.worker.pending.values())
        await asyncio.sleep(0)

    def inputs(self):
        return [json.loads(call.kwargs["input"]) for call in self.create.await_args_list]

    def pile_on(self, message_id, channel=2):
        human_reaction(self.db, message_id, 8, channel=channel)
        human_reaction(self.db, message_id, 9, channel=channel)
        self.worker.observe_reaction(SimpleNamespace(guild_id=1, channel_id=channel, message_id=message_id))

    async def test_quiet_channel_is_evaluated_by_timer_and_empty_windows_are_skipped(self):
        self.ingest(1)
        self.ingest(2, channel=3, live=False)
        self.worker.POLL_INTERVAL = 0
        self.worker.start()
        await asyncio.sleep(0)
        self.assertFalse(self.worker.pending)
        self.age(3601)
        await asyncio.sleep(0)
        await self.drain()
        self.worker._schedule("2", force=True)
        await self.drain()
        self.assertEqual([p["eligible_message_ids"] for p in self.inputs()], [["1"]])

    async def test_tenth_message_triggers_and_overlapping_context_is_not_eligible(self):
        for n in range(1, 10):
            self.ingest(n)
        self.assertFalse(self.worker.pending)
        self.ingest(10)
        await self.drain()
        self.ingest(11, live=False)
        self.ingest(12)
        self.age(3601)
        await self.worker._process("2", None, "conversation_window", False)
        first, second = self.inputs()
        self.assertIn("JSON", first["output_instruction"])
        self.assertEqual(first["eligible_message_ids"], [str(n) for n in range(1, 11)])
        self.assertEqual(second["eligible_message_ids"], ["12"])
        self.assertEqual([m["message_id"] for m in second["messages"]], [str(n) for n in range(1, 13)])

    async def test_window_posts_to_only_the_selected_target(self):
        guild = SimpleNamespace(id=1)
        message = SimpleNamespace(author=SimpleNamespace(id=3, bot=False), guild=guild,
                                  webhook_id=None, reactions=[], add_reaction=AsyncMock())
        channel = SimpleNamespace(guild=guild, fetch_message=AsyncMock(return_value=message))
        self.worker.discord_client.get_channel.return_value = channel
        self.create.return_value = model_response("react", "4", "unicode:🔥")
        for n in range(1, 11):
            self.ingest(n)
        await self.drain()
        channel.fetch_message.assert_awaited_once_with(4)
        message.add_reaction.assert_awaited_once_with("🔥")
        self.assertEqual(tuple(self.db.execute(
            """SELECT selected_message_id, new_message_count, posting_outcome, input_tokens
               FROM shadow_evaluations"""
        ).fetchone()), ("4", 10, "posted", 42))

    async def test_window_rejects_a_target_that_is_only_context(self):
        self.ingest(1, live=False)
        self.ingest(2)
        self.age(3601)
        self.create.return_value = model_response("react", "1", "unicode:🔥")
        await self.worker._process("2", None, "conversation_window", False)
        self.worker.discord_client.get_channel.assert_not_called()
        self.assertEqual(self.db.execute("SELECT status FROM shadow_evaluations").fetchone()[0], "failed")

    async def test_migration_preserves_historical_evaluations_and_archive(self):
        path = str(Path(self.path).with_name("historical.sqlite3"))
        with patch("discord_bot.storage.database.MIGRATIONS", MIGRATIONS[:-1]), Database(path) as old:
            archive(old.connection, live_message(1))
            old.connection.execute(
                """INSERT INTO shadow_evaluations (message_id,guild_id,channel_id,trigger,status,
                   decision,posting_outcome) VALUES ('1','1','2','independent','completed','react','posted')"""
            )
        with Database(path) as upgraded:
            self.assertEqual(tuple(upgraded.connection.execute(
                """SELECT message_id, trigger, posting_outcome, selected_message_id, new_message_count
                   FROM shadow_evaluations"""
            ).fetchone()), ("1", "independent", "posted", None, None))
            self.assertIsNone(upgraded.connection.execute(
                "SELECT reaction_queued_at FROM messages"
            ).fetchone()[0])

    async def test_pile_on_requires_distinct_people_and_has_surrounding_context(self):
        for n in range(1, 4):
            self.ingest(n)
        human_reaction(self.db, 2, 8, "unicode:😂")
        human_reaction(self.db, 2, 8)
        payload = SimpleNamespace(guild_id=1, channel_id=2, message_id=2)
        self.worker.observe_reaction(payload)
        self.assertFalse(self.worker.pending)
        human_reaction(self.db, 2, 9)
        self.worker.observe_reaction(payload)
        await self.drain()
        self.worker.observe_reaction(payload)
        self.assertFalse(self.worker.pending)
        self.age(3601)
        await self.worker._process("2", None, "conversation_window", False)
        first, second = self.inputs()
        self.assertEqual(first["trigger"], "pile_on")
        self.assertEqual(first["eligible_message_ids"], ["2"])
        self.assertEqual([m["message_id"] for m in first["messages"]], ["1", "2", "3"])
        self.assertEqual(first["messages"][1]["reactions"], {"unicode:🔥": 2, "unicode:😂": 1})
        self.assertEqual(second["eligible_message_ids"], ["1", "3"])

    async def test_concurrent_paths_and_shared_budget_with_historical_rows(self):
        self.worker.max_evaluations = 2
        self.db.execute(
            """INSERT INTO shadow_evaluations (message_id,guild_id,channel_id,trigger,status)
               VALUES ('100','1','2','independent','completed')"""
        )
        self.ingest(1)
        self.pile_on(1)
        self.worker._schedule("2", force=True)
        self.ingest(2, channel=3)
        self.worker._schedule("3", force=True)
        await self.drain()
        self.assertEqual([p["eligible_message_ids"] for p in self.inputs()], [["1"]])
        self.assertGreater(self.db.execute(
            "SELECT reaction_queued_at FROM messages WHERE message_id='2'"
        ).fetchone()[0], 0)

    async def test_model_failure_and_restart_keep_only_unevaluated_targets(self):
        self.ingest(1)
        self.pile_on(1)
        await self.drain()
        self.ingest(2)
        self.age(3601)
        self.create.side_effect = [TimeoutError(), model_response()]
        await self.worker._process("2", None, "conversation_window", False)
        await self.worker.close()
        self.database.close()
        self.database.open()
        self.db = self.database.connection
        self.worker = self.new_worker()
        self.worker.start()
        await asyncio.sleep(0)
        await self.drain()
        self.assertEqual([p["eligible_message_ids"] for p in self.inputs()], [["1"], ["2"], ["2"]])
        self.assertEqual([r[0] for r in self.db.execute(
            "SELECT status FROM shadow_evaluations ORDER BY rowid"
        )], ["completed", "failed", "completed"])

    async def test_deleted_during_evaluation_is_not_fetched_or_posted(self):
        async def delete_then_select(**kwargs):
            self.db.execute("UPDATE messages SET deleted_at=CURRENT_TIMESTAMP WHERE message_id='1'")
            return model_response("react", "1", "unicode:🔥")

        self.create.side_effect = delete_then_select
        self.ingest(1)
        self.pile_on(1)
        await self.drain()
        self.worker.discord_client.get_channel.assert_not_called()
        self.assertEqual(self.db.execute(
            "SELECT posting_outcome FROM shadow_evaluations"
        ).fetchone()[0], "message_deleted")

    async def test_existing_test_prefix_can_trigger_a_window(self):
        with patch.dict("os.environ", {"REACTION_SHADOW_TEST_PREFIX": "message"}):
            self.worker = self.new_worker()
        self.ingest(1)
        await self.drain()
        self.assertEqual(self.inputs()[0]["trigger"], "conversation_window")


if __name__ == "__main__":
    unittest.main()
