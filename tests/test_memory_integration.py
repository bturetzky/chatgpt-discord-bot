"""Memory integration regressions using mocked OpenAI/Pinecone clients."""
import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from discord_bot.functions.memory_function import WeatherLookup as StoreMemory
from discord_bot.handlers.vector_handler import VectorHandler
from discord_bot.handlers.vectore_store import VectorStore
from tests.test_reliability import make_handler, make_message


class VectorMemoryTests(unittest.TestCase):
    def test_embedding_retrieval_passes_vector_to_store(self):
        handler = object.__new__(VectorHandler)
        handler.client = MagicMock()
        handler.client.embeddings.create.return_value.data = [MagicMock(embedding=[0.1, 0.2])]
        handler.vector_store = MagicMock()
        handler.vector_store.fetch_context.return_value = [{"summary": "likes gardening"}]
        self.assertEqual(handler.get_relevant_contexts("question"), [{"summary": "likes gardening"}])
        handler.client.embeddings.create.assert_called_once_with(
            input=["question"], model="text-embedding-ada-002"
        )
        handler.vector_store.fetch_context.assert_called_once_with([0.1, 0.2], limit=None)

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


@patch.dict(os.environ, {"MEMORY_RETRIEVAL_ENHANCED": "false"})
class DiscordMemoryIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_retrieved_memory_precedes_history_in_model_input(self):
        handler, message = make_handler(), make_message()
        handler.vector_handler.get_relevant_contexts.return_value = [
            "likes gardening", "likes sci-fi"
        ]
        handler.vector_handler.get_relationship_contexts.return_value = []
        with patch("discord_bot.handlers.discord_handler.asyncio.sleep", new_callable=AsyncMock):
            await handler.process_message(message)
        history = handler.chatgpt_handler.get_response.await_args.args[0]
        self.assertEqual(len(history), 3)
        self.assertTrue(all(item["role"] == "system" for item in history[:2]))
        self.assertIn("likes gardening", str(history[:2]))
        self.assertIn("likes sci-fi", str(history[:2]))
        self.assertEqual(history[-1], {"role": "user", "content": "hi"})

    async def test_relationship_memories_are_prioritized_and_deduplicated(self):
        handler, message = make_handler(), make_message()
        handler.vector_handler.get_relevant_contexts.return_value = ["shared joke", "likes gardening"]
        handler.vector_handler.get_relationship_contexts.return_value = ["shared joke"]
        with patch("discord_bot.handlers.discord_handler.asyncio.sleep", new_callable=AsyncMock):
            await handler.process_message(message)
        history = handler.chatgpt_handler.get_response.await_args.args[0]
        self.assertEqual(len(history), 3)
        self.assertEqual(sum("shared joke" in item["content"] for item in history), 1)
        self.assertIn("shared joke", history[0]["content"])
        handler.vector_handler.get_relationship_contexts.assert_called_once_with(["123"], 4)

    async def test_empty_memory_keeps_history_intact(self):
        handler, message = make_handler(), make_message()
        handler.vector_handler.get_relevant_contexts.return_value = []
        handler.vector_handler.get_relationship_contexts.return_value = []
        with patch("discord_bot.handlers.discord_handler.asyncio.sleep", new_callable=AsyncMock):
            await handler.process_message(message)
        history = handler.chatgpt_handler.get_response.await_args.args[0]
        self.assertEqual(history, [{"role": "user", "content": "hi"}])


if __name__ == "__main__":
    unittest.main()
