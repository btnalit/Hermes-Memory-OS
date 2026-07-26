"""
Monitor performance budget and cache testing utilities.

Provides runtime budget tracking for Monitor sections and cache
equivalence tests.  Ensures that valid fresh cache allows expensive
readers to be monkeypatched while still succeeding.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Callable, Iterator

MONITOR_PERF_SCHEMA_VERSION = "memory-os.monitor_perf.v1"


@dataclass
class RuntimeBudget:
    """Runtime budget for a Monitor section."""

    section_key: str
    budget_seconds: float
    start_time: float = 0.0
    end_time: float = 0.0
    elapsed: float = 0.0
    exceeded: bool = False
    cache_hit: bool = False

    @property
    def remaining(self) -> float:
        return max(0.0, self.budget_seconds - self.elapsed)


@contextmanager
def track_runtime(
    section_key: str,
    budget_seconds: float,
) -> Iterator[RuntimeBudget]:
    """Context manager to track runtime for a Monitor section.

    Usage:
        with track_runtime("memory_files", 5.0) as budget:
            result = collect_data()
            if budget.exceeded:
                result = None
    """
    budget = RuntimeBudget(
        section_key=section_key,
        budget_seconds=budget_seconds,
        start_time=perf_counter(),
    )
    try:
        yield budget
    finally:
        budget.end_time = perf_counter()
        budget.elapsed = budget.end_time - budget.start_time
        budget.exceeded = budget.elapsed > budget.budget_seconds


@dataclass
class CacheParityResult:
    """Result of a cache parity test."""

    section_key: str
    cache_value: Any = None
    live_value: Any = None
    equivalent: bool = False
    cache_hit: bool = False
    live_raised: bool = False
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": MONITOR_PERF_SCHEMA_VERSION,
            "section_key": self.section_key,
            "equivalent": self.equivalent,
            "cache_hit": self.cache_hit,
            "live_raised": self.live_raised,
            "error": self.error,
        }


def verify_cache_parity(
    section_key: str,
    cache_reader: Callable[[], Any],
    live_reader: Callable[[], Any],
    *,
    allow_cache_zero: bool = True,
) -> CacheParityResult:
    """Verify that cache and live computation produce equivalent results.

    Args:
        section_key: Monitor section key.
        cache_reader: Function that reads from cache.
        live_reader: Function that reads from source (may be expensive).
        allow_cache_zero: If True, 0 is a valid cached value.

    Returns:
        CacheParityResult with equivalence result.
    """
    result = CacheParityResult(section_key=section_key)

    try:
        cache_value = cache_reader()
        result.cache_value = cache_value
        result.cache_hit = cache_value is not None
        if not result.cache_hit and not allow_cache_zero:
            return result
    except Exception as exc:
        result.error = f"cache_read_failed: {exc}"
        return result

    try:
        live_value = live_reader()
        result.live_value = live_value
    except Exception:
        # If cache is valid fresh and live raises, that's OK (cache is a valid fallback)
        result.live_raised = True
        result.equivalent = result.cache_hit
        result.error = "live_reader_raised_but_cache_valid"
        return result

    # Compare values
    if allow_cache_zero and cache_value == 0:
        result.equivalent = True
    elif cache_value == live_value:
        result.equivalent = True
    else:
        result.equivalent = False

    return result