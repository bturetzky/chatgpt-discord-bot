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
            await client.login(token)
            gateway = asyncio.create_task(client.connect(reconnect=True))
            ready = asyncio.create_task(client.wait_until_ready())
            try:
                done, _ = await asyncio.wait(
                    (gateway, ready), timeout=45, return_when=asyncio.FIRST_COMPLETED
                )
                if gateway in done:
                    # Propagate a connection error rather than silently completing.
                    await gateway
                    raise RuntimeError("Discord gateway stopped before becoming ready")
                if ready not in done:
                    raise TimeoutError("Discord gateway did not become ready within 45 seconds")
                await ready
                await run_backfill(
                    client, archive, days=args.days,
                    limit_per_channel=args.limit_per_channel, dry_run=args.dry_run,
                )
            finally:
                ready.cancel()
                await asyncio.gather(ready, return_exceptions=True)
                await client.close()
                gateway.cancel()
                await asyncio.gather(gateway, return_exceptions=True)
                # Let aiohttp's SSL transports finish closing before asyncio.run stops the loop.
                await asyncio.sleep(0.25)



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
