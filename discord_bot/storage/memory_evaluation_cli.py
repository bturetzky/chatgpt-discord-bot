"""Operator-only memory evaluation preview; never publishes memories."""
import argparse
import asyncio
import json
import os

import aiohttp

from .database import Database
from .evidence_evaluation import EVALUATOR_VERSION as EVIDENCE_VERSION, evaluate_evidence
from .memory_evaluation import preview, record


async def discover_bot_id():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise ValueError("DISCORD_TOKEN is required for verified bot identity")
    async with aiohttp.ClientSession() as session:
        async with session.get(
            "https://discord.com/api/v10/users/@me",
            headers={"Authorization": f"Bot {token}"},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as response:
            response.raise_for_status()
            data = await response.json()
            return str(data["id"])


def main():
    parser = argparse.ArgumentParser(description="Preview candidate triage (no Pinecone writes)")
    parser.add_argument("--guild-id", required=True)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--evidence", action="store_true",
                        help="Validate source provenance and call model on human evidence")
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-6.1-terra"))
    parser.add_argument("--record", action="store_true",
                        help="Explicitly persist review/exclusion assessments in SQLite")
    args = parser.parse_args()
    path = os.getenv("DISCORD_SQLITE_PATH")
    if not path:
        parser.error("DISCORD_SQLITE_PATH is required")
    if args.evidence and not os.getenv("OPENAI_API_KEY"):
        parser.error("OPENAI_API_KEY is required for evidence evaluation")
    if not 1 <= args.limit <= 100:
        parser.error("--limit must be 1..100")
    bot_id = asyncio.run(discover_bot_id()) if args.evidence else None
    with Database(path) as db:
        if args.evidence:
            entries = asyncio.run(evaluate_evidence(
                db.connection, guild_id=args.guild_id, limit=args.limit,
                bot_author_id=bot_id, model=args.model))
        else:
            entries = preview(db.connection, guild_id=args.guild_id, limit=args.limit)
        if args.record:
            record(db.connection, entries, evaluator_version=(
                EVIDENCE_VERSION if args.evidence else "triage-v1"))
    print(json.dumps({"count": len(entries), "recorded": args.record,
                      "mode": "evidence" if args.evidence else "triage",
                      "candidates": entries}, indent=2))


if __name__ == "__main__":
    main()
