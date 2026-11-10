"""Memory capture and retrieval regressions without external credentials."""
import unittest
from unittest.mock import MagicMock

from discord_bot.handlers.vectore_store import VectorStore
from discord_bot.handlers.chatgpt_handler import ChatGPTHandler
from discord_bot.handlers.discord_handler import DiscordHandler


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
        self.assertEqual(store.index.query.call_args.kwargs["top_k"], 8)

    def test_identical_fact_upserts_same_id_despite_timestamp(self):
        store = VectorStore("test-key")
        store.index = MagicMock()
        store.store_additional_data([0.1], "2026-11-07 10:00:00: Alan owns two cats")
        store.store_additional_data([0.1], "2026-11-07 11:00:00: alan   owns TWO cats")
        first = store.index.upsert.call_args_list[0].kwargs["vectors"][0]
        second = store.index.upsert.call_args_list[1].kwargs["vectors"][0]
        self.assertEqual(first["id"], second["id"])
        self.assertTrue(first["id"].startswith("memory-v1-"))

    def test_distinct_facts_get_distinct_ids(self):
        store = VectorStore("test-key")
        store.index = MagicMock()
        store.store_additional_data([0.1], "2026-11-07 10:00:00: Alan owns two cats")
        store.store_additional_data([0.1], "2026-11-07 10:00:01: Bowen owns two cats")
        first = store.index.upsert.call_args_list[0].kwargs["vectors"][0]["id"]
        second = store.index.upsert.call_args_list[1].kwargs["vectors"][0]["id"]
        self.assertNotEqual(first, second)

    def test_empty_matches(self):
        store = VectorStore("test-key")
        store.index = MagicMock()
        store.index.query.return_value = {"matches": []}
        self.assertEqual(store.fetch_context([0.1]), [])

    def test_conversation_query_includes_multiple_people_not_bot(self):
        history = [
            {"role": "user", "content": "Bowen (Discord ID 12): I like dogs"},
            {"role": "assistant", "content": "Got it"},
            {"role": "user", "content": "Alan (Discord ID 34): I have two cats"},
            {"role": "user", "content": "Bowen (Discord ID 12): What about pets?"},
        ]
        query = DiscordHandler.build_memory_query(history)
        self.assertIn("Bowen (Discord ID 12): I like dogs", query)
        self.assertIn("Alan (Discord ID 34): I have two cats", query)
        self.assertNotIn("Got it", query)

    def test_conversation_query_is_bounded_and_prefers_recent_turns(self):
        history = [{"role": "user", "content": f"Speaker {i}: " + "x" * 80} for i in range(12)]
        query = DiscordHandler.build_memory_query(history, max_turns=3, max_chars=200)
        self.assertLessEqual(len(query), 202)
        self.assertIn("Speaker 11", query)
        self.assertNotIn("Speaker 0", query)

    def test_memory_tool_requires_explicit_request(self):
        handler = object.__new__(ChatGPTHandler)
        prompt = handler.get_response_system_prompt_content("@bot")
        self.assertIn("Use store_memory only when a human explicitly asks", prompt)
        self.assertIn("Do not call store_memory for unsolicited facts", prompt)
        self.assertIn("separate automatic memory pipeline", prompt)
        self.assertIn("standalone", prompt)
        self.assertIn("Never store credentials", prompt)
        self.assertIn("any participant", prompt)


if __name__ == "__main__":
    unittest.main()
