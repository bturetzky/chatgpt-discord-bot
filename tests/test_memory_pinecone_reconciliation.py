"""Strict read-only Pinecone reconciliation tests; no network calls."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from discord_bot.storage.database import Database
from discord_bot.storage.memory_publication_ledger import stage_create
from discord_bot.storage.memory_pinecone_reconciliation import (
    classify_fetch, expected_metadata, fetch_revision,
)


class FakeIndex:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def fetch(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.tmp.name) / "memory.sqlite")).open()
        self.db.connection.execute(
            """INSERT INTO messages
               (guild_id, channel_id, message_id, author_id, content, created_at)
               VALUES ('1', '2', '4', '3', 'I like puzzles', '2026-11-01T00:00:00Z')"""
        )
        stage_create(self.db.connection, {
            "proposal_id": "proposal-v1-test", "decision": "review_required",
            "operation": "create", "blockers": [],
            "memory": {"guild_id": "1", "source_channel_id": "2",
                       "scope": "individual", "durability": "durable",
                       "summary": "User likes puzzles.", "participant_ids": ["3"],
                       "source_message_ids": ["4"]},
        }, memory_id="logical-1", bot_author_id="9")
        self.expected = expected_metadata(self.db.connection, "logical-1", 1)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_matching_fetch_with_namespace(self):
        index = FakeIndex({"vectors": {"v": {"metadata": dict(self.expected)}}})
        result = fetch_revision(index, self.db.connection, memory_id="logical-1",
                                revision=1, vector_id="v", namespace="dev")
        self.assertEqual(result["observation"], "matching")
        self.assertTrue(result["matching_vector"])
        self.assertEqual(index.calls, [{"ids": ["v"], "namespace": "dev"}])

    def test_missing_is_not_confirmed(self):
        result = classify_fetch({"vectors": {}}, vector_id="v", expected=self.expected)
        self.assertEqual(result["observation"], "missing")
        self.assertFalse(result["matching_vector"])

    def test_legacy_metadata_is_not_confirmed(self):
        result = classify_fetch({"vectors": {"v": {"metadata": {"summary": "User likes puzzles."}}}},
                                vector_id="v", expected=self.expected)
        self.assertEqual(result["observation"], "mismatched")

    def test_every_identity_field_must_match(self):
        for field in self.expected:
            with self.subTest(field=field):
                bad = dict(self.expected)
                if field == "participant_ids":
                    bad[field] = ["999"]
                elif field == "revision":
                    bad[field] = 2
                else:
                    bad[field] = "incorrect"
                result = classify_fetch(
                    {"vectors": {"v": {"metadata": bad}}}, vector_id="v",
                    expected=self.expected)
                self.assertEqual(result["observation"], "mismatched")

    def test_sdk_object_shape(self):
        response = SimpleNamespace(vectors={"v": SimpleNamespace(metadata=dict(self.expected))})
        self.assertEqual(classify_fetch(
            response, vector_id="v", expected=self.expected)["observation"], "matching")

    def test_timeout_is_unknown_not_missing(self):
        index = FakeIndex(error=TimeoutError("network failure"))
        result = fetch_revision(index, self.db.connection, memory_id="logical-1",
                                revision=1, vector_id="v")
        self.assertEqual(result["observation"], "unknown")
        self.assertFalse(result["matching_vector"])

    def test_invalid_response_is_unknown(self):
        self.assertEqual(classify_fetch(
            None, vector_id="v", expected=self.expected)["observation"], "unknown")

    def test_unknown_revision_fails_before_network(self):
        index = FakeIndex({"vectors": {}})
        with self.assertRaises(ValueError):
            fetch_revision(index, self.db.connection, memory_id="logical-1",
                           revision=2, vector_id="v")
        self.assertEqual(index.calls, [])


if __name__ == "__main__":
    unittest.main()
