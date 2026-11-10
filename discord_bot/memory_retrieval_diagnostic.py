"""Read-only operator preview of current Pinecone memory retrieval.

Run: python -m discord_bot.memory_retrieval_diagnostic --query "What games do I play?"
Never logs or writes query text or retrieved memory bodies outside explicit CLI output.
"""
import argparse
import json
import os

from .handlers.vectore_store import RETRIEVAL_LIMIT
from .handlers.vector_handler import EMBEDDING_MODEL, VectorHandler
from .memory_selection import enabled, normalize_matches, retrieve_and_select


def preview(semantic, relationship, *, semantic_limit=RETRIEVAL_LIMIT, relationship_limit=4):
    """Model the current injection path, including exact-text deduplication."""
    selected = []
    seen = set()
    for item in relationship[:relationship_limit] + semantic[:semantic_limit]:
        if item["summary"] not in seen:
            selected.append(item["summary"])
            seen.add(item["summary"])
    return {
        "semantic_matches": semantic,
        "relationship_matches": relationship,
        "current_injection": selected,
        "injected_count": len(selected),
        "injected_characters": sum(len(s) for s in selected),
        "note": "Current production retrieval does not filter by similarity score. "
                "This is a read-only preview; token counts and relevance decisions are not inferred.",
    }


def inspect(query, participant_ids, *, semantic_limit=None, relationship_limit=None, latest=None):
    from openai import OpenAI
    from pinecone import Pinecone
    from .handlers.vectore_store import INDEX_NAME
    if not os.getenv("OPENAI_API_KEY") or not os.getenv("PINECONE_API_KEY"):
        raise SystemExit("OPENAI_API_KEY and PINECONE_API_KEY required")
    if enabled():
        handler = VectorHandler(os.environ["OPENAI_API_KEY"], os.environ["PINECONE_API_KEY"])
        candidates = {}
        context, decisions = retrieve_and_select(
            handler, query, query if latest is None else latest, participant_ids,
            semantic_pool=semantic_limit, relationship_pool=relationship_limit, candidates=candidates,
        )
        selected = sum(item["reason"] == "selected" for item in decisions)
        return {
            **candidates,
            "retrieved_count": len(decisions),
            "injected_count": selected,
            "rejected_count": len(decisions) - selected,
            "injected_characters": len(context),
            "context": context,
            "decisions": decisions,
        }
    semantic_limit = RETRIEVAL_LIMIT if semantic_limit is None else semantic_limit
    if relationship_limit is None:
        relationship_limit = int(os.getenv("RELATIONSHIP_MEMORY_LIMIT", "4"))
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    index = Pinecone(api_key=os.environ["PINECONE_API_KEY"]).Index(INDEX_NAME)

    def search(text, limit, query_filter=None):
        embedding = client.embeddings.create(model=EMBEDDING_MODEL, input=[text]).data[0].embedding
        kwargs = {"vector": embedding, "top_k": limit, "include_values": False, "include_metadata": True}
        if query_filter:
            kwargs["filter"] = query_filter
        return normalize_matches(index.query(**kwargs))

    semantic = search(query, semantic_limit)
    relationship = []
    if participant_ids and relationship_limit > 0:
        query_filter = {"$and": [
            {"memory_type": {"$eq": "relationship"}},
            {"participant_ids": {"$in": participant_ids}},
        ]}
        relationship = search(
            "established relationships, running jokes, shared experiences, and conversational preferences",
            relationship_limit, query_filter,
        )
    result = preview(semantic, relationship, semantic_limit=semantic_limit, relationship_limit=relationship_limit)
    result.update({"query": query, "participant_ids": participant_ids,
                   "semantic_limit": semantic_limit, "relationship_limit": relationship_limit})
    return result


def main():
    parser = argparse.ArgumentParser(description="Read-only semantic/relationship memory retrieval preview")
    parser.add_argument("--query", required=True, help="Exact text to embed; use the full recent-user-turn query to reproduce production")
    parser.add_argument("--participant-id", action="append", default=[], help="Discord participant ID; repeat for multiple users")
    parser.add_argument("--semantic-limit", type=int)
    parser.add_argument("--relationship-limit", type=int)
    parser.add_argument("--latest", help="Latest addressed message without speaker prefix, for enhanced multi-turn previews")
    parser.add_argument("--json", action="store_true", help="Structured output (default is readable JSON too)")
    args = parser.parse_args()
    if ((args.semantic_limit is not None and not 1 <= args.semantic_limit <= 50)
            or (args.relationship_limit is not None and not 0 <= args.relationship_limit <= 20)):
        parser.error("semantic limit must be 1..50; relationship limit must be 0..20")
    if any(not value.isdecimal() for value in args.participant_id):
        parser.error("--participant-id must be numeric")
    result = inspect(args.query, list(dict.fromkeys(args.participant_id)),
                     semantic_limit=args.semantic_limit, relationship_limit=args.relationship_limit, latest=args.latest)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
