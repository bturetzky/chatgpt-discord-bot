import json
import tempfile
import unittest
from pathlib import Path

from discord_bot.storage import Database
from discord_bot.storage.memory_evaluation import evaluate, preview, record


def candidate(summary, kind="fact", participants=None, confidence="high"):
    return {"memory_type": kind, "summary": summary,
            "participant_ids": json.dumps(participants or ["111"]),
            "source_message_ids": json.dumps(["m1"]), "confidence": confidence}


class MemoryEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.temp.name) / "test.sqlite")).open()
        self.conn = self.db.connection
        self.conn.execute(
            """INSERT INTO extraction_batches
               (batch_id, guild_id, channel_id, first_message_id,
                last_message_id, source_hash, extractor_version, status)
               VALUES ('batch', 'guild', 'channel', 'm1', 'm1', 'hash', 'v2', 'completed')"""
        )
        self.conn.execute(
            """INSERT INTO extraction_candidates
               (batch_id, candidate_index, memory_type, summary,
                participant_ids, source_message_ids, confidence, rationale)
               VALUES ('batch', 0, 'fact', 'Alice likes science fiction.',
                       '["111"]', '["m1"]', 'high', 'Direct statement')"""
        )

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_durable_individual_is_not_auto_accepted(self):
        result = evaluate(candidate("Alice likes science fiction."))
        self.assertEqual((result.scope, result.durability, result.disposition),
                         ("individual", "durable", "review"))

    def test_evolving_project_and_transient_game_milestone(self):
        self.assertEqual(evaluate(candidate("Alice is currently working on a bot.")).durability,
                         "evolving")
        self.assertEqual(evaluate(candidate("Alice reached the credits with 142 moons.",
                                            kind="event")).durability, "transient")

    def test_lore_needs_multiple_participants_and_still_needs_review(self):
        self.assertEqual(evaluate(candidate("Running joke", "lore")).scope, "uncertain")
        result = evaluate(candidate("Running joke", "lore", ["111", "222"]))
        self.assertEqual((result.scope, result.disposition), ("collective", "review"))

    def test_preview_read_only_guild_scoped_and_record_idempotent(self):
        self.assertEqual(preview(self.conn, guild_id="other"), [])
        rows = preview(self.conn, guild_id="guild")
        self.assertEqual(len(rows), 1)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM candidate_evaluations").fetchone()[0], 0)
        record(self.conn, rows)
        record(self.conn, rows)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM candidate_evaluations").fetchone()[0], 1)
        self.assertEqual(self.conn.execute(
            "SELECT status FROM extraction_candidates").fetchone()[0], "proposed")

    def test_preview_preserves_shared_connection_row_factory(self):
        self.assertIsNone(self.conn.row_factory)
        self.assertEqual(len(preview(self.conn, guild_id="guild")), 1)
        self.assertIsNone(self.conn.row_factory)
        self.assertEqual(self.conn.execute("SELECT 1").fetchone(), (1,))

    def test_invalid_limit_rejected(self):
        with self.assertRaises(ValueError):
            preview(self.conn, guild_id="guild", limit=101)


if __name__ == "__main__":
    unittest.main()
