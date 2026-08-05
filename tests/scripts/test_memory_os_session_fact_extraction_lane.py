"""Tests for the session_fact_extraction lane script's CLI/env contract and
execution report writer.

Mirrors tests/scripts/test_memory_os_candidate_aggregation_lane.py: the
boundary dict written to the helper execution report must never carry a bare
True (any_boundary_true() has no concept of "provisional"), and this lane
never sends/executes/writes identity/crystallizes anything, so every
boundary field is unconditionally False.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from plugins.memory.memory_os.execution_gate import any_boundary_true
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore
from scripts.memory_os_session_fact_extraction_lane import _write_execution_report, main

_VALID_ENVELOPE_ID = "xgate_test_sfe_lane_script_envelope"


def _store_with_gate(tmp_path) -> MemoryOSStore:
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    store = MemoryOSStore(roots)
    store.initialize()

    now = datetime.now(timezone.utc)
    expires_at = now.replace(year=now.year + 1).isoformat().replace("+00:00", "Z")
    envelope = {
        "schema_version": "memory-os.execution_gate_envelope.v0",
        "stage": "permit",
        "execution_gate_envelope_id": _VALID_ENVELOPE_ID,
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": expires_at,
        "profile": "memoryos-test",
        "lane_id": "session_fact_extraction",
        "trigger_surface": "hermes_cron",
        "risk_class": "local_helper",
        "human_approval_required": False,
        "why_no_human_approval": "test",
        "scope": {"registry_key": "session_fact_extraction", "raw_script": "test"},
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
        },
        "boundary_true": False,
        "precheck": {"helper_present": True},
        "permit_decision": "allowed",
        "permit_reason": "boundary_false",
    }
    gate_path = roots.hermes_home / "memory-os" / "system" / "execution_gate_envelopes.jsonl"
    gate_path.parent.mkdir(parents=True, exist_ok=True)
    with gate_path.open("a") as f:
        f.write(json.dumps(envelope, sort_keys=True) + "\n")

    return store


def _fake_result(**overrides):
    base = {
        "schema_version": "memory-os.session_fact_extraction_run.v0",
        "profile": "memoryos-test",
        "lane_id": "session_fact_extraction",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sessions_scanned": 0,
        "sessions_eligible": 0,
        "sessions_processed": 0,
        "sessions_skipped_already_processed": 0,
        "messages_considered": 0,
        "messages_eligible_over_threshold": 0,
        "facts_extracted": 0,
        "candidates_written": 0,
        "llm_calls": 0,
        "llm_failures_by_reason": {},
        "fallback_used_count": 0,
        "status": "ok",
        "skipped": False,
        "skipped_reason": "",
        "error_records": [],
        "actual_send": False,
        "actual_execute": False,
        "actual_identity_write": False,
        "actual_crystallized_approval": False,
    }
    base.update(overrides)
    return base


def test_lane_script_execution_report_boundary_stays_false_even_with_writes(tmp_path, monkeypatch):
    """Counterfactual: if _write_execution_report ever passed a lane counter
    straight through into `boundary` (the P1-1 mistake this pattern guards
    against elsewhere), any_boundary_true() would flip True the moment a
    real candidate got written. It must not.
    """
    result = _fake_result(sessions_processed=1, candidates_written=3, facts_extracted=3)

    report_path = tmp_path / "execution-report.json"
    monkeypatch.setenv("MEMORY_OS_EXECUTION_REPORT_PATH", str(report_path))

    _write_execution_report(result)

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert any_boundary_true(report["boundary"]) is False
    assert report["boundary"]["actual_crystallized_approval"] is False
    assert report["result_summary"]["candidates_written"] == 3


def test_lane_script_execution_report_empty_tick_boundary_stays_false(tmp_path, monkeypatch):
    result = _fake_result()
    report_path = tmp_path / "execution-report.json"
    monkeypatch.setenv("MEMORY_OS_EXECUTION_REPORT_PATH", str(report_path))

    _write_execution_report(result)

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert any_boundary_true(report["boundary"]) is False


def test_main_end_to_end_prints_required_counters_and_writes_report(tmp_path, monkeypatch, capsys):
    _store_with_gate(tmp_path)
    report_path = tmp_path / "helper-report.json"

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_PROFILE", "memoryos-test")
    monkeypatch.setenv("MEMORY_OS_EXECUTION_GATE_ENVELOPE_ID", _VALID_ENVELOPE_ID)
    monkeypatch.setenv("MEMORY_OS_EXECUTION_REPORT_PATH", str(report_path))

    returncode = main()
    assert returncode == 0

    out = capsys.readouterr().out
    summary = json.loads(out)

    for key in (
        "sessions_scanned",
        "sessions_eligible",
        "sessions_processed",
        "sessions_skipped_already_processed",
        "messages_considered",
        "messages_eligible_over_threshold",
        "facts_extracted",
        "candidates_written",
        "llm_calls",
        "llm_failures_by_reason",
        "fallback_used_count",
        "skipped",
        "skipped_reason",
        "status",
    ):
        assert key in summary, key

    # No sessions directory under tmp_path -> explicit skip, not silent no-op.
    assert summary["skipped"] is True
    assert summary["skipped_reason"] == "sessions_dir_absent"

    assert report_path.exists()
    written = json.loads(report_path.read_text(encoding="utf-8"))
    assert any_boundary_true(written["boundary"]) is False
