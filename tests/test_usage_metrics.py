import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from discord_bot.handlers.usage_metrics import ChatUsage


class ChatUsageTests(unittest.TestCase):
    def test_aggregates_tool_round_trips_and_cached_tokens(self):
        usage = ChatUsage("test-model")
        usage.add(SimpleNamespace(input_tokens=1000, output_tokens=200, input_tokens_details=SimpleNamespace(cached_tokens=300)))
        usage.add(SimpleNamespace(input_tokens=500, output_tokens=100, input_tokens_details=None))
        self.assertEqual((usage.calls, usage.input_tokens, usage.cached_input_tokens, usage.output_tokens), (2, 1500, 300, 300))

    def test_cost_estimate_with_configured_rates(self):
        with patch.dict(os.environ, {
            "OPENAI_INPUT_USD_PER_1M": "2",
            "OPENAI_CACHED_INPUT_USD_PER_1M": "0.5",
            "OPENAI_OUTPUT_USD_PER_1M": "8",
        }):
            usage = ChatUsage("test-model")
            usage.add(SimpleNamespace(input_tokens=1000, output_tokens=200, input_tokens_details=SimpleNamespace(cached_tokens=300)))
            self.assertAlmostEqual(usage.estimated_cost_usd(), (700 * 2 + 300 * .5 + 200 * 8) / 1_000_000)

    def test_unconfigured_price_not_reported_as_zero(self):
        with patch.dict(os.environ, {"OPENAI_INPUT_USD_PER_1M": "0", "OPENAI_OUTPUT_USD_PER_1M": "0"}):
            self.assertIsNone(ChatUsage("test-model").estimated_cost_usd())

    def test_missing_usage(self):
        usage = ChatUsage("test-model")
        usage.add(None)
        self.assertEqual(usage.calls, 0)


if __name__ == "__main__":
    unittest.main()
