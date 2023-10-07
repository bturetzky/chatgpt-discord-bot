import openai
from .vectore_store import VectorStore

EMBEDDING_MODEL = "text-embedding-ada-002"

import openai

class VectorHandler:
    def __init__(self, openai_apikey, pinecone_apikey):
        openai.api_key = openai_apikey
        self.vector_store = VectorStore(pinecone_apikey)
        self.vector_store.initialize_pinecone()

    def encode_message(self, message):
        model = "text-embedding-ada-002"
        #print(f"Encoding message: {message}")
        response = openai.Embedding.create(input=[message], model=model)
        #print(f"response length: {len(response['data'][0]['embedding'])}")
        return response['data'][0]['embedding']

    def get_relevant_contexts(self, initial_message, namespace):
        query_vector = self.encode_message(initial_message)
        return self.vector_store.fetch_context(query_vector, namespace)

    def store_additional_data(self, summary, namespace):
        #print(f"Storing additional data: {summary}")
        print("Storing additional data in vector store...")
        summary_vector = self.encode_message(summary)
        self.vector_store.store_additional_data(summary_vector, summary, namespace)

    async def close(self):
        await self.vector_store.close()

