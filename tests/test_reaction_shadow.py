import asyncio
import tempfile
from unittest.mock import AsyncMock, Mock, patch
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import discord

from discord_bot.storage import Database
from discord_bot.handlers.reaction_shadow import ReactionShadow


class FakeResponses:
    def __init__(self):
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        return SimpleNamespace(
            output_text='{"action":"react","emoji_key":"unicode:🔥","reason_category":"celebration"}',
            usage=SimpleNamespace(input_tokens=42, output_tokens=12),
        )


class FakeClient:
    def __init__(self):
        self.responses = FakeResponses()

    async def close(self):
        pass


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
            ("unicode:🔥", "react", "bot", "ineligible"),
            ("unicode:🔥", "react", "already", "already_reacted"),
            ("unicode:🔥", "react", "cooldown", "cooldown"),
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
                    guild.get_emoji.return_value = None
                if problem == "already":
                    message.reactions = [SimpleNamespace(me=True)]

                model = FakeClient()
                model.responses.create = AsyncMock(return_value=SimpleNamespace(
                    output_text=f'{{"action":"{decision}","emoji_key":"{key}"}}'))
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
                    if problem in ("cooldown", "paced"):
                        for n in range(12 if problem == "paced" else 1):
                            db.connection.execute(
                                """INSERT INTO shadow_evaluations
                                   (message_id,guild_id,channel_id,trigger,status,posting_outcome,posted_at)
                                   VALUES (?, '1', '2', 'independent', 'completed', 'posted',
                                           datetime('now', ?))""",
                                (str(100 + n), "-1 hour" if problem == "paced" else "-1 minute"),
                            )
                    shadow = ReactionShadow(db.connection, guild_id="1", api_key="unused",
                                            discord_client=gateway, client=model, delay=0)
                    shadow.schedule(1, 2, 5, "independent")
                    shadow.schedule(1, 2, 5, "pile_on")
                    if problem in ("before_attempt", "during_attempt"):
                        with self.assertLogs(level="ERROR") as logs:
                            await shadow.pending["5"]
                        self.assertIn("Traceback (most recent call last)", logs.output[0])
                    else:
                        await shadow.pending["5"]
                    outcome, posted_at = db.connection.execute(
                        "SELECT posting_outcome, posted_at FROM shadow_evaluations WHERE message_id='5'"
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
                                            discord_client=gateway, client=model, delay=0)
                    shadow.schedule(1, 2, 5, "pile_on")
                    self.assertFalse(shadow.pending)
                    model.responses.create.assert_awaited_once()
                    await shadow.close()

    async def test_budget_dedupe_guild_scope_and_persistence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "bot.sqlite3")
            with Database(path) as db:
                for n in range(1, 5):
                    db.connection.execute(
                        """INSERT INTO messages (guild_id,channel_id,message_id,author_id,content,created_at)
                           VALUES (?,?,?,?,?,?)""",
                        ("1", "2", str(n), "3", "a hilarious conversation to evaluate",
                         datetime.now(timezone.utc).isoformat()),
                    )
                db.connection.executemany(
                    """INSERT INTO shadow_evaluations
                       (message_id, guild_id, channel_id, trigger, status, evaluated_at)
                       VALUES (?, '1', '2', 'independent', 'completed', datetime('now', ?))""",
                    [(str(n), "-23 hours") for n in range(100, 146)] + [("146", "-25 hours")],
                )
                client = FakeClient()
                shadow = ReactionShadow(db.connection, guild_id="1", api_key="unused",
                                        discord_client=Mock(get_channel=Mock(return_value=None)),
                                        client=client, delay=0)
                shadow.schedule(9, 2, 1, "independent")
                shadow.schedule(1, 2, 1, "independent")
                shadow.schedule(1, 2, 1, "pile_on")
                await asyncio.sleep(.05)
                shadow.schedule(1, 2, 2, "pile_on")
                await asyncio.sleep(.05)
                shadow.schedule(1, 2, 3, "independent")
                await asyncio.sleep(.05)
                self.assertEqual(client.responses.calls, 2)
                self.assertEqual(db.connection.execute(
                    "SELECT count(*) FROM shadow_evaluations").fetchone()[0], 49)
                self.assertEqual(db.connection.execute(
                    "SELECT sum(input_tokens) FROM shadow_evaluations").fetchone()[0], 84)
                await shadow.close()
            with Database(path) as db:
                client = FakeClient()
                shadow = ReactionShadow(db.connection, guild_id="1", api_key="unused",
                                        discord_client=Mock(get_channel=Mock(return_value=None)),
                                        client=client, delay=0)
                shadow.schedule(1, 2, 4, "independent")
                await asyncio.sleep(.05)
                self.assertEqual(client.responses.calls, 0)
                await shadow.close()

    async def test_opt_in_prefix_bypasses_sampling_without_changing_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            with Database(str(Path(tmp) / "bot.sqlite3")) as db:
                client = FakeClient()
                with patch.dict("os.environ", {"REACTION_SHADOW_TEST_PREFIX": "[shadow-test]"}):
                    shadow = ReactionShadow(db.connection, guild_id="1", api_key="unused",
                                            discord_client=Mock(get_channel=Mock(return_value=None)),
                                        client=client, delay=0, max_evaluations=1)
                self.assertEqual(shadow.test_prefix, "[shadow-test]")
                db.connection.execute(
                    """INSERT INTO messages (guild_id,channel_id,message_id,author_id,content,created_at)
                       VALUES (?,?,?,?,?,?)""",
                    ("1", "2", "123", "3", "[shadow-test] funny message for evaluation",
                     datetime.now(timezone.utc).isoformat()),
                )
                message = SimpleNamespace(
                    id=123, guild=SimpleNamespace(id=1),
                    channel=SimpleNamespace(id=2, type=SimpleNamespace(name="text")),
                    author=SimpleNamespace(id=3, bot=False),
                    content="[shadow-test] funny message for evaluation",
                    webhook_id=None, mentions=[], reference=None,
                )
                shadow.observe_message(message, bot_id=99)
                await asyncio.sleep(.05)
                self.assertEqual(client.responses.calls, 1)
                self.assertEqual(db.connection.execute(
                    "SELECT trigger FROM shadow_evaluations WHERE message_id='123'"
                ).fetchone()[0], "independent")
                await shadow.close()

    async def test_reaction_trigger_uses_distinct_people(self):
        with tempfile.TemporaryDirectory() as tmp:
            with Database(str(Path(tmp) / "bot.sqlite3")) as db:
                db.connection.execute(
                    """INSERT INTO messages (guild_id,channel_id,message_id,author_id,content,created_at)
                       VALUES (?,?,?,?,?,?)""",
                    ("1", "2", "5", "3", "this is an interesting enough message",
                     datetime.now(timezone.utc).isoformat()),
                )
                client = FakeClient()
                shadow = ReactionShadow(db.connection, guild_id="1", api_key="unused",
                                        discord_client=Mock(get_channel=Mock(return_value=None)),
                                        client=client, delay=0)
                for emoji in ("unicode:😂", "unicode:🔥"):
                    db.connection.execute(
                        """INSERT INTO reaction_members (guild_id,channel_id,message_id,emoji_key,user_id)
                           VALUES (?,?,?,?,?)""", ("1", "2", "5", emoji, "8"))
                payload = SimpleNamespace(guild_id=1, channel_id=2, message_id=5)
                shadow.observe_reaction(payload)
                await asyncio.sleep(.05)
                self.assertEqual(client.responses.calls, 0)
                db.connection.execute(
                    """INSERT INTO reaction_members (guild_id,channel_id,message_id,emoji_key,user_id)
                       VALUES (?,?,?,?,?)""", ("1", "2", "5", "unicode:🔥", "9"))
                shadow.observe_reaction(payload)
                await asyncio.sleep(.05)
                self.assertEqual(client.responses.calls, 1)
                await shadow.close()


if __name__ == "__main__":
    unittest.main()
