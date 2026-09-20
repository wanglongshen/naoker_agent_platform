from __future__ import annotations

import time

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

WORKER_UPTIME = Gauge(
    "agent_worker_uptime_seconds",
    "Seconds since worker process started",
)
WORKER_CLAIMED = Counter(
    "agent_worker_claimed_total",
    "Total attempts claimed by worker",
)
WORKER_ACTIVE = Gauge(
    "agent_worker_active_attempts",
    "Currently active attempts being processed",
)
WORKER_POLL_LATENCY = Histogram(
    "agent_worker_poll_latency_ms",
    "Worker main loop poll latency in milliseconds",
    buckets=(1, 5, 10, 25, 50, 100, 250, 500, 1000),
)
WORKER_ERRORS = Counter(
    "agent_worker_error_total",
    "Total errors encountered by worker",
)
WORKER_HEARTBEATS = Counter(
    "agent_worker_heartbeats_total",
    "Total heartbeat ticks emitted",
)

_worker_start_time = time.monotonic()


def worker_uptime_seconds() -> float:
    return time.monotonic() - _worker_start_time


def render_metrics() -> str:
    WORKER_UPTIME.set(worker_uptime_seconds())
    return generate_latest().decode("utf-8")


def metrics_content_type() -> str:
    return CONTENT_TYPE_LATEST
