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
) -> bool:
    """Return True if fewer than MAX_PER_HOUR deliveries in the past WINDOW_SECONDS.

    Args:
        deliveries: List of delivery records from speak_gate deliveries.jsonl.
                    Each record must have 'decision' (str) and 'ts' (ISO str).
        now: Current time for the window cutoff. Uses UTC now if omitted.

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
    return len(recent) < MAX_PER_HOUR


def _parse_ts(ts: str) -> datetime:
    """Parse an ISO timestamp string.

    Returns datetime.min on any parse failure so the delivery is treated
    as ancient and never counted (safe default — avoid false rate-limit).
    """
    if not ts:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        ts_clean = str(ts).replace("Z", "+00:00")
        return datetime.fromisoformat(ts_clean)
    except (ValueError, TypeError):
        return datetime.min.replace(tzinfo=timezone.utc)
