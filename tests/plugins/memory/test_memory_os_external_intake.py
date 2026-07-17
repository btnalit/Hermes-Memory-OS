"""Tests for external_intake — provider-agnostic external evidence port."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from plugins.memory.memory_os.crystallized import CrystallizedCandidate
from plugins.memory.memory_os.execution_gate import execution_gate_records_path
from plugins.memory.memory_os.external_intake import external_intake
from plugins.memory.memory_os.inner_drive import classify_event_for_inner_drive
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore


# ── Helpers ──────────────────────────────────────────────────────────────


def _store(tmp_path) -> MemoryOSStore:
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    store = MemoryOSStore(roots)
    store.initialize()
    return store


# ── Tests ────────────────────────────────────────────────────────────────


class TestExternalIntake:
    """Q.1: External evidence intake creates tainted events with correct metadata."""

    def test_intake_creates_event_with_external_evidence_source_class(self, tmp_path):
        """Verify event kind, source_class, external_ref, provider, candidate_allowed."""
        store = _store(tmp_path)
        event_id = external_intake(
            store,
            content="external evidence content for testing",
            external_ref="ragflow:dataset:doc:chunk-001",
            provider="testing_provider",
            metadata={"source": "test_suite"},
        )

        events = store.read_events()
        assert len(events) == 1
        event = events[0]

        assert event.id == event_id
        assert event.kind == "external_evidence_intake"
        assert event.source == "external_intake"

        safe_ref = dict(event.safe_ref)
        assert safe_ref.get("source_class") == "external_evidence"
        assert safe_ref.get("external_ref") == "ragflow:dataset:doc:chunk-001"
        assert safe_ref.get("provider") == "testing_provider"
        assert safe_ref.get("candidate_allowed") is True
        assert "metadata" in safe_ref
        assert safe_ref["metadata"]["source"] == "test_suite"
        assert "execution_gate_envelope_id" in safe_ref

        tags = list(event.tags)
        assert "external-evidence" in tags
        assert "tainted" in tags
        assert "provider:testing_provider" in tags

    def test_intake_empty_external_ref_raises(self, tmp_path):
        """Empty or whitespace-only external_ref raises ValueError."""
        store = _store(tmp_path)

        with pytest.raises(ValueError, match="external_ref must be a non-empty string"):
            external_intake(
                store,
                content="test content",
                external_ref="",
                provider="test",
            )

        with pytest.raises(ValueError, match="external_ref must be a non-empty string"):
            external_intake(
                store,
                content="test content",
                external_ref="   ",
                provider="test",
            )

        # Verify no events were written
        assert len(store.read_events()) == 0

    def test_intake_event_classified_for_inner_drive(self, tmp_path):
        """Verify classify_event_for_inner_drive returns candidate_allowed=True, working_kind='lingering'."""
        store = _store(tmp_path)
        external_intake(
            store,
            content="classification test content",
            external_ref="ragflow:doc:chunk-002",
            provider="test",
        )

        events = store.read_events()
        assert len(events) == 1
        event = events[0]

        decision = classify_event_for_inner_drive(event)
        assert decision.candidate_allowed is True
        assert decision.working_kind == "lingering"
        assert decision.working_weight == 0.45

    def test_intake_execution_gate_envelope_created(self, tmp_path):
        """Verify ExecutionGate permit record exists with lane_id='external_evidence_intake'."""
        store = _store(tmp_path)
        external_intake(
            store,
            content="gate test content",
            external_ref="ragflow:doc:chunk-003",
            provider="test",
        )

        gate_path = execution_gate_records_path(store.roots)
        assert gate_path.exists()

        records = [
            json.loads(line)
            for line in gate_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        permits = [r for r in records if r.get("stage") == "permit"]
        completions = [r for r in records if r.get("stage") == "completion"]

        assert len(permits) >= 1
        assert permits[0]["lane_id"] == "external_evidence_intake"
        assert permits[0]["permit_decision"] == "allowed"
        assert permits[0]["trigger_surface"] == "external_intake"
        assert permits[0]["risk_class"] == "low"

        assert len(completions) >= 1
        assert completions[0]["lane_id"] == "external_evidence_intake"
        assert completions[0]["execution_status"] == "completed"

    def test_intake_completion_postcheck_does_not_trip_boundary(self, tmp_path):
        """A routine intake append is not a boundary event: no bare-True postcheck values."""
        from plugins.memory.memory_os.execution_gate import any_boundary_true

        store = _store(tmp_path)
        external_intake(
            store,
            content="boundary test content",
            external_ref="ragflow:doc:chunk-005",
            provider="test",
        )

        gate_path = execution_gate_records_path(store.roots)
        records = [
            json.loads(line)
            for line in gate_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        completions = [r for r in records if r.get("stage") == "completion"]
        assert len(completions) == 1
        completion = completions[0]

        assert completion["postcheck"] == {"event_appended_count": 1}
        assert any_boundary_true(completion["postcheck"]) is False
        assert completion["postcheck_boundary_true"] is False

    def test_intake_tainted_candidate_blocked_by_p0_wall(self, tmp_path):
        """Verify candidate from external_intake event is tainted (is_tainted returns True)."""
        from plugins.memory.memory_os.provenance import is_tainted

        store = _store(tmp_path)
        event_id = external_intake(
            store,
            content="tainted candidate test content",
            external_ref="ragflow:doc:chunk-004",
            provider="test",
        )

        candidate = CrystallizedCandidate(
            candidate_id="cand-ext-intake-001",
            kind="moment",
            body="tainted candidate from external intake event",
            source_event_ids=[event_id],
            sensitivity="private",
            tags=["test", "tainted"],
            bridge_state="inner_drive_candidate",
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        assert is_tainted(candidate, store=store) is True
