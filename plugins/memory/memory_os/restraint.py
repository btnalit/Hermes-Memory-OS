"""
Low-clue handling and restraint utilities for Memory-OS.

Defines policies for:
- Low-clue recall: give direction or minimal clarification, do not force
  a single answer when evidence is insufficient.
- Repeated denial: stop guessing after configurable consecutive denials.
- Candidate/provisional/confidence: never treat as Owner approval.
- Session priority: current explicit request over historical anchors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .approval import ApprovalDecision, ApprovalPurpose

RESTRAINT_SCHEMA_VERSION = "memory-os.restraint.v1"


@dataclass
class LowCluePolicy:
    """Policy for handling low-clue recall queries."""

    max_confidence_threshold: float = 0.6
    min_evidence_count: int = 2
    prefer_direction_over_answer: bool = True
    clarification_template: str = "关于这个，我目前的信息还不够确定，建议先确认一下具体方向。"


@dataclass
class DenialTracker:
    """Tracks consecutive Owner denials or corrections."""

    max_consecutive_denials: int = 3
    consecutive_denials: int = 0
    last_denied_at: str = ""
    last_denied_query: str = ""
    guessing_paused: bool = False
    pause_until: str = ""

    def record_denial(self, *, query: str = "", now: datetime | None = None) -> None:
        ts = (now or datetime.now(timezone.utc)).isoformat()
        self.consecutive_denials += 1
        self.last_denied_at = ts
        self.last_denied_query = query
        if self.consecutive_denials >= self.max_consecutive_denials:
            self.guessing_paused = True
            pause_duration = 86400  # 24 hours in seconds
            pause_end = (now or datetime.now(timezone.utc)).timestamp() + pause_duration
            self.pause_until = datetime.fromtimestamp(pause_end, tz=timezone.utc).isoformat()

    def record_positive_feedback(self) -> None:
        self.consecutive_denials = 0
        self.guessing_paused = False
        self.pause_until = ""

    def can_guess(self, now: datetime | None = None) -> bool:
        if not self.guessing_paused:
            return True
        if not self.pause_until:
            return False
        try:
            from .timeutil import parse_utc
            pause_dt = parse_utc(self.pause_until)
            if pause_dt is None:
                return False
            return (now or datetime.now(timezone.utc)) >= pause_dt
        except (ValueError, TypeError):
            return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": RESTRAINT_SCHEMA_VERSION,
            "consecutive_denials": self.consecutive_denials,
            "guessing_paused": self.guessing_paused,
            "pause_until": self.pause_until,
            "can_guess": self.can_guess(),
        }


@dataclass
class CandidateEvaluation:
    """Evaluation of a candidate/provisional/confidence signal."""

    source: str = ""
    confidence: float = 0.0
    is_owner_approval: bool = False
    approval_decision: ApprovalDecision | None = None
    is_provisional: bool = False
    is_candidate: bool = False
    has_evidence: bool = False
    verdict: str = ""

    def evaluate(self) -> str:
        """Determine whether the signal qualifies as a valid action."""
        if self.approval_decision is not None:
            decision = self.approval_decision
            approved_purposes = {
                ApprovalPurpose.APPROVE_FOR_VISIBILITY,
                ApprovalPurpose.APPROVE_FOR_WORKING,
                ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
            }
            if decision.purpose in approved_purposes and decision.reviewer and decision.reviewed_at:
                self.verdict = "valid_owner_approval"
                return self.verdict
        if self.is_owner_approval:
            self.verdict = "unverified_owner_claim_not_approval"
            return self.verdict
        if self.is_provisional:
            self.verdict = "provisional_not_approval"
            return self.verdict
        if self.is_candidate:
            self.verdict = "candidate_not_approval"
            return self.verdict
        if self.confidence > 0.9 and not self.has_evidence:
            self.verdict = "model_confidence_not_approval"
            return self.verdict
        self.verdict = "silence_not_approval"
        return self.verdict

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": RESTRAINT_SCHEMA_VERSION,
            "source": self.source,
            "confidence": self.confidence,
            "is_owner_approval": self.is_owner_approval,
            "approval_decision_present": self.approval_decision is not None,
            "is_provisional": self.is_provisional,
            "is_candidate": self.is_candidate,
            "has_evidence": self.has_evidence,
            "verdict": self.verdict,
        }


@dataclass
class SessionPriority:
    """Tracks session priority: explicit request over historical anchors."""

    has_explicit_request: bool = False
    task_anchor_present: bool = False
    proposal_present: bool = False
    digest_present: bool = False
    reflection_present: bool = False
    priority: str = "explicit_request"

    def evaluate_priority(self) -> str:
        if self.has_explicit_request:
            self.priority = "explicit_request"
        elif self.task_anchor_present:
            self.priority = "task_anchor"
        elif self.proposal_present:
            self.priority = "proposal"
        elif self.digest_present:
            self.priority = "digest"
        elif self.reflection_present:
            self.priority = "reflection"
        else:
            self.priority = "none"
        return self.priority

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": RESTRAINT_SCHEMA_VERSION,
            "has_explicit_request": self.has_explicit_request,
            "priority": self.priority,
        }