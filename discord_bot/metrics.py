"""Process-local Prometheus metrics for the Discord bot."""
import asyncio
import json
import logging
import time

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
