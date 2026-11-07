import unittest
from unittest.mock import MagicMock, patch

from discord_bot.handlers.vectore_store import VectorStore


class RelationshipMemoryTests(unittest.TestCase):
    def setUp(self):
        self.store = VectorStore("test")
        self.store.index = MagicMock()

    def test_write_relationship_metadata(self):
        self.store.store_additional_data([0.1], "2026-11-07 10:00:00: Alan and Bowen joke about easy mode", memory_type="relationship", participant_ids=["123", "456", "not-an-id"])
        record = self.store.index.upsert.call_args.kwargs["vectors"][0]
        self.assertEqual(record["metadata"]["memory_type"], "relationship")
        self.assertEqual(record["metadata"]["participant_ids"], ["123", "456"])

    def test_filtered_retrieval(self):
        self.store.index.query.return_value = {"matches": [{"metadata": {"summary": "A shared joke"}}]}
        self.assertEqual(self.store.fetch_context([0.1], limit=4, participant_ids=["123"], memory_type="relationship"), ["A shared joke"])
        query = self.store.index.query.call_args.kwargs
        self.assertEqual(query["top_k"], 4)
        self.assertEqual(query["filter"]["$and"][1]["participant_ids"]["$in"], ["123"])

    def test_legacy_unfiltered_retrieval(self):
        self.store.index.query.return_value = {"matches": [{"metadata": {"summary": "Old memory"}}]}
        self.assertEqual(self.store.fetch_context([0.1], limit=8), ["Old memory"])
        self.assertNotIn("filter", self.store.index.query.call_args.kwargs)


if __name__ == "__main__":
    unittest.main()
