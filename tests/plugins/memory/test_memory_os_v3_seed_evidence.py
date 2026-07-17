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
