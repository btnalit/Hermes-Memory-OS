from __future__ import annotations

import json
from datetime import datetime, timezone

from plugins.memory.memory_os.clearance_receipts import (
    ClearanceReceipt,
    clearance_receipts_path,
    rebuild_clearance_receipt_snapshot,
    write_clearance_receipt,
)
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.memory.memory_os.v3_wandering import WANDERING_PROMPT_CONTRACT, run_v3_wandering_cycle
from plugins.memory.memory_os.wandering_journal import query_journal


def _store(tmp_path) -> MemoryOSStore:
    roots = MemoryOSRoots.from_hermes_home(tmp_path / ".hermes", profile="default")
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def _receipt(*, invalidated_at=None) -> ClearanceReceipt:
    return ClearanceReceipt(
        receipt_id="clear-1",
        record_id="cand-1",
        content_hash="abc",
        verdict="clear",
        corpus_watermark=7,
        judge_version="judge-v1",
        judged_at="2026-07-15T00:00:00Z",
        invalidated_at=invalidated_at,
        invalidated_by="event-8" if invalidated_at else None,
    )


def test_clearance_snapshot_projects_effective_receipts_and_source_watermark(tmp_path):
    from plugins.memory.memory_os.clearance_receipts import clearance_snapshot_freshness

    store = _store(tmp_path)
    write_clearance_receipt(store.roots, _receipt())
    path = clearance_receipts_path(store.roots)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_receipt(invalidated_at="2026-07-15T01:00:00Z").to_dict(), sort_keys=True) + "\n")

    snapshot = rebuild_clearance_receipt_snapshot(store.roots)
    freshness = clearance_snapshot_freshness(store.roots)

    assert snapshot["raw_ledger_rows"] == 2
    assert snapshot["effective_receipts"] == 1
    assert snapshot["active_receipts"] == 0
    assert snapshot["latest_watermark"] == 7
    assert snapshot["source_ledger_sha256"]
    assert snapshot["source_ledger_size_bytes"] == path.stat().st_size
    assert freshness["status"] == "fresh"
    assert freshness["would_gate_activation"] is False


def test_clearance_snapshot_detects_ledger_drift_and_fails_closed_for_activation(tmp_path):
    from plugins.memory.memory_os.clearance_receipts import clearance_snapshot_freshness

    store = _store(tmp_path)
    write_clearance_receipt(store.roots, _receipt())
    rebuild_clearance_receipt_snapshot(store.roots)
    path = clearance_receipts_path(store.roots)
    with path.open("a", encoding="utf-8") as handle:
        newer = _receipt(invalidated_at="2026-07-15T01:00:00Z").to_dict()
        handle.write(json.dumps(newer, sort_keys=True) + "\n")

    freshness = clearance_snapshot_freshness(store.roots, for_activation=True)

    assert freshness["status"] == "stale"
    assert freshness["severity"] == "FAIL"
    assert freshness["would_gate_activation"] is True
    assert "ledger" in freshness["reason"]


def test_provisional_write_postcheck_distinguishes_write_from_permanent_approval():
    from plugins.modules.governance.candidate_aggregation import provisional_write_postcheck

    report = provisional_write_postcheck()

    assert report == {
        "crystallized_write": "provisional_success",
        "actual_provisional_crystallized_write": True,
        "actual_permanent_crystallized_approval": False,
        "actual_unapproved_crystallized_approval": False,
    }


def test_v3_wandering_contract_is_boundary_only_and_empty_output_is_healthy(tmp_path):
    forbidden = ("find an insight", "must produce", "success criterion", "minimum output", "catch-up", "emergency")
    lowered = WANDERING_PROMPT_CONTRACT.lower()
    assert all(term not in lowered for term in forbidden)
    assert 'return {"entries":[]}' in WANDERING_PROMPT_CONTRACT

    class EmptyAdapter:
        capability = True

        def infer(self, *, packet, prompt_contract, route_snapshot):
            return {
                "status": "ok",
                "actual_provider": route_snapshot["provider"],
                "actual_model": route_snapshot["model"],
                "structured_output": {"entries": []},
                "model_input_transmitted": True,
                "owner_delivery_attempted": False,
                "external_action_executed": False,
                "tools_enabled": False,
                "tool_calls": [],
            }

    store = _store(tmp_path)
    result = run_v3_wandering_cycle(
        store,
        adapter=EmptyAdapter(),
        route_snapshot={"provider": "fixture", "model": "fixture"},
        seed_candidates=[{
            "ref": "crystallized:fixture",
            "kind": "stable_memory",
            "bounded_text": "A bounded source fragment",
            "epistemic_status": "approved",
            "salience_reasons": [],
        }],
        edges=[],
        quiet_gate={"quiet": True},
        ttl_days=3,
        max_entry_chars=100,
        max_lineage_hops=2,
        model_input_char_budget=100,
    )

    assert result["status"] == "healthy_no_sample"
    assert result["reason"] == "empty_entries"
    assert result["owner_delivery_attempted"] is False
    assert result["external_action_executed"] is False


def test_v3_no_eligible_input_is_healthy_without_model_call(tmp_path):
    class NeverAdapter:
        capability = True

        def infer(self, **_kwargs):
            raise AssertionError("model must not be called without eligible input")

    result = run_v3_wandering_cycle(
        _store(tmp_path),
        adapter=NeverAdapter(),
        route_snapshot={"provider": "fixture", "model": "fixture"},
        seed_candidates=[],
        edges=[],
        quiet_gate={"quiet": True},
        ttl_days=3,
        max_entry_chars=100,
        max_lineage_hops=2,
        model_input_char_budget=100,
    )
    assert result["status"] == "healthy_no_sample"
    assert result["reason"] == "no_eligible_input"
    assert result["model_input_transmitted"] is False


def test_owner_journal_query_trace_contains_scope_but_no_result_or_body_metadata(tmp_path):
    store = _store(tmp_path)
    assert query_journal(store, scope_class="all") == []
    path = store.roots.memory_os_root / "system" / "wandering_journal.jsonl"
    trace = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])

    assert set(trace) == {"queried_at", "scope"}
    assert trace["queried_at"]
    assert trace["scope"] == "all"
    assert "scope_class" not in trace
    assert "result_count_bucket" not in trace
    assert "query" not in trace
    assert "body" not in trace


def test_v3_ttl_sweep_status_remains_cycle_only(tmp_path):
    from plugins.memory.memory_os.v3_retention import sweep_pending_expired

    store = _store(tmp_path)
    now = datetime(2026, 7, 15, tzinfo=timezone.utc)
    report = sweep_pending_expired(store, now=now)

    assert report["cycle_status"] == "ok"
    sweep = json.loads((store.roots.memory_os_root / "system" / "v3_journal_sweep_status.json").read_text())
    assert sweep == {"cycle_status": "ok"}
    assert all("delet" not in key and "annihilat" not in key and "count" not in key for key in sweep)
