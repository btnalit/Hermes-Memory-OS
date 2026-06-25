from datetime import datetime, timezone

import pytest

from plugins.memory.memory_os.approval import (
    ApprovalDecision,
    ApprovalPurpose,
    approval_from_cw019_state,
)
from plugins.memory.memory_os.crystallized import (
    INACTIVE_CANONICAL_STATES,
    CrystallizedApprovalError,
    CrystallizedCandidate,
    CrystallizedMemoryService,
    append_candidate_queue,
    is_active_crystallized_frontmatter,
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


def test_inactive_canonical_states_includes_provisional_expired_and_cap_evicted():
    """INACTIVE_CANONICAL_STATES must include provisional states
    so is_active_crystallized_frontmatter returns False for them."""
    from plugins.memory.memory_os.crystallized import INACTIVE_CANONICAL_STATES, is_active_crystallized_frontmatter

    assert "provisional_expired" in INACTIVE_CANONICAL_STATES
    assert "provisional_cap_evicted" in INACTIVE_CANONICAL_STATES

    # Active records still pass
    assert is_active_crystallized_frontmatter({"canonical_state": "active"}) is True
    assert is_active_crystallized_frontmatter({}) is True  # default=active

    # Provisional expired/evicted are inactive
    assert is_active_crystallized_frontmatter({"canonical_state": "provisional_expired"}) is False
    assert is_active_crystallized_frontmatter({"canonical_state": "provisional_cap_evicted"}) is False

    # Existing inactive states still work
    assert is_active_crystallized_frontmatter({"canonical_state": "owner_revoked"}) is False
    assert is_active_crystallized_frontmatter({"canonical_state": "demoted"}) is False


def test_write_approved_record_with_provisional_true_adds_provisional_frontmatter_keys(tmp_path):
    """When decision.provisional=True, frontmatter must include
    provisional, expires_at, and recurrence keys."""
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
    from plugins.memory.memory_os.crystallized import CrystallizedCandidate, CrystallizedMemoryService
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="test")
    store = MemoryOSStore(roots)
    store.initialize()

    candidate = CrystallizedCandidate(
        candidate_id="cand_prov_001",
        kind="fact",  # non-moment: uses caller-supplied TTL unchanged
        body="User mentioned liking rainy days.",
        source_event_ids=["evt_001"],
        sensitivity="private",
        bridge_state="inner_drive_candidate",
    )
    decision = ApprovalDecision(
        candidate_id="cand_prov_001",
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="resolver",
        reviewed_at="2026-06-17T00:00:00Z",
        note="auto-approved",
        source_state="resolver_approved",
        provisional=True,
        expires_at="2026-06-24T00:00:00Z",
        recurrence=0,
    )
    service = CrystallizedMemoryService(store)
    path = service.write_approved_record(candidate, decision, file_name="owner_approved.md")

    records = service.read_records("owner_approved.md")
    assert len(records) == 1
    fm = records[0].frontmatter
    assert fm["provisional"] is True
    assert fm["expires_at"] == "2026-06-24T00:00:00Z"
    assert fm["recurrence"] == "0"
    assert fm["approved_by"] == "resolver"
    assert fm["bridge_state"] == "inner_drive_candidate"


def test_write_approved_record_with_provisional_false_does_not_add_provisional_keys(tmp_path):
    """When decision.provisional=False (default), frontmatter must NOT
    include provisional/expires_at/recurrence keys."""
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
    from plugins.memory.memory_os.crystallized import CrystallizedCandidate, CrystallizedMemoryService
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="test")
    store = MemoryOSStore(roots)
    store.initialize()

    candidate = CrystallizedCandidate(
        candidate_id="cand_normal_001",
        kind="moment",
        body="User mentioned liking rainy days.",
        source_event_ids=["evt_001"],
        sensitivity="private",
    )
    decision = ApprovalDecision(
        candidate_id="cand_normal_001",
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="owner",
        reviewed_at="2026-06-17T00:00:00Z",
        provisional=False,
    )
    service = CrystallizedMemoryService(store)
    path = service.write_approved_record(candidate, decision, file_name="owner_approved.md")

    records = service.read_records("owner_approved.md")
    assert len(records) == 1
    fm = records[0].frontmatter
    assert "provisional" not in fm
    assert "expires_at" not in fm
    assert "recurrence" not in fm


def test_invalidate_provisional_record_sets_canonical_state_and_preserves_record(tmp_path):
    """invalidate_provisional_record must set canonical_state to
    provisional_expired/provisional_cap_evicted, add audit, keep record on disk."""
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
    from plugins.memory.memory_os.crystallized import (
        CrystallizedCandidate, CrystallizedMemoryService,
        is_active_crystallized_frontmatter,
    )
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="test")
    store = MemoryOSStore(roots)
    store.initialize()

    # First write a provisional record
    candidate = CrystallizedCandidate(
        candidate_id="cand_inv_001",
        kind="fact",  # non-moment: uses caller-supplied TTL unchanged
        body="Temporary memory that will expire.",
        source_event_ids=["evt_001"],
        sensitivity="private",
        bridge_state="inner_drive_candidate",
    )
    decision = ApprovalDecision(
        candidate_id="cand_inv_001",
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="resolver",
        reviewed_at="2026-06-17T00:00:00Z",
        source_state="resolver_approved",
        provisional=True,
        expires_at="2026-06-24T00:00:00Z",
    )
    service = CrystallizedMemoryService(store)
    path = service.write_approved_record(candidate, decision, file_name="owner_approved.md")
    records = service.read_records("owner_approved.md")
    record_id = records[0].frontmatter["id"]

    # Now invalidate it
    result = service.invalidate_provisional_record(
        record_id,
        reason="resolver_ttl_expired",
        invalidated_by="provisional_sweep",
    )
    assert result["record_id"] == record_id
    assert result["canonical_state_changed"] is True

    # Re-read - canonical_state should be changed
    records_after = service.read_records("owner_approved.md")
    fm_after = records_after[0].frontmatter
    assert fm_after["canonical_state"] == "provisional_expired"
    assert fm_after["provisional"] is True  # preserved
    assert fm_after["expires_at"] == "2026-06-24T00:00:00Z"  # preserved
    assert is_active_crystallized_frontmatter(fm_after) is False

    # Record still exists on disk (invalidate != delete)
    assert path.exists()


def test_invalidate_provisional_record_fails_for_nonexistent_record(tmp_path):
    """Invalidating a non-existent record should raise KeyError."""
    from plugins.memory.memory_os.crystallized import CrystallizedMemoryService
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="test")
    store = MemoryOSStore(roots)
    store.initialize()

    service = CrystallizedMemoryService(store)
    import pytest
    with pytest.raises(KeyError):
        service.invalidate_provisional_record(
            "nonexistent_id",
            reason="resolver_ttl_expired",
        )


def test_confirm_provisional_record_removes_provisional_and_expires_at(tmp_path):
    """confirm_provisional_record must set provisional=False, clear expires_at,
    set confirmed_at/confirmed_by, restore canonical_state=active."""
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
    from plugins.memory.memory_os.crystallized import CrystallizedCandidate, CrystallizedMemoryService
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="test")
    store = MemoryOSStore(roots)
    store.initialize()

    candidate = CrystallizedCandidate(
        candidate_id="cand_conf_001",
        kind="moment",
        body="User preference: dark mode enabled.",
        source_event_ids=["evt_001"],
        sensitivity="private",
        bridge_state="inner_drive_candidate",
    )
    decision = ApprovalDecision(
        candidate_id="cand_conf_001",
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="resolver",
        reviewed_at="2026-06-17T00:00:00Z",
        source_state="resolver_approved",
        provisional=True,
        expires_at="2026-06-24T00:00:00Z",
    )
    service = CrystallizedMemoryService(store)
    service.write_approved_record(candidate, decision, file_name="owner_approved.md")
    records = service.read_records("owner_approved.md")
    record_id = records[0].frontmatter["id"]

    result = service.confirm_provisional_record(record_id, confirmed_by="owner")
    assert result["record_id"] == record_id
    assert result["canonical_state_changed"] is True

    records_after = service.read_records("owner_approved.md")
    fm = records_after[0].frontmatter
    assert fm.get("provisional") is False
    assert fm.get("expires_at") is None or fm.get("expires_at") == ""
    assert fm.get("confirmed_by") == "owner"
    assert fm.get("confirmed_at") is not None


def test_list_provisional_records_filters_active_provisional_only(tmp_path):
    """list_provisional_records must return only active provisional records,
    excluding non-provisional and expired/evicted ones."""
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
    from plugins.memory.memory_os.crystallized import CrystallizedCandidate, CrystallizedMemoryService
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="test")
    store = MemoryOSStore(roots)
    store.initialize()
    service = CrystallizedMemoryService(store)

    # Write a provisional record
    candidate = CrystallizedCandidate(
        candidate_id="cand_list_001",
        kind="moment",
        body="Active provisional memory.",
        source_event_ids=["evt_001"],
        sensitivity="private",
    )
    decision = ApprovalDecision(
        candidate_id="cand_list_001",
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="resolver",
        reviewed_at="2026-06-17T00:00:00Z",
        source_state="resolver_approved",
        provisional=True,
        expires_at="2026-06-24T00:00:00Z",
    )
    service.write_approved_record(candidate, decision, file_name="owner_approved.md")

    # Write a non-provisional record
    candidate2 = CrystallizedCandidate(
        candidate_id="cand_list_002",
        kind="moment",
        body="Permanent owner-approved memory.",
        source_event_ids=["evt_002"],
        sensitivity="private",
    )
    decision2 = ApprovalDecision(
        candidate_id="cand_list_002",
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="owner",
        reviewed_at="2026-06-17T00:00:00Z",
        provisional=False,
    )
    service.write_approved_record(candidate2, decision2, file_name="owner_approved.md")

    results = service.list_provisional_records()
    assert len(results) == 1
    assert results[0]["provisional"] is True
    assert results[0]["candidate_id"] == "cand_list_001"
