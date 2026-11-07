"""Aggregated OpenAI Responses usage for one Discord chat turn.

Pricing is operator-configured because model prices change and may differ by tier.
No message text, memory contents, or tool arguments are logged.
"""
import logging
import os


def _price(name):
    try:
        value = float(os.getenv(name, "0"))
        return value if value >= 0 else 0.0
    except ValueError:
        return 0.0


class ChatUsage:
    def __init__(self, model):
        self.model = model
        self.calls = 0
        self.input_tokens = 0
        self.cached_input_tokens = 0
        self.output_tokens = 0

    def add(self, usage):
        if usage is None:
            return
        self.calls += 1
        self.input_tokens += usage.input_tokens or 0
        self.output_tokens += usage.output_tokens or 0
        details = getattr(usage, "input_tokens_details", None)
        self.cached_input_tokens += (getattr(details, "cached_tokens", 0) or 0)

    def estimated_cost_usd(self):
        input_rate = _price("OPENAI_INPUT_USD_PER_1M")
        cached_rate = _price("OPENAI_CACHED_INPUT_USD_PER_1M")
        output_rate = _price("OPENAI_OUTPUT_USD_PER_1M")
        if not input_rate or not output_rate:
            return None
        cached = min(self.cached_input_tokens, self.input_tokens)
        uncached = self.input_tokens - cached
        # Without a cached-input rate, price cached tokens at the standard rate
        # rather than incorrectly treating them as free.
        cached_rate = cached_rate if cached_rate else input_rate
        return (uncached * input_rate + cached * cached_rate + self.output_tokens * output_rate) / 1_000_000

    def log(self, elapsed_seconds):
        estimate = self.estimated_cost_usd()
        logging.info(
            "OpenAI chat usage: model=%s calls=%d input_tokens=%d cached_input_tokens=%d output_tokens=%d elapsed_ms=%d estimated_cost_usd=%s",
            self.model, self.calls, self.input_tokens, self.cached_input_tokens,
            self.output_tokens, round(elapsed_seconds * 1000),
            f"{estimate:.6f}" if estimate is not None else "unconfigured",
        )
