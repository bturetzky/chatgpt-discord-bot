"""Mocked tool and OpenAI failure regressions; no network or credentials needed."""
import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import requests
from openai import APIConnectionError
from pydantic import BaseModel

from discord_bot.handlers.chatgpt_handler import ChatGPTHandler
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

    async def test_multiple_calls_produce_distinct_correlated_outputs(self):
        calls = [
            tool_call("one", "weather_lookup", '{"city":"Seattle"}'),
            tool_call("two", "search_web", '{"query":"Python"}'),
        ]
        self.handler.client.responses.create.side_effect = [
            response(calls),
            response([], "Done"),
        ]
        self.assertEqual(await self.handler.get_response([{"role": "user", "content": "hi"}], None), "Done")
        self.assertEqual(self.handler.function_handler.execute_function.await_count, 2)
        sent = self.handler.client.responses.create.await_args.kwargs["input"]
        outputs = [item for item in sent if isinstance(item, dict) and item.get("type") == "function_call_output"]
        self.assertEqual([item["call_id"] for item in outputs], ["one", "two"])
        self.assertEqual([item["output"] for item in outputs], ["ok", "ok"])

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

    async def test_tool_error_is_passed_back_for_model_response(self):
        self.handler.function_handler.execute_function.return_value = "An error occurred while executing the function."
        self.handler.client.responses.create.side_effect = [
            response([tool_call("failure", "search_web", '{"query":"test"}')]),
            response([], "Search unavailable"),
        ]
        self.assertEqual(await self.handler.get_response([], None), "Search unavailable")
        sent = self.handler.client.responses.create.await_args.kwargs["input"]
        self.assertIn("error", sent[-1]["output"])

    async def test_empty_response_returns_fallback(self):
        self.handler.client.responses.create.return_value = response([])
        self.assertIn("couldn't generate", await self.handler.get_response([], None))

    async def test_openai_timeout_returns_fallback(self):
        self.handler.client.responses.create.side_effect = asyncio.TimeoutError()
        result = await self.handler.get_response([], None)
        self.assertIn("error processing your request with OpenAI", result)


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
        from discord_bot.handlers.function_handler import FunctionHandler
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
        session = self.mock_response(payload={"web": {"results": "not a list"}})
        with patch.dict("os.environ", {"BRAVE_SEARCH_API_KEY": "test-secret"}), \
             patch("discord_bot.functions.search_web.aiohttp.ClientSession", return_value=session):
            result = json.loads(await SearchWeb().execute({"query": "Python"}))
        self.assertEqual(result["error"]["code"], "PROVIDER_ERROR")

    async def test_invalid_result_count(self):
        result = json.loads(await SearchWeb().execute({"query": "Python", "max_results": 99}))
        self.assertEqual(result["error"]["code"], "INVALID_ARGUMENT")


if __name__ == "__main__":
    unittest.main()
