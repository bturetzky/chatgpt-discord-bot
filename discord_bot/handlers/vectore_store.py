import hashlib
import logging
import os
import re
from pinecone import Pinecone

from ..memory_selection import normalize_matches

INDEX_NAME = "discord-bot-context2"
# This comes from the model we're using for embeddings, ada-002
DIMENSIONS = 1536
RETRIEVAL_LIMIT = int(os.getenv("SEMANTIC_MEMORY_LIMIT", "8"))

class VectorStore:
    def __init__(self, pinecone_api_key):
        self.pinecone_api_key = pinecone_api_key
        self.index = None
        self.index_name = INDEX_NAME

    def initialize_pinecone(self):
        pc = Pinecone(api_key=self.pinecone_api_key)
        #if self.index_name not in pc.list_indexes():
        #    pc.create_index(name=self.index_name, metric="cosine", dimension=DIMENSIONS)
        self.index = pc.Index(self.index_name)

    def store_additional_data(self, vector, summary, memory_type="fact", participant_ids=None):
        # Stable IDs make repeated writes of the same fact idempotent, even when
        # the tool prepends a different timestamp on each invocation.
        fact = re.sub(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}:\s*", "", summary).strip()
        normalized = " ".join(fact.casefold().split())
        unique_id = "memory-v1-" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        #print(f"Storing additional data: {summary} with uuid {unique_id} in namespace {namespace}")
        memory_type = memory_type if memory_type in {"fact", "relationship", "event"} else "fact"
        participant_ids = sorted({str(i) for i in (participant_ids or []) if str(i).isdigit()})
        metadata = {"summary": summary, "memory_type": memory_type}
        if participant_ids:
            metadata["participant_ids"] = participant_ids
        self.index.upsert(vectors=[{
            'id': unique_id,
            'values': vector,
            'metadata': metadata
        }])

    def fetch_context(self, query_vector, limit=None, participant_ids=None, memory_type=None, diagnostics=None):
        try:
            #print(f"index is...: {self.index}")
            query_filter = None
            if memory_type and participant_ids:
                query_filter = {"$and": [
                    {"memory_type": {"$eq": memory_type}},
                    {"participant_ids": {"$in": [str(i) for i in participant_ids]}}
                ]}
            options = {"filter": query_filter} if query_filter else {}
            results = self.index.query(
                **options,
                top_k=RETRIEVAL_LIMIT if limit is None else limit,  # Number of closest vectors to retrieve
                include_values=False,  # Whether to include the vectors themselves in the response
                include_metadata=True,  # Whether to include any metadata stored alongside vectors
                vector=query_vector     # The query vector
            )
            matches = normalize_matches(results)
            if diagnostics is not None:
                diagnostics.extend(matches)
            return [match["summary"] for match in matches]
        except Exception as exc:
            logging.warning("Memory vector lookup failed: error_type=%s", type(exc).__name__)
            return None


    async def close(self):
        # Pinecone's client/index use HTTP connections; no global deinit API exists.
        # The SDK manages connection cleanup; retain this hook for the handler.
        pass
