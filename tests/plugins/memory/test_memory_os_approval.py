"""Tests for ApprovalDecision — provisional fields."""

from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose


def test_approval_decision_defaults_provisional_fields_to_false_none_zero():
    """New provisional fields must default safely — no behavior change for existing callers."""
    decision = ApprovalDecision(
        candidate_id="cand_001",
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="owner",
        reviewed_at="2026-06-17T00:00:00Z",
    )
    assert decision.provisional is False
    assert decision.expires_at is None
    assert decision.recurrence == 0


def test_approval_decision_provisional_fields_set_explicitly():
    """Provisional fields can be set for resolver-approved records."""
    decision = ApprovalDecision(
        candidate_id="cand_002",
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="resolver",
        reviewed_at="2026-06-17T00:00:00Z",
        note="auto-approved by resolver",
        source_state="resolver_approved",
        provisional=True,
        expires_at="2026-06-24T00:00:00Z",
        recurrence=0,
    )
    assert decision.provisional is True
    assert decision.expires_at == "2026-06-24T00:00:00Z"
    assert decision.recurrence == 0
    assert decision.allows_crystallized_write is True


def test_approval_decision_allows_crystallized_write_unchanged_with_provisional():
    """provisional=True does NOT change allows_crystallized_write behavior."""
    decision = ApprovalDecision(
        candidate_id="cand_003",
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="resolver",
        reviewed_at="2026-06-17T00:00:00Z",
        provisional=True,
        expires_at="2026-06-24T00:00:00Z",
    )
    assert decision.allows_crystallized_write is True
