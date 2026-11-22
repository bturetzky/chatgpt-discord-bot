import asyncio
import json
import os
import socket
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
