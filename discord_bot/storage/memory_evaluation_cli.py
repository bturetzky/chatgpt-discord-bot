"""Operator-only memory evaluation preview; never publishes memories."""
import argparse
import json
import os

from .database import Database
from .memory_evaluation import preview, record


def main():
    parser = argparse.ArgumentParser(description="Preview candidate triage (no Pinecone writes)")
    parser.add_argument("--guild-id", required=True)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--record", action="store_true",
                        help="Explicitly persist review-only assessments in SQLite")
    args = parser.parse_args()
    path = os.getenv("DISCORD_SQLITE_PATH")
    if not path:
        parser.error("DISCORD_SQLITE_PATH is required")
    with Database(path) as db:
        entries = preview(db.connection, guild_id=args.guild_id, limit=args.limit)
        if args.record:
            record(db.connection, entries)
    print(json.dumps({"count": len(entries), "recorded": args.record,
                      "candidates": entries}, indent=2))


if __name__ == "__main__":
    main()
