from __future__ import annotations

import json
from datetime import datetime, timezone

from plugins.memory.memory_os.exposure_rollup import exposure_monitor_stats
from plugins.memory.memory_os.memory_sources import (
    ATTRIBUTION_SCHEMA_VERSION,
    append_memory_source_record,
)
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
    # Default to trigger_class="natural_cron" unless a row overrides it: these
    # fixtures model legitimate cron-driven rollup history for schema-era
    # health / natural-cycle-gating tests, distinct from the manual/legacy
    # rows exercised by the Fix 3 provenance tests below.
    rows = [{**row, "trigger_class": row.get("trigger_class", "natural_cron")} for row in rows]
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
        # Current-era, fully attributed: this is what makes schema_era_health
        # PASS rather than healthy_no_sample (item 16a).
        "attribution_schema": ATTRIBUTION_SCHEMA_VERSION,
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
        # Stands for a fully healthy current-era record. Unfreeze readiness now
        # also requires real attributed evidence rather than an empty gated set
        # (item 16a's era boundary).
        "attribution_schema": ATTRIBUTION_SCHEMA_VERSION,
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
        # Stands for a fully healthy current-era record. Unfreeze readiness now
        # also requires real attributed evidence rather than an empty gated set
        # (item 16a's era boundary).
        "attribution_schema": ATTRIBUTION_SCHEMA_VERSION,
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
    assert "candidate_cluster:cluster-1" in _closed_targets([active], now=now)

    expired = dict(active, deferred_until="2026-07-14T12:00:00Z")
    assert _defer_action_is_active(expired, now=now) is False


def test_exposure_stats_fail_current_window_on_schema_attribution_gap(tmp_path):
    store = _store(tmp_path)
    append_memory_source_record(store.roots, {
        "record_id": "natural-gap",
        "created_at": "2026-07-15T00:00:00Z",
        "natural_production": True,
        "traffic_class": "production",
        # Item 16a: the gate only holds records to the attribution contract when
        # they were written by the attribution-complete producer. This fixture
        # must therefore sit INSIDE that era -- its point is that a gapped
        # current-era record still FAILs, which is unchanged.
        "attribution_schema": ATTRIBUTION_SCHEMA_VERSION,
        "selected": [_section(source_ids=[])],
        "dropped": [],
    })

    stats = exposure_monitor_stats(store, now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc))

    assert stats["schema_era_attribution_gap_count"] == 1
    assert stats["schema_era_health"] == "FAIL"
    assert "schema_era_health_not_pass" in stats["freeze_reasons"]
    assert stats["attribution_era_record_count"] == 1
    assert stats["legacy_unattributed_record_count"] == 0


def test_pre_attribution_era_gaps_are_surfaced_as_debt_not_gated(tmp_path):
    """Records written before the attribution fix cannot be attributed
    retroactively -- the disclosure already happened without capturing IDs.

    Gating on them would keep the FAIL red forever no matter how correct the
    producer becomes: on production all 69 gapped rows are natural rows, so
    they sit inside the gated era permanently. They are surfaced as debt
    instead, exactly like legacy_unmarked_rollup_count does for rollup rows
    written before trigger_class existed.

    Counterfactual: without the era boundary this record is counted, health is
    FAIL, and no producer fix can ever clear it.
    """
    store = _store(tmp_path)
    append_memory_source_record(store.roots, {
        "record_id": "pre-attribution-natural-gap",
        "created_at": "2026-07-15T00:00:00Z",
        "natural_production": True,
        "traffic_class": "production",
        # No attribution_schema: this is a pre-fix row.
        "selected": [_section(source_ids=[])],
        "dropped": [],
    })

    stats = exposure_monitor_stats(store, now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc))

    assert stats["legacy_unattributed_record_count"] == 1, "the debt must be visible"
    assert stats["attribution_era_record_count"] == 0
    assert stats["schema_era_attribution_gap_count"] == 0, "pre-fix rows must not be gated"
    # NOT "PASS": with an empty gated set the attribution check has judged
    # nothing, and reporting PASS there would be green bought by narrowing the
    # measurement -- the exact trap item 16b warns about. Clearance also stays
    # frozen until real attributed traffic exists.
    assert stats["schema_era_health"] == "healthy_no_sample"
    assert "attribution_era_no_sample" in stats["freeze_reasons"]
    assert stats["v2c_unfreeze_ready"] is False
    # Still counted in the all-history debt view, so it is never simply erased.
    assert stats["all_history_attribution_gap_count"] == 1


def test_manual_trigger_rollups_do_not_count_toward_natural_cycle_gate(tmp_path):
    """Fix 3: manual runs must not pollute natural-cycle cadence telemetry."""
    store = _store(tmp_path)
    append_memory_source_record(store.roots, {
        "record_id": "natural-anchor-manual",
        "created_at": "2026-08-01T00:00:00Z",
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
            "trigger_class": "manual",
        }
        for day in range(8, 15)
    ])

    stats = exposure_monitor_stats(store, now=datetime(2026, 8, 15, 12, tzinfo=timezone.utc))

    # Same 7-consecutive-day shape as
    # test_budget_pressure_streak_accepts_seven_recent_completed_calendar_days,
    # but every row is a manual run — none of it may count as natural cadence.
    assert stats["initial_natural_cycle_count"] == 0
    assert stats["budget_pressure_streak_days"] == 0
    assert stats["v2c_unfreeze_ready"] is False
    assert "initial_natural_cycles:0/3" in stats["freeze_reasons"]
    assert stats["legacy_unmarked_rollup_count"] == 0


def test_legacy_unmarked_rollups_counted_separately_and_excluded_from_natural_gate(tmp_path):
    """Fix 3: rollup rows written before trigger_class existed are legacy —
    visible via legacy_unmarked_rollup_count, never silently folded into the
    natural-cycle gate."""
    store = _store(tmp_path)
    append_memory_source_record(store.roots, {
        "record_id": "natural-anchor-legacy",
        "created_at": "2026-08-01T00:00:00Z",
        "natural_production": True,
        "traffic_class": "production",
        "selected": [_section(source_ids=["crystallized:one"])],
        "dropped": [],
    })
    path = store.roots.memory_os_root / "system" / "exposure_rollup.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    legacy_rows = [
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
            # deliberately no "trigger_class" — pre-Fix-3 legacy shape
        }
        for day in range(8, 15)
    ]
    path.write_text("\n".join(json.dumps(row) for row in legacy_rows) + "\n", encoding="utf-8")
    (path.parent / "exposure_rollup_snapshot.json").write_text(
        json.dumps({
            "schema_version": "memory-os.exposure_rollup_snapshot.v0",
            "latest_window_start": legacy_rows[-1]["window_start"],
            "latest_window_end": legacy_rows[-1]["window_end"],
        }),
        encoding="utf-8",
    )

    stats = exposure_monitor_stats(store, now=datetime(2026, 8, 15, 12, tzinfo=timezone.utc))

    assert stats["legacy_unmarked_rollup_count"] == 7
    assert stats["initial_natural_cycle_count"] == 0
    assert stats["budget_pressure_streak_days"] == 0
    assert stats["v2c_unfreeze_ready"] is False
