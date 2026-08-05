"""CE.2: provenance-less candidates must not crash the aggregation lane.

Production shape being pinned: session_fact_extraction's first five candidates
carried ``source_event_ids=[]`` and durable_fact verdicts; the durable-fact
bypass auto-approved them, the crystallized write gate raised
``CrystallizedApprovalError`` (crystallized records require source_event_ids),
nothing caught it, and every candidate_aggregation tick from 12:12Z on died
with rc=1 and no helper report — one bad candidate starving the whole lane on
every due tick.

Two independent fixes, each with its own counterfactual here:
1. eligibility: ``_resolver_verdict`` refuses provenance-less candidates
   (they cannot be crystallized on ANY approval path, so auto-approving them
   can only crash), routing them to owner review;
2. containment: a provisional write failure is recorded as a bounded
   error_record and the candidate re-routed, never re-raised out of the tick.
"""

import json
from datetime import datetime, timezone

import plugins.modules.governance.candidate_aggregation as aggregation
from plugins.memory.memory_os.crystallized import (
    CrystallizedCandidate,
    read_candidate_triage,
)
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore

_VALID_ENVELOPE_ID = "xgate_test_candidate_provenance_envelope"


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
    with gate_path.open("a") as handle:
        handle.write(json.dumps(envelope, sort_keys=True) + "\n")
    return store


def _candidate(candidate_id: str, *, source_event_ids: list[str]) -> CrystallizedCandidate:
    return CrystallizedCandidate(
        candidate_id=candidate_id,
        kind="moment",
        body="Extracted from session s-1 (telegram): the owner prefers rsync backups.",
        source_event_ids=source_event_ids,
        sensitivity="private",
        tags=["session_fact_extraction", "long_message_fact"],
        bridge_state="inner_drive_candidate",
        created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )


def test_resolver_verdict_refuses_provenance_less_candidates(tmp_path):
    store = _store_with_gate(tmp_path)
    verdict = aggregation._resolver_verdict(
        _candidate("cand_sfe_noprov", source_event_ids=[]), store=store,
    )
    assert verdict["approve"] is False
    assert verdict["reason"] == "missing_source_event_ids"


def test_provenance_less_durable_fact_routes_to_owner_review_not_the_cliff(tmp_path, monkeypatch):
    """The exact production shape. Counterfactual: without the eligibility
    check this raises CrystallizedApprovalError out of the pipeline stage —
    the crash that killed every tick."""
    store = _store_with_gate(tmp_path)
    bad = _candidate("cand_sfe_noprov_e2e", source_event_ids=[])
    monkeypatch.setattr(
        "plugins.modules.governance.fact_judge.read_fact_judge_verdicts",
        lambda _store: {"cand_sfe_noprov_e2e": True},
    )

    result = aggregation._cluster_and_promote(
        [bad], store, set(), envelope_id=_VALID_ENVELOPE_ID, min_cluster_size=2,
    )

    assert result["provisional_crystallized_write_count"] == 0
    triage = read_candidate_triage(store)
    latest = next(rec for rec in triage if rec.get("candidate_id") == "cand_sfe_noprov_e2e")
    assert latest.get("target_state") == "owner_eligible", (
        "a provenance-less durable fact must reach owner review, not crash the lane"
    )


def test_provisional_write_failure_is_contained_and_reported(tmp_path, monkeypatch):
    """Counterfactual: without _try_write_resolver_provisional the injected
    failure re-raises out of the stage and the second candidate is never
    processed — one bad candidate starving the lane."""
    store = _store_with_gate(tmp_path)
    good = _candidate("cand_ok_provenance", source_event_ids=["evt-real-001"])
    monkeypatch.setattr(
        "plugins.modules.governance.fact_judge.read_fact_judge_verdicts",
        lambda _store: {"cand_ok_provenance": True},
    )

    def _boom(store, candidate, decision):
        raise RuntimeError("injected write failure")

    monkeypatch.setattr(aggregation, "_write_resolver_provisional", _boom)

    error_records: list[dict] = []
    result = aggregation._cluster_and_promote(
        [good], store, set(),
        envelope_id=_VALID_ENVELOPE_ID, min_cluster_size=2,
        error_records=error_records,
    )

    assert result["provisional_crystallized_write_count"] == 0
    assert any(
        record.get("error_code") == "provisional_write_failed"
        and record.get("component") == "candidate_aggregation"
        for record in error_records
    ), "the failure must surface as a bounded error record, not a crash"
    triage = read_candidate_triage(store)
    latest = next(rec for rec in triage if rec.get("candidate_id") == "cand_ok_provenance")
    assert latest.get("target_state") == "owner_eligible"
