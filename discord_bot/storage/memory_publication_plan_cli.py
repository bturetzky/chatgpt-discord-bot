"""Operator-only read-only publication plan. No publication or ledger writes."""
import argparse
import asyncio
import json
import os

from pinecone import Pinecone

from .database import Database
from .memory_consolidation import preview_consolidation
from .memory_evaluation_cli import discover_bot_id
from .memory_publication_plan import plan_entries
from ..handlers.vectore_store import INDEX_NAME


def main():
    parser = argparse.ArgumentParser(description="Preview blocked and reviewable memory publications")
    parser.add_argument("--guild-id", default=os.getenv("REACTION_SHADOW_GUILD_ID"))
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-6.1-terra"))
    args = parser.parse_args()
    if not args.guild_id or not args.guild_id.isdecimal():
        parser.error("--guild-id or REACTION_SHADOW_GUILD_ID required")
    if not 1 <= args.limit <= 100:
        parser.error("--limit must be 1..100")
    for name in ("DISCORD_SQLITE_PATH", "DISCORD_TOKEN", "OPENAI_API_KEY", "PINECONE_API_KEY"):
        if not os.getenv(name):
            parser.error(name + " is required")
    bot_id = asyncio.run(discover_bot_id())
    index = Pinecone(api_key=os.environ["PINECONE_API_KEY"]).Index(INDEX_NAME)
    with Database(os.environ["DISCORD_SQLITE_PATH"]) as db:
        entries = asyncio.run(preview_consolidation(
            db.connection, guild_id=args.guild_id, bot_author_id=bot_id,
            model=args.model, limit=args.limit, index=index))
        result = plan_entries(db.connection, entries, guild_id=args.guild_id,
                              bot_author_id=bot_id)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
