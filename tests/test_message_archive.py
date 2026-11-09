import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from discord_bot.storage import Database
from discord_bot.storage.message_archive import MessageArchive


class ArchiveTests(unittest.TestCase):
    def test_insert_edit_delete_and_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "bot.sqlite3")
            with Database(path) as db:
                archive = MessageArchive(db)
                message = SimpleNamespace(
                    guild=SimpleNamespace(id=1),
                    channel=SimpleNamespace(id=2, parent=None),
                    id=3, author=SimpleNamespace(id=4),
                    content="hello archive",
                    created_at=datetime.now(timezone.utc), edited_at=None,
                )
                archive.upsert(message)
                archive.upsert(message)
                self.assertEqual(db.connection.execute("SELECT count(*) FROM messages").fetchone()[0], 1)
                self.assertEqual(db.connection.execute(
                    "SELECT count(*) FROM messages_fts WHERE messages_fts MATCH 'hello'"
                ).fetchone()[0], 1)
                archive.edit(3, "updated text", "2026-11-08T12:00:00Z")
                stale = SimpleNamespace(**{**vars(message), "content": "stale snapshot"})
                archive.upsert(stale)
                self.assertEqual(db.connection.execute(
                    "SELECT content FROM messages WHERE message_id='3'"
                ).fetchone()[0], "updated text")
                archive.edit(3, "older edit", "2026-11-08T11:00:00Z")
                self.assertEqual(db.connection.execute(
                    "SELECT content FROM messages WHERE message_id='3'"
                ).fetchone()[0], "updated text")
                self.assertEqual(db.connection.execute(
                    "SELECT count(*) FROM messages_fts WHERE messages_fts MATCH 'updated'"
                ).fetchone()[0], 1)
                archive.delete(3)
                self.assertEqual(db.connection.execute(
                    "SELECT count(*) FROM messages_fts WHERE messages_fts MATCH 'updated'"
                ).fetchone()[0], 0)
                self.assertIsNotNone(db.connection.execute(
                    "SELECT deleted_at FROM messages WHERE message_id='3'"
                ).fetchone()[0])
                archive.upsert(message)
                self.assertEqual(db.connection.execute(
                    "SELECT content FROM messages WHERE message_id='3'"
                ).fetchone()[0], "")
                archive.delete(999)
                unknown = SimpleNamespace(**{**vars(message), "id": 999, "content": "deleted before backfill"})
                archive.upsert(unknown)
                self.assertIsNone(db.connection.execute(
                    "SELECT 1 FROM messages WHERE message_id='999'"
                ).fetchone())
            with Database(path) as reopened:
                self.assertEqual(reopened.connection.execute(
                    "SELECT count(*) FROM schema_migrations"
                ).fetchone()[0], 5)
                self.assertEqual(reopened.connection.execute(
                    "SELECT count(*) FROM messages"
                ).fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
