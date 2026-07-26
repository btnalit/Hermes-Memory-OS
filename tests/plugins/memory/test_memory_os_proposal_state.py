"""Tests for proposal/token state machine."""

import pytest
from datetime import datetime, timezone
from plugins.memory.memory_os.proposal_state import (
    ProposalState,
    TokenState,
    ProposalStage,
    TokenStage,
    is_proposal_terminal,
    is_token_terminal,
    is_allowed_proposal_transition,
    is_allowed_token_transition,
    transition_proposal,
    transition_token,
    infer_proposal_stage_from_state,
    infer_token_stage_from_action,
    build_proposal_report,
    build_token_report,
)


class TestProposalTransitions:
    def test_drafted_to_submitted(self):
        assert is_allowed_proposal_transition("drafted", "submitted") is True

    def test_drafted_to_cancelled(self):
        assert is_allowed_proposal_transition("drafted", "cancelled") is True

    def test_submitted_to_approved(self):
        assert is_allowed_proposal_transition("submitted", "approved_for_proposal") is True

    def test_approved_to_applied(self):
        assert is_allowed_proposal_transition("approved_for_proposal", "applied") is True

    def test_approved_to_rejected(self):
        assert is_allowed_proposal_transition("approved_for_proposal", "rejected") is True

    def test_approved_to_expired(self):
        assert is_allowed_proposal_transition("approved_for_proposal", "expired") is True

    def test_terminal_no_transition(self):
        assert is_allowed_proposal_transition("applied", "submitted") is False
        assert is_allowed_proposal_transition("rejected", "submitted") is False
        assert is_allowed_proposal_transition("expired", "submitted") is False
        assert is_allowed_proposal_transition("cancelled", "submitted") is False

    def test_direct_to_applied_invalid(self):
        assert is_allowed_proposal_transition("drafted", "applied") is False


class TestTokenTransitions:
    def test_active_to_approved(self):
        assert is_allowed_token_transition("active", "approved") is True

    def test_active_to_rejected(self):
        assert is_allowed_token_transition("active", "rejected") is True

    def test_active_to_deferred(self):
        assert is_allowed_token_transition("active", "deferred") is True

    def test_active_to_revoked(self):
        assert is_allowed_token_transition("active", "revoked") is True

    def test_deferred_to_active(self):
        assert is_allowed_token_transition("deferred", "active") is True

    def test_deferred_to_expired(self):
        assert is_allowed_token_transition("deferred", "expired") is True

    def test_terminal_no_transition(self):
        assert is_allowed_token_transition("approved", "active") is False
        assert is_allowed_token_transition("rejected", "active") is False
        assert is_allowed_token_transition("revoked", "active") is False
        assert is_allowed_token_transition("expired", "active") is False


class TestTransitionProposal:
    def test_full_proposal_lifecycle(self):
        state = ProposalState(proposal_id="prop-1")
        now = datetime(2026, 7, 22, 12, 0, 0, tzinfo=timezone.utc)

        state = transition_proposal(state, "submitted", reason="owner requested", now=now)
        assert state.stage == "submitted"

        state = transition_proposal(state, "approved_for_proposal", reason="owner approved", now=now)
        assert state.stage == "approved_for_proposal"

        state = transition_proposal(state, "applied", reason="auto-applied", now=now)
        assert state.stage == "applied"
        assert is_proposal_terminal(state.stage)

    def test_invalid_transition(self):
        state = ProposalState(proposal_id="prop-2")
        with pytest.raises(ValueError, match="not allowed"):
            transition_proposal(state, "applied")

    def test_rejection_tracks_reason(self):
        state = ProposalState(proposal_id="prop-3", stage="approved_for_proposal")
        state = transition_proposal(state, "rejected", reason="not needed")
        assert state.rejection_reason == "not needed"

    def test_transition_history(self):
        state = ProposalState(proposal_id="prop-4")
        state = transition_proposal(state, "submitted")
        state = transition_proposal(state, "approved_for_proposal")
        state = transition_proposal(state, "rejected")
        assert len(state.transition_history) == 3
        assert state.transition_history[0]["from_stage"] == "drafted"
        assert state.transition_history[0]["to_stage"] == "submitted"


class TestTransitionToken:
    def test_full_token_lifecycle(self):
        state = TokenState(token_id="token-1")
        now = datetime(2026, 7, 22, 12, 0, 0, tzinfo=timezone.utc)

        state = transition_token(state, "approved", reason="owner approved", now=now)
        assert state.stage == "approved"
        assert is_token_terminal(state.stage)

    def test_defer_and_reactivate(self):
        state = TokenState(token_id="token-2")
        state = transition_token(state, "deferred", reason="need more info")
        assert state.stage == "deferred"
        assert state.defer_reason == "need more info"

        state = transition_token(state, "active")
        assert state.stage == "active"

    def test_invalid_transition(self):
        state = TokenState(token_id="token-3", stage="approved")
        with pytest.raises(ValueError, match="not allowed"):
            transition_token(state, "active")

    def test_revoked_tracks_reason(self):
        state = TokenState(token_id="token-4")
        state = transition_token(state, "revoked", reason="superseded")
        assert state.revoked_reason == "superseded"


class TestInferProposalStage:
    def test_empty(self):
        assert infer_proposal_stage_from_state("") == "drafted"

    def test_approved(self):
        assert infer_proposal_stage_from_state("approved") == "approved_for_proposal"

    def test_exact(self):
        assert infer_proposal_stage_from_state("approved_for_proposal") == "approved_for_proposal"


class TestInferTokenStage:
    def test_approve_action(self):
        assert infer_token_stage_from_action("approve") == "approved"

    def test_empty_action(self):
        assert infer_token_stage_from_action("") == "active"


class TestReports:
    def test_proposal_report(self):
        state = ProposalState(proposal_id="prop-1", stage="submitted")
        report = build_proposal_report(state)
        assert report["schema_version"] is not None
        assert report["proposal_id"] == "prop-1"
        assert report["stage"] == "submitted"
        assert report["is_terminal"] is False

    def test_token_report(self):
        state = TokenState(token_id="token-1", stage="active")
        report = build_token_report(state)
        assert report["schema_version"] is not None
        assert report["token_id"] == "token-1"
        assert report["is_terminal"] is False