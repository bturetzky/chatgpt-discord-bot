"""Memory integration regressions using mocked OpenAI/Pinecone clients."""
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from discord_bot.functions.memory_function import WeatherLookup as StoreMemory
from discord_bot.handlers.vector_handler import VectorHandler
from discord_bot.handlers.vectore_store import VectorStore
from discord_bot.memory_selection import retrieve_and_select
from tests.test_reliability import make_handler, make_message


class VectorMemoryTests(unittest.TestCase):
    def test_embedding_retrieval_passes_vector_to_store(self):
        handler = object.__new__(VectorHandler)
        handler.client = MagicMock()
        handler.client.embeddings.create.return_value.data = [MagicMock(embedding=[0.1, 0.2])]
        handler.vector_store = MagicMock()
        retrieve_and_select(handler, "question", [])
        handler.client.embeddings.create.assert_called_once_with(
            input=["question"], model="text-embedding-ada-002"
        )
        handler.vector_store.fetch_context.assert_called_once_with([0.1, 0.2], limit=16, diagnostics=[])

    def test_store_embeds_and_upserts_summary(self):
        handler = object.__new__(VectorHandler)
        handler.client = MagicMock()
        handler.client.embeddings.create.return_value.data = [MagicMock(embedding=[0.3])]
        handler.vector_store = MagicMock()
        handler.store_additional_data("likes gardening")
        handler.vector_store.store_additional_data.assert_called_once_with([0.3], "likes gardening", memory_type="fact", participant_ids=None)

    def test_pinecone_empty_matches(self):
        store = VectorStore("fake-key")
        store.index = MagicMock()
        store.index.query.return_value = {"matches": []}
        self.assertEqual(store.fetch_context([0.1]), [])

    def test_pinecone_query_failure_returns_none(self):
        store = VectorStore("fake-key")
        store.index = MagicMock()
        store.index.query.side_effect = RuntimeError("unavailable")
        self.assertIsNone(store.fetch_context([0.1]))

    def test_pinecone_upsert_preserves_summary(self):
        store = VectorStore("fake-key")
        store.index = MagicMock()
        store.store_additional_data([0.1], "likes gardening")
        vectors = store.index.upsert.call_args.kwargs["vectors"]
        self.assertEqual(vectors[0]["values"], [0.1])
        self.assertEqual(vectors[0]["metadata"], {"summary": "likes gardening", "memory_type": "fact"})
        self.assertTrue(vectors[0]["id"])


class MemoryToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_memory_tool_writes_timestamped_text(self):
        vector = MagicMock()
        with patch("discord_bot.functions.memory_function.VectorHandler", return_value=vector):
            tool = StoreMemory()
        with patch("discord_bot.functions.memory_function.datetime") as clock:
            clock.now.return_value.strftime.return_value = "2026-11-07 08:00:00"
            result = await tool.execute({"memory": "likes gardening"})
        self.assertEqual(result, "Memory stored.")
        vector.store_additional_data.assert_called_once_with("2026-11-07 08:00:00: likes gardening", memory_type="fact", participant_ids=[])


class DiscordMemoryIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def configure_matches(self, handler, semantic, relationship=()):
        store = VectorStore("fake-key")
        store.index = MagicMock()
        handler.vector_handler.vector_store = store
        store.index.query.side_effect = [{"matches": semantic}, {"matches": relationship}]
        return store

    async def test_retrieved_memory_precedes_history_in_single_section(self):
        handler, message = make_handler(), make_message()
        self.configure_matches(handler, [
            {"metadata": {"summary": "likes gardening"}},
            {"metadata": {"summary": "likes sci-fi"}},
        ])
        with patch("discord_bot.handlers.discord_handler.asyncio.sleep", new_callable=AsyncMock):
            await handler.process_message(message)
        history = handler.chatgpt_handler.get_response.await_args.args[0]
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["role"], "system")
        self.assertIn("likes gardening", history[0]["content"])
        self.assertIn("likes sci-fi", history[0]["content"])
        self.assertEqual(history[-1], {"role": "user", "content": "hi"})

    async def test_relationship_memories_are_participant_filtered_and_deduplicated(self):
        handler, message = make_handler(), make_message()
        message.content = "What happened at the last game night?"
        relationship = {"metadata": {
            "summary": "shared joke", "memory_type": "relationship", "participant_ids": ["123"],
        }}
        other = {"metadata": {
            "summary": "other participants' tradition", "memory_type": "relationship",
            "participant_ids": ["456"],
        }}
        handler.get_message_history.return_value = [
            {"role": "user", "content": "friend (Discord ID 123): Discord ID 456"},
        ]
        store = self.configure_matches(handler, [relationship, other], [relationship])
        with patch("discord_bot.handlers.discord_handler.asyncio.sleep", new_callable=AsyncMock):
            await handler.process_message(message)
        history = handler.chatgpt_handler.get_response.await_args.args[0]
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["content"].count("shared joke"), 1)
        self.assertNotIn("other participants", history[0]["content"])
        query = store.index.query.call_args.kwargs
        self.assertEqual(query["top_k"], 4)
        self.assertEqual(query["filter"]["$and"][1]["participant_ids"]["$in"], ["123"])

    async def test_empty_memory_keeps_history_intact(self):
        handler, message = make_handler(), make_message()
        self.configure_matches(handler, [])
        with patch("discord_bot.handlers.discord_handler.asyncio.sleep", new_callable=AsyncMock):
            await handler.process_message(message)
        history = handler.chatgpt_handler.get_response.await_args.args[0]
        self.assertEqual(history, [{"role": "user", "content": "hi"}])
        handler.vector_handler.client.responses.create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
