"""SQLite-only publication ledger integration tests."""
import tempfile
import unittest
from pathlib import Path

from discord_bot.storage.database import Database
from discord_bot.storage.memory_publication_ledger import (
    invalidate_changed_sources, record_attempt, reconcile_recorded_attempt,
    stage_create, validate_sources,
)


def plan():
    return {
        "proposal_id": "proposal-v1-test",
        "decision": "review_required", "operation": "create", "blockers": [],
        "memory": {
            "guild_id": "1", "source_channel_id": "2", "scope": "individual",
            "durability": "durable", "summary": "User likes cooperative games.",
            "participant_ids": ["3"], "source_message_ids": ["4"],
        },
    }


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.temp.name) / "db.sqlite")).open()
        self.c = self.db.connection
        self.c.execute(
            """INSERT INTO messages
               (guild_id, channel_id, message_id, author_id, content, created_at)
               VALUES ('1', '2', '4', '3', 'I love cooperative games', '2026-11-01T00:00:00Z')""",
        )

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_stage_idempotent_and_no_remote_attempt(self):
        self.assertTrue(stage_create(self.c, plan(), memory_id="logical-1", bot_author_id="9")["created"])
        self.assertFalse(stage_create(self.c, plan(), memory_id="logical-1", bot_author_id="9")["created"])
        self.assertTrue(validate_sources(self.c, "logical-1", 1, bot_author_id="9"))
        self.assertEqual(self.c.execute(
            "SELECT COUNT(*) FROM memory_publication_attempts").fetchone()[0], 0)

    def test_rejects_edited_source_and_rolls_back(self):
        self.c.execute("UPDATE messages SET edited_at='now' WHERE message_id='4'")
        with self.assertRaises(ValueError):
            stage_create(self.c, plan(), memory_id="logical-1", bot_author_id="9")
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM memory_records").fetchone()[0], 0)

    def test_rejects_bot_and_cross_guild_source(self):
        with self.assertRaises(ValueError):
            stage_create(self.c, plan(), memory_id="logical-1", bot_author_id="3")
        self.c.execute("UPDATE messages SET guild_id='8' WHERE message_id='4'")
        with self.assertRaises(ValueError):
            stage_create(self.c, plan(), memory_id="logical-1", bot_author_id="9")

    def test_source_edit_invalidates_staged_revision(self):
        stage_create(self.c, plan(), memory_id="logical-1", bot_author_id="9")
        self.c.execute("UPDATE messages SET content='changed' WHERE message_id='4'")
        self.assertFalse(validate_sources(self.c, "logical-1", 1, bot_author_id="9"))
        self.assertTrue(invalidate_changed_sources(
            self.c, "logical-1", 1, bot_author_id="9"))
        self.assertEqual(self.c.execute(
            "SELECT state FROM memory_revisions").fetchone()[0], "invalidated")

    def test_attempt_requires_reconciliation(self):
        stage_create(self.c, plan(), memory_id="logical-1", bot_author_id="9")
        result = record_attempt(
            self.c, attempt_id="a", memory_id="logical-1",
            revision=1, operation="upsert", vector_id="v")
        self.assertFalse(result["remote_write_performed"])
        with self.assertRaises(ValueError):
            record_attempt(self.c, attempt_id="b", memory_id="logical-1",
                           revision=1, operation="upsert", vector_id="v")
        self.assertEqual(reconcile_recorded_attempt(
            self.c, "a", observation="unknown"), "uncertain")
        self.assertEqual(self.c.execute(
            "SELECT state FROM memory_revisions").fetchone()[0], "pending")
        self.assertEqual(reconcile_recorded_attempt(
            self.c, "a", observation="matching", matching_vector=True), "confirmed")
        self.assertEqual(self.c.execute(
            "SELECT state FROM memory_revisions").fetchone()[0], "published")
        self.assertEqual(self.c.execute(
            "SELECT lifecycle, current_revision FROM memory_records").fetchone(),
            ("active", 1))

    def test_missing_remote_vector_is_failed_not_published(self):
        stage_create(self.c, plan(), memory_id="logical-1", bot_author_id="9")
        record_attempt(self.c, attempt_id="a", memory_id="logical-1",
                       revision=1, operation="upsert", vector_id="v")
        self.assertEqual(reconcile_recorded_attempt(
            self.c, "a", observation="missing"), "failed")
        self.assertEqual(self.c.execute(
            "SELECT state FROM memory_revisions").fetchone()[0], "failed")


if __name__ == "__main__":
    unittest.main()
