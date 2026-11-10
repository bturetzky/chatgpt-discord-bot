"""Autonomous publication eligibility and deterministic identity tests."""
import unittest
import sqlite3
from discord_bot.storage.autonomous_memory import eligible, memory_vector_id, pending_fingerprint


class AutonomousMemoryTests(unittest.TestCase):
    def test_only_clean_create_is_eligible(self):
        plan = {"decision": "review_required", "operation": "create",
                "blockers": [], "memory": {"summary": "Likes puzzles"}}
        self.assertTrue(eligible(plan))
        for key, value in [("decision", "blocked"), ("operation", "merge"),
                           ("blockers", ["edited source"])]:
            changed = dict(plan, **{key: value})
            self.assertFalse(eligible(changed))

    def test_fingerprint_invalidated_by_source_edit_and_new_candidate(self):
        db = sqlite3.connect(":memory:")
        db.executescript("""
            CREATE TABLE extraction_batches (batch_id TEXT, guild_id TEXT,
                extractor_version TEXT, status TEXT);
            CREATE TABLE extraction_candidates (batch_id TEXT, candidate_index INTEGER,
                status TEXT, summary TEXT, participant_ids TEXT,
                source_message_ids TEXT, confidence TEXT, memory_type TEXT);
            CREATE TABLE messages (guild_id TEXT, message_id TEXT, author_id TEXT,
                channel_id TEXT, content TEXT, created_at TEXT,
                edited_at TEXT, deleted_at TEXT);
            INSERT INTO extraction_batches VALUES ('b', 'g', 'v', 'completed');
            INSERT INTO extraction_candidates VALUES
                ('b', 0, 'proposed', 'Likes puzzles', '["1"]', '["m"]', 'high', 'fact');
            INSERT INTO messages VALUES ('g', 'm', '1', 'c', 'hello', 't', NULL, NULL);
        """)
        first = pending_fingerprint(db, "g", "model")
        self.assertEqual(first, pending_fingerprint(db, "g", "model"))
        db.execute("UPDATE messages SET content='edited', edited_at='later'")
        second = pending_fingerprint(db, "g", "model")
        self.assertNotEqual(first, second)
        db.execute("""INSERT INTO extraction_candidates VALUES
            ('b', 1, 'proposed', 'Another fact', '["1"]', '["m"]', 'high', 'fact')""")
        self.assertNotEqual(second, pending_fingerprint(db, "g", "model"))
        db.close()

    def test_id_is_stable_and_attributed(self):
        a = memory_vector_id("1", "individual", ["3"], "Likes  puzzles")
        self.assertEqual(a, memory_vector_id("1", "individual", ["3"], "likes puzzles"))
        self.assertNotEqual(a, memory_vector_id("2", "individual", ["3"], "Likes puzzles"))
        self.assertNotEqual(a, memory_vector_id("1", "individual", ["4"], "Likes puzzles"))
        self.assertNotEqual(a, memory_vector_id("1", "collective", ["3"], "Likes puzzles"))


if __name__ == "__main__":
    unittest.main()
