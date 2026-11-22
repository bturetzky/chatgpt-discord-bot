import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from discord_bot.storage.autonomous_memory import run_forever
from discord_bot.storage.discovery_shadow import DiscoveryShadow
from tests.test_prometheus_metrics import sample


class WorkerMetricsTests(unittest.IsolatedAsyncioTestCase):
    async def test_memory_keeps_last_success_through_partial_failure_and_shutdown(self):
        labels = {"worker": "autonomous_memory"}
        before_idle = sample("worker_cycles_total", **labels, outcome="idle")
        before_failure = sample("worker_cycles_total", **labels, outcome="partial_failure")
        stop = asyncio.Event()
        cycle = 0
        last_success = 0

        async def step(*args, **kwargs):
            nonlocal cycle, last_success
            cycle += 1
            self.assertEqual(sample("worker_running", **labels), 1)
            self.assertGreater(sample("worker_cycle_started_timestamp_seconds", **labels), 0)
            if cycle == 1:
                return {"failed": 0, "publication_decisions": {}, "idle_checkpoint_hit": True}
            last_success = sample("worker_last_success_timestamp_seconds", **labels)
            stop.set()
            return {"failed": 1, "publication_decisions": {}, "idle_checkpoint_hit": False}

        with patch("discord_bot.storage.autonomous_memory.INTERVAL_SECONDS", 0.001), patch(
            "discord_bot.storage.autonomous_memory.run_once", side_effect=step,
        ):
            await run_forever(SimpleNamespace(db=None), None, guild_id=1, bot_author_id=2,
                              model="test", stop_event=stop)
        self.assertGreater(last_success, 0)
        self.assertEqual(sample("worker_last_success_timestamp_seconds", **labels), last_success)
        self.assertEqual(sample("worker_cycles_total", **labels, outcome="idle"), before_idle + 1)
        self.assertEqual(sample("worker_cycles_total", **labels, outcome="partial_failure"),
                         before_failure + 1)
        self.assertEqual(sample("worker_running", **labels), 0)
        self.assertEqual(sample("worker_cycle_started_timestamp_seconds", **labels), 0)

    async def test_discovery_stalled_cycle_is_visible_then_clears_on_cancellation(self):
        worker = DiscoveryShadow.__new__(DiscoveryShadow)
        entered = asyncio.Event()

        async def blocked(_hints):
            entered.set()
            await asyncio.Event().wait()

        worker.run_once = blocked
        labels = {"worker": "discovery"}
        before = sample("worker_cycles_total", **labels, outcome="cancelled")
        task = asyncio.create_task(worker.run_forever(dict))
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            self.assertEqual(sample("worker_running", **labels), 1)
            self.assertGreater(sample("worker_cycle_started_timestamp_seconds", **labels), 0)
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(sample("worker_running", **labels), 0)
        self.assertEqual(sample("worker_cycle_started_timestamp_seconds", **labels), 0)
        self.assertEqual(sample("worker_cycles_total", **labels, outcome="cancelled"), before + 1)

    async def test_discovery_unexpected_exit_records_failed_cycle(self):
        worker = DiscoveryShadow.__new__(DiscoveryShadow)
        worker.run_once = AsyncMock(side_effect=RuntimeError("internal detail"))
        labels = {"worker": "discovery"}
        failed = sample("worker_cycles_total", **labels, outcome="failed")
        last_success = sample("worker_last_success_timestamp_seconds", **labels)
        with self.assertRaises(RuntimeError):
            await worker.run_forever(dict)
        self.assertEqual(sample("worker_cycles_total", **labels, outcome="failed"), failed + 1)
        self.assertEqual(sample("worker_last_success_timestamp_seconds", **labels), last_success)
        self.assertEqual(sample("worker_running", **labels), 0)
