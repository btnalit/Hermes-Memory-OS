"""Approval state primitives for Memory-OS."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ApprovalPurpose(str, Enum):
    APPROVE_FOR_VISIBILITY = "approve_for_visibility"
    APPROVE_FOR_WORKING = "approve_for_working"
    APPROVE_FOR_CRYSTALLIZED = "approve_for_crystallized"
    REJECT = "reject"
    DEFER = "defer"


@dataclass(frozen=True)
class ApprovalDecision:
    candidate_id: str
    purpose: ApprovalPurpose
    reviewer: str
    reviewed_at: str
    note: str = ""
    source_state: str = ""
    provisional: bool = False
    expires_at: str | None = None
    recurrence: int = 0
    external_evidence_ack: bool = False
    acked_external_ref: str | None = None

    @property
    def allows_crystallized_write(self) -> bool:
        return self.purpose is ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED


def approval_from_cw019_state(
    *,
    candidate_id: str,
    cw019_state: str,
    reviewer: str,
    reviewed_at: str,
) -> ApprovalDecision:
    """Map CW-019 review states without upgrading them to crystallized approval."""

    purpose = {
        "owner_eligible": ApprovalPurpose.APPROVE_FOR_VISIBILITY,
        "owner_declined": ApprovalPurpose.REJECT,
        "owner_defer": ApprovalPurpose.DEFER,
    }.get(cw019_state, ApprovalPurpose.DEFER)
    return ApprovalDecision(
        candidate_id=candidate_id,
        purpose=purpose,
        reviewer=reviewer,
        reviewed_at=reviewed_at,
        source_state=cw019_state,
    )
