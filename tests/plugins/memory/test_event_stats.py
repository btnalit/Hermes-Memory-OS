"""Tests for event_stats cache (V4.1 P1-2/3 counterfactuals).

Covers:
  - build/write/read round-trip
  - freshness tiers: fresh / acceptable / warning / degraded / missing / corrupt
  - missing fallback writeback
  - corrupt fallback writeback
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from plugins.memory.memory_os.event_stats import (
    EventStats,
    build_event_stats,
    event_stats_path,
    read_event_stats,
    write_event_stats,
)
from plugins.memory.memory_os.roots import MemoryOSRoots


def _make_roots(tmp_path: Path) -> MemoryOSRoots:
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="main")
    roots.memory_os_root.mkdir(parents=True, exist_ok=True)
    (roots.memory_os_root / "runtime").mkdir(parents=True, exist_ok=True)
    return roots


def _make_event_dicts(count: int) -> list[dict]:
    return [
        {
            "id": f"evt-{i:04d}",
            "ts": (datetime.now(timezone.utc) - timedelta(minutes=i)).isoformat(),
            "source": "test-source",
            "kind": "test-kind",
            "source_class": "general",
            "protected": False,
        }
        for i in range(count)
    ]


# ── Round-trip ────────────────────────────────────────────────────────

def test_build_write_read_round_trip(tmp_path):
    """build_event_stats → write → read produces same counts."""
    roots = _make_roots(tmp_path)
    events = _make_event_dicts(42)
    stats = build_event_stats(events)
    stats.events_root = str(roots.events_root)

    write_event_stats(roots, stats)

    read_back, freshness = read_event_stats(roots)
    assert read_back is not None
    assert read_back.total_event_count == 42
    assert freshness in ("fresh", "acceptable")


def test_write_event_stats_is_atomic(tmp_path):
    """write_event_stats produces valid JSON that can be re-read."""
    roots = _make_roots(tmp_path)
    events = _make_event_dicts(10)
    stats = build_event_stats(events)
    stats.events_root = str(roots.events_root)

    write_event_stats(roots, stats)
    path = event_stats_path(roots)
    assert path.exists()
    # Should be valid JSON
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["total_event_count"] == 10


# ── Freshness tiers ───────────────────────────────────────────────────

def test_freshness_missing(tmp_path):
    """No cache file → freshness='missing'."""
    roots = _make_roots(tmp_path)
    stats, freshness = read_event_stats(roots)
    assert stats is None
    assert freshness == "missing"


def test_freshness_corrupt(tmp_path):
    """Invalid JSON → freshness='corrupt'."""
    roots = _make_roots(tmp_path)
    path = event_stats_path(roots)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("this is not valid json", encoding="utf-8")

    stats, freshness = read_event_stats(roots)
    assert stats is None
    assert freshness == "corrupt"


def test_freshness_fresh(tmp_path):
    """Recently written cache (<15 min) → freshness='fresh'."""
    roots = _make_roots(tmp_path)
    events = _make_event_dicts(5)
    stats = build_event_stats(events)
    stats.events_root = str(roots.events_root)
    write_event_stats(roots, stats)

    _, freshness = read_event_stats(roots)
    assert freshness == "fresh"


def test_freshness_degraded_from_old_timestamp(tmp_path, monkeypatch):
    """Cache older than 2h → freshness='degraded'."""
    roots = _make_roots(tmp_path)
    path = event_stats_path(roots)
    path.parent.mkdir(parents=True, exist_ok=True)
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    path.write_text(
        json.dumps({
            "schema_version": "memory-os.event_stats.v0",
            "total_event_count": 5,
            "latest_event_id": "",
            "latest_event_ts": "",
            "by_source": {},
            "by_kind": {},
            "events_root": str(roots.events_root),
            "updated_at": old_ts,
        }),
        encoding="utf-8",
    )

    _, freshness = read_event_stats(roots)
    assert freshness == "degraded"


def test_freshness_warning(tmp_path):
    """Cache 30min-2h old → freshness='warning'."""
    roots = _make_roots(tmp_path)
    path = event_stats_path(roots)
    path.parent.mkdir(parents=True, exist_ok=True)
    warn_ts = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat()
    path.write_text(
        json.dumps({
            "schema_version": "memory-os.event_stats.v0",
            "total_event_count": 5,
            "latest_event_id": "",
            "latest_event_ts": "",
            "by_source": {},
            "by_kind": {},
            "events_root": str(roots.events_root),
            "updated_at": warn_ts,
        }),
        encoding="utf-8",
    )

    _, freshness = read_event_stats(roots)
    assert freshness == "warning"


# ── Counterfactual: fallback writeback ────────────────────────────────

def test_status_fallback_missing_stats_rebuilds_cache(tmp_path):
    """When no event_stats.json exists, a rebuild writes the cache file."""
    roots = _make_roots(tmp_path)
    events = _make_event_dicts(10)
    stats = build_event_stats(events)
    stats.events_root = str(roots.events_root)

    # Simulate fallback writeback
    write_event_stats(roots, stats)

    path = event_stats_path(roots)
    assert path.exists()
    read_back, freshness = read_event_stats(roots)
    assert read_back is not None
    assert read_back.total_event_count == 10
    assert freshness == "fresh"


def test_status_fallback_corrupt_stats_rebuilds_cache(tmp_path):
    """When event_stats.json is corrupt, rebuild overwrites with valid data."""
    roots = _make_roots(tmp_path)
    path = event_stats_path(roots)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{{{broken json", encoding="utf-8")

    # Verify it's corrupt
    stats, freshness = read_event_stats(roots)
    assert stats is None
    assert freshness == "corrupt"

    # Simulate rebuild
    events = _make_event_dicts(7)
    new_stats = build_event_stats(events)
    new_stats.events_root = str(roots.events_root)
    write_event_stats(roots, new_stats)

    # Now it should be valid
    read_back, freshness = read_event_stats(roots)
    assert read_back is not None
    assert read_back.total_event_count == 7
    assert freshness in ("fresh", "acceptable")
