"""Mocked tool and OpenAI failure regressions; no network or credentials needed."""
import asyncio
import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import requests
from openai import APIConnectionError
from pydantic import BaseModel

from discord_bot.handlers import chatgpt_handler
from discord_bot.handlers.chatgpt_handler import ChatGPTHandler
from discord_bot.handlers.function_handler import FunctionHandler
from discord_bot.handlers.tool_output import MAX_TOOL_RESULT_CHARS
from discord_bot.functions.get_weather import WeatherLookup
from discord_bot.functions.get_webpage_contents import GetWebPageContents
from discord_bot.functions.search_web import SearchWeb


class OutputItem(BaseModel):
    type: str
    call_id: str | None = None
    name: str | None = None
    arguments: str | None = None


def response(items, text=""):
    return SimpleNamespace(output=items, output_text=text)


def tool_call(call_id, name, arguments):
    return OutputItem(type="function_call", call_id=call_id, name=name, arguments=arguments)


class OpenAIToolRegressions(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        with patch("discord_bot.handlers.chatgpt_handler.FunctionHandler"):
            self.handler = ChatGPTHandler("test-key")
        self.handler.client = MagicMock()
        self.handler.client.responses.create = AsyncMock()
        self.handler.function_handler.api_functions = []
        self.handler.function_handler.execute_function = AsyncMock(return_value="ok")

    def budgets(self):
        return [
            json.JSONDecoder().raw_decode(
                call.kwargs["instructions"].split("Internal tool budget: ", 1)[1]
            )[0]
            for call in self.handler.client.responses.create.await_args_list
        ]

    async def test_parallel_batch_respects_cap_and_forces_final_answer(self):
        create = self.handler.client.responses.create
        create.side_effect = [
            response([tool_call("invalid", "search_web", "bad JSON"),
                      tool_call("page", "get_webpage_contents", '{"url":"https://example.org"}')]),
            response([tool_call("video", "read_youtube", '{"url":"https://youtu.be/example"}'),
                      tool_call("extra", "search_web", '{}')]),
            response([], "Answer from available evidence"),
        ]
        self.handler.function_handler.execute_function.return_value = (
            '{"ok":false,"error":{"code":"PROVIDER_ERROR"}}'
        )
        self.handler.send_interim_message = AsyncMock()
        with patch.object(chatgpt_handler, "MAX_FUNCTION_CALLS", 3):
            self.assertEqual(await self.handler.get_response([], None), "Answer from available evidence")
        budgets = self.budgets()
        self.assertEqual([b["function_calls_remaining"] for b in budgets], [3, 1, 0])
        self.assertEqual([b["shared_webpage_youtube_reads_remaining"] for b in budgets],
                         [chatgpt_handler.MAX_PAGE_READS, 1, 0])
        self.assertEqual(create.await_args.kwargs["tool_choice"], "none")
        self.assertIn("Answer now", create.await_args.kwargs["instructions"])
        outputs = [json.loads(item["output"]) for item in create.await_args.kwargs["input"]
                   if item["type"] == "function_call_output"]
        self.assertEqual([item["error"]["code"] for item in outputs],
                         ["INVALID_ARGUMENT", "PROVIDER_ERROR", "PROVIDER_ERROR", "FUNCTION_LIMIT"])
        self.assertEqual(self.handler.function_handler.execute_function.await_count, 2)
        self.handler.send_interim_message.assert_not_awaited()

    async def test_automatic_youtube_timeout_spends_both_allowances(self):
        create = self.handler.client.responses.create
        create.side_effect = [
            response([tool_call("video", "read_youtube", '{"url":"https://youtu.be/example"}')]),
            response([tool_call("page", "get_webpage_contents", '{"url":"https://example.org"}')]),
            response([], "Partial coverage"),
        ]
        self.handler.function_handler.execute_function.side_effect = [
            '{"ok":true,"source":"transcript","next_cursor":{"segment_index":2}}',
            asyncio.TimeoutError(),
        ]
        self.assertEqual(await self.handler.get_response([], None), "Partial coverage")
        budgets = self.budgets()
        cap = chatgpt_handler.MAX_FUNCTION_CALLS
        self.assertEqual([b["function_calls_remaining"] for b in budgets], [cap, cap - 2, cap - 3])
        self.assertEqual([b["shared_webpage_youtube_reads_remaining"] for b in budgets],
                         [chatgpt_handler.MAX_PAGE_READS, 0, 0])
        self.assertEqual(self.handler.function_handler.execute_function.await_count, 2)
        outputs = [json.loads(item["output"]) for item in create.await_args.kwargs["input"]
                   if item["type"] == "function_call_output"]
        self.assertIn("failed or timed out", outputs[0]["limitations"][0])
        self.assertEqual(outputs[1]["error"]["code"], "READ_LIMIT")

    async def test_oversized_tool_results_are_bounded_before_model_replay(self):
        create = self.handler.client.responses.create
        create.side_effect = [
            response([tool_call("object", "search_web", "{}"),
                      tool_call("list", "search_web", "{}"),
                      tool_call("text", "search_web", "{}")]),
            response([], "Done"),
        ]
        large = "x" * MAX_TOOL_RESULT_CHARS
        self.handler.function_handler.execute_function.side_effect = [
            json.dumps({"ok": True, "data": large}),
            json.dumps([{"title": "First"}, {"data": large}]),
            "\\\n" * MAX_TOOL_RESULT_CHARS,
        ]
        self.assertEqual(await self.handler.get_response([], None), "Done")
        outputs = [item["output"] for item in create.await_args.kwargs["input"]
                   if item["type"] == "function_call_output"]
        for output in outputs:
            self.assertLessEqual(len(output), MAX_TOOL_RESULT_CHARS)
            self.assertTrue(json.loads(output)["result_truncated"])
        self.assertEqual(json.loads(outputs[0])["result"], {"ok": True})
        self.assertEqual(json.loads(outputs[1])["result"], [{"title": "First"}])
        self.assertTrue(json.loads(outputs[2])["result"])

    async def test_no_tools_sends_only_the_model_reply(self):
        self.handler.send_interim_message = AsyncMock()
        self.handler.client.responses.create.return_value = response([], "Which city?")
        self.assertEqual(await self.handler.get_response([], "channel"), "Which city?")
        self.handler.send_interim_message.assert_not_awaited()
        self.handler.function_handler.execute_function.assert_not_awaited()

    async def test_independent_requests_each_send_one_update_for_one_tool(self):
        progress = AsyncMock()
        self.handler.send_interim_message = progress
        for update in ("Checking the forecast", "Checking tomorrow's weather"):
            self.handler.client.responses.create.side_effect = [
                response([tool_call("weather", "weather_lookup",
                                    json.dumps({"quick_update": update}))]),
                response([], "Forecast ready"),
            ]
            self.assertEqual(await self.handler.get_response([], "channel"), "Forecast ready")
        self.assertEqual([call.args for call in progress.await_args_list], [
            ("channel", "Checking the forecast"), ("channel", "Checking tomorrow's weather"),
        ])

    async def test_multiple_calls_produce_distinct_correlated_outputs(self):
        progress = AsyncMock()
        self.handler.send_interim_message = progress
        calls = [
            tool_call("one", "weather_lookup", '{"city":"Seattle","quick_update":"Checking the forecast"}'),
            tool_call("two", "search_web", '{"query":"Seattle","quick_update":"Checking the web"}'),
        ]
        self.handler.client.responses.create.side_effect = [
            response(calls),
            response([tool_call("three", "search_web", '{"query":"Seattle rain","quick_update":"Checking rainfall"}')]),
            response([], "Done"),
        ]
        self.assertEqual(await self.handler.get_response([], "channel"), "Done")
        progress.assert_awaited_once_with("channel", "Checking the forecast")
        self.assertEqual(self.handler.function_handler.execute_function.await_count, 3)
        sent = self.handler.client.responses.create.await_args.kwargs["input"]
        outputs = [item for item in sent if isinstance(item, dict) and item.get("type") == "function_call_output"]
        self.assertEqual([item["call_id"] for item in outputs], ["one", "two", "three"])
        self.assertEqual([item["output"] for item in outputs], ["ok", "ok", "ok"])

    async def test_concurrent_requests_have_separate_budgets_and_progress_allowances(self):
        both_started = asyncio.Event()
        progress = AsyncMock()
        self.handler.send_interim_message = progress

        async def create_response(**kwargs):
            conversation = kwargs["input"]
            topic = conversation[0]["content"]
            if len(conversation) == 1:
                return response([tool_call(topic, "search_web",
                                           json.dumps({"quick_update": f"Checking {topic}"}))])
            return response([], f"Found {topic}")

        async def execute(*args):
            if progress.await_count == 2:
                both_started.set()
            await both_started.wait()
            return "ok"

        self.handler.client.responses.create.side_effect = create_response
        self.handler.function_handler.execute_function.side_effect = execute
        results = await asyncio.wait_for(asyncio.gather(
            self.handler.get_response([{"role": "user", "content": "Seattle"}], "channel"),
            self.handler.get_response([{"role": "user", "content": "Portland"}], "channel"),
        ), timeout=2)
        cap = chatgpt_handler.MAX_FUNCTION_CALLS
        self.assertEqual([b["function_calls_remaining"] for b in self.budgets()],
                         [cap, cap, cap - 1, cap - 1])
        self.assertEqual(results, ["Found Seattle", "Found Portland"])
        self.assertCountEqual([call.args for call in progress.await_args_list], [
            ("channel", "Checking Seattle"), ("channel", "Checking Portland"),
        ])

    async def test_both_discord_history_tools_receive_context(self):
        context = {"guild": object(), "member": object(), "archive": object()}
        calls = [
            tool_call("search", "search_discord_history", '{"query":"roast"}'),
            tool_call("context", "get_discord_conversation_context",
                      '{"channel_id":"10","message_id":"100"}'),
        ]
        self.handler.client.responses.create.side_effect = [
            response(calls), response([], "Found it"),
        ]
        self.assertEqual(await self.handler.get_response(
            [{"role": "user", "content": "find the roast"}], None,
            discord_context=context), "Found it")
        for call in self.handler.function_handler.execute_function.await_args_list:
            self.assertIs(call.kwargs["context"], context)

    async def test_history_tool_updates_are_silent_but_other_tools_can_report_progress(self):
        progress = AsyncMock()
        self.handler.send_interim_message = progress
        calls = [
            tool_call("search", "search_discord_history",
                      '{"query":"roast","quick_update":"Searching archive"}'),
            tool_call("context", "get_discord_conversation_context",
                      '{"channel_id":"10","message_id":"100","quick_update":"Reading context"}'),
            tool_call("web", "search_web",
                      '{"query":"Python","quick_update":"Checking the web"}'),
        ]
        self.handler.client.responses.create.side_effect = [
            response(calls), response([], "Done"),
        ]
        self.assertEqual(await self.handler.get_response([], "channel"), "Done")
        progress.assert_awaited_once_with("channel", "Checking the web")
        self.assertEqual(self.handler.function_handler.execute_function.await_count, 3)

    async def test_only_history_tools_do_not_send_progress(self):
        progress = AsyncMock()
        self.handler.send_interim_message = progress
        self.handler.client.responses.create.side_effect = [
            response([tool_call("search", "search_discord_history",
                                '{"query":"roast","quick_update":"Searching"}')]),
            response([tool_call("context", "get_discord_conversation_context",
                                '{"channel_id":"10","message_id":"100","quick_update":"Reading"}')]),
            response([], "Found it"),
        ]
        self.assertEqual(await self.handler.get_response([], "channel"), "Found it")
        progress.assert_not_awaited()

    async def test_malformed_arguments_are_reported_to_model(self):
        self.handler.client.responses.create.side_effect = [
            response([tool_call("bad", "search_web", "{bad json")]),
            response([], "Recovered"),
        ]
        self.assertEqual(await self.handler.get_response([], None), "Recovered")
        self.handler.function_handler.execute_function.assert_not_awaited()
        sent = self.handler.client.responses.create.await_args.kwargs["input"]
        self.assertIn("Invalid tool arguments", sent[-1]["output"])

    async def test_non_object_arguments_are_rejected(self):
        self.handler.client.responses.create.side_effect = [
            response([tool_call("array", "search_web", '["not", "an object"]')]),
            response([], "OK"),
        ]
        self.assertEqual(await self.handler.get_response([], None), "OK")
        self.handler.function_handler.execute_function.assert_not_awaited()

    async def test_tool_error_and_retry_do_not_send_another_update(self):
        progress = AsyncMock()
        self.handler.send_interim_message = progress
        self.handler.function_handler.execute_function.side_effect = ["Search error", "Retry error"]
        self.handler.client.responses.create.side_effect = [
            response([tool_call("failure", "search_web", '{"query":"test","quick_update":"Checking sources"}')]),
            response([tool_call("retry", "search_web", '{"query":"test","quick_update":"Trying again"}')]),
            response([], "Search unavailable"),
        ]
        self.assertEqual(await self.handler.get_response([], "channel"), "Search unavailable")
        progress.assert_awaited_once_with("channel", "Checking sources")
        sent = self.handler.client.responses.create.await_args.kwargs["input"]
        outputs = [item["output"] for item in sent if isinstance(item, dict)
                   and item.get("type") == "function_call_output"]
        self.assertEqual(outputs, ["Search error", "Retry error"])

    async def test_empty_response_returns_fallback(self):
        self.handler.client.responses.create.return_value = response([])
        self.assertIn("couldn't generate", await self.handler.get_response([], None))

    async def test_openai_timeout_returns_fallback(self):
        self.handler.client.responses.create.side_effect = asyncio.TimeoutError()
        result = await self.handler.get_response([], None)
        self.assertIn("error processing your request with OpenAI", result)


class FunctionExecutionRegressions(unittest.IsolatedAsyncioTestCase):
    async def test_sync_tool_times_out_without_blocking_event_loop(self):
        started = threading.Event()
        release = threading.Event()

        class SyncTool:
            def execute(self, args):
                started.set()
                release.wait(2)
                return "Finished"

        with patch.object(FunctionHandler, "load_functions", return_value={"sync": SyncTool}), \
                patch.object(FunctionHandler, "get_api_functions", return_value=[]):
            handler = FunctionHandler()
        try:
            with patch("discord_bot.handlers.function_handler.TOOL_TIMEOUT", 0.1):
                task = asyncio.create_task(handler.execute_function("sync", {}))
                self.assertTrue(await asyncio.to_thread(started.wait, 1))
                result = json.loads(await task)
                self.assertEqual(result["error"]["code"], "TIMEOUT")
        finally:
            release.set()

    async def test_timeout_and_provider_errors_exclude_sensitive_details(self):
        tool = MagicMock()
        with patch.object(FunctionHandler, "load_functions", return_value={"sample": tool}), \
                patch.object(FunctionHandler, "get_api_functions", return_value=[]):
            handler = FunctionHandler()
        execute = tool.return_value.execute = AsyncMock()
        for exc, code, retryable in [
            (asyncio.TimeoutError("https://example.org/private?token=secret"), "TIMEOUT", True),
            (RuntimeError("https://example.org/private?token=secret"), "PROVIDER_ERROR", False),
        ]:
            with self.subTest(code=code), self.assertLogs(level="WARNING") as logs:
                execute.side_effect = exc
                result = json.loads(await handler.execute_function("sample", {}))
                self.assertFalse(result["ok"])
                self.assertEqual(result["error"]["code"], code)
                self.assertEqual(result["error"]["retryable"], retryable)
                for text in [*logs.output, json.dumps(result)]:
                    self.assertNotIn("example.org", text)
                    self.assertNotIn("secret", text)


class WeatherToolRegressions(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tool = WeatherLookup()
        self.args = {"city": "Gig Harbor", "state": "WA", "country_code": "US"}

    async def test_empty_geocode_results(self):
        geocode = MagicMock()
        geocode.json.return_value = []
        with patch("discord_bot.functions.get_weather.requests.get", return_value=geocode) as get:
            result = await self.tool.execute(self.args)
        self.assertIn("No weather location found", result)
        get.assert_called_once()

    async def test_geocode_network_failure(self):
        with patch("discord_bot.functions.get_weather.requests.get", side_effect=requests.Timeout):
            result = await self.tool.execute(self.args)
        self.assertIn("Unable to look up weather location", result)

    async def test_forecast_network_failure(self):
        geocode = MagicMock()
        geocode.json.return_value = [{"lat": 47.3, "lon": -122.6}]
        with patch("discord_bot.functions.get_weather.requests.get", side_effect=[geocode, requests.Timeout]):
            result = await self.tool.execute(self.args)
        self.assertIn("Unable to fetch weather", result)

    async def test_hourly_forecast_is_bounded(self):
        geocode = MagicMock()
        geocode.json.return_value = [{"lat": 47.3, "lon": -122.6}]
        forecast = MagicMock(status_code=200, text=json.dumps({"hourly": list(range(48))}))
        with patch("discord_bot.functions.get_weather.requests.get", side_effect=[geocode, forecast]):
            result = await self.tool.execute(self.args)
        self.assertEqual(len(json.loads(result)["hourly"]), 24)


class WebpageToolRegressions(unittest.IsolatedAsyncioTestCase):
    async def test_missing_url(self):
        self.assertIn("provide a URL", await GetWebPageContents().execute({}))

    async def test_network_failure(self):
        with patch("discord_bot.functions.get_webpage_contents.fetch_public_html", side_effect=requests.Timeout):
            result = await GetWebPageContents().execute({"url": "https://example.org"})
        self.assertEqual(json.loads(result)["error"]["code"], "TIMEOUT")

    async def test_page_without_article_or_div(self):
        reply = MagicMock(content=b"<html><body><p>Plain text</p></body></html>")
        with patch("discord_bot.functions.get_webpage_contents.fetch_public_html", return_value=reply.content):
            result = await GetWebPageContents().execute({"url": "https://example.org"})
        self.assertIn("Plain text", result)

    async def test_long_page_truncates(self):
        reply = MagicMock(content=("<html><body><p>" + "x" * 12005 + "</p></body></html>").encode())
        with patch("discord_bot.functions.get_webpage_contents.fetch_public_html", return_value=reply.content):
            result = await GetWebPageContents().execute({"url": "https://example.org"})
        payload = json.loads(result)
        self.assertTrue(payload["content_truncated"])
        self.assertEqual(len(payload["content"]), 12000)


class LoggingRegressions(unittest.TestCase):
    def test_tool_registration_logs_names_not_schema(self):
        handler = object.__new__(FunctionHandler)
        handler.functions = {"search_web": MagicMock(name="search_web")}
        handler.functions["search_web"].return_value.description = "secret-description"
        handler.functions["search_web"].return_value.get_parameters.return_value = {"secret": "hidden"}
        with self.assertLogs(level="INFO") as logs:
            handler.get_api_functions()
        self.assertIn("search_web", logs.output[0])
        self.assertNotIn("secret-description", logs.output[0])
        self.assertNotIn("hidden", logs.output[0])


class SearchToolRegressions(unittest.IsolatedAsyncioTestCase):
    def mock_response(self, status=200, payload=None):
        response = MagicMock()
        response.status = status
        response.json = AsyncMock(return_value=payload if payload is not None else {
            "web": {"results": [{"title": "Python docs", "url": "https://docs.python.org/3/"}]}
        })
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)
        session = MagicMock()
        session.get.return_value = response
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)
        return session

    async def test_missing_query(self):
        self.assertEqual(json.loads(await SearchWeb().execute({}))["error"]["code"], "INVALID_ARGUMENT")

    async def test_missing_key(self):
        with patch.dict("os.environ", {}, clear=True):
            result = json.loads(await SearchWeb().execute({"query": "Python"}))
        self.assertEqual(result["error"]["code"], "CONFIG_ERROR")

    async def test_success(self):
        session = self.mock_response()
        with patch.dict("os.environ", {"BRAVE_SEARCH_API_KEY": "test-secret"}), \
             patch("discord_bot.functions.search_web.aiohttp.ClientSession", return_value=session):
            result = json.loads(await SearchWeb().execute({"query": "Python"}))
        self.assertTrue(result["ok"])
        self.assertEqual(result["results"][0]["url"], "https://docs.python.org/3/")
        self.assertEqual(session.get.call_args.kwargs["headers"]["X-Subscription-Token"], "test-secret")

    async def test_freshness_schema_and_serialization(self):
        schema = SearchWeb.get_parameters()
        options = ["pd", "pw", "pm", "py"]
        self.assertEqual(schema["properties"]["freshness"]["enum"], options)
        self.assertNotIn("freshness", schema["required"])
        for freshness in options:
            with self.subTest(freshness=freshness):
                session = self.mock_response()
                result = await self.execute_mock_search(session, freshness=freshness)
                self.assertTrue(result["ok"])
                self.assertEqual(session.get.call_args.kwargs["params"], {
                    "q": "Python", "count": 1, "freshness": freshness,
                })

    async def test_invalid_freshness_avoids_provider_request(self):
        with patch("discord_bot.functions.search_web.aiohttp.ClientSession") as client:
            for freshness in ("week", "", None, ["pw"]):
                with self.subTest(freshness=freshness):
                    result = json.loads(await SearchWeb().execute({
                        "query": "Python", "freshness": freshness,
                    }))
                    self.assertEqual(result["error"]["code"], "INVALID_ARGUMENT")
            client.assert_not_called()

    async def execute_mock_search(self, session, **args):
        with patch.dict("os.environ", {"BRAVE_SEARCH_API_KEY": "test-secret"}), \
             patch("discord_bot.functions.search_web.aiohttp.ClientSession", return_value=session):
            return json.loads(await SearchWeb().execute({"query": "Python", **args}))

    async def test_metadata_is_optional_and_snippets_are_bounded(self):
        entry = {"title": "Python docs", "url": "https://docs.python.org/3/"}
        date = "2025-01-02T00:00:00Z"
        session = self.mock_response(payload={"web": {"results": [
            dict(entry, description="  Release   notes  ", page_age=date),
            entry,
            dict(entry, description=[], page_age={}, page_fetched=date),
            dict(entry, description="長" * 500, page_age="  "),
            dict(entry, description="  ", page_age="x" * 65),
            dict(entry, title="Outside the requested limit"),
        ]}})
        result = await self.execute_mock_search(session, max_results=5)
        self.assertEqual(result["results"], [
            dict(entry, snippet="Release notes", page_date=date),
            entry,
            entry,
            dict(entry, snippet="長" * 400),
            entry,
        ])
        self.assertEqual(session.get.call_args.kwargs["params"], {"q": "Python", "count": 5})

    async def test_rate_limit_is_explicit(self):
        session = self.mock_response(status=429)
        with patch.dict("os.environ", {"BRAVE_SEARCH_API_KEY": "test-secret"}), \
             patch("discord_bot.functions.search_web.aiohttp.ClientSession", return_value=session):
            result = json.loads(await SearchWeb().execute({"query": "Python"}))
        self.assertEqual(result["error"]["code"], "RATE_LIMITED")
        self.assertFalse(result["error"]["retryable"])
        session.get.assert_called_once()

    async def test_auth_error(self):
        session = self.mock_response(status=401)
        with patch.dict("os.environ", {"BRAVE_SEARCH_API_KEY": "test-secret"}), \
             patch("discord_bot.functions.search_web.aiohttp.ClientSession", return_value=session):
            result = json.loads(await SearchWeb().execute({"query": "Python"}))
        self.assertEqual(result["error"]["code"], "AUTH_ERROR")

    async def test_no_results(self):
        session = self.mock_response(payload={"web": {"results": []}})
        with patch.dict("os.environ", {"BRAVE_SEARCH_API_KEY": "test-secret"}), \
             patch("discord_bot.functions.search_web.aiohttp.ClientSession", return_value=session):
            result = json.loads(await SearchWeb().execute({"query": "Python"}))
        self.assertEqual(result["error"]["code"], "NO_RESULTS")

    async def test_timeout_returns_structured_error(self):
        session = self.mock_response()
        session.get.side_effect = asyncio.TimeoutError()
        with patch.dict("os.environ", {"BRAVE_SEARCH_API_KEY": "test-secret"}), \
             patch("discord_bot.functions.search_web.aiohttp.ClientSession", return_value=session):
            result = json.loads(await SearchWeb().execute({"query": "Python"}))
        self.assertEqual(result["error"]["code"], "TIMEOUT")

    async def test_network_failure_returns_structured_error(self):
        from aiohttp import ClientConnectionError
        session = self.mock_response()
        session.get.side_effect = ClientConnectionError("connection refused")
        with patch.dict("os.environ", {"BRAVE_SEARCH_API_KEY": "test-secret"}), \
             patch("discord_bot.functions.search_web.aiohttp.ClientSession", return_value=session):
            result = json.loads(await SearchWeb().execute({"query": "Python"}))
        self.assertEqual(result["error"]["code"], "PROVIDER_ERROR")

    async def test_malformed_provider_response_returns_error(self):
        for payload in ([], {"web": []}, {"web": {"results": "not a list"}}):
            with self.subTest(payload=payload):
                result = await self.execute_mock_search(self.mock_response(payload=payload))
                self.assertEqual(result["error"]["code"], "PROVIDER_ERROR")

    async def test_invalid_result_count(self):
        result = json.loads(await SearchWeb().execute({"query": "Python", "max_results": 99}))
        self.assertEqual(result["error"]["code"], "INVALID_ARGUMENT")


if __name__ == "__main__":
    unittest.main()
