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
        with patch("discord_bot.functions.get_webpage_contents.requests.get", side_effect=requests.Timeout):
            result = await GetWebPageContents().execute({"url": "https://example.org"})
        self.assertIn("Error fetching the webpage", result)

    async def test_page_without_article_or_div(self):
        reply = MagicMock(content=b"<html><body><p>Plain text</p></body></html>")
        with patch("discord_bot.functions.get_webpage_contents.requests.get", return_value=reply):
            result = await GetWebPageContents().execute({"url": "https://example.org"})
        self.assertIn("Plain text", result)

    async def test_long_page_truncates(self):
        reply = MagicMock(content=("<html><body><p>" + "x" * 5000 + "</p></body></html>").encode())
        with patch("discord_bot.functions.get_webpage_contents.requests.get", return_value=reply):
            result = await GetWebPageContents().execute({"url": "https://example.org"})
        self.assertLessEqual(len(result), 4003)
        self.assertTrue(result.endswith("..."))


class SearchToolRegressions(unittest.IsolatedAsyncioTestCase):
    async def test_missing_query(self):
        self.assertIn("No search query", await SearchWeb().execute({}))

    async def test_ddg_rate_limit_is_graceful(self):
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        client.text.side_effect = RuntimeError("202 Ratelimit")
        with patch("discord_bot.functions.search_web.AsyncDDGS", return_value=client):
            result = await SearchWeb().execute({"query": "Python docs"})
        self.assertIn("error occurred while searching", result)


if __name__ == "__main__":
    unittest.main()
