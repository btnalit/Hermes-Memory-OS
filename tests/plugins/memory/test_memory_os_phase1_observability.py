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


def test_v1_era_gapped_rows_are_debt_not_permanent_gate_fail(tmp_path):
    """纪元 v1→v2 反事实(2026-08-07):v1 曾宣称归属完备,生产证伪 —
    E8c 时代 graph 路径留下一条已展示但 source_ids 为空的 v1 纪元内自然行,
    纪元门按全纪元计 gap → 永久 FAIL 且无法追溯补齐。版本升级后该行必须
    降为已分类债务:不进 schema_era gap 门(修复缺席=常量仍为 v1 时本测试
    必红),但 all_history 与 legacy 债务计数保留(分类而非抹除)。"""
    store = _store(tmp_path)
    append_memory_source_record(store.roots, {
        "record_id": "v1-era-graph-gap",
        "created_at": "2026-08-07T09:51:49Z",
        "natural_production": True,
        "traffic_class": "production",
        # 字面 v1(不是常量):钉住的就是「旧纪元行不再受门约束」这件事
        "attribution_schema": "memory-os.memory_sources_attribution.v1",
        "selected": [_section(source_ids=[])],
        "dropped": [],
    })

    stats = exposure_monitor_stats(store, now=datetime(2026, 8, 8, 0, tzinfo=timezone.utc))

    assert stats["schema_era_attribution_gap_count"] == 0, (
        "v1 rows must leave the gated set after the era bump"
    )
    assert stats["all_history_attribution_gap_count"] == 1, (
        "debt is classified, never erased"
    )
    assert stats["legacy_unattributed_record_count"] == 1
    # 零 v2 样本:诚实护栏 — no-sample + 冻结,不买绿
    assert stats["schema_era_health"] == "healthy_no_sample"
    assert "attribution_era_no_sample" in stats["freeze_reasons"]


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
def test_rolling_attribution_window_is_era_scoped_and_has_a_reader(tmp_path):
    """Item 17: rolling_7d_attribution_gap_count was computed and read by nothing.

    Two properties are asserted together because either alone is insufficient:
      - era-scoped: a recent PRE-marker row must not count, or the window would
        report gaps for 7 days after the producer fix while the producer is
        correct;
      - denominated: the era record count travels with it, so 0 gaps over 0
        records cannot be misread as "recent traffic was clean".

    Counterfactual: computing rolling_gap over rolling_records instead of
    rolling_era_records makes the first assertion fail (1 != 0).
    """
    store = _store(tmp_path)
    now = datetime(2026, 8, 4, 12, tzinfo=timezone.utc)

    # Recent, natural, gapped -- but PRE-marker, so unattributable retroactively.
    append_memory_source_record(store.roots, {
        "record_id": "recent-pre-marker-gap",
        "created_at": "2026-08-03T00:00:00Z",
        "natural_production": True,
        "traffic_class": "production",
        "selected": [_section(source_ids=[])],
        "dropped": [],
    })

    stats = exposure_monitor_stats(store, now=now)
    assert stats["rolling_7d_attribution_gap_count"] == 0, (
        "a pre-marker row must not be counted as a recent attribution gap"
    )
    assert stats["rolling_7d_attribution_era_record_count"] == 0, (
        "no attributed traffic in the window, so the denominator must say so"
    )

    # Now a recent MARKED row with a real gap: that is an active regression.
    append_memory_source_record(store.roots, {
        "record_id": "recent-marked-gap",
        "created_at": "2026-08-03T12:00:00Z",
        "natural_production": True,
        "traffic_class": "production",
        "attribution_schema": ATTRIBUTION_SCHEMA_VERSION,
        "selected": [_section(source_ids=[])],
        "dropped": [],
    })

    stats = exposure_monitor_stats(store, now=now)
    assert stats["rolling_7d_attribution_gap_count"] == 1
    assert stats["rolling_7d_attribution_era_record_count"] == 1
    # And it still drives the real gate, so the rolling number stays diagnostic.
    assert stats["schema_era_attribution_gap_count"] == 1
    assert stats["schema_era_health"] == "FAIL"


def test_exposure_monitor_stats_key_census_every_key_has_a_disposition(tmp_path):
    """Backlog 18: every key exposure_monitor_stats returns must have a
    conscious disposition. A key that is merely computed and returned alerts
    nobody (the schema_era_classified_ratio lesson: a number can be cited as
    evidence for months while feeding no decision). Pinning the exact key set
    forces the next added key to be triaged at birth instead of joining the
    orphan list this backlog item drained.

    Dispositions:
      graded    -- feeds a PASS/WARN/FAIL decision in the monitor
      info      -- surfaced by a monitor INFO entry (visible, never alerting)
      internal  -- consumed inside the producer (freeze_reasons/schema_health)
      component -- published inside another entry's diagnostic breakdown
      identity  -- schema/version bookkeeping

    Counterfactual: before this census, attribution_gap_count (an unread
    duplicate alias) and schema_era_natural_record_count (misnamed, and exactly
    attribution_era_record_count + legacy_unattributed_record_count) sat in the
    dict for no reader; both are asserted absent below.
    """
    store = _store(tmp_path)
    stats = exposure_monitor_stats(store)

    dispositions = {
        "schema_version": "identity",
        "exposure_rollup_lag_hours": "info",       # v2_exposure_rollup_ledger_state
        "exposure_rollup_records_total": "info",   # v2_exposure_rollup_ledger_state
        "legacy_unmarked_rollup_count": "info",    # migration-debt entry
        "cumulative_eligible": "component",        # conservation_total_passes
        "cumulative_selected": "component",
        "cumulative_dropped_by_budget": "component",
        "cumulative_dropped_by_rank": "component",
        "conservation_total_passes": "graded",     # migration-debt conservation issue
        "all_history_attribution_gap_count": "graded",
        "schema_era_attribution_gap_count": "graded",
        "legacy_unattributed_record_count": "info",
        "attribution_era_record_count": "info",
        "rolling_7d_attribution_gap_count": "info",
        "rolling_7d_attribution_era_record_count": "info",
        "schema_era_conservation_failure_count": "graded",
        "rolling_7d_natural_record_count": "info", # recent-window entry
        "schema_era_classified_ratio": "info",     # v2_exposure_classification_coverage
        "schema_era_health": "graded",
        "telemetry_degraded_count": "internal",
        "initial_natural_cycle_count": "internal",
        "production_observation_days": "internal",
        "budget_pressure_streak_days": "internal",
        "v2c_unfreeze_ready": "graded",
        "downstream_clearance_closure_frozen": "graded",
        "freeze_reasons": "graded",
        "latest_window_start": "info",             # v2_exposure_rollup_ledger_state
        "latest_window_end": "info",               # v2_exposure_rollup_ledger_state
        "snapshot_status": "info",                 # v2_exposure_rollup_ledger_state
        # Backlog 14: run-outcome contract (completion is not output).
        "last_run_outcome": "info",                # v2_exposure_rollup_ledger_state
        "last_run_at": "info",                     # v2_exposure_rollup_ledger_state
        "last_run_new_records": "info",            # v2_exposure_rollup_ledger_state
    }

    assert set(stats.keys()) == set(dispositions), (
        "exposure_monitor_stats key set changed; give the new/removed key a "
        "conscious disposition here (graded / info / internal / component) "
        "and, for graded/info, a real monitor reader -- see backlog 18"
    )
    assert "attribution_gap_count" not in stats
    assert "schema_era_natural_record_count" not in stats
