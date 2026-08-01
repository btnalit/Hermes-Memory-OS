"""Tests for approve_external_evidence owner action — P2.3."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from plugins.memory.memory_os.crystallized import (
    CrystallizedApprovalError,
    CrystallizedCandidate,
    CrystallizedMemoryService,
    append_candidate_queue,
    read_candidate_queue,
)
from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
from plugins.memory.memory_os.config import save_config
from plugins.memory.memory_os.external_intake import external_intake
from plugins.memory.memory_os.owner_actions import (
    apply_owner_action,
    parse_owner_review_reply,
    render_owner_review_digest,
)
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore


# ── Helpers ──────────────────────────────────────────────────────────────


def _store(tmp_path) -> MemoryOSStore:
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def _create_tainted_candidate(
    store: MemoryOSStore,
    *,
    candidate_id: str,
    content: str,
    external_ref: str,
    provider: str = "test_provider",
) -> tuple[str, CrystallizedCandidate]:
    """Create a tainted event and appends a candidate referencing it.
    Returns (event_id, candidate)."""
    event_id = external_intake(
        store,
        content=content,
        external_ref=external_ref,
        provider=provider,
    )
    candidate = CrystallizedCandidate(
        candidate_id=candidate_id,
        kind="moment",
        body=content,
        source_event_ids=[event_id],
        sensitivity="private",
        tags=["test", "external-evidence"],
        bridge_state="inner_drive_candidate",
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    append_candidate_queue(store, candidate)
    return event_id, candidate


def _approve_external_via_recorded_digest(
    store: MemoryOSStore,
    candidate_id: str,
    *,
    owner_id: str = "test-owner",
) -> dict:
    channel = "telegram"
    save_config(
        {
            "owner_review": {
                "enabled": True,
                "actions_enabled": True,
                "recurring_delivery_enabled": True,
                "recurring_delivery_mode": "hermes_cron",
                "recurring_delivery_channel": channel,
                "recurring_delivery_target_class": "owner_home",
            }
        },
        store.roots.hermes_home,
    )
    rendered = render_owner_review_digest(
        store,
        owner_id=owner_id,
        channel=channel,
        max_action_required=20,
        max_review_suggested=20,
        max_fyi=20,
        record_active=True,
    )
    item = next(
        item
        for items in rendered["sections"].values()
        for item in items
        if item.get("target_type") == "candidate" and item.get("target_id") == candidate_id
    )
    action_tokens = item.get("action_tokens") if isinstance(item.get("action_tokens"), dict) else {}
    assert "approve_external_evidence" in action_tokens, item
    token = str(action_tokens["approve_external_evidence"])
    parsed = parse_owner_review_reply(
        store,
        f"memory approve {token}",
        owner_id=owner_id,
        channel=channel,
        apply=True,
        digest_id=str(rendered["digest_id"]),
        require_recorded_digest=True,
    )
    assert parsed["status"] == "ok", parsed
    return dict(parsed["owner_action_result"])


# ── Tests ────────────────────────────────────────────────────────────────


class TestApproveExternalEvidenceOwnerAction:
    """Task P2.3 — approve_external_evidence owner action."""

    def test_approve_external_evidence_crystallizes_tainted_candidate(self, tmp_path):
        """Approve external evidence crystallizes a tainted candidate with correct ack."""
        store = _store(tmp_path)
        ref = "ragflow:dataset:doc:chunk-approve-001"
        _event_id, candidate = _create_tainted_candidate(
            store,
            candidate_id="cand-ext-approve-ok",
            content="approve external evidence test content",
            external_ref=ref,
        )

        result = _approve_external_via_recorded_digest(store, candidate.candidate_id)

        assert result["status"] == "ok", f"Expected ok, got {result}"
        rr = result["result_ref"]
        assert rr["candidate_id"] == candidate.candidate_id
        assert rr["acked_external_ref"] == ref, (
            f"Expected acked_external_ref={ref}, got {rr['acked_external_ref']}"
        )

        # Verify the crystallized record file was written
        crystallized_path = rr["crystallized_path"]
        assert crystallized_path, "crystallized_path must be non-empty"

        # Verify candidate is no longer in the queue (processing removes it
        # implicitly — write_approved_record writes a .md, but check ok)
        remaining = [c for c in read_candidate_queue(store) if c.candidate_id == candidate.candidate_id]
        assert len(remaining) == 1, "write_approved_record does not remove from queue"

    def test_approve_external_evidence_wrong_ref_rejected(self, tmp_path):
        """Wrong acked_external_ref triggers P0 wall rejection."""
        store = _store(tmp_path)
        _event_id, candidate = _create_tainted_candidate(
            store,
            candidate_id="cand-ext-wrong-ref",
            content="wrong ref test content",
            external_ref="ragflow:dataset:doc:chunk-006",
        )

        decision = ApprovalDecision(
            candidate_id=candidate.candidate_id,
            purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
            reviewer="test-owner",
            reviewed_at=datetime.now(timezone.utc).isoformat(),
            external_evidence_ack=True,
            acked_external_ref="wrong-ref-value",
        )
        with pytest.raises(CrystallizedApprovalError, match="external_evidence_ack_ref_mismatch"):
            CrystallizedMemoryService(store).write_approved_record(
                candidate,
                decision,
                file_name="owner_approved.md",
            )

    def test_ordinary_approve_cannot_approve_tainted_candidate(self, tmp_path):
        """Ordinary approve_candidate on a tainted candidate raises P0 wall error."""
        store = _store(tmp_path)
        _event_id, candidate = _create_tainted_candidate(
            store,
            candidate_id="cand-ordinary-fail",
            content="ordinary approve on tainted candidate",
            external_ref="ragflow:dataset:doc:chunk-007",
        )

        decision = ApprovalDecision(
            candidate_id=candidate.candidate_id,
            purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
            reviewer="test-owner",
            reviewed_at=datetime.now(timezone.utc).isoformat(),
        )
        with pytest.raises(CrystallizedApprovalError, match="external_evidence_requires_explicit_ack"):
            CrystallizedMemoryService(store).write_approved_record(
                candidate,
                decision,
                file_name="owner_approved.md",
            )

    def test_approve_external_evidence_untainted_candidate_rejected(self, tmp_path):
        """Validation rejects approve_external_evidence for non-tainted candidates."""
        store = _store(tmp_path)
        candidate = CrystallizedCandidate(
            candidate_id="cand-untainted",
            kind="moment",
            body="untainted candidate",
            source_event_ids=[],
            sensitivity="private",
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        append_candidate_queue(store, candidate)

        result = apply_owner_action(
            store,
            action_type="approve_external_evidence",
            target=f"candidate:{candidate.candidate_id}",
            owner_id="test-owner",
            channel="test",
            apply=True,
        )

        assert result["status"] == "error", f"Expected error for untainted candidate, got {result}"
        assert "candidate_not_tainted" in str(result), f"Missing candidate_not_tainted in {result}"

    def test_approve_external_evidence_nonexistent_candidate(self, tmp_path):
        """Validation rejects approve_external_evidence for missing candidates."""
        store = _store(tmp_path)

        result = apply_owner_action(
            store,
            action_type="approve_external_evidence",
            target="candidate:nonexistent-cand-id",
            owner_id="test-owner",
            channel="test",
            apply=True,
        )

        assert result["status"] == "error", f"Expected error for missing candidate, got {result}"
        assert "candidate_not_found" in str(result), f"Missing candidate_not_found in {result}"
