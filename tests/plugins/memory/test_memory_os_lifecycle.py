"""Tests for lifecycle state machine."""

import pytest
from datetime import datetime, timezone
from plugins.memory.memory_os.lifecycle import (
    LifecycleState,
    LifecycleStage,
    LifecycleTransition,
    is_terminal,
    is_allowed_transition,
    transition,
    stage_order,
    infer_stage_from_bridge,
    derive_stage_from_working,
    build_lifecycle_report,
)


class TestIsTerminal:
    def test_crystallized_is_terminal(self):
        assert is_terminal("crystallized") is True

    def test_expired_is_terminal(self):
        assert is_terminal("expired") is True

    def test_revoked_is_terminal(self):
        assert is_terminal("revoked") is True

    def test_working_is_not_terminal(self):
        assert is_terminal("working") is False

    def test_candidate_is_not_terminal(self):
        assert is_terminal("candidate") is False


class TestIsAllowedTransition:
    def test_working_to_candidate(self):
        assert is_allowed_transition("working", "candidate") is True

    def test_candidate_to_crystallized(self):
        assert is_allowed_transition("candidate", "crystallized") is True

    def test_candidate_to_deferred(self):
        assert is_allowed_transition("candidate", "deferred") is True

    def test_candidate_to_rejected(self):
        assert is_allowed_transition("candidate", "rejected") is True

    def test_crystallized_to_revoked(self):
        assert is_allowed_transition("crystallized", "revoked") is True

    def test_deferred_to_candidate(self):
        assert is_allowed_transition("deferred", "candidate") is True

    def test_working_to_crystallized_direct(self):
        assert is_allowed_transition("working", "crystallized") is False  # must go through candidate

    def test_terminal_to_anything(self):
        assert is_allowed_transition("crystallized", "candidate") is False
        assert is_allowed_transition("expired", "candidate") is False
        assert is_allowed_transition("revoked", "candidate") is False


class TestTransition:
    def test_simple_transition(self):
        state = LifecycleState(item_id="test-1")
        now = datetime(2026, 7, 22, 12, 0, 0, tzinfo=timezone.utc)
        result = transition(state, "candidate", reason="test", now=now)
        assert result.stage == "candidate"
        assert len(result.transition_history) == 1
        assert result.transition_history[0]["transition"] == "working→candidate"

    def test_transition_to_crystallized(self):
        state = LifecycleState(item_id="test-2", stage="candidate")
        now = datetime(2026, 7, 22, 12, 0, 0, tzinfo=timezone.utc)
        result = transition(state, "crystallized", reason="owner approved", now=now)
        assert result.stage == "crystallized"
        assert is_terminal(result.stage)

    def test_transition_to_rejected(self):
        state = LifecycleState(item_id="test-3", stage="candidate")
        result = transition(state, "rejected", reason="owner rejected")
        assert result.stage == "rejected"
        assert result.rejection_count == 1

    def test_transition_from_terminal_raises(self):
        # Terminal states can still transition if the transition is in the
        # allowed matrix (e.g. crystallized→revoked).  Only disallowed
        # transitions raise.
        state = LifecycleState(item_id="test-4", stage="crystallized")
        # crystallized→candidate is NOT in the allowed matrix
        with pytest.raises(ValueError, match="not allowed"):
            transition(state, "candidate")

    def test_invalid_transition_raises(self):
        state = LifecycleState(item_id="test-5", stage="working")
        with pytest.raises(ValueError, match="not allowed"):
            transition(state, "crystallized")

    def test_rejection_count_increments(self):
        state = LifecycleState(item_id="test-6", stage="candidate")
        state = transition(state, "rejected", reason="no")
        assert state.rejection_count == 1
        state.stage = "candidate"  # reset for next transition
        state = transition(state, "rejected", reason="still no")
        assert state.rejection_count == 2

    def test_multiple_transitions(self):
        state = LifecycleState(item_id="test-7")
        state = transition(state, "candidate", reason="promoted")
        state = transition(state, "crystallized", reason="owner approved")
        state = transition(state, "revoked", reason="owner revoked")
        assert len(state.transition_history) == 3
        assert state.transition_history[0]["transition"] == "working→candidate"
        assert state.transition_history[1]["transition"] == "candidate→crystallized"
        assert state.transition_history[2]["transition"] == "crystallized→revoked"


class TestStageOrder:
    def test_working_first(self):
        assert stage_order("working") == 0

    def test_candidate_second(self):
        assert stage_order("candidate") == 1

    def test_crystallized_third(self):
        assert stage_order("crystallized") == 3

    def test_unknown_high(self):
        assert stage_order("unknown") == 99


class TestInferStageFromBridge:
    def test_empty_bridge(self):
        assert infer_stage_from_bridge("") == "working"

    def test_inner_drive_candidate(self):
        assert infer_stage_from_bridge("inner_drive_candidate") == "candidate"

    def test_owner_approved(self):
        assert infer_stage_from_bridge("owner_approved") == "crystallized"

    def test_owner_rejected(self):
        assert infer_stage_from_bridge("owner_rejected") == "rejected"

    def test_owner_revoked(self):
        assert infer_stage_from_bridge("owner_revoked") == "revoked"


class TestDeriveStageFromWorking:
    def test_active_working(self):
        item = {"status": "active"}
        assert derive_stage_from_working(item) == "working"

    def test_expired(self):
        item = {"status": "expired"}
        assert derive_stage_from_working(item) == "expired"

    def test_with_candidate(self):
        item = {"status": "active"}
        assert derive_stage_from_working(item, has_candidate=True) == "candidate"

    def test_with_crystallized(self):
        item = {"status": "active"}
        assert derive_stage_from_working(item, has_crystallized=True) == "crystallized"


class TestBuildLifecycleReport:
    def test_report_structure(self):
        state = LifecycleState(item_id="test-1", stage="candidate")
        report = build_lifecycle_report(state)
        assert report["schema_version"] is not None
        assert report["item_id"] == "test-1"
        assert report["stage"] == "candidate"
        assert report["is_terminal"] is False