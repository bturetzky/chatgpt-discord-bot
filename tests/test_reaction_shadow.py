import asyncio
import tempfile
from unittest.mock import patch
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

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
                client = FakeClient()
                shadow = ReactionShadow(db.connection, guild_id="1", api_key="unused",
                                        client=client, delay=0, max_evaluations=2)
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
                    "SELECT count(*) FROM shadow_evaluations").fetchone()[0], 2)
                self.assertEqual(db.connection.execute(
                    "SELECT sum(input_tokens) FROM shadow_evaluations").fetchone()[0], 84)
                await shadow.close()
            with Database(path) as db:
                client = FakeClient()
                shadow = ReactionShadow(db.connection, guild_id="1", api_key="unused",
                                        client=client, delay=0, max_evaluations=2)
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
