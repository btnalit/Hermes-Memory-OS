"""
Gap Note — bounded uncertainty disclosure for Memory-OS recall.

Implements the Gap Note dataflow:

    Recall Plan
    → build_recall_gap_note_candidate(plan)
    → structured reason_codes/counts/would_render
    → shadow metadata-only observation
    → apply-canary bounded renderer
    → at most one natural sentence

Only signals that are directly relevant to the current recall query are
eligible.  Global Monitor warnings are not mechanically attached.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

GAP_NOTE_SCHEMA_VERSION = "memory-os.gap_note.v1"

# ── Eligible reason codes ───────────────────────────────────────────────────
# Only these signals can enter a Gap Note.  Lower-authority/local conflicts
# resolved by arbitration are excluded.

ELIGIBLE_REASON_CODES: frozenset[str] = frozenset({
    "owner_conflict_requires_clarification",
    "stale_task_revision",
})


@dataclass
class GapNoteCandidate:
    """A structured candidate for a Gap Note, built from the Recall Plan.

    Shadow mode: only records reason_codes, counts, and would_render flag.
    Does NOT persist claim/query/source body or final rendered text.
    """

    plan_version: str = ""
    reason_codes: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    would_render: bool = False
    would_render_text: str = ""
    conflict_count: int = 0
    stale_task_count: int = 0
    shadow_only: bool = True

    def is_eligible(self) -> bool:
        return any(c in ELIGIBLE_REASON_CODES for c in self.reason_codes)

    def has_gap(self) -> bool:
        return self.is_eligible() and self.would_render

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": GAP_NOTE_SCHEMA_VERSION,
            "reason_codes": self.reason_codes,
            "counts": self.counts,
            "would_render": self.would_render,
            "conflict_count": self.conflict_count,
            "stale_task_count": self.stale_task_count,
            "shadow_only": self.shadow_only,
        }


@dataclass
class GapNoteRender:
    """The rendered output of a Gap Note.

    Only available when apply_canary is active.  At most one sentence.
    """

    rendered: str = ""
    reason_code: str = ""
    budget_used: bool = False

    def is_empty(self) -> bool:
        return not self.rendered

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": GAP_NOTE_SCHEMA_VERSION,
            "rendered": self.rendered,
            "reason_code": self.reason_code,
            "budget_used": self.budget_used,
        }


# ── Templates ───────────────────────────────────────────────────────────────

_CONFLICT_TEMPLATE = (
    "关于这一点，现有高权威记忆仍有冲突，建议以当前来源再确认一次。"
)
_STALE_TASK_TEMPLATE = (
    "关于这项状态，我找到的记录可能已经过期，近期变化可能尚未进入记忆。"
)


def render_gap_note(candidate: GapNoteCandidate, *, budget: int = 1) -> GapNoteRender:
    """Render a Gap Note candidate into at most one sentence.

    Only one reason code is rendered per call.  Higher-priority codes
    (owner_conflict > stale_task) take precedence.
    """
    if not candidate.is_eligible() or not candidate.would_render:
        return GapNoteRender()

    if budget <= 0:
        return GapNoteRender(budget_used=False)

    # Priority: owner_conflict > stale_task
    if "owner_conflict_requires_clarification" in candidate.reason_codes:
        return GapNoteRender(
            rendered=_CONFLICT_TEMPLATE,
            reason_code="owner_conflict_requires_clarification",
            budget_used=True,
        )
    if "stale_task_revision" in candidate.reason_codes:
        return GapNoteRender(
            rendered=_STALE_TASK_TEMPLATE,
            reason_code="stale_task_revision",
            budget_used=True,
        )

    return GapNoteRender()


def build_gap_note_candidate(
    plan: dict[str, Any],
    *,
    shadow_only: bool = True,
) -> GapNoteCandidate:
    """Build a GapNoteCandidate from a Recall Plan.

    Only records reason codes, counts, and would-render.
    Does NOT persist claim/query/source body or final rendered text.
    """
    reason_codes: list[str] = []
    counts: dict[str, int] = {}
    conflict_count = 0
    stale_task_count = 0
    would_render = False

    # Check for owner conflict
    findings = plan.get("findings", [])
    for finding in findings:
        fc = finding.get("code", "")
        if fc == "owner_conflict_requires_clarification":
            reason_codes.append(fc)
            conflict_count += 1
            counts[fc] = counts.get(fc, 0) + 1
        elif fc == "stale_task_revision":
            reason_codes.append(fc)
            stale_task_count += 1
            counts[fc] = counts.get(fc, 0) + 1

    # would_render is true if any eligible reason code is present
    would_render = any(c in ELIGIBLE_REASON_CODES for c in reason_codes)

    return GapNoteCandidate(
        plan_version=plan.get("schema_version", ""),
        reason_codes=reason_codes,
        counts=counts,
        would_render=would_render,
        conflict_count=conflict_count,
        stale_task_count=stale_task_count,
        shadow_only=shadow_only,
    )