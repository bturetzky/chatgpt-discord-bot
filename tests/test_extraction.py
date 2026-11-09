import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from discord_bot.storage import Database
from discord_bot.storage.extraction import discover_windows, register_windows


class ExtractionFoundationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.tmp.name) / "bot.sqlite3")).open()
        self.base = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def add(self, message_id, minute, channel="10", content="hello", guild="1"):
        created = (self.base + timedelta(minutes=minute)).isoformat()
        self.db.connection.execute(
            """INSERT INTO messages
               (guild_id, channel_id, message_id, author_id, content, created_at)
               VALUES (?, ?, ?, 'user', ?, ?)""",
            (guild, channel, str(message_id), content, created),
        )

    def windows(self, **kwargs):
        return discover_windows(
            self.db.connection, guild_id="1",
            cutoff=self.base + timedelta(hours=4), **kwargs,
        )

    def test_channel_idle_gap_and_message_cap(self):
        self.add(1, 0)
        self.add(2, 2)
        self.add(3, 50)
        self.add(4, 51, channel="20")
        self.add(5, 52, channel="20")
        self.add(6, 53, channel="20")
        self.add(7, 0, guild="other")
        windows = self.windows(max_messages=2)
        self.assertEqual([[r[2] for r in w.messages] for w in windows],
                         [["1", "2"], ["3"], ["4", "5"], ["6"]])

    def test_registration_idempotency_and_changed_source(self):
        self.add(1, 0, content="a running joke")
        self.add(2, 1)
        window = self.windows()[0]
        self.assertEqual(register_windows(self.db.connection, [window]), 1)
        self.assertEqual(register_windows(self.db.connection, [window]), 0)
        self.db.connection.execute(
            "UPDATE extraction_batches SET status='completed' WHERE batch_id=?",
            (window.batch_id,),
        )
        self.db.connection.execute(
            "UPDATE messages SET content='corrected' WHERE message_id='1'"
        )
        revised = self.windows()[0]
        self.assertEqual(revised.batch_id, window.batch_id)
        self.assertNotEqual(revised.source_hash, window.source_hash)
        self.assertEqual(register_windows(self.db.connection, [revised]), 1)
        self.assertEqual(self.db.connection.execute(
            "SELECT status FROM extraction_batches WHERE batch_id=?",
            (window.batch_id,),
        ).fetchone()[0], "pending")
        self.assertNotEqual(
            self.windows(extractor_version="v2")[0].batch_id, window.batch_id
        )

    def test_deleted_empty_cutoff_and_limits(self):
        self.add(1, 0)
        self.add(2, 1, content="")
        self.add(3, 2)
        self.db.connection.execute(
            "UPDATE messages SET deleted_at=CURRENT_TIMESTAMP WHERE message_id='3'"
        )
        self.assertEqual(len(self.windows()[0].messages), 1)
        self.assertEqual(self.windows(since=self.base + timedelta(hours=1)), [])
        with self.assertRaises(ValueError):
            self.windows(max_rows=0)
        with self.assertRaises(ValueError):
            self.windows(max_rows=0)
        self.add(4, 4)
        with self.assertRaises(ValueError):
            self.windows(max_rows=1)


if __name__ == "__main__":
    unittest.main()
