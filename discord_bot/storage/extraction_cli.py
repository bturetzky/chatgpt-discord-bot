"""Operator-only, bounded server-culture extraction dry-run CLI.

Example (use a small, settled historical range):
python -m discord_bot.storage.extraction_cli --guild-id "$GUILD_ID" \
  --since 2026-11-08T12:00:00+00:00 --until 2026-11-08T13:00:00+00:00
"""
import argparse
import asyncio
import json
import os
from datetime import datetime

from .database import Database
from .extraction_dry_run import dry_run


def main():
    parser = argparse.ArgumentParser(description="Bounded culture-memory dry-run (no Pinecone writes)")
    parser.add_argument("--guild-id", required=True)
    parser.add_argument("--human-author-id", action="append", required=True,
                        help="trusted human Discord user ID; repeat for each human author")
    parser.add_argument("--since", required=True, help="inclusive ISO-8601 timestamp with timezone")
    parser.add_argument("--until", required=True, help="exclusive ISO-8601 timestamp with timezone")
    parser.add_argument("--max-windows", type=int, default=5)
    parser.add_argument("--max-rows", type=int, default=1000)
    parser.add_argument("--max-messages", type=int, default=40)
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-6.1-terra"))
    args = parser.parse_args()
    since = datetime.fromisoformat(args.since.replace("Z", "+00:00"))
    until = datetime.fromisoformat(args.until.replace("Z", "+00:00"))
    if since.tzinfo is None or until.tzinfo is None:
        parser.error("--since and --until must include timezone")
    path = os.environ.get("DISCORD_SQLITE_PATH")
    if not path:
        parser.error("DISCORD_SQLITE_PATH is required")
    if not os.getenv("OPENAI_API_KEY"):
        parser.error("OPENAI_API_KEY is required")
    with Database(path) as db:
        counts = asyncio.run(dry_run(
            db.connection, guild_id=args.guild_id, since=since, until=until,
            max_windows=args.max_windows, max_rows=args.max_rows,
            max_messages=args.max_messages, model=args.model,
            human_author_ids=args.human_author_id,
            api_key=os.environ["OPENAI_API_KEY"],
        ))
    print(json.dumps(counts, sort_keys=True))


if __name__ == "__main__":
    main()
