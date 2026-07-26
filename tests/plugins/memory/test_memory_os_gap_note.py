"""Tests for Gap Note bounded uncertainty disclosure."""

import pytest
from plugins.memory.memory_os.gap_note import (
    GapNoteCandidate,
    GapNoteRender,
    build_gap_note_candidate,
    render_gap_note,
    ELIGIBLE_REASON_CODES,
)


class TestBuildGapNoteCandidate:
    def test_no_gap(self):
        plan = {"schema_version": "v1", "findings": []}
        candidate = build_gap_note_candidate(plan)
        assert not candidate.is_eligible()
        assert not candidate.has_gap()
        assert candidate.shadow_only is True

    def test_conflict_finding(self):
        plan = {
            "schema_version": "v1",
            "findings": [{"code": "owner_conflict_requires_clarification"}],
        }
        candidate = build_gap_note_candidate(plan)
        assert candidate.is_eligible()
        assert candidate.has_gap()
        assert candidate.conflict_count == 1

    def test_stale_task_finding(self):
        plan = {
            "schema_version": "v1",
            "findings": [{"code": "stale_task_revision"}],
        }
        candidate = build_gap_note_candidate(plan)
        assert candidate.is_eligible()
        assert candidate.has_gap()
        assert candidate.stale_task_count == 1

    def test_multiple_findings(self):
        plan = {
            "schema_version": "v1",
            "findings": [
                {"code": "owner_conflict_requires_clarification"},
                {"code": "stale_task_revision"},
                {"code": "low_freshness"},
            ],
        }
        candidate = build_gap_note_candidate(plan)
        assert candidate.is_eligible()
        assert candidate.has_gap()
        assert candidate.conflict_count == 1
        assert candidate.stale_task_count == 1


class TestRenderGapNote:
    def test_empty_candidate(self):
        candidate = GapNoteCandidate()
        render = render_gap_note(candidate)
        assert render.is_empty()

    def test_conflict_render(self):
        candidate = GapNoteCandidate(
            reason_codes=["owner_conflict_requires_clarification"],
            would_render=True,
        )
        render = render_gap_note(candidate)
        assert not render.is_empty()
        assert "冲突" in render.rendered
        assert render.budget_used is True

    def test_stale_task_render(self):
        candidate = GapNoteCandidate(
            reason_codes=["stale_task_revision"],
            would_render=True,
        )
        render = render_gap_note(candidate)
        assert not render.is_empty()
        assert "过期" in render.rendered
        assert render.budget_used is True

    def test_no_budget(self):
        candidate = GapNoteCandidate(
            reason_codes=["owner_conflict_requires_clarification"],
            would_render=True,
        )
        render = render_gap_note(candidate, budget=0)
        assert render.is_empty()
        assert render.budget_used is False

    def test_priority_conflict_over_stale(self):
        candidate = GapNoteCandidate(
            reason_codes=[
                "stale_task_revision",
                "owner_conflict_requires_clarification",
            ],
            would_render=True,
        )
        render = render_gap_note(candidate)
        assert "冲突" in render.rendered  # conflict takes priority
        assert render.reason_code == "owner_conflict_requires_clarification"


class TestEligibleCodes:
    def test_eligible_codes(self):
        assert "owner_conflict_requires_clarification" in ELIGIBLE_REASON_CODES
        assert "stale_task_revision" in ELIGIBLE_REASON_CODES

    def test_inelegible_code(self):
        assert "low_freshness" not in ELIGIBLE_REASON_CODES
        assert "attribution_gap" not in ELIGIBLE_REASON_CODES