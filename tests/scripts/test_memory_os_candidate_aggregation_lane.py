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
import sys
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


# ── 2026-08-15: compaction_skip_reason wiring through main() ───────────────
#
# main() builds two separate closed-set surfaces from the lane's result:
# the printed cron-delivery `summary` dict (an explicit key-picking
# whitelist that dropped compaction_skip_reason), and the run_status/reason
# derivation for record_lane_last_run, which used to derive purely from
# counters (promoted+demoted+fleeting+compacted). Since compacted_count is
# 0 both when compaction ran with nothing to archive AND when it was
# skipped, a skipped compaction misreported as "no_triage_actions"/
# "triaged" -- byte-identical to a healthy tick. Both need the fix; this
# test proves both from ONE real lane failure.


def test_compaction_skip_reason_flows_through_script_summary_and_lane_last_run(
    tmp_path, monkeypatch, capsys,
):
    """Invokes main() in-process (not subprocess) so
    aggregation.read_effective_candidates can be monkeypatched to a genuine
    failure -- the real-producer discipline used throughout this batch's
    counterfactuals. A hand-written result dict would only prove the
    key-picking lines exist, not that main() actually receives the field
    from a real lane run."""
    import scripts.memory_os_candidate_aggregation_lane as lane_script
    import plugins.modules.governance.candidate_aggregation as aggregation
    from plugins.memory.memory_os.lane_last_run import read_lane_last_run

    _store_with_gate(tmp_path)  # writes the envelope main() will read from disk

    def _raise_view_failure(_store):
        raise RuntimeError("synthetic effective-view failure")

    monkeypatch.setattr(aggregation, "read_effective_candidates", _raise_view_failure)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "memory_os_candidate_aggregation_lane.py",
            "--hermes-home", str(tmp_path),
            "--profile", "memoryos-test",
            "--envelope-id", _VALID_ENVELOPE_ID,
        ],
    )

    rc = lane_script.main()
    assert rc == 0

    printed = capsys.readouterr().out
    summary = json.loads(printed)
    assert summary["compaction_skip_reason"] == "effective_view_unavailable", (
        "the script's printed cron-delivery summary dropped "
        f"compaction_skip_reason: {summary}"
    )

    last_run = read_lane_last_run(str(tmp_path), "candidate_aggregation")
    assert last_run is not None
    assert last_run["status"] == "ok", (
        "a view failure is visibility, not alerting: a view failure already "
        "emits its own error record, and a queue that merely grows is "
        "recoverable, so status must stay ok, not warn/fail"
    )
    assert last_run["reason"] == "compaction_skipped_effective_view_unavailable", (
        "counterfactual: without the fix this reports 'no_triage_actions' "
        "-- byte-identical to a healthy tick with nothing to compact, "
        f"because compacted_count is 0 either way. got: {last_run}"
    )
