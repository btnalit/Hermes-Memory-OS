"""
Proposal and token state machine for Memory-OS.

Extends the lifecycle state machine with proposal-specific and token-specific
state transitions.  Proposals go through their own lifecycle independent of
the memory item lifecycle, and tokens represent the active review surface
that the owner interacts with.

Proposal states:
    drafted → submitted → approved_for_proposal → applied / rejected / expired
    drafted → cancelled

Token states:
    active → approved / rejected / deferred / revoked
    deferred → active / expired
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from .timeutil import now_utc, parse_utc, safe_compare

PROPOSAL_SCHEMA_VERSION = "memory-os.proposal_state.v1"
TOKEN_SCHEMA_VERSION = "memory-os.token_state.v1"


class ProposalStage(str, Enum):
    """Stages in the proposal lifecycle."""

    DRAFTED = "drafted"
    SUBMITTED = "submitted"
    APPROVED_FOR_PROPOSAL = "approved_for_proposal"
    APPLIED = "applied"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class TokenStage(str, Enum):
    """Stages in the token lifecycle."""

    ACTIVE = "active"
    APPROVED = "approved"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    REVOKED = "revoked"
    EXPIRED = "expired"


# ── Terminal states ─────────────────────────────────────────────────────────
_PROPOSAL_TERMINAL: frozenset[ProposalStage] = frozenset({
    ProposalStage.APPLIED,
    ProposalStage.REJECTED,
    ProposalStage.EXPIRED,
    ProposalStage.CANCELLED,
})

_TOKEN_TERMINAL: frozenset[TokenStage] = frozenset({
    TokenStage.APPROVED,
    TokenStage.REJECTED,
    TokenStage.REVOKED,
    TokenStage.EXPIRED,
})

# ── Allowed transitions ────────────────────────────────────────────────────
_PROPOSAL_TRANSITIONS: dict[ProposalStage, set[ProposalStage]] = {
    ProposalStage.DRAFTED: {ProposalStage.SUBMITTED, ProposalStage.CANCELLED},
    ProposalStage.SUBMITTED: {ProposalStage.APPROVED_FOR_PROPOSAL, ProposalStage.REJECTED, ProposalStage.CANCELLED},
    ProposalStage.APPROVED_FOR_PROPOSAL: {ProposalStage.APPLIED, ProposalStage.REJECTED, ProposalStage.EXPIRED},
    ProposalStage.APPLIED: set(),
    ProposalStage.REJECTED: set(),
    ProposalStage.EXPIRED: set(),
    ProposalStage.CANCELLED: set(),
}

_TOKEN_TRANSITIONS: dict[TokenStage, set[TokenStage]] = {
    TokenStage.ACTIVE: {TokenStage.APPROVED, TokenStage.REJECTED, TokenStage.DEFERRED, TokenStage.REVOKED},
    TokenStage.APPROVED: set(),
    TokenStage.REJECTED: set(),
    TokenStage.DEFERRED: {TokenStage.ACTIVE, TokenStage.EXPIRED},
    TokenStage.REVOKED: set(),
    TokenStage.EXPIRED: set(),
}


@dataclass
class ProposalState:
    """State of a proposal."""

    proposal_id: str = ""
    stage: str = ProposalStage.DRAFTED.value
    candidate_id: str = ""
    body_summary: str = ""
    created_at: str = ""
    transition_history: list[dict[str, Any]] = field(default_factory=list)
    rejection_reason: str = ""
    expiry_reason: str = ""


@dataclass
class TokenState:
    """State of a review token."""

    token_id: str = ""
    stage: str = TokenStage.ACTIVE.value
    proposal_id: str = ""
    owner_action: str = ""
    created_at: str = ""
    transition_history: list[dict[str, Any]] = field(default_factory=list)
    deferred_until: str = ""
    defer_reason: str = ""
    rejection_reason: str = ""
    revoked_reason: str = ""


def is_proposal_terminal(stage: str) -> bool:
    try:
        return ProposalStage(stage) in _PROPOSAL_TERMINAL
    except ValueError:
        return False


def is_token_terminal(stage: str) -> bool:
    try:
        return TokenStage(stage) in _TOKEN_TERMINAL
    except ValueError:
        return False


def is_allowed_proposal_transition(from_stage: str, to_stage: str) -> bool:
    try:
        from_enum = ProposalStage(from_stage)
        to_enum = ProposalStage(to_stage)
    except ValueError:
        return False
    return to_enum in _PROPOSAL_TRANSITIONS.get(from_enum, set())


def is_allowed_token_transition(from_stage: str, to_stage: str) -> bool:
    try:
        from_enum = TokenStage(from_stage)
        to_enum = TokenStage(to_stage)
    except ValueError:
        return False
    return to_enum in _TOKEN_TRANSITIONS.get(from_enum, set())


def transition_proposal(
    state: ProposalState,
    to_stage: str,
    *,
    reason: str = "",
    now: datetime | None = None,
) -> ProposalState:
    ref = now or now_utc()
    from_stage = state.stage
    if not is_allowed_proposal_transition(from_stage, to_stage):
        raise ValueError(
            f"Proposal transition '{from_stage}→{to_stage}' is not allowed"
        )
    ts = ref.isoformat()
    record = {
        "from_stage": from_stage,
        "to_stage": to_stage,
        "timestamp": ts,
        "reason": reason,
    }
    state.stage = to_stage
    state.transition_history.append(record)
    if to_stage == ProposalStage.REJECTED.value:
        state.rejection_reason = reason
    elif to_stage == ProposalStage.EXPIRED.value:
        state.expiry_reason = reason
    return state


def transition_token(
    state: TokenState,
    to_stage: str,
    *,
    reason: str = "",
    now: datetime | None = None,
) -> TokenState:
    ref = now or now_utc()
    from_stage = state.stage
    if not is_allowed_token_transition(from_stage, to_stage):
        raise ValueError(
            f"Token transition '{from_stage}→{to_stage}' is not allowed"
        )
    ts = ref.isoformat()
    record = {
        "from_stage": from_stage,
        "to_stage": to_stage,
        "timestamp": ts,
        "reason": reason,
    }
    state.stage = to_stage
    state.transition_history.append(record)
    if to_stage == TokenStage.DEFERRED.value:
        state.defer_reason = reason
    elif to_stage == TokenStage.REJECTED.value:
        state.rejection_reason = reason
    elif to_stage == TokenStage.REVOKED.value:
        state.revoked_reason = reason
    return state


def infer_proposal_stage_from_state(state_str: str) -> str:
    mapping = {
        "": ProposalStage.DRAFTED.value,
        "draft": ProposalStage.DRAFTED.value,
        "submitted": ProposalStage.SUBMITTED.value,
        "approved_for_proposal": ProposalStage.APPROVED_FOR_PROPOSAL.value,
        "approved": ProposalStage.APPROVED_FOR_PROPOSAL.value,
        "applied": ProposalStage.APPLIED.value,
        "rejected": ProposalStage.REJECTED.value,
        "expired": ProposalStage.EXPIRED.value,
        "cancelled": ProposalStage.CANCELLED.value,
    }
    return mapping.get(state_str.lower().strip(), ProposalStage.DRAFTED.value)


def infer_token_stage_from_action(action: str) -> str:
    mapping = {
        "": TokenStage.ACTIVE.value,
        "approve": TokenStage.APPROVED.value,
        "reject": TokenStage.REJECTED.value,
        "defer": TokenStage.DEFERRED.value,
        "revoke": TokenStage.REVOKED.value,
    }
    return mapping.get(action.lower().strip(), TokenStage.ACTIVE.value)


def build_proposal_report(state: ProposalState) -> dict[str, Any]:
    return {
        "schema_version": PROPOSAL_SCHEMA_VERSION,
        "proposal_id": state.proposal_id,
        "stage": state.stage,
        "is_terminal": is_proposal_terminal(state.stage),
        "transition_count": len(state.transition_history),
        "rejection_reason": state.rejection_reason,
        "expiry_reason": state.expiry_reason,
    }


def build_token_report(state: TokenState) -> dict[str, Any]:
    return {
        "schema_version": TOKEN_SCHEMA_VERSION,
        "token_id": state.token_id,
        "stage": state.stage,
        "is_terminal": is_token_terminal(state.stage),
        "proposal_id": state.proposal_id,
        "deferred_until": state.deferred_until,
        "transition_count": len(state.transition_history),
    }