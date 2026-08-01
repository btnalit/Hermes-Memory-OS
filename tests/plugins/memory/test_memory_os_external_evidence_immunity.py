import json
import sqlite3
from datetime import datetime, timezone

import pytest

from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
from plugins.memory.memory_os.crystallized import (
    CrystallizedApprovalError,
    CrystallizedCandidate,
    CrystallizedMemoryService,
    append_candidate_queue,
    read_candidate_queue,
    read_candidate_triage,
)
from plugins.memory.memory_os.index import MemoryOSIndex
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.schema import EVENT_SCHEMA_VERSION, EventEnvelope
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.modules.governance.candidate_aggregation import _cluster_and_promote

pytestmark = pytest.mark.usefixtures("crystallized_test_write_authority")

_VALID_ENVELOPE_ID = "xgate_test_external_evidence_immunity"


def _store(tmp_path) -> MemoryOSStore:
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def _store_with_gate(tmp_path) -> MemoryOSStore:
    store = _store(tmp_path)
    now = datetime.now(timezone.utc)
    envelope = {
        "schema_version": "memory-os.execution_gate_envelope.v0",
        "stage": "permit",
        "execution_gate_envelope_id": _VALID_ENVELOPE_ID,
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": now.replace(year=now.year + 1).isoformat().replace("+00:00", "Z"),
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
    gate_path = store.roots.hermes_home / "memory-os" / "system" / "execution_gate_envelopes.jsonl"
    gate_path.parent.mkdir(parents=True, exist_ok=True)
    with gate_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(envelope, sort_keys=True) + "\n")
    return store


def _append_event(store: MemoryOSStore, event_id: str, *, source_class: str = "", external_ref: str = "") -> EventEnvelope:
    safe_ref = {}
    if source_class:
        safe_ref["source_class"] = source_class
    if external_ref:
        safe_ref["external_ref"] = external_ref
    event = EventEnvelope(
        schema_version=EVENT_SCHEMA_VERSION,
        id=event_id,
        ts="2026-06-18T00:00:00+00:00",
        profile="memoryos-test",
        source="test",
        kind="conversation_turn",
        summary="synthetic event",
        safe_ref=safe_ref,
        tags=[],
        sensitivity="private",
        body_policy="summary_only",
        hashes={},
        promotion_state="raw",
    )
    store.append_event(event)
    return event


def _candidate(candidate_id: str = "cand-ext-001", *, source_event_ids=None, provenance=None) -> CrystallizedCandidate:
    return CrystallizedCandidate(
        candidate_id=candidate_id,
        kind="moment",
        body="记住：每次部署外部证据前必须经过 owner ack 才能进入长期记忆",
        source_event_ids=list(source_event_ids or ["evt-clean"]),
        sensitivity="private",
        tags=["test"],
        bridge_state="inner_drive_candidate",
        created_at="2026-06-18T00:00:01+00:00",
        provenance=provenance,
    )


def test_tainted_event_safe_ref_source_class_is_tainted(tmp_path):
    from plugins.memory.memory_os.provenance import is_tainted

    store = _store(tmp_path)
    event = _append_event(
        store,
        "evt-tainted",
        source_class="external_evidence",
        external_ref="external:dataset:doc:chunk",
    )

    assert is_tainted(event, store=store) is True


def test_candidate_own_external_evidence_provenance_is_tainted(tmp_path):
    from plugins.memory.memory_os.provenance import candidate_external_ref, is_tainted

    store = _store(tmp_path)
    candidate = _candidate(
        provenance={
            "source_class": "external_evidence",
            "external_ref": "external:dataset:doc:chunk",
            "crystallization_allowed": False,
        }
    )

    assert is_tainted(candidate, store=store) is True
    assert candidate_external_ref(candidate, store=store) == "external:dataset:doc:chunk"


def test_candidate_transitively_tainted_by_source_event(tmp_path):
    from plugins.memory.memory_os.provenance import candidate_external_ref, is_tainted

    store = _store(tmp_path)
    _append_event(
        store,
        "evt-tainted",
        source_class="external_evidence",
        external_ref="external:dataset:doc:chunk",
    )
    candidate = _candidate(source_event_ids=["evt-tainted"], provenance=None)

    assert is_tainted(candidate, store=store) is True
    assert candidate_external_ref(candidate, store=store) == "external:dataset:doc:chunk"


def test_candidate_transitive_lookup_error_fails_closed_as_tainted(tmp_path):
    from plugins.memory.memory_os.provenance import is_tainted

    class BrokenStore:
        def read_events(self):
            raise RuntimeError("event store unavailable")

    candidate = _candidate(source_event_ids=["evt-unknown"], provenance=None)

    assert is_tainted(candidate, store=BrokenStore()) is True


def test_candidate_queue_and_index_preserve_provenance_json(tmp_path):
    store = _store(tmp_path)
    provenance = {
        "source_class": "external_evidence",
        "external_ref": "external:dataset:doc:chunk",
        "contains_external_evidence": True,
        "crystallization_allowed": False,
    }
    candidate = _candidate(provenance=provenance)
    append_candidate_queue(store, candidate)

    queued = read_candidate_queue(store)
    assert queued[0].provenance == provenance

    MemoryOSIndex(store.roots).rebuild_from_store(store)
    conn = sqlite3.connect(store.roots.index_path)
    try:
        cols = {row[1] for row in conn.execute("pragma table_info(crystallized_candidates)").fetchall()}
        assert "provenance_json" in cols
        row = conn.execute(
            "select provenance_json from crystallized_candidates where candidate_id = ?",
            (candidate.candidate_id,),
        ).fetchone()
        assert json.loads(row[0]) == provenance
    finally:
        conn.close()


def test_write_approved_record_rejects_tainted_candidate_without_external_ack(tmp_path):
    store = _store(tmp_path)
    candidate = _candidate(
        provenance={"source_class": "external_evidence", "external_ref": "external:dataset:doc:chunk"}
    )
    decision = ApprovalDecision(
        candidate_id=candidate.candidate_id,
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="owner",
        reviewed_at="2026-06-18T00:00:00+00:00",
    )

    with pytest.raises(CrystallizedApprovalError, match="external_evidence_requires_explicit_ack"):
        CrystallizedMemoryService(store).write_approved_record(candidate, decision, file_name="moments.md")

    assert list(store.roots.crystallized_root.glob("*.md")) == []


def test_write_approved_record_rejects_tainted_candidate_with_wrong_external_ref_ack(tmp_path):
    store = _store(tmp_path)
    candidate = _candidate(
        provenance={"source_class": "external_evidence", "external_ref": "external:dataset:doc:chunk"}
    )
    decision = ApprovalDecision(
        candidate_id=candidate.candidate_id,
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="owner",
        reviewed_at="2026-06-18T00:00:00+00:00",
        external_evidence_ack=True,
        acked_external_ref="external:other:doc:chunk",
    )

    with pytest.raises(CrystallizedApprovalError, match="external_evidence_ack_ref_mismatch"):
        CrystallizedMemoryService(store).write_approved_record(candidate, decision, file_name="moments.md")

    assert list(store.roots.crystallized_root.glob("*.md")) == []


def test_write_approved_record_rejects_tainted_candidate_with_missing_external_ref_even_with_ack(tmp_path):
    store = _store(tmp_path)
    candidate = _candidate(provenance={"source_class": "external_evidence"})
    decision = ApprovalDecision(
        candidate_id=candidate.candidate_id,
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="owner",
        reviewed_at="2026-06-18T00:00:00+00:00",
        external_evidence_ack=True,
        acked_external_ref="",
    )

    with pytest.raises(CrystallizedApprovalError, match="external_evidence_ref_unresolved"):
        CrystallizedMemoryService(store).write_approved_record(candidate, decision, file_name="moments.md")

    assert list(store.roots.crystallized_root.glob("*.md")) == []


def test_write_approved_record_allows_matching_external_ref_ack_and_preserves_provenance(tmp_path):
    store = _store(tmp_path)
    provenance = {"source_class": "external_evidence", "external_ref": "external:dataset:doc:chunk"}
    candidate = _candidate(provenance=provenance)
    decision = ApprovalDecision(
        candidate_id=candidate.candidate_id,
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="owner",
        reviewed_at="2026-06-18T00:00:00+00:00",
        external_evidence_ack=True,
        acked_external_ref="external:dataset:doc:chunk",
    )

    service = CrystallizedMemoryService(store)
    service.write_approved_record(candidate, decision, file_name="moments.md")

    records = service.read_records("moments.md")
    assert records[0].frontmatter["provenance"] == provenance
    assert records[0].frontmatter["external_evidence_ack"] is True
    assert records[0].frontmatter["acked_external_ref"] == "external:dataset:doc:chunk"


def test_write_approved_record_allows_transitive_external_ref_ack_and_preserves_provenance(tmp_path):
    store = _store(tmp_path)
    _append_event(
        store,
        "evt-tainted",
        source_class="external_evidence",
        external_ref="external:dataset:doc:chunk",
    )
    candidate = _candidate(source_event_ids=["evt-tainted"], provenance=None)
    decision = ApprovalDecision(
        candidate_id=candidate.candidate_id,
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="owner",
        reviewed_at="2026-06-18T00:00:00+00:00",
        external_evidence_ack=True,
        acked_external_ref="external:dataset:doc:chunk",
    )

    service = CrystallizedMemoryService(store)
    service.write_approved_record(candidate, decision, file_name="moments.md")

    records = service.read_records("moments.md")
    assert records[0].frontmatter["provenance"] == {
        "source_class": "external_evidence",
        "external_ref": "external:dataset:doc:chunk",
    }


def test_cluster_auto_resolver_skips_tainted_candidate_without_lane_error(tmp_path):
    store = _store_with_gate(tmp_path)
    _append_event(
        store,
        "evt-tainted",
        source_class="external_evidence",
        external_ref="external:dataset:doc:chunk",
    )
    tainted = _candidate("cand-tainted", source_event_ids=["evt-tainted"])
    clean = CrystallizedCandidate(
        candidate_id="cand-clean",
        kind="moment",
        body="记住：每次普通部署都必须先备份配置文件",
        source_event_ids=["evt-clean"],
        sensitivity="private",
        tags=["test"],
        bridge_state="inner_drive_candidate",
        created_at="2026-06-18T00:00:02+00:00",
    )

    result = _cluster_and_promote(
        [tainted, clean],
        store,
        set(),
        envelope_id=_VALID_ENVELOPE_ID,
        now=datetime(2026, 6, 18, tzinfo=timezone.utc),
        min_cluster_size=1,
    )

    assert result["promoted_count"] == 1
    triage = read_candidate_triage(store)
    by_id = {item["candidate_id"]: item for item in triage}
    assert by_id["cand-tainted"]["target_state"] == "owner_eligible"
    assert by_id["cand-tainted"]["reason"] == "external_evidence_tainted_blocked"
    assert by_id["cand-clean"]["target_state"] == "resolver_approved"
    assert not CrystallizedMemoryService(store).find_records_by_candidate_id("cand-tainted")


def test_fact_judge_durable_bypass_skips_tainted_candidate_without_crystallizing(tmp_path):
    store = _store_with_gate(tmp_path)
    _append_event(
        store,
        "evt-tainted",
        source_class="external_evidence",
        external_ref="external:dataset:doc:chunk",
    )
    tainted = _candidate("cand-tainted", source_event_ids=["evt-tainted"])
    verdicts_path = store.roots.memory_os_root / "system-modules" / "fact_judge" / "verdicts.jsonl"
    verdicts_path.parent.mkdir(parents=True, exist_ok=True)
    verdicts_path.write_text(
        json.dumps({"candidate_id": "cand-tainted", "durable_fact": True}, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    result = _cluster_and_promote(
        [tainted],
        store,
        set(),
        envelope_id=_VALID_ENVELOPE_ID,
        now=datetime(2026, 6, 18, tzinfo=timezone.utc),
        min_cluster_size=2,
    )

    assert result["promoted_count"] == 0
    triage = read_candidate_triage(store)
    assert triage[0]["candidate_id"] == "cand-tainted"
    assert triage[0]["target_state"] == "owner_eligible"
    assert triage[0]["reason"] == "external_evidence_tainted_blocked"
    assert not CrystallizedMemoryService(store).find_records_by_candidate_id("cand-tainted")


def test_static_hygiene_fails_when_memory_os_contains_external_provider_literal(tmp_path):
    from scripts.memory_os_static_hygiene_check import run_static_hygiene

    repo = tmp_path / "repo"
    target = repo / "plugins" / "memory" / "memory_os"
    target.mkdir(parents=True)
    (target / "bad.py").write_text("PROVIDER = 'ragflow'\n", encoding="utf-8")

    def runner(argv, cwd):
        return {"exit_code": 0, "stdout": "", "stderr": ""}

    report = run_static_hygiene(repo, runner=runner)

    assert report["checks"]["memory_os_provider_agnostic"]["status"] == "fail"
    assert report["status"] == "fail"
