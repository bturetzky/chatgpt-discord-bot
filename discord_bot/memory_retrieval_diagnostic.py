"""Read-only operator preview of current Pinecone memory retrieval.

Run: python -m discord_bot.memory_retrieval_diagnostic --query "What games do I play?"
Never logs or writes query text or retrieved memory bodies outside explicit CLI output.
"""
import argparse
import json
import os

from .handlers.vector_handler import VectorHandler
from .memory_selection import retrieve_and_select


def inspect(query, participant_ids, *, semantic_limit=None, relationship_limit=None):
    if not os.getenv("OPENAI_API_KEY") or not os.getenv("PINECONE_API_KEY"):
        raise SystemExit("OPENAI_API_KEY and PINECONE_API_KEY required")
    handler = VectorHandler(
        os.environ["OPENAI_API_KEY"], os.environ["PINECONE_API_KEY"]
    )
    candidates = {}
    context, decisions = retrieve_and_select(
        handler,
        query,
        participant_ids,
        semantic_pool=semantic_limit,
        relationship_pool=relationship_limit,
        candidates=candidates,
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


def main():
    parser = argparse.ArgumentParser(
        description="Read-only semantic/relationship memory retrieval preview"
    )
    parser.add_argument(
        "--query",
        required=True,
        help="Exact text to embed; use the full recent-user-turn query to reproduce production",
    )
    parser.add_argument(
        "--participant-id",
        action="append",
        default=[],
        help="Discord participant ID; repeat for multiple users",
    )
    parser.add_argument("--semantic-limit", type=int)
    parser.add_argument("--relationship-limit", type=int)
    parser.add_argument(
        "--json",
        action="store_true",
        help="Structured output (default is readable JSON too)",
    )
    args = parser.parse_args()
    if (args.semantic_limit is not None and not 1 <= args.semantic_limit <= 50) or (
        args.relationship_limit is not None and not 0 <= args.relationship_limit <= 20
    ):
        parser.error("semantic limit must be 1..50; relationship limit must be 0..20")
    if any(not value.isdecimal() for value in args.participant_id):
        parser.error("--participant-id must be numeric")
    result = inspect(
        args.query,
        list(dict.fromkeys(args.participant_id)),
        semantic_limit=args.semantic_limit,
        relationship_limit=args.relationship_limit,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
