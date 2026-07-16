from __future__ import annotations

import json
from datetime import datetime, timezone

from plugins.memory.memory_os.exposure_rollup import exposure_monitor_stats
from plugins.memory.memory_os.memory_sources import append_memory_source_record
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore


def _store(tmp_path) -> MemoryOSStore:
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path / ".hermes", profile="default"))
    store.initialize()
    return store


def _section(*, source_ids):
    return {
        "heading": "Crystallized Memory",
        "source_class": "crystallized",
        "source_ids": source_ids,
        "chars": 100,
        "reason_codes": [],
    }


def _write_rollups(store, rows):
    path = store.roots.memory_os_root / "system" / "exposure_rollup.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    snapshot = {
        "schema_version": "memory-os.exposure_rollup_snapshot.v0",
        "latest_window_start": rows[-1]["window_start"],
        "latest_window_end": rows[-1]["window_end"],
    }
    (path.parent / "exposure_rollup_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")


def test_recall_and_review_modes_are_explicit_and_invalid_values_fail_to_shadow(tmp_path):
    from plugins.memory.memory_os.config import load_config

    home = tmp_path / ".hermes"
    memory_root = home / "memory-os"
    memory_root.mkdir(parents=True)
    (memory_root / "config.json").write_text(
        json.dumps({
            "recall_arbitration": {
                "mode": "apply_canary",
                "freshness_guard_mode": "invalid",
                "conflict_resolution_mode": "invalid",
            },
            "owner_review": {"review_agenda_v2_mode": "invalid"},
        }),
        encoding="utf-8",
    )

    config = load_config(home)

    assert config["recall_arbitration"] == {
        "mode": "apply_canary",
        "budget_chars": 1800,
        "freshness_guard_mode": "shadow",
        "conflict_resolution_mode": "shadow",
    }
    assert config["owner_review"]["review_agenda_v2_mode"] == "shadow"


def test_exposure_stats_separate_legacy_debt_from_schema_era_health_and_freeze_gates(tmp_path):
    store = _store(tmp_path)
    append_memory_source_record(store.roots, {
        "record_id": "legacy-gap",
        "created_at": "2026-07-01T00:00:00Z",
        "selected": [_section(source_ids=[])],
        "dropped": [],
    })
    append_memory_source_record(store.roots, {
        "record_id": "natural-good",
        "created_at": "2026-07-14T00:00:00Z",
        "natural_production": True,
        "traffic_class": "production",
        "selected": [_section(source_ids=["crystallized:one"])],
        "dropped": [],
    })
    _write_rollups(store, [
        {
            "window_start": "2026-07-13T00:00:00Z", "window_end": "2026-07-14T01:00:00Z",
            "records_processed": 1, "records_classified": 1, "eligible": 1,
            "selected": 1, "dropped_by_budget": 0, "dropped_by_rank": 0,
            "conservation_passes": True,
        },
        {
            "window_start": "2026-07-14T01:00:00Z", "window_end": "2026-07-15T01:00:00Z",
            "records_processed": 1, "records_classified": 1, "eligible": 1,
            "selected": 1, "dropped_by_budget": 0, "dropped_by_rank": 0,
            "conservation_passes": True,
        },
    ])

    stats = exposure_monitor_stats(store, now=datetime(2026, 7, 15, 12, tzinfo=timezone.utc))

    assert stats["all_history_attribution_gap_count"] == 1
    assert stats["schema_era_attribution_gap_count"] == 0
    assert stats["schema_era_health"] == "PASS"
    assert stats["initial_natural_cycle_count"] == 2
    assert stats["budget_pressure_streak_days"] == 0
    assert stats["v2c_unfreeze_ready"] is False
    assert "initial_natural_cycles:2/3" in stats["freeze_reasons"]
    assert any(reason.startswith("production_observation_days:") for reason in stats["freeze_reasons"])
    assert "budget_pressure_streak:0/7" in stats["freeze_reasons"]
    assert stats["conservation_total_passes"] is True


def test_budget_pressure_streak_requires_consecutive_calendar_days(tmp_path):
    store = _store(tmp_path)
    append_memory_source_record(store.roots, {
        "record_id": "natural-anchor",
        "created_at": "2026-07-01T00:00:00Z",
        "natural_production": True,
        "traffic_class": "production",
        "selected": [_section(source_ids=["crystallized:one"])],
        "dropped": [],
    })
    _write_rollups(store, [
        {
            "window_start": f"2026-07-{day:02d}T00:00:00Z",
            "window_end": f"2026-07-{day:02d}T01:00:00Z",
            "records_processed": 1,
            "records_classified": 1,
            "eligible": 1,
            "selected": 0,
            "dropped_by_budget": 1,
            "dropped_by_rank": 0,
            "conservation_passes": True,
        }
        for day in (1, 3, 5, 7, 9, 11, 13)
    ])

    stats = exposure_monitor_stats(store, now=datetime(2026, 8, 15, tzinfo=timezone.utc))

    assert stats["initial_natural_cycle_count"] == 7
    assert stats["budget_pressure_streak_days"] == 0
    assert stats["v2c_unfreeze_ready"] is False
    assert "budget_pressure_streak:0/7" in stats["freeze_reasons"]


def test_budget_pressure_streak_accepts_seven_recent_completed_calendar_days(tmp_path):
    store = _store(tmp_path)
    append_memory_source_record(store.roots, {
        "record_id": "natural-anchor",
        "created_at": "2026-07-01T00:00:00Z",
        "natural_production": True,
        "traffic_class": "production",
        "selected": [_section(source_ids=["crystallized:one"])],
        "dropped": [],
    })
    _write_rollups(store, [
        {
            "window_start": f"2026-08-{day:02d}T00:00:00Z",
            "window_end": f"2026-08-{day:02d}T23:00:00Z",
            "records_processed": 1,
            "records_classified": 1,
            "eligible": 1,
            "selected": 0,
            "dropped_by_budget": 1,
            "dropped_by_rank": 0,
            "conservation_passes": True,
        }
        for day in range(8, 15)
    ])

    stats = exposure_monitor_stats(store, now=datetime(2026, 8, 15, 12, tzinfo=timezone.utc))

    assert stats["budget_pressure_streak_days"] == 7
    assert stats["v2c_unfreeze_ready"] is True
    assert stats["freeze_reasons"] == []


def test_candidate_cluster_defer_is_a_cooldown_not_permanent_closure():
    from plugins.memory.memory_os.owner_actions import (
        _closed_targets,
        _defer_action_is_active,
        _normalized_defer_until,
    )

    now = datetime(2026, 7, 15, 12, tzinfo=timezone.utc)
    until = _normalized_defer_until("", now=now)
    assert until == "2026-07-22T12:00:00+00:00"
    active = {
        "result": "applied",
        "target_type": "candidate_cluster",
        "target_id": "cluster-1",
        "action_type": "defer_candidate_cluster",
        "created_at": "2026-07-15T12:00:00Z",
        "deferred_until": until,
    }
    assert _defer_action_is_active(active, now=now) is True
    assert "candidate_cluster:cluster-1" in _closed_targets([active])

    expired = dict(active, deferred_until="2026-07-14T12:00:00Z")
    assert _defer_action_is_active(expired, now=now) is False


def test_exposure_stats_fail_current_window_on_schema_attribution_gap(tmp_path):
    store = _store(tmp_path)
    append_memory_source_record(store.roots, {
        "record_id": "natural-gap",
        "created_at": "2026-07-15T00:00:00Z",
        "natural_production": True,
        "traffic_class": "production",
        "selected": [_section(source_ids=[])],
        "dropped": [],
    })

    stats = exposure_monitor_stats(store, now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc))

    assert stats["schema_era_attribution_gap_count"] == 1
    assert stats["schema_era_health"] == "FAIL"
    assert "schema_era_health_not_pass" in stats["freeze_reasons"]
