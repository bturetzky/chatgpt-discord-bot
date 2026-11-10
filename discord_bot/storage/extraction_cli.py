"""Operator-only, bounded server-culture extraction dry-run CLI.

Example (use a small, settled historical range):
python -m discord_bot.storage.extraction_cli --guild-id "$GUILD_ID" \
  --since 2026-11-08T12:00:00+00:00 --until 2026-11-08T13:00:00+00:00
"""
import argparse
import asyncio
import json
import os
import aiohttp
from datetime import datetime

from .database import Database
from .extraction_dry_run import dry_run


def main():
    parser = argparse.ArgumentParser(description="Bounded culture-memory dry-run (no Pinecone writes)")
    parser.add_argument("--guild-id", default=os.getenv("REACTION_SHADOW_GUILD_ID"),
                        help="Defaults to REACTION_SHADOW_GUILD_ID from deployment")
    parser.add_argument("--since", required=True, help="inclusive ISO-8601 timestamp with timezone")
    parser.add_argument("--until", required=True, help="exclusive ISO-8601 timestamp with timezone")
    parser.add_argument("--max-windows", type=int, default=5)
    parser.add_argument("--max-rows", type=int, default=1000)
    parser.add_argument("--max-messages", type=int, default=40)
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-6.1-terra"))
    args = parser.parse_args()
    if not args.guild_id or not args.guild_id.isdecimal():
        parser.error("--guild-id or numeric REACTION_SHADOW_GUILD_ID is required")
    since = datetime.fromisoformat(args.since.replace("Z", "+00:00"))
    until = datetime.fromisoformat(args.until.replace("Z", "+00:00"))
    if since.tzinfo is None or until.tzinfo is None:
        parser.error("--since and --until must include timezone")
    path = os.environ.get("DISCORD_SQLITE_PATH")
    if not path:
        parser.error("DISCORD_SQLITE_PATH is required")
    if not os.getenv("OPENAI_API_KEY"):
        parser.error("OPENAI_API_KEY is required")
    async def bot_id_from_discord():
        token = os.environ.get("DISCORD_TOKEN")
        if not token:
            parser.error("DISCORD_TOKEN is required to identify the bot")
        async with aiohttp.ClientSession() as session:
            async with session.get("https://discord.com/api/v10/users/@me",
                                   headers={"Authorization": f"Bot {token}"},
                                   timeout=aiohttp.ClientTimeout(total=10)) as response:
                response.raise_for_status()
                data = await response.json()
                return str(data["id"])

    bot_author_id = asyncio.run(bot_id_from_discord())
    with Database(path) as db:
        counts = asyncio.run(dry_run(
            db.connection, guild_id=args.guild_id, since=since, until=until,
            max_windows=args.max_windows, max_rows=args.max_rows,
            max_messages=args.max_messages, model=args.model,
            bot_author_id=bot_author_id,
            api_key=os.environ["OPENAI_API_KEY"],
        ))
    print(json.dumps(counts, sort_keys=True))


if __name__ == "__main__":
    main()
