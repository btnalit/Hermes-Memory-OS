"""Event statistics cache for O(1) status/monitor reads.

Dual writers (heartbeat primary, status fallback) both use
lock + tmp + os.replace for atomicity.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .jsonl_io import locked_jsonl_file

EVENT_STATS_SCHEMA_VERSION = "memory-os.event_stats.v0"


class EventStats:
    """Aggregated event counts for fast status/monitor reads."""

    def __init__(
        self,
        *,
        total_event_count: int = 0,
        latest_event_id: str | None = None,
        latest_event_ts: str | None = None,
        by_source: dict[str, int] | None = None,
        by_kind: dict[str, int] | None = None,
        events_root: str | None = None,
        updated_at: str | None = None,
    ) -> None:
        self.total_event_count = total_event_count
        self.latest_event_id = latest_event_id
        self.latest_event_ts = latest_event_ts
        self.by_source = by_source or {}
        self.by_kind = by_kind or {}
        self.events_root = events_root
        self.updated_at = updated_at or datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": EVENT_STATS_SCHEMA_VERSION,
            "updated_at": self.updated_at,
            "total_event_count": self.total_event_count,
            "latest_event_id": self.latest_event_id,
            "latest_event_ts": self.latest_event_ts,
            "by_source": self.by_source,
            "by_kind": self.by_kind,
            "events_root": self.events_root,
        }


def build_event_stats(events: list[dict[str, object]]) -> EventStats:
    """Build EventStats from a list of event records."""
    stats = EventStats(total_event_count=len(events))
    if events:
        last = events[-1]
        stats.latest_event_id = str(last.get("id", "")) if last.get("id") else None
        stats.latest_event_ts = str(last.get("ts", "")) if last.get("ts") else None
    for evt in events:
        src = str(evt.get("source", "unknown"))
        kind = str(evt.get("kind", "unknown"))
        stats.by_source[src] = stats.by_source.get(src, 0) + 1
        stats.by_kind[kind] = stats.by_kind.get(kind, 0) + 1
    return stats


def event_stats_path(roots: object) -> Path:
    """Return the path to event_stats.json."""
    return Path(str(roots.runtime_dir)) / "event_stats.json"


def write_event_stats(roots: object, stats: EventStats) -> None:
    """Write event_stats.json atomically under lock (dual-writer safe)."""
    stats_path = event_stats_path(roots)
    stats.updated_at = datetime.now(timezone.utc).isoformat()
    with locked_jsonl_file(stats_path) as target:
        tmp_path = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        tmp_path.write_text(
            json.dumps(stats.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp_path, target)


def read_event_stats(roots: object) -> tuple[EventStats | None, str]:
    """Read event_stats.json. Returns (EventStats | None, freshness).

    Freshness tiers: fresh (<15 min), acceptable (<30 min),
    warning (<2 h), degraded (>=2 h), missing, corrupt.
    """
    stats_path = event_stats_path(roots)
    if not stats_path.exists():
        return None, "missing"
    try:
        data = json.loads(stats_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None, "corrupt"
    updated_at = data.get("updated_at")
    if isinstance(updated_at, str) and updated_at:
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(updated_at)).total_seconds()
        except ValueError:
            age = float("inf")
        if age < 900:
            freshness = "fresh"
        elif age < 1800:
            freshness = "acceptable"
        elif age < 7200:
            freshness = "warning"
        else:
            freshness = "degraded"
    else:
        freshness = "unknown"
    return EventStats(
        total_event_count=int(data.get("total_event_count", 0)),
        latest_event_id=str(data.get("latest_event_id") or ""),
        latest_event_ts=str(data.get("latest_event_ts") or ""),
        by_source=dict(data.get("by_source") or {}),
        by_kind=dict(data.get("by_kind") or {}),
        events_root=str(data.get("events_root") or ""),
        updated_at=str(updated_at),
    ), freshness
