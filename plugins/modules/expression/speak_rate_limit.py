"""Deterministic rolling-window rate limiter for spontaneous owner speech.

Pure function — no state, no I/O, no LLM. Counts delivered records from
speak_gate deliveries.jsonl within the past 60 minutes and enforces a
hard cap of 5 per rolling window.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

MAX_PER_HOUR = 5
WINDOW_SECONDS = 3600


def under_speak_limit(
    deliveries: list[dict[str, Any]],
    now: datetime | None = None,
    max_per_hour: int | None = None,
) -> bool:
    """Return True if fewer than max_per_hour deliveries in the past WINDOW_SECONDS.

    Args:
        deliveries: List of delivery records from speak_gate deliveries.jsonl.
                    Each record must have 'decision' (str) and 'ts' (ISO str).
        now: Current time for the window cutoff. Uses UTC now if omitted.
        max_per_hour: Explicit limit supplied by the stateful caller. If None,
                      uses the pure deterministic MAX_PER_HOUR fallback.

    Returns:
        True if a new spontaneous expression may be delivered (under limit).
        False if the limit has been reached (should rate-limit).
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=WINDOW_SECONDS)
    recent = [
        d for d in deliveries
        if d.get("decision") == "delivered"
        and _parse_ts(d.get("ts", "")) > cutoff
    ]
    if max_per_hour is None:
        max_per_hour = MAX_PER_HOUR
    return len(recent) < max_per_hour


def _parse_ts(ts: str) -> datetime:
    """Parse an ISO timestamp string.

    Returns datetime.min on any parse failure so the delivery is treated
    as ancient and never counted (safe default — avoid false rate-limit).
    A successfully-parsed but timezone-naive value (no offset) is treated
    as UTC rather than returned naive: this store's own writer stamps
    aware UTC timestamps, so a naive value only reaches here via a
    hand-edited/legacy record, and comparing it as-is against the aware
    `cutoff` in under_speak_limit would raise TypeError instead of
    hitting this function's own fail-open contract.
    """
    if not ts:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        ts_clean = str(ts).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(ts_clean)
    except (ValueError, TypeError):
        return datetime.min.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
