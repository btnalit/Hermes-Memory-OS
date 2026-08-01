from datetime import datetime, timedelta, timezone
import threading

import pytest

from plugins.memory.memory_os.audit import read_audit_entries
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


def test_approved_write_waits_for_canonical_transition_lock(tmp_path, monkeypatch):
    """A revoke read/replace must not race an append and discard that append."""
    service = _service(tmp_path)
    first = _candidate()
    first_decision = ApprovalDecision(
        candidate_id=first.candidate_id,
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="owner",
        reviewed_at="2026-05-20T08:00:00+00:00",
    )
    service.write_approved_record(first, first_decision, file_name="moments.md")
    first_id = service.read_records("moments.md")[0].frontmatter["id"]

    second = CrystallizedCandidate(
        candidate_id="cand-concurrent-append-002",
        kind="moment",
        body="A second owner-approved record written during a revoke.",
        source_event_ids=["evt-concurrent-append-002"],
    )
    second_decision = ApprovalDecision(
        candidate_id=second.candidate_id,
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="owner",
        reviewed_at="2026-05-20T08:02:00+00:00",
    )

    revoke_reader_entered = threading.Event()
    release_revoke = threading.Event()
    append_attempted = threading.Event()
    append_entered = threading.Event()
    failures: list[BaseException] = []
    original_read_records = service.read_records
    original_append = service.store.append_crystallized_record

    def paused_read_records(file_name: str):
        records = original_read_records(file_name)
        revoke_reader_entered.set()
        if not release_revoke.wait(timeout=5):
            raise AssertionError("timed out waiting to release revoke")
        return records

    def observed_append(*args, **kwargs):
        append_entered.set()
        return original_append(*args, **kwargs)

    monkeypatch.setattr(service, "read_records", paused_read_records)
    monkeypatch.setattr(service.store, "append_crystallized_record", observed_append)

    def revoke_target() -> None:
        try:
            service.revoke_record(
                str(first_id), revoked_by="owner", reason="concurrency regression"
            )
        except BaseException as exc:  # surfaced after both threads join
            failures.append(exc)

    def append_second() -> None:
        try:
            append_attempted.set()
            service.write_approved_record(
                second, second_decision, file_name="moments.md"
            )
        except BaseException as exc:  # surfaced after both threads join
            failures.append(exc)

    revoke_thread = threading.Thread(target=revoke_target)
    append_thread = threading.Thread(target=append_second)
    revoke_thread.start()
    assert revoke_reader_entered.wait(timeout=5)
    append_thread.start()
    assert append_attempted.wait(timeout=5)
    append_raced_transition = append_entered.wait(timeout=0.5)
    release_revoke.set()
    revoke_thread.join(timeout=5)
    append_thread.join(timeout=5)

    assert not revoke_thread.is_alive()
    assert not append_thread.is_alive()
    assert failures == []
    assert append_raced_transition is False
    assert append_entered.is_set()
    assert {record.frontmatter["candidate_id"] for record in original_read_records("moments.md")} == {
        first.candidate_id,
        second.candidate_id,
    }


def test_revoke_holds_edge_lock_across_read_modify_write(tmp_path, monkeypatch):
    """A concurrent governed edge append must survive revoke invalidation."""
    service = _service(tmp_path)
    candidate = _candidate()
    decision = ApprovalDecision(
        candidate_id=candidate.candidate_id,
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="owner",
        reviewed_at="2026-05-20T08:00:00+00:00",
    )
    service.write_approved_record(candidate, decision, file_name="moments.md")
    record_id = str(service.read_records("moments.md")[0].frontmatter["id"])

    from plugins.memory.memory_os import jsonl_io

    edges_path = service.store.roots.memory_os_root / "graph" / "edges.jsonl"
    initial_edge = {
        "edge_id": "edge-revoke-initial",
        "from_record_id": record_id,
        "to_record_id": "other-record",
        "state": "active",
    }
    late_edge = {
        "edge_id": "edge-concurrent-late",
        "from_record_id": "late-a",
        "to_record_id": "late-b",
        "state": "candidate",
    }
    jsonl_io.append_jsonl_locked(edges_path, initial_edge)

    edge_read_entered = threading.Event()
    release_revoke = threading.Event()
    late_append_attempted = threading.Event()
    late_append_entered = threading.Event()
    failures: list[BaseException] = []
    original_read_jsonl = jsonl_io.read_jsonl
    original_append_under_lock = jsonl_io._append_line_under_lock

    def paused_read_jsonl(path, *args, **kwargs):
        records = original_read_jsonl(path, *args, **kwargs)
        if str(path) == str(edges_path):
            edge_read_entered.set()
            if not release_revoke.wait(timeout=5):
                raise AssertionError("timed out waiting to release edge rewrite")
        return records

    def observed_append_under_lock(target, line, **kwargs):
        if target == edges_path and "edge-concurrent-late" in line:
            late_append_entered.set()
        return original_append_under_lock(target, line, **kwargs)

    monkeypatch.setattr(jsonl_io, "read_jsonl", paused_read_jsonl)
    monkeypatch.setattr(jsonl_io, "_append_line_under_lock", observed_append_under_lock)

    def revoke_target() -> None:
        try:
            service.revoke_record(
                record_id, revoked_by="owner", reason="edge-lock regression"
            )
        except BaseException as exc:
            failures.append(exc)

    def append_late_edge() -> None:
        try:
            late_append_attempted.set()
            jsonl_io.append_jsonl_locked(edges_path, late_edge)
        except BaseException as exc:
            failures.append(exc)

    revoke_thread = threading.Thread(target=revoke_target)
    append_thread = threading.Thread(target=append_late_edge)
    revoke_thread.start()
    assert edge_read_entered.wait(timeout=5)
    append_thread.start()
    assert late_append_attempted.wait(timeout=5)
    append_raced_rewrite = late_append_entered.wait(timeout=0.5)
    release_revoke.set()
    revoke_thread.join(timeout=5)
    append_thread.join(timeout=5)

    assert not revoke_thread.is_alive()
    assert not append_thread.is_alive()
    assert failures == []
    assert append_raced_rewrite is False
    assert late_append_entered.is_set()
    final_edges = original_read_jsonl(edges_path)
    assert {edge["edge_id"] for edge in final_edges} == {
        "edge-revoke-initial",
        "edge-concurrent-late",
    }
    assert final_edges[0]["state"] == "invalidated"


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

    audit_entries = read_audit_entries(service.store.roots.audit_path)
    assert any(entry["action"] == "crystallized_record_written" for entry in audit_entries)
    assert any(candidate.source_event_ids[0] in str(entry) for entry in audit_entries)


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

    from plugins.memory.memory_os.permanent_promotion import PermanentPromotionService
    issued = PermanentPromotionService(store).propose(record_id, channel="cli")
    result = PermanentPromotionService(store).approve(issued["token"])
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


# ── S-series: Auto-promotion (passive trust) ─────────────────────────────

class TestAutoPromoteProvisionalRecords:
    """S.1-S.3 + T.1-T.2: Passive trust auto-promotion tests."""

    def test_s1_auto_promote_old_enough_record(self, tmp_path):
        """S.1: provisional aged ≥ min_age_days → auto-promoted to permanent."""
        from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
        from plugins.memory.memory_os.crystallized import (
            CrystallizedCandidate, CrystallizedMemoryService,
        )
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore

        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="test")
        store = MemoryOSStore(roots)
        store.initialize()
        now = datetime.now(timezone.utc)

        # Write a provisional record approved 10 days ago (≥ default 7-day min_age)
        candidate = CrystallizedCandidate(
            candidate_id="cand_auto_001",
            kind="fact",
            body="This is a well-aged provisional record.",
            source_event_ids=["evt_001"],
            sensitivity="private",
            bridge_state="inner_drive_candidate",
        )
        approved_at = (now - timedelta(days=10)).isoformat()
        decision = ApprovalDecision(
            candidate_id="cand_auto_001",
            purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
            reviewer="resolver",
            reviewed_at=approved_at,
            source_state="resolver_approved",
            provisional=True,
            expires_at=(now + timedelta(days=30)).isoformat(),
        )
        service = CrystallizedMemoryService(store)
        service.write_approved_record(candidate, decision, file_name="owner_approved.md")

        # Verify it's provisional before promotion
        assert len(service.list_provisional_records()) == 1

        # Run auto-promotion
        result = service.auto_promote_provisional_records(now=now)
        assert result["status"] == "ok"
        assert result["eligible_count"] == 1
        assert result["promoted_count"] == 0

        # V2-0 leaves it provisional until an owner-issued proposal/token action.
        assert len(service.list_provisional_records()) == 1

    def test_s1_too_young_not_promoted(self, tmp_path):
        """S.1: provisional younger than min_age → not promoted."""
        from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
        from plugins.memory.memory_os.crystallized import (
            CrystallizedCandidate, CrystallizedMemoryService,
        )
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore

        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="test")
        store = MemoryOSStore(roots)
        store.initialize()
        now = datetime.now(timezone.utc)

        candidate = CrystallizedCandidate(
            candidate_id="cand_young_001",
            kind="fact",
            body="This is a very recent provisional record.",
            source_event_ids=["evt_001"],
            sensitivity="private",
            bridge_state="inner_drive_candidate",
        )
        approved_at = (now - timedelta(days=1)).isoformat()  # only 1 day old
        decision = ApprovalDecision(
            candidate_id="cand_young_001",
            purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
            reviewer="resolver",
            reviewed_at=approved_at,
            source_state="resolver_approved",
            provisional=True,
            expires_at=(now + timedelta(days=30)).isoformat(),
        )
        service = CrystallizedMemoryService(store)
        service.write_approved_record(candidate, decision, file_name="owner_approved.md")

        result = service.auto_promote_provisional_records(now=now)
        assert result["eligible_count"] == 0
        assert result["promoted_count"] == 0
        assert result["skipped_too_young_count"] == 1

        # Still provisional
        assert len(service.list_provisional_records()) == 1

    def test_s2_owner_rejected_not_promoted(self, tmp_path):
        """S.2: owner-rejected records → invisible to list_provisional, never promoted.

        After owner rejection, the canonical_state becomes provisional_rejected,
        which is in INACTIVE_CANONICAL_STATES. list_provisional_records()
        excludes it, so auto_promote never even sees it.
        """
        from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
        from plugins.memory.memory_os.crystallized import (
            CrystallizedCandidate, CrystallizedMemoryService,
        )
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore

        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="test")
        store = MemoryOSStore(roots)
        store.initialize()
        now = datetime.now(timezone.utc)

        candidate = CrystallizedCandidate(
            candidate_id="cand_rejected_001",
            kind="fact",
            body="This record was rejected by owner.",
            source_event_ids=["evt_001"],
            sensitivity="private",
            bridge_state="inner_drive_candidate",
        )
        approved_at = (now - timedelta(days=10)).isoformat()
        decision = ApprovalDecision(
            candidate_id="cand_rejected_001",
            purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
            reviewer="resolver",
            reviewed_at=approved_at,
            source_state="resolver_approved",
            provisional=True,
            expires_at=(now + timedelta(days=30)).isoformat(),
        )
        service = CrystallizedMemoryService(store)
        service.write_approved_record(candidate, decision, file_name="owner_approved.md")

        # Mark as rejected by owner
        records = service.read_records("owner_approved.md")
        record_id = records[0].frontmatter["id"]
        service.invalidate_provisional_record(
            record_id,
            reason="owner_rejected",
            invalidated_by="owner",
        )

        # Rejected record is no longer in list_provisional_records
        assert len(service.list_provisional_records()) == 0

        # Auto-promotion sees nothing to promote
        result = service.auto_promote_provisional_records(now=now)
        assert result["eligible_count"] == 0
        assert result["promoted_count"] == 0

    def test_s3_knob_disabled_no_promotion(self, tmp_path):
        """S.3: auto_promote_enabled=False → no promotion."""
        from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
        from plugins.memory.memory_os.crystallized import (
            CrystallizedCandidate, CrystallizedMemoryService,
        )
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore

        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="test")
        store = MemoryOSStore(roots)
        store.initialize()
        now = datetime.now(timezone.utc)

        # Register override to disable auto-promotion
        from plugins.memory.memory_os.knob_overrides import register_override

        register_override(
            "auto_promote_enabled", False, prior=True,
            proposed_by="test", approved_via="resolver",
            expires_at=(now + timedelta(days=7)).isoformat(),
            _now=now, _store_root=tmp_path,
        )

        candidate = CrystallizedCandidate(
            candidate_id="cand_knob_off_001",
            kind="fact",
            body="Should not be promoted when knob is off.",
            source_event_ids=["evt_001"],
            sensitivity="private",
            bridge_state="inner_drive_candidate",
        )
        approved_at = (now - timedelta(days=10)).isoformat()
        decision = ApprovalDecision(
            candidate_id="cand_knob_off_001",
            purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
            reviewer="resolver",
            reviewed_at=approved_at,
            source_state="resolver_approved",
            provisional=True,
            expires_at=(now + timedelta(days=30)).isoformat(),
        )
        service = CrystallizedMemoryService(store)
        service.write_approved_record(candidate, decision, file_name="owner_approved.md")

        with pytest.warns(DeprecationWarning, match="auto_promote_enabled"):
            result = service.auto_promote_provisional_records(now=now, _store_root=tmp_path)
        assert result["status"] == "disabled"
        assert result["promoted_count"] == 0

        # Still provisional
        assert len(service.list_provisional_records()) == 1

    def test_dry_run_counts_but_does_not_promote(self, tmp_path):
        """dry_run=True counts eligible but does not promote."""
        from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
        from plugins.memory.memory_os.crystallized import (
            CrystallizedCandidate, CrystallizedMemoryService,
        )
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore

        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="test")
        store = MemoryOSStore(roots)
        store.initialize()
        now = datetime.now(timezone.utc)

        candidate = CrystallizedCandidate(
            candidate_id="cand_dry_001",
            kind="fact",
            body="Dry run test record.",
            source_event_ids=["evt_001"],
            sensitivity="private",
            bridge_state="inner_drive_candidate",
        )
        approved_at = (now - timedelta(days=10)).isoformat()
        decision = ApprovalDecision(
            candidate_id="cand_dry_001",
            purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
            reviewer="resolver",
            reviewed_at=approved_at,
            source_state="resolver_approved",
            provisional=True,
            expires_at=(now + timedelta(days=30)).isoformat(),
        )
        service = CrystallizedMemoryService(store)
        service.write_approved_record(candidate, decision, file_name="owner_approved.md")

        result = service.auto_promote_provisional_records(now=now, dry_run=True)
        assert result["eligible_count"] == 1
        assert result["promoted_count"] == 0
        assert result["dry_run"] is True

        # Record still provisional
        assert len(service.list_provisional_records()) == 1

    def test_multiple_records_mixed_ages(self, tmp_path):
        """Mix of old, young, and rejected records — correct counts."""
        from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
        from plugins.memory.memory_os.crystallized import (
            CrystallizedCandidate, CrystallizedMemoryService,
        )
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore

        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="test")
        store = MemoryOSStore(roots)
        store.initialize()
        now = datetime.now(timezone.utc)
        service = CrystallizedMemoryService(store)

        # Old record (≥7 days)
        c1 = CrystallizedCandidate(
            candidate_id="cand_old",
            kind="fact", body="Old record.",
            source_event_ids=["evt_1"], sensitivity="private",
            bridge_state="inner_drive_candidate",
        )
        d1 = ApprovalDecision(
            candidate_id="cand_old",
            purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
            reviewer="resolver",
            reviewed_at=(now - timedelta(days=10)).isoformat(),
            source_state="resolver_approved", provisional=True,
            expires_at=(now + timedelta(days=30)).isoformat(),
        )
        service.write_approved_record(c1, d1, file_name="owner_approved.md")

        # Young record (<7 days)
        c2 = CrystallizedCandidate(
            candidate_id="cand_young",
            kind="fact", body="Young record.",
            source_event_ids=["evt_2"], sensitivity="private",
            bridge_state="inner_drive_candidate",
        )
        d2 = ApprovalDecision(
            candidate_id="cand_young",
            purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
            reviewer="resolver",
            reviewed_at=(now - timedelta(days=2)).isoformat(),
            source_state="resolver_approved", provisional=True,
            expires_at=(now + timedelta(days=30)).isoformat(),
        )
        service.write_approved_record(c2, d2, file_name="owner_approved.md")

        result = service.auto_promote_provisional_records(now=now)
        assert result["eligible_count"] == 1
        assert result["promoted_count"] == 0
        assert result["skipped_too_young_count"] == 1

        # Both remain until an owner action approves a proposal.
        assert len(service.list_provisional_records()) == 2


# ── S.X: Adversarial verification ────────────────────────────────────────

class TestAutoPromoteAdversarial:
    """S.X: Removing auto-promotion logic MUST cause S.1 to fail."""

    def test_sx_old_record_stays_provisional_without_promotion(self, tmp_path):
        """S.X: Without auto-promotion, old provisional stays provisional.

        This is the adversarial counterpart to S.1 — proves S.1 tests
        the actual promotion logic, not just the passage of time.
        """
        from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
        from plugins.memory.memory_os.crystallized import (
            CrystallizedCandidate, CrystallizedMemoryService,
        )
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore

        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="test")
        store = MemoryOSStore(roots)
        store.initialize()
        now = datetime.now(timezone.utc)

        candidate = CrystallizedCandidate(
            candidate_id="cand_adversarial",
            kind="fact",
            body="Old record without auto-promotion.",
            source_event_ids=["evt_001"],
            sensitivity="private",
            bridge_state="inner_drive_candidate",
        )
        approved_at = (now - timedelta(days=10)).isoformat()
        decision = ApprovalDecision(
            candidate_id="cand_adversarial",
            purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
            reviewer="resolver",
            reviewed_at=approved_at,
            source_state="resolver_approved",
            provisional=True,
            expires_at=(now + timedelta(days=30)).isoformat(),
        )
        service = CrystallizedMemoryService(store)
        service.write_approved_record(candidate, decision, file_name="owner_approved.md")

        # Without calling auto_promote, record stays provisional
        assert len(service.list_provisional_records()) == 1

        # Compatibility wrapper is non-mutating in V2-0.
        result = service.auto_promote_provisional_records(now=now)
        assert result["promoted_count"] == 0
        assert len(service.list_provisional_records()) == 1


# ── Write-time candidate_id idempotency guard ────────────────────────────────
# Regression tests for duplicate-candidate rows: append_candidate_queue must
# never append a second physical row for an id that already exists.


def test_append_candidate_queue_dedups_same_id(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    store = MemoryOSStore(roots)
    store.initialize()

    cand = CrystallizedCandidate(
        candidate_id="cand-dedup-001",
        kind="moment",
        body="first write",
        source_event_ids=["evt-dedup-1"],
        sensitivity="private",
        bridge_state="owner_eligible",
    )
    append_candidate_queue(store, cand)
    # Re-processing the same event (as inner_drive did during config boot) must not add a 2nd row.
    append_candidate_queue(store, cand)

    queued = read_candidate_queue(store)
    assert len(queued) == 1, f"expected exactly 1 row, got {len(queued)}"
    assert queued[0].candidate_id == "cand-dedup-001"


def test_append_candidate_queue_allows_distinct_ids(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    store = MemoryOSStore(roots)
    store.initialize()

    for i in range(5):
        append_candidate_queue(
            store,
            CrystallizedCandidate(
                candidate_id=f"cand-distinct-{i}",
                kind="moment",
                body=f"body {i}",
                source_event_ids=[f"evt-distinct-{i}"],
                sensitivity="private",
                bridge_state="owner_eligible",
            ),
        )
    assert len(read_candidate_queue(store)) == 5


def test_append_candidate_queue_emits_dedup_audit_on_skip(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    store = MemoryOSStore(roots)
    store.initialize()

    cand = CrystallizedCandidate(
        candidate_id="cand-dedup-audit",
        kind="moment",
        body="dup body",
        source_event_ids=["evt-dedup-audit"],
        sensitivity="private",
        bridge_state="owner_eligible",
    )
    append_candidate_queue(store, cand)
    append_candidate_queue(store, cand)

    actions = [
        e.get("action")
        for e in read_audit_entries(store.roots.audit_path)
    ]
    assert actions.count("crystallized_candidate_queued") == 1
    assert "crystallized_candidate_dedup_skipped" in actions


def test_index_and_queue_counts_converge_after_dedup_guard(tmp_path):
    """Status over-count (139 vs 132) must not recur: index PK REPLACE and the
    write-time guard both agree on distinct candidate_id count."""
    import sqlite3

    from plugins.memory.memory_os.index import MemoryOSIndex

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    store = MemoryOSStore(roots)
    store.initialize()

    cand = CrystallizedCandidate(
        candidate_id="cand-converge-1",
        kind="moment",
        body="converge",
        source_event_ids=["evt-converge-1"],
        sensitivity="private",
        bridge_state="owner_eligible",
    )
    append_candidate_queue(store, cand)
    append_candidate_queue(store, cand)  # would have been the 2nd dup row pre-fix

    queue_count = len(read_candidate_queue(store))
    index_count = MemoryOSIndex(roots).counts().get("crystallized_candidates", 0)
    # index table may be empty pre-build; build it to verify PK dedup matches.
    MemoryOSIndex(roots).try_rebuild_from_store(store)
    index_count = MemoryOSIndex(roots).counts().get("crystallized_candidates", 0)
    assert queue_count == 1
    assert index_count == 1


# ── Fix 3: candidate_aggregation status persistence ────────────────────────


def test_write_then_read_candidate_aggregation_status(tmp_path):
    store = _service(tmp_path).store
    from plugins.memory.memory_os.crystallized import (
        latest_candidate_aggregation_status,
        read_candidate_aggregation_status,
        write_candidate_aggregation_status,
    )

    summary = {
        "candidates_read": 12,
        "pending": 3,
        "already_triaged": 9,
        "promoted_count": 2,
        "rejected_demoted_count": 1,
        "demoted_count": 1,
        "fleeting_count": 4,
        "compacted_count": 5,
    }
    # No envelope → operator exemption path (mirrors append_candidate_triage)
    write_candidate_aggregation_status(store, summary=summary)

    latest = latest_candidate_aggregation_status(store)
    assert latest is not None
    assert latest["promoted_count"] == 2
    assert latest["compacted_count"] == 5
    assert latest["fleeting_count"] == 4
    assert "structural_write_governance" in latest

    all_records = read_candidate_aggregation_status(store)
    assert len(all_records) == 1


def test_candidate_aggregation_status_unavailable_returns_none(tmp_path):
    store = _service(tmp_path).store
    from plugins.memory.memory_os.crystallized import (
        latest_candidate_aggregation_status,
    )

    assert latest_candidate_aggregation_status(store) is None


# ── Task 5: permanent-promotion eligibility (V2-0 migration) ──────────────
# collect_permanent_promotion_eligibility() replaces the silent age-based
# auto-promote write path with a non-mutating, owner-facing eligibility
# report. It must never write permanent state and must expose a derived
# `legacy_auto_promoted` projection without rewriting canonical frontmatter.


def _build_aged_provisional(service, *, candidate_id, days_old, now,
                            file_name="owner_approved.md"):
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
    from plugins.memory.memory_os.crystallized import CrystallizedCandidate

    candidate = CrystallizedCandidate(
        candidate_id=candidate_id,
        kind="fact",
        body=f"Aged provisional record {candidate_id}.",
        source_event_ids=[f"evt_{candidate_id}"],
        sensitivity="private",
        bridge_state="inner_drive_candidate",
    )
    decision = ApprovalDecision(
        candidate_id=candidate_id,
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="resolver",
        reviewed_at=(now - timedelta(days=days_old)).isoformat(),
        source_state="resolver_approved",
        provisional=True,
        expires_at=(now + timedelta(days=30)).isoformat(),
    )
    service.write_approved_record(candidate, decision, file_name=file_name)


def _eligibility_service(tmp_path):
    from plugins.memory.memory_os.crystallized import CrystallizedMemoryService
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="test")
    store = MemoryOSStore(roots)
    store.initialize()
    return CrystallizedMemoryService(store)


def test_legacy_auto_promote_never_writes_permanent_even_when_old(tmp_path):
    service = _eligibility_service(tmp_path)
    now = datetime.now(timezone.utc)
    _build_aged_provisional(service, candidate_id="cand_old30", days_old=30, now=now)

    report = service.collect_permanent_promotion_eligibility(now=now)

    assert report["promoted_count"] == 0
    assert report["eligible_count"] == 1
    # Record must be untouched: still provisional, no permanent rewrite.
    assert len(service.list_provisional_records()) == 1
    records = service.read_records("owner_approved.md")
    assert records[0].frontmatter["provisional"] is True


def test_migration_snapshot_lists_all_previously_age_eligible_records(tmp_path):
    service = _eligibility_service(tmp_path)
    now = datetime.now(timezone.utc)
    _build_aged_provisional(service, candidate_id="cand_a", days_old=20, now=now)
    _build_aged_provisional(service, candidate_id="cand_b", days_old=10, now=now)
    _build_aged_provisional(service, candidate_id="cand_young", days_old=1, now=now)

    report = service.collect_permanent_promotion_eligibility(now=now)

    eligible_ids = {e["candidate_id"] for e in report["eligible_records"]}
    assert eligible_ids == {"cand_a", "cand_b"}
    assert report["eligible_count"] == 2
    assert all(e["projection"] == "legacy_auto_promoted" for e in report["eligible_records"])


def test_migration_marks_legacy_auto_promoted_projection_without_rewriting_frontmatter(tmp_path):
    service = _eligibility_service(tmp_path)
    now = datetime.now(timezone.utc)
    _build_aged_provisional(service, candidate_id="cand_proj", days_old=15, now=now)

    report = service.collect_permanent_promotion_eligibility(now=now)

    assert report["eligible_records"][0]["projection"] == "legacy_auto_promoted"
    # Projection is derived-only: canonical frontmatter must NOT carry it.
    records = service.read_records("owner_approved.md")
    fm = records[0].frontmatter
    assert "legacy_auto_promoted" not in fm
    assert fm.get("canonical_state", "") != "legacy_auto_promoted"
    assert fm["provisional"] is True


def test_old_override_keys_warn_and_are_migrated_to_new_keys(tmp_path):
    from plugins.memory.memory_os.knob_overrides import register_override

    service = _eligibility_service(tmp_path)
    now = datetime.now(timezone.utc)
    _build_aged_provisional(service, candidate_id="cand_knob", days_old=15, now=now)

    # Legacy key must still be honored (migrated to the new key) but warn.
    register_override(
        "auto_promote_enabled", False, prior=True,
        proposed_by="test", approved_via="resolver",
        expires_at=(now + timedelta(days=7)).isoformat(),
        _now=now, _store_root=tmp_path,
    )
    with pytest.warns(DeprecationWarning):
        report = service.collect_permanent_promotion_eligibility(
            now=now, _store_root=tmp_path,
        )
    assert report["status"] == "disabled"
    assert report["promoted_count"] == 0


def test_new_permanent_proposal_key_wins_over_legacy_alias(tmp_path):
    from plugins.memory.memory_os.knob_overrides import register_override

    service = _eligibility_service(tmp_path)
    now = datetime.now(timezone.utc)
    _build_aged_provisional(service, candidate_id="cand_new_wins", days_old=15, now=now)

    # Legacy alias says disabled, new key says enabled → new key wins, no warn needed.
    register_override(
        "auto_promote_enabled", False, prior=True,
        proposed_by="test", approved_via="resolver",
        expires_at=(now + timedelta(days=7)).isoformat(),
        _now=now, _store_root=tmp_path,
    )
    register_override(
        "permanent_proposal_enabled", True, prior=False,
        proposed_by="test", approved_via="resolver",
        expires_at=(now + timedelta(days=7)).isoformat(),
        _now=now, _store_root=tmp_path,
    )
    report = service.collect_permanent_promotion_eligibility(now=now, _store_root=tmp_path)
    assert report["status"] == "ok"
    assert report["eligible_count"] == 1
