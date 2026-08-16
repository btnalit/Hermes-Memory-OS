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


# ── Fix 5: recent_event_summaries in event_stats ──────────────────────

def test_build_event_stats_captures_recent_summaries():
    """build_event_stats stores the last 5 event summaries for O(1) status."""
    events = _make_event_dicts(20)
    stats = build_event_stats(events)

    assert len(stats.recent_event_summaries) == 5
    # Last event in the list should be the most recent (events are reversed by time)
    assert stats.recent_event_summaries[-1]["id"] == "evt-0019"
    assert stats.recent_event_summaries[-1]["kind"] == "test-kind"


def test_build_event_stats_fewer_than_5_events():
    """When there are fewer than 5 events, all summaries are captured."""
    events = _make_event_dicts(3)
    stats = build_event_stats(events)

    assert len(stats.recent_event_summaries) == 3
    assert stats.recent_event_summaries[0]["id"] == "evt-0000"


def test_event_stats_roundtrip_recent_summaries(tmp_path):
    """recent_event_summaries survive write → read roundtrip."""
    roots = _make_roots(tmp_path)
    events = _make_event_dicts(8)
    stats = build_event_stats(events)
    stats.events_root = str(roots.events_root)
    write_event_stats(roots, stats)

    read_back, freshness = read_event_stats(roots)
    assert read_back is not None
    assert len(read_back.recent_event_summaries) == 5
    assert read_back.recent_event_summaries[-1]["id"] == "evt-0007"
    assert all("id" in s and "ts" in s and "kind" in s and "summary" in s
               for s in read_back.recent_event_summaries)


def test_legacy_event_stats_without_recent_summaries_returns_empty(tmp_path):
    """Event stats written before the schema addition default to empty list."""
    roots = _make_roots(tmp_path)
    path = event_stats_path(roots)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write legacy-format stats (no recent_event_summaries field)
    path.write_text(json.dumps({
        "schema_version": "memory-os.event_stats.v0",
        "updated_at": "2026-07-01T00:00:00+00:00",
        "total_event_count": 42,
        "latest_event_id": "ev-old",
        "latest_event_ts": "2026-07-01T00:00:00+00:00",
        "by_source": {"test": 42},
        "by_kind": {"note": 42},
        "events_root": str(roots.events_root),
    }), encoding="utf-8")

    stats, freshness = read_event_stats(roots)
    assert stats is not None
    assert stats.recent_event_summaries == [], (
        "Legacy stats without recent_event_summaries must default to empty list"
    )


# ── Fix 5b: continuity_selector caching in event_stats ─────────────────

def _make_event_dict_with_source_class(
    evt_id: str,
    ts: str,
    *,
    source: str = "foreground",
    kind: str = "conversation_turn",
    safe_ref: dict | None = None,
) -> dict:
    return {
        "id": evt_id,
        "ts": ts,
        "source": source,
        "kind": kind,
        "summary": f"summary-{evt_id}",
        "source_class": "general",
        "protected": False,
        "safe_ref": safe_ref or {"source_class": source},
        "tags": [],
    }


def test_build_event_stats_includes_continuity_selector():
    """build_event_stats produces continuity_selector with correct structure."""
    events = _make_event_dicts(10)
    stats = build_event_stats(events)

    cs = stats.continuity_selector
    assert isinstance(cs, dict), "continuity_selector must be a dict"
    assert cs["schema_version"] == "memory-os.continuity_selector.v0"
    assert "selected_total" in cs
    assert "dropped_total" in cs
    assert "selected_by_source_class" in cs
    assert "dropped_by_source_class" in cs
    assert "seed_slots" in cs
    assert "max_records" in cs
    # selected_total + dropped_total == total_event_count
    assert cs["selected_total"] + cs["dropped_total"] == 10, (
        f"selected({cs['selected_total']}) + dropped({cs['dropped_total']}) != 10"
    )


def test_continuity_selector_classifies_source_classes():
    """Events with distinct source_classes are bucketed correctly."""
    ts1 = "2026-07-01T00:00:00+00:00"
    ts2 = "2026-07-01T00:01:00+00:00"
    ts3 = "2026-07-01T00:02:00+00:00"
    events = [
        _make_event_dict_with_source_class("e1", ts1, kind="conversation_turn", safe_ref={"source_class": "foreground"}),
        _make_event_dict_with_source_class("e2", ts2, source="cron", kind="cron_job", safe_ref={"source_module": "cron_mirror"}),
        _make_event_dict_with_source_class("e3", ts3, source="mailbox", kind="mailbox_item", safe_ref={"platform": "mailbox"}),
    ]
    # sorted by ts (oldest first)
    stats = build_event_stats(events)

    cs = stats.continuity_selector
    assert cs["selected_total"] + cs["dropped_total"] == 3
    # All source classes should appear in at least one of the counters
    all_sc = set(cs["selected_by_source_class"]) | set(cs["dropped_by_source_class"])
    assert "foreground" in all_sc
    assert "cron" in all_sc
    assert "mailbox" in all_sc


def test_continuity_selector_empty_events():
    """Empty event list produces valid zeroed continuity_selector."""
    stats = build_event_stats([])

    cs = stats.continuity_selector
    assert cs["selected_total"] == 0
    assert cs["dropped_total"] == 0
    assert cs["selected_by_source_class"] == {}
    assert cs["dropped_by_source_class"] == {}


def test_continuity_selector_roundtrip(tmp_path):
    """continuity_selector survives write → read roundtrip."""
    roots = _make_roots(tmp_path)
    events = _make_event_dicts(8)
    stats = build_event_stats(events)
    stats.events_root = str(roots.events_root)
    write_event_stats(roots, stats)

    read_back, freshness = read_event_stats(roots)
    assert read_back is not None
    cs = read_back.continuity_selector
    assert isinstance(cs, dict)
    assert cs["schema_version"] == "memory-os.continuity_selector.v0"
    assert cs["selected_total"] + cs["dropped_total"] == 8


def test_legacy_event_stats_without_continuity_selector_returns_empty_dict(tmp_path):
    """Event stats written before continuity_selector was added default to {}."""
    roots = _make_roots(tmp_path)
    path = event_stats_path(roots)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema_version": "memory-os.event_stats.v0",
        "updated_at": "2026-07-01T00:00:00+00:00",
        "total_event_count": 42,
        "latest_event_id": "ev-old",
        "latest_event_ts": "2026-07-01T00:00:00+00:00",
        "by_source": {"test": 42},
        "by_kind": {"note": 42},
        "events_root": str(roots.events_root),
    }), encoding="utf-8")

    stats, freshness = read_event_stats(roots)
    assert stats is not None
    assert stats.continuity_selector == {}, (
        "Legacy stats without continuity_selector must default to empty dict"
    )


def test_continuity_selector_parity_with_live_selector(tmp_path):
    """Cached continuity_selector must match live continuity_selector_report output.

    Uses a real MemoryOSStore with events spanning different source classes
    and importance levels to verify the dict-based selection logic is an exact
    mirror of the EventEnvelope-based logic in prefetch.py.
    """
    from plugins.memory.memory_os.crystallized import append_candidate_queue
    from plugins.memory.memory_os.prefetch import continuity_selector_report
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.schema import EventEnvelope
    from plugins.memory.memory_os.store import MemoryOSStore

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="test")
    store = MemoryOSStore(roots)
    store.initialize()

    # Create events across different source classes with varying importance
    now = datetime.now(timezone.utc)
    events_data = [
        # (age_minutes, source_class, kind, tags, importance)
        (10, "foreground", "conversation_turn", [], 0.5),
        (9, "foreground", "conversation_turn", [], 0.8),
        (8, "cron", "cron_job", ["cron"], 0.0),
        (7, "cron", "cron_job", ["cron"], 0.3),
        (6, "mailbox", "mailbox_item", ["mailbox"], 0.0),
        (5, "mailbox", "mailbox_item", ["mailbox"], 0.9),
        (4, "governance", "proposal", [], 0.2),
        (3, "governance", "ops_gate", [], 0.7),
        (2, "state_source", "state_change", [], 0.0),
        (1, "foreground", "conversation_turn_mirrored", [], 0.6),
    ]

    for i, (age_min, sc, kind, tags, importance) in enumerate(events_data):
        ts = (now - timedelta(minutes=age_min)).isoformat()
        safe_ref = {
            "source_class": sc,
            "source_module": "cron_mirror" if sc == "cron" else "",
            "platform": "mailbox" if sc == "mailbox" else "",
            "importance": importance,
        }
        event = EventEnvelope(
            schema_version="memory-os.event.v0",
            id=f"evt-parity-{i:04d}",
            ts=ts,
            profile="test",
            source=sc,
            kind=kind,
            summary=f"summary-{i}",
            tags=tags,
            safe_ref=safe_ref,
        )
        store.append_event(event)

    # Live selector (EventEnvelope path)
    live = continuity_selector_report(store)

    # Cached selector (dict path — same data)
    sorted_events = sorted(store.read_events(), key=lambda e: e.ts)
    event_dicts = [e.to_dict() for e in sorted_events]
    cached = build_event_stats(event_dicts).continuity_selector

    # Compare counts
    assert cached["selected_total"] == live["selected_total"], (
        f"selected_total: cached={cached['selected_total']} live={live['selected_total']}"
    )
    assert cached["dropped_total"] == live["dropped_total"], (
        f"dropped_total: cached={cached['dropped_total']} live={live['dropped_total']}"
    )

    # Compare per-source-class breakdowns
    for field in ("selected_by_source_class", "dropped_by_source_class"):
        cached_val = cached[field]
        live_val = live[field]
        for sc in set(list(cached_val) + list(live_val)):
            c = cached_val.get(sc, 0)
            l = live_val.get(sc, 0)
            assert c == l, (
                f"{field}[{sc}]: cached={c} live={l}"
            )

    # Structural fields
    assert cached["seed_slots"] == live["seed_slots"]
    assert cached["max_records"] == live["max_records"]
    assert cached["schema_version"] == live["schema_version"]


def test_continuity_selector_parity_with_bookkeeping_burst_and_tied_ts(tmp_path):
    """Decisive parity test for the verified mirror-drift defect.

    Builds ONE synthetic event set containing:
      - one seed-eligible event per _CONTINUITY_SEED_SLOTS bucket (7 events,
        filling all 7 seed slots and leaving exactly 1 global-fill slot open
        under _MAX_CONTINUITY_RECORDS=8),
      - a bookkeeping burst of 5 governance_* events (high importance, recent
        ts, two of them sharing the exact same ts to exercise the (ts, id)
        sort tie-break) that must be excluded from the global recency FILL
        (but not from governance's own seed slot — that asymmetry is pinned),
      - one ordinary lower-importance foreground conversation_turn event that
        should win the single remaining fill slot once the burst is excluded.

    Feeds the SAME events through both real producers:
      - live: EventEnvelope objects via MemoryOSStore + continuity_selector_report
      - mirror: the same events' .to_dict() via build_event_stats

    Before the fix, the live selector excludes the governance_* burst from
    its fill (prefetch._select_continuity_events line 3074-3078) while the
    mirror's `remaining` had no such exclusion, so cached selected_by_source_class
    reported governance=2/foreground=2 while live reported governance=1/
    foreground=3 for this exact input — the disagreement this test pins.
    """
    from plugins.memory.memory_os.prefetch import continuity_selector_report
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.schema import EventEnvelope
    from plugins.memory.memory_os.store import MemoryOSStore

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="test")
    store = MemoryOSStore(roots)
    store.initialize()

    now = datetime.now(timezone.utc)

    def _ts(minutes_ago: float) -> str:
        return (now - timedelta(minutes=minutes_ago)).isoformat()

    events_data = [
        # -- 7 seed-eligible events, one per bucket (age_minutes chosen so
        #    each is the top-ranked candidate in its own source-class bucket) --
        # (id_suffix, age_minutes, source, kind, safe_ref, importance)
        ("seed-foreground-a", 1, "foreground", "conversation_turn", {}, 0.9),
        ("seed-foreground-b", 2, "foreground", "conversation_turn", {}, 0.8),
        ("seed-cron", 3, "cron_src", "cron_job",
         {"source_module": "cron_mirror"}, 0.5),
        ("seed-mailbox", 4, "mailbox_src", "mailbox_item",
         {"platform": "mailbox"}, 0.5),
        ("seed-room-family", 5, "family", "room_update", {}, 0.5),
        ("seed-state-source", 6, "state_src", "state_change",
         {"source_module": "state_source_mirror"}, 0.5),
        ("seed-governance", 0.2, "governance", "proposal_review", {}, 1.0),
        # -- bookkeeping burst: must be excluded from the global FILL only --
        # Two share the exact same ts to exercise the (ts, id) sort tie-break.
        ("burst-1", 0.5, "governance", "governance_resolver_approved", {}, 1.0),
        ("burst-2-tied", 0.6, "governance", "governance_resolver_invalidated", {}, 1.0),
        ("burst-3-tied", 0.6, "governance", "governance_resolver_approved", {}, 1.0),
        ("burst-4", 0.7, "governance", "governance_resolver_invalidated", {}, 1.0),
        ("burst-5", 0.8, "governance", "governance_resolver_approved", {}, 1.0),
        # -- ordinary event that should win the single remaining fill slot
        #    once the burst above is correctly excluded --
        ("extra-foreground", 9, "foreground", "conversation_turn", {}, 0.4),
    ]

    # burst-2-tied and burst-3-tied share an identical ts string.
    tied_ts = _ts(0.6)

    for id_suffix, age_min, source, kind, safe_ref_extra, importance in events_data:
        ts = tied_ts if id_suffix in ("burst-2-tied", "burst-3-tied") else _ts(age_min)
        safe_ref = {"importance": importance, **safe_ref_extra}
        event = EventEnvelope(
            schema_version="memory-os.event.v0",
            id=f"evt-{id_suffix}",
            ts=ts,
            profile="test",
            source=source,
            kind=kind,
            summary=f"summary-{id_suffix}",
            tags=[],
            safe_ref=safe_ref,
        )
        store.append_event(event)

    # Live selector (EventEnvelope path).
    live = continuity_selector_report(store)

    # Cached selector (dict path — same data, same real producer chain).
    sorted_events = sorted(store.read_events(), key=lambda e: e.ts)
    event_dicts = [e.to_dict() for e in sorted_events]
    cached = build_event_stats(event_dicts).continuity_selector

    assert cached["selected_total"] == live["selected_total"], (
        f"selected_total: cached={cached['selected_total']} live={live['selected_total']}"
    )
    assert cached["dropped_total"] == live["dropped_total"], (
        f"dropped_total: cached={cached['dropped_total']} live={live['dropped_total']}"
    )
    for field in ("selected_by_source_class", "dropped_by_source_class"):
        cached_val = cached[field]
        live_val = live[field]
        for sc in set(list(cached_val) + list(live_val)):
            c = cached_val.get(sc, 0)
            l = live_val.get(sc, 0)
            assert c == l, f"{field}[{sc}]: cached={c} live={l}"

    # Pin the actual live-correct values so a future change to either side
    # that breaks parity is caught even if both sides drift together.
    assert live["selected_by_source_class"] == {
        "foreground": 3, "cron": 1, "mailbox": 1,
        "room_family": 1, "state_source": 1, "governance": 1,
    }
    assert live["dropped_by_source_class"] == {"governance": 5}
    assert live["selected_total"] == 8
    assert live["dropped_total"] == 5
