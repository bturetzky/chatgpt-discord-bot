import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import discord

from discord_bot.storage import Database
from discord_bot.storage.database import MIGRATIONS
from discord_bot.storage.message_archive import MessageArchive


class ArchiveTests(unittest.TestCase):
    def test_unchanged_edited_snapshots_enrich_legacy_reply_metadata(self):
        for is_reply in (False, True):
            with self.subTest(is_reply=is_reply), tempfile.TemporaryDirectory() as tmp:
                with Database(str(Path(tmp) / "bot.sqlite3")) as db:
                    archive = MessageArchive(db)
                    timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
                    message = SimpleNamespace(
                        guild=SimpleNamespace(id=1), channel=SimpleNamespace(id=2, parent=None),
                        id=3, author=SimpleNamespace(id=4), content="original",
                        created_at=timestamp, edited_at=timestamp,
                    )
                    archive.upsert(message)

                    def snapshot():
                        return db.connection.execute(
                            "SELECT content, edited_at, reply_channel_id, reply_message_id "
                            "FROM messages WHERE message_id='3'"
                        ).fetchone()

                    original = snapshot()
                    self.assertEqual(original[2:], (None, None))
                    message.type = discord.MessageType.reply if is_reply else discord.MessageType.default
                    message.reference = SimpleNamespace(guild_id=1, channel_id=2, message_id=1) if is_reply else None
                    archive.upsert(message)
                    expected = ("2", "1") if is_reply else (None, "")
                    self.assertEqual(snapshot(), (*original[:2], *expected))

                    message.edited_at = None
                    message.content = "stale"
                    message.reference = None
                    archive.upsert(message)
                    self.assertEqual(snapshot(), (*original[:2], *expected))

                    message.edited_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
                    message.content = "newer"
                    archive.upsert(message)
                    self.assertEqual(snapshot()[0], "newer")
                    self.assertEqual(snapshot()[2:], expected)

                    archive.delete(3)
                    archive.upsert(message)
                    self.assertEqual(snapshot()[0], "")

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
                ).fetchone()[0], len(MIGRATIONS))
                self.assertEqual(reopened.connection.execute(
                    "SELECT count(*) FROM messages"
                ).fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
