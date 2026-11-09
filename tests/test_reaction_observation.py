import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from discord_bot.storage import Database
from discord_bot.storage.reaction_observer import ReactionObserver


class ReactionObservationTests(unittest.TestCase):
    def test_add_remove_clear_and_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "bot.sqlite3")
            with Database(path) as db:
                observer = ReactionObserver(db.connection)
                payload = SimpleNamespace(guild_id=1, channel_id=2, message_id=3,
                                          user_id=4, emoji="🔥")
                observer.add(payload, bot_user_id=99)
                observer.add(payload, bot_user_id=99)
                observer.add(SimpleNamespace(**{**vars(payload), "user_id": 99}),
                             bot_user_id=99)
                self.assertEqual(observer.counts(1, 2, 3), [("unicode:🔥", 1)])
                other = SimpleNamespace(**{**vars(payload), "user_id": 5,
                                         "emoji": SimpleNamespace(id=123)})
                observer.add(other, bot_user_id=99)
                self.assertEqual(len(observer.counts(1, 2, 3)), 2)
                observer.remove(payload)
                self.assertEqual(observer.counts(1, 2, 3), [("custom:123", 1)])
            with Database(path) as db:
                observer = ReactionObserver(db.connection)
                self.assertEqual(observer.counts(1, 2, 3), [("custom:123", 1)])
                observer.clear_emoji(other)
                self.assertEqual(observer.counts(1, 2, 3), [])
                observer.add(payload, bot_user_id=99)
                observer.clear(payload)
                self.assertEqual(observer.counts(1, 2, 3), [])

    def test_guild_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            with Database(str(Path(tmp) / "bot.sqlite3")) as db:
                observer = ReactionObserver(db.connection)
                for guild in (1, 2):
                    observer.add(SimpleNamespace(guild_id=guild, channel_id=guild,
                        message_id=guild, user_id=4, emoji="💀"), bot_user_id=99)
                self.assertEqual(observer.counts(1, 1, 1), [("unicode:💀", 1)])
                self.assertEqual(observer.counts(2, 2, 2), [("unicode:💀", 1)])


if __name__ == "__main__":
    unittest.main()
