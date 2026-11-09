"""Standalone backfill must release the Discord HTTP session on all exit paths."""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from discord_bot.storage.backfill import main


class BackfillLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_client_context_closes_after_success_and_failure(self):
        for failure in (None, RuntimeError("backfill failed")):
            with self.subTest(failure=failure):
                client = MagicMock()
                client.__aenter__ = AsyncMock(return_value=client)
                client.__aexit__ = AsyncMock(return_value=None)
                client.close = AsyncMock()

                def register(callback):
                    client.on_ready = callback
                    return callback

                client.event.side_effect = register

                async def start(_token):
                    await client.on_ready()

                client.start = AsyncMock(side_effect=start)
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
                client.close.assert_awaited_once()
                client.__aexit__.assert_awaited_once()
