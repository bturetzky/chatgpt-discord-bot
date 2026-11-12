"""Operator CLI smoke tests: local SQLite only; no Discord, OpenAI or Pinecone."""
import contextlib
import io
import json
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
                deleted_at TEXT, reaction_queued_at INTEGER
            );
            CREATE TABLE reaction_members (guild_id TEXT);
            CREATE TABLE shadow_evaluations (
                guild_id TEXT, channel_id TEXT, message_id TEXT, evaluated_at TEXT,
                status TEXT, trigger TEXT, decision TEXT, emoji_key TEXT,
                reason_category TEXT, input_tokens INTEGER, output_tokens INTEGER,
                posting_outcome TEXT, posted_at TEXT, selected_message_id TEXT, new_message_count INTEGER
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
            INSERT INTO messages VALUES ('123','456','789','2026-11-01T00:00:00Z',NULL,NULL);
            INSERT INTO shadow_evaluations VALUES (
                '123','456','789',datetime('now','-2 days'),
                'completed','independent','react','unicode:😂','funny',30,5,'posted','2026-11-09 00:00:01',NULL,NULL);
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
        values = dict(guild_id=None, json=True, limit=30,
                      react_only=False, stats=False, status="accepted",
                      verify_pinecone=False)
        values.update(kwargs)
        args = Namespace(**values)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            function(args)
        return buffer.getvalue()

    def test_reactions_link_and_emoji(self):
        result = self.capture(admin.reactions, posted_only=True)
        self.assertIn('"posting_outcome": "posted"', result)
        self.assertIn("https://discord.com/channels/123/456/789", result)
        self.assertIn("unicode:😂", result)

    def test_reactions_reports_pending_windows_and_selected_message(self):
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE messages SET reaction_queued_at=unixepoch('now')-3601")
            db.execute(
                """INSERT INTO shadow_evaluations VALUES (
                   '123','456','evaluation-key',datetime('now'),'completed','conversation_window',
                   'react','unicode:🔥','funny',42,12,'posted',datetime('now'),'789',10)"""
            )
        report = json.loads(self.capture(admin.reactions))
        self.assertEqual(report["pending_windows"][0]["scheduling_state"], "due")
        self.assertEqual(report["evaluations_used_24h"], 1)
        window = next(row for row in report["evaluations"] if row["trigger"] == "conversation_window")
        self.assertEqual(window["new_message_count"], 10)
        self.assertEqual(window["url"], "https://discord.com/channels/123/456/789")

    def test_reactions_reports_model_retry_delay(self):
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE messages SET reaction_queued_at=unixepoch('now')-3601")
            db.execute(
                """INSERT INTO shadow_evaluations VALUES (
                   '123','456','failed-key',datetime('now'),'failed','conversation_window',
                   NULL,NULL,'TimeoutError',0,0,NULL,NULL,NULL,1)"""
            )
        report = json.loads(self.capture(admin.reactions))
        self.assertEqual(report["pending_windows"][0]["scheduling_state"], "model_retry_delay")

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
