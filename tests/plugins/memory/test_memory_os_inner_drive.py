"""Tests for classify_event_for_inner_drive — source gate foundation.

Covers all 7 event kind branches of the pure classification function.
This is the test infrastructure (阶段〇) required before any source-gate
business logic changes.

Spec: docs/resolver/hermes-memory-os-source-gate-quality-spec.md
Checklist: docs/resolver/hermes-memory-os-stabilization-checklist.md §F.1
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from plugins.memory.memory_os.inner_drive import (
    InnerDriveEventDecision,
    classify_event_for_inner_drive,
)
from plugins.memory.memory_os.schema import EVENT_SCHEMA_VERSION, EventEnvelope


# ── Helpers ──────────────────────────────────────────────────────────────

def _event(*, kind="conversation_turn", summary="User: I decided to use PostgreSQL for the database | Assistant: That is a solid choice, PostgreSQL has strong ACID compliance and good scalability",
           safe_ref=None, source="telegram", tags=None, body_policy="summary_only",
           event_id=None, sensitivity="private") -> EventEnvelope:
    """Construct a minimal EventEnvelope for classification tests."""
    return EventEnvelope(
        schema_version=EVENT_SCHEMA_VERSION,
        id=event_id or f"evt_{kind}_test",
        ts=datetime.now(timezone.utc).isoformat(),
        profile="default",
        source=source,
        kind=kind,
        summary=summary,
        safe_ref=safe_ref or {},
        tags=tags or ["test"],
        sensitivity=sensitivity,
        body_policy=body_policy,
        promotion_state="raw",
    )


# ── G.0 — Baseline: all 7 event kind branches ───────────────────────────

class TestClassifyEventForInnerDriveBaseline:
    """G.0: classify_event_for_inner_drive basic contract for all 7 event kinds.

    These tests lock in the current behavior BEFORE any source-gate changes.
    If a source-gate change accidentally breaks a non-conversation_turn branch,
    one of these tests will catch it.
    """

    def test_conversation_turn_candidate_allowed_true(self):
        """conversation_turn → candidate_allowed=True (default, pre-source-gate)."""
        decision = classify_event_for_inner_drive(_event(kind="conversation_turn"))
        assert decision.candidate_allowed is True
        assert decision.working_kind == "lingering"
        assert decision.working_weight == 0.6
        assert decision.drive_policy == "eligible"
        assert decision.skip_reason == ""

    def test_memory_write_candidate_allowed_true(self):
        """memory_write → candidate_allowed=True, working_weight=0.45."""
        decision = classify_event_for_inner_drive(_event(kind="memory_write"))
        assert decision.candidate_allowed is True
        assert decision.working_kind == "lingering"
        assert decision.working_weight == 0.45

    def test_conversation_turn_mirrored_bounded_summary_blocked(self):
        """mirrored + body_policy=bounded_summary → candidate_allowed=False."""
        decision = classify_event_for_inner_drive(
            _event(
                kind="conversation_turn_mirrored",
                safe_ref={"body_policy": "bounded_summary"},
            )
        )
        assert decision.candidate_allowed is False
        assert decision.working_kind == "lingering"
        assert decision.working_weight == 0.3

    def test_journal_card_observed_blocked(self):
        """journal_card_observed → candidate_allowed=False, working_kind=attention."""
        decision = classify_event_for_inner_drive(_event(kind="journal_card_observed"))
        assert decision.candidate_allowed is False
        assert decision.working_kind == "attention"
        assert decision.working_weight == 0.25
        assert decision.drive_policy == "low_weight"

    def test_cron_job_run_blocked(self):
        """cron_job_run → candidate_allowed=False with skip_reason."""
        decision = classify_event_for_inner_drive(_event(kind="cron_job_run"))
        assert decision.candidate_allowed is False
        assert decision.skip_reason == "index_only"

    def test_runtime_heartbeat_ignored(self):
        """runtime_heartbeat → drive_policy=ignore, candidate_allowed=False."""
        decision = classify_event_for_inner_drive(_event(kind="runtime_heartbeat"))
        assert decision.candidate_allowed is False
        assert decision.drive_policy == "ignore"
        assert decision.skip_reason == "runtime_event"

    def test_module_audit_ignored(self):
        """module_audit → drive_policy=ignore."""
        decision = classify_event_for_inner_drive(_event(kind="module_audit"))
        assert decision.drive_policy == "ignore"
        assert decision.candidate_allowed is False

    def test_index_event_ignored(self):
        """index_event → drive_policy=ignore."""
        decision = classify_event_for_inner_drive(_event(kind="index_event"))
        assert decision.drive_policy == "ignore"
        assert decision.candidate_allowed is False

    def test_unknown_kind_fallback_index_only(self):
        """Unknown/novel kind → drive_policy=index_only, skip_reason set."""
        decision = classify_event_for_inner_drive(
            _event(kind="some_future_event_kind")
        )
        assert decision.drive_policy == "index_only"
        assert decision.candidate_allowed is False
        assert decision.skip_reason == "unknown_event_kind"

    def test_session_observed_blocked(self):
        """session_observed → candidate_allowed=False."""
        decision = classify_event_for_inner_drive(_event(kind="session_observed"))
        assert decision.candidate_allowed is False


# ── G.3 — candidate_explicit override ────────────────────────────────────

class TestCandidateExplicitOverride:
    """candidate_explicit in safe_ref overrides the default decision."""

    def test_candidate_explicit_true_overrides_blocked_kind(self):
        """candidate_explicit=True makes a normally-blocked kind allowed."""
        decision = classify_event_for_inner_drive(
            _event(
                kind="journal_card_observed",
                safe_ref={"candidate_allowed": True},
            )
        )
        assert decision.candidate_allowed is True

    def test_candidate_explicit_false_overrides_allowed_kind(self):
        """candidate_explicit=False blocks a normally-allowed kind."""
        decision = classify_event_for_inner_drive(
            _event(
                kind="conversation_turn",
                safe_ref={"candidate_allowed": False},
            )
        )
        assert decision.candidate_allowed is False

    def test_candidate_explicit_none_string_uses_default(self):
        """Non-boolean candidate_explicit falls through to default."""
        decision = classify_event_for_inner_drive(
            _event(
                kind="conversation_turn",
                safe_ref={"candidate_allowed": "yes"},
            )
        )
        # "yes" is not a bool → default=True
        assert decision.candidate_allowed is True


# ── Explicit policy edge cases ───────────────────────────────────────────

class TestExplicitPolicy:
    """drive_policy via safe_ref explicit_policy field."""

    def test_explicit_low_weight_policy_unmatched_kind(self):
        """explicit_policy=low_weight on unmatched kind → working_kind=attention.

        NOTE: memory_write is matched by its own branch before the low_weight
        fallback. The explicit low_weight path only triggers for kinds that
        don't match any earlier branch (e.g. a kind outside the big-4).
        """
        decision = classify_event_for_inner_drive(
            _event(
                kind="custom_event",
                safe_ref={"drive_policy": "low_weight"},
            )
        )
        assert decision.drive_policy == "low_weight"
        assert decision.working_kind == "attention"
        assert decision.working_weight == 0.2
        assert decision.candidate_allowed is False

    def test_memory_write_explicit_policy_changes_drive_policy_only(self):
        """memory_write with explicit drive_policy still uses its own branch.

        The kind-matched branch uses explicit_policy for drive_policy but
        candidate_allowed/working_kind/working_weight come from the branch.
        """
        decision = classify_event_for_inner_drive(
            _event(
                kind="memory_write",
                safe_ref={"drive_policy": "low_weight"},
            )
        )
        assert decision.drive_policy == "low_weight"  # overrides "eligible"
        assert decision.working_kind == "lingering"     # from branch, not fallback
        assert decision.working_weight == 0.45           # from branch
        assert decision.candidate_allowed is True        # from branch

    def test_explicit_index_only_policy_unmatched_kind(self):
        """explicit_policy=index_only on unmatched kind → candidate_allowed=False.

        Like low_weight, this only triggers for kinds that don't match
        an earlier branch. conversation_turn has its own branch.
        """
        decision = classify_event_for_inner_drive(
            _event(
                kind="custom_event",
                safe_ref={"drive_policy": "index_only"},
            )
        )
        assert decision.candidate_allowed is False
        assert decision.skip_reason == "index_only"

    def test_conversation_turn_with_explicit_index_only_keeps_own_branch(self):
        """conversation_turn branch wins over explicit_policy fallback.

        drive_policy reflects the explicit value but candidate_allowed comes
        from the branch default=True (unless candidate_explicit is set).
        """
        decision = classify_event_for_inner_drive(
            _event(
                kind="conversation_turn",
                safe_ref={"drive_policy": "index_only"},
            )
        )
        assert decision.drive_policy == "index_only"
        assert decision.candidate_allowed is True  # from branch, not fallback


# ── source_class extraction ─────────────────────────────────────────────

class TestSourceClass:
    """source_class is extracted from event metadata for routing."""

    def test_conversation_turn_is_foreground(self):
        decision = classify_event_for_inner_drive(_event(kind="conversation_turn"))
        assert decision.source_class == "foreground"

    def test_cron_source_is_cron(self):
        decision = classify_event_for_inner_drive(
            _event(kind="cron_job_run", source="cron")
        )
        assert decision.source_class == "cron"

    def test_self_activity_is_recognized(self):
        decision = classify_event_for_inner_drive(
            _event(
                kind="conversation_turn",
                safe_ref={"source_class": "self_activity"},
            )
        )
        assert decision.source_class == "self_activity"


# ── Return type contract ─────────────────────────────────────────────────

class TestReturnType:
    """classify_event_for_inner_drive always returns InnerDriveEventDecision."""

    def test_returns_inner_drive_event_decision(self):
        decision = classify_event_for_inner_drive(_event())
        assert isinstance(decision, InnerDriveEventDecision)

    def test_all_fields_present(self):
        """All dataclass fields are populated (no None where str expected)."""
        decision = classify_event_for_inner_drive(_event())
        assert isinstance(decision.source_class, str)
        assert isinstance(decision.drive_policy, str)
        assert isinstance(decision.working_kind, str)
        assert isinstance(decision.working_weight, float)
        assert isinstance(decision.candidate_allowed, bool)
        assert isinstance(decision.skip_reason, str)


# ── G-series: Source gate fragment detection ─────────────────────────────
# These tests validate _is_obvious_fragment behavior (F.2.3).

class TestSourceGateFragmentDetection:
    """G.1-G.6: Source gate correctly identifies fragments vs knowledge."""

    def test_g1_obvious_fragment_blocked(self):
        """G.1: Obvious fragment → candidate_allowed=False, working still set."""
        decision = classify_event_for_inner_drive(
            _event(
                kind="conversation_turn",
                summary="User: 更新部署看看 | Assistant: 部署完成，服务已重启",
            )
        )
        assert decision.candidate_allowed is False
        assert decision.skip_reason == "source_gate:obvious_fragment"
        assert decision.working_kind == "lingering"  # working unaffected

    def test_g1_process_inquiry_blocked(self):
        """G.1: 查一下 / 看一下 style process inquiry → fragment."""
        decision = classify_event_for_inner_drive(
            _event(
                kind="conversation_turn",
                summary="User: 查一下服务状态怎么样 | Assistant: 服务运行正常，CPU 45%",
            )
        )
        assert decision.candidate_allowed is False
        assert decision.skip_reason == "source_gate:obvious_fragment"

    def test_g1_short_confirm_blocked(self):
        """G.1: Ultra-short confirmation ('好的', '嗯') → fragment."""
        decision = classify_event_for_inner_drive(
            _event(
                kind="conversation_turn",
                summary="User: 好的 | Assistant: 收到",
            )
        )
        assert decision.candidate_allowed is False
        assert decision.skip_reason == "source_gate:obvious_fragment"

    def test_g1_layer_b_navigation_blocked(self):
        """G.1: Layer B regex catches navigation/command patterns."""
        decision = classify_event_for_inner_drive(
            _event(
                kind="conversation_turn",
                summary="User: 打开页面看看部署状态 | Assistant: 页面已打开，显示部署成功",
            )
        )
        assert decision.candidate_allowed is False
        assert decision.skip_reason == "source_gate:obvious_fragment"

    def test_g2_knowledge_dialogue_allowed(self):
        """G.2: Knowledge-containing dialogue → candidate_allowed=True."""
        decision = classify_event_for_inner_drive(
            _event(
                kind="conversation_turn",
                summary="User: I decided to use PostgreSQL for the database | Assistant: That is a solid choice, PostgreSQL has strong ACID compliance and good scalability",
            )
        )
        assert decision.candidate_allowed is True
        assert decision.skip_reason == ""

    def test_g2_technical_decision_allowed(self):
        """G.2: Technical decision → candidate_allowed=True."""
        decision = classify_event_for_inner_drive(
            _event(
                kind="conversation_turn",
                summary="User: 我们决定把认证模块从JWT迁移到OAuth2，需要更新所有微服务的认证中间件 | Assistant: 好的，OAuth2确实更安全，支持令牌刷新和撤销机制，我来更新架构文档并制定迁移计划",
            )
        )
        assert decision.candidate_allowed is True

    def test_g2_preference_statement_allowed(self):
        """G.2: User states a preference → candidate_allowed=True."""
        decision = classify_event_for_inner_drive(
            _event(
                kind="conversation_turn",
                summary="User: I prefer using async/await over raw promises | Assistant: Noted, async/await确实更清晰",
            )
        )
        assert decision.candidate_allowed is True

    def test_g3_candidate_explicit_overrides_gate(self):
        """G.3: candidate_explicit=True overrides source gate (fragment→allowed)."""
        decision = classify_event_for_inner_drive(
            _event(
                kind="conversation_turn",
                summary="User: 好的 | Assistant: 收到",
                safe_ref={"candidate_allowed": True},
            )
        )
        assert decision.candidate_allowed is True

    def test_g3_candidate_explicit_false_blocks_knowledge(self):
        """G.3: candidate_explicit=False blocks even knowledge dialogue."""
        decision = classify_event_for_inner_drive(
            _event(
                kind="conversation_turn",
                summary="User: We decided to use Rust for the backend | Assistant: Great choice, Rust has excellent performance",
                safe_ref={"candidate_allowed": False},
            )
        )
        assert decision.candidate_allowed is False

    def test_g4_ambiguous_not_blocked(self):
        """G.4: Ambiguous dialogue → fail-safe allows through."""
        decision = classify_event_for_inner_drive(
            _event(
                kind="conversation_turn",
                summary="User: Can we discuss the architecture for a moment | Assistant: Sure, what aspect would you like to focus on",
            )
        )
        # "Can we discuss..." is somewhat process-y but has substance
        # Fail-safe: if unsure, allow through
        assert decision.candidate_allowed is True

    def test_g5_working_branch_unaffected_by_fragment(self):
        """G.5: Fragment still gets working memory — recent memory preserved."""
        decision = classify_event_for_inner_drive(
            _event(
                kind="conversation_turn",
                summary="User: 好的 | Assistant: 收到",
            )
        )
        assert decision.candidate_allowed is False  # blocked from candidate
        assert decision.working_kind == "lingering"  # working still active

    def test_g6_user_fragment_in_substantive_turn(self):
        """G.6: Fragment user-segment + substantive assistant → still fragment.

        The user's message is a fragment even though the assistant replied
        substantively. Either segment being a fragment → overall fragment.
        """
        decision = classify_event_for_inner_drive(
            _event(
                kind="conversation_turn",
                summary="User: 好的 | Assistant: PostgreSQL uses MVCC for concurrency control, which allows readers to not block writers",
            )
        )
        assert decision.candidate_allowed is False
        assert decision.skip_reason == "source_gate:obvious_fragment"

    def test_g6_assistant_fragment_in_substantive_turn(self):
        """G.6: Substantive user + fragment assistant → still fragment.

        Assistant's short confirmation doesn't salvage the turn.
        """
        decision = classify_event_for_inner_drive(
            _event(
                kind="conversation_turn",
                summary="User: We need to implement a distributed lock using Redis Redlock algorithm | Assistant: ok",
            )
        )
        assert decision.candidate_allowed is False
        assert decision.skip_reason == "source_gate:obvious_fragment"

    def test_g6_both_substantive_allowed(self):
        """G.6: Both segments substantive → candidate_allowed=True."""
        decision = classify_event_for_inner_drive(
            _event(
                kind="conversation_turn",
                summary="User: We need to implement a distributed lock using Redis Redlock algorithm | Assistant: Redlock has known issues with clock skew, consider using a consensus-based approach like Raft instead",
            )
        )
        assert decision.candidate_allowed is True


# ── G.X: Adversarial verification ────────────────────────────────────────

class TestSourceGateAdversarial:
    """G.X: Removing source gate logic MUST cause fragment tests to fail."""

    def test_gx_fragment_detection_is_the_cause(self, monkeypatch):
        """G.X: If _is_obvious_fragment always returns False, G.1 MUST fail.

        This proves the test is truly testing the source gate, not some
        other mechanism. Disable the gate → fragment should pass through.
        """
        # Disable fragment detection
        import plugins.memory.memory_os.inner_drive as mod

        monkeypatch.setattr(mod, "_is_obvious_fragment", lambda _summary: False)

        decision = classify_event_for_inner_drive(
            _event(
                kind="conversation_turn",
                summary="User: 好的 | Assistant: 收到",
            )
        )
        # With gate disabled, fragment passes through
        assert decision.candidate_allowed is True
        assert decision.skip_reason == ""


# ── Degenerate / edge inputs ─────────────────────────────────────────────

class TestEdgeInputs:
    """Graceful handling of unusual event shapes."""

    def test_empty_summary(self):
        """Empty summary should not crash classification."""
        decision = classify_event_for_inner_drive(
            _event(kind="conversation_turn", summary="")
        )
        assert isinstance(decision, InnerDriveEventDecision)
        # Empty summary is still a conversation_turn → default allowed
        assert decision.candidate_allowed is True

    def test_none_safe_ref(self):
        """safe_ref=None should be handled gracefully (treated as empty dict)."""
        # EventEnvelope enforces dict, but if somehow None gets through...
        event = _event()
        object.__setattr__(event, "safe_ref", None)
        decision = classify_event_for_inner_drive(event)
        assert isinstance(decision, InnerDriveEventDecision)

    def test_promotion_state_preserved(self):
        """promotion_state is on the event but classification ignores it."""
        decision = classify_event_for_inner_drive(
            _event(kind="conversation_turn")
        )
        assert decision.candidate_allowed is True
