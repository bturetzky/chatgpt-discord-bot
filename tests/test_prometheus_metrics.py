import asyncio
import json
import os
import socket
import subprocess
import sys
import textwrap
import unittest
from unittest.mock import AsyncMock, patch

import aiohttp

from discord_bot import app, metrics
from discord_bot.handlers.chatgpt_handler import ChatGPTHandler, FallbackReply
from discord_bot.handlers.function_handler import FunctionHandler
from prometheus_client.parser import text_string_to_metric_families
from tests.test_reliability import make_handler, make_message


def sample(name, **labels):
    value = metrics.REGISTRY.get_sample_value("discord_bot_" + name, labels)
    return 0 if value is None else value


class EndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_scrape_and_cleanup(self):
        runner = await metrics.start_metrics_server("127.0.0.1", 0)
        port = runner.addresses[0][1]
        url = f"http://127.0.0.1:{port}/metrics"
        async with aiohttp.ClientSession() as client:
            try:
                async with client.get(url) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.content_type, "text/plain")
                    names = {family.name for family in text_string_to_metric_families(
                        await response.text())}
                    self.assertIn("process_start_time_seconds", names)
                    self.assertIn("discord_bot_gateway_connected", names)
                with patch.object(metrics, "generate_latest", side_effect=RuntimeError):
                    with self.assertLogs("aiohttp.server", level="ERROR"):
                        async with client.get(url) as response:
                            self.assertEqual(response.status, 500)
            finally:
                await runner.cleanup()

            with self.assertRaises(aiohttp.ClientConnectorError):
                await client.get(url)

    async def test_bind_failure_prevents_bot_startup(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            async def bind_occupied_port():
                return await metrics.start_metrics_server("127.0.0.1", port)

            with patch.dict(os.environ, dict.fromkeys(
                    ("DISCORD_TOKEN", "OPENAI_API_KEY", "PINECONE_API_KEY"), "test")), \
                    patch.object(app, "start_metrics_server", side_effect=bind_occupied_port), \
                    patch.object(app, "DiscordHandler") as bot:
                with self.assertRaises(OSError):
                    await app._main()
                bot.assert_not_called()


class StartupMetricsTests(unittest.TestCase):
    def test_first_scrape_contains_zero_counters_and_first_event_counts_once(self):
        # The registry is process-local. Start fresh regardless of test order.
        result = subprocess.run([sys.executable, "-c", textwrap.dedent("""
            import asyncio
            import json
            from types import SimpleNamespace
            from unittest.mock import patch

            import aiohttp

            from discord_bot import app, metrics
            from discord_bot.handlers.usage_metrics import model_call

            async def test_startup():
                snapshots = []

                async def start_metrics_server():
                    runner = await metrics.start_metrics_server("127.0.0.1", 0)
                    url = f"http://127.0.0.1:{runner.addresses[0][1]}/metrics"
                    async with aiohttp.ClientSession() as client:
                        async with client.get(url) as response:
                            response.raise_for_status()
                            snapshots.append(await response.text())
                    return runner

                async def run_bot(*_credentials):
                    if len(snapshots) == 1:
                        await metrics.run_tool(
                            asyncio.sleep(0, result={"ok": True}),
                            tool="search_web", source="reply",
                        )
                        for model in ("gpt-6.1-terra", "unrecognized-test-model"):
                            await model_call(asyncio.sleep(0, result=SimpleNamespace()),
                                             model=model, operation="reply")

                with (patch.object(app, "start_metrics_server", start_metrics_server),
                      patch.object(app, "_run_bot", run_bot)):
                    await app._main()
                    await app._main()
                print(json.dumps(snapshots))

            asyncio.run(test_startup())
        """)], env={**os.environ, "DISCORD_TOKEN": "test", "OPENAI_API_KEY": "test",
                   "PINECONE_API_KEY": "test", "OPENAI_MODEL": "gpt-6.1-terra",
                   "REACTION_SHADOW_MODEL": "unrecognized-test-model"},
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        before, after = json.loads(result.stdout)

        def samples(scrape):
            families = list(text_string_to_metric_families(scrape))
            names = [family.name for family in families]
            self.assertEqual(len(names), len(set(names)))
            values = {}
            for family in families:
                for item in family.samples:
                    key = (item.name, frozenset(item.labels.items()))
                    self.assertNotIn(key, values)
                    values[key] = item.value
            return values

        def key(name, **labels):
            return "discord_bot_" + name, frozenset(labels.items())

        initial = samples(before)
        final = samples(after)
        expected = (
            key("requests_total", route="dm", outcome="answered"),
            key("model_calls_total", operation="reply", model="gpt-6.1-terra", outcome="success"),
            key("model_tokens_total", operation="reply_recall_embedding",
                model="text-embedding-ada-002", kind="input"),
            key("model_estimated_cost_usd_total", operation="discovery", model="gpt-6.1-terra"),
            key("model_cost_coverage_total", operation="reaction", model="other",
                status="unknown_price"),
            key("tool_executions_total", tool="weather_lookup", source="reply", outcome="success"),
            key("tool_executions_total", tool="get_webpage_contents", source="discovery",
                outcome="timeout"),
            key("tool_rejections_total", tool="read_youtube", source="reply", reason="invalid_cursor"),
            key("tool_rejections_total", tool="unknown", source="reply", reason="unknown_tool"),
            key("discovery_runs_total", outcome="complete"),
            key("discovery_selections_total"),
            key("discovery_delivery_attempts_total"),
            key("discovery_deliveries_total", outcome="sent"),
            key("discovery_deferrals_total", reason="active"),
            key("reaction_decisions_total", trigger="pile_on", outcome="react"),
            key("reaction_skips_total", trigger="conversation_window", reason="not_due"),
            key("reaction_delivery_attempts_total", source="reply_tool"),
            key("reaction_deliveries_total", source="proactive", outcome="emitted"),
            key("memory_extraction_windows_total", outcome="processed"),
            key("memory_candidate_outcomes_total", outcome="published"),
            key("worker_cycles_total", worker="archive_reconciliation", outcome="partial_failure"),
        )
        for series in expected:
            with self.subTest(series=series):
                self.assertEqual(initial.get(series), 0)
        tool = key("tool_executions_total", tool="search_web", source="reply", outcome="success")
        self.assertEqual(initial.get(tool), 0)
        self.assertEqual(final.get(tool), 1)
        model_call = key("model_calls_total", operation="reply", model="gpt-6.1-terra",
                         outcome="success")
        self.assertEqual(final.get(model_call), 1)

        dynamic = key("model_calls_total", operation="reply", model="other", outcome="success")
        self.assertNotIn(dynamic, initial)
        self.assertEqual(final.get(dynamic), 1)
        self.assertNotIn("unrecognized-test-model", before + after)
        self.assertNotIn(key("tool_executions_total", tool="weather_lookup",
                             source="discovery", outcome="success"), initial)
        self.assertNotIn(key("model_tokens_total", operation="reply_recall_embedding",
                             model="text-embedding-ada-002", kind="output"), initial)


class ReplyAndToolMetricsTests(unittest.IsolatedAsyncioTestCase):
    async def test_reply_is_counted_before_trailing_sleep(self):
        handler, message = make_handler(), make_message()
        labels = {"route": "mention", "outcome": "answered"}
        before = sample("requests_total", **labels)

        async def sleep(_delay):
            self.assertEqual(sample("requests_total", **labels), before + 1)

        with patch("discord_bot.handlers.discord_handler.asyncio.sleep", side_effect=sleep):
            await handler.process_message(message)
        message.channel.send.assert_awaited_once()
        self.assertEqual(sample("requests_total", **labels), before + 1)

    async def test_reply_sleeps_after_each_send_and_handles_trailing_sleep_failure(self):
        handler, message = make_handler(), make_message()
        first, second = "a" * 1000, "b" * 1000
        handler.chatgpt_handler.get_response.return_value = f"{first}\n{second}"
        events = []

        async def send(text):
            events.append(("send", text))

        async def sleep(delay):
            events.append(("sleep", delay))
            if len(events) == 4:
                raise RuntimeError("trailing sleep failed")

        message.channel.send.side_effect = send
        with self.assertLogs(level="ERROR"), patch(
            "discord_bot.handlers.discord_handler.asyncio.sleep", side_effect=sleep,
        ):
            await handler.process_message(message)
        self.assertEqual(events[:4], [
            ("send", first + "\n"), ("sleep", 3),
            ("send", second + "\n"), ("sleep", 3),
        ])
        self.assertEqual(len(events), 5)
        self.assertIn("error with sending", events[-1][1])

    async def test_fallback_and_partial_delivery_are_distinct(self):
        for outcome in ("fallback", "partial_delivery"):
            with self.subTest(outcome=outcome):
                handler, message = make_handler(), make_message()
                labels = {"route": "mention", "outcome": outcome}
                before = sample("requests_total", **labels)
                if outcome == "fallback":
                    handler.chatgpt_handler.get_response.return_value = FallbackReply("test fallback")
                else:
                    handler.chatgpt_handler.get_response.return_value = "a" * 1000 + "\n" + "b" * 1000
                    message.channel.send.side_effect = [None, RuntimeError("send failed"), None]
                with patch("discord_bot.handlers.discord_handler.asyncio.sleep", new_callable=AsyncMock):
                    await handler.process_message(message)
                self.assertEqual(sample("requests_total", **labels), before + 1)

    async def test_dispatcher_timeout_result_is_counted_once(self):
        class BlockedTool:
            async def execute(self, _arguments):
                await asyncio.Event().wait()

        dispatcher = FunctionHandler.__new__(FunctionHandler)
        dispatcher.functions = {"read_youtube": BlockedTool}
        dispatcher.api_functions = [{"name": "read_youtube"}]
        handler = ChatGPTHandler.__new__(ChatGPTHandler)
        handler.function_handler = dispatcher
        labels = {"tool": "read_youtube", "source": "reply"}
        timeouts = sample("tool_executions_total", **labels, outcome="timeout")
        durations = sample("tool_execution_duration_seconds_count", **labels)
        with patch("discord_bot.handlers.function_handler.TOOL_TIMEOUT", 0):
            result = await handler._execute_tool("read_youtube", {}, timeout=2)
        self.assertEqual(json.loads(result)["error"]["code"], "TIMEOUT")
        self.assertEqual(sample("tool_executions_total", **labels, outcome="timeout"), timeouts + 1)
        self.assertEqual(sample("tool_execution_duration_seconds_count", **labels), durations + 1)

    async def test_tool_timeout_is_counted_once_and_update_failure_is_nonfatal(self):
        async def blocked():
            await asyncio.Event().wait()

        labels = {"tool": "read_youtube", "source": "reply", "outcome": "timeout"}
        before = sample("tool_executions_total", **labels)
        with self.assertRaises(TimeoutError):
            await metrics.run_tool(blocked(), tool="read_youtube", source="reply", timeout=0.001)
        self.assertEqual(sample("tool_executions_total", **labels), before + 1)

        tool = AsyncMock(return_value={"ok": True, "text": "private example"})
        with patch.object(metrics.TOOL_EXECUTIONS, "labels", side_effect=RuntimeError):
            self.assertEqual(await metrics.run_tool(tool(), tool="search_web", source="reply"),
                             tool.return_value)
        self.assertNotIn(b"private example", metrics.generate_latest(metrics.REGISTRY))
