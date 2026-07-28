"""Tests for restraint module."""

import pytest
from datetime import datetime, timedelta, timezone
from plugins.memory.memory_os.restraint import (
    LowCluePolicy, DenialTracker, CandidateEvaluation, SessionPriority
)
from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose


class TestDenialTracker:
    def test_initial_state(self):
        tracker = DenialTracker()
        assert tracker.can_guess()
        assert not tracker.guessing_paused

    def test_denial_under_threshold(self):
        tracker = DenialTracker(max_consecutive_denials=3)
        tracker.record_denial(query="q1")
        assert tracker.can_guess()
        assert not tracker.guessing_paused

    def test_denial_reaches_threshold(self):
        tracker = DenialTracker(max_consecutive_denials=3)
        for i in range(3):
            tracker.record_denial(query=f"q{i}")
        assert tracker.guessing_paused
        assert not tracker.can_guess()

    def test_positive_feedback_resets(self):
        tracker = DenialTracker(max_consecutive_denials=3)
        for i in range(3):
            tracker.record_denial(query=f"q{i}")
        assert tracker.guessing_paused
        tracker.record_positive_feedback()
        assert tracker.can_guess()
        assert not tracker.guessing_paused

    def test_can_guess_after_pause_expires(self):
        now = datetime.now(timezone.utc)
        tracker = DenialTracker(max_consecutive_denials=1)
        tracker.record_denial(query="q", now=now)
        assert not tracker.can_guess(now)

        # 25 hours later — pause should have expired
        later = now + timedelta(hours=25)
        assert tracker.can_guess(later)


class TestCandidateEvaluation:
    def test_unverified_owner_boolean_is_not_approval(self):
        eval = CandidateEvaluation(source="owner", is_owner_approval=True)
        assert eval.evaluate() == "unverified_owner_claim_not_approval"

    def test_structured_approval_decision_is_required(self):
        decision = ApprovalDecision(
            candidate_id="candidate-1",
            purpose=ApprovalPurpose.APPROVE_FOR_WORKING,
            reviewer="owner",
            reviewed_at="2026-07-27T00:00:00+00:00",
        )
        eval = CandidateEvaluation(source="owner", approval_decision=decision)
        assert eval.evaluate() == "valid_owner_approval"

    def test_provisional_not_approval(self):
        eval = CandidateEvaluation(source="system", is_provisional=True)
        assert eval.evaluate() == "provisional_not_approval"

    def test_candidate_not_approval(self):
        eval = CandidateEvaluation(source="system", is_candidate=True)
        assert eval.evaluate() == "candidate_not_approval"

    def test_high_confidence_no_evidence(self):
        eval = CandidateEvaluation(source="model", confidence=0.95, has_evidence=False)
        assert eval.evaluate() == "model_confidence_not_approval"

    def test_silence_not_approval(self):
        eval = CandidateEvaluation(source="system")
        assert eval.evaluate() == "silence_not_approval"


class TestSessionPriority:
    def test_explicit_request_wins(self):
        sp = SessionPriority(has_explicit_request=True, task_anchor_present=True)
        assert sp.evaluate_priority() == "explicit_request"

    def test_task_anchor_default(self):
        sp = SessionPriority(task_anchor_present=True)
        assert sp.evaluate_priority() == "task_anchor"

    def test_no_priority(self):
        sp = SessionPriority()
        assert sp.evaluate_priority() == "none"