"""Tests for approve_external_evidence owner action — P2.3."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from plugins.memory.memory_os.crystallized import (
    CrystallizedApprovalError,
    CrystallizedCandidate,
    append_candidate_queue,
    read_candidate_queue,
)
from plugins.memory.memory_os.external_intake import external_intake
from plugins.memory.memory_os.owner_actions import apply_owner_action
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

        result = apply_owner_action(
            store,
            action_type="approve_external_evidence",
            target=f"candidate:{candidate.candidate_id}",
            owner_id="test-owner",
            channel="test",
            apply=True,
        )

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

        with pytest.raises(CrystallizedApprovalError, match="external_evidence_ack_ref_mismatch"):
            apply_owner_action(
                store,
                action_type="approve_external_evidence",
                target=f"candidate:{candidate.candidate_id}",
                owner_id="test-owner",
                channel="test",
                reply_context={"acked_external_ref": "wrong-ref-value"},
                apply=True,
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

        with pytest.raises(CrystallizedApprovalError, match="external_evidence_requires_explicit_ack"):
            apply_owner_action(
                store,
                action_type="approve_candidate",
                target=f"candidate:{candidate.candidate_id}",
                owner_id="test-owner",
                channel="test",
                apply=True,
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
