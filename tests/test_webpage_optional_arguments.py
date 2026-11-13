"""Regression tests for nullable webpage reader options in Responses tool calls."""
import json
import unittest
from unittest.mock import patch

from discord_bot.functions.get_webpage_contents import FetchedHTML, GetWebPageContents


class WebpageOptionalArgumentsTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_and_null_options_are_omitted(self):
        page = FetchedHTML(b"<html><head><title>Example</title></head><body><main><h1>Test</h1><p>Useful page text.</p></main></body></html>",
                           "https://example.org/article", 200)
        variants = (
            {"url": "https://example.org/article"},
            {"url": "https://example.org/article", "cursor": None, "find_text": None},
            {"url": "https://example.org/article", "cursor": "", "find_text": ""},
            {"url": "https://example.org/article", "cursor": "  ", "find_text": "  "},
            {"url": "https://example.org/article", "cursor": "", "find_text": "Useful"},
            {"url": "https://example.org/article", "cursor": None, "find_text": "Useful"},
        )
        with patch("discord_bot.functions.get_webpage_contents.fetch_public_html", return_value=page) as fetch:
            for args in variants:
                with self.subTest(args=args):
                    result = json.loads(await GetWebPageContents().execute(json.loads(json.dumps(args))))
                    self.assertTrue(result["ok"], result)
                    self.assertIn("Useful page text.", result["content"])
            self.assertEqual(fetch.call_count, len(variants))

    async def test_invalid_real_options_still_fail_before_fetch(self):
        cases = (
            ({"cursor": "invented", "find_text": None}, "INVALID_CURSOR"),
            ({"cursor": 123, "find_text": ""}, "INVALID_CURSOR"),
            ({"cursor": "", "find_text": 123}, "INVALID_ARGUMENT"),
            ({"cursor": "", "find_text": "x" * 201}, "INVALID_ARGUMENT"),
            ({"cursor": "invented", "find_text": "Useful"}, "INVALID_ARGUMENT"),
        )
        with patch("discord_bot.functions.get_webpage_contents.fetch_public_html") as fetch:
            for options, expected in cases:
                with self.subTest(options=options), self.assertLogs(level="WARNING"):
                    result = json.loads(await GetWebPageContents().execute(
                        {"url": "https://example.org/article", **options}))
                    self.assertEqual(result["error"]["code"], expected)
            fetch.assert_not_called()

    def test_registered_schema_is_responses_compatible(self):
        schema = GetWebPageContents.get_parameters()
        self.assertEqual(set(schema["required"]), set(schema["properties"]))
        self.assertFalse(schema["additionalProperties"])
        self.assertNotIn("quick_update", schema["properties"])
        for field in ("cursor", "find_text"):
            self.assertIn("null", schema["properties"][field]["type"])
