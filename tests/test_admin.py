"""Operator CLI smoke tests: local SQLite only; no Discord, OpenAI or Pinecone."""
import contextlib
import io
import os
import sqlite3
import tempfile
import unittest
from argparse import Namespace
from unittest.mock import patch

from discord_bot import admin


class OperatorCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = os.path.join(self.temp.name, "bot.sqlite3")
        db = sqlite3.connect(self.path)
        db.executescript("""
            CREATE TABLE messages (
                guild_id TEXT, channel_id TEXT, message_id TEXT, created_at TEXT,
                deleted_at TEXT
            );
            CREATE TABLE reaction_members (guild_id TEXT);
            CREATE TABLE shadow_evaluations (
                guild_id TEXT, channel_id TEXT, message_id TEXT, evaluated_at TEXT,
                status TEXT, trigger TEXT, decision TEXT, emoji_key TEXT,
                reason_category TEXT, input_tokens INTEGER, output_tokens INTEGER
            );
            CREATE TABLE extraction_batches (
                batch_id TEXT, guild_id TEXT, channel_id TEXT,
                status TEXT, created_at TEXT
            );
            CREATE TABLE extraction_candidates (
                batch_id TEXT, candidate_index INTEGER, status TEXT,
                memory_type TEXT, summary TEXT, participant_ids TEXT,
                source_message_ids TEXT
            );
            CREATE TABLE extraction_usage (
                batch_id TEXT, input_tokens INTEGER, output_tokens INTEGER
            );
            CREATE TABLE backfill_cursors (channel_id TEXT);
            INSERT INTO messages VALUES ('123','456','789','2026-11-01T00:00:00Z',NULL);
            INSERT INTO shadow_evaluations VALUES (
                '123','456','789','2026-11-09 00:00:00',
                'completed','independent','react','unicode:😂','funny',30,5);
            INSERT INTO extraction_batches VALUES ('batch1','123','456','completed','2026-11-09');
            INSERT INTO extraction_candidates VALUES (
                'batch1',0,'accepted','fact','A remembered fact','["111"]','["789"]');
        """)
        db.commit()
        db.close()
        self.env = patch.dict(os.environ, {
            "DISCORD_SQLITE_PATH": self.path, "REACTION_SHADOW_GUILD_ID": "123"
        })
        self.env.start()
        self.addCleanup(self.env.stop)

    def capture(self, function, **kwargs):
        args = Namespace(guild_id=None, json=True, limit=30,
                         react_only=False, stats=False, status="accepted",
                         verify_pinecone=False, **kwargs)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            function(args)
        return buffer.getvalue()

    def test_reactions_link_and_emoji(self):
        result = self.capture(admin.reactions)
        self.assertIn("https://discord.com/channels/123/456/789", result)
        self.assertIn("unicode:😂", result)

    def test_reactions_empty_guild(self):
        result = self.capture(admin.reactions, guild_id="999")
        self.assertIn('"evaluations": []', result)

    def test_memory_list_not_falsely_confirmed(self):
        result = self.capture(admin.memories)
        self.assertIn('"pinecone": "not_checked"', result)
        self.assertIn("A remembered fact", result)

    def test_memory_stats(self):
        result = self.capture(admin.memory_stats)
        self.assertIn('"accepted"', result)

    def test_archive(self):
        result = self.capture(admin.archive)
        self.assertIn('"messages": 1', result)

    def test_status(self):
        result = self.capture(admin.status)
        self.assertIn('"sqlite_quick_check": "ok"', result)


if __name__ == "__main__":
    unittest.main()
