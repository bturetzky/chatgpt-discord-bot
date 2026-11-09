import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from discord_bot.storage import Database
from discord_bot.storage.message_archive import MessageArchive
from discord_bot.storage.history import backfill_channel


class FakeChannel:
    def __init__(self, messages):
        self.id = 22
        self.messages = messages
        self.requests = []

    def history(self, *, limit, before=None, oldest_first=False):
        self.requests.append((limit, before.id if before else None))
        items = [m for m in self.messages if before is None or m.id < before.id][:limit]

        async def iterator():
            for item in items:
                yield item
        return iterator()


def message(number, age_days=1):
    return SimpleNamespace(
        id=number, guild=SimpleNamespace(id=1),
        channel=SimpleNamespace(id=22, parent=None),
        author=SimpleNamespace(id=3), content=f"message {number}",
        created_at=datetime.now(timezone.utc) - timedelta(days=age_days),
        edited_at=None,
    )


class HistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_resume_and_idempotency(self):
        with tempfile.TemporaryDirectory() as tmp:
            with Database(str(Path(tmp) / "archive.db")) as db:
                archive = MessageArchive(db)
                channel = FakeChannel([message(105), message(104), message(103), message(102)])
                cutoff = datetime.now(timezone.utc) - timedelta(days=30)
                self.assertEqual(await backfill_channel(
                    channel, archive, limit=2, cutoff=cutoff), 2)
                self.assertEqual(await backfill_channel(
                    channel, archive, limit=2, cutoff=cutoff), 2)
                self.assertEqual(channel.requests, [(2, None), (2, 104)])
                self.assertEqual(db.connection.execute(
                    "SELECT COUNT(*) FROM messages").fetchone()[0], 4)
                self.assertEqual(db.connection.execute(
                    "SELECT before_message_id FROM backfill_cursors").fetchone()[0], "102")
                self.assertEqual(await backfill_channel(
                    channel, archive, limit=2, cutoff=cutoff), 0)

    async def test_dry_run_does_not_persist_and_cutoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            with Database(str(Path(tmp) / "archive.db")) as db:
                archive = MessageArchive(db)
                channel = FakeChannel([message(105), message(104, age_days=50)])
                cutoff = datetime.now(timezone.utc) - timedelta(days=30)
                self.assertEqual(await backfill_channel(
                    channel, archive, limit=10, cutoff=cutoff, dry_run=True), 1)
                self.assertEqual(db.connection.execute(
                    "SELECT COUNT(*) FROM messages").fetchone()[0], 0)
                self.assertIsNone(db.connection.execute(
                    "SELECT 1 FROM backfill_cursors").fetchone())
                self.assertEqual(await backfill_channel(
                    channel, archive, limit=10, cutoff=cutoff), 1)
                self.assertEqual(db.connection.execute(
                    "SELECT COUNT(*) FROM messages").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
