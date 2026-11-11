import unittest
from unittest.mock import MagicMock, patch
from discord_bot.handlers.vectore_store import VectorStore
from discord_bot.memory_selection import normalize_matches
from discord_bot.memory_retrieval_diagnostic import inspect


class RetrievalDiagnosticTests(unittest.TestCase):
    def test_scores_and_types_preserved_and_bad_metadata_ignored(self):
        rows = normalize_matches({"matches": [
            {"score": 0.87, "metadata": {"summary": "A likes gardening", "memory_type": "fact"}},
            {"score": 0.1, "metadata": {"summary": ""}},
            {"metadata": {"other": "missing"}},
            {"score": 0.2, "metadata": {"summary": "Legacy fact"}},
        ]})
        self.assertEqual([r["score"] for r in rows], [0.87, 0.2])
        self.assertEqual(rows[1]["memory_type"], "legacy/unspecified")

    def test_live_diagnostics_do_not_change_retrieved_text(self):
        store = VectorStore('test')
        store.index = MagicMock()
        store.index.query.return_value = {'matches': [
            {'score': 0.91, 'metadata': {'summary': 'Alice grows tomatoes', 'memory_type': 'fact'}},
            {'score': 0.15, 'metadata': {'summary': 'Unrelated fact'}},
        ]}
        diagnostics = []
        self.assertEqual(store.fetch_context([0.1], diagnostics=diagnostics),
                         ['Alice grows tomatoes', 'Unrelated fact'])
        self.assertEqual([m['score'] for m in diagnostics], [0.91, 0.15])
        self.assertEqual(store.fetch_context([0.1]), ['Alice grows tomatoes', 'Unrelated fact'])

    def test_empty_results(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "mock", "PINECONE_API_KEY": "mock"}), patch(
            "discord_bot.memory_retrieval_diagnostic.VectorHandler"
        ) as handler:
            result = inspect("What games do I play?", [])
        self.assertEqual(result["injected_count"], 0)
        self.assertEqual(result["retrieved_count"], 0)
        self.assertEqual(result["context"], "")
        handler.return_value.client.responses.create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
