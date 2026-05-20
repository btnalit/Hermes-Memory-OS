"""Benchmark harness for Memory-OS v0."""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .fixtures import generate_event_corpus
from .index import MemoryOSIndex
from .prefetch import build_prefetch
from .schema import EventEnvelope
from .store import MemoryOSStore
from .working import WorkingMemoryService


LARGE_BENCHMARK_THRESHOLD = 100_000

DEFAULT_SLO = {
    "sync_turn_enqueue_p95_ms": 20.0,
    "event_append_p95_ms": 20.0,
    "prefetch_cold_ms": 100.0,
    "prefetch_warm_ms": 100.0,
    "sqlite_rebuild_ms_per_1k": 500.0,
    "working_decay_ms_per_1k": 500.0,
    "status_command_ms": 100.0,
}


@dataclass(frozen=True)
class BenchmarkConfig:
    record_count: int
    seed: int = 1
    profile: str = "memoryos-test"
    large_opt_in: bool = False


def run_benchmark(store: MemoryOSStore, config: BenchmarkConfig) -> dict[str, Any]:
    if config.record_count >= LARGE_BENCHMARK_THRESHOLD and not config.large_opt_in:
        return {
            "schema_version": "memory-os.benchmark.v0",
            "record_count": config.record_count,
            "skipped": True,
            "large_opt_in_required": True,
            "reason": "Large benchmark requires explicit opt-in.",
            "corpus": {
                "source": "fixtures.generate_event_corpus",
                "seed": config.seed,
                "profile": config.profile,
            },
            "metrics": {},
            "slo": dict(DEFAULT_SLO),
            "pass": False,
        }

    events = [EventEnvelope.from_dict(raw) for raw in generate_event_corpus(
        count=config.record_count,
        seed=config.seed,
        profile=config.profile,
    )]
    append_durations = []
    for event in events:
        started = time.perf_counter()
        store.append_event(event)
        append_durations.append(_elapsed_ms(started))

    working = WorkingMemoryService(store)
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    for index in range(min(config.record_count, 100)):
        working.add_item("lingering", f"Synthetic benchmark working item {index}", now=now)

    started = time.perf_counter()
    cold_context = build_prefetch("synthetic", budget_chars=2200, store=store, index=None)
    prefetch_cold_ms = _elapsed_ms(started)

    started = time.perf_counter()
    warm_context = build_prefetch("synthetic", budget_chars=2200, store=store, index=None)
    prefetch_warm_ms = _elapsed_ms(started)

    started = time.perf_counter()
    MemoryOSIndex(store.roots).rebuild_from_store(store)
    sqlite_rebuild_ms = _elapsed_ms(started)

    started = time.perf_counter()
    working.decay_items("lingering", now=now + timedelta(hours=1))
    working_decay_ms = _elapsed_ms(started)

    started = time.perf_counter()
    status_counts = {
        "events": len(store.read_events()),
        "prefetch_cold_chars": len(cold_context),
        "prefetch_warm_chars": len(warm_context),
    }
    status_command_ms = _elapsed_ms(started)

    metrics = {
        "event_append_p95_ms": _p95(append_durations),
        "prefetch_cold_ms": prefetch_cold_ms,
        "prefetch_warm_ms": prefetch_warm_ms,
        "sqlite_rebuild_ms": sqlite_rebuild_ms,
        "working_decay_ms": working_decay_ms,
        "status_command_ms": status_command_ms,
    }
    checks = _slo_checks(metrics, config.record_count)
    return {
        "schema_version": "memory-os.benchmark.v0",
        "record_count": config.record_count,
        "skipped": False,
        "large_opt_in_required": config.record_count >= LARGE_BENCHMARK_THRESHOLD,
        "corpus": {
            "source": "fixtures.generate_event_corpus",
            "seed": config.seed,
            "profile": config.profile,
        },
        "metrics": metrics,
        "status_counts": status_counts,
        "slo": dict(DEFAULT_SLO),
        "slo_checks": checks,
        "pass": all(check["pass"] for check in checks.values()),
    }


def _slo_checks(metrics: dict[str, float], record_count: int) -> dict[str, dict[str, Any]]:
    scale = max(record_count / 1000.0, 1.0)
    checks = {
        "event_append_p95_ms": (metrics["event_append_p95_ms"], DEFAULT_SLO["event_append_p95_ms"]),
        "prefetch_cold_ms": (metrics["prefetch_cold_ms"], DEFAULT_SLO["prefetch_cold_ms"]),
        "prefetch_warm_ms": (metrics["prefetch_warm_ms"], DEFAULT_SLO["prefetch_warm_ms"]),
        "sqlite_rebuild_ms": (metrics["sqlite_rebuild_ms"], DEFAULT_SLO["sqlite_rebuild_ms_per_1k"] * scale),
        "working_decay_ms": (metrics["working_decay_ms"], DEFAULT_SLO["working_decay_ms_per_1k"] * scale),
        "status_command_ms": (metrics["status_command_ms"], DEFAULT_SLO["status_command_ms"]),
    }
    return {
        name: {"actual_ms": actual, "limit_ms": limit, "pass": actual <= limit}
        for name, (actual, limit) in checks.items()
    }


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000.0


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=20, method="inclusive")[18]
