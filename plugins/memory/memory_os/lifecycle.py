"""
Memory-OS lifecycle state machine — working → candidate → crystallized.

Defines the typed state transitions for memory items as they progress
through the lifecycle pipeline.  Replaces ad-hoc state checks with a
single authoritative state machine.

State machine
=============
working → candidate → crystallized (permanent)
                ↓
            deferred / rejected / revoked
                ↓
            expired

Terminal states: crystallized, expired, revoked
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from .timeutil import parse_utc, now_utc, safe_compare

LIFECYCLE_SCHEMA_VERSION = "memory-os.lifecycle.v1"


class LifecycleStage(str, Enum):
    """Stages in the memory lifecycle."""

    WORKING = "working"
    CANDIDATE = "candidate"
    CRYSTALLIZED = "crystallized"
    DEFERRED = "deferred"
    REJECTED = "rejected"
    REVOKED = "revoked"
    EXPIRED = "expired"


class LifecycleTransition(str, Enum):
    """Allowed transitions between lifecycle stages."""

    WORKING_TO_CANDIDATE = "working→candidate"
    CANDIDATE_TO_CRYSTALLIZED = "candidate→crystallized"
    CANDIDATE_TO_DEFERRED = "candidate→deferred"
    CANDIDATE_TO_REJECTED = "candidate→rejected"
    CRYSTALLIZED_TO_REVOKED = "crystallized→revoked"
    DEFERRED_TO_CANDIDATE = "deferred→candidate"
    DEFERRED_TO_EXPIRED = "deferred→expired"
    REJECTED_TO_CANDIDATE = "rejected→candidate"


# ── Terminal states: no further transitions allowed ─────────────────────────
_TERMINAL_STAGES: frozenset[LifecycleStage] = frozenset({
    LifecycleStage.CRYSTALLIZED,
    LifecycleStage.EXPIRED,
    LifecycleStage.REVOKED,
})

# ── Allowed transition matrix ──────────────────────────────────────────────
_ALLOWED_TRANSITIONS: dict[LifecycleStage, set[LifecycleStage]] = {
    LifecycleStage.WORKING: {LifecycleStage.CANDIDATE},
    LifecycleStage.CANDIDATE: {
        LifecycleStage.CRYSTALLIZED,
        LifecycleStage.DEFERRED,
        LifecycleStage.REJECTED,
    },
    LifecycleStage.CRYSTALLIZED: {LifecycleStage.REVOKED},
    LifecycleStage.DEFERRED: {LifecycleStage.CANDIDATE, LifecycleStage.EXPIRED},
    LifecycleStage.REJECTED: {LifecycleStage.CANDIDATE},
    LifecycleStage.REVOKED: set(),
    LifecycleStage.EXPIRED: set(),
}


@dataclass
class LifecycleState:
    """Current lifecycle state of a memory item."""

    stage: str = LifecycleStage.WORKING.value
    item_id: str = ""
    transition_history: list[dict[str, Any]] = field(default_factory=list)
    last_transition_at: str = ""
    expires_at: str = ""
    rejection_count: int = 0
    defer_reason: str = ""
    rejection_reason: str = ""


@dataclass
class LifecycleTransitionRecord:
    """A single transition record in the history."""

    from_stage: str
    to_stage: str
    transition: str
    timestamp: str
    reason: str = ""
    actor: str = "system"


def is_terminal(stage: str) -> bool:
    """Return True if the stage is terminal."""
    return LifecycleStage(stage) in _TERMINAL_STAGES


def is_allowed_transition(from_stage: str, to_stage: str) -> bool:
    """Return True if the transition is allowed."""
    try:
        from_enum = LifecycleStage(from_stage)
        to_enum = LifecycleStage(to_stage)
    except ValueError:
        return False
    allowed = _ALLOWED_TRANSITIONS.get(from_enum, set())
    return to_enum in allowed


def transition(
    state: LifecycleState,
    to_stage: str,
    *,
    reason: str = "",
    actor: str = "system",
    now: datetime | None = None,
) -> LifecycleState:
    """Transition the lifecycle state to a new stage.

    Raises ValueError if the transition is not allowed.
    """
    ref = now or now_utc()
    from_stage = state.stage

    if not is_allowed_transition(from_stage, to_stage):
        raise ValueError(
            f"Transition '{from_stage}→{to_stage}' is not allowed"
        )

    transition_name = f"{from_stage}→{to_stage}"
    ts = ref.isoformat()

    record = LifecycleTransitionRecord(
        from_stage=from_stage,
        to_stage=to_stage,
        transition=transition_name,
        timestamp=ts,
        reason=reason,
        actor=actor,
    )

    state.stage = to_stage
    state.last_transition_at = ts
    state.transition_history.append(asdict(record))

    if to_stage == LifecycleStage.REJECTED.value:
        state.rejection_count += 1
        state.rejection_reason = reason
    if to_stage == LifecycleStage.DEFERRED.value:
        state.defer_reason = reason

    return state


def stage_order(stage: str) -> int:
    """Return the numeric order of a lifecycle stage.

    Lower numbers are earlier in the lifecycle.
    """
    order = {
        LifecycleStage.WORKING.value: 0,
        LifecycleStage.CANDIDATE.value: 1,
        LifecycleStage.DEFERRED.value: 2,
        LifecycleStage.REJECTED.value: 2,
        LifecycleStage.CRYSTALLIZED.value: 3,
        LifecycleStage.REVOKED.value: 4,
        LifecycleStage.EXPIRED.value: 5,
    }
    return order.get(stage, 99)


def infer_stage_from_bridge(bridge_state: str) -> str:
    """Infer lifecycle stage from a bridge_state string.

    Returns the lifecycle stage that corresponds to a given bridge_state.
    """
    bridge_to_stage = {
        "": LifecycleStage.WORKING.value,
        "inner_drive_candidate": LifecycleStage.CANDIDATE.value,
        "reflect_owner_review_candidate": LifecycleStage.CANDIDATE.value,
        "candidate_cluster": LifecycleStage.CANDIDATE.value,
        "owner_approved": LifecycleStage.CRYSTALLIZED.value,
        "owner_rejected": LifecycleStage.REJECTED.value,
        "owner_deferred": LifecycleStage.DEFERRED.value,
        "owner_revoked": LifecycleStage.REVOKED.value,
        "expired": LifecycleStage.EXPIRED.value,
        "provisional": LifecycleStage.CANDIDATE.value,
        "superseded": LifecycleStage.REVOKED.value,
    }
    return bridge_to_stage.get(bridge_state, LifecycleStage.WORKING.value)


def derive_stage_from_working(
    item: dict[str, Any],
    *,
    has_candidate: bool = False,
    has_crystallized: bool = False,
) -> str:
    """Derive the lifecycle stage from a working item's state.

    Examines item status, candidate presence, and crystallized presence
    to determine the most accurate lifecycle stage without relying on
    file existence alone.
    """
    status = str(item.get("status", "") or "")
    if status == "expired":
        return LifecycleStage.EXPIRED.value
    if status == "cancelled":
        return LifecycleStage.REJECTED.value
    if has_crystallized:
        return LifecycleStage.CRYSTALLIZED.value
    if has_candidate:
        return LifecycleStage.CANDIDATE.value
    if status == "deferred":
        return LifecycleStage.DEFERRED.value
    return LifecycleStage.WORKING.value


def build_lifecycle_report(state: LifecycleState) -> dict[str, Any]:
    """Build a structured lifecycle report for the state."""
    return {
        "schema_version": LIFECYCLE_SCHEMA_VERSION,
        "item_id": state.item_id,
        "stage": state.stage,
        "is_terminal": is_terminal(state.stage),
        "last_transition_at": state.last_transition_at,
        "expires_at": state.expires_at,
        "rejection_count": state.rejection_count,
        "defer_reason": state.defer_reason,
        "rejection_reason": state.rejection_reason,
        "transition_count": len(state.transition_history),
    }