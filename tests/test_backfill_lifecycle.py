"""Backfill runs after gateway readiness and always closes the Discord session."""
import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from discord_bot.storage.backfill import main


class BackfillLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_cleanup_after_success_and_failure(self):
        for failure in (None, RuntimeError("backfill failed")):
            with self.subTest(failure=failure):
                client = MagicMock()
                client.__aenter__ = AsyncMock(return_value=client)
                client.__aexit__ = AsyncMock(return_value=None)
                client.login = AsyncMock()
                client.close = AsyncMock()
                ready = asyncio.Event()
                stopped = asyncio.Event()

                async def connect(*, reconnect):
                    ready.set()
                    await stopped.wait()

                async def wait_until_ready():
                    await ready.wait()

                async def close():
                    stopped.set()

                client.connect = AsyncMock(side_effect=connect)
                client.wait_until_ready = AsyncMock(side_effect=wait_until_ready)
                client.close.side_effect = close
                database = MagicMock()
                database.__enter__.return_value = SimpleNamespace(connection=MagicMock())
                database.__exit__.return_value = None
                with patch.dict(os.environ, {
                    "DISCORD_SQLITE_PATH": "/tmp/test-backfill.db",
                    "DISCORD_TOKEN": "fake-token",
                }), patch("discord_bot.storage.backfill.discord.Client", return_value=client), \
                    patch("discord_bot.storage.backfill.Database", return_value=database), \
                    patch("discord_bot.storage.backfill.run_backfill", new_callable=AsyncMock) as run:
                    run.side_effect = failure
                    if failure:
                        with self.assertRaises(RuntimeError):
                            await main(SimpleNamespace(days=30, limit_per_channel=100, dry_run=True))
                    else:
                        await main(SimpleNamespace(days=30, limit_per_channel=100, dry_run=True))
                client.login.assert_awaited_once()
                client.close.assert_awaited_once()
                client.__aexit__.assert_awaited_once()
                run.assert_awaited_once()
