"""Process-local Prometheus metrics for the Discord bot."""
import asyncio
import json
import logging
import time
from contextlib import contextmanager

from aiohttp import web
from prometheus_client import (
    CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram,
    ProcessCollector, generate_latest,
)

REGISTRY = CollectorRegistry()
ProcessCollector(registry=REGISTRY)
PREFIX = "discord_bot_"
METRICS_PORT = 9100

REQUESTS = Counter(PREFIX + "requests_total", "Terminal Discord reply requests.",
                   ("route", "outcome"), registry=REGISTRY)
REQUEST_DURATION = Histogram(
    PREFIX + "request_duration_seconds", "Discord reply handling through terminal delivery.",
    ("route",), buckets=(0.25, 0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300), registry=REGISTRY,
)
TOOL_EXECUTIONS = Counter(
    PREFIX + "tool_executions_total", "Terminal tool executions.",
    ("tool", "source", "outcome"), registry=REGISTRY,
)
TOOL_DURATION = Histogram(
    PREFIX + "tool_execution_duration_seconds", "Elapsed time observed by the tool caller.",
    ("tool", "source"), buckets=(0.1, 0.5, 1, 2, 5, 10, 12, 20, 30, 45), registry=REGISTRY,
)
TOOL_REJECTIONS = Counter(
    PREFIX + "tool_rejections_total", "Tool requests rejected before execution.",
    ("tool", "source", "reason"), registry=REGISTRY,
)
GATEWAY_CONNECTED = Gauge(
    PREFIX + "gateway_connected", "Whether the Discord gateway is connected.", registry=REGISTRY,
)


def increment(metric, *labels, amount=1):
    try:
        (metric.labels(*labels) if labels else metric).inc(amount)
    except Exception:
        logging.getLogger(__name__).debug("Prometheus counter update failed")


def observe(metric, started, *labels):
    try:
        (metric.labels(*labels) if labels else metric).observe(time.monotonic() - started)
    except Exception:
        logging.getLogger(__name__).debug("Prometheus histogram update failed")


def set_gauge(metric, value, *labels):
    try:
        (metric.labels(*labels) if labels else metric).set(value)
    except Exception:
        logging.getLogger(__name__).debug("Prometheus gauge update failed")


async def run_tool(call, *, tool, source, timeout=None):
    """Observe a dispatched tool through the deadline seen by its caller."""
    started = time.monotonic()
    outcome = "error"
    try:
        async with asyncio.timeout(timeout):
            result = await call
        try:
            payload = json.loads(result) if isinstance(result, str) else result
        except (ValueError, RecursionError):
            payload = None
        if isinstance(payload, dict) and payload.get("ok") is False:
            error = payload.get("error")
            code = error.get("code") if isinstance(error, dict) else None
            if code == "UNKNOWN_TOOL":
                outcome = None
                increment(TOOL_REJECTIONS, tool, source, "unknown_tool")
            elif code == "TIMEOUT":
                outcome = "timeout"
        else:
            outcome = "success"
        return result
    except TimeoutError:
        outcome = "timeout"
        raise
    except asyncio.CancelledError:
        outcome = "cancelled"
        raise
    finally:
        if outcome is not None:
            increment(TOOL_EXECUTIONS, tool, source, outcome)
            observe(TOOL_DURATION, started, tool, source)


async def start_metrics_server(host="0.0.0.0", port=METRICS_PORT, *, registry=REGISTRY):
    async def scrape(_request):
        return web.Response(body=generate_latest(registry),
                            headers={"Content-Type": CONTENT_TYPE_LATEST})

    app = web.Application()
    app.router.add_get("/metrics", scrape)
    runner = web.AppRunner(app, access_log=None, shutdown_timeout=2)
    await runner.setup()
    try:
        await web.TCPSite(runner, host, port).start()
    except BaseException:
        await runner.cleanup()
        raise
    return runner


MODEL_CALLS = Counter(
    PREFIX + "model_calls_total", "Terminal logical OpenAI SDK calls.",
    ("operation", "model", "outcome"), registry=REGISTRY,
)
MODEL_DURATION = Histogram(
    PREFIX + "model_call_duration_seconds", "Elapsed time of logical OpenAI SDK calls.",
    ("operation",), buckets=(0.1, 0.5, 1, 2, 5, 10, 15, 25, 30, 45, 60, 120),
    registry=REGISTRY,
)
MODEL_TOKENS = Counter(
    PREFIX + "model_tokens_total", "OpenAI-reported tokens. Cached input is included in input.",
    ("operation", "model", "kind"), registry=REGISTRY,
)
MODEL_COST = Counter(
    PREFIX + "model_estimated_cost_usd_total", "Estimated OpenAI token charges in USD.",
    ("operation", "model"), registry=REGISTRY,
)
MODEL_COST_COVERAGE = Counter(
    PREFIX + "model_cost_coverage_total", "Availability of a cost estimate by logical call.",
    ("operation", "model", "status"), registry=REGISTRY,
)


DISCOVERY_RUNS = Counter(PREFIX + "discovery_runs_total", "Terminal reserved discovery runs.",
                         ("outcome",), registry=REGISTRY)
DISCOVERY_SELECTIONS = Counter(PREFIX + "discovery_selections_total", "Selected discovery drafts.",
                               registry=REGISTRY)
DISCOVERY_ATTEMPTS = Counter(PREFIX + "discovery_delivery_attempts_total", "Discovery send attempts.",
                             registry=REGISTRY)
DISCOVERY_DELIVERIES = Counter(PREFIX + "discovery_deliveries_total", "Selected draft delivery outcomes.",
                               ("outcome",), registry=REGISTRY)
DISCOVERY_DEFERRALS = Counter(PREFIX + "discovery_deferrals_total", "Persisted discovery deferrals.",
                              ("reason",), registry=REGISTRY)
MEMORY_WINDOWS = Counter(PREFIX + "memory_extraction_windows_total", "Memory extraction window outcomes.",
                         ("outcome",), registry=REGISTRY)
MEMORY_CANDIDATES = Counter(PREFIX + "memory_candidate_outcomes_total", "Memory candidate dispositions.",
                            ("outcome",), registry=REGISTRY)
REACTION_DECISIONS = Counter(PREFIX + "reaction_decisions_total", "Autonomous reaction evaluations.",
                             ("trigger", "outcome"), registry=REGISTRY)
REACTION_ATTEMPTS = Counter(PREFIX + "reaction_delivery_attempts_total", "Discord add-reaction attempts.",
                            ("source",), registry=REGISTRY)
REACTION_DELIVERIES = Counter(PREFIX + "reaction_deliveries_total", "Discord reaction delivery outcomes.",
                              ("source", "outcome"), registry=REGISTRY)
REACTION_SKIPS = Counter(PREFIX + "reaction_skips_total", "Autonomous reaction scheduling gates.",
                         ("trigger", "reason"), registry=REGISTRY)

WORKER_RUNNING = Gauge(PREFIX + "worker_running", "Whether the background task is running.",
                       ("worker",), registry=REGISTRY)
WORKER_CYCLES = Counter(PREFIX + "worker_cycles_total", "Terminal worker cycles.",
                        ("worker", "outcome"), registry=REGISTRY)
WORKER_LAST_SUCCESS = Gauge(
    PREFIX + "worker_last_success_timestamp_seconds", "Unix time of the last clean worker cycle.",
    ("worker",), registry=REGISTRY,
)
WORKER_CYCLE_STARTED = Gauge(
    PREFIX + "worker_cycle_started_timestamp_seconds", "Unix start time of current work, or zero.",
    ("worker",), registry=REGISTRY,
)

for worker in ("discovery", "autonomous_memory", "reaction_poller", "reaction_evaluator",
               "archive_reconciliation"):
    for gauge in (WORKER_RUNNING, WORKER_LAST_SUCCESS, WORKER_CYCLE_STARTED):
        gauge.labels(worker)


@contextmanager
def worker_running(worker):
    set_gauge(WORKER_RUNNING, 1, worker)
    try:
        yield
    finally:
        set_gauge(WORKER_RUNNING, 0, worker)


@contextmanager
def worker_cycle(worker):
    outcome = "success"
    set_gauge(WORKER_CYCLE_STARTED, time.time(), worker)

    def finish(result):
        nonlocal outcome
        outcome = result

    try:
        yield finish
    except asyncio.CancelledError:
        outcome = "cancelled"
        raise
    except Exception:
        outcome = "failed"
        raise
    finally:
        set_gauge(WORKER_CYCLE_STARTED, 0, worker)
        increment(WORKER_CYCLES, worker, outcome)
        if outcome in ("success", "idle"):
            set_gauge(WORKER_LAST_SUCCESS, time.time(), worker)
