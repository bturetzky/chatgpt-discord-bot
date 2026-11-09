"""Operator backfill: python -m discord_bot.storage.backfill --days 30 --limit-per-channel 200"""
import argparse
import asyncio
import logging
import os

import discord

from .database import Database
from .message_archive import MessageArchive
from .history import run_backfill


async def main(args):
    path = os.environ["DISCORD_SQLITE_PATH"]
    token = os.environ["DISCORD_TOKEN"]
    intents = discord.Intents.default()
    intents.message_content = True
    async with discord.Client(intents=intents) as client:
        with Database(path) as database:
            archive = MessageArchive(database)
            completed = False

            @client.event
            async def on_ready():
                nonlocal completed
                if completed:
                    return
                completed = True
                try:
                    await run_backfill(
                        client, archive, days=args.days,
                        limit_per_channel=args.limit_per_channel, dry_run=args.dry_run,
                    )
                finally:
                    await client.close()

            await client.start(token)



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bounded, resumable Discord history backfill")
    parser.add_argument("--days", type=int, required=True)
    parser.add_argument("--limit-per-channel", type=int, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.days < 1 or not 1 <= args.limit_per_channel <= 1000:
        parser.error("--days must be positive and --limit-per-channel must be 1..1000")
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main(args))
