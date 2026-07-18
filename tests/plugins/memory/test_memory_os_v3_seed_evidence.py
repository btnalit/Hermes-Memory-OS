from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone

from plugins.memory.memory_os.memory_sources import append_memory_source_record
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore


def _store(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="default")
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def _record(record_id, created_at, *source_ids, traffic_class="production", natural=True):
    return {
        "schema_version": "memory-os.memory_sources.v0",
        "record_id": record_id,
        "created_at": created_at,
        "traffic_class": traffic_class,
        "natural_production": natural,
        "selected": [
            {
                "source_class": "crystallized",
                "source_ids": list(source_ids),
            }
        ],
        "dropped": [],
    }


def test_daily_product_keeps_exact_edges_and_shared_entity_edges(tmp_path, monkeypatch):
    from plugins.memory.memory_os import v3_seed_evidence
    from plugins.memory.memory_os.v3_seed_evidence import run_v3_seed_evidence_cycle

    store = _store(tmp_path)
    append_memory_source_record(
        store.roots,
        _record("msrc_1", "2026-07-12T01:00:00Z", "crystallized:cry_a", "crystallized:cry_b"),
    )
    append_memory_source_record(
        store.roots,
        _record("msrc_2", "2026-07-12T02:00:00Z", "crystallized:cry_a", "crystallized:cry_c"),
    )
    monkeypatch.setattr(v3_seed_evidence, "_entity_index_is_enabled", lambda _store: True)
    with sqlite3.connect(store.roots.index_path) as conn:
        conn.execute(
            "create table entity_index (entity_id text, entity_text text, record_id text, role text, proposed_by text, created_at text)"
        )
        conn.executemany(
            "insert into entity_index (entity_id, entity_text, record_id, role, proposed_by, created_at) values (?, ?, ?, ?, ?, ?)",
            [
                ("ent_shared", "Shared", "cry_a", "mention", "test", "2026-07-12T00:00:00Z"),
                ("ent_shared", "Shared", "cry_b", "mention", "test", "2026-07-12T00:00:00Z"),
            ],
        )

    report = run_v3_seed_evidence_cycle(
        store,
        target_date=date(2026, 7, 12),
        now=datetime(2026, 7, 13, 1, tzinfo=timezone.utc),
        max_edges=100,
    )

    assert report["status"] == "ok"
    assert report["valid"] is True
    daily = report["daily_record"]
    assert daily["natural_date"] == "2026-07-12"
    assert daily["source_offset_start"] == 0
    assert daily["source_offset_end"] == 2
    assert daily["natural_production_record_count"] == 2
    assert daily["exact_edge_count"] == 3
    assert daily["stored_edge_count"] == 3
    assert daily["coverage_ratio"] == 1.0
    assert daily["shared_entity_status"] == "available"
    assert {(edge["from"], edge["to"], edge["kind"], edge["count"]) for edge in daily["edges"]} == {
        ("crystallized:cry_a", "crystallized:cry_b", "co_selected", 1),
        ("crystallized:cry_a", "crystallized:cry_c", "co_selected", 1),
        ("crystallized:cry_a", "crystallized:cry_b", "shared_entity", 1),
    }
    persisted = [json.loads(line) for line in (store.roots.memory_os_root / "system" / "v3_seed_edges_daily.jsonl").read_text().splitlines()]
    assert persisted == [daily]


def test_storage_cap_marks_day_partial_and_invalid_without_calling_it_exact(tmp_path):
    from plugins.memory.memory_os.v3_seed_evidence import run_v3_seed_evidence_cycle

    store = _store(tmp_path)
    append_memory_source_record(
        store.roots,
        _record(
            "msrc_cap",
            "2026-07-12T01:00:00Z",
            "crystallized:a",
            "crystallized:b",
            "crystallized:c",
        ),
    )

    report = run_v3_seed_evidence_cycle(
        store,
        target_date="2026-07-12",
        now=datetime(2026, 7, 13, 1, tzinfo=timezone.utc),
        max_edges=2,
        require_shared_entity=False,
    )

    daily = report["daily_record"]
    assert daily["exact_edge_count"] == 3
    assert daily["stored_edge_count"] == 2
    assert daily["truncation_count"] == 1
    assert daily["coverage_ratio"] == 2 / 3
    assert daily["valid"] is False
    assert "edge_storage_cap_exceeded" in daily["invalid_reasons"]


def test_nonproduction_and_legacy_unclassified_records_cannot_create_valid_day(tmp_path):
    from plugins.memory.memory_os.v3_seed_evidence import run_v3_seed_evidence_cycle

    store = _store(tmp_path)
    append_memory_source_record(
        store.roots,
        _record("msrc_shadow", "2026-07-12T01:00:00Z", "crystallized:a", traffic_class="shadow", natural=False),
    )
    append_memory_source_record(
        store.roots,
        {
            "record_id": "msrc_legacy",
            "created_at": "2026-07-12T02:00:00Z",
            "selected": [{"source_ids": ["crystallized:b"]}],
            "dropped": [],
        },
    )

    report = run_v3_seed_evidence_cycle(
        store,
        target_date="2026-07-12",
        now=datetime(2026, 7, 13, 1, tzinfo=timezone.utc),
        require_shared_entity=False,
    )

    daily = report["daily_record"]
    assert daily["input_record_count"] == 2
    assert daily["natural_production_record_count"] == 0
    assert daily["excluded_traffic_count"] == 2
    assert daily["valid"] is False
    assert "no_natural_production_input" in daily["invalid_reasons"]
    assert "unclassified_traffic_present" in daily["invalid_reasons"]


def test_unsafe_source_id_invalidates_whole_day(tmp_path):
    from plugins.memory.memory_os.v3_seed_evidence import run_v3_seed_evidence_cycle

    store = _store(tmp_path)
    append_memory_source_record(
        store.roots,
        _record("msrc_unsafe", "2026-07-12T01:00:00Z", "crystallized:safe", "file:///private/raw"),
    )

    report = run_v3_seed_evidence_cycle(
        store,
        target_date="2026-07-12",
        now=datetime(2026, 7, 13, 1, tzinfo=timezone.utc),
        require_shared_entity=False,
    )

    daily = report["daily_record"]
    assert daily["privacy_source_violation_count"] == 1
    assert daily["valid"] is False
    assert "privacy_or_source_id_violation" in daily["invalid_reasons"]
    assert all("file:///" not in json.dumps(edge) for edge in daily["edges"])


def test_repeated_identical_cycle_is_idempotent(tmp_path):
    from plugins.memory.memory_os.v3_seed_evidence import run_v3_seed_evidence_cycle

    store = _store(tmp_path)
    append_memory_source_record(
        store.roots,
        _record("msrc_once", "2026-07-12T01:00:00Z", "crystallized:a", "crystallized:b"),
    )
    kwargs = {
        "target_date": "2026-07-12",
        "now": datetime(2026, 7, 13, 1, tzinfo=timezone.utc),
        "require_shared_entity": False,
    }

    first = run_v3_seed_evidence_cycle(store, **kwargs)
    second = run_v3_seed_evidence_cycle(store, **kwargs)

    assert first["skipped"] is False
    assert second["skipped"] is True
    assert len((store.roots.memory_os_root / "system" / "v3_seed_edges_daily.jsonl").read_text().splitlines()) == 1


def test_snapshot_counts_only_latest_revision_of_30_consecutive_valid_days(tmp_path):
    from plugins.memory.memory_os.v3_seed_evidence import build_v3_seed_evidence_snapshot

    store = _store(tmp_path)
    rows = []
    for day in range(1, 31):
        rows.append(
            {
                "schema_version": "memory-os.v3_seed_edges_daily.v0",
                "natural_date": f"2026-06-{day:02d}",
                "created_at": f"2026-07-01T00:00:{day:02d}Z",
                "valid": True,
                "coverage_ratio": 1.0,
                "source_cursor_contiguous": True,
                "rebuild_digest": f"sha256:{day}",
                # These fixtures model 30 days of legitimate cron history —
                # the natural-cycle gate (BB.6-2) only counts trigger_class
                # "natural_cron" rows, so the fixture must be tagged as such
                # to keep testing the latest-revision/consecutive-day logic
                # this test is actually about.
                "trigger_class": "natural_cron",
            }
        )
    snapshot = build_v3_seed_evidence_snapshot(store, daily_records=rows)

    assert snapshot["valid_day_count"] == 30
    assert snapshot["consecutive_valid_day_count"] == 30
    assert snapshot["activation_evidence_ready"] is True
    assert snapshot["first_valid_date"] == "2026-06-01"
    assert snapshot["last_valid_date"] == "2026-06-30"
    assert snapshot["legacy_unmarked_day_count"] == 0


def test_manual_trigger_days_do_not_count_toward_natural_activation_gate(tmp_path):
    """BB.6-2: a manually-triggered (no MEMORY_OS_EXECUTION_GATE_ENVELOPE_ID
    env var) run must not be able to inflate consecutive_valid_day_count or
    mark activation_evidence_ready — only trigger_class=natural_cron rows
    count toward the 30-day readiness gate."""
    from plugins.memory.memory_os.v3_seed_evidence import build_v3_seed_evidence_snapshot

    store = _store(tmp_path)
    rows = [
        {
            "schema_version": "memory-os.v3_seed_edges_daily.v0",
            "natural_date": f"2026-06-{day:02d}",
            "created_at": f"2026-07-01T00:00:{day:02d}Z",
            "valid": True,
            "coverage_ratio": 1.0,
            "source_cursor_contiguous": True,
            "rebuild_digest": f"sha256:{day}",
            "trigger_class": "manual",
        }
        for day in range(1, 31)
    ]
    snapshot = build_v3_seed_evidence_snapshot(store, daily_records=rows)

    assert snapshot["valid_day_count"] == 0
    assert snapshot["consecutive_valid_day_count"] == 0
    assert snapshot["activation_evidence_ready"] is False
    assert snapshot["legacy_unmarked_day_count"] == 0


def test_legacy_unmarked_days_counted_separately_and_excluded_from_natural_gate(tmp_path):
    """BB.6-2: rows written before trigger_class existed are visible via
    legacy_unmarked_day_count but never counted as natural (same treatment
    as manual runs — pre-fix history cannot silently satisfy the gate)."""
    from plugins.memory.memory_os.v3_seed_evidence import build_v3_seed_evidence_snapshot

    store = _store(tmp_path)
    rows = [
        {
            "schema_version": "memory-os.v3_seed_edges_daily.v0",
            "natural_date": f"2026-06-{day:02d}",
            "created_at": f"2026-07-01T00:00:{day:02d}Z",
            "valid": True,
            "coverage_ratio": 1.0,
            "source_cursor_contiguous": True,
            "rebuild_digest": f"sha256:{day}",
        }
        for day in range(1, 31)
    ]
    snapshot = build_v3_seed_evidence_snapshot(store, daily_records=rows)

    assert snapshot["valid_day_count"] == 0
    assert snapshot["consecutive_valid_day_count"] == 0
    assert snapshot["activation_evidence_ready"] is False
    assert snapshot["legacy_unmarked_day_count"] == 30


def test_daily_record_stamps_trigger_class_from_execution_gate_envelope_env_var(tmp_path, monkeypatch):
    """BB.6-2: run_v3_seed_evidence_cycle stamps trigger_class on the daily
    record from MEMORY_OS_EXECUTION_GATE_ENVELOPE_ID — only a process
    launched under the cron ExecutionGate wrapper has this env var set."""
    from plugins.memory.memory_os.v3_seed_evidence import run_v3_seed_evidence_cycle

    store = _store(tmp_path)
    append_memory_source_record(
        store.roots,
        _record("msrc_manual", "2026-07-12T01:00:00Z", "crystallized:a", "crystallized:b"),
    )
    monkeypatch.delenv("MEMORY_OS_EXECUTION_GATE_ENVELOPE_ID", raising=False)

    manual_report = run_v3_seed_evidence_cycle(
        store,
        target_date="2026-07-12",
        now=datetime(2026, 7, 13, 1, tzinfo=timezone.utc),
        require_shared_entity=False,
    )
    assert manual_report["daily_record"]["trigger_class"] == "manual"

    monkeypatch.setenv("MEMORY_OS_EXECUTION_GATE_ENVELOPE_ID", "real-cron-envelope")
    append_memory_source_record(
        store.roots,
        _record("msrc_natural", "2026-07-13T01:00:00Z", "crystallized:c", "crystallized:d"),
    )
    natural_report = run_v3_seed_evidence_cycle(
        store,
        target_date="2026-07-13",
        now=datetime(2026, 7, 14, 1, tzinfo=timezone.utc),
        require_shared_entity=False,
    )
    assert natural_report["daily_record"]["trigger_class"] == "natural_cron"


def test_manual_then_natural_cron_same_day_upgrades_provenance_instead_of_skipping(tmp_path, monkeypatch):
    """BB.6-2 provenance upgrade counterfactual: a manual run that writes day D
    first must not permanently block that day's natural_cron credit.  When the
    cron run arrives with an identical rebuild_digest, the digest-match skip
    must be bypassed and a natural_cron row written (normal write path)."""
    from plugins.memory.memory_os.v3_seed_evidence import run_v3_seed_evidence_cycle

    store = _store(tmp_path)
    append_memory_source_record(
        store.roots,
        _record("msrc_up", "2026-07-12T01:00:00Z", "crystallized:a", "crystallized:b"),
    )

    monkeypatch.delenv("MEMORY_OS_EXECUTION_GATE_ENVELOPE_ID", raising=False)
    manual_report = run_v3_seed_evidence_cycle(
        store,
        target_date="2026-07-12",
        now=datetime(2026, 7, 13, 1, tzinfo=timezone.utc),
        require_shared_entity=False,
    )
    assert manual_report["skipped"] is False
    assert manual_report["daily_record"]["trigger_class"] == "manual"

    monkeypatch.setenv("MEMORY_OS_EXECUTION_GATE_ENVELOPE_ID", "real-cron-envelope")
    natural_report = run_v3_seed_evidence_cycle(
        store,
        target_date="2026-07-12",
        now=datetime(2026, 7, 13, 2, tzinfo=timezone.utc),
        require_shared_entity=False,
    )

    assert natural_report["skipped"] is False
    assert natural_report["daily_record"]["trigger_class"] == "natural_cron"
    assert natural_report["daily_record"]["rebuild_digest"] == manual_report["daily_record"]["rebuild_digest"]
    persisted = [
        json.loads(line)
        for line in (store.roots.memory_os_root / "system" / "v3_seed_edges_daily.jsonl").read_text().splitlines()
    ]
    assert len(persisted) == 2
    assert persisted[-1]["trigger_class"] == "natural_cron"
    assert natural_report["snapshot"]["valid_day_count"] == 1
    assert natural_report["snapshot"]["consecutive_valid_day_count"] == 1


def test_natural_cron_then_manual_same_day_still_skips(tmp_path, monkeypatch):
    """BB.6-2: the reverse order must keep skipping — a manual rerun after the
    cron row exists must never overwrite/downgrade natural provenance."""
    from plugins.memory.memory_os.v3_seed_evidence import run_v3_seed_evidence_cycle

    store = _store(tmp_path)
    append_memory_source_record(
        store.roots,
        _record("msrc_rev", "2026-07-12T01:00:00Z", "crystallized:a", "crystallized:b"),
    )

    monkeypatch.setenv("MEMORY_OS_EXECUTION_GATE_ENVELOPE_ID", "real-cron-envelope")
    natural_report = run_v3_seed_evidence_cycle(
        store,
        target_date="2026-07-12",
        now=datetime(2026, 7, 13, 1, tzinfo=timezone.utc),
        require_shared_entity=False,
    )
    assert natural_report["skipped"] is False
    assert natural_report["daily_record"]["trigger_class"] == "natural_cron"

    monkeypatch.delenv("MEMORY_OS_EXECUTION_GATE_ENVELOPE_ID", raising=False)
    manual_report = run_v3_seed_evidence_cycle(
        store,
        target_date="2026-07-12",
        now=datetime(2026, 7, 13, 2, tzinfo=timezone.utc),
        require_shared_entity=False,
    )

    assert manual_report["skipped"] is True
    assert manual_report["reason"] == "daily_product_unchanged"
    persisted = [
        json.loads(line)
        for line in (store.roots.memory_os_root / "system" / "v3_seed_edges_daily.jsonl").read_text().splitlines()
    ]
    assert len(persisted) == 1
    assert persisted[0]["trigger_class"] == "natural_cron"


def test_snapshot_later_manual_row_cannot_evict_natural_day(tmp_path):
    """BB.6-2 eviction counterfactual: natural_by_date must be an independent
    last-writer-wins pass over ONLY natural_cron rows.  If the mixed
    latest_by_date is filtered instead (the pre-fix shape), a LATER manual row
    for the same date wins the merge, gets filtered out, and the already-earned
    natural day silently vanishes from the activation gate."""
    from plugins.memory.memory_os.v3_seed_evidence import build_v3_seed_evidence_snapshot

    store = _store(tmp_path)
    natural_row = {
        "schema_version": "memory-os.v3_seed_edges_daily.v0",
        "natural_date": "2026-06-01",
        "created_at": "2026-06-02T00:00:01Z",
        "valid": True,
        "coverage_ratio": 1.0,
        "source_cursor_contiguous": True,
        "rebuild_digest": "sha256:natural",
        "trigger_class": "natural_cron",
    }
    later_manual_row = {
        "schema_version": "memory-os.v3_seed_edges_daily.v0",
        "natural_date": "2026-06-01",
        "created_at": "2026-06-03T00:00:00Z",
        "valid": False,
        "coverage_ratio": 0.0,
        "source_cursor_contiguous": True,
        "rebuild_digest": "sha256:manual",
        "trigger_class": "manual",
    }

    snapshot = build_v3_seed_evidence_snapshot(store, daily_records=[natural_row, later_manual_row])

    assert snapshot["valid_day_count"] == 1
    assert snapshot["consecutive_valid_day_count"] == 1
    assert snapshot["first_valid_date"] == "2026-06-01"
    assert snapshot["last_valid_date"] == "2026-06-01"
    # latest_by_date fields intentionally still reflect ALL rows: the latest
    # (manual, invalid) revision drives invalid_day_count and
    # latest_recorded_date even though the natural gate keeps the day.
    # latest_natural_date is cron-true freshness (P2 #8): here the day has a
    # natural row, so both views agree.
    assert snapshot["invalid_day_count"] == 1
    assert snapshot["latest_natural_date"] == "2026-06-01"
    assert snapshot["latest_recorded_date"] == "2026-06-01"
    # The date HAS natural coverage, so it never lands in manual_day_count.
    assert snapshot["manual_day_count"] == 0
    assert snapshot["legacy_unmarked_day_count"] == 0


def test_snapshot_30_day_natural_streak_survives_interleaved_manual_rows(tmp_path):
    """BB.6-2: an achieved 30-day natural streak (activation_evidence_ready)
    must not regress when later manual/backfill rows are appended for the same
    dates."""
    from plugins.memory.memory_os.v3_seed_evidence import build_v3_seed_evidence_snapshot

    store = _store(tmp_path)
    rows = []
    for day in range(1, 31):
        rows.append(
            {
                "schema_version": "memory-os.v3_seed_edges_daily.v0",
                "natural_date": f"2026-06-{day:02d}",
                "created_at": f"2026-07-01T00:00:{day:02d}Z",
                "valid": True,
                "coverage_ratio": 1.0,
                "source_cursor_contiguous": True,
                "rebuild_digest": f"sha256:{day}",
                "trigger_class": "natural_cron",
            }
        )
    # Later manual reruns for every other day — all newer than the natural rows.
    for day in range(1, 31, 2):
        rows.append(
            {
                "schema_version": "memory-os.v3_seed_edges_daily.v0",
                "natural_date": f"2026-06-{day:02d}",
                "created_at": f"2026-07-02T00:00:{day:02d}Z",
                "valid": True,
                "coverage_ratio": 1.0,
                "rebuild_digest": f"sha256:manual-{day}",
                "trigger_class": "manual",
            }
        )

    snapshot = build_v3_seed_evidence_snapshot(store, daily_records=rows)

    assert snapshot["valid_day_count"] == 30
    assert snapshot["consecutive_valid_day_count"] == 30
    assert snapshot["activation_evidence_ready"] is True
    assert snapshot["first_valid_date"] == "2026-06-01"
    assert snapshot["last_valid_date"] == "2026-06-30"
    assert snapshot["legacy_unmarked_day_count"] == 0


def test_valid_manual_only_day_is_counted_in_manual_day_count(tmp_path):
    """P2 #8 counterfactual (a): a date whose rows are all manual and valid
    previously appeared in NO snapshot bucket — not natural (correct), not
    invalid (it is valid), not legacy (it has trigger_class).  It must land in
    manual_day_count, and ONLY there."""
    from plugins.memory.memory_os.v3_seed_evidence import build_v3_seed_evidence_snapshot

    store = _store(tmp_path)
    manual_valid_row = {
        "schema_version": "memory-os.v3_seed_edges_daily.v0",
        "natural_date": "2026-06-01",
        "created_at": "2026-06-02T00:00:01Z",
        "valid": True,
        "coverage_ratio": 1.0,
        "source_cursor_contiguous": True,
        "rebuild_digest": "sha256:manual-valid",
        "trigger_class": "manual",
    }

    snapshot = build_v3_seed_evidence_snapshot(store, daily_records=[manual_valid_row])

    assert snapshot["manual_day_count"] == 1
    # ... and nowhere else: the day is not natural, not invalid, not legacy.
    assert snapshot["valid_day_count"] == 0
    assert snapshot["consecutive_valid_day_count"] == 0
    assert snapshot["invalid_day_count"] == 0
    assert snapshot["legacy_unmarked_day_count"] == 0


def test_manual_and_legacy_days_partition_without_fallthrough(tmp_path):
    """P2 #8: dates lacking natural_cron coverage split cleanly between
    manual_day_count (latest row has trigger_class) and
    legacy_unmarked_day_count (latest row missing trigger_class) — no date can
    fall through both buckets."""
    from plugins.memory.memory_os.v3_seed_evidence import build_v3_seed_evidence_snapshot

    store = _store(tmp_path)
    rows = [
        {
            "schema_version": "memory-os.v3_seed_edges_daily.v0",
            "natural_date": "2026-06-01",
            "created_at": "2026-06-02T00:00:01Z",
            "valid": True,
            "coverage_ratio": 1.0,
            "rebuild_digest": "sha256:manual",
            "trigger_class": "manual",
        },
        {
            "schema_version": "memory-os.v3_seed_edges_daily.v0",
            "natural_date": "2026-06-02",
            "created_at": "2026-06-03T00:00:01Z",
            "valid": True,
            "coverage_ratio": 1.0,
            "rebuild_digest": "sha256:legacy",
        },
        {
            "schema_version": "memory-os.v3_seed_edges_daily.v0",
            "natural_date": "2026-06-03",
            "created_at": "2026-06-04T00:00:01Z",
            "valid": True,
            "coverage_ratio": 1.0,
            "rebuild_digest": "sha256:natural",
            "trigger_class": "natural_cron",
        },
    ]

    snapshot = build_v3_seed_evidence_snapshot(store, daily_records=rows)

    assert snapshot["manual_day_count"] == 1
    assert snapshot["legacy_unmarked_day_count"] == 1
    assert snapshot["valid_day_count"] == 1


def test_manual_run_today_does_not_advance_latest_natural_date(tmp_path):
    """P2 #8 counterfactual (b): latest_natural_date is cron-true freshness —
    a manual run covering today must NOT advance it (pre-fix it was the max
    over ALL rows, so a manual run masked a stalled cron), while a natural
    row must.  The all-rows view stays visible as latest_recorded_date."""
    from plugins.memory.memory_os.v3_seed_evidence import build_v3_seed_evidence_snapshot

    store = _store(tmp_path)
    natural_yesterday = {
        "schema_version": "memory-os.v3_seed_edges_daily.v0",
        "natural_date": "2026-06-01",
        "created_at": "2026-06-02T00:00:01Z",
        "valid": True,
        "coverage_ratio": 1.0,
        "rebuild_digest": "sha256:natural-1",
        "trigger_class": "natural_cron",
    }
    manual_today = {
        "schema_version": "memory-os.v3_seed_edges_daily.v0",
        "natural_date": "2026-06-02",
        "created_at": "2026-06-03T00:00:01Z",
        "valid": True,
        "coverage_ratio": 1.0,
        "rebuild_digest": "sha256:manual-2",
        "trigger_class": "manual",
    }

    snapshot = build_v3_seed_evidence_snapshot(
        store, daily_records=[natural_yesterday, manual_today]
    )
    # Cron freshness stalls at the last natural day; the manual run only
    # advances the display-oriented all-rows view.
    assert snapshot["latest_natural_date"] == "2026-06-01"
    assert snapshot["latest_recorded_date"] == "2026-06-02"

    natural_today = dict(
        natural_yesterday,
        natural_date="2026-06-02",
        created_at="2026-06-03T01:00:00Z",
        rebuild_digest="sha256:natural-2",
    )
    snapshot = build_v3_seed_evidence_snapshot(
        store, daily_records=[natural_yesterday, manual_today, natural_today]
    )
    assert snapshot["latest_natural_date"] == "2026-06-02"
    assert snapshot["latest_recorded_date"] == "2026-06-02"


def test_snapshot_no_rows_has_empty_freshness_fields(tmp_path):
    """P2 #8: both freshness fields degrade to empty strings with no rows."""
    from plugins.memory.memory_os.v3_seed_evidence import build_v3_seed_evidence_snapshot

    store = _store(tmp_path)
    snapshot = build_v3_seed_evidence_snapshot(store, daily_records=[])

    assert snapshot["latest_natural_date"] == ""
    assert snapshot["latest_recorded_date"] == ""
    assert snapshot["manual_day_count"] == 0


def test_snapshot_latest_revision_survives_microsecond_omission_boundary(tmp_path):
    """P2 #10 counterfactual (all-rows merge): lexicographic created_at
    comparison picks the WRONG latest revision on the microsecond-omission
    boundary — "...T10:00:00.500000Z" < "...T10:00:00Z" as strings ("." sorts
    before "Z") although it is temporally LATER.  The temporally-later manual
    invalid revision must win the all-rows merge and drive invalid_day_count;
    under the pre-fix string comparison the earlier natural row wins and
    invalid_day_count stays 0."""
    from plugins.memory.memory_os.v3_seed_evidence import build_v3_seed_evidence_snapshot

    store = _store(tmp_path)
    temporally_later_manual = {
        "schema_version": "memory-os.v3_seed_edges_daily.v0",
        "natural_date": "2026-06-01",
        "created_at": "2026-06-02T10:00:00.500000Z",
        "valid": False,
        "coverage_ratio": 0.0,
        "rebuild_digest": "sha256:manual-revision",
        "trigger_class": "manual",
    }
    temporally_earlier_natural = {
        "schema_version": "memory-os.v3_seed_edges_daily.v0",
        "natural_date": "2026-06-01",
        "created_at": "2026-06-02T10:00:00Z",
        "valid": True,
        "coverage_ratio": 1.0,
        "rebuild_digest": "sha256:natural-original",
        "trigger_class": "natural_cron",
    }

    # File order: the temporally-later row first, the temporally-earlier row
    # last — string comparison would let the later-in-file row win ("Z" >= ".").
    snapshot = build_v3_seed_evidence_snapshot(
        store, daily_records=[temporally_later_manual, temporally_earlier_natural]
    )

    # The temporally-later (invalid manual) revision is the true latest row.
    assert snapshot["invalid_day_count"] == 1
    # The independent natural merge still keeps the natural day (BD.3).
    assert snapshot["valid_day_count"] == 1


def test_snapshot_natural_merge_survives_microsecond_omission_boundary(tmp_path):
    """P2 #10 counterfactual (natural-only merge): same boundary inside
    natural_by_date — the temporally-later invalid natural revision must win
    over the temporally-earlier valid one even though it sorts first as a
    string and appears first in the file."""
    from plugins.memory.memory_os.v3_seed_evidence import build_v3_seed_evidence_snapshot

    store = _store(tmp_path)
    temporally_later_invalid = {
        "schema_version": "memory-os.v3_seed_edges_daily.v0",
        "natural_date": "2026-06-01",
        "created_at": "2026-06-02T10:00:00.500000Z",
        "valid": False,
        "coverage_ratio": 0.0,
        "rebuild_digest": "sha256:cron-invalid-revision",
        "trigger_class": "natural_cron",
    }
    temporally_earlier_valid = {
        "schema_version": "memory-os.v3_seed_edges_daily.v0",
        "natural_date": "2026-06-01",
        "created_at": "2026-06-02T10:00:00Z",
        "valid": True,
        "coverage_ratio": 1.0,
        "rebuild_digest": "sha256:cron-valid-original",
        "trigger_class": "natural_cron",
    }

    snapshot = build_v3_seed_evidence_snapshot(
        store, daily_records=[temporally_later_invalid, temporally_earlier_valid]
    )

    # The temporally-later revision is invalid, so the day earns no credit.
    assert snapshot["valid_day_count"] == 0
    assert snapshot["consecutive_valid_day_count"] == 0
    assert snapshot["invalid_day_count"] == 1


def test_snapshot_unparseable_created_at_falls_back_to_string_comparison(tmp_path):
    """P2 #10 documented fallback: if either created_at fails to parse, the
    merge falls back to the historical string comparison (stable — later in
    string order wins, later in file order wins ties)."""
    from plugins.memory.memory_os.v3_seed_evidence import build_v3_seed_evidence_snapshot

    store = _store(tmp_path)
    unparseable_row = {
        "schema_version": "memory-os.v3_seed_edges_daily.v0",
        "natural_date": "2026-06-01",
        "created_at": "zzz-not-a-timestamp",
        "valid": False,
        "coverage_ratio": 0.0,
        "rebuild_digest": "sha256:garbage",
        "trigger_class": "natural_cron",
    }
    parseable_row = {
        "schema_version": "memory-os.v3_seed_edges_daily.v0",
        "natural_date": "2026-06-01",
        "created_at": "2026-06-02T00:00:00Z",
        "valid": True,
        "coverage_ratio": 1.0,
        "rebuild_digest": "sha256:parseable",
        "trigger_class": "natural_cron",
    }

    # String fallback: "2026-..." < "zzz-..." so the unparseable row keeps
    # winning regardless of file order — identical to pre-fix behavior.
    snapshot = build_v3_seed_evidence_snapshot(
        store, daily_records=[unparseable_row, parseable_row]
    )
    assert snapshot["valid_day_count"] == 0
    assert snapshot["invalid_day_count"] == 1

    snapshot = build_v3_seed_evidence_snapshot(
        store, daily_records=[parseable_row, unparseable_row]
    )
    assert snapshot["valid_day_count"] == 0
    assert snapshot["invalid_day_count"] == 1
