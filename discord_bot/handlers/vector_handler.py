"""Embeddings used for the existing 1536-dimensional Pinecone index."""
from openai import OpenAI

from .vectore_store import VectorStore

EMBEDDING_MODEL = "text-embedding-ada-002"


class VectorHandler:
    _instance = None

    def __new__(cls, openai_apikey=None, pinecone_apikey=None):
        if cls._instance is None:
            instance = super().__new__(cls)
            instance.client = OpenAI(api_key=openai_apikey)
            instance.vector_store = VectorStore(pinecone_apikey)
            instance.vector_store.initialize_pinecone()
            cls._instance = instance
        return cls._instance

    def encode_message(self, message):
        response = self.client.embeddings.create(
            input=[message], model=EMBEDDING_MODEL
        )
        return response.data[0].embedding

    def get_relevant_contexts(self, initial_message, limit=None):
        query_vector = self.encode_message(initial_message)
        return self.vector_store.fetch_context(query_vector, limit=limit)

    def get_relationship_contexts(self, participant_ids, limit=4):
        if not participant_ids:
            return []
        query_vector = self.encode_message("established relationships, running jokes, shared experiences, and conversational preferences")
        return self.vector_store.fetch_context(query_vector, limit=limit, participant_ids=participant_ids, memory_type="relationship")

    def store_additional_data(self, summary, memory_type="fact", participant_ids=None):
        summary_vector = self.encode_message(summary)
        self.vector_store.store_additional_data(summary_vector, summary, memory_type=memory_type, participant_ids=participant_ids)

    async def close(self):
        await self.vector_store.close()
