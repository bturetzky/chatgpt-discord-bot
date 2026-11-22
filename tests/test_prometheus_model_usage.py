import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
from openai import AsyncOpenAI
from openai.types.responses.response_usage import ResponseUsage

from discord_bot import metrics
from discord_bot.handlers.usage_metrics import model_call, recall_embedding
from tests.test_prometheus_metrics import sample


class ModelMetricsTests(unittest.IsolatedAsyncioTestCase):
    async def test_reported_usage_on_incomplete_response_is_counted_once(self):
        operation, model = "discovery", "gpt-6.1-terra"
        labels = {"operation": operation, "model": model}
        cost = sample("model_estimated_cost_usd_total", **labels)
        calls = sample("model_calls_total", **labels, outcome="incomplete")
        cached = sample("model_tokens_total", **labels, kind="cached_input")
        usage = ResponseUsage.model_validate({
            "input_tokens": 1000, "output_tokens": 40, "total_tokens": 1040,
            "input_tokens_details": {"cached_tokens": 300, "cache_write_tokens": 200},
            "output_tokens_details": {"reasoning_tokens": 0},
        })
        response = SimpleNamespace(status="incomplete", usage=usage, service_tier="default")
        create = AsyncMock(return_value=response)
        result, decoded = await model_call(create(), model=model, operation=operation)
        self.assertIs(result, response)
        self.assertEqual(decoded.cache_write_tokens, 200)
        self.assertEqual(sample("model_calls_total", **labels, outcome="incomplete"), calls + 1)
        self.assertEqual(sample("model_tokens_total", **labels, kind="cached_input"), cached + 300)
        expected_usd = (500 + 300 * 0.05 + 200 * 1.25 + 40 * 5) / 1_000_000
        self.assertAlmostEqual(sample("model_estimated_cost_usd_total", **labels), cost + expected_usd)
        create.assert_awaited_once()

    async def test_sdk_response_without_optional_cache_writes_is_priced_for_ordinary_calls(self):
        model = "gpt-6.1-terra"

        def transport(_request):
            return httpx.Response(200, json={
                "id": "resp_test", "object": "response", "created_at": 0,
                "status": "completed", "model": model, "service_tier": "default",
                "output": [],
                "usage": {
                    "input_tokens": 1500, "output_tokens": 40, "total_tokens": 1540,
                    "input_tokens_details": {"cached_tokens": 300},
                    "output_tokens_details": {"reasoning_tokens": 0},
                },
            })

        http = httpx.AsyncClient(transport=httpx.MockTransport(transport))
        async with AsyncOpenAI(api_key="test", http_client=http) as client:
            for operation, options, status in (
                ("reaction", {}, "estimated"),
                ("discovery", {"prompt_cache_options": {"mode": "explicit"}}, "unsupported_pricing"),
            ):
                with self.subTest(operation=operation):
                    labels = {"operation": operation, "model": model}
                    coverage = sample("model_cost_coverage_total", **labels, status=status)
                    cost = sample("model_estimated_cost_usd_total", **labels)
                    response, usage = await model_call(
                        client.responses.create(model=model, input="test", **options),
                        model=model, operation=operation, explicit_cache=bool(options),
                    )
                    self.assertIsInstance(response.usage, ResponseUsage)
                    self.assertIsNone(usage.cache_write_tokens)
                    self.assertEqual(sample("model_cost_coverage_total", **labels, status=status),
                                     coverage + 1)
                    expected = (1200 + 300 * .05 + 40 * 5) / 1_000_000 if not options else 0
                    self.assertAlmostEqual(sample("model_estimated_cost_usd_total", **labels),
                                           cost + expected)

    async def test_unknown_model_never_appears_and_remains_unpriced(self):
        labels = {"operation": "reaction", "model": "other"}
        before = sample("model_cost_coverage_total", **labels, status="unknown_price")
        usage = SimpleNamespace(input_tokens=9, output_tokens=2)
        create = AsyncMock(return_value=SimpleNamespace(usage=usage))
        await model_call(create(), model="private-unrecognized-model", operation="reaction")
        self.assertEqual(sample("model_cost_coverage_total", **labels, status="unknown_price"),
                         before + 1)
        self.assertEqual(sample("model_estimated_cost_usd_total", **labels), 0)
        self.assertNotIn(b"private-unrecognized-model", metrics.generate_latest(metrics.REGISTRY))

    async def test_incomplete_pricing_keeps_reported_token_totals(self):
        operation, model = "discovery", "gpt-6.1-terra"
        labels = {"operation": operation, "model": model}
        unsupported = sample("model_cost_coverage_total", **labels, status="unsupported_pricing")
        tokens = sample("model_tokens_total", **labels, kind="input")
        cost = sample("model_estimated_cost_usd_total", **labels)
        response = SimpleNamespace(usage=SimpleNamespace(input_tokens=10, output_tokens=1))
        await model_call(AsyncMock(return_value=response)(), model=model, operation=operation)
        self.assertEqual(sample("model_cost_coverage_total", **labels, status="unsupported_pricing"),
                         unsupported + 1)
        self.assertEqual(sample("model_tokens_total", **labels, kind="input"), tokens + 10)
        self.assertEqual(sample("model_estimated_cost_usd_total", **labels), cost)

    async def test_timeout_counts_once_and_preserves_missing_usage(self):
        labels = {"operation": "memory_extraction", "model": "gpt-6.1-terra"}
        calls = sample("model_calls_total", **labels, outcome="timeout")
        missing = sample("model_cost_coverage_total", **labels, status="missing_usage")
        with self.assertRaises(TimeoutError):
            await model_call(asyncio.Event().wait(), model=labels["model"],
                             operation=labels["operation"], timeout=0.001)
        self.assertEqual(sample("model_calls_total", **labels, outcome="timeout"), calls + 1)
        self.assertEqual(sample("model_cost_coverage_total", **labels, status="missing_usage"),
                         missing + 1)

    def test_sync_embedding_uses_reported_prompt_tokens(self):
        labels = {"operation": "reply_recall_embedding", "model": "text-embedding-ada-002"}
        before = sample("model_tokens_total", **labels, kind="input")
        cost = sample("model_estimated_cost_usd_total", **labels)
        response = SimpleNamespace(usage=SimpleNamespace(prompt_tokens=80, total_tokens=80))
        create = Mock(return_value=response)
        self.assertIs(recall_embedding(create, model=labels["model"], input=["test"]), response)
        self.assertEqual(sample("model_tokens_total", **labels, kind="input"), before + 80)
        self.assertAlmostEqual(sample("model_estimated_cost_usd_total", **labels), cost + .000008)
