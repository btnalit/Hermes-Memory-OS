"""Tests for the candidate_aggregation lane script's execution report writer.

P1-1: `_write_execution_report()` builds the `boundary` dict written to the
helper execution report file (read downstream by the boundary runtime probe
and the monitor). That dict must never carry a bare `True` for
`actual_crystallized_approval` -- execution_gate.any_boundary_true() treats
ANY nested bare `True` as a boundary violation, with no concept of
"provisional". A bounded, reversible provisional crystallized write is
legitimate; letting it leak into this boundary channel as a bare True is
indistinguishable from a real violation to that scanner (and to anything
downstream that scans the same shape).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from plugins.memory.memory_os.crystallized import CrystallizedCandidate, append_candidate_queue
from plugins.memory.memory_os.execution_gate import any_boundary_true
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.modules.governance.candidate_aggregation import run_candidate_aggregation_lane
from scripts.memory_os_candidate_aggregation_lane import _write_execution_report

_VALID_ENVELOPE_ID = "xgate_test_lane_script_envelope"


def _store_with_gate(tmp_path) -> MemoryOSStore:
    """Create an initialized store with a pre-written valid execution-gate envelope."""
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
        "lane_id": "candidate_aggregation",
        "trigger_surface": "hermes_cron",
        "risk_class": "bounded_reversible_queue",
        "human_approval_required": False,
        "why_no_human_approval": "test",
        "scope": {"registry_key": "candidate_aggregation", "raw_script": "test"},
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


def _cand(candidate_id: str, body: str) -> CrystallizedCandidate:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return CrystallizedCandidate(
        candidate_id=candidate_id,
        kind="moment",
        body=body,
        source_event_ids=["evt-test"],
        sensitivity="private",
        tags=["test"],
        bridge_state="",
        created_at=now,
        rejection_count=0,
    )


def test_candidate_aggregation_lane_provisional_write_does_not_trip_boundary(tmp_path, monkeypatch):
    """A real provisional crystallized write must not appear as a bare True
    anywhere in the lane script's helper execution report `boundary` dict.

    Counterfactual: before the P1-1 fix, `_write_execution_report` passed
    `result["actual_crystallized_approval"]` straight through into
    `boundary`. Since a real provisional write sets that field True, the
    written report's boundary dict would contain a bare True and
    any_boundary_true() would flag it as a violation.
    """
    store = _store_with_gate(tmp_path)
    append_candidate_queue(store, _cand("cand-lane-report", "记住：每次启动必须检查日志"))

    result = run_candidate_aggregation_lane(store, execution_gate_envelope_id=_VALID_ENVELOPE_ID)
    # Sanity: a real provisional write happened (otherwise this test proves nothing).
    assert result["actual_crystallized_approval"] is True
    assert result["provisional_crystallized_write_count"] == 1

    report_path = tmp_path / "execution-report.json"
    monkeypatch.setenv("MEMORY_OS_EXECUTION_REPORT_PATH", str(report_path))

    _write_execution_report(result)

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert any_boundary_true(report["boundary"]) is False
    assert report["boundary"]["actual_permanent_crystallized_approval"] is False


def test_candidate_aggregation_lane_empty_tick_boundary_stays_false(tmp_path, monkeypatch):
    """No candidates -> no write -> the boundary dict is trivially all False."""
    store = _store_with_gate(tmp_path)
    result = run_candidate_aggregation_lane(store, execution_gate_envelope_id=_VALID_ENVELOPE_ID)
    assert result["actual_crystallized_approval"] is False

    report_path = tmp_path / "execution-report.json"
    monkeypatch.setenv("MEMORY_OS_EXECUTION_REPORT_PATH", str(report_path))

    _write_execution_report(result)

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert any_boundary_true(report["boundary"]) is False
