"""Event statistics cache for O(1) status/monitor reads.

Dual writers (heartbeat primary, status fallback) both use
lock + tmp + os.replace for atomicity.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .jsonl_io import locked_jsonl_file

EVENT_STATS_SCHEMA_VERSION = "memory-os.event_stats.v0"

# Continuity selector constants — mirrors prefetch._BRIDGE_SEED_SLOTS / _MAX_CONTINUITY_RECORDS
_CONTINUITY_SEED_SLOTS: dict[str, int] = {
    "foreground": 2,
    "cron": 1,
    "mailbox": 1,
    "room_family": 1,
    "state_source": 1,
    "governance": 1,
}
_MAX_CONTINUITY_RECORDS: int = 8
_SOURCE_CLASS_PRIORITY: list[str] = [
    "cron", "mailbox", "room_family", "foreground",
    "state_source", "governance", "other",
]


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
        recent_event_summaries: list[dict[str, str]] | None = None,
        continuity_selector: dict[str, object] | None = None,
    ) -> None:
        self.total_event_count = total_event_count
        self.latest_event_id = latest_event_id
        self.latest_event_ts = latest_event_ts
        self.by_source = by_source or {}
        self.by_kind = by_kind or {}
        self.events_root = events_root
        self.updated_at = updated_at or datetime.now(timezone.utc).isoformat()
        self.recent_event_summaries: list[dict[str, str]] = recent_event_summaries or []
        self.continuity_selector: dict[str, object] = continuity_selector or {}

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
            "recent_event_summaries": self.recent_event_summaries,
            "continuity_selector": self.continuity_selector,
        }


def _dict_source_class(evt: dict[str, object]) -> str:
    """Dict-based source class classifier — mirrors prefetch._event_source_class."""
    safe_ref = evt.get("safe_ref") if isinstance(evt.get("safe_ref"), dict) else {}
    source = str(evt.get("source", "")).lower()
    kind = str(evt.get("kind", "")).lower()
    tags = {str(t).lower() for t in (evt.get("tags") or [])}
    source_module = str(safe_ref.get("source_module", "")).lower()
    source_class = str(safe_ref.get("source_class", "")).lower()
    platform = str(safe_ref.get("platform", "")).lower()
    if source_module == "cron_mirror" or source == "cron" or "cron" in tags or platform == "cron":
        return "cron"
    if source_module == "state_source_mirror" or source_class.startswith("state:") or source == "state_source_mirror":
        return "state_source"
    if platform == "mailbox" or source == "mailbox" or "mailbox" in tags:
        return "mailbox"
    if platform in {"room", "family", "household"} or source in {"room", "family", "household"}:
        return "room_family"
    if source_module in {"ops_gate", "proposal_queue", "evidence_scoring", "self_evolution"}:
        return "governance"
    if any(marker in kind for marker in ("proposal", "governance", "evidence", "ops_gate", "self_evolution")):
        return "governance"
    if kind in {"conversation_turn", "memory_write", "conversation_turn_mirrored"}:
        return "foreground"
    return "other"


def _build_continuity_selector(events: list[dict[str, object]]) -> dict[str, object]:
    """Compute continuity selector summary from sorted event dicts.

    Deterministic mirror of _select_continuity_events + continuity_selector_report
    using dicts instead of EventEnvelope objects.  Runs in O(N) inside
    build_event_stats so CLI status can read the result in O(1).
    """
    if not events:
        return {
            "schema_version": "memory-os.continuity_selector.v0",
            "selected_total": 0,
            "dropped_total": 0,
            "selected_by_source_class": {},
            "dropped_by_source_class": {},
            "seed_slots": dict(_CONTINUITY_SEED_SLOTS),
            "max_records": _MAX_CONTINUITY_RECORDS,
        }

    # newest-first for seed slot selection
    events_rev: list[dict[str, object]] = list(reversed(events))
    buckets: dict[str, list[dict[str, object]]] = {sc: [] for sc in _CONTINUITY_SEED_SLOTS}
    for evt in events_rev:
        sc = _dict_source_class(evt)
        if sc in buckets:
            buckets[sc].append(evt)

    selected_ids: set[str] = set()

    # Phase 1: fill seed slots (most recent per source_class, capped)
    for source_class, limit in _CONTINUITY_SEED_SLOTS.items():
        for evt in buckets[source_class][:limit]:
            if len(selected_ids) >= _MAX_CONTINUITY_RECORDS:
                break
            eid = str(evt.get("id", ""))
            if eid and eid not in selected_ids:
                selected_ids.add(eid)

    # Phase 2: fill remaining slots by priority + recency
    remaining = [evt for evt in events_rev if str(evt.get("id", "")) not in selected_ids]

    def _global_sort_key(evt: dict[str, object]) -> tuple[int, str, str]:
        sc = _dict_source_class(evt)
        priority = _SOURCE_CLASS_PRIORITY.index(sc) if sc in _SOURCE_CLASS_PRIORITY else 99
        return (-priority, str(evt.get("ts", "")), str(evt.get("id", "")))

    for evt in sorted(remaining, key=_global_sort_key, reverse=True):
        if len(selected_ids) >= _MAX_CONTINUITY_RECORDS:
            break
        eid = str(evt.get("id", ""))
        if eid and eid not in selected_ids:
            selected_ids.add(eid)

    selected_by_sc = Counter(
        _dict_source_class(evt) for evt in events_rev
        if str(evt.get("id", "")) in selected_ids
    )
    dropped_by_sc = Counter(
        _dict_source_class(evt) for evt in events_rev
        if str(evt.get("id", "")) not in selected_ids
    )

    return {
        "schema_version": "memory-os.continuity_selector.v0",
        "selected_total": len(selected_ids),
        "dropped_total": len(events) - len(selected_ids),
        "selected_by_source_class": dict(selected_by_sc),
        "dropped_by_source_class": dict(dropped_by_sc),
        "seed_slots": dict(_CONTINUITY_SEED_SLOTS),
        "max_records": _MAX_CONTINUITY_RECORDS,
    }


def build_event_stats(events: list[dict[str, object]]) -> EventStats:
    """Build EventStats from a list of event records (assumed sorted by ts).

    Captures bounded recent_event_summaries and continuity_selector so
    status/monitor consumers can read O(1) without a full event scan + sort.
    """
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
    stats.recent_event_summaries = [
        {
            "id": str(evt.get("id", "")),
            "ts": str(evt.get("ts", "")),
            "kind": str(evt.get("kind", "")),
            "summary": str(evt.get("summary", "")),
        }
        for evt in events[-5:]
    ]
    stats.continuity_selector = _build_continuity_selector(events)
    return stats


def event_stats_path(roots: object) -> Path:
    """Return the path to event_stats.json."""
    return Path(str(roots.memory_os_root)) / "runtime" / "event_stats.json"


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
    recent_summaries: list[dict[str, str]] = []
    raw_recent = data.get("recent_event_summaries")
    if isinstance(raw_recent, list):
        for item in raw_recent:
            if isinstance(item, dict):
                recent_summaries.append({
                    "id": str(item.get("id", "")),
                    "ts": str(item.get("ts", "")),
                    "kind": str(item.get("kind", "")),
                    "summary": str(item.get("summary", "")),
                })
    continuity_selector: dict[str, object] = {}
    raw_cs = data.get("continuity_selector")
    if isinstance(raw_cs, dict):
        continuity_selector = {
            "schema_version": str(raw_cs.get("schema_version", "")),
            "selected_total": int(raw_cs.get("selected_total", 0)),
            "dropped_total": int(raw_cs.get("dropped_total", 0)),
            "selected_by_source_class": dict(raw_cs.get("selected_by_source_class") or {}),
            "dropped_by_source_class": dict(raw_cs.get("dropped_by_source_class") or {}),
            "seed_slots": dict(raw_cs.get("seed_slots") or {}),
            "max_records": int(raw_cs.get("max_records", 0)),
        }
    return EventStats(
        total_event_count=int(data.get("total_event_count", 0)),
        latest_event_id=str(data.get("latest_event_id") or ""),
        latest_event_ts=str(data.get("latest_event_ts") or ""),
        by_source=dict(data.get("by_source") or {}),
        by_kind=dict(data.get("by_kind") or {}),
        events_root=str(data.get("events_root") or ""),
        updated_at=str(updated_at),
        recent_event_summaries=recent_summaries,
        continuity_selector=continuity_selector,
    ), freshness
