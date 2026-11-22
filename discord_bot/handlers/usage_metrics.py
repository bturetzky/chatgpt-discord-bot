"""OpenAI usage shared by existing summaries and Prometheus counters."""
import asyncio
from dataclasses import dataclass
import logging
import math
import os
import re
import time

from openai import APITimeoutError, RateLimitError

from .. import metrics


DEFAULT_MODEL_RATES = {
    "gpt-6.1-terra": (1.0, 0.05, 5.0),  # Standard USD per 1M tokens
}
EMBEDDING_MODEL_RATES = {"text-embedding-ada-002": 0.10}
TERRA = "gpt-6.1-terra"


def _price(name, default=0):
    try:
        value = float(os.getenv(name, str(default)))
        return value if math.isfinite(value) and value >= 0 else 0.0
    except ValueError:
        return 0.0


def model_label(model):
    if not isinstance(model, str):
        return "other"
    if model in DEFAULT_MODEL_RATES or model in EMBEDDING_MODEL_RATES:
        return model
    if re.fullmatch(r"gpt-6\.1-terra-\d{4}-\d{2}-\d{2}", model):
        return TERRA
    return "other"


def _tokens(value):
    return value if type(value) is int and value >= 0 else None


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    cached_input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int | None = None
    cache_reads_reported: bool = True
    # The bot uses the provider's default cache lifetime.
    default_cache_lifetime: bool = True


def decode_usage(usage, *, embeddings=False):
    if embeddings:
        count = _tokens(getattr(usage, "prompt_tokens", None))
        if count is None:
            count = _tokens(getattr(usage, "total_tokens", None))
        return TokenUsage(count) if count is not None else None

    input_count = _tokens(getattr(usage, "input_tokens", None))
    output = _tokens(getattr(usage, "output_tokens", None))
    if input_count is None or output is None:
        return None
    details = getattr(usage, "input_tokens_details", None)
    cached = _tokens(getattr(details, "cached_tokens", None))
    writes = _tokens(getattr(details, "cache_write_tokens", None))
    lifetimes = getattr(details, "cache_write_tokens_details", None)
    long_writes = (
        lifetimes.get("ttl_12h_tokens") if isinstance(lifetimes, dict)
        else getattr(lifetimes, "ttl_12h_tokens", None)
    )
    return TokenUsage(input_count, cached or 0, output, writes,
                      cache_reads_reported=cached is not None,
                      default_cache_lifetime=not long_writes)


def _estimate(model, usage, *, embeddings=False, chat_overrides=False, tier=None,
              explicit_cache=False):
    if usage is None:
        return "missing_usage", None
    if isinstance(tier, str) and tier not in ("default", "standard"):
        return "unsupported_pricing", None
    if embeddings:
        rate = EMBEDDING_MODEL_RATES.get(model)
        if rate is None:
            return "unknown_price", None
        return "estimated", usage.input_tokens * rate / 1_000_000

    input_rate, cached_rate, output_rate = DEFAULT_MODEL_RATES.get(model, (0, 0, 0))
    if chat_overrides:
        input_rate = _price("OPENAI_INPUT_USD_PER_1M", input_rate)
        cached_rate = _price("OPENAI_CACHED_INPUT_USD_PER_1M", cached_rate)
        output_rate = _price("OPENAI_OUTPUT_USD_PER_1M", output_rate)
    if not input_rate or not output_rate or (usage.cached_input_tokens and not cached_rate):
        return "unknown_price", None

    writes = usage.cache_write_tokens or 0
    # Normal Responses can omit the cache-write field. An explicitly cached
    # request needs a reported write count to estimate its charges.
    if (model == TERRA and (not usage.cache_reads_reported or usage.input_tokens > 272_000)
            or (explicit_cache and usage.cache_write_tokens is None)
            or not usage.default_cache_lifetime
            or usage.cached_input_tokens + writes > usage.input_tokens
            or (writes and model != TERRA)):
        return "unsupported_pricing", None
    ordinary = usage.input_tokens - usage.cached_input_tokens - writes
    cost = (ordinary * input_rate + usage.cached_input_tokens * cached_rate
            + writes * input_rate * 1.25 + usage.output_tokens * output_rate)
    return "estimated", cost / 1_000_000


def _failure_outcome(error):
    if isinstance(error, (TimeoutError, APITimeoutError)):
        return "timeout"
    if isinstance(error, RateLimitError):
        return "rate_limited"
    if isinstance(error, asyncio.CancelledError):
        return "cancelled"
    return "error"


def _record_call(operation, model, started, outcome, usage, *, embeddings=False, tier=None,
                 explicit_cache=False):
    labels = (operation, model_label(model))
    metrics.increment(metrics.MODEL_CALLS, *labels, outcome)
    metrics.observe(metrics.MODEL_DURATION, started, operation)
    if usage is not None:
        metrics.increment(metrics.MODEL_TOKENS, *labels, "input", amount=usage.input_tokens)
        if not embeddings:
            metrics.increment(metrics.MODEL_TOKENS, *labels, "cached_input",
                              amount=usage.cached_input_tokens)
            metrics.increment(metrics.MODEL_TOKENS, *labels, "output", amount=usage.output_tokens)
    coverage, cost = _estimate(model, usage, embeddings=embeddings,
                               chat_overrides=operation == "reply", tier=tier,
                               explicit_cache=explicit_cache)
    metrics.increment(metrics.MODEL_COST_COVERAGE, *labels, coverage)
    if cost is not None:
        metrics.increment(metrics.MODEL_COST, *labels, amount=cost)


async def model_call(call, *, model, operation=None, timeout=None, embeddings=False,
                     usage_totals=None, explicit_cache=False):
    """Observe one SDK invocation, including its retries and caller deadline."""
    started = time.monotonic()
    try:
        async with asyncio.timeout(timeout):
            response = await call
    except (Exception, asyncio.CancelledError) as error:
        if operation is not None:
            _record_call(operation, model, started, _failure_outcome(error), None,
                         embeddings=embeddings)
        raise

    usage = decode_usage(getattr(response, "usage", None), embeddings=embeddings)
    if usage_totals is not None:
        usage_totals["embeddings_requests" if embeddings else "responses_requests"] += 1
        if usage is not None:
            if embeddings:
                usage_totals["embedding_tokens"] += usage.input_tokens
            else:
                usage_totals["input_tokens"] += usage.input_tokens
                usage_totals["output_tokens"] += usage.output_tokens
    if operation is not None:
        status = getattr(response, "status", None)
        outcome = ("incomplete" if status == "incomplete" else
                   "provider_error" if status in ("failed", "cancelled", "queued", "in_progress")
                   else "success")
        _record_call(operation, model, started, outcome, usage, embeddings=embeddings,
                     tier=getattr(response, "service_tier", None), explicit_cache=explicit_cache)
    return response, usage


def recall_embedding(create, *, model, input):
    started = time.monotonic()
    operation = "reply_recall_embedding"
    try:
        response = create(model=model, input=input)
    except Exception as error:
        _record_call(operation, model, started, _failure_outcome(error), None, embeddings=True)
        raise
    usage = decode_usage(getattr(response, "usage", None), embeddings=True)
    _record_call(operation, model, started, "success", usage, embeddings=True)
    return response


class ChatUsage:
    def __init__(self, model):
        self.model = model
        self.calls = 0
        self.input_tokens = 0
        self.cached_input_tokens = 0
        self.output_tokens = 0
        self._estimated_cost = 0.0
        self._cost_known = True

    def add(self, usage, *, tier=None):
        usage = usage if isinstance(usage, TokenUsage) else decode_usage(usage)
        if usage is None:
            self._cost_known = False
            return
        self.calls += 1
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.cached_input_tokens += usage.cached_input_tokens
        _, cost = _estimate(self.model, usage, chat_overrides=True, tier=tier)
        if cost is None:
            self._cost_known = False
        else:
            self._estimated_cost += cost

    def estimated_cost_usd(self):
        return self._estimated_cost if self.calls and self._cost_known else None

    def log(self, elapsed_seconds):
        estimate = self.estimated_cost_usd()
        logging.info(
            "OpenAI chat usage: model=%s calls=%d input_tokens=%d cached_input_tokens=%d output_tokens=%d elapsed_ms=%d estimated_cost_usd=%s",
            self.model, self.calls, self.input_tokens, self.cached_input_tokens,
            self.output_tokens, round(elapsed_seconds * 1000),
            f"{estimate:.6f}" if estimate is not None else "unconfigured",
        )
