from datetime import datetime, timezone

import pytest

from plugins.memory.memory_os.approval import (
    ApprovalDecision,
    ApprovalPurpose,
    approval_from_cw019_state,
)
from plugins.memory.memory_os.crystallized import (
    CrystallizedApprovalError,
    CrystallizedCandidate,
    CrystallizedMemoryService,
    append_candidate_queue,
    read_candidate_queue,
)
from plugins.memory.memory_os.fixtures import build_event
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.schema import CRYSTALLIZED_SCHEMA_VERSION, EventEnvelope
from plugins.memory.memory_os.store import MemoryOSStore


def _service(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    store = MemoryOSStore(roots)
    store.initialize()
    return CrystallizedMemoryService(store)


def _candidate() -> CrystallizedCandidate:
    event = EventEnvelope.from_dict(build_event(seed=21, profile="memoryos-test"))
    return CrystallizedCandidate(
        candidate_id="cand-cw019-001",
        kind="moment",
        body="Agent-rewritten long-term memory.",
        source_event_ids=[event.id],
        sensitivity="private",
        tags=["cw-019", "synthetic"],
        bridge_state="owner_eligible",
    )


def test_unapproved_candidate_cannot_write_crystallized_record(tmp_path):
    service = _service(tmp_path)
    candidate = _candidate()
    decision = ApprovalDecision(
        candidate_id=candidate.candidate_id,
        purpose=ApprovalPurpose.DEFER,
        reviewer="owner",
        reviewed_at="2026-05-20T08:00:00+00:00",
    )

    with pytest.raises(CrystallizedApprovalError, match="approve_for_crystallized"):
        service.write_approved_record(candidate, decision, file_name="moments.md")

    assert list(service.store.roots.crystallized_root.glob("*.md")) == []


def test_candidate_queue_round_trips_default_none_tags(tmp_path):
    service = _service(tmp_path)
    candidate = CrystallizedCandidate(
        candidate_id="cand-tags-none-001",
        kind="moment",
        body="Candidate without explicit tags.",
        source_event_ids=["evt-tags-none-001"],
    )

    append_candidate_queue(service.store, candidate)

    records = read_candidate_queue(service.store)
    assert len(records) == 1
    assert records[0].candidate_id == "cand-tags-none-001"
    assert records[0].tags == []


def test_approved_record_frontmatter_contains_approval_metadata_and_source_events(tmp_path):
    service = _service(tmp_path)
    candidate = _candidate()
    decision = ApprovalDecision(
        candidate_id=candidate.candidate_id,
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="owner",
        reviewed_at="2026-05-20T08:00:00+00:00",
        note="Approved for long-term memory.",
    )

    path = service.write_approved_record(
        candidate,
        decision,
        file_name="moments.md",
        now=datetime(2026, 5, 20, 8, 1, tzinfo=timezone.utc),
    )
    records = service.read_records("moments.md")

    assert path == service.store.roots.crystallized_root / "moments.md"
    assert len(records) == 1
    assert records[0].body == candidate.body
    frontmatter = records[0].frontmatter
    assert frontmatter["schema_version"] == CRYSTALLIZED_SCHEMA_VERSION
    assert frontmatter["candidate_id"] == candidate.candidate_id
    assert frontmatter["approved_by"] == "owner"
    assert frontmatter["approved_at"] == "2026-05-20T08:00:00+00:00"
    assert frontmatter["approval_purpose"] == "approve_for_crystallized"
    assert frontmatter["source_event_ids"] == candidate.source_event_ids
    assert frontmatter["sensitivity"] == "private"
    assert frontmatter["hindsight_indexed"] is False


def test_cw019_owner_eligible_is_preserved_but_not_upgraded_to_crystallized_approval(tmp_path):
    service = _service(tmp_path)
    candidate = _candidate()
    decision = approval_from_cw019_state(
        candidate_id=candidate.candidate_id,
        cw019_state="owner_eligible",
        reviewer="owner",
        reviewed_at="2026-05-20T08:00:00+00:00",
    )

    assert decision.purpose == ApprovalPurpose.APPROVE_FOR_VISIBILITY
    with pytest.raises(CrystallizedApprovalError, match="owner_eligible"):
        service.write_approved_record(candidate, decision, file_name="moments.md")


def test_approved_record_is_auditable_back_to_source_events(tmp_path):
    service = _service(tmp_path)
    candidate = _candidate()
    decision = ApprovalDecision(
        candidate_id=candidate.candidate_id,
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="owner",
        reviewed_at="2026-05-20T08:00:00+00:00",
    )

    service.write_approved_record(candidate, decision, file_name="moments.md")

    audit_lines = service.store.roots.audit_path.read_text(encoding="utf-8").splitlines()
    assert any("crystallized_record_written" in line for line in audit_lines)
    assert any(candidate.source_event_ids[0] in line for line in audit_lines)


def test_approval_purpose_enum_contains_required_v1_states():
    assert [purpose.value for purpose in ApprovalPurpose] == [
        "approve_for_visibility",
        "approve_for_working",
        "approve_for_crystallized",
        "reject",
        "defer",
    ]
