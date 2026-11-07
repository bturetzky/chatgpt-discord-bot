"""Memory capture and retrieval regressions without external credentials."""
import unittest
from unittest.mock import MagicMock

from discord_bot.handlers.vectore_store import VectorStore
from discord_bot.handlers.chatgpt_handler import ChatGPTHandler


class MemoryRecallTests(unittest.TestCase):
    def test_retrieval_returns_clean_summary_text(self):
        store = VectorStore("test-key")
        store.index = MagicMock()
        store.index.query.return_value = {"matches": [
            {"metadata": {"summary": "Alice grows tomatoes"}, "score": 0.9},
            {"metadata": {"summary": ""}},
            {"metadata": {"unrelated": "value"}},
            {"metadata": {"summary": "Bob enjoys science fiction"}},
        ]}
        self.assertEqual(
            store.fetch_context([0.1, 0.2]),
            ["Alice grows tomatoes", "Bob enjoys science fiction"],
        )
        self.assertEqual(store.index.query.call_args.kwargs["top_k"], 9)

    def test_empty_matches(self):
        store = VectorStore("test-key")
        store.index = MagicMock()
        store.index.query.return_value = {"matches": []}
        self.assertEqual(store.fetch_context([0.1]), [])

    def test_capture_instructions_encourage_ordinary_context(self):
        handler = object.__new__(ChatGPTHandler)
        prompt = handler.get_response_system_prompt_content("@bot")
        self.assertIn("Ordinary concrete facts", prompt)
        self.assertIn("standalone", prompt)
        self.assertIn("Never store credentials", prompt)


if __name__ == "__main__":
    unittest.main()
