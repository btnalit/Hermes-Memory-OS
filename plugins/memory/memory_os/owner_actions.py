"""Owner review and action state machine for Memory-OS."""

from __future__ import annotations

import json
import sqlite3
import hashlib
import subprocess
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .approval import ApprovalDecision, ApprovalPurpose
from .audit import append_audit
from .config import load_config
from .crystallized import (
    CrystallizedCandidate,
    CrystallizedMemoryService,
    is_active_crystallized_frontmatter,
    read_candidate_queue,
    read_candidate_triage,
    resolve_candidate_effective_state,
)
from .memory_sources import (
    ALLOWED_FEEDBACK_RATINGS,
    POLICY_APPLY_SCHEMA_VERSION,
    POLICY_SCHEMA_VERSION,
    append_memory_source_feedback_record,
    memory_sources_feedback_path,
    memory_sources_policy_applies_path,
    memory_sources_policy_path,
    read_memory_sources_policy,
    read_memory_source_feedback_records,
    read_memory_source_records,
)
from .read_model_paths import owner_actions_path as _owner_actions_path
from .roots import MemoryOSRoots
from .jsonl_io import append_jsonl_locked, build_error_record
from .store import MemoryOSStore
from .candidate_clusters import (
    candidate_cluster_action_target,
    candidate_cluster_scope,
    find_candidate_cluster_by_target,
    build_candidate_clusters,
)


OWNER_ACTION_SCHEMA_VERSION = "memory-os.owner_action.v0"
OWNER_REVIEW_STATUS_SCHEMA_VERSION = "memory-os.owner_review_status.v0"
OWNER_REVIEW_QUEUE_SCHEMA_VERSION = "memory-os.owner_review_queue.v0"
OWNER_REVIEW_AGING_SCHEMA_VERSION = "memory-os.owner_review_aging.v0"
OWNER_REVIEW_CHANNEL_SCHEMA_VERSION = "memory-os.owner_review_channel.v0"
OWNER_REVIEW_DIGEST_PREVIEW_SCHEMA_VERSION = "memory-os.owner_review_digest_preview.v0"
OWNER_REVIEW_RENDERED_DIGEST_SCHEMA_VERSION = "memory-os.owner_review_rendered_digest.v0"
OWNER_REVIEW_SURFACE_SCHEMA_VERSION = "memory-os.owner_review_surface.v0"
OWNER_REVIEW_REPLY_SCHEMA_VERSION = "memory-os.owner_review_reply.v0"
OWNER_REVIEW_DELIVERY_GATE_SCHEMA_VERSION = "memory-os.owner_review_delivery_gate.v0"
OWNER_REVIEW_DELIVERY_SCHEMA_VERSION = "memory-os.owner_review_delivery.v0"
OWNER_REVIEW_DELIVERY_STATUS_SCHEMA_VERSION = "memory-os.owner_review_delivery_status.v0"
OWNER_REVIEW_CRON_INTEGRATION_SCHEMA_VERSION = "memory-os.owner_review_cron_integration.v0"
APPROVED_PROPOSAL_FOLLOWUPS_SCHEMA_VERSION = "memory-os.approved_proposal_followups.v0"
OWNER_BURDEN_BUDGET_SCHEMA_VERSION = "memory-os.owner_burden_budget.v0"
APPROVED_PROPOSAL_OPS_GATE_SCHEMA_VERSION = "memory-os.approved_proposal_ops_gate.v0"
APPROVED_PROPOSAL_OPS_GATE_BATCH_SCHEMA_VERSION = "memory-os.approved_proposal_ops_gate_batch.v0"
PROPOSAL_FOLLOWUP_AUTO_ROUTE_SCHEMA_VERSION = "memory-os.proposal_followup_auto_route.v0"
APPROVED_PROPOSAL_EXECUTION_APPLY_SCHEMA_VERSION = "memory-os.approved_proposal_execution_apply.v0"
APPROVED_PROPOSAL_EXECUTION_TICKET_SCHEMA_VERSION = "memory-os.approved_proposal_execution_ticket.v0"
OWNER_ACTION_RESULT_SCHEMA_VERSION = "memory-os.owner_action_result.v0"
SPEAK_PERMISSION_SCHEMA_VERSION = "memory-os.speak_permission_ticket.v0"
EXPRESSION_FEEDBACK_SCHEMA_VERSION = "memory-os.expression_feedback.v0"
OWNER_REVIEW_TEXT_LIMIT = 2400
OWNER_REVIEW_DELIVERY_ADAPTERS = {"hermes_owner_channel", "hermes_send"}
LEFT_BRAIN_REVIEW_SUGGESTED_PER_SOURCE_CAP = 2
OWNER_BURDEN_ACTION_REQUIRED_CAP = 5
OWNER_BURDEN_REVIEW_SUGGESTED_CAP = 20
OWNER_BURDEN_FYI_CAP = 20
OWNER_BURDEN_STALE_CAP = 0
PROPOSAL_FOLLOWUP_AUTO_ROUTE_SAFE_KINDS = {"proposal"}
PROPOSAL_FOLLOWUP_AUTO_ROUTE_TRUE_BLOCK_KEYS = {
    "actual_send",
    "actual_execute",
    "actual_identity_write",
    "actual_relationship_write",
    "actual_unapproved_crystallized_approval",
    "actual_crystallized_approval",
    "crystallized_approved",
    "execution_ticket_created",
    "requires_execution_ticket",
    "policy_written",
    "memory_sources_policy_written",
    "legacy_template_cleanup_written",
    "deep_reflection_policy_written",
    "relationship_written",
    "identity_written",
    "canonical_memory_written",
}
PROPOSAL_FOLLOWUP_AUTO_ROUTE_COUNT_BLOCK_KEYS = {
    "execution_ticket_count",
    "ticket_created_count",
    "policy_apply_count",
    "memory_sources_policy_apply_count",
    "legacy_template_cleanup_apply_count",
    "deep_reflection_policy_apply_count",
    "relationship_write_count",
    "identity_write_count",
    "canonical_memory_write_count",
}
PROPOSAL_FOLLOWUP_AUTO_ROUTE_BOUNDARY_KEYS = {
    "actual_send",
    "actual_execute",
    "actual_identity_write",
    "actual_relationship_write",
    "actual_unapproved_crystallized_approval",
    "actual_crystallized_approval",
}
PROPOSAL_FOLLOWUP_AUTO_ROUTE_SAMPLE_WINDOW_DAYS = 7
PROPOSAL_FOLLOWUP_AUTO_ROUTE_FULL_AUTO_MIN_SAMPLES = 20
PROPOSAL_FOLLOWUP_AUTO_ROUTE_FULL_AUTO_AGREEMENT_RATE = 0.90
PROPOSAL_FOLLOWUP_AUTO_ROUTE_FULL_AUTO_WILSON_LOWER_BOUND = 0.80
PROPOSAL_FOLLOWUP_AUTO_ROUTE_LIMITED_AUTO_MIN_SAMPLES = 3
PROPOSAL_FOLLOWUP_AUTO_ROUTE_FIRST_CANARY_DAILY_CAP = 1
PROPOSAL_FOLLOWUP_AUTO_ROUTE_AFTER_SUCCESSFUL_LIMITED_ROUTES = 3
PROPOSAL_FOLLOWUP_AUTO_ROUTE_EXPANDED_DAILY_CAP = 3
HINDSIGHT_CURATION_ACTION_TYPES = {
    "retain_hindsight_curation",
    "reject_hindsight_curation",
    "demote_hindsight_curation",
}

EXPRESSION_FEEDBACK_ACTION_TYPES = {
    "like_expression",
    "too_mechanical",
    "too_frequent",
    "boundary_private",
    "off_voice",
    "mute_period",
}

EXPRESSION_FEEDBACK_DIGEST_ACTIONS = (
    "like_expression",
    "too_mechanical",
    "too_frequent",
    "boundary_private",
    "off_voice",
)

ACTION_TYPES = {
    "approve_candidate",
    "reject_candidate",
    "approve_candidate_cluster",
    "reject_candidate_cluster",
    "defer_candidate_cluster",
    "revoke_crystallized",
    "demote_crystallized",
    "mark_feedback",
    "approve_proposal",
    "reject_proposal",
    "apply_proposal",
    "allow_speak_once",
    "approve_session_mirror_apply",
    *HINDSIGHT_CURATION_ACTION_TYPES,
    *EXPRESSION_FEEDBACK_ACTION_TYPES,
    "approve_edge",
    "reject_edge",
    "approve_external_evidence",
    "confirm_provisional_crystallized_record",
    "reject_provisional_crystallized_record",
    "confirm_provisional_knob_override",
    "reject_provisional_knob_override",
}

TERMINAL_ACTIONS_BY_TARGET_TYPE = {
    "candidate": {"approve_candidate", "reject_candidate", "approve_external_evidence"},
    "candidate_cluster": {"approve_candidate_cluster", "reject_candidate_cluster", "defer_candidate_cluster"},
    "crystallized_record": {"revoke_crystallized", "demote_crystallized"},
    "proposal": {"approve_proposal", "reject_proposal", "apply_proposal"},
    "memory_source": {"mark_feedback"},
    "speak": {"allow_speak_once"},
    "session_mirror_apply": {"approve_session_mirror_apply"},
    "hindsight_curation": HINDSIGHT_CURATION_ACTION_TYPES,
    "expression": EXPRESSION_FEEDBACK_ACTION_TYPES,
    "provisional_crystallized_record": {
        "confirm_provisional_crystallized_record",
        "reject_provisional_crystallized_record",
    },
    "edge": {"approve_edge", "reject_edge"},
}


def owner_actions_path(roots: MemoryOSRoots) -> Path:
    return _owner_actions_path(roots)


def feedback_ledger_path(roots: MemoryOSRoots) -> Path:
    return roots.memory_os_root / "system" / "feedback_ledger.jsonl"


def crystallization_approvals_path(roots: MemoryOSRoots) -> Path:
    return roots.memory_os_root / "system" / "crystallization_approvals.jsonl"


def proposal_action_ledger_path(roots: MemoryOSRoots) -> Path:
    return roots.memory_os_root / "system" / "proposal_action_ledger.jsonl"


def speak_permission_tickets_path(roots: MemoryOSRoots) -> Path:
    return roots.memory_os_root / "system" / "speak_permission_tickets.jsonl"


def hindsight_curation_decisions_path(roots: MemoryOSRoots) -> Path:
    return roots.memory_os_root / "system" / "hindsight_curation_decisions.jsonl"


def approved_proposal_execution_tickets_path(roots: MemoryOSRoots) -> Path:
    return roots.memory_os_root / "system" / "approved_proposal_execution_tickets.jsonl"


def deep_reflection_policy_path(roots: MemoryOSRoots) -> Path:
    return roots.hermes_home / "system-modules" / "deep_reflection" / "policy.json"


def deep_reflection_policy_applies_path(roots: MemoryOSRoots) -> Path:
    return roots.hermes_home / "system-modules" / "deep_reflection" / "policy_applies.jsonl"


def expression_feedback_ledger_path(roots: MemoryOSRoots) -> Path:
    return roots.memory_os_root / "system" / "expression_feedback_ledger.jsonl"


def right_brain_expression_outcomes_path(roots: MemoryOSRoots) -> Path:
    return roots.hermes_home / "system-modules" / "right_brain_expression_adapter" / "outcomes.jsonl"


def owner_review_deliveries_path(roots: MemoryOSRoots) -> Path:
    return roots.memory_os_root / "system" / "owner_review_deliveries.jsonl"


def owner_review_rendered_digests_path(roots: MemoryOSRoots) -> Path:
    return roots.memory_os_root / "system" / "owner_review_rendered_digests.jsonl"


def owner_review_cron_helper_path(roots: MemoryOSRoots) -> Path:
    return roots.hermes_home / "scripts" / "memory_os_owner_review_digest.py"


def owner_review_status_report(store: MemoryOSStore) -> dict[str, Any]:
    actions = read_owner_action_records(store.roots)
    queue = owner_review_queue_report(store, limit=100)
    aging = queue.get("review_aging") if isinstance(queue.get("review_aging"), dict) else owner_review_aging_report(store)
    by_type = Counter(str(record.get("action_type", "")) for record in actions)
    by_result = Counter(str(record.get("result", "")) for record in actions)
    owner_active_period = _owner_active_period(actions)
    duplicate_ignored_count = int(by_result.get("duplicate_ignored", 0))
    error_count = int(by_result.get("error", 0))
    owner_approved_crystallized_write_count = sum(
        1 for record in actions if (record.get("owner_effect") or {}).get("owner_approved_crystallized_write")
    )
    owner_revoked_crystallized_count = sum(
        1 for record in actions if (record.get("owner_effect") or {}).get("owner_revoked_crystallized_record")
    )
    owner_demoted_crystallized_count = sum(
        1 for record in actions if (record.get("owner_effect") or {}).get("owner_demoted_crystallized_record")
    )
    unapproved_crystallized_write_count = sum(
        1
        for record in actions
        if (record.get("boundary") or {}).get("actual_unapproved_crystallized_approval")
    )
    return {
        "schema_version": OWNER_REVIEW_STATUS_SCHEMA_VERSION,
        "profile": store.roots.profile or "default",
        "review_channel": resolve_owner_review_channel(store),
        "review_queue": {
            "pending_count": queue["pending_count"],
            "action_required_count": queue["action_required_count"],
            "review_suggested_count": queue["review_suggested_count"],
            "fyi_count": queue["fyi_count"],
            "raw_action_required_count": aging.get("raw_action_required_count"),
            "effective_action_required_count": aging.get("effective_action_required_count"),
            "aged_to_review_suggested_count": aging.get("aged_to_review_suggested_count"),
            "aged_to_fyi_count": aging.get("aged_to_fyi_count"),
            "stale_count": 0,
            "overflow_count": queue["overflow_count"],
        },
        "review_aging": aging,
        "owner_action_count": len(actions),
        "action_type_counts": dict(sorted(by_type.items())),
        "duplicate_ignored_count": duplicate_ignored_count,
        "error_count": error_count,
        "owner_approved_crystallized_write_count": owner_approved_crystallized_write_count,
        "unapproved_crystallized_write_count": unapproved_crystallized_write_count,
        "owner_actions": {
            "count": len(actions),
            "count_24h": len(_records_since(actions, hours=24)),
            "by_type": dict(sorted(by_type.items())),
            "duplicate_action_ignored_count": duplicate_ignored_count,
            "error_count": error_count,
            "owner_approved_crystallized_write_count": owner_approved_crystallized_write_count,
            "owner_revoked_crystallized_count": owner_revoked_crystallized_count,
            "owner_demoted_crystallized_count": owner_demoted_crystallized_count,
            "unapproved_crystallized_write_count": unapproved_crystallized_write_count,
        },
        "candidate_approved_count": int(by_type.get("approve_candidate", 0)),
        "candidate_rejected_count": int(by_type.get("reject_candidate", 0)),
        "crystallized_revoked_count": owner_revoked_crystallized_count,
        "crystallized_demoted_count": owner_demoted_crystallized_count,
        "proposal_approved_count": int(by_type.get("approve_proposal", 0)),
        "proposal_rejected_count": int(by_type.get("reject_proposal", 0)),
        "feedback_by_rating": _feedback_by_rating(actions),
        "crystallized_created_by_owner_action": sum(
            1 for record in actions if (record.get("owner_effect") or {}).get("owner_approved_crystallized_write")
        ),
        "digest_generated_count": 0,
        "digest_sent_count": 0,
        "digest_boundary_true_count": 0,
        "delivery_status": owner_review_delivery_status_report(store),
        "cron_integration": owner_review_cron_integration_report(store),
        "digest_burden": _owner_burden_budget(queue, owner_active_period=owner_active_period),
        "feedback_backflow": {
            "by_action_type": dict(sorted(by_type.items())),
            "by_route": {},
            "by_source_class": {},
            "apply_ready_count": 0,
        },
        "approved_proposal_followups": _approved_proposal_followups_summary(store),
    }


def _owner_burden_budget(queue: dict[str, Any], *, owner_active_period: bool) -> dict[str, Any]:
    pending_total = int(queue.get("pending_count") or 0)
    action_required_count = int(queue.get("action_required_count") or 0)
    review_suggested_count = int(queue.get("review_suggested_count") or 0)
    fyi_count = int(queue.get("fyi_count") or 0)
    stale_count = int((queue.get("review_aging") or {}).get("stale_count") or 0)
    over_budget = {
        "action_required": max(action_required_count - OWNER_BURDEN_ACTION_REQUIRED_CAP, 0),
        "review_suggested": max(review_suggested_count - OWNER_BURDEN_REVIEW_SUGGESTED_CAP, 0),
        "fyi": max(fyi_count - OWNER_BURDEN_FYI_CAP, 0),
        "stale": max(stale_count - OWNER_BURDEN_STALE_CAP, 0),
    }
    return {
        "schema_version": OWNER_BURDEN_BUDGET_SCHEMA_VERSION,
        "owner_active_period": owner_active_period,
        "pending_total": pending_total,
        "action_required_count": action_required_count,
        "review_suggested_count": review_suggested_count,
        "fyi_count": fyi_count,
        "informational_count": review_suggested_count + fyi_count,
        "stale_count": stale_count,
        "budget": {
            "action_required_cap": OWNER_BURDEN_ACTION_REQUIRED_CAP,
            "review_suggested_cap": OWNER_BURDEN_REVIEW_SUGGESTED_CAP,
            "fyi_cap": OWNER_BURDEN_FYI_CAP,
            "stale_cap": OWNER_BURDEN_STALE_CAP,
        },
        "over_budget": over_budget,
        "budget_status": "watch" if any(value > 0 for value in over_budget.values()) else "ok",
        "action_required_per_digest": None,
        "owner_response_latency_hours": None,
        "action_completion_rate": None if not owner_active_period else 0.0,
    }


def approved_proposal_followups_report(store: MemoryOSStore, *, limit: int = 20) -> dict[str, Any]:
    """Project owner-approved proposals into a bounded follow-up surface.

    This report is intentionally read-only. It makes approved proposals visible
    for human-controlled follow-up without creating execution tickets or
    executing work.
    """

    proposals = [item for item in _read_proposal_queue(store) if str(item.get("state") or "") == "approved_for_proposal"]
    approvals = _latest_proposal_approval_by_target(read_owner_action_records(store.roots))
    ops_gate_reviews = _ops_gate_reviews_by_proposal(store)
    policy_applies = _policy_applies_by_proposal(store)
    memory_sources_policy_applies = _memory_sources_policy_applies_by_proposal(store)
    legacy_cleanup_applies = _legacy_template_cleanup_applies_by_proposal(store)
    execution_tickets = _approved_proposal_execution_tickets_by_proposal(store)
    deep_reflection_policy_applies = _deep_reflection_policy_applies_by_proposal(store)
    items: list[dict[str, Any]] = []
    for proposal in proposals:
        proposal_id = str(proposal.get("candidate_id") or "")
        if not proposal_id:
            continue
        approval = approvals.get(proposal_id, {})
        ops_gate_review = ops_gate_reviews.get(proposal_id, {})
        policy_apply = policy_applies.get(proposal_id, {})
        memory_sources_policy_apply = memory_sources_policy_applies.get(proposal_id, {})
        legacy_cleanup_apply = legacy_cleanup_applies.get(proposal_id, {})
        execution_ticket = execution_tickets.get(proposal_id, {})
        deep_reflection_policy_apply = deep_reflection_policy_applies.get(proposal_id, {})
        apply_kind = _explicit_proposal_apply_kind(proposal)
        ticket_kind = _unsupported_proposal_execution_ticket_kind(proposal)
        if policy_apply:
            followup_state = "applied_expression_policy"
        elif memory_sources_policy_apply:
            followup_state = "applied_memory_sources_policy"
        elif legacy_cleanup_apply:
            followup_state = "applied_legacy_template_cleanup"
        elif deep_reflection_policy_apply:
            followup_state = "bounded_policy_written"
        elif execution_ticket:
            followup_state = str(execution_ticket.get("ticket_state") or "awaiting_typed_execution_plan")
        elif ops_gate_review:
            if apply_kind:
                followup_state = "supported_apply_ready"
            elif ticket_kind:
                followup_state = "unsupported_requires_execution_ticket"
            else:
                followup_state = "unsupported_apply_kind"
        else:
            followup_state = "awaiting_ops_gate_review"
        approved_at = str(approval.get("created_at") or proposal.get("updated_at") or "")
        items.append(
            {
                "schema_version": "memory-os.approved_proposal_followup_item.v0",
                "followup_id": f"proposal_followup:{proposal_id}",
                "proposal_id": proposal_id,
                "title": _bounded_text(str(proposal.get("title") or "Approved proposal"), 140),
                "source_module": "proposal_queue",
                "proposal_kind": str(proposal.get("kind") or "proposal"),
                "state": "approved_for_proposal",
                "followup_state": followup_state,
                "approved_at": approved_at,
                "owner_action_id": str(approval.get("owner_action_id") or ""),
                "owner_id": str(approval.get("owner_id") or ""),
                "ops_gate_report_id": str(ops_gate_review.get("report_id") or ""),
                "ops_gate_decision": str(ops_gate_review.get("decision") or ""),
                "policy_apply_id": str(policy_apply.get("apply_id") or ""),
                "policy_version": int(policy_apply.get("policy_version") or 0),
                "policy_written": bool(policy_apply),
                "apply_kind": apply_kind,
                "memory_sources_policy_apply_id": str(memory_sources_policy_apply.get("apply_id") or ""),
                "memory_sources_policy_version": int(memory_sources_policy_apply.get("policy_version") or 0),
                "memory_sources_policy_written": bool(memory_sources_policy_apply),
                "legacy_template_cleanup_apply_id": str(legacy_cleanup_apply.get("apply_id") or ""),
                "legacy_template_closed_count": int(legacy_cleanup_apply.get("closed_count") or 0),
                "deep_reflection_policy_apply_id": str(deep_reflection_policy_apply.get("apply_id") or ""),
                "deep_reflection_policy_version": int(deep_reflection_policy_apply.get("policy_version") or 0),
                "deep_reflection_policy_written": bool(deep_reflection_policy_apply),
                "execution_ticket_id": str(execution_ticket.get("ticket_id") or ""),
                "execution_ticket_type": str(execution_ticket.get("ticket_type") or ticket_kind),
                "execution_ticket_state": str(execution_ticket.get("ticket_state") or ""),
                "evidence_refs": _safe_list(execution_ticket.get("evidence_refs")),
                "evidence_required": _safe_list(execution_ticket.get("evidence_required")),
                "rollback": _bounded_text(str(execution_ticket.get("rollback") or ""), 260),
                "suggested_path": _bounded_text(str(execution_ticket.get("suggested_path") or ""), 260),
                "safe_source_ids": _safe_list(proposal.get("source_refs")),
                "next_step": _proposal_followup_next_step(followup_state),
                "execution_ticket_created": bool(execution_ticket),
                "actual_execute": False,
                "raw_body_included": False,
            }
        )
    items = sorted(items, key=lambda item: (str(item.get("approved_at") or ""), str(item.get("proposal_id") or "")), reverse=True)
    bounded_limit = max(int(limit), 0)
    shown = items[:bounded_limit]
    awaiting_ops_gate_count = sum(1 for item in items if item.get("followup_state") == "awaiting_ops_gate_review")
    supported_apply_ready_count = sum(1 for item in items if item.get("followup_state") == "supported_apply_ready")
    unsupported_requires_execution_ticket_count = sum(
        1 for item in items if item.get("followup_state") == "unsupported_requires_execution_ticket"
    )
    unsupported_apply_kind_count = sum(1 for item in items if item.get("followup_state") == "unsupported_apply_kind")
    ops_gate_reviewed_count = (
        supported_apply_ready_count + unsupported_requires_execution_ticket_count + unsupported_apply_kind_count
    )
    ticket_created_count = sum(1 for item in items if item.get("execution_ticket_created") is True)
    awaiting_typed_execution_plan_count = sum(
        1 for item in items if item.get("followup_state") == "awaiting_typed_execution_plan"
    )
    evidence_resolved_count = sum(1 for item in items if item.get("followup_state") == "evidence_resolved")
    bounded_policy_written_count = sum(1 for item in items if item.get("followup_state") == "bounded_policy_written")
    policy_apply_count = sum(1 for item in items if item.get("followup_state") == "applied_expression_policy")
    memory_sources_policy_apply_count = sum(
        1 for item in items if item.get("followup_state") == "applied_memory_sources_policy"
    )
    legacy_cleanup_apply_count = sum(
        1 for item in items if item.get("followup_state") == "applied_legacy_template_cleanup"
    )
    return {
        "schema_version": APPROVED_PROPOSAL_FOLLOWUPS_SCHEMA_VERSION,
        "profile": store.roots.profile or "default",
        "status": "ok",
        "approved_proposal_count": len(proposals),
        "pending_followup_count": awaiting_ops_gate_count,
        "open_followup_count": sum(
            1
            for item in items
            if item.get("followup_state")
            not in {
                "applied_expression_policy",
                "applied_memory_sources_policy",
                "applied_legacy_template_cleanup",
                "evidence_resolved",
                "bounded_policy_written",
            }
        ),
        "shown_count": len(shown),
        "overflow_count": max(len(items) - bounded_limit, 0),
        "awaiting_ops_gate_count": awaiting_ops_gate_count,
        "ops_gate_reviewed_count": ops_gate_reviewed_count,
        "supported_apply_ready_count": supported_apply_ready_count,
        "unsupported_requires_execution_ticket_count": unsupported_requires_execution_ticket_count,
        "unsupported_apply_kind_count": unsupported_apply_kind_count,
        "awaiting_explicit_execution_count": supported_apply_ready_count + unsupported_requires_execution_ticket_count,
        "ticket_created_count": ticket_created_count,
        "awaiting_typed_execution_plan_count": awaiting_typed_execution_plan_count,
        "evidence_resolved_count": evidence_resolved_count,
        "bounded_policy_written_count": bounded_policy_written_count,
        "policy_apply_count": policy_apply_count,
        "memory_sources_policy_apply_count": memory_sources_policy_apply_count,
        "legacy_template_cleanup_apply_count": legacy_cleanup_apply_count,
        "deep_reflection_policy_apply_count": bounded_policy_written_count,
        "execution_ticket_count": ticket_created_count,
        "actual_execute": False,
        "raw_body_included": False,
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
        },
        "items": shown,
    }


def _approved_proposal_followups_summary(store: MemoryOSStore) -> dict[str, Any]:
    report = approved_proposal_followups_report(store, limit=5)
    return {
        "schema_version": report["schema_version"],
        "approved_proposal_count": report["approved_proposal_count"],
        "pending_followup_count": report["pending_followup_count"],
        "open_followup_count": report["open_followup_count"],
        "shown_count": report["shown_count"],
        "overflow_count": report["overflow_count"],
        "awaiting_ops_gate_count": report["awaiting_ops_gate_count"],
        "ops_gate_reviewed_count": report["ops_gate_reviewed_count"],
        "supported_apply_ready_count": report["supported_apply_ready_count"],
        "unsupported_requires_execution_ticket_count": report["unsupported_requires_execution_ticket_count"],
        "unsupported_apply_kind_count": report["unsupported_apply_kind_count"],
        "awaiting_explicit_execution_count": report["awaiting_explicit_execution_count"],
        "ticket_created_count": report["ticket_created_count"],
        "awaiting_typed_execution_plan_count": report["awaiting_typed_execution_plan_count"],
        "evidence_resolved_count": report["evidence_resolved_count"],
        "bounded_policy_written_count": report["bounded_policy_written_count"],
        "policy_apply_count": report["policy_apply_count"],
        "memory_sources_policy_apply_count": report["memory_sources_policy_apply_count"],
        "legacy_template_cleanup_apply_count": report["legacy_template_cleanup_apply_count"],
        "deep_reflection_policy_apply_count": report["deep_reflection_policy_apply_count"],
        "execution_ticket_count": report["execution_ticket_count"],
        "actual_execute": report["actual_execute"],
        "raw_body_included": report["raw_body_included"],
    }


def owner_review_surface_report(
    store: MemoryOSStore,
    *,
    owner_id: str = "",
    channel: str = "agent",
    operation: str = "overview",
    section: str = "all",
    anchor: str = "",
    action_token: str = "",
    offset: int = 0,
    limit: int = 5,
) -> dict[str, Any]:
    """Read-only owner review surface for Hermes agent pagination/detail.

    Hermes owns owner-facing conversation. This report gives Hermes bounded
    data for "next page", "expand R3", and approved-proposal follow-up
    questions without applying any owner action.
    """

    resolved_owner = str(owner_id or "owner")
    safe_operation = str(operation or "overview").strip().lower()
    if safe_operation not in {
        "overview",
        "page",
        "next_page",
        "detail",
        "proposal_followups",
        "expression_feedback_context",
        "memory_sources_feedback_context",
    }:
        safe_operation = "overview"
    safe_section = _safe_review_section(section)
    bounded_limit = max(min(int(limit or 5), 10), 1)
    bounded_offset = max(int(offset or 0), 0)
    if safe_operation == "detail":
        return _owner_review_surface_detail(
            store,
            owner_id=resolved_owner,
            channel=channel,
            anchor=anchor,
            action_token=action_token,
        )
    if safe_operation == "proposal_followups":
        report = approved_proposal_followups_report(store, limit=bounded_limit)
        _attach_proposal_followup_apply_actions(report)
        return {
            "schema_version": OWNER_REVIEW_SURFACE_SCHEMA_VERSION,
            "profile": store.roots.profile or "default",
            "owner_id": resolved_owner,
            "status": "ok",
            "operation": safe_operation,
            "proposal_followups": report,
            "raw_body_included": False,
            "boundary": _owner_review_false_boundary(),
        }
    if safe_operation == "expression_feedback_context":
        return _owner_review_surface_expression_feedback_context(
            store,
            owner_id=resolved_owner,
            limit=bounded_limit,
        )
    if safe_operation == "memory_sources_feedback_context":
        return _owner_review_surface_memory_sources_feedback_context(
            store,
            owner_id=resolved_owner,
            limit=bounded_limit,
        )

    queue = owner_review_queue_report(store, limit=1000)
    latest_record = _latest_owner_home_digest_record(store.roots, owner_id=resolved_owner)
    latest_rendered = _rendered_digest_from_record(latest_record) if latest_record else {}
    latest_counts = latest_rendered.get("counts") if isinstance(latest_rendered.get("counts"), dict) else {}
    offsets = _surface_offsets(
        operation=safe_operation,
        section=safe_section,
        explicit_offset=bounded_offset,
        latest_counts=latest_counts,
    )
    sections: dict[str, list[dict[str, Any]]] = {}
    next_offsets: dict[str, int] = {}
    for priority in _selected_review_sections(safe_section):
        raw_items = [item for item in queue.get("items", []) if item.get("priority") == priority]
        start = offsets.get(priority, 0)
        selected = raw_items[start : start + bounded_limit]
        sections[priority] = [
            _render_review_item(_digest_item(item), section=priority)
            for item in selected
            if isinstance(item, dict)
        ]
        next_offsets[priority] = min(start + len(selected), len(raw_items))
    return {
        "schema_version": OWNER_REVIEW_SURFACE_SCHEMA_VERSION,
        "profile": store.roots.profile or "default",
        "owner_id": resolved_owner,
        "status": "ok",
        "operation": safe_operation,
        "section": safe_section,
        "source": "latest_owner_home_digest" if latest_record else "current_queue",
        "latest_digest_id": str((latest_record or {}).get("digest_id") or ""),
        "counts": {
            "pending": queue.get("pending_count"),
            "action_required_total": queue.get("action_required_count"),
            "review_suggested_total": queue.get("review_suggested_count"),
            "fyi_total": queue.get("fyi_count"),
        },
        "offsets": offsets,
        "next_offsets": next_offsets,
        "sections": sections,
        "raw_body_included": False,
        "boundary": _owner_review_false_boundary(),
    }


def route_approved_proposal_followup_to_ops_gate(
    store: MemoryOSStore,
    *,
    proposal_id: str,
    owner_id: str = "owner",
    channel: str = "cli",
    apply: bool = False,
) -> dict[str, Any]:
    """Route an approved proposal follow-up through OpsGate report-only review.

    This is an explicit owner/operator apply path into the execution gate. It
    writes an OpsGate report only when ``apply`` is true. It never executes work
    and never creates an execution ticket.
    """

    proposal = _find_proposal(store, proposal_id)
    if not proposal:
        return _approved_proposal_ops_gate_error(
            store,
            proposal_id=proposal_id,
            owner_id=owner_id,
            channel=channel,
            reason="proposal_not_found",
            apply=apply,
        )
    if str(proposal.get("state") or "") != "approved_for_proposal":
        return _approved_proposal_ops_gate_error(
            store,
            proposal_id=proposal_id,
            owner_id=owner_id,
            channel=channel,
            reason="proposal_not_approved_for_followup",
            apply=apply,
        )

    proposed_action = _ops_gate_action_from_proposal(proposal)
    existing_review = _ops_gate_reviews_by_proposal(store).get(proposal_id)
    if apply and existing_review:
        return {
            "schema_version": APPROVED_PROPOSAL_OPS_GATE_SCHEMA_VERSION,
            "profile": store.roots.profile or "default",
            "status": "duplicate_ignored",
            "dry_run": False,
            "owner_id": owner_id,
            "channel": channel,
            "proposal_id": proposal_id,
            "proposal_state": "approved_for_proposal",
            "proposed_action": proposed_action,
            "existing_ops_gate_review": existing_review,
            "ops_gate_report_written": False,
            "ops_gate_result": {},
            "execution_ticket_created": False,
            "actual_execute": False,
            "raw_body_included": False,
            "boundary": _owner_review_false_boundary(),
        }
    ops_gate_result: dict[str, Any] = {}
    if apply:
        from plugins.modules.governance.ops_gate import OpsGateModule

        module = OpsGateModule(store.roots.hermes_home, profile=store.roots.profile or "default")
        ops_gate_result = module.run_once(store=store, proposed_actions=[proposed_action])
    status = "ok" if not apply else str(ops_gate_result.get("status") or "error")

    return {
        "schema_version": APPROVED_PROPOSAL_OPS_GATE_SCHEMA_VERSION,
        "profile": store.roots.profile or "default",
        "status": status,
        "dry_run": not apply,
        "owner_id": owner_id,
        "channel": channel,
        "proposal_id": proposal_id,
        "proposal_state": "approved_for_proposal",
        "proposed_action": proposed_action,
        "existing_ops_gate_review": existing_review or {},
        "ops_gate_report_written": bool(apply and ops_gate_result.get("report_id")),
        "ops_gate_result": ops_gate_result,
        "execution_ticket_created": False,
        "actual_execute": False,
        "raw_body_included": False,
        "boundary": _owner_review_false_boundary(),
    }


def route_pending_approved_proposal_followups_to_ops_gate(
    store: MemoryOSStore,
    *,
    owner_id: str = "owner",
    channel: str = "cli",
    limit: int = 50,
    apply: bool = False,
) -> dict[str, Any]:
    """Route all approved proposals still awaiting OpsGate review.

    This is a bounded operator/agent helper for closing the report-only
    follow-up stage. It never creates execution tickets and never executes
    work. Re-running it is idempotent because already reviewed proposals are
    skipped by the underlying single-proposal route.
    """

    report = approved_proposal_followups_report(store, limit=1_000_000)
    items = [
        item
        for item in report.get("items", [])
        if isinstance(item, dict) and item.get("followup_state") == "awaiting_ops_gate_review"
    ]
    bounded_limit = max(min(int(limit or 50), 200), 0)
    selected = items[:bounded_limit]
    results = [
        route_approved_proposal_followup_to_ops_gate(
            store,
            proposal_id=str(item.get("proposal_id") or ""),
            owner_id=owner_id,
            channel=channel,
            apply=apply,
        )
        for item in selected
    ]
    status = "ok"
    if any(result.get("status") == "error" for result in results):
        status = "error"
    return {
        "schema_version": APPROVED_PROPOSAL_OPS_GATE_BATCH_SCHEMA_VERSION,
        "profile": store.roots.profile or "default",
        "status": status,
        "dry_run": not apply,
        "owner_id": owner_id,
        "channel": channel,
        "eligible_count": len(items),
        "selected_count": len(selected),
        "overflow_count": max(len(items) - bounded_limit, 0),
        "ops_gate_report_written_count": sum(1 for result in results if result.get("ops_gate_report_written") is True),
        "duplicate_ignored_count": sum(1 for result in results if result.get("status") == "duplicate_ignored"),
        "error_count": sum(1 for result in results if result.get("status") == "error"),
        "execution_ticket_created": False,
        "actual_execute": False,
        "raw_body_included": False,
        "boundary": _owner_review_false_boundary(),
        "results": results[:20],
    }


def auto_route_safe_proposal_followups_to_ops_gate(
    store: MemoryOSStore,
    *,
    owner_id: str = "memory_os_auto",
    channel: str = "automation",
    limit: int = 50,
    apply: bool = False,
) -> dict[str, Any]:
    """Graduate safe proposal follow-up process motion to OpsGate report-only.

    This is Lane E: it moves only low-risk ``proposal_queue_only`` candidates
    into follow-up and immediately reuses the existing OpsGate report-only path.
    It is not an owner action, does not create execution tickets, and never
    applies proposal policy.
    """

    from plugins.modules.governance.proposal_queue import ProposalQueueModule

    module = ProposalQueueModule(store.roots.hermes_home, profile=store.roots.profile or "default")
    queue = module.read_queue()
    queue_items = [item for item in queue.get("items", []) if isinstance(item, dict)]
    candidates = [item for item in queue_items if _proposal_followup_auto_route_eligible(item)]
    boundary_rejected_count = sum(1 for item in queue_items if _proposal_auto_route_boundary_rejected(item))
    bounded_limit = max(min(int(limit or 50), 200), 0)
    successful_limited_routes = _proposal_followup_auto_route_success_count(store)
    owner_comparison = _proposal_followup_auto_route_owner_comparison_counts(store)
    calibration = _proposal_followup_auto_route_calibration(
        candidates,
        successful_limited_routes=successful_limited_routes,
        owner_comparison=owner_comparison,
    )
    effective_limit = bounded_limit
    if apply and not calibration["full_auto_eligible"]:
        effective_limit = min(effective_limit, int(calibration["current_auto_route_cap_per_day"]))
    selected = candidates[:effective_limit]
    promoted_ids: list[str] = []
    if apply:
        for item in selected:
            proposal_id = str(item.get("candidate_id") or "")
            if not proposal_id:
                continue
            module.transition(
                store=store,
                candidate_id=proposal_id,
                decision="approve",
                reviewer=owner_id,
                note="auto_route_to_ops_gate_report_only",
            )
            promoted_ids.append(proposal_id)
    ops_gate = route_pending_approved_proposal_followups_to_ops_gate(
        store,
        owner_id=owner_id,
        channel=channel,
        limit=bounded_limit,
        apply=apply,
    ) if apply else {
        "schema_version": APPROVED_PROPOSAL_OPS_GATE_BATCH_SCHEMA_VERSION,
        "status": "ok",
        "dry_run": True,
        "eligible_count": len(selected),
        "selected_count": len(selected),
        "overflow_count": max(len(candidates) - bounded_limit, 0),
        "ops_gate_report_written_count": 0,
        "duplicate_ignored_count": 0,
        "error_count": 0,
        "execution_ticket_created": False,
        "actual_execute": False,
        "raw_body_included": False,
        "boundary": _owner_review_false_boundary(),
        "results": [],
    }
    policy_write_count = _proposal_policy_write_count(approved_proposal_followups_report(store, limit=1_000_000))
    result = {
        "schema_version": PROPOSAL_FOLLOWUP_AUTO_ROUTE_SCHEMA_VERSION,
        "profile": store.roots.profile or "default",
        "status": "ok" if ops_gate.get("status") in {"ok", "warning"} else "error",
        "dry_run": not apply,
        "owner_id": owner_id,
        "channel": channel,
        "lane_id": "proposal_followup_auto_route",
        "lane_mode": calibration["lane_mode"],
        "sample_window_days": PROPOSAL_FOLLOWUP_AUTO_ROUTE_SAMPLE_WINDOW_DAYS,
        "minimum_real_samples_for_full_auto": PROPOSAL_FOLLOWUP_AUTO_ROUTE_FULL_AUTO_MIN_SAMPLES,
        "minimum_real_samples_for_limited_auto": PROPOSAL_FOLLOWUP_AUTO_ROUTE_LIMITED_AUTO_MIN_SAMPLES,
        "observed_owner_agreement_rate_required": PROPOSAL_FOLLOWUP_AUTO_ROUTE_FULL_AUTO_AGREEMENT_RATE,
        "wilson_95_lower_bound_required": PROPOSAL_FOLLOWUP_AUTO_ROUTE_FULL_AUTO_WILSON_LOWER_BOUND,
        "owner_agreement_evidence_source": calibration["owner_agreement_evidence_source"],
        "eligible_sample_count": calibration["eligible_sample_count"],
        "shadow_decision_count": calibration["shadow_decision_count"],
        "owner_agreement_count": calibration["owner_agreement_count"],
        "owner_disagreement_count": calibration["owner_disagreement_count"],
        "owner_agreement_rate": calibration["owner_agreement_rate"],
        "wilson_95_lower_bound": calibration["wilson_95_lower_bound"],
        "proposal_kind_coverage": calibration["proposal_kind_coverage"],
        "full_auto_eligible": calibration["full_auto_eligible"],
        "limited_auto_eligible": calibration["limited_auto_eligible"],
        "limited_auto_graduated": calibration["limited_auto_graduated"],
        "limited_auto_evidence_source": calibration["limited_auto_evidence_source"],
        "limited_auto_first_canary_max_auto_routes_per_day": PROPOSAL_FOLLOWUP_AUTO_ROUTE_FIRST_CANARY_DAILY_CAP,
        "limited_auto_after_successful_routes": PROPOSAL_FOLLOWUP_AUTO_ROUTE_AFTER_SUCCESSFUL_LIMITED_ROUTES,
        "limited_auto_expanded_max_auto_routes_per_day": PROPOSAL_FOLLOWUP_AUTO_ROUTE_EXPANDED_DAILY_CAP,
        "successful_limited_auto_route_count": successful_limited_routes,
        "current_auto_route_cap_per_day": calibration["current_auto_route_cap_per_day"],
        "continue_shadow_comparison": True,
        "auto_demote_on_first_boundary_or_owner_disagreement": True,
        "actual_followup_route_changed": bool(apply and promoted_ids),
        "eligible_count": len(candidates),
        "selected_count": len(selected),
        "requested_limit": bounded_limit,
        "effective_limit": effective_limit,
        "overflow_count": max(len(candidates) - effective_limit, 0),
        "auto_followup_routed_count": len(promoted_ids),
        "auto_followup_actual_execute_count": 0,
        "auto_followup_policy_write_count": 0 if not apply else 0,
        "auto_followup_actual_send_count": 0,
        "existing_policy_write_count": policy_write_count,
        "owner_action_required_count": 0,
        "owner_action_required_boundary_count": boundary_rejected_count,
        "auto_followup_boundary_rejected_count": boundary_rejected_count,
        "execution_ticket_created": False,
        "actual_execute": False,
        "raw_body_included": False,
        "promoted_proposal_ids": promoted_ids[:20],
        "ops_gate": ops_gate,
        "boundary": _owner_review_false_boundary(),
    }
    if apply:
        append_audit(
            store.roots.audit_path,
            action="proposal_followup_auto_route_to_ops_gate",
            status=result["status"],
            target=str(_proposal_queue_path(store)),
            details={
                "eligible_count": result["eligible_count"],
                "auto_followup_routed_count": result["auto_followup_routed_count"],
                "owner_action_required_boundary_count": result["owner_action_required_boundary_count"],
                "ops_gate_report_written_count": ops_gate.get("ops_gate_report_written_count"),
                "actual_execute": False,
                "policy_write_count": 0,
                "lane_mode": result["lane_mode"],
                "effective_limit": result["effective_limit"],
                "wilson_95_lower_bound": result["wilson_95_lower_bound"],
            },
        )
    return result


def _proposal_followup_auto_route_calibration(
    candidates: list[dict[str, Any]],
    *,
    successful_limited_routes: int,
    owner_comparison: dict[str, Any],
) -> dict[str, Any]:
    eligible_sample_count = len(candidates)
    sample_count = int(owner_comparison.get("sample_count") or 0)
    owner_agreement_count = int(owner_comparison.get("owner_agreement_count") or 0)
    owner_disagreement_count = int(owner_comparison.get("owner_disagreement_count") or 0)
    owner_agreement_rate = (owner_agreement_count / sample_count) if sample_count else 0.0
    wilson = _wilson_lower_bound(owner_agreement_count, sample_count)
    limited_auto_graduated = successful_limited_routes >= PROPOSAL_FOLLOWUP_AUTO_ROUTE_AFTER_SUCCESSFUL_LIMITED_ROUTES
    full_auto_eligible = (
        sample_count >= PROPOSAL_FOLLOWUP_AUTO_ROUTE_FULL_AUTO_MIN_SAMPLES
        and owner_agreement_rate >= PROPOSAL_FOLLOWUP_AUTO_ROUTE_FULL_AUTO_AGREEMENT_RATE
        and wilson >= PROPOSAL_FOLLOWUP_AUTO_ROUTE_FULL_AUTO_WILSON_LOWER_BOUND
    )
    limited_auto_eligible = (
        limited_auto_graduated
        or (
            PROPOSAL_FOLLOWUP_AUTO_ROUTE_LIMITED_AUTO_MIN_SAMPLES
            <= sample_count
            < PROPOSAL_FOLLOWUP_AUTO_ROUTE_FULL_AUTO_MIN_SAMPLES
            and owner_agreement_rate == 1.0
        )
    )
    if full_auto_eligible:
        lane_mode = "full_auto"
    elif limited_auto_eligible:
        lane_mode = "limited_auto"
    elif sample_count <= 0 and eligible_sample_count <= 0:
        lane_mode = "insufficient_volume_running"
    else:
        lane_mode = "live_shadow_calibration"
    current_cap = (
        PROPOSAL_FOLLOWUP_AUTO_ROUTE_EXPANDED_DAILY_CAP
        if successful_limited_routes >= PROPOSAL_FOLLOWUP_AUTO_ROUTE_AFTER_SUCCESSFUL_LIMITED_ROUTES
        else PROPOSAL_FOLLOWUP_AUTO_ROUTE_FIRST_CANARY_DAILY_CAP
    )
    return {
        "lane_mode": lane_mode,
        "eligible_sample_count": eligible_sample_count,
        "shadow_decision_count": sample_count,
        "owner_agreement_count": owner_agreement_count,
        "owner_disagreement_count": owner_disagreement_count,
        "owner_agreement_rate": round(owner_agreement_rate, 4),
        "wilson_95_lower_bound": round(wilson, 4),
        "proposal_kind_coverage": _proposal_followup_kind_coverage_from_owner_comparison(owner_comparison),
        "full_auto_eligible": full_auto_eligible,
        "limited_auto_eligible": limited_auto_eligible,
        "limited_auto_graduated": limited_auto_graduated,
        "owner_agreement_evidence_source": "owner_action_decision_ledger",
        "limited_auto_evidence_source": (
            "historical_successful_routes"
            if limited_auto_graduated
            else "current_shadow_samples"
            if limited_auto_eligible
            else "insufficient_evidence"
        ),
        "current_auto_route_cap_per_day": current_cap,
    }


def _wilson_lower_bound(successes: int, total: int, *, z: float = 1.96) -> float:
    if total <= 0:
        return 0.0
    phat = successes / total
    denom = 1 + z * z / total
    centre = phat + z * z / (2 * total)
    margin = z * ((phat * (1 - phat) + z * z / (4 * total)) / total) ** 0.5
    return max((centre - margin) / denom, 0.0)


def _proposal_followup_kind_coverage(candidates: list[dict[str, Any]]) -> list[str]:
    values = {
        str(item.get("proposal_class") or item.get("kind") or "proposal").strip()[:96]
        for item in candidates
        if isinstance(item, dict)
    }
    return sorted(value for value in values if value)[:20]


def _proposal_followup_kind_coverage_from_owner_comparison(owner_comparison: dict[str, Any]) -> list[str]:
    coverage = owner_comparison.get("proposal_kind_coverage")
    if isinstance(coverage, list):
        return sorted({str(item).strip()[:96] for item in coverage if str(item).strip()})[:20]
    return []


def _proposal_followup_auto_route_owner_decision_context(
    proposal: dict[str, Any],
    *,
    action_type: str,
) -> dict[str, Any]:
    auto_would_route = _proposal_followup_auto_route_eligible(proposal)
    owner_decision = "approve" if action_type == "approve_proposal" else "reject"
    proposal_kind = str(proposal.get("proposal_class") or proposal.get("kind") or "proposal").strip()[:96]
    return {
        "schema_version": "memory-os.proposal_followup_auto_route_owner_decision.v0",
        "candidate_id": str(proposal.get("candidate_id") or ""),
        "proposal_kind": proposal_kind or "proposal",
        "owner_decision": owner_decision,
        "auto_would_route": auto_would_route,
        "comparison_sample": auto_would_route,
        "owner_auto_agreement": auto_would_route and owner_decision == "approve",
        "owner_auto_disagreement": auto_would_route and owner_decision == "reject",
        "boundary_clean": proposal_auto_route_boundary_clean(proposal),
        "actual_execute": False,
        "actual_send": False,
        "actual_policy_write": False,
        "boundary": _owner_review_false_boundary(),
    }


def _proposal_followup_auto_route_owner_comparison_counts(store: MemoryOSStore) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=PROPOSAL_FOLLOWUP_AUTO_ROUTE_SAMPLE_WINDOW_DAYS)
    sample_count = 0
    agreement_count = 0
    disagreement_count = 0
    kind_coverage: set[str] = set()
    for record in _read_jsonl(owner_actions_path(store.roots)):
        created_at = _parse_dt(str(record.get("created_at") or ""))
        if created_at is None or created_at < cutoff:
            continue
        context = record.get("action_context") if isinstance(record.get("action_context"), dict) else {}
        decision = (
            context.get("proposal_followup_auto_route_owner_decision")
            if isinstance(context.get("proposal_followup_auto_route_owner_decision"), dict)
            else {}
        )
        if decision.get("schema_version") != "memory-os.proposal_followup_auto_route_owner_decision.v0":
            continue
        if decision.get("comparison_sample") is not True:
            continue
        sample_count += 1
        if decision.get("owner_auto_agreement") is True:
            agreement_count += 1
        if decision.get("owner_auto_disagreement") is True:
            disagreement_count += 1
        kind = str(decision.get("proposal_kind") or "").strip()[:96]
        if kind:
            kind_coverage.add(kind)
    return {
        "sample_count": sample_count,
        "owner_agreement_count": agreement_count,
        "owner_disagreement_count": disagreement_count,
        "proposal_kind_coverage": sorted(kind_coverage)[:20],
    }


def _proposal_followup_auto_route_success_count(store: MemoryOSStore) -> int:
    count = 0
    for record in _read_jsonl(store.roots.audit_path):
        if record.get("action") != "proposal_followup_auto_route_to_ops_gate":
            continue
        details = record.get("details") if isinstance(record.get("details"), dict) else {}
        try:
            routed = int(details.get("auto_followup_routed_count") or 0)
        except (TypeError, ValueError):
            routed = 0
        if routed > 0 and record.get("status") == "ok":
            count += routed
    return count


def _proposal_followup_auto_route_eligible(proposal: dict[str, Any]) -> bool:
    state = str(proposal.get("state") or "")
    if state not in {"candidate", "owner_eligible", "owner_defer"}:
        return False
    if str(proposal.get("approval_purpose") or "") != "proposal_queue_only":
        return False
    if not proposal_auto_route_boundary_clean(proposal):
        return False
    if _proposal_requires_maturation(proposal):
        return False
    return True


def proposal_auto_route_boundary_clean(proposal: dict[str, Any]) -> bool:
    """Return true only for report-only process-motion proposals.

    Lane E may automatically move a proposal into OpsGate follow-up, but it
    must never carry send, execution, identity, policy, relationship, or
    canonical-memory write authority across that boundary.
    """

    kind = str(proposal.get("kind") or "proposal").strip().lower()
    if kind not in PROPOSAL_FOLLOWUP_AUTO_ROUTE_SAFE_KINDS:
        return False
    if _explicit_proposal_apply_kind(proposal):
        return False
    for key in PROPOSAL_FOLLOWUP_AUTO_ROUTE_TRUE_BLOCK_KEYS:
        if bool(proposal.get(key)):
            return False
    for key in PROPOSAL_FOLLOWUP_AUTO_ROUTE_COUNT_BLOCK_KEYS:
        try:
            if int(proposal.get(key) or 0) > 0:
                return False
        except (TypeError, ValueError):
            return False
    boundary = proposal.get("boundary") if isinstance(proposal.get("boundary"), dict) else {}
    for key in PROPOSAL_FOLLOWUP_AUTO_ROUTE_BOUNDARY_KEYS:
        if bool(boundary.get(key)):
            return False
    return True


def _proposal_auto_route_boundary_rejected(proposal: dict[str, Any]) -> bool:
    state = str(proposal.get("state") or "")
    if state not in {"candidate", "owner_eligible", "owner_defer"}:
        return False
    if str(proposal.get("approval_purpose") or "") != "proposal_queue_only":
        return False
    return not proposal_auto_route_boundary_clean(proposal)


def _proposal_policy_write_count(report: dict[str, Any]) -> int:
    return (
        int(report.get("policy_apply_count") or 0)
        + int(report.get("memory_sources_policy_apply_count") or 0)
        + int(report.get("legacy_template_cleanup_apply_count") or 0)
        + int(report.get("deep_reflection_policy_apply_count") or 0)
    )


def apply_approved_proposal_execution_decision(
    store: MemoryOSStore,
    *,
    proposal_id: str,
    owner_id: str = "owner",
    channel: str = "cli",
    owner_approved: bool = False,
    apply: bool = False,
    evidence_refs: list[str] | None = None,
    evidence_summary: str = "",
) -> dict[str, Any]:
    """Apply an owner-approved proposal after OpsGate review.

    This is the explicit apply step after ``approved_for_proposal`` and
    OpsGate report-only review. Bounded policy proposal kinds write local
    policy files consumed by Memory-OS runtime surfaces. Unsupported but
    recognized kinds create typed internal execution-plan tickets instead of
    running a generic executor. This does not run shell commands or send
    messages.
    """

    proposal = _find_proposal(store, proposal_id)
    if not proposal:
        return _approved_proposal_execution_apply_error(
            store,
            proposal_id=proposal_id,
            owner_id=owner_id,
            channel=channel,
            reason="proposal_not_found",
            apply=apply,
        )
    if str(proposal.get("state") or "") != "approved_for_proposal":
        return _approved_proposal_execution_apply_error(
            store,
            proposal_id=proposal_id,
            owner_id=owner_id,
            channel=channel,
            reason="proposal_not_approved_for_followup",
            apply=apply,
        )
    apply_kind = _explicit_proposal_apply_kind(proposal)
    if apply_kind not in {"expression_policy", "memory_sources_policy", "proposal_queue_legacy_template_cleanup"}:
        ticket_kind = _unsupported_proposal_execution_ticket_kind(proposal)
        if ticket_kind:
            if apply and not owner_approved:
                return _approved_proposal_execution_apply_error(
                    store,
                    proposal_id=proposal_id,
                    owner_id=owner_id,
                    channel=channel,
                    reason="owner_explicit_apply_required",
                    apply=apply,
                )
            ops_gate_review = _ops_gate_reviews_by_proposal(store).get(proposal_id, {})
            if not ops_gate_review:
                return _approved_proposal_execution_apply_error(
                    store,
                    proposal_id=proposal_id,
                    owner_id=owner_id,
                    channel=channel,
                    reason="missing_ops_gate_review",
                    apply=apply,
                )
            if str(ops_gate_review.get("decision") or "") != "would_allow":
                return _approved_proposal_execution_apply_error(
                    store,
                    proposal_id=proposal_id,
                    owner_id=owner_id,
                    channel=channel,
                    reason="ops_gate_not_allowing",
                    apply=apply,
                )
            return _approved_proposal_execution_ticket_result(
                store,
                proposal=proposal,
                owner_id=owner_id,
                channel=channel,
                apply=apply,
                ticket_kind=ticket_kind,
                ops_gate_review=ops_gate_review,
                evidence_refs=evidence_refs or [],
                evidence_summary=evidence_summary,
            )
        return _approved_proposal_execution_apply_error(
            store,
            proposal_id=proposal_id,
            owner_id=owner_id,
            channel=channel,
            reason="unsupported_apply_kind",
            apply=apply,
        )
    ops_gate_review = _ops_gate_reviews_by_proposal(store).get(proposal_id, {})
    if not ops_gate_review:
        return _approved_proposal_execution_apply_error(
            store,
            proposal_id=proposal_id,
            owner_id=owner_id,
            channel=channel,
            reason="missing_ops_gate_review",
            apply=apply,
        )
    if str(ops_gate_review.get("decision") or "") != "would_allow":
        return _approved_proposal_execution_apply_error(
            store,
            proposal_id=proposal_id,
            owner_id=owner_id,
            channel=channel,
            reason="ops_gate_not_allowing",
            apply=apply,
        )
    if apply and not owner_approved:
        return _approved_proposal_execution_apply_error(
            store,
            proposal_id=proposal_id,
            owner_id=owner_id,
            channel=channel,
            reason="owner_explicit_apply_required",
            apply=apply,
        )
    if apply_kind == "proposal_queue_legacy_template_cleanup":
        existing_cleanup = _legacy_template_cleanup_applies_by_proposal(store).get(proposal_id, {})
        if apply and existing_cleanup:
            return _approved_proposal_legacy_template_cleanup_apply_result(
                store,
                status="duplicate_ignored",
                proposal=proposal,
                owner_id=owner_id,
                channel=channel,
                apply=apply,
                ops_gate_review=ops_gate_review,
                apply_record=existing_cleanup,
                target_ids=[],
                closed_count=0,
                cleanup_written=False,
            )
        targets = _legacy_template_cleanup_targets(store, exclude_proposal_id=proposal_id)
        apply_record: dict[str, Any] = {}
        closed_count = 0
        if apply:
            apply_record = _write_proposal_queue_legacy_template_cleanup(
                store,
                proposal=proposal,
                targets=targets,
                owner_id=owner_id,
                channel=channel,
                ops_gate_review=ops_gate_review,
            )
            closed_count = int(apply_record.get("closed_count") or 0)
        return _approved_proposal_legacy_template_cleanup_apply_result(
            store,
            status="applied" if apply else "ready",
            proposal=proposal,
            owner_id=owner_id,
            channel=channel,
            apply=apply,
            ops_gate_review=ops_gate_review,
            apply_record=apply_record,
            target_ids=[str(item.get("candidate_id") or "") for item in targets],
            closed_count=closed_count,
            cleanup_written=bool(apply_record),
        )

    if apply_kind == "memory_sources_policy":
        existing_memory_sources_apply = _memory_sources_policy_applies_by_proposal(store).get(proposal_id, {})
        if apply and existing_memory_sources_apply:
            return _approved_proposal_memory_sources_policy_apply_result(
                store,
                status="duplicate_ignored",
                proposal=proposal,
                owner_id=owner_id,
                channel=channel,
                apply=apply,
                ops_gate_review=ops_gate_review,
                apply_record=existing_memory_sources_apply,
                policy={},
                policy_written=False,
            )
        memory_sources_policy = _memory_sources_policy_from_proposal(
            store,
            proposal=proposal,
            owner_id=owner_id,
            channel=channel,
            ops_gate_review=ops_gate_review,
        )
        memory_sources_apply_record: dict[str, Any] = {}
        if apply:
            memory_sources_apply_record = _write_memory_sources_policy(
                store,
                proposal=proposal,
                policy=memory_sources_policy,
            )
            _mark_proposal_memory_sources_policy_applied(
                store,
                proposal_id=proposal_id,
                apply_record=memory_sources_apply_record,
            )
        return _approved_proposal_memory_sources_policy_apply_result(
            store,
            status="applied" if apply else "ready",
            proposal=proposal,
            owner_id=owner_id,
            channel=channel,
            apply=apply,
            ops_gate_review=ops_gate_review,
            apply_record=memory_sources_apply_record,
            policy=memory_sources_policy,
            policy_written=bool(memory_sources_apply_record),
        )

    existing_apply = _policy_applies_by_proposal(store).get(proposal_id, {})
    if apply and existing_apply:
        return _approved_proposal_execution_apply_result(
            store,
            status="duplicate_ignored",
            proposal=proposal,
            owner_id=owner_id,
            channel=channel,
            apply=apply,
            ops_gate_review=ops_gate_review,
            existing_apply=existing_apply,
            policy={},
            policy_written=False,
        )

    policy = _right_brain_expression_policy_from_proposal(
        store,
        proposal=proposal,
        owner_id=owner_id,
        channel=channel,
        ops_gate_review=ops_gate_review,
    )
    apply_record: dict[str, Any] = {}
    if apply:
        apply_record = _write_right_brain_expression_policy(store, proposal=proposal, policy=policy)
        _mark_proposal_policy_applied(store, proposal_id=proposal_id, apply_record=apply_record)
    return _approved_proposal_execution_apply_result(
        store,
        status="applied" if apply else "ready",
        proposal=proposal,
        owner_id=owner_id,
        channel=channel,
        apply=apply,
        ops_gate_review=ops_gate_review,
        existing_apply=apply_record,
        policy=policy,
        policy_written=bool(apply_record),
    )


def owner_review_cron_integration_report(store: MemoryOSStore) -> dict[str, Any]:
    config = load_config(store.roots.hermes_home).get("owner_review", {})
    if not isinstance(config, dict):
        config = {}
    helper_path = owner_review_cron_helper_path(store.roots)
    job_name = str(config.get("cron_job_name") or "memory-os-owner-review-digest")
    jobs = _read_hermes_cron_jobs(store.roots.hermes_home)
    matched_job = _find_owner_review_cron_job(jobs, job_name=job_name, helper_name=helper_path.name)
    rendered_records = _records_since(read_owner_review_rendered_digest_records(store.roots), hours=24)
    raw_body_count = sum(1 for record in rendered_records if bool(record.get("raw_body_included")))
    deliver = str((matched_job or {}).get("deliver") or "")
    script = str((matched_job or {}).get("script") or "")
    enabled = bool(config.get("recurring_delivery_enabled"))
    job_enabled = bool((matched_job or {}).get("enabled")) if matched_job else False
    delivery_configured = bool(matched_job and job_enabled and deliver and deliver != "local")
    findings: list[dict[str, Any]] = []
    if enabled and not helper_path.is_file():
        findings.append(_owner_review_finding("cron_helper_missing", "error"))
    if enabled and not matched_job:
        findings.append(_owner_review_finding("cron_job_missing", "warning"))
    if matched_job and not str(script).endswith(helper_path.name):
        findings.append(_owner_review_finding("cron_job_script_mismatch", "warning"))
    if matched_job and not deliver:
        findings.append(_owner_review_finding("cron_delivery_target_missing", "warning"))
    if raw_body_count > 0:
        findings.append(_owner_review_finding("cron_rendered_digest_raw_body_included", "error"))
    status = "error" if any(item["severity"] == "error" for item in findings) else ("warning" if findings else "ok")
    return {
        "schema_version": OWNER_REVIEW_CRON_INTEGRATION_SCHEMA_VERSION,
        "profile": store.roots.profile or "default",
        "status": status,
        "enabled": enabled,
        "mode": str(config.get("recurring_delivery_mode") or "disabled"),
        "job_name": job_name,
        "job_present": bool(matched_job),
        "job_enabled": job_enabled,
        "job_id": str((matched_job or {}).get("id") or (matched_job or {}).get("job_id") or ""),
        "schedule_display": _cron_schedule_display(matched_job or {}),
        "helper_script_present": helper_path.is_file(),
        "helper_script_path": str(helper_path),
        "helper_script_name": helper_path.name,
        "hermes_delivery_configured": delivery_configured,
        "hermes_delivery_target_class": _delivery_target_class(deliver),
        "recurring_delivery_channel": _safe_channel(str(config.get("recurring_delivery_channel") or "")),
        "rendered_count_24h": len(rendered_records),
        "skipped_count_24h": 0,
        "error_count_24h": 0,
        "raw_body_included_count": raw_body_count,
        "unapproved_send_count": 0,
        "findings": findings,
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
        },
    }


def owner_review_delivery_status_report(store: MemoryOSStore) -> dict[str, Any]:
    records = read_owner_review_delivery_records(store.roots)
    by_result = Counter(str(record.get("result", "")) for record in records)
    owner_approved_count = sum(
        1 for record in records if (record.get("owner_effect") or {}).get("owner_approved_digest_delivery")
    )
    unapproved_count = sum(
        1 for record in records if (record.get("boundary") or {}).get("actual_unapproved_send")
    )
    raw_body_count = sum(1 for record in records if bool(record.get("raw_body_included")))
    last = records[-1] if records else {}
    return {
        "schema_version": OWNER_REVIEW_DELIVERY_STATUS_SCHEMA_VERSION,
        "profile": store.roots.profile or "default",
        "delivery_count": len(records),
        "sent_count": int(by_result.get("sent", 0)),
        "skipped_count": int(by_result.get("skipped", 0)),
        "error_count": int(by_result.get("error", 0)),
        "duplicate_ignored_count": int(by_result.get("duplicate_ignored", 0)),
        "owner_approved_digest_delivery_count": owner_approved_count,
        "unapproved_send_count": unapproved_count,
        "raw_body_included_count": raw_body_count,
        "last_delivery": _bounded_delivery_record(last) if last else {},
    }


def owner_review_aging_report(store: MemoryOSStore) -> dict[str, Any]:
    closed = _closed_targets(read_owner_action_records(store.roots))
    items = _candidate_cluster_review_items(store, closed)
    items.extend(_candidate_review_items(store, closed))
    items.extend(_proposal_review_items(store, closed))
    items.extend(_proposal_apply_review_items(store, closed))
    items.extend(_session_mirror_apply_review_items(store, closed))
    items.extend(_speak_review_items(store, closed))
    items.extend(_left_brain_advisor_review_items(store, closed))
    items.extend(_provisional_crystallized_review_items(store, closed))
    items.extend(_provisional_knob_override_review_items(store, closed))
    aged_items, aging = _apply_review_aging(store, items)
    return _review_aging_summary(aged_items, aging)


def resolve_owner_review_channel(store: MemoryOSStore, *, owner_id: str = "") -> dict[str, Any]:
    config = load_config(store.roots.hermes_home).get("owner_review", {})
    if not isinstance(config, dict):
        config = {}
    resolved_owner = str(owner_id or config.get("owner_id") or "owner")
    mode = str(config.get("mode") or "dry_run")
    if mode == "disabled":
        return _channel_report(
            status="disabled",
            reason="owner_review_mode_disabled",
            profile=store.roots.profile or "default",
            owner_id=resolved_owner,
            channel="unknown",
            target_ref="",
            direct_message=False,
            configured_by_owner=False,
            fallback_used=False,
            candidates=[],
        )

    configured = _configured_channel_candidate(config, owner_id=resolved_owner)
    candidates = _session_channel_candidates(store, owner_id=resolved_owner, limit=5)
    if configured:
        safe = _channel_candidate_is_safe(configured, allow_group=bool(config.get("allow_group")))
        status = "selected" if bool(config.get("enabled")) and safe else "dry_run_only"
        reason = "explicit_owner_config" if safe else "explicit_config_not_owner_verified"
        return _channel_report(
            status=status,
            reason=reason,
            profile=store.roots.profile or "default",
            owner_id=resolved_owner,
            channel=configured["channel"],
            target_ref=configured["target_ref"],
            direct_message=configured["direct_message"],
            configured_by_owner=True,
            fallback_used=False,
            candidates=candidates,
        )

    direct_candidates = [item for item in candidates if item.get("direct_message")]
    if len(direct_candidates) == 1:
        candidate = direct_candidates[0]
        return _channel_report(
            status="dry_run_only",
            reason="single_owner_direct_metadata_candidate",
            profile=store.roots.profile or "default",
            owner_id=resolved_owner,
            channel=str(candidate.get("channel") or "unknown"),
            target_ref=str(candidate.get("target_ref") or ""),
            direct_message=True,
            configured_by_owner=False,
            fallback_used=True,
            candidates=candidates,
        )
    if len(direct_candidates) > 1:
        return _channel_report(
            status="dry_run_only",
            reason="multiple_owner_direct_metadata_candidates",
            profile=store.roots.profile or "default",
            owner_id=resolved_owner,
            channel="cli",
            target_ref="",
            direct_message=False,
            configured_by_owner=False,
            fallback_used=True,
            candidates=candidates,
        )
    return _channel_report(
        status="dry_run_only",
        reason="cli_preview_fallback",
        profile=store.roots.profile or "default",
        owner_id=resolved_owner,
        channel="cli",
        target_ref="",
        direct_message=False,
        configured_by_owner=False,
        fallback_used=True,
        candidates=candidates,
    )


def owner_review_digest_preview(
    store: MemoryOSStore,
    *,
    owner_id: str = "",
    max_action_required: int | None = None,
    max_review_suggested: int | None = None,
    max_fyi: int | None = None,
    digest_mode: str = "review",
) -> dict[str, Any]:
    digest_mode = _digest_mode(digest_mode)
    config = load_config(store.roots.hermes_home).get("owner_review", {})
    if not isinstance(config, dict):
        config = {}
    resolved_owner = str(owner_id or config.get("owner_id") or "owner")
    actions_enabled = bool(config.get("actions_enabled"))
    action_limit = _positive_limit(max_action_required, config.get("max_action_required"), 3)
    if digest_mode == "agenda":
        suggested_limit = 0
        fyi_limit = 0
    else:
        suggested_limit = _positive_limit(max_review_suggested, config.get("max_review_suggested"), 2)
        fyi_limit = _positive_limit(max_fyi, config.get("max_fyi"), 2)
    queue = owner_review_queue_report(store, limit=1000)
    status = owner_review_status_report(store)
    channel = resolve_owner_review_channel(store, owner_id=resolved_owner)
    queue_items = list(queue.get("items") or [])
    review_aging = queue.get("review_aging") if isinstance(queue.get("review_aging"), dict) else {}
    visible_queue_items, stale_informational_suppressed = _suppress_stale_informational_digest_items(
        queue_items,
        review_aging=review_aging,
    )
    action_items = _digest_items(visible_queue_items, "action_required", action_limit)
    suggested_items = _digest_items(visible_queue_items, "review_suggested", suggested_limit)
    queue_fyi_items = _digest_items(visible_queue_items, "fyi", fyi_limit)
    memory_fyi_items = _memory_source_fyi_items(
        store,
        limit=max(fyi_limit - len(queue_fyi_items), 0),
        start=len(queue_fyi_items) + 1,
    )
    status_fyi_items = _fyi_items(
        status,
        limit=max(fyi_limit - len(queue_fyi_items) - len(memory_fyi_items), 0),
        start=len(queue_fyi_items) + len(memory_fyi_items) + 1,
    )
    fyi_items = queue_fyi_items + memory_fyi_items + status_fyi_items
    visible_action_total = sum(1 for item in visible_queue_items if item.get("priority") == "action_required")
    visible_review_suggested_total = sum(1 for item in visible_queue_items if item.get("priority") == "review_suggested")
    visible_fyi_total = sum(1 for item in visible_queue_items if item.get("priority") == "fyi")
    fyi_total = visible_fyi_total + len(memory_fyi_items) + 2
    digest_id = _digest_id()
    preview = {
        "schema_version": OWNER_REVIEW_DIGEST_PREVIEW_SCHEMA_VERSION,
        "digest_id": digest_id,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "profile": store.roots.profile or "default",
        "owner_id": resolved_owner,
        "status": "ok",
        "mode": "preview",
        "digest_mode": digest_mode,
        "will_send": False,
        "delivery_skipped": True,
        "actions_enabled": actions_enabled,
        "raw_body_included": False,
        "review_channel": channel,
        "limits": {
            "max_action_required": action_limit,
            "max_review_suggested": suggested_limit,
            "max_fyi": fyi_limit,
        },
        "counts": {
            "pending": queue.get("pending_count"),
            "action_required_total": queue.get("action_required_count"),
            "review_suggested_total": queue.get("review_suggested_count"),
            "fyi_total": fyi_total,
            "raw_action_required_total": (queue.get("review_aging") or {}).get("raw_action_required_count")
            if isinstance(queue.get("review_aging"), dict)
            else None,
            "action_required_shown": len(action_items),
            "review_suggested_shown": len(suggested_items),
            "fyi_shown": len(fyi_items),
            "stale_informational_suppressed": stale_informational_suppressed,
            "visible_action_required_total": visible_action_total,
            "visible_review_suggested_total": visible_review_suggested_total,
            "visible_fyi_total": visible_fyi_total,
        },
        "review_aging": review_aging,
        "aging_behavior": {
            "stale_informational_action": "suppress_from_digest",
            "stale_informational_suppressed_count": stale_informational_suppressed,
            "canonical_state_changed": False,
            "owner_action_created": False,
        },
        "overflow": {
            "action_required": max(visible_action_total - len(action_items), 0),
            "review_suggested": max(visible_review_suggested_total - len(suggested_items), 0),
            "fyi": max(fyi_total - len(fyi_items), 0),
        },
        "sections": {
            "action_required": action_items,
            "review_suggested": suggested_items,
            "fyi": fyi_items,
        },
        "text_preview": _digest_text_preview(action_items, suggested_items, fyi_items, store=store),
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
        },
    }
    return preview


def render_owner_review_digest(
    store: MemoryOSStore,
    *,
    owner_id: str = "",
    channel: str = "cli",
    max_action_required: int | None = None,
    max_review_suggested: int | None = None,
    max_fyi: int | None = None,
    digest_mode: str = "review",
    record_active: bool = False,
) -> dict[str, Any]:
    digest_mode = _digest_mode(digest_mode)
    preview = owner_review_digest_preview(
        store,
        owner_id=owner_id,
        max_action_required=max_action_required,
        max_review_suggested=max_review_suggested,
        max_fyi=max_fyi,
        digest_mode=digest_mode,
    )
    rendered_sections = {
        "action_required": [
            _render_review_item(item, section="action_required")
            for item in (preview.get("sections") or {}).get("action_required", [])
        ],
        "review_suggested": [
            _render_review_item(item, section="review_suggested")
            for item in (preview.get("sections") or {}).get("review_suggested", [])
        ],
        "fyi": [
            _render_review_item(item, section="fyi")
            for item in (preview.get("sections") or {}).get("fyi", [])
        ],
    }
    rendered = {
        "schema_version": OWNER_REVIEW_RENDERED_DIGEST_SCHEMA_VERSION,
        "digest_id": preview.get("digest_id"),
        "created_at": preview.get("created_at"),
        "profile": preview.get("profile"),
        "owner_id": preview.get("owner_id"),
        "status": preview.get("status"),
        "mode": "rendered_preview",
        "digest_mode": digest_mode,
        "will_send": False,
        "delivery_skipped": True,
        "actions_enabled": bool(preview.get("actions_enabled")),
        "raw_body_included": False,
        "delivery_binding": _owner_review_delivery_binding(store, channel),
        "review_channel": preview.get("review_channel"),
        "limits": preview.get("limits"),
        "counts": preview.get("counts"),
        "review_aging": preview.get("review_aging"),
        "overflow": preview.get("overflow"),
        "sections": rendered_sections,
        "text": _rendered_digest_text(
            rendered_sections,
            counts=preview.get("counts"),
            overflow=preview.get("overflow"),
            digest_mode=digest_mode,
            store=store,
        ),
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
        },
    }
    if record_active:
        _append_owner_review_rendered_digest(store, rendered, channel=channel)
        rendered["recorded_active_digest"] = True
    return rendered


def parse_owner_review_reply(
    store: MemoryOSStore,
    reply_text: str,
    *,
    owner_id: str = "owner",
    channel: str = "cli",
    apply: bool = False,
    digest_id: str = "",
    require_recorded_digest: bool = False,
    max_action_required: int | None = None,
    max_review_suggested: int | None = None,
    max_fyi: int | None = None,
) -> dict[str, Any]:
    parsed = _parse_owner_reply_text(reply_text)
    anchor = str(parsed.get("anchor") or "").upper() if parsed.get("status") == "ok" else ""
    action_token = str(parsed.get("action_token") or "").lower() if parsed.get("status") == "ok" else ""

    # --- P1: expiry cliff guard tokens (oa_confirm_ / oa_let_expire_) ---
    if action_token and action_token.startswith("oa_confirm_"):
        record_id = action_token[len("oa_confirm_"):]
        if not record_id.strip():
            return _reply_result(
                status="error",
                reply_text=reply_text,
                owner_id=owner_id,
                channel=channel,
                apply=apply,
                reason="missing record_id in oa_confirm_ token",
                rendered={"profile": store.roots.profile or "default"},
                binding="raw_token",
            )
        # P1 fix: require recorded digest when caller demands it (was bypassed)
        rendered, binding = _resolve_reply_digest(
            store,
            owner_id=owner_id,
            channel=channel,
            digest_id=digest_id,
            require_recorded_digest=require_recorded_digest,
            anchor=anchor,
            action_token=action_token,
            max_action_required=max_action_required,
            max_review_suggested=max_review_suggested,
            max_fyi=max_fyi,
        )
        if binding == "digest_not_found":
            return _reply_result(
                status="needs_clarification",
                reply_text=reply_text,
                owner_id=owner_id,
                channel=channel,
                apply=apply,
                reason="digest_not_found_or_expired",
                rendered=rendered,
                binding=binding,
            )
        service = CrystallizedMemoryService(store)
        try:
            result = service.confirm_provisional_record(
                record_id.strip(),
                confirmed_by="owner",
            )
        except KeyError:
            return _reply_result(
                status="error",
                reply_text=reply_text,
                owner_id=owner_id,
                channel=channel,
                apply=apply,
                reason=f"record_not_found: {record_id.strip()}",
                rendered=rendered,
                binding=binding,
            )
        return _reply_result(
            status="ok",
            reply_text=reply_text,
            owner_id=owner_id,
            channel=channel,
            apply=apply,
            reason="",
            rendered=rendered,
            binding=binding,
            action_result={
                "status": "ok",
                "action": "provisional_confirmed",
                "record_id": record_id.strip(),
                "canonical_state_changed": result.get("canonical_state_changed", False),
            },
        )

    if action_token and action_token.startswith("oa_let_expire_"):
        record_id = action_token[len("oa_let_expire_"):]
        if not record_id.strip():
            return _reply_result(
                status="error",
                reply_text=reply_text,
                owner_id=owner_id,
                channel=channel,
                apply=apply,
                reason="missing record_id in oa_let_expire_ token",
                rendered={"profile": store.roots.profile or "default"},
                binding="raw_token",
            )
        if apply:
            append_audit(
                store.roots.audit_path,
                action="provisional_let_expire",
                status="ok",
                target=str(store.roots.crystallized_root),
                details={
                    "record_id": record_id.strip(),
                    "note": "owner explicitly chose to let this provisional record expire",
                },
            )
        return _reply_result(
            status="ok",
            reply_text=reply_text,
            owner_id=owner_id,
            channel=channel,
            apply=apply,
            reason="",
            rendered={"profile": store.roots.profile or "default"},
            binding="raw_token",
            action_result={
                "status": "ok",
                "action": "provisional_let_expire_acknowledged",
                "record_id": record_id.strip(),
            },
        )

    rendered, binding = _resolve_reply_digest(
        store,
        owner_id=owner_id,
        channel=channel,
        digest_id=digest_id,
        require_recorded_digest=require_recorded_digest,
        anchor=anchor,
        action_token=action_token,
        max_action_required=max_action_required,
        max_review_suggested=max_review_suggested,
        max_fyi=max_fyi,
    )
    surface_token_match = _surface_action_token_map(store.roots).get(action_token) if action_token else None
    if binding == "digest_not_found" and not surface_token_match:
        return _reply_result(
            status="needs_clarification",
            reply_text=reply_text,
            owner_id=owner_id,
            channel=channel,
            apply=apply,
            reason="digest_not_found_or_expired",
            rendered=rendered,
            binding=binding,
        )
    if parsed["status"] != "ok":
        return _reply_result(
            status=parsed["status"],
            reply_text=reply_text,
            owner_id=owner_id,
            channel=channel,
            apply=apply,
            reason=parsed.get("reason", ""),
            rendered=rendered,
            binding=binding,
        )
    item: dict[str, Any] | None = None
    action_type = ""
    if action_token:
        token_match = _rendered_action_token_map(rendered).get(action_token)
        if not token_match:
            token_match = surface_token_match or _surface_action_token_map(store.roots).get(action_token)
        if token_match:
            item = token_match["item"]
            action_type = str(token_match.get("action_type") or "")
        if not item:
            return _reply_result(
                status="needs_clarification",
                reply_text=reply_text,
                owner_id=owner_id,
                channel=channel,
                apply=apply,
                reason="action_token_not_found_in_recorded_digest",
                rendered=rendered,
                parsed=parsed,
                binding=binding,
            )
    else:
        anchor_map = _rendered_anchor_map(rendered)
        anchor = str(parsed["anchor"]).upper()
        item = anchor_map.get(anchor)
    if not item:
        return _reply_result(
            status="needs_clarification",
            reply_text=reply_text,
            owner_id=owner_id,
            channel=channel,
            apply=apply,
            reason="anchor_not_found_in_current_digest",
            rendered=rendered,
            parsed=parsed,
            binding=binding,
        )
    if not action_type:
        action_type = _owner_action_type_from_reply(parsed["verb"], item)
    if not action_type:
        return _reply_result(
            status="unsupported",
            reply_text=reply_text,
            owner_id=owner_id,
            channel=channel,
            apply=apply,
            reason="action_not_supported_for_anchor",
            rendered=rendered,
            parsed=parsed,
            item=item,
            binding=binding,
        )
    target_type = str(token_match.get("target_type") or "") if action_token and token_match else ""
    target_id = str(token_match.get("target_id") or "") if action_token and token_match else ""
    if not target_type or not target_id:
        target_type, target_id = _target_for_action_item(action_type, item)
    if action_token and not _reply_verb_matches_action_type(str(parsed.get("verb") or ""), action_type):
        return _reply_result(
            status="unsupported",
            reply_text=reply_text,
            owner_id=owner_id,
            channel=channel,
            apply=apply,
            reason="action_token_verb_mismatch",
            rendered=rendered,
            parsed={**parsed, "action_type": action_type, "target_type": target_type, "target_id": target_id},
            item=item,
            binding=binding,
        )
    if (
        action_token
        and action_type in EXPRESSION_FEEDBACK_ACTION_TYPES
        and str(parsed.get("rating") or "") != action_type
    ):
        return _reply_result(
            status="unsupported",
            reply_text=reply_text,
            owner_id=owner_id,
            channel=channel,
            apply=apply,
            reason="expression_feedback_rating_mismatch",
            rendered=rendered,
            parsed={**parsed, "action_type": action_type, "target_type": target_type, "target_id": target_id},
            item=item,
            binding=binding,
        )
    action_result = apply_owner_action(
        store,
        action_type=action_type,
        target=f"{target_type}:{target_id}",
        owner_id=owner_id,
        channel=channel,
        note=f"owner command: {action_token or anchor}",
        rating=str(parsed.get("rating") or ""),
        apply=apply,
        reply_context=_owner_reply_action_context(
            rendered=rendered,
            binding=binding,
            item=item,
            action_token=action_token,
            reply_text=reply_text,
        ),
    )
    return _reply_result(
        status="ok" if action_result.get("status") in {"ok", "duplicate_ignored"} else "error",
        reply_text=reply_text,
        owner_id=owner_id,
        channel=channel,
        apply=apply,
        reason="",
        rendered=rendered,
        parsed={**parsed, "action_type": action_type, "target_type": target_type, "target_id": target_id},
        item=item,
        action_result=action_result,
        binding=binding,
    )


def owner_review_delivery_gate_report(store: MemoryOSStore, *, owner_id: str = "") -> dict[str, Any]:
    config = load_config(store.roots.hermes_home).get("owner_review", {})
    if not isinstance(config, dict):
        config = {}
    resolved_owner = str(owner_id or config.get("owner_id") or "owner")
    channel = resolve_owner_review_channel(store, owner_id=resolved_owner)
    preview = owner_review_digest_preview(store, owner_id=resolved_owner)
    delivery_enabled = bool(config.get("delivery_enabled"))
    delivery_adapter = str(config.get("delivery_adapter") or "none")
    delivery_target_class = _delivery_target_class(str(channel.get("target_ref") or ""))
    blocked_reasons: list[str] = []
    if not delivery_enabled:
        blocked_reasons.append("delivery_not_enabled")
    if delivery_adapter in {"", "none", "disabled"}:
        blocked_reasons.append("delivery_adapter_not_configured")
    elif delivery_adapter not in OWNER_REVIEW_DELIVERY_ADAPTERS:
        blocked_reasons.append("delivery_adapter_unsupported")
    elif delivery_target_class == "missing":
        blocked_reasons.append("delivery_target_missing")
    elif delivery_target_class in {"auto", "local", "origin"}:
        blocked_reasons.append("delivery_target_not_owner_channel")
    if channel.get("status") != "selected":
        blocked_reasons.append("review_channel_not_selected")
    if not channel.get("configured_by_owner"):
        blocked_reasons.append("review_channel_not_configured_by_owner")
    if channel.get("raw_body_included") is True:
        blocked_reasons.append("review_channel_raw_body")
    if preview.get("raw_body_included") is True:
        blocked_reasons.append("digest_preview_raw_body")
    if preview.get("will_send") is True:
        blocked_reasons.append("digest_preview_already_would_send")
    status = "ready" if not blocked_reasons else ("disabled" if not delivery_enabled else "blocked")
    return {
        "schema_version": OWNER_REVIEW_DELIVERY_GATE_SCHEMA_VERSION,
        "profile": store.roots.profile or "default",
        "owner_id": resolved_owner,
        "status": status,
        "ready_for_delivery": status == "ready",
        "delivery_enabled": delivery_enabled,
        "delivery_adapter": delivery_adapter,
        "delivery_target_class": delivery_target_class,
        "blocked_reasons": blocked_reasons,
        "review_channel": {
            "status": channel.get("status"),
            "reason": channel.get("reason"),
            "channel": channel.get("channel"),
            "target_ref": channel.get("target_ref"),
            "direct_message": channel.get("direct_message"),
            "configured_by_owner": channel.get("configured_by_owner"),
            "fallback_used": channel.get("fallback_used"),
            "raw_body_included": channel.get("raw_body_included"),
        },
        "digest": {
            "schema_version": preview.get("schema_version"),
            "digest_id": preview.get("digest_id"),
            "status": preview.get("status"),
            "counts": preview.get("counts"),
            "overflow": preview.get("overflow"),
            "raw_body_included": preview.get("raw_body_included"),
            "will_send": preview.get("will_send"),
            "actions_enabled": preview.get("actions_enabled"),
        },
        "delivery_status": owner_review_delivery_status_report(store),
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
        },
    }


def deliver_owner_review_digest_once(
    store: MemoryOSStore,
    *,
    owner_id: str = "",
    delivery_key: str = "",
    owner_triggered: bool = False,
    apply: bool = False,
) -> dict[str, Any]:
    config = load_config(store.roots.hermes_home).get("owner_review", {})
    if not isinstance(config, dict):
        config = {}
    resolved_owner = str(owner_id or config.get("owner_id") or "owner")
    gate = owner_review_delivery_gate_report(store, owner_id=resolved_owner)
    preview = owner_review_digest_preview(store, owner_id=resolved_owner)
    channel = gate.get("review_channel") if isinstance(gate.get("review_channel"), dict) else {}
    created_at = datetime.now(timezone.utc)
    key = str(delivery_key or "").strip()
    if not key:
        key = f"{resolved_owner}|one_shot|{created_at.strftime('%Y%m%dT%H%M%S%fZ')}"
    existing = _find_delivery_by_key(store.roots, key)
    if existing:
        duplicate = _base_delivery_record(
            store,
            owner_id=resolved_owner,
            delivery_key=key,
            digest_id=str(existing.get("digest_id") or ""),
            channel=channel,
            result="duplicate_ignored",
            created_at=created_at,
        )
        duplicate["result_ref"] = {"existing_delivery_id": existing.get("delivery_id", "")}
        if apply:
            _append_owner_review_delivery(store, duplicate)
        return {
            "schema_version": OWNER_REVIEW_DELIVERY_SCHEMA_VERSION,
            "profile": store.roots.profile or "default",
            "status": "duplicate_ignored",
            "dry_run": not apply,
            "record": duplicate,
            "gate": gate,
        }

    record = _base_delivery_record(
        store,
        owner_id=resolved_owner,
        delivery_key=key,
        digest_id=str(preview.get("digest_id") or ""),
        channel=channel,
        result="dry_run" if not apply else "skipped",
        created_at=created_at,
    )
    record["digest"] = _bounded_delivery_digest(preview)

    blocked_reasons = list(gate.get("blocked_reasons") or [])
    if not owner_triggered:
        blocked_reasons.append("owner_trigger_required")
    if preview.get("raw_body_included") is True:
        blocked_reasons.append("digest_preview_raw_body")
    if channel.get("raw_body_included") is True:
        blocked_reasons.append("review_channel_raw_body")

    if blocked_reasons:
        record["result"] = "skipped"
        record["blocked_reasons"] = blocked_reasons
        result = {
            "schema_version": OWNER_REVIEW_DELIVERY_SCHEMA_VERSION,
            "profile": store.roots.profile or "default",
            "status": "skipped",
            "dry_run": not apply,
            "record": record,
            "gate": gate,
        }
        if apply:
            _append_owner_review_delivery(store, record)
        return result

    message = _delivery_message_from_preview(preview)
    record["text_char_count"] = len(message)
    if not apply:
        record["result"] = "ready"
        return {
            "schema_version": OWNER_REVIEW_DELIVERY_SCHEMA_VERSION,
            "profile": store.roots.profile or "default",
            "status": "ready",
            "dry_run": True,
            "record": record,
            "gate": gate,
        }

    send_result = _send_owner_review_digest_via_hermes(
        hermes_bin=str(config.get("hermes_bin") or "hermes"),
        target_ref=str(channel.get("target_ref") or ""),
        message=message,
    )
    record["delivery_ref"] = send_result.get("delivery_ref") if isinstance(send_result.get("delivery_ref"), dict) else {}
    if send_result.get("ok") is True:
        record["result"] = "sent"
        record["boundary"]["actual_send"] = True
        record["owner_effect"]["owner_approved_digest_delivery"] = True
        status = "sent"
    else:
        record["result"] = "error"
        record["code"] = str(send_result.get("code") or "hermes_send_failed")
        record["blocked_reasons"] = [record["code"]]
        status = "error"
    if apply:
        _append_owner_review_delivery(store, record)
    return {
        "schema_version": OWNER_REVIEW_DELIVERY_SCHEMA_VERSION,
        "profile": store.roots.profile or "default",
        "status": status,
        "dry_run": False,
        "record": record,
        "gate": gate,
    }


def owner_review_queue_report(store: MemoryOSStore, *, limit: int = 20) -> dict[str, Any]:
    closed = _closed_targets(read_owner_action_records(store.roots))
    items = _candidate_cluster_review_items(store, closed)
    items.extend(_candidate_review_items(store, closed))
    items.extend(_proposal_review_items(store, closed))
    items.extend(_proposal_apply_review_items(store, closed))
    items.extend(_session_mirror_apply_review_items(store, closed))
    items.extend(_speak_review_items(store, closed))
    items.extend(_left_brain_advisor_review_items(store, closed))
    items.extend(_provisional_crystallized_review_items(store, closed))
    aged_items, aging = _apply_review_aging(store, items)
    sorted_items = sorted(
        aged_items,
        key=lambda item: (_priority_sort_key(item["priority"]), item["target_type"], item["target_id"]),
    )
    anchored = _with_anchors(sorted_items[: max(int(limit), 0)])
    counts = Counter(str(item.get("priority", "")) for item in sorted_items)
    return {
        "schema_version": OWNER_REVIEW_QUEUE_SCHEMA_VERSION,
        "profile": store.roots.profile or "default",
        "limit": max(int(limit), 0),
        "pending_count": len(sorted_items),
        "action_required_count": int(counts.get("action_required", 0)),
        "review_suggested_count": int(counts.get("review_suggested", 0)),
        "fyi_count": int(counts.get("fyi", 0)),
        "overflow_count": max(len(sorted_items) - max(int(limit), 0), 0),
        "raw_body_included": False,
        "review_aging": _review_aging_summary(sorted_items, aging),
        "items": anchored,
    }


def apply_owner_action(
    store: MemoryOSStore,
    *,
    action_type: str,
    target: str,
    owner_id: str,
    channel: str = "cli",
    note: str = "",
    rating: str = "",
    apply: bool = False,
    reply_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if action_type not in ACTION_TYPES:
        return _action_error(store, action_type, target, owner_id, channel, "invalid_action_type", apply=apply)
    target_type, target_id = _normalize_target(action_type, target)
    original_target_id = target_id
    if action_type in EXPRESSION_FEEDBACK_ACTION_TYPES and target_type == "expression":
        outcome = _find_right_brain_expression_outcome(store.roots, target_id)
        if outcome and str(outcome.get("outcome_id") or ""):
            target_id = str(outcome.get("outcome_id") or "")
    idempotency_action_type = _idempotency_action_type(action_type, rating=rating)
    idempotency_key = _idempotency_key(
        owner_id=owner_id,
        target_type=target_type,
        target_id=target_id,
        action_type=idempotency_action_type,
    )
    existing = _find_idempotent_action(store.roots, idempotency_key)
    if existing:
        duplicate = _duplicate_record(existing, idempotency_key, action_type, target_type, target_id, owner_id, channel)
        if apply:
            _append_owner_action(store, duplicate)
        return {
            "schema_version": OWNER_ACTION_RESULT_SCHEMA_VERSION,
            "profile": store.roots.profile or "default",
            "status": "duplicate_ignored",
            "dry_run": not apply,
            "idempotency_key": idempotency_key,
            "existing_owner_action_id": existing.get("owner_action_id", ""),
            "record": duplicate,
        }

    validation_error = _validate_action_target(store, action_type, target_type, target_id, rating=rating)
    if validation_error:
        return _action_error(
            store,
            action_type,
            target,
            owner_id,
            channel,
            validation_error,
            target_type=target_type,
            target_id=target_id,
            idempotency_key=idempotency_key,
            apply=apply,
        )

    record = _base_action_record(
        idempotency_key=idempotency_key,
        action_type=action_type,
        target_type=target_type,
        target_id=target_id,
        owner_id=owner_id,
        channel=channel,
        result="dry_run" if not apply else "applied",
        note=note,
        rating=rating,
    )
    _attach_owner_reply_context(record, reply_context or {})
    if original_target_id != target_id:
        record["original_target_id"] = original_target_id
    if action_type in {"approve_proposal", "reject_proposal"}:
        proposal = _find_proposal(store, target_id)
        if proposal:
            record["action_context"] = {
                "proposal_followup_auto_route_owner_decision": _proposal_followup_auto_route_owner_decision_context(
                    proposal,
                    action_type=action_type,
                )
            }
    result_ref: dict[str, Any] = {}
    if apply:
        result_ref = _apply_state_transition(store, record, note=note, rating=rating)
        record["result_ref"] = result_ref
        _append_owner_action(store, record)
        _append_action_specific_ledger(store, record)
    return {
        "schema_version": OWNER_ACTION_RESULT_SCHEMA_VERSION,
        "profile": store.roots.profile or "default",
        "status": "ok",
        "dry_run": not apply,
        "idempotency_key": idempotency_key,
        "record": record,
        "result_ref": result_ref,
    }


def read_owner_action_records(roots: MemoryOSRoots, *, limit: int = 0) -> list[dict[str, Any]]:
    records = _read_jsonl(owner_actions_path(roots))
    if limit > 0:
        return records[-limit:]
    return records


def read_owner_review_delivery_records(roots: MemoryOSRoots, *, limit: int = 0) -> list[dict[str, Any]]:
    records = _read_jsonl(owner_review_deliveries_path(roots))
    if limit > 0:
        return records[-limit:]
    return records


def read_owner_review_rendered_digest_records(roots: MemoryOSRoots, *, limit: int = 0) -> list[dict[str, Any]]:
    records = _read_jsonl(owner_review_rendered_digests_path(roots))
    if limit > 0:
        return records[-limit:]
    return records


def read_speak_permission_tickets(roots: MemoryOSRoots, *, limit: int = 0) -> list[dict[str, Any]]:
    records = _read_jsonl(speak_permission_tickets_path(roots))
    if limit > 0:
        return records[-limit:]
    return records


def _resolve_reply_digest(
    store: MemoryOSStore,
    *,
    owner_id: str,
    channel: str,
    digest_id: str,
    require_recorded_digest: bool = False,
    anchor: str = "",
    action_token: str = "",
    max_action_required: int | None,
    max_review_suggested: int | None,
    max_fyi: int | None,
) -> tuple[dict[str, Any], str]:
    explicit_digest_id = str(digest_id or "").strip()
    if explicit_digest_id:
        record = _find_rendered_digest_record(
            store.roots,
            digest_id=explicit_digest_id,
            owner_id=owner_id,
            channel=channel,
        )
        if not record:
            return _empty_rendered_digest(store, owner_id=owner_id), "digest_not_found"
        return _rendered_digest_from_record(record), "recorded_digest"

    record = _latest_rendered_digest_record(store.roots, owner_id=owner_id, channel=channel)
    if record:
        return _rendered_digest_from_record(record), "latest_recorded_digest"

    record = _latest_owner_home_digest_record(
        store.roots,
        owner_id=owner_id,
        anchor=anchor,
        action_token=action_token,
    )
    if record:
        return _rendered_digest_from_record(record), "latest_owner_home_digest"

    if require_recorded_digest:
        return _empty_rendered_digest(store, owner_id=owner_id), "digest_not_found"

    return (
        render_owner_review_digest(
            store,
            owner_id=owner_id,
            channel=channel,
            max_action_required=max_action_required,
            max_review_suggested=max_review_suggested,
            max_fyi=max_fyi,
        ),
        "current_digest_fallback",
    )


def _append_owner_review_rendered_digest(store: MemoryOSStore, rendered: dict[str, Any], *, channel: str) -> None:
    path = owner_review_rendered_digests_path(store.roots)
    record = {
        "schema_version": "memory-os.owner_review_rendered_digest_record.v0",
        "digest_id": str(rendered.get("digest_id") or ""),
        "created_at": str(rendered.get("created_at") or ""),
        "profile": store.roots.profile or "default",
        "owner_id": str(rendered.get("owner_id") or "owner"),
        "channel": _safe_channel(channel),
        "delivery_binding": rendered.get("delivery_binding") if isinstance(rendered.get("delivery_binding"), dict) else {},
        "rendered_digest": _bounded_rendered_digest(rendered),
        "raw_body_included": False,
    }
    _append_jsonl(path, record)
    append_audit(
        store.roots.audit_path,
        action="owner_review_rendered_digest_recorded",
        status="ok",
        target=str(path),
        details={
            "digest_id": record["digest_id"],
            "owner_id": record["owner_id"],
            "channel": record["channel"],
            "delivery_scope": (record.get("delivery_binding") or {}).get("scope", ""),
            "raw_body_included": False,
        },
    )


def _find_rendered_digest_record(
    roots: MemoryOSRoots,
    *,
    digest_id: str,
    owner_id: str,
    channel: str,
) -> dict[str, Any] | None:
    for record in reversed(read_owner_review_rendered_digest_records(roots)):
        if str(record.get("digest_id") or "") != digest_id:
            continue
        if owner_id and str(record.get("owner_id") or "") != owner_id:
            continue
        if channel and str(record.get("channel") or "") != _safe_channel(channel):
            continue
        return record
    return None


def _latest_rendered_digest_record(roots: MemoryOSRoots, *, owner_id: str, channel: str) -> dict[str, Any] | None:
    for record in reversed(read_owner_review_rendered_digest_records(roots)):
        if owner_id and str(record.get("owner_id") or "") != owner_id:
            continue
        if channel and str(record.get("channel") or "") != _safe_channel(channel):
            continue
        return record
    return None


def _latest_owner_home_digest_record(
    roots: MemoryOSRoots,
    *,
    owner_id: str,
    anchor: str = "",
    action_token: str = "",
) -> dict[str, Any] | None:
    target_anchor = str(anchor or "").upper()
    target_token = str(action_token or "").lower()
    for record in reversed(read_owner_review_rendered_digest_records(roots)):
        if owner_id and str(record.get("owner_id") or "") != owner_id:
            continue
        binding = record.get("delivery_binding") if isinstance(record.get("delivery_binding"), dict) else {}
        if str(binding.get("scope") or "") != "owner_home":
            continue
        if target_anchor and not _record_has_anchor(record, target_anchor):
            continue
        if target_token and not _record_has_action_token(record, target_token):
            continue
        return record
    return None


def _record_has_anchor(record: dict[str, Any], anchor: str) -> bool:
    target_anchor = str(anchor or "").upper()
    if not target_anchor:
        return True
    return target_anchor in _rendered_anchor_map(_rendered_digest_from_record(record))


def _record_has_action_token(record: dict[str, Any], action_token: str) -> bool:
    target_token = str(action_token or "").lower()
    if not target_token:
        return True
    return target_token in _rendered_action_token_map(_rendered_digest_from_record(record))


def _rendered_digest_from_record(record: dict[str, Any]) -> dict[str, Any]:
    rendered = record.get("rendered_digest") if isinstance(record.get("rendered_digest"), dict) else {}
    if rendered:
        return dict(rendered)
    return {
        "schema_version": OWNER_REVIEW_RENDERED_DIGEST_SCHEMA_VERSION,
        "digest_id": record.get("digest_id"),
        "created_at": record.get("created_at"),
        "profile": record.get("profile"),
        "owner_id": record.get("owner_id"),
        "status": "ok",
        "sections": {"action_required": [], "review_suggested": [], "fyi": []},
        "raw_body_included": False,
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
        },
    }


def _bounded_rendered_digest(rendered: dict[str, Any]) -> dict[str, Any]:
    sections = rendered.get("sections") if isinstance(rendered.get("sections"), dict) else {}
    return {
        "schema_version": OWNER_REVIEW_RENDERED_DIGEST_SCHEMA_VERSION,
        "digest_id": rendered.get("digest_id"),
        "created_at": rendered.get("created_at"),
        "profile": rendered.get("profile"),
        "owner_id": rendered.get("owner_id"),
        "status": rendered.get("status"),
        "mode": rendered.get("mode"),
        "will_send": False,
        "actions_enabled": False,
        "raw_body_included": False,
        "delivery_binding": rendered.get("delivery_binding") if isinstance(rendered.get("delivery_binding"), dict) else {},
        "counts": rendered.get("counts") if isinstance(rendered.get("counts"), dict) else {},
        "overflow": rendered.get("overflow") if isinstance(rendered.get("overflow"), dict) else {},
        "sections": {
            "action_required": [_bounded_rendered_item(item) for item in sections.get("action_required", [])],
            "review_suggested": [_bounded_rendered_item(item) for item in sections.get("review_suggested", [])],
            "fyi": [_bounded_rendered_item(item) for item in sections.get("fyi", [])],
        },
        "text": _bounded_text(str(rendered.get("text") or ""), 3500),
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
        },
    }


def _owner_review_delivery_binding(store: MemoryOSStore, channel: str) -> dict[str, Any]:
    config = load_config(store.roots.hermes_home).get("owner_review", {})
    if not isinstance(config, dict):
        config = {}
    safe_channel = _safe_channel(channel)
    recurring_channel = _safe_channel(str(config.get("recurring_delivery_channel") or ""))
    recurring_enabled = bool(config.get("recurring_delivery_enabled"))
    recurring_mode = str(config.get("recurring_delivery_mode") or "")
    scope = "channel"
    if recurring_enabled and recurring_mode in {"hermes_cron", "hermes_cron_agent"} and recurring_channel == safe_channel:
        scope = "owner_home"
    return {
        "schema_version": "memory-os.owner_review_delivery_binding.v0",
        "scope": scope,
        "channel": safe_channel,
        "recurring_delivery_channel": recurring_channel,
        "deliver_target_class": str(config.get("recurring_delivery_target_class") or "missing"),
        "raw_body_included": False,
    }


def _bounded_rendered_item(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    return {
        "anchor": str(item.get("anchor") or ""),
        "review_item_id": str(item.get("review_item_id") or ""),
        "target_type": str(item.get("target_type") or ""),
        "target_id": str(item.get("target_id") or ""),
        "source_module": str(item.get("source_module") or ""),
        "section": str(item.get("section") or ""),
        "question": _bounded_text(str(item.get("question") or ""), 220),
        "suggested_action": _bounded_text(str(item.get("suggested_action") or ""), 220),
        "reason": _bounded_text(str(item.get("reason") or ""), 240),
        "consequence": _bounded_text(str(item.get("consequence") or ""), 240),
        "proposed_memory_text": _bounded_text(str(item.get("proposed_memory_text") or ""), 360),
        "proposal_detail": _bounded_text(str(item.get("proposal_detail") or ""), 620),
        "proposal_kind": _bounded_text(str(item.get("proposal_kind") or ""), 120),
        "ops_gate_report_id": _bounded_text(str(item.get("ops_gate_report_id") or ""), 120),
        "requires_maturation": bool(item.get("requires_maturation")),
        "expression_preview": _bounded_text(str(item.get("expression_preview") or ""), 360),
        "expression_preview_suppressed": bool(item.get("expression_preview_suppressed")),
        "session_mirror_approval": _bounded_session_mirror_approval(
            item.get("session_mirror_approval") if isinstance(item.get("session_mirror_approval"), dict) else {}
        ),
        "action_tokens": {
            str(key): str(value)
            for key, value in (item.get("action_tokens") if isinstance(item.get("action_tokens"), dict) else {}).items()
        },
        "action_targets": {
            str(key): {
                "target_type": str(value.get("target_type") or ""),
                "target_id": str(value.get("target_id") or ""),
            }
            for key, value in (
                item.get("action_targets") if isinstance(item.get("action_targets"), dict) else {}
            ).items()
            if isinstance(value, dict)
        },
        "owner_utterance_scope": str(item.get("owner_utterance_scope") or "owner_chat_utterance"),
        "owner_utterance_examples": [
            str(value)
            for value in (item.get("owner_utterance_examples") or item.get("action_commands") or [])
        ][:8],
        "agent_tool_calls": [
            value
            for value in (item.get("agent_tool_calls") if isinstance(item.get("agent_tool_calls"), list) else [])
            if isinstance(value, dict)
        ][:8],
        "safe_source_ids": [str(source_id) for source_id in item.get("safe_source_ids") or []][:12],
        "raw_body_included": False,
    }


def _empty_rendered_digest(store: MemoryOSStore, *, owner_id: str) -> dict[str, Any]:
    return {
        "schema_version": OWNER_REVIEW_RENDERED_DIGEST_SCHEMA_VERSION,
        "digest_id": "",
        "created_at": "",
        "profile": store.roots.profile or "default",
        "owner_id": owner_id,
        "status": "missing",
        "sections": {"action_required": [], "review_suggested": [], "fyi": []},
        "raw_body_included": False,
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
        },
    }


def _apply_state_transition(store: MemoryOSStore, record: dict[str, Any], *, note: str, rating: str) -> dict[str, Any]:
    action_type = str(record["action_type"])
    target_id = str(record["target_id"])
    if action_type == "approve_external_evidence":
        from .provenance import candidate_external_ref
        candidate = _find_candidate(store, target_id)
        assert candidate is not None
        external_ref = candidate_external_ref(candidate, store=store) or ""

        action_ctx = record.get("action_context") or {}
        acked_ref = str(action_ctx.get("acked_external_ref") or external_ref)

        decision = ApprovalDecision(
            candidate_id=candidate.candidate_id,
            purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
            reviewer=str(record["owner_id"]),
            reviewed_at=str(record["created_at"]),
            note=note,
            external_evidence_ack=True,
            acked_external_ref=acked_ref,
        )
        path = CrystallizedMemoryService(store).write_approved_record(
            candidate,
            decision,
            file_name="owner_approved.md",
        )
        record["owner_effect"]["owner_approved_external_evidence"] = True
        record["owner_effect"]["owner_approved_crystallized_write"] = True
        return {
            "crystallized_path": str(path),
            "candidate_id": target_id,
            "acked_external_ref": acked_ref,
        }
    if action_type == "approve_candidate":
        candidate = _find_candidate(store, target_id)
        assert candidate is not None
        decision = ApprovalDecision(
            candidate_id=candidate.candidate_id,
            purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
            reviewer=str(record["owner_id"]),
            reviewed_at=str(record["created_at"]),
            note=note,
        )
        path = CrystallizedMemoryService(store).write_approved_record(
            candidate,
            decision,
            file_name="owner_approved.md",
        )
        record["owner_effect"]["owner_approved_crystallized_write"] = True
        return {"crystallized_path": str(path), "candidate_id": target_id}
    if action_type == "reject_candidate":
        return {"candidate_id": target_id, "state": "owner_rejected"}
    if action_type in {"approve_candidate_cluster", "reject_candidate_cluster", "defer_candidate_cluster"}:
        cluster, scope, status = find_candidate_cluster_by_target(store, target_id)
        if status != "ok" or cluster is None:
            return {"state": "failed_closed", "code": status, "cluster_scope": scope}
        record["action_context"] = {"candidate_cluster_scope": scope}
        if action_type == "approve_candidate_cluster":
            service = CrystallizedMemoryService(store)
            paths: list[str] = []
            approved_ids: list[str] = []
            candidates = {candidate.candidate_id: candidate for candidate in read_candidate_queue(store.roots)}
            for candidate_id in scope["member_candidate_ids"]:
                candidate = candidates.get(str(candidate_id))
                if candidate is None:
                    return {"state": "failed_closed", "code": "candidate_cluster_member_missing", "cluster_scope": scope}
                decision = ApprovalDecision(
                    candidate_id=candidate.candidate_id,
                    purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
                    reviewer=str(record["owner_id"]),
                    reviewed_at=str(record["created_at"]),
                    note=_bounded_text(note or "owner_approved_candidate_cluster", 240),
                )
                path = service.write_approved_record(
                    candidate,
                    decision,
                    file_name="owner_approved.md",
                )
                paths.append(str(path))
                approved_ids.append(candidate.candidate_id)
            record["owner_effect"]["owner_approved_crystallized_write"] = True
            record["owner_effect"]["owner_approved_candidate_cluster"] = True
            return {
                "cluster_id": scope["cluster_id"],
                "cluster_scope_hash": scope["scope_hash"],
                "approved_candidate_ids": approved_ids,
                "crystallized_paths": paths,
                "canonical_write_count": len(paths),
                "state": "owner_approved_cluster",
            }
        state = "owner_rejected_cluster" if action_type == "reject_candidate_cluster" else "owner_deferred_cluster"
        return {
            "cluster_id": scope["cluster_id"],
            "cluster_scope_hash": scope["scope_hash"],
            "member_candidate_ids": list(scope["member_candidate_ids"]),
            "state": state,
            "canonical_write_count": 0,
        }
    if action_type == "revoke_crystallized":
        revoke_result = CrystallizedMemoryService(store).revoke_record(
            target_id,
            revoked_by=str(record["owner_id"]),
            reason=_bounded_text(note or "owner_revoked", 240),
        )
        snapshot_id = _hindsight_snapshot_id_for_store(store)
        from .substrates.ledger import SubstrateOperationLedger
        from plugins.modules.governance.crystallized_revalidator import (
            invalidate_hindsight_projection_for_canonical_change,
        )

        invalidate_hindsight_projection_for_canonical_change(
            projection_ledger_path=store.roots.memory_os_root / "system" / "projection_ledger.jsonl",
            record_id=target_id,
            record_version="current",
            reason="owner_revoked",
            substrate_snapshot_id=snapshot_id,
        )
        SubstrateOperationLedger(store.roots.memory_os_root / "system" / "substrate_operations.jsonl").append(
            {
                "provider": "hindsight",
                "operation": "invalidate",
                "source_record_ref": target_id,
                "source_version": "current",
                "reason": "owner_revoked",
                "substrate_snapshot_id": snapshot_id,
            }
        )
        record["owner_effect"]["owner_revoked_crystallized_record"] = True
        record["owner_effect"]["projection_invalidation_recorded"] = True
        return {
            **revoke_result,
            "actual_delete": False,
            "projection_invalidated": True,
            "substrate_snapshot_id": snapshot_id,
        }
    if action_type == "demote_crystallized":
        demote_result = CrystallizedMemoryService(store).demote_record(
            target_id,
            demoted_by=str(record["owner_id"]),
            reason=_bounded_text(note or "owner_demoted", 240),
        )
        snapshot_id = _hindsight_snapshot_id_for_store(store)
        from .substrates.ledger import SubstrateOperationLedger
        from plugins.modules.governance.crystallized_revalidator import (
            invalidate_hindsight_projection_for_canonical_change,
        )

        invalidate_hindsight_projection_for_canonical_change(
            projection_ledger_path=store.roots.memory_os_root / "system" / "projection_ledger.jsonl",
            record_id=target_id,
            record_version="current",
            reason="owner_demoted",
            substrate_snapshot_id=snapshot_id,
        )
        SubstrateOperationLedger(store.roots.memory_os_root / "system" / "substrate_operations.jsonl").append(
            {
                "provider": "hindsight",
                "operation": "invalidate",
                "source_record_ref": target_id,
                "source_version": "current",
                "reason": "owner_demoted",
                "substrate_snapshot_id": snapshot_id,
            }
        )
        record["owner_effect"]["owner_demoted_crystallized_record"] = True
        record["owner_effect"]["projection_invalidation_recorded"] = True
        return {
            **demote_result,
            "actual_delete": False,
            "projection_invalidated": True,
            "substrate_snapshot_id": snapshot_id,
        }
    if action_type in {"approve_proposal", "reject_proposal"}:
        from plugins.modules.governance.proposal_queue import ProposalQueueModule

        module = ProposalQueueModule(store.roots.hermes_home, profile=store.roots.profile or "default")
        decision = "approve" if action_type == "approve_proposal" else "reject"
        proposal = module.transition(
            store=store,
            candidate_id=target_id,
            decision=decision,
            reviewer=str(record["owner_id"]),
            note=note,
        )
        return {"proposal_id": target_id, "state": proposal.get("state", "")}
    if action_type == "apply_proposal":
        return apply_approved_proposal_execution_decision(
            store,
            proposal_id=target_id,
            owner_id=str(record["owner_id"]),
            channel=str(record["channel"]),
            owner_approved=True,
            apply=True,
        )
    if action_type == "mark_feedback":
        feedback = _append_feedback(store, record, rating=rating, note=note)
        return {"feedback_id": feedback["feedback_id"], "memory_source_record_id": target_id}
    if action_type == "allow_speak_once":
        ticket = _append_speak_ticket(store, record)
        return {
            "ticket_id": ticket["ticket_id"],
            "target_id": target_id,
            "status": ticket.get("status"),
            "actual_send": bool(ticket.get("actual_send")),
            "delivery_ref": ticket.get("delivery_ref") if isinstance(ticket.get("delivery_ref"), dict) else {},
            "error_code": str(ticket.get("error_code") or ""),
        }
    if action_type == "approve_session_mirror_apply":
        context = record.pop("action_context", {})
        approval = (
            context.get("session_mirror_approval")
            if isinstance(context.get("session_mirror_approval"), dict)
            else {}
        )
        record["owner_effect"]["owner_approved_session_mirror_apply"] = True
        return {
            "approval_scope": "session_mirror_production_bounded_apply",
            "stable_scope_id": str(approval.get("stable_scope_id") or ""),
            "digest_item_id": str(approval.get("digest_item_id") or ""),
            "selected_pending_session_fingerprint": str(
                approval.get("selected_pending_session_fingerprint") or ""
            ),
            "boundary_contract_version": str(approval.get("boundary_contract_version") or ""),
            "max_sessions": max(int(approval.get("max_sessions") or 1), 1),
            "platform_allowlist": approval.get("platform_allowlist")
            if isinstance(approval.get("platform_allowlist"), list)
            else [],
            "auto_apply_after_graduation": bool(approval.get("auto_apply_after_graduation")),
            "auto_apply_max_sessions_per_run": max(int(approval.get("auto_apply_max_sessions_per_run") or 1), 1),
            "expires_at": str(approval.get("expires_at") or ""),
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
        }
    if action_type in HINDSIGHT_CURATION_ACTION_TYPES:
        decision = _append_hindsight_curation_decision(store, record, note=note)
        record["owner_effect"]["owner_recorded_hindsight_curation_decision"] = True
        return {
            "decision_id": decision["decision_id"],
            "curation_decision": decision["curation_decision"],
            "actual_hindsight_write": False,
            "actual_hindsight_delete": False,
            "actual_execute": False,
        }
    if action_type in EXPRESSION_FEEDBACK_ACTION_TYPES:
        feedback = _append_expression_feedback(store, record, note=note)
        return {
            "feedback_id": feedback["feedback_id"],
            "draft_id": feedback["draft_id"],
            "outcome_id": feedback.get("outcome_id", ""),
            "request_id": feedback.get("request_id", ""),
            "outcome_feedback_linked": bool(feedback.get("outcome_feedback_linked")),
        }
    if action_type == "confirm_provisional_crystallized_record":
        result = CrystallizedMemoryService(store).confirm_provisional_record(
            target_id, confirmed_by=str(record["owner_id"]),
        )
        record["owner_effect"]["owner_confirmed_provisional"] = True
        return {"record_id": target_id, "canonical_state_changed": result.get("canonical_state_changed", False)}
    if action_type == "reject_provisional_crystallized_record":
        result = CrystallizedMemoryService(store).invalidate_provisional_record(
            target_id, reason="owner_rejected", invalidated_by=str(record["owner_id"]),
        )
        record["owner_effect"]["owner_rejected_provisional"] = True
        return {"record_id": target_id, "canonical_state_changed": result.get("canonical_state_changed", False)}
    if action_type == "confirm_provisional_knob_override":
        return _apply_confirm_provisional_knob_override(store, record)
    if action_type == "reject_provisional_knob_override":
        return _apply_reject_provisional_knob_override(store, record)
    if action_type == "approve_edge":
        from .index import MemoryOSIndex
        index = MemoryOSIndex(store.roots)
        result = index.transition_edge_state(target_id, "active")
        if result and result.get("state") == "active":
            record["owner_effect"]["owner_approved_edge"] = True
        return {"edge_id": target_id, "new_state": result.get("state", "active") if result else "failed"}
    if action_type == "reject_edge":
        from .index import MemoryOSIndex
        index = MemoryOSIndex(store.roots)
        result = index.transition_edge_state(target_id, "invalidated")
        if result and result.get("state") == "invalidated":
            record["owner_effect"]["owner_rejected_edge"] = True
        return {"edge_id": target_id, "new_state": result.get("state", "invalidated") if result else "failed"}
    return {}


def _apply_confirm_provisional_knob_override(store: MemoryOSStore, action: dict[str, Any]) -> dict[str, Any]:
    """Confirm a provisional knob override (owner action)."""
    from plugins.memory.memory_os.knob_overrides import _override_store_path
    from plugins.memory.memory_os.structural_write_gate import append_governed_jsonl
    from uuid import uuid4

    target_id = str(action.get("target_id") or "")
    now = datetime.now(timezone.utc)
    store_path = _override_store_path(store.roots)

    # Find the active override
    original = None
    for record in _read_jsonl(store_path):
        if record.get("id") == target_id:
            original = record
            break

    if original is None:
        return {"status": "error", "reason": "override_not_found"}

    # Write confirmed record through structural write gate
    confirmed = {
        "schema_version": "memory-os.knob_override.v0",
        "id": f"ko_owner_confirm_{now.strftime('%Y%m%dT%H%M%S%fZ')}_{uuid4().hex[:10]}",
        "knob": original.get("knob"),
        "override_value": original.get("override_value"),
        "prior_value": original.get("prior_value"),
        "bounds": original.get("bounds"),
        "provisional": False,
        "expires_at": "",
        "proposed_by": "owner",
        "approved_via": "owner",
        "state": "confirmed",
        "confirmed_from": target_id,
        "ts": now.isoformat(),
    }
    append_governed_jsonl(
        store,
        store_path,
        confirmed,
        write_owner="owner_action",
        lane_id="owner_knob_override_confirm",
        risk_class="owner_gated_knob_override",
        execution_gate_envelope_id="",
        scope_hash="owner_action_gated",
        allow_owner_action_without_envelope=True,
    )

    append_audit(
        store.roots.audit_path,
        action="knob_override_confirmed",
        status="ok",
        target=f"knob:{original.get('knob')}",
        details={"override_id": target_id, "confirmed_by": "owner"},
    )
    return {"status": "ok", "action": "confirmed", "confirmed_id": confirmed["id"]}


def _apply_reject_provisional_knob_override(store: MemoryOSStore, action: dict[str, Any]) -> dict[str, Any]:
    """Reject a provisional knob override — revert to prior value."""
    from plugins.memory.memory_os.knob_overrides import revert_override

    target_id = str(action.get("target_id") or "")
    rev = revert_override(target_id, reason="owner_rejected", roots=store.roots)

    append_audit(
        store.roots.audit_path,
        action="knob_override_rejected",
        status="ok",
        target=f"knob:{rev.get('knob')}",
        details={"override_id": target_id, "reverted_to": rev.get("override_value")},
    )
    return {"status": "ok", "action": "reverted", "reverted_to": rev.get("override_value")}


def _validate_action_target(
    store: MemoryOSStore,
    action_type: str,
    target_type: str,
    target_id: str,
    *,
    rating: str,
) -> str:
    if action_type in {"approve_candidate", "reject_candidate"} and not _find_candidate(store, target_id):
        return "candidate_not_found"
    if action_type == "approve_external_evidence":
        candidate = _find_candidate(store, target_id)
        if candidate is None:
            return "candidate_not_found"
        from .provenance import candidate_external_ref, is_tainted
        if not is_tainted(candidate, store=store):
            return "candidate_not_tainted"
        if not candidate_external_ref(candidate, store=store):
            return "external_evidence_ref_unresolved"
        return ""
    if action_type in {"approve_candidate_cluster", "reject_candidate_cluster", "defer_candidate_cluster"}:
        if target_type != "candidate_cluster":
            return "invalid_candidate_cluster_target"
        _cluster, _scope, status = find_candidate_cluster_by_target(store, target_id)
        if status != "ok":
            return status
    if action_type in {"revoke_crystallized", "demote_crystallized"}:
        if target_type != "crystallized_record":
            return "invalid_crystallized_record_target"
        if not _find_crystallized_record(store, target_id):
            return "crystallized_record_not_found"
    if action_type in {"approve_proposal", "reject_proposal"}:
        proposal = _find_proposal(store, target_id)
        if not proposal:
            return "proposal_not_found"
        allowed_states = {"candidate", "owner_eligible", "owner_defer"}
        if action_type == "reject_proposal":
            allowed_states.add("approved_for_proposal")
        if str(proposal.get("state", "")) not in allowed_states:
            return "proposal_not_pending"
    if action_type == "apply_proposal":
        report = apply_approved_proposal_execution_decision(
            store,
            proposal_id=target_id,
            owner_id="validation",
            channel="validation",
            owner_approved=False,
            apply=False,
        )
        if report.get("status") != "ready":
            return str(report.get("reason") or "proposal_apply_not_ready")
    if action_type == "mark_feedback":
        if rating not in ALLOWED_FEEDBACK_RATINGS:
            return "invalid_feedback_rating"
        if not _find_memory_source(store, target_id):
            return "memory_source_not_found"
    if action_type == "allow_speak_once":
        if target_type != "speak":
            return "invalid_speak_target"
        would_send = _find_speak_would_send(store, target_id)
        if not would_send:
            return "speak_target_not_found"
        payload_ref = str(would_send.get("payload_ref") or "")
        if _contains_transcript_marker(_expression_text_for_payload_ref(store, payload_ref)):
            return "speak_payload_transcript_marker"
    if action_type in EXPRESSION_FEEDBACK_ACTION_TYPES and target_type != "expression":
        return "invalid_expression_target"
    if action_type == "approve_session_mirror_apply":
        if target_type != "session_mirror_apply":
            return "invalid_session_mirror_apply_target"
        if not target_id.startswith("production_bounded:"):
            return "invalid_session_mirror_apply_scope"
    if action_type in HINDSIGHT_CURATION_ACTION_TYPES:
        if target_type != "hindsight_curation":
            return "invalid_hindsight_curation_target"
        if not _find_hindsight_curation_finding(store, target_id):
            return "hindsight_curation_finding_not_found"
    if action_type in {"confirm_provisional_crystallized_record", "reject_provisional_crystallized_record"}:
        if target_type != "provisional_crystallized_record":
            return "invalid_provisional_crystallized_record_target"
        service = CrystallizedMemoryService(store)
        found = service.find_record(target_id)
        if found is None:
            return "provisional_crystallized_record_not_found"
        if found.frontmatter.get("provisional") is not True:
            return "provisional_crystallized_record_not_provisional"
        if not is_active_crystallized_frontmatter(found.frontmatter):
            canon = str(found.frontmatter.get("canonical_state") or "active")
            return f"provisional_crystallized_record_already_{canon}"
    if action_type in {"confirm_provisional_knob_override", "reject_provisional_knob_override"}:
        if target_type != "knob_override":
            return "invalid_knob_override_target"
        from plugins.memory.memory_os.knob_overrides import list_active_overrides
        found = any(o.get("id") == target_id for o in list_active_overrides())
        if not found:
            return "knob_override_not_found_or_not_active"
    if action_type in {"approve_edge", "reject_edge"}:
        if target_type != "edge":
            return "invalid_edge_target"
        if not target_id or not isinstance(target_id, str) or not target_id.strip():
            return "invalid_edge_id"
        from .index import MemoryOSIndex
        index = MemoryOSIndex(store.roots)
        edge = index.get_edge(target_id)
        if edge is None:
            return "edge_not_found"
    return ""


def _append_feedback(store: MemoryOSStore, record: dict[str, Any], *, rating: str, note: str) -> dict[str, Any]:
    created_at = datetime.now(timezone.utc)
    source = _find_memory_source(store, str(record["target_id"])) or {}
    feedback = {
        "schema_version": "memory-os.memory_sources_feedback.v0",
        "feedback_id": f"msfb_{created_at.strftime('%Y%m%dT%H%M%S%fZ')}_{uuid4().hex[:8]}",
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
        "profile": store.roots.profile or "default",
        "memory_source_record_id": str(record["target_id"]),
        "memory_source_created_at": str(source.get("created_at") or ""),
        "route": str(source.get("route") or "unknown"),
        "query_class": str(source.get("query_class") or "unknown"),
        "rating": rating,
        "note": _bounded_text(note, 240),
        "source": "owner_action",
        "owner_action_id": record["owner_action_id"],
    }
    append_memory_source_feedback_record(store.roots, feedback)
    _append_jsonl(feedback_ledger_path(store.roots), feedback)
    append_audit(
        store.roots.audit_path,
        action="owner_action_feedback_recorded",
        status="ok",
        target=str(memory_sources_feedback_path(store.roots)),
        details={
            "feedback_id": feedback["feedback_id"],
            "memory_source_record_id": feedback["memory_source_record_id"],
            "rating": feedback["rating"],
            "owner_action_id": record["owner_action_id"],
        },
    )
    return feedback


def _append_speak_ticket(store: MemoryOSStore, record: dict[str, Any]) -> dict[str, Any]:
    created_at = datetime.now(timezone.utc)
    expires_at = created_at + timedelta(hours=24)
    target_id = str(record["target_id"])
    would_send = _find_speak_would_send(store, target_id) or {}
    payload_ref = str(would_send.get("payload_ref") or "")
    expression_text = _expression_text_for_payload_ref(store, payload_ref)
    ticket = {
        "schema_version": SPEAK_PERMISSION_SCHEMA_VERSION,
        "ticket_id": f"spt_{created_at.strftime('%Y%m%dT%H%M%S%fZ')}_{uuid4().hex[:8]}",
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
        "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
        "profile": store.roots.profile or "default",
        "owner_action_id": record["owner_action_id"],
        "payload_ref": payload_ref or target_id,
        "would_send_id": target_id,
        "status": "pending",
        "actual_send": False,
        "actual_unapproved_send": False,
        "raw_body_included": False,
        "text_char_count": len(expression_text),
        "delivery_ref": {},
    }
    config = _right_brain_speak_once_config(store)
    if bool(config.get("speak_once_delivery_enabled")):
        adapter = str(config.get("delivery_adapter") or "none")
        target_ref = str(config.get("target_ref") or "")
        target_class = _delivery_target_class(target_ref)
        if adapter not in OWNER_REVIEW_DELIVERY_ADAPTERS:
            ticket["status"] = "error"
            ticket["error_code"] = "right_brain_delivery_adapter_unsupported"
            record["result"] = "error"
        elif target_class not in {"explicit_target", "platform_home"}:
            ticket["status"] = "error"
            ticket["error_code"] = "right_brain_delivery_target_not_owner_channel"
            record["result"] = "error"
        elif not expression_text:
            ticket["status"] = "error"
            ticket["error_code"] = "right_brain_expression_empty"
            record["result"] = "error"
        else:
            send_result = _send_owner_review_digest_via_hermes(
                hermes_bin=str(config.get("hermes_bin") or "hermes"),
                target_ref=target_ref,
                message=expression_text,
            )
            ticket["delivery_ref"] = (
                send_result.get("delivery_ref") if isinstance(send_result.get("delivery_ref"), dict) else {}
            )
            if send_result.get("ok") is True:
                ticket["status"] = "sent"
                ticket["actual_send"] = True
                record["boundary"]["actual_send"] = True
            else:
                ticket["status"] = "error"
                ticket["error_code"] = str(send_result.get("code") or "right_brain_hermes_send_failed")
                record["result"] = "error"
    _append_jsonl(speak_permission_tickets_path(store.roots), ticket)
    return ticket


def _append_hindsight_curation_decision(
    store: MemoryOSStore,
    record: dict[str, Any],
    *,
    note: str,
) -> dict[str, Any]:
    created_at = datetime.now(timezone.utc)
    finding = _find_hindsight_curation_finding(store, str(record["target_id"])) or {}
    action_type = str(record["action_type"])
    curation_decision = action_type.removesuffix("_hindsight_curation")
    decision = {
        "schema_version": "memory-os.hindsight_curation_decision.v0",
        "decision_id": f"hcur_{created_at.strftime('%Y%m%dT%H%M%S%fZ')}_{uuid4().hex[:8]}",
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
        "profile": store.roots.profile or "default",
        "owner_action_id": str(record["owner_action_id"]),
        "owner_id": str(record["owner_id"]),
        "channel": str(record.get("channel") or "unknown"),
        "action_type": action_type,
        "curation_decision": curation_decision,
        "finding_id": str(record["target_id"]),
        "source_key": str(finding.get("source_key") or ""),
        "projection_id": str(finding.get("projection_id") or ""),
        "safe_source_ids": _safe_list(finding.get("safe_source_ids")),
        "note": _bounded_text(note, 240),
        "actual_hindsight_write": False,
        "actual_hindsight_delete": False,
        "actual_hindsight_demote": False,
        "actual_execute": False,
        "actual_send": False,
        "actual_policy_write": False,
        "actual_route_score_write": False,
        "hindsight_authoritative": False,
        "advisory_only": True,
        "raw_body_included": False,
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_relationship_write": False,
            "actual_crystallized_approval": False,
            "actual_policy_write": False,
            "actual_route_score_write": False,
            "hindsight_write": False,
        },
    }
    _append_jsonl(hindsight_curation_decisions_path(store.roots), decision)
    append_audit(
        store.roots.audit_path,
        action="hindsight_curation_decision_recorded",
        status="ok",
        target=str(hindsight_curation_decisions_path(store.roots)),
        details={
            "decision_id": decision["decision_id"],
            "curation_decision": curation_decision,
            "finding_id": decision["finding_id"],
            "actual_hindsight_write": False,
        },
    )
    return decision


def _append_expression_feedback(store: MemoryOSStore, record: dict[str, Any], *, note: str) -> dict[str, Any]:
    created_at = datetime.now(timezone.utc)
    target_id = str(record["target_id"])
    outcome = _find_right_brain_expression_outcome(store.roots, target_id)
    linked_outcome_id = str(outcome.get("outcome_id") or "") if outcome else ""
    linked_request_id = str(outcome.get("request_id") or "") if outcome else ""
    feedback_target_id = linked_outcome_id or target_id
    expression_target_id = str(record.get("original_target_id") or target_id)
    feedback = {
        "schema_version": EXPRESSION_FEEDBACK_SCHEMA_VERSION,
        "feedback_id": f"efb_{created_at.strftime('%Y%m%dT%H%M%S%fZ')}_{uuid4().hex[:8]}",
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
        "profile": store.roots.profile or "default",
        "owner_id": str(record["owner_id"]),
        "channel": str(record.get("channel") or "unknown"),
        "owner_action_id": str(record["owner_action_id"]),
        "draft_id": feedback_target_id,
        "expression_target_id": expression_target_id,
        "action_type": str(record["action_type"]),
        "note": _bounded_text(note, 240),
        "source": "owner_action",
        "outcome_feedback_linked": bool(outcome),
        "outcome_id": linked_outcome_id,
        "request_id": linked_request_id,
        "outcome_observed_at": str(outcome.get("observed_at") or "") if outcome else "",
        "policy_version": outcome.get("policy_version") if outcome else None,
        "outcome_silent": outcome.get("silent") if outcome else None,
        "outcome_preview_chars": int(outcome.get("outcome_preview_chars") or 0) if outcome else 0,
        "outcome_preview": "",
        "raw_body_included": False,
        "live_policy_changed": False,
        "actual_send": False,
        "actual_execute": False,
        "actual_identity_write": False,
    }
    _append_jsonl(expression_feedback_ledger_path(store.roots), feedback)
    append_audit(
        store.roots.audit_path,
        action="owner_action_expression_feedback_recorded",
        status="ok",
        target=str(expression_feedback_ledger_path(store.roots)),
        details={
            "feedback_id": feedback["feedback_id"],
            "draft_id": feedback["draft_id"],
            "action_type": feedback["action_type"],
            "owner_action_id": record["owner_action_id"],
            "outcome_id": feedback["outcome_id"],
            "request_id": feedback["request_id"],
            "outcome_feedback_linked": feedback["outcome_feedback_linked"],
            "live_policy_changed": False,
        },
    )
    return feedback


def _find_right_brain_expression_outcome(roots: MemoryOSRoots, target_id: str) -> dict[str, Any] | None:
    records = [
        record
        for record in _read_jsonl(right_brain_expression_outcomes_path(roots))
        if isinstance(record, dict)
    ]
    if not records:
        return None
    normalized = str(target_id or "").strip()
    if normalized in {"latest", "latest_outcome", "last", "last_outcome"}:
        return records[-1]
    for record in reversed(records):
        if str(record.get("outcome_id") or "") == normalized:
            return record
        if str(record.get("request_id") or "") == normalized:
            return record
    return None


def _append_action_specific_ledger(store: MemoryOSStore, record: dict[str, Any]) -> None:
    action_type = str(record.get("action_type", ""))
    if action_type in {
        "approve_candidate",
        "reject_candidate",
        "approve_candidate_cluster",
        "reject_candidate_cluster",
        "defer_candidate_cluster",
        "revoke_crystallized",
        "demote_crystallized",
    }:
        _append_jsonl(crystallization_approvals_path(store.roots), record)
    elif action_type in {"approve_proposal", "reject_proposal", "apply_proposal"}:
        _append_jsonl(proposal_action_ledger_path(store.roots), record)


def _append_owner_action(store: MemoryOSStore, record: dict[str, Any]) -> None:
    path = owner_actions_path(store.roots)
    _append_jsonl(path, record)
    append_audit(
        store.roots.audit_path,
        action="owner_action_recorded",
        status="ok" if record.get("result") != "error" else "error",
        target=str(path),
        details={
            "owner_action_id": record.get("owner_action_id", ""),
            "action_type": record.get("action_type", ""),
            "target_type": record.get("target_type", ""),
            "target_id": record.get("target_id", ""),
            "result": record.get("result", ""),
        },
    )


def _append_owner_review_delivery(store: MemoryOSStore, record: dict[str, Any]) -> None:
    path = owner_review_deliveries_path(store.roots)
    _append_jsonl(path, record)
    append_audit(
        store.roots.audit_path,
        action="owner_review_digest_delivery_recorded",
        status="ok" if record.get("result") != "error" else "error",
        target=str(path),
        details={
            "delivery_id": record.get("delivery_id", ""),
            "delivery_key": record.get("delivery_key", ""),
            "digest_id": record.get("digest_id", ""),
            "result": record.get("result", ""),
            "owner_approved_digest_delivery": (record.get("owner_effect") or {}).get(
                "owner_approved_digest_delivery",
                False,
            ),
            "actual_unapproved_send": (record.get("boundary") or {}).get("actual_unapproved_send", False),
        },
    )


def _action_error(
    store: MemoryOSStore,
    action_type: str,
    target: str,
    owner_id: str,
    channel: str,
    code: str,
    *,
    target_type: str = "",
    target_id: str = "",
    idempotency_key: str = "",
    apply: bool,
) -> dict[str, Any]:
    if not target_type or not target_id:
        target_type, target_id = _normalize_target(action_type, target)
    if not idempotency_key:
        idempotency_key = _idempotency_key(
            owner_id=owner_id,
            target_type=target_type,
            target_id=target_id,
            action_type=action_type,
        )
    record = _base_action_record(
        idempotency_key=idempotency_key,
        action_type=action_type,
        target_type=target_type,
        target_id=target_id,
        owner_id=owner_id,
        channel=channel,
        result="error",
        note="",
        rating="",
    )
    record["code"] = code
    if apply:
        _append_owner_action(store, record)
    return {
        "schema_version": OWNER_ACTION_RESULT_SCHEMA_VERSION,
        "profile": store.roots.profile or "default",
        "status": "error",
        "code": code,
        "dry_run": not apply,
        "idempotency_key": idempotency_key,
        "record": record,
    }


def _base_action_record(
    *,
    idempotency_key: str,
    action_type: str,
    target_type: str,
    target_id: str,
    owner_id: str,
    channel: str,
    result: str,
    note: str,
    rating: str,
) -> dict[str, Any]:
    created_at = datetime.now(timezone.utc)
    return {
        "schema_version": OWNER_ACTION_SCHEMA_VERSION,
        "owner_action_id": f"oact_{created_at.strftime('%Y%m%dT%H%M%S%fZ')}_{uuid4().hex[:8]}",
        "idempotency_key": idempotency_key,
        "action_type": action_type,
        "target_type": target_type,
        "target_id": target_id,
        "owner_id": owner_id,
        "channel": channel,
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
        "result": result,
        "result_ref": {},
        "note": _bounded_text(note, 240),
        "rating": rating,
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
        },
        "owner_effect": {
            "owner_approved_crystallized_write": False,
            "owner_revoked_crystallized_record": False,
            "owner_demoted_crystallized_record": False,
            "owner_approved_session_mirror_apply": False,
            "projection_invalidation_recorded": False,
        },
    }


def _base_delivery_record(
    store: MemoryOSStore,
    *,
    owner_id: str,
    delivery_key: str,
    digest_id: str,
    channel: dict[str, Any],
    result: str,
    created_at: datetime,
) -> dict[str, Any]:
    return {
        "schema_version": OWNER_REVIEW_DELIVERY_SCHEMA_VERSION,
        "delivery_id": f"odel_{created_at.strftime('%Y%m%dT%H%M%S%fZ')}_{uuid4().hex[:8]}",
        "delivery_key": delivery_key,
        "digest_id": digest_id,
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
        "profile": store.roots.profile or "default",
        "owner_id": owner_id,
        "channel": _safe_channel(str(channel.get("channel") or "")),
        "target_ref": _safe_target_ref(str(channel.get("target_ref") or "")),
        "direct_message": bool(channel.get("direct_message")),
        "result": result,
        "blocked_reasons": [],
        "raw_body_included": False,
        "text_char_count": 0,
        "digest": {},
        "delivery_ref": {},
        "boundary": {
            "actual_send": False,
            "actual_unapproved_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
        },
        "owner_effect": {
            "owner_approved_digest_delivery": False,
        },
    }


def _bounded_delivery_digest(preview: dict[str, Any]) -> dict[str, Any]:
    counts = preview.get("counts") if isinstance(preview.get("counts"), dict) else {}
    overflow = preview.get("overflow") if isinstance(preview.get("overflow"), dict) else {}
    return {
        "schema_version": preview.get("schema_version"),
        "digest_id": preview.get("digest_id"),
        "counts": {
            "action_required_total": counts.get("action_required_total"),
            "raw_action_required_total": counts.get("raw_action_required_total"),
            "review_suggested_total": counts.get("review_suggested_total"),
            "fyi_total": counts.get("fyi_total"),
            "action_required_shown": counts.get("action_required_shown"),
            "review_suggested_shown": counts.get("review_suggested_shown"),
            "fyi_shown": counts.get("fyi_shown"),
        },
        "overflow": {
            "action_required": overflow.get("action_required"),
            "review_suggested": overflow.get("review_suggested"),
            "fyi": overflow.get("fyi"),
        },
        "raw_body_included": bool(preview.get("raw_body_included")),
    }


def _bounded_delivery_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": record.get("schema_version"),
        "delivery_id": record.get("delivery_id"),
        "delivery_key": record.get("delivery_key"),
        "digest_id": record.get("digest_id"),
        "created_at": record.get("created_at"),
        "owner_id": record.get("owner_id"),
        "channel": record.get("channel"),
        "target_ref": record.get("target_ref"),
        "result": record.get("result"),
        "blocked_reasons": record.get("blocked_reasons") or [],
        "raw_body_included": record.get("raw_body_included"),
        "text_char_count": record.get("text_char_count"),
        "delivery_ref": record.get("delivery_ref") if isinstance(record.get("delivery_ref"), dict) else {},
        "boundary": record.get("boundary") if isinstance(record.get("boundary"), dict) else {},
        "owner_effect": record.get("owner_effect") if isinstance(record.get("owner_effect"), dict) else {},
    }


def _send_owner_review_digest_via_hermes(
    *,
    hermes_bin: str,
    target_ref: str,
    message: str,
) -> dict[str, Any]:
    command = [str(hermes_bin or "hermes"), "send", "--to", str(target_ref), "--json", str(message)]
    try:
        completed = subprocess.run(command, check=False, text=True, capture_output=True)
    except FileNotFoundError:
        return {
            "ok": False,
            "code": "hermes_send_command_missing",
            "delivery_ref": {
                "adapter": "hermes_send",
                "target_class": _delivery_target_class(target_ref),
                "returncode": 127,
            },
        }

    parsed: dict[str, Any] = {}
    if completed.stdout.strip():
        try:
            loaded = json.loads(completed.stdout)
            if isinstance(loaded, dict):
                parsed = loaded
        except json.JSONDecodeError:
            parsed = {}
    delivery_ref = {
        "adapter": "hermes_send",
        "target_class": _delivery_target_class(target_ref),
        "returncode": completed.returncode,
    }
    delivery_ref.update(_bounded_hermes_send_response(parsed))
    if completed.returncode != 0:
        delivery_ref["stderr_preview"] = _bounded_text(completed.stderr or completed.stdout or "", 320)
        return {"ok": False, "code": "hermes_send_failed", "delivery_ref": delivery_ref}
    return {"ok": True, "delivery_ref": delivery_ref}


def _bounded_hermes_send_response(response: dict[str, Any]) -> dict[str, Any]:
    bounded: dict[str, Any] = {}
    for key in ("ok", "status", "platform", "backend", "message_id", "id"):
        value = response.get(key)
        if value not in (None, ""):
            bounded[key] = _bounded_text(str(value), 160) if isinstance(value, str) else value
    result = response.get("result")
    if isinstance(result, dict):
        for key in ("message_id", "id", "status", "platform", "backend"):
            value = result.get(key)
            if value not in (None, "") and key not in bounded:
                bounded[key] = _bounded_text(str(value), 160) if isinstance(value, str) else value
    error = response.get("error")
    if error not in (None, ""):
        bounded["error"] = _bounded_text(str(error), 240)
    return bounded


def _duplicate_record(
    existing: dict[str, Any],
    idempotency_key: str,
    action_type: str,
    target_type: str,
    target_id: str,
    owner_id: str,
    channel: str,
) -> dict[str, Any]:
    record = _base_action_record(
        idempotency_key=idempotency_key,
        action_type=action_type,
        target_type=target_type,
        target_id=target_id,
        owner_id=owner_id,
        channel=channel,
        result="duplicate_ignored",
        note="",
        rating="",
    )
    record["result_ref"] = {"existing_owner_action_id": existing.get("owner_action_id", "")}
    return record


def _attach_owner_reply_context(record: dict[str, Any], context: dict[str, Any]) -> None:
    if not context:
        return
    record["source"] = str(context.get("source") or "")
    record["digest_id"] = str(context.get("digest_id") or "")
    record["reply_ingress_id"] = str(context.get("reply_ingress_id") or "")
    token_binding = context.get("token_binding") if isinstance(context.get("token_binding"), dict) else {}
    record["token_binding"] = {
        "scope": str(token_binding.get("scope") or ""),
        "digest_id": str(token_binding.get("digest_id") or ""),
        "review_item_id": str(token_binding.get("review_item_id") or ""),
        "action_token_hash": str(token_binding.get("action_token_hash") or ""),
    }
    session_mirror_approval = context.get("session_mirror_approval")
    if isinstance(session_mirror_approval, dict) and session_mirror_approval:
        record["action_context"] = {
            "session_mirror_approval": _bounded_session_mirror_approval(session_mirror_approval),
        }
    acked_ref = context.get("acked_external_ref")
    if acked_ref is not None:
        if "action_context" not in record:
            record["action_context"] = {}
        record["action_context"]["acked_external_ref"] = str(acked_ref)


def _candidate_cluster_review_items(store: MemoryOSStore, closed: set[str]) -> list[dict[str, Any]]:
    clusters = build_candidate_clusters(read_candidate_queue(store.roots))
    items: list[dict[str, Any]] = []
    for cluster in clusters:
        if cluster.member_count < 2:
            continue
        target_id = candidate_cluster_action_target(cluster)
        target_ref = f"candidate_cluster:{target_id}"
        if target_ref in closed:
            continue
        scope = candidate_cluster_scope(cluster)
        actions = _review_actions("candidate_cluster", target_id)
        items.append(
            {
                "schema_version": "memory-os.review_item.v0",
                "review_item_id": f"review:{target_ref}",
                "target_type": "candidate_cluster",
                "target_id": target_id,
                "source_module": "crystallized_candidate_clusters",
                "priority": "action_required",
                "created_at": cluster.created_at_min,
                "created_at_source": "cluster_member_min",
                "status": "pending",
                "summary": _bounded_text(
                    f"候选记忆近重复簇：{cluster.member_count} 条候选 / {cluster.evidence_count} 个安全引用，可一次审一簇。",
                    220,
                ),
                "proposed_memory_text": _bounded_text(cluster.representative_body, 360),
                "candidate_kind": ",".join(sorted(cluster.kinds.keys())),
                "safe_source_ids": [f"event:{event_id}" for event_id in cluster.source_event_ids],
                "cluster_scope": scope,
                "member_candidate_ids": list(cluster.member_candidate_ids),
                "sensitivity": cluster.sensitivity,
                "mixed_sensitivity": cluster.mixed_sensitivity,
                "action_tokens": {action["action_type"]: action["token"] for action in actions},
                "action_targets": {
                    action["action_type"]: {"target_type": action["target_type"], "target_id": action["target_id"]}
                    for action in actions
                },
                "raw_body_included": False,
            }
        )
    return items


def _candidate_review_items(store: MemoryOSStore, closed: set[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    # Read triage records to compute effective states
    triage_records = read_candidate_triage(store)
    for candidate in read_candidate_queue(store.roots):
        target_ref = f"candidate:{candidate.candidate_id}"
        if target_ref in closed:
            continue
        # Skip candidates already tagged as fleeting (no owner action needed)
        effective_state = resolve_candidate_effective_state(candidate, triage_records)
        if effective_state == "fleeting":
            continue
        # Candidates already crystallized — skip
        crystallized_matches = CrystallizedMemoryService(store).find_records_by_candidate_id(candidate.candidate_id)
        if crystallized_matches:
            continue
        needs_consolidation = _candidate_needs_consolidation(candidate.body)
        created_at, created_at_source = _candidate_created_at_info(store, candidate)
        # owner_eligible candidates get action_required; others keep original priority
        priority = "fyi" if needs_consolidation else "action_required"
        items.append(
            {
                "schema_version": "memory-os.review_item.v0",
                "review_item_id": f"review:{target_ref}",
                "target_type": "candidate_cleanup" if needs_consolidation else "candidate",
                "target_id": candidate.candidate_id,
                "source_module": "crystallized_candidates",
                "priority": priority,
                "created_at": created_at,
                "created_at_source": created_at_source,
                "status": "pending",
                "effective_state": effective_state,
                "summary": (
                    "Memory candidate is a transcript/event excerpt and needs consolidation before approval"
                    if needs_consolidation
                    else _bounded_text(f"Proposed memory: {candidate.body}", 260)
                ),
                "proposed_memory_text": "" if needs_consolidation else _bounded_text(candidate.body, 360),
                "candidate_kind": candidate.kind,
                "safe_source_ids": [f"event:{event_id}" for event_id in candidate.source_event_ids],
                "raw_body_included": False,
            }
        )
    return items


def _candidate_created_at(store: MemoryOSStore, candidate: CrystallizedCandidate) -> str:
    return _candidate_created_at_info(store, candidate)[0]


def _candidate_created_at_info(store: MemoryOSStore, candidate: CrystallizedCandidate) -> tuple[str, str]:
    if candidate.created_at:
        return candidate.created_at, "producer"
    if not candidate.source_event_ids:
        return "", "missing"
    events_by_id = {str(event.id): event for event in store.read_events()}
    for event_id in candidate.source_event_ids:
        event = events_by_id.get(str(event_id))
        if not event:
            continue
        created_at = str(getattr(event, "ts", "") or "")
        if created_at:
            return created_at, "safe_source_ref"
    return "", "missing"


def _proposal_review_items(store: MemoryOSStore, closed: set[str]) -> list[dict[str, Any]]:
    proposals = _read_proposal_queue(store)
    items: list[dict[str, Any]] = []
    for proposal in proposals:
        proposal_id = str(proposal.get("candidate_id", ""))
        if not proposal_id:
            continue
        state = str(proposal.get("state", ""))
        if state not in {"candidate", "owner_eligible", "owner_defer"}:
            continue
        requires_maturation = _proposal_requires_maturation(proposal)
        created_at, created_at_source = _created_at_with_source(
            proposal,
            primary_key="created_at",
            fallback_keys=("updated_at",),
            fallback_source="updated_at_fallback",
        )
        items.append(
            {
                "schema_version": "memory-os.review_item.v0",
                "review_item_id": f"review:proposal:{proposal_id}",
                "target_type": "proposal",
                "target_id": proposal_id,
                "source_module": "proposal_queue",
                "priority": "review_suggested" if requires_maturation else "action_required",
                "created_at": created_at,
                "created_at_source": created_at_source,
                "status": "pending",
                "summary": _bounded_text(str(proposal.get("title") or "Proposal candidate"), 160),
                "proposal_detail": _proposal_detail(proposal, requires_maturation=requires_maturation),
                "requires_maturation": requires_maturation,
                "safe_source_ids": _safe_list(proposal.get("source_refs")),
                "raw_body_included": False,
            }
        )
    return items


def _proposal_apply_review_items(store: MemoryOSStore, closed: set[str]) -> list[dict[str, Any]]:
    followups = approved_proposal_followups_report(store, limit=1_000_000)
    _attach_proposal_followup_apply_actions(followups)
    items: list[dict[str, Any]] = []
    for followup in followups.get("items") if isinstance(followups.get("items"), list) else []:
        if not isinstance(followup, dict):
            continue
        proposal_id = str(followup.get("proposal_id") or "")
        if not proposal_id:
            continue
        if str(followup.get("followup_state") or "") != "supported_apply_ready":
            continue
        if not (followup.get("action_tokens") or {}).get("apply_proposal"):
            continue
        title = _bounded_text(str(followup.get("title") or "approved proposal follow-up"), 160)
        proposal_kind = str(followup.get("proposal_kind") or "")
        detail = (
            f"OpsGate report-only 已给出 would_allow；proposal_kind={proposal_kind}。"
            "你现在要决定是否把这个 bounded proposal 写入对应 Memory-OS runtime policy/projection。"
            "这不会创建 generic executor 或 execution ticket。"
        )
        created_at, created_at_source = _created_at_with_source(
            followup,
            primary_key="approved_at",
            fallback_keys=("updated_at",),
            fallback_source="updated_at_fallback",
        )
        items.append(
            {
                "schema_version": "memory-os.review_item.v0",
                "review_item_id": f"review:proposal_apply:{proposal_id}",
                "target_type": "proposal_apply",
                "target_id": proposal_id,
                "source_module": "proposal_followups",
                "priority": "action_required",
                "created_at": created_at,
                "created_at_source": created_at_source,
                "status": "awaiting_explicit_apply",
                "summary": title,
                "proposal_detail": _bounded_text(detail, 620),
                "safe_source_ids": _safe_list(followup.get("safe_source_ids")),
                "ops_gate_report_id": str(followup.get("ops_gate_report_id") or ""),
                "proposal_kind": proposal_kind,
                "raw_body_included": False,
            }
        )
    return items


def _session_mirror_apply_review_items(store: MemoryOSStore, closed: set[str]) -> list[dict[str, Any]]:
    from .session_mirror import (
        SESSION_MIRROR_BOUNDARY_CONTRACT_VERSION,
        SessionMirror,
        session_mirror_stable_scope_id,
    )

    try:
        report = SessionMirror(store).scan(dry_run=True, max_sessions=1)
    except Exception:
        return []
    selected = report.get("selected_sessions") if isinstance(report.get("selected_sessions"), list) else []
    if not selected:
        return []
    first = selected[0] if isinstance(selected[0], dict) else {}
    fingerprint = str(first.get("fingerprint") or "")
    if not fingerprint:
        return []
    platform = str(first.get("platform") or "").lower().replace("-", "_")
    digest_item_id = f"session_mirror_apply:{fingerprint}"
    stable_scope_id = session_mirror_stable_scope_id(
        digest_item_id=digest_item_id,
        selected_pending_session_fingerprint=fingerprint,
        max_sessions=1,
        platform_allowlist=[platform] if platform else [],
    )
    target_id = f"production_bounded:{stable_scope_id}"
    if f"session_mirror_apply:{target_id}" in closed:
        return []
    approval = {
        "approval_scope": "session_mirror_production_bounded_apply",
        "stable_scope_id": stable_scope_id,
        "digest_item_id": digest_item_id,
        "selected_pending_session_fingerprint": fingerprint,
        "boundary_contract_version": SESSION_MIRROR_BOUNDARY_CONTRACT_VERSION,
        "max_sessions": 1,
        "platform_allowlist": [platform] if platform else [],
        "auto_apply_after_graduation": True,
        "auto_apply_max_sessions_per_run": 1,
        "expires_at": "",
        "actual_send": False,
        "actual_execute": False,
        "actual_identity_write": False,
        "actual_unapproved_crystallized_approval": False,
    }
    created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return [
        {
            "schema_version": "memory-os.review_item.v0",
            "review_item_id": f"review:session_mirror_apply:{stable_scope_id}",
            "target_type": "session_mirror_apply",
            "target_id": target_id,
            "source_module": "session_mirror",
            "priority": "action_required",
            "created_at": created_at,
            "created_at_source": "scan_pending",
            "status": "pending_lane_graduation",
            "summary": _bounded_text(
                f"SessionMirror bounded production lane approval: platform={platform or 'unknown'}; "
                f"fingerprint={fingerprint}; max_sessions=1",
                180,
            ),
            "safe_source_ids": [f"session_mirror:{fingerprint}"],
            "session_mirror_approval": approval,
            "selected_sessions": [first],
            "raw_body_included": False,
        }
    ]


def _speak_review_items(store: MemoryOSStore, closed: set[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for module_name in ("wandering_mind", "speak_gate"):
        path = store.roots.hermes_home / "system-modules" / module_name / "would_send.jsonl"
        for record in _read_jsonl(path):
            target_id = str(record.get("id") or record.get("payload_ref") or "")
            if not target_id or f"speak:{target_id}" in closed:
                continue
            payload_ref = str(record.get("payload_ref") or "")
            expression_preview, expression_preview_suppressed = _safe_expression_preview_for_payload_ref(store, payload_ref)
            created_at, created_at_source = _created_at_with_source(
                record,
                primary_key="created_at",
                fallback_keys=("ts",),
                fallback_source="legacy_ts",
            )
            items.append(
                {
                    "schema_version": "memory-os.review_item.v0",
                    "review_item_id": f"review:speak:{target_id}",
                    "target_type": "speak",
                    "target_id": target_id,
                    "source_module": module_name,
                    "priority": "review_suggested",
                    "created_at": created_at,
                    "created_at_source": created_at_source,
                    "status": "pending",
                    "summary": "右脑 would-send 主动发言草案",
                    "payload_ref": payload_ref,
                    "expression_preview": expression_preview,
                    "expression_preview_suppressed": expression_preview_suppressed,
                    "safe_source_ids": [],
                    "raw_body_included": False,
                }
            )
    return items


def _left_brain_advisor_review_items(store: MemoryOSStore, closed: set[str]) -> list[dict[str, Any]]:
    from .left_brain_advisor import read_left_brain_advisor_reports

    reports = read_left_brain_advisor_reports(store.roots, limit=1)
    if not reports:
        return []
    latest = reports[-1]
    findings = latest.get("findings") if isinstance(latest.get("findings"), list) else []
    items: list[dict[str, Any]] = []
    per_source_visible_count: Counter[str] = Counter()
    per_source_overflow_count: Counter[str] = Counter()
    for finding in findings:
        if not isinstance(finding, dict) or not bool(finding.get("owner_visible")):
            continue
        target_id = str(finding.get("finding_id") or finding.get("target_id") or "")
        target_type = str(finding.get("target_type") or "left_brain_advisor_finding")
        if target_type not in {"left_brain_advisor_finding", "hindsight_curation"}:
            target_type = "left_brain_advisor_finding"
        source_key = str(finding.get("source_key") or "unknown")
        priority = str(finding.get("priority") or "review_suggested")
        if (
            priority in {"review_suggested", "fyi"}
            and per_source_visible_count[source_key] >= LEFT_BRAIN_REVIEW_SUGGESTED_PER_SOURCE_CAP
        ):
            per_source_overflow_count[source_key] += 1
            continue
        per_source_visible_count[source_key] += 1
        if not target_id or f"{target_type}:{target_id}" in closed:
            continue
        items.append(
            {
                "schema_version": "memory-os.review_item.v0",
                "review_item_id": f"review:{target_type}:{target_id}",
                "target_type": target_type,
                "target_id": target_id,
                "source_module": "left_brain_advisor",
                "priority": priority,
                "created_at": str(latest.get("created_at") or ""),
                "created_at_source": "left_brain_advisor_report",
                "status": "report_only",
                "summary": _bounded_text(str(finding.get("summary") or finding.get("title") or ""), 220),
                "reason": _bounded_text(str(finding.get("reason") or ""), 240),
                "safe_source_ids": _safe_list(finding.get("safe_source_ids")),
                "actions_suppressed": bool(finding.get("actions_suppressed")),
                "allowed_action_type": str(finding.get("allowed_action_type") or "review_only"),
                "raw_body_included": False,
            }
        )
    for source_key, overflow_count in sorted(per_source_overflow_count.items()):
        summary_id = "lba_owner_burden_" + _stable_token(
            f"{latest.get('report_id') or latest.get('created_at')}:{source_key}:{overflow_count}",
            16,
        )
        if f"left_brain_advisor_finding:{summary_id}" in closed:
            continue
        items.append(
            {
                "schema_version": "memory-os.review_item.v0",
                "review_item_id": f"review:left_brain_advisor_finding:{summary_id}",
                "target_type": "left_brain_advisor_finding",
                "target_id": summary_id,
                "source_module": "left_brain_advisor",
                "priority": "fyi",
                "created_at": str(latest.get("created_at") or ""),
                "created_at_source": "left_brain_advisor_report",
                "status": "report_only",
                "summary": _bounded_text(
                    f"{source_key} 还有 {overflow_count} 条相似左脑诊断已聚合，避免 owner digest 噪音。",
                    220,
                ),
                "reason": "Owner-burden cap aggregated repeated LeftBrainAdvisor findings; full evidence remains in the advisor report.",
                "safe_source_ids": [],
                "actions_suppressed": True,
                "allowed_action_type": "review_only",
                "raw_body_included": False,
                "owner_burden_aggregate": True,
                "aggregated_source_key": source_key,
                "aggregated_count": overflow_count,
            }
        )
    return items


def _provisional_crystallized_review_items(store: MemoryOSStore, closed: set[str]) -> list[dict[str, Any]]:
    """Generate review items for active provisional crystallized records.

    Each provisional record appears in the owner digest with:
    - Countdown (remaining days until auto-expiry)
    - Confirm/reject action tokens
    - Recurrence escalation: records whose content hash appears >=3 times
      are bumped to "action_required" priority regardless of expiry.
    """
    service = CrystallizedMemoryService(store)
    records = service.list_provisional_records()
    if not records:
        return []

    now = datetime.now(timezone.utc)

    # ── Recurrence detection (body content hash) ──
    hash_counter: Counter[str] = Counter()
    for r in records:
        body = str(r.get("body") or "").strip()
        if body:
            content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
            hash_counter[content_hash] += 1

    recurrence_by_id: dict[str, int] = {}
    for r in records:
        body = str(r.get("body") or "").strip()
        if body:
            content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
            recurrence_by_id[r["id"]] = hash_counter[content_hash]

    items: list[dict[str, Any]] = []
    for r in records:
        record_id = str(r.get("id") or "")
        target_ref = f"provisional_crystallized_record:{record_id}"
        if target_ref in closed:
            continue
        if not record_id:
            continue

        # Compute remaining days
        expires_str = str(r.get("expires_at") or "").strip()
        remaining_days = 999
        if expires_str:
            try:
                expires_at = datetime.fromisoformat(expires_str)
                remaining_seconds = (expires_at - now).total_seconds()
                remaining_days = max(0, int(remaining_seconds / 86400))
            except (ValueError, TypeError):
                pass

        # Recurrence count
        recurrence_count = recurrence_by_id.get(record_id, 1)

        # Priority
        if recurrence_count >= 3 or remaining_days <= 3:
            priority = "action_required"
        elif remaining_days <= 5:
            priority = "review_suggested"
        else:
            priority = "fyi"

        # Summary — suppress body text when it looks like raw transcript
        raw_body = str(r.get("body") or "").strip()
        if _contains_transcript_marker(raw_body):
            body_text = "(摘要隐藏：内容包含原始对话片段)"
        else:
            body_text = _bounded_text(raw_body, 180)
        summary_parts = [f"(剩{remaining_days}d) {body_text}"]
        if recurrence_count >= 3:
            summary_parts.insert(0, f"⚠high-recurrence({recurrence_count}x): ")
        summary = "".join(summary_parts)

        # Action tokens
        actions = _review_actions("provisional_crystallized_record", record_id)

        created_at = str(r.get("approved_at") or r.get("created_at") or now.isoformat().replace("+00:00", "Z"))

        items.append({
            "schema_version": "memory-os.review_item.v0",
            "review_item_id": f"review:{target_ref}",
            "target_type": "provisional_crystallized_record",
            "target_id": record_id,
            "source_module": "crystallized_memory",
            "priority": priority,
            "created_at": created_at,
            "created_at_source": "provisional_record_approved_at",
            "status": "pending",
            "summary": _bounded_text(summary, 260),
            "provisional_body": body_text,
            "expires_at": expires_str,
            "remaining_days": remaining_days,
            "recurrence_count": recurrence_count,
            "canonical_state": str(r.get("canonical_state") or "active"),
            "safe_source_ids": [],
            "action_tokens": {action["action_type"]: action["token"] for action in actions},
            "action_targets": {
                action["action_type"]: {"target_type": action["target_type"], "target_id": action["target_id"]}
                for action in actions
            },
            "raw_body_included": False,
        })

    return items


def _provisional_knob_override_review_items(store: MemoryOSStore, closed: set[str]) -> list[dict[str, Any]]:
    """Generate owner-review items for active provisional knob overrides."""
    from plugins.memory.memory_os.knob_overrides import list_active_overrides, OVERRIDABLE_KNOBS

    active = list_active_overrides(roots=store.roots)
    items: list[dict[str, Any]] = []
    for override in active:
        if override.get("state") != "active":
            continue
        knob_name = str(override.get("knob") or "")
        target_id = f"knob_override:{override.get('id', '')}"
        target_ref = target_id
        if target_ref in closed:
            continue

        spec = OVERRIDABLE_KNOBS.get(knob_name, {})
        prior = override.get("prior_value", spec.get("default"))
        current = override.get("override_value", prior)
        expires_str = str(override.get("expires_at") or "")
        days_left = ""
        if expires_str:
            try:
                expires_dt = datetime.fromisoformat(expires_str)
                remaining = expires_dt - datetime.now(timezone.utc)
                days_left = f"{max(0, remaining.days)}d"
            except ValueError:
                pass

        summary = (
            f"自演化旋钮调整: {knob_name} {prior}→{current} · "
            f"还剩 {days_left or '?'} · [确认/回退]"
        )

        actions = _review_actions("knob_override", override.get("id", ""))
        items.append({
            "schema_version": "memory-os.review_item.v0",
            "review_item_id": f"review:{target_ref}",
            "target_type": "knob_override",
            "target_id": override.get("id", ""),
            "source_module": "override_sweep",
            "priority": "action_required",
            "created_at": override.get("ts", ""),
            "created_at_source": "override_ts",
            "status": "pending",
            "summary": _bounded_text(summary, 220),
            "proposed_memory_text": "",
            "candidate_kind": "knob_tune",
            "knob_name": knob_name,
            "override_value": current,
            "prior_value": prior,
            "bounds": override.get("bounds"),
            "approved_via": str(override.get("approved_via") or ""),
            "expires_at": expires_str,
            "action_tokens": {action["action_type"]: action["token"] for action in actions},
            "action_targets": {
                action["action_type"]: {"target_type": action["target_type"], "target_id": action["target_id"]}
                for action in actions
            },
            "raw_body_included": False,
        })
    return items


def _created_at_with_source(
    record: dict[str, Any],
    *,
    primary_key: str,
    fallback_keys: tuple[str, ...],
    fallback_source: str,
) -> tuple[str, str]:
    primary = str(record.get(primary_key) or "")
    if primary:
        return primary, "producer"
    for key in fallback_keys:
        value = str(record.get(key) or "")
        if value:
            return value, fallback_source
    return "", "missing"


def _memory_source_fyi_items(store: MemoryOSStore, *, limit: int, start: int = 1) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    records = read_memory_source_records(store.roots, limit=50)
    selected: list[dict[str, Any]] = []
    for record in reversed(records):
        record_id = str(record.get("record_id") or "")
        if not record_id:
            continue
        anchor = f"F{start + len(selected)}"
        selected.append(
            {
                "anchor": anchor,
                "target_type": "memory_source",
                "target_id": record_id,
                "source_module": "memory_sources",
                "priority": "fyi",
                "kind": "memory_sources_feedback",
                "summary": _bounded_text(
                    f"Context route={record.get('route') or 'unknown'}; "
                    f"query_class={record.get('query_class') or 'unknown'}",
                    180,
                ),
                "route": str(record.get("route") or "unknown"),
                "query_class": str(record.get("query_class") or "unknown"),
                "source_classes": _safe_list(record.get("source_classes")),
                "safe_source_ids": _safe_list(record.get("safe_source_ids")),
                "raw_body_included": False,
            }
        )
        if len(selected) >= limit:
            break
    return selected


def _expression_text_for_payload_ref(store: MemoryOSStore, payload_ref: str) -> str:
    prefix = "local://wandering_mind/"
    if not payload_ref.startswith(prefix):
        return ""
    output_id = payload_ref.removeprefix(prefix).strip("/")
    if not output_id or output_id == "silent":
        return ""
    for record in _read_jsonl(store.roots.hermes_home / "system-modules" / "wandering_mind" / "outputs.jsonl"):
        if str(record.get("id") or "") == output_id:
            return str(record.get("output") or "")
    return ""


def _safe_expression_preview_for_payload_ref(store: MemoryOSStore, payload_ref: str) -> tuple[str, bool]:
    text = _expression_text_for_payload_ref(store, payload_ref)
    if not text:
        return "", False
    if _contains_transcript_marker(text):
        return (
            "这条右脑表达草案包含原始对话样式片段，摘要已隐藏；请给表达反馈或要求重新生成，不建议直接允许发送。",
            True,
        )
    return _bounded_text(text, 360), False


def _find_speak_would_send(store: MemoryOSStore, target_id: str) -> dict[str, Any] | None:
    clean = str(target_id or "")
    if not clean:
        return None
    for module_name in ("wandering_mind", "speak_gate"):
        path = store.roots.hermes_home / "system-modules" / module_name / "would_send.jsonl"
        for record in _read_jsonl(path):
            if str(record.get("id") or record.get("payload_ref") or "") == clean:
                item = dict(record)
                item["source_module"] = module_name
                return item
    return None


def _right_brain_speak_once_config(store: MemoryOSStore) -> dict[str, Any]:
    config = load_config(store.roots.hermes_home).get("right_brain_expression", {})
    return dict(config) if isinstance(config, dict) else {}


def _proposal_requires_maturation(proposal: dict[str, Any]) -> bool:
    title = str(proposal.get("title") or "").strip().lower()
    body = str(proposal.get("body") or "").strip().lower()
    generic_titles = {
        "self-evolution dry-run proposal",
    }
    generic_bodies = {
        "use the highest evidence signal to prepare a reviewed governance improvement.",
        "use the highest feature-maturity evidence signal to prepare a reviewed governance improvement.",
    }
    if title in generic_titles and body in generic_bodies:
        return True
    if title in generic_titles and len(_safe_list(proposal.get("source_refs"))) > 0 and "specific" not in body:
        return True
    return False


def _proposal_detail(proposal: dict[str, Any], *, requires_maturation: bool) -> str:
    if requires_maturation:
        refs = _safe_list(proposal.get("source_refs"))
        suffix = f" 当前只有 {len(refs)} 个 score 引用。" if refs else ""
        return _bounded_text(
            "该项仍是 SelfEvolution 模板提案，缺少具体要调整什么、为什么调整、如何验证。"
            f"{suffix} 它不会进入今日审批，需先生成具体方案。",
            420,
        )
    body = str(proposal.get("body") or "").strip()
    if not body or _looks_like_raw_proposal_body(body):
        return ""
    return _bounded_text(body, 420)


def _looks_like_raw_proposal_body(body: str) -> bool:
    lowered = body.lower()
    raw_markers = (
        "raw ",
        "raw_",
        "private raw",
        "transcript:",
    )
    return any(marker in lowered for marker in raw_markers) or _contains_transcript_marker(body)


def _contains_transcript_marker(value: str) -> bool:
    lowered = str(value or "").lower()
    transcript_markers = (
        "user:",
        "assistant:",
        "用户:",
        "用户：",
        "助手:",
        "助手：",
        "菸草:",
        "菸草：",
        "agentcoco:",
        "agentcoco：",
        "| assistant:",
        "| user:",
    )
    return any(marker in lowered for marker in transcript_markers)


def _channel_report(
    *,
    status: str,
    reason: str,
    profile: str,
    owner_id: str,
    channel: str,
    target_ref: str,
    direct_message: bool,
    configured_by_owner: bool,
    fallback_used: bool,
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": OWNER_REVIEW_CHANNEL_SCHEMA_VERSION,
        "status": status,
        "reason": reason,
        "profile": profile,
        "owner_id": owner_id,
        "channel": _safe_channel(channel),
        "target_ref": _safe_target_ref(target_ref),
        "direct_message": bool(direct_message),
        "last_owner_activity_at": candidates[0].get("last_owner_activity_at") if candidates else "",
        "configured_by_owner": bool(configured_by_owner),
        "fallback_used": bool(fallback_used),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "raw_body_included": False,
    }


def _configured_channel_candidate(config: dict[str, Any], *, owner_id: str) -> dict[str, Any] | None:
    channel = _safe_channel(str(config.get("channel") or ""))
    target_ref = _safe_target_ref(str(config.get("target_ref") or ""))
    if not channel or channel == "unknown" or not target_ref:
        return None
    return {
        "channel": channel,
        "target_ref": target_ref,
        "direct_message": bool(config.get("direct_message")),
        "last_owner_activity_at": "",
        "configured_by_owner": True,
        "owner_id": owner_id,
        "source": "config",
    }


def _channel_candidate_is_safe(candidate: dict[str, Any], *, allow_group: bool) -> bool:
    if not candidate.get("target_ref"):
        return False
    if candidate.get("direct_message") is True:
        return True
    return bool(allow_group)


def _session_channel_candidates(store: MemoryOSStore, *, owner_id: str, limit: int) -> list[dict[str, Any]]:
    candidates = _state_db_channel_candidates(store, owner_id=owner_id)
    return sorted(candidates, key=lambda item: str(item.get("last_owner_activity_at") or ""), reverse=True)[:limit]


def _state_db_channel_candidates(store: MemoryOSStore, *, owner_id: str) -> list[dict[str, Any]]:
    path = store.roots.hermes_home / "state.db"
    if not path.exists():
        return []
    try:
        uri = f"file:{path.as_posix()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as conn:
            conn.row_factory = sqlite3.Row
            if not _table_exists(conn, "sessions"):
                return []
            columns = _table_columns(conn, "sessions")
            id_col = _first_existing(columns, ("id", "session_id", "uuid"))
            if not id_col:
                return []
            platform_col = _first_existing(columns, ("source", "platform", "channel", "kind"))
            updated_col = _first_existing(columns, ("updated_at", "last_updated", "created_at"))
            target_col = _first_existing(
                columns,
                ("target_ref", "target", "chat_id", "conversation_id", "channel_id", "thread_id", "room_id"),
            )
            owner_col = _first_existing(columns, ("owner_id", "user_id", "account_id", "principal_id"))
            direct_col = _first_existing(columns, ("direct_message", "is_direct", "is_dm", "dm", "is_group", "group"))
            rows = conn.execute(f"select * from sessions order by {updated_col or id_col} desc limit 20").fetchall()
    except Exception:
        return []
    candidates: list[dict[str, Any]] = []
    for row in rows:
        platform = str(row[platform_col]) if platform_col else "unknown"
        target_ref = _target_ref(platform, str(row[target_col]) if target_col else str(row[id_col]))
        direct_message = _direct_flag(row[direct_col], direct_col) if direct_col else False
        row_owner = str(row[owner_col]) if owner_col else ""
        if row_owner and row_owner != owner_id:
            continue
        candidates.append(
            {
                "source": "state_db.sessions",
                "channel": _safe_channel(platform),
                "target_ref": _safe_target_ref(target_ref),
                "direct_message": direct_message,
                "last_owner_activity_at": str(row[updated_col]) if updated_col else "",
                "configured_by_owner": False,
                "owner_id": owner_id,
                "raw_body_included": False,
            }
        )
    return candidates


def _digest_items(items: list[dict[str, Any]], priority: str, limit: int) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    selected: list[dict[str, Any]] = []
    for item in items:
        if item.get("priority") != priority:
            continue
        selected.append(_digest_item(item))
        if len(selected) >= limit:
            break
    return selected


def _suppress_stale_informational_digest_items(
    items: list[dict[str, Any]],
    *,
    review_aging: dict[str, Any],
) -> tuple[list[dict[str, Any]], int]:
    retention_days = int(review_aging.get("informational_retention_days") or 0)
    if retention_days <= 0:
        return items, 0
    visible: list[dict[str, Any]] = []
    suppressed = 0
    for item in items:
        priority = str(item.get("source_priority") or item.get("priority") or "")
        age_days = item.get("age_days")
        if priority in {"review_suggested", "fyi"} and isinstance(age_days, int) and age_days > retention_days:
            suppressed += 1
            continue
        visible.append(item)
    return visible, suppressed


def _digest_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "anchor": item.get("anchor"),
        "review_item_id": item.get("review_item_id"),
        "target_type": item.get("target_type"),
        "target_id": item.get("target_id"),
        "source_module": item.get("source_module"),
        "priority": item.get("priority"),
        "source_priority": item.get("source_priority"),
        "effective_priority": item.get("effective_priority"),
        "aging_reason": item.get("aging_reason"),
        "age_days": item.get("age_days"),
        "summary": _bounded_text(str(item.get("summary") or ""), 180),
        "proposed_memory_text": _bounded_text(str(item.get("proposed_memory_text") or ""), 360),
        "proposal_detail": _bounded_text(str(item.get("proposal_detail") or ""), 620),
        "proposal_kind": _bounded_text(str(item.get("proposal_kind") or ""), 120),
        "ops_gate_report_id": _bounded_text(str(item.get("ops_gate_report_id") or ""), 120),
        "requires_maturation": bool(item.get("requires_maturation")),
        "expression_preview": _bounded_text(str(item.get("expression_preview") or ""), 360),
        "expression_preview_suppressed": bool(item.get("expression_preview_suppressed")),
        "payload_ref": _bounded_text(str(item.get("payload_ref") or ""), 220),
        "session_mirror_approval": _bounded_session_mirror_approval(
            item.get("session_mirror_approval") if isinstance(item.get("session_mirror_approval"), dict) else {}
        ),
        "safe_source_ids": item.get("safe_source_ids") or [],
        "raw_body_included": False,
    }


def _bounded_session_mirror_approval(value: dict[str, Any]) -> dict[str, Any]:
    if not value:
        return {}
    platform_allowlist = value.get("platform_allowlist") if isinstance(value.get("platform_allowlist"), list) else []
    return {
        "approval_scope": _bounded_text(str(value.get("approval_scope") or ""), 80),
        "stable_scope_id": _bounded_text(str(value.get("stable_scope_id") or ""), 80),
        "digest_item_id": _bounded_text(str(value.get("digest_item_id") or ""), 120),
        "selected_pending_session_fingerprint": _bounded_text(
            str(value.get("selected_pending_session_fingerprint") or ""),
            120,
        ),
        "boundary_contract_version": _bounded_text(str(value.get("boundary_contract_version") or ""), 80),
        "max_sessions": max(int(value.get("max_sessions") or 0), 0),
        "platform_allowlist": [str(item)[:80] for item in platform_allowlist[:10]],
        "auto_apply_after_graduation": bool(value.get("auto_apply_after_graduation")),
        "auto_apply_max_sessions_per_run": max(int(value.get("auto_apply_max_sessions_per_run") or 0), 0),
        "expires_at": _bounded_text(str(value.get("expires_at") or ""), 80),
        "actual_send": bool(value.get("actual_send")),
        "actual_execute": bool(value.get("actual_execute")),
        "actual_identity_write": bool(value.get("actual_identity_write")),
        "actual_unapproved_crystallized_approval": bool(value.get("actual_unapproved_crystallized_approval")),
    }


def _fyi_items(status: dict[str, Any], *, limit: int, start: int = 1) -> list[dict[str, Any]]:
    queue = status.get("review_queue") if isinstance(status.get("review_queue"), dict) else {}
    actions = status.get("owner_actions") if isinstance(status.get("owner_actions"), dict) else {}
    fyi = [
        {
            "anchor": f"F{start}",
            "kind": "review_queue",
            "target_type": "digest_status",
            "target_id": "review_queue",
            "source_module": "owner_review",
            "summary": (
                f"pending={queue.get('pending_count')}; "
                f"action_required={queue.get('action_required_count')}; "
                f"review_suggested={queue.get('review_suggested_count')}"
            ),
            "raw_body_included": False,
        },
        {
            "anchor": f"F{start + 1}",
            "kind": "owner_actions",
            "target_type": "digest_status",
            "target_id": "owner_actions",
            "source_module": "owner_review",
            "summary": (
                f"owner_actions={actions.get('count')}; "
                f"duplicates={actions.get('duplicate_action_ignored_count')}; "
                f"errors={actions.get('error_count')}"
            ),
            "raw_body_included": False,
        },
    ]
    return fyi[:limit]


def _render_review_item(item: dict[str, Any], *, section: str) -> dict[str, Any]:
    target_type = str(item.get("target_type") or item.get("kind") or "digest_status")
    source_module = str(item.get("source_module") or "owner_review")
    anchor = str(item.get("anchor") or "")
    target_id = str(item.get("target_id") or item.get("kind") or "")
    actions = [] if _review_item_suppresses_actions(item) else _review_actions(target_type, target_id)
    if target_type == "speak" and bool(item.get("expression_preview_suppressed")):
        actions = [action for action in actions if action.get("action_type") != "allow_speak_once"]
    question = _review_question(target_type, item)
    suggested_action = _review_suggested_action(actions, target_type)
    consequence = _review_consequence(target_type)
    if target_type == "speak" and bool(item.get("expression_preview_suppressed")):
        consequence = "这条表达草案像原始对话片段，摘要不展示原文，也不提供 allow；表达反馈只入 ledger 并参与后续 proposal。"
    return {
        "anchor": anchor,
        "review_item_id": str(item.get("review_item_id") or ""),
        "target_type": target_type,
        "target_id": target_id,
        "source_module": source_module,
        "section": section,
        "question": question,
        "suggested_action": suggested_action,
        "reason": _review_reason(target_type, item),
        "consequence": consequence,
        "proposed_memory_text": _bounded_text(str(item.get("proposed_memory_text") or ""), 360)
        if target_type == "candidate"
        else "",
        "proposal_detail": _bounded_text(str(item.get("proposal_detail") or ""), 620)
        if target_type in {"proposal", "proposal_apply"}
        else "",
        "requires_maturation": bool(item.get("requires_maturation")),
        "expression_preview": _bounded_text(str(item.get("expression_preview") or ""), 360)
        if target_type == "speak"
        else "",
        "expression_preview_suppressed": bool(item.get("expression_preview_suppressed"))
        if target_type == "speak"
        else False,
        "session_mirror_approval": _bounded_session_mirror_approval(
            item.get("session_mirror_approval") if isinstance(item.get("session_mirror_approval"), dict) else {}
        )
        if target_type == "session_mirror_apply"
        else {},
        "action_tokens": {action["action_type"]: action["token"] for action in actions},
        "action_targets": {
            action["action_type"]: {
                "target_type": action["target_type"],
                "target_id": action["target_id"],
            }
            for action in actions
        },
        "owner_utterance_scope": "owner_chat_utterance",
        "owner_utterance_examples": [action["owner_utterance_example"] for action in actions],
        "agent_tool_calls": [
            action["agent_tool_call"]
            for action in actions
            if isinstance(action.get("agent_tool_call"), dict) and action["agent_tool_call"]
        ],
        "safe_source_ids": item.get("safe_source_ids") or [],
        "raw_body_included": False,
    }


def _review_question(target_type: str, item: dict[str, Any]) -> str:
    if target_type == "candidate":
        proposed = _bounded_text(str(item.get("proposed_memory_text") or item.get("summary") or ""), 160)
        if proposed:
            return f"这条候选记忆要批准为长期记忆吗？{proposed}"
        return "这条候选记忆要批准为长期记忆吗？"
    if target_type == "candidate_cluster":
        scope = item.get("cluster_scope") if isinstance(item.get("cluster_scope"), dict) else {}
        member_ids = scope.get("member_candidate_ids") if isinstance(scope, dict) else []
        count = len(member_ids or item.get("member_candidate_ids") or [])
        return f"这个近重复候选簇要一次性 approve/reject/defer 吗？共 {count} 条候选。"
    if target_type == "candidate_cleanup":
        return "这条候选记忆还像原始对话片段，批准前需要先整理。"
    if target_type == "proposal":
        summary = _safe_review_summary(item.get("summary"), fallback="这个 proposal")
        if item.get("requires_maturation"):
            return _bounded_text(f"这个 proposal 还不能审批，需要先变成具体方案：{summary}", 180)
        return _bounded_text(f"这个 proposal 要进入人工后续处理吗？{summary}", 180)
    if target_type == "proposal_apply":
        summary = _safe_review_summary(item.get("summary"), fallback="这个已批准 proposal")
        return _bounded_text(f"要把这个已批准 proposal 显式应用到运行时策略/投影吗？{summary}", 180)
    if target_type == "crystallized_record":
        return "要撤销或降级这条 crystallized memory 吗？处理后本地 canonical recall 不再返回它。"
    if target_type == "memory_source":
        return "这次注入的记忆/上下文对回答有帮助吗？"
    if target_type == "speak":
        return "这条右脑表达草案要允许一次，还是给表达质量反馈？"
    if target_type == "session_mirror_apply":
        return "要批准 SessionMirror 这个 bounded 生产导入 lane 毕业并执行一次真实 smoke 吗？"
    if target_type == "left_brain_advisor_finding":
        summary = _safe_review_summary(item.get("summary"), fallback="左脑信号诊断")
        return _bounded_text(f"左脑发现一个需要关注的治理信号：{summary}", 180)
    if target_type == "hindsight_curation":
        summary = _safe_review_summary(item.get("summary"), fallback="Hindsight 治理建议")
        return _bounded_text(f"要记录这条 Hindsight 治理决策吗？{summary}", 180)
    return "请看一下这条 Memory-OS 状态信号。"


def _review_suggested_action(actions: list[dict[str, str]], target_type: str) -> str:
    examples = [action["owner_utterance_example"] for action in actions]
    if target_type in {"candidate", "proposal"} and len(examples) >= 2:
        return f"{examples[0]} or {examples[1]}"
    if target_type == "candidate_cluster" and examples:
        return " or ".join(examples[:3])
    if target_type == "proposal_apply" and examples:
        return examples[0]
    if target_type == "proposal" and not examples:
        return "不进入今日审批；等待 SelfEvolution 生成具体方案后再进入 owner decision"
    if target_type == "crystallized_record" and examples:
        return " or ".join(examples[:2])
    if target_type == "memory_source" and examples:
        return examples[0]
    if target_type == "speak" and examples:
        return f"{examples[0]}；如果内容不合适，让 Hermes 记录具体表达反馈"
    if target_type == "session_mirror_apply" and examples:
        return examples[0]
    if target_type == "hindsight_curation" and examples:
        return " or ".join(examples[:3])
    if target_type == "candidate_cleanup":
        return "这次摘要里不需要操作；等待后续整理或 review queue 清理"
    return "不需要操作"


def _review_reason(target_type: str, item: dict[str, Any]) -> str:
    source_module = str(item.get("source_module") or "owner_review")
    if target_type == "candidate":
        source_count = len(item.get("safe_source_ids") or [])
        aging = str(item.get("aging_reason") or "pending_owner_review")
        return _bounded_text(
            f"{source_module} 从 {source_count} 个安全引用里提出了稳定记忆候选；队列原因：{aging}。",
            220,
        )
    if target_type == "candidate_cluster":
        scope = item.get("cluster_scope") if isinstance(item.get("cluster_scope"), dict) else {}
        mixed = bool(scope.get("mixed_sensitivity")) if isinstance(scope, dict) else False
        sensitivity_note = "；mixed sensitivity，必须 fail-closed 或拆簇" if mixed else ""
        return _bounded_text(
            f"{source_module} 聚合了近重复候选，token 绑定 cluster_id、member ids、source ids 和 sensitivity scope{sensitivity_note}。",
            220,
        )
    if target_type == "candidate_cleanup":
        source_count = len(item.get("safe_source_ids") or [])
        return _bounded_text(
            f"{source_module} 从 {source_count} 个安全引用里提出了候选，但它仍像原始对话/事件摘录，不像稳定记忆。",
            220,
        )
    if target_type == "proposal":
        summary = _safe_review_summary(item.get("summary"), fallback="proposal candidate")
        if item.get("requires_maturation"):
            return _bounded_text(
                f"{source_module} 排入的 proposal 仍是模板/泛化建议，缺少具体动作、依据和验收口径：{summary}。",
                220,
            )
        return _bounded_text(f"{source_module} 排入了这个 proposal：{summary}。", 220)
    if target_type == "proposal_apply":
        report_id = str(item.get("ops_gate_report_id") or "")
        return _bounded_text(
            f"{source_module} 已完成 OpsGate report-only review；report={report_id or 'unknown'}，decision=would_allow。",
            220,
        )
    if target_type == "crystallized_record":
        return _bounded_text(
            f"{source_module} 提供了 owner 显式撤销/降级入口；record={item.get('target_id') or 'unknown'}。",
            220,
        )
    if target_type == "memory_source":
        route = str(item.get("route") or "unknown")
        query_class = str(item.get("query_class") or "unknown")
        return _bounded_text(
            f"{source_module} 记录了上下文归因：route={route} / query={query_class}。",
            220,
        )
    if target_type == "speak":
        if item.get("expression_preview_suppressed"):
            return _bounded_text(
                f"{source_module} 产生了一条 would-send 草案，但它像原始对话片段，摘要已隐藏原文。",
                220,
            )
        if item.get("expression_preview"):
            return _bounded_text(f"{source_module} 产生了一条可审阅的 would-send 主动发言草案。", 220)
        return _bounded_text(f"{source_module} 产生了一条 would-send 主动发言草案，但当前只能看到安全引用。", 220)
    if target_type == "session_mirror_apply":
        approval = item.get("session_mirror_approval") if isinstance(item.get("session_mirror_approval"), dict) else {}
        return _bounded_text(
            "SessionMirror 检测到一个可安全导入的 pending 会话。"
            f"fingerprint={approval.get('selected_pending_session_fingerprint') or 'unknown'}; "
            f"max_sessions={approval.get('max_sessions') or 1}。",
            220,
        )
    if target_type == "left_brain_advisor_finding":
        return _bounded_text(
            str(item.get("reason") or "LeftBrainAdvisor 只做 report-only 诊断，不执行任何动作。"),
            220,
        )
    if target_type == "hindsight_curation":
        return _bounded_text(
            str(item.get("reason") or "LeftBrainAdvisor 提出 Hindsight curation 建议；Memory-OS 只记录 owner 决策，不写/删 Hindsight。"),
            220,
        )
    return _bounded_text(_safe_review_summary(item.get("summary"), fallback="只是状态趋势。"), 220)


def _safe_review_summary(value: Any, *, fallback: str) -> str:
    summary = str(value or "").strip()
    if not summary or _looks_like_raw_proposal_body(summary):
        return fallback
    return summary


def _review_consequence(target_type: str) -> str:
    if target_type == "candidate":
        return "批准会写入一条 owner-approved crystallized memory；拒绝会保留审计证据并关闭该项。"
    if target_type == "candidate_cluster":
        return "批准会逐个成员写 owner-approved canonical crystallized memory；reject/defer 只写 owner action ledger；scope 变化或 mixed sensitivity 会 fail-closed。"
    if target_type == "candidate_cleanup":
        return "不会写入长期记忆；该项会留在 review backlog，直到整理或显式清理处理。"
    if target_type == "proposal":
        return "批准只表示允许进入人工 follow-up；不会执行任何工作。拒绝会降权/关闭该 proposal。"
    if target_type == "proposal_apply":
        return "应用只写入这个 bounded policy/projection 目标；不会创建 generic executor、execution ticket 或外部执行。"
    if target_type == "crystallized_record":
        return "撤销或降级会让本地 crystallized 记录退出 active canonical，并记录 Hindsight 投影 invalidate；不会删除审计证据。"
    if target_type == "memory_source":
        return "反馈先作为证据入 ledger；不会直接改变 live routing，除非之后经过单独 apply gate。"
    if target_type == "speak":
        return "允许会创建一个会过期的一次性许可；表达反馈只入 ledger 并参与后续 proposal，不会直接改策略。"
    if target_type == "session_mirror_apply":
        return (
            "批准会授权一个 bounded SessionMirror 生产导入 scope 并允许一次真实 smoke；"
            "不写长期记忆、不发送消息、不执行工具、不改 identity/route/score。"
        )
    if target_type == "left_brain_advisor_finding":
        return "仅进入 owner digest 可见面；不会创建审批 token、不会 apply、不会改策略或长期记忆。"
    if target_type == "hindsight_curation":
        return "批准只记录一条 Hindsight curation owner decision；不会写入、删除、降级或提升 Hindsight，也不会让 Hindsight authoritative。"
    return "仅供了解；不需要状态变更。"


def _review_actions(target_type: str, target_id: str) -> list[dict[str, str]]:
    if not target_id:
        return []
    if target_type == "candidate":
        return [
            _review_action("approve", "approve_candidate", target_type, target_id),
            _review_action("reject", "reject_candidate", target_type, target_id),
        ]
    if target_type == "candidate_cluster":
        return [
            _review_action("approve", "approve_candidate_cluster", target_type, target_id),
            _review_action("reject", "reject_candidate_cluster", target_type, target_id),
            _review_action("defer", "defer_candidate_cluster", target_type, target_id),
        ]
    if target_type == "proposal":
        # Generic or template proposals are deliberately not actionable. They
        # must mature into a concrete proposal before owner approval.
        # The item-specific suppression happens in _render_review_item().
        return [
            _review_action("approve", "approve_proposal", target_type, target_id),
            _review_action("reject", "reject_proposal", target_type, target_id),
        ]
    if target_type == "proposal_apply":
        return [_review_action("apply", "apply_proposal", "proposal", target_id)]
    if target_type == "crystallized_record":
        return [
            _review_action("demote", "demote_crystallized", target_type, target_id),
            _review_action("revoke", "revoke_crystallized", target_type, target_id),
        ]
    if target_type == "memory_source":
        return [_review_action("feedback", "mark_feedback", target_type, target_id)]
    if target_type == "speak":
        actions = [_review_action("allow", "allow_speak_once", target_type, target_id)]
        actions.extend(
            _review_action("feedback", action_type, "expression", target_id)
            for action_type in EXPRESSION_FEEDBACK_DIGEST_ACTIONS
        )
        return actions
    if target_type == "session_mirror_apply":
        return [_review_action("approve", "approve_session_mirror_apply", target_type, target_id)]
    if target_type == "hindsight_curation":
        return [
            _review_action("approve", "retain_hindsight_curation", target_type, target_id),
            _review_action("reject", "reject_hindsight_curation", target_type, target_id),
            _review_action("demote", "demote_hindsight_curation", target_type, target_id),
        ]
    if target_type == "provisional_crystallized_record":
        return [
            _review_action("confirm", "confirm_provisional_crystallized_record", target_type, target_id),
            _review_action("reject", "reject_provisional_crystallized_record", target_type, target_id),
        ]
    if target_type == "knob_override":
        return [
            _review_action("confirm", "confirm_provisional_knob_override", target_type, target_id),
            _review_action("reject", "reject_provisional_knob_override", target_type, target_id),
        ]
    return []


def _review_item_suppresses_actions(item: dict[str, Any]) -> bool:
    return bool(item.get("actions_suppressed")) or (
        str(item.get("target_type") or "") == "proposal" and bool(item.get("requires_maturation"))
    )


def _review_action(verb: str, action_type: str, target_type: str, target_id: str) -> dict[str, str]:
    token = _action_token(action_type=action_type, target_type=target_type, target_id=target_id)
    rating = ""
    if action_type == "mark_feedback":
        rating = "useful|irrelevant|too_mechanistic|missing_context|overconfident|needs_specific_recall"
    elif action_type in EXPRESSION_FEEDBACK_ACTION_TYPES:
        rating = action_type
    owner_utterance_example = _owner_utterance_example(action=verb, action_token=token, rating=rating)
    agent_tool_call = (
        {}
        if "|" in rating or verb == "defer"
        else _owner_review_reply_tool_call(action=verb, action_token=token, rating=rating)
    )
    return {
        "verb": verb,
        "action_type": action_type,
        "target_type": target_type,
        "target_id": target_id,
        "token": token,
        "owner_utterance_example": owner_utterance_example,
        "agent_tool_call": agent_tool_call,
    }


def _action_token(*, action_type: str, target_type: str, target_id: str) -> str:
    payload = "|".join([str(action_type), str(target_type), str(target_id)])
    return "oa_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:14]


def _render_expiring_provisional_section(store: MemoryOSStore) -> str:
    """渲染临近过期 provisional 区段，带 confirm/let_expire action token。

    从 system/expiring_provisional.json 读取 sweep 输出的列表，
    按 recurrence 降序 + expires_at 升序取 top-N，生成 digest 区段。
    """
    from plugins.modules.governance.provisional_sweep import _expiring_list_path as _sweep_list_path
    from plugins.memory.memory_os.knob_overrides import resolve_knob

    list_path = _sweep_list_path(store)
    if not list_path.exists():
        return ""

    try:
        expiring = json.loads(list_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ""

    if not isinstance(expiring, list) or not expiring:
        return ""

    max_n = int(resolve_knob("max_expiring_in_digest", default=10))
    # 按 recurrence 降序 + expires_at 升序
    expiring.sort(
        key=lambda r: (
            -int(r.get("recurrence", 0)),
            str(r.get("expires_at", "")),
        )
    )
    expiring = expiring[:max_n]

    lines = [
        "## ⚠ 即将过期的 Provisional 事实（48h 内）",
        "",
    ]
    for r in expiring:
        record_id = str(r.get("id") or "")
        raw_body = str(r.get("body") or "").strip()
        if _contains_transcript_marker(raw_body):
            body = "(摘要隐藏：内容包含原始对话片段)"
        else:
            body = raw_body
            if len(body) > 120:
                body = body[:117] + "..."
        hours = int(r.get("hours_remaining", 0))
        external_ref = str(r.get("external_ref") or "")
        ref_line = f"\n    外部参考: {external_ref}" if external_ref else ""

        lines.append(
            f"- [⏳即将过期] {body} (剩{hours}h){ref_line}\n"
            f"    → confirm: 确认为 permanent    let_expire: 让其过期\n"
            f"    action_tokens: oa_confirm_{record_id} | oa_let_expire_{record_id}"
        )
    lines.append("")
    return "\n".join(lines)


def _digest_text_preview(
    action_items: list[dict[str, Any]],
    suggested_items: list[dict[str, Any]],
    fyi_items: list[dict[str, Any]],
    *,
    store: MemoryOSStore | None = None,
) -> str:
    rendered_sections = {
        "action_required": [_render_review_item(item, section="action_required") for item in action_items],
        "review_suggested": [_render_review_item(item, section="review_suggested") for item in suggested_items],
        "fyi": [_render_review_item(item, section="fyi") for item in fyi_items],
    }
    return _rendered_digest_text(rendered_sections, store=store)[:2000]


def _rendered_digest_text(
    sections: dict[str, list[dict[str, Any]]],
    *,
    counts: dict[str, Any] | None = None,
    overflow: dict[str, Any] | None = None,
    digest_mode: str = "review",
    store: MemoryOSStore | None = None,
) -> str:
    digest_mode = _digest_mode(digest_mode)
    max_chars = OWNER_REVIEW_TEXT_LIMIT
    title = "Memory-OS 今日审批议程" if digest_mode == "agenda" else "Memory-OS 审批摘要"
    initial_overview = _rendered_overview_lines(counts or {}, overflow or {}, digest_mode=digest_mode)
    overview_start = 2
    overview_end = overview_start + len(initial_overview)
    lines = [
        title,
        "",
        *initial_overview,
        "",
        "回复方式：",
        "- 直接在 Hermes 会话里回复示例，例如：memory approve oa_...",
        "- 也可以只回复 oa_...，Hermes 会继续问你要 approve/reject/allow/feedback。",
        "- A1/R1/F1 只是列表编号，不是审批 ID。",
        "",
    ]
    rendered_counts: dict[str, int] = {}
    budget_omitted: dict[str, int] = {}
    section_specs = [("需要你决定", "action_required")]
    if digest_mode != "agenda":
        section_specs.extend(
            [
                ("建议你看", "review_suggested"),
                ("仅供了解", "fyi"),
            ]
        )
    for section_title, key in section_specs:
        section_lines = [f"{section_title}:"]
        items = sections.get(key, [])
        shown_count = 0
        section_omitted = 0
        if not items:
            section_lines.append("- 无")
        for item in items:
            item_lines = _rendered_digest_item_lines(item)
            candidate = lines + section_lines + item_lines + [""]
            if len("\n".join(candidate).rstrip()) > max_chars:
                section_omitted += 1
                continue
            section_lines.extend(item_lines)
            shown_count += 1
        rendered_counts[key] = shown_count
        budget_omitted[key] = section_omitted
        if section_omitted:
            summary_line = f"- 还有 {section_omitted} 项为了控制 Telegram 摘要长度被省略。"
            candidate = lines + section_lines + [summary_line, ""]
            if len("\n".join(candidate).rstrip()) <= max_chars:
                section_lines.append(summary_line)
        lines.extend(section_lines)
        lines.append("")

    # 临近过期 provisional 提醒（expiry cliff guard）
    if store is not None:
        _expiring = _render_expiring_provisional_section(store)
        if _expiring:
            candidate = lines + [_expiring]
            if len("\n".join(candidate).rstrip()) <= max_chars:
                lines.append(_expiring)

    # 待审批 edges 区段（owner review for governed edges）
    if store is not None:
        try:
            from .index import MemoryOSIndex, _initialize_schema
            index = MemoryOSIndex(store.roots)
            if index.roots.index_path.exists():
                conn = sqlite3.connect(str(index.roots.index_path))
                conn.row_factory = sqlite3.Row
                try:
                    _initialize_schema(conn)
                    rows = conn.execute(
                        "select * from memory_edges where state = 'owner_eligible' order by weight desc limit 20"
                    ).fetchall()
                    if rows:
                        edge_lines = ["## Pending Edge Review", ""]
                        for row in rows:
                            edge_id = row["edge_id"]
                            rel = row["relation_type"]
                            weight = row["weight"]
                            from_id = row["from_record_id"]
                            to_id = row["to_record_id"]
                            edge_lines.append(
                                f"- [{rel} w={weight:.2f}] {from_id} -> {to_id}\n"
                                f"  approve_edge:{edge_id} | reject_edge:{edge_id}"
                            )
                        candidate = lines + edge_lines + [""]
                        if len("\n".join(candidate).rstrip()) <= max_chars:
                            lines.extend(edge_lines)
                            lines.append("")
                finally:
                    conn.close()
        except Exception as exc:
            # fail-open: edge digest must not break main digest
            try:
                _append_jsonl(
                    store.roots.memory_os_root / "system" / "error_records.jsonl",
                    build_error_record(
                        component="owner_actions._rendered_digest_text",
                        operation="edge_digest_query",
                        error_code="edge_digest_query_failed",
                        severity="warn",
                        recoverable=True,
                        details={"error_type": type(exc).__name__, "message": str(exc)[:200]},
                    ),
                )
            except Exception:
                pass

    final_overview = _rendered_overview_lines(
        counts or {},
        overflow or {},
        digest_mode=digest_mode,
        rendered_counts=rendered_counts,
        budget_omitted=budget_omitted,
    )
    lines = lines[:overview_start] + final_overview + lines[overview_end:]
    return "\n".join(lines).rstrip()


def _rendered_overview_lines(
    counts: dict[str, Any],
    overflow: dict[str, Any],
    *,
    digest_mode: str = "review",
    rendered_counts: dict[str, int] | None = None,
    budget_omitted: dict[str, int] | None = None,
) -> list[str]:
    if not counts:
        return ["全貌：本条摘要只展示当前优先项；未展示项会在后续摘要或你主动要求时继续展开。"]
    pending = int(counts.get("pending") or 0)
    action_total = int(counts.get("action_required_total") or 0)
    action_shown = int(counts.get("action_required_shown") or 0)
    suggested_total = int(counts.get("review_suggested_total") or 0)
    suggested_shown = int(counts.get("review_suggested_shown") or 0)
    fyi_total = int(counts.get("fyi_total") or 0)
    fyi_shown = int(counts.get("fyi_shown") or 0)
    if rendered_counts is not None:
        action_shown = int(rendered_counts.get("action_required", action_shown))
        suggested_shown = int(rendered_counts.get("review_suggested", suggested_shown))
        fyi_shown = int(rendered_counts.get("fyi", fyi_shown))
    budget_omitted = budget_omitted or {}
    action_omitted = max(
        int(overflow.get("action_required") or 0),
        int(budget_omitted.get("action_required") or 0),
        max(action_total - action_shown, 0),
    )
    suggested_omitted = max(
        int(overflow.get("review_suggested") or 0),
        int(budget_omitted.get("review_suggested") or 0),
        max(suggested_total - suggested_shown, 0),
    )
    fyi_omitted = max(
        int(overflow.get("fyi") or 0),
        int(budget_omitted.get("fyi") or 0),
        max(fyi_total - fyi_shown, 0),
    )
    if _digest_mode(digest_mode) == "agenda":
        lines = [
            "今日议程：",
            f"- 需要你决定 {action_total} 项；本条展示 {action_shown} 项，未展示 {action_omitted} 项。",
            "- 本推送只包含审批项和真实告警；建议查看/FYI 不主动推送。",
        ]
        if action_omitted:
            lines.append("- 想继续处理可回复：下一页 / 还有哪些 / 展开 A4。")
        else:
            lines.append("- 其它观察项可主动问：还有哪些 / 查看建议项 / 查看 FYI。")
        return lines
    return [
        "全貌：",
        f"- 待处理 {pending} 项；本条展示 {action_shown + suggested_shown + fyi_shown} 项。",
        f"- 需要你决定 {action_total} 项：展示 {action_shown}，未展示 {action_omitted}。",
        f"- 建议你看 {suggested_total} 项：展示 {suggested_shown}，未展示 {suggested_omitted}。",
        f"- 仅供了解 {fyi_total} 项：展示 {fyi_shown}，未展示 {fyi_omitted}。",
        "- 没展示的不是丢失；为避免刷屏，会在后续摘要或你要求展开时再列。",
    ]


def _delivery_message_from_preview(preview: dict[str, Any]) -> str:
    text = str(preview.get("text_preview") or "")
    text = text.replace("Memory-OS owner review preview", "Memory-OS 审批摘要", 1)
    lines = [
        "Memory-OS 审批摘要",
        "",
        "这是 owner 触发的一次性 review smoke；不会自动审批或执行。",
        "",
    ]
    body = text
    if body.startswith("Memory-OS 审批摘要"):
        body = "\n".join(body.splitlines()[1:]).lstrip()
    lines.append(body)
    message = "\n".join(lines)
    return _bounded_text(message, 3500)


def _digest_lines(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- none"]
    return [f"- [{item.get('anchor')}] {item.get('summary')}" for item in items]


def _rendered_digest_lines(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- none"]
    lines: list[str] = []
    for item in items:
        lines.extend(_rendered_digest_item_lines(item))
    return lines


def _rendered_digest_item_lines(item: dict[str, Any]) -> list[str]:
    target_ref = f"{item.get('target_type')}:{item.get('target_id')}"
    examples = [
        str(value)
        for value in (item.get("owner_utterance_examples") or item.get("action_commands") or [])
    ]
    action_line = " / ".join(examples) if examples else str(item.get("suggested_action") or "no action required")
    lines = [
        f"- [{item.get('anchor')}] {item.get('question')}",
        f"  会话回复示例: {action_line}",
        f"  引用: {target_ref}",
        f"  原因: {item.get('reason')}",
        f"  结果: {item.get('consequence')}",
        f"  来源: {item.get('source_module')}",
    ]
    expression_preview = str(item.get("expression_preview") or "")
    if expression_preview:
        lines.insert(1, f"  内容: {expression_preview}")
    proposal_detail = str(item.get("proposal_detail") or "")
    if proposal_detail:
        proposal_detail = proposal_detail.replace("owner 对", "用户对").replace("owner 标记", "用户标记")
        proposal_detail = proposal_detail.replace("根据 owner ", "根据用户 ")
        proposal_detail = proposal_detail.replace("根据 用户", "根据用户").replace("根据用户 ", "根据用户")
        proposal_detail = proposal_detail.replace("用户 表达", "用户表达")
        lines.insert(1, f"  内容: {_bounded_text(proposal_detail, 280)}")
    return lines


def _rendered_anchor_map(rendered: dict[str, Any]) -> dict[str, dict[str, Any]]:
    sections = rendered.get("sections") if isinstance(rendered.get("sections"), dict) else {}
    result: dict[str, dict[str, Any]] = {}
    for items in sections.values():
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict) and str(item.get("anchor") or ""):
                result[str(item.get("anchor")).upper()] = item
    return result


def _rendered_action_token_map(rendered: dict[str, Any]) -> dict[str, dict[str, Any]]:
    sections = rendered.get("sections") if isinstance(rendered.get("sections"), dict) else {}
    result: dict[str, dict[str, Any]] = {}
    for items in sections.values():
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            tokens = item.get("action_tokens") if isinstance(item.get("action_tokens"), dict) else {}
            for action_type, token in tokens.items():
                clean = str(token or "").lower()
                if not clean:
                    continue
                target_type, target_id = _target_for_action_item(str(action_type), item)
                result[clean] = {
                    "item": item,
                    "action_type": str(action_type),
                    "target_type": target_type,
                    "target_id": target_id,
                }
    return result


MEMORY_SOURCE_FEEDBACK_CONTEXT_RATINGS = (
    "useful",
    "missing_context",
    "too_mechanistic",
    "needs_specific_recall",
    "overconfident",
    "irrelevant",
    "missing_candidate",
    "clarification_selected",
    "clarification_rejected",
)


def _surface_action_token_map(roots: MemoryOSRoots) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    result.update(_expression_feedback_action_token_map(roots))
    result.update(_memory_sources_feedback_action_token_map(roots))
    result.update(_proposal_followup_action_token_map(roots))
    result.update(_crystallized_revoke_action_token_map(roots))
    return result


def _crystallized_revoke_action_token_map(roots: MemoryOSRoots) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    store = MemoryOSStore(roots)
    service = CrystallizedMemoryService(store)
    if not roots.crystallized_root.exists():
        return result
    for path in sorted(roots.crystallized_root.glob("*.md")):
        for record in service.read_records(path.name):
            if not is_active_crystallized_frontmatter(record.frontmatter):
                continue
            record_id = str(record.frontmatter.get("id") or "").strip()
            if not record_id:
                continue
            token = _action_token(
                action_type="revoke_crystallized",
                target_type="crystallized_record",
                target_id=record_id,
            )
            demote_token = _action_token(
                action_type="demote_crystallized",
                target_type="crystallized_record",
                target_id=record_id,
            )
            item = {
                "target_type": "crystallized_record",
                "target_id": record_id,
                "source_module": "crystallized_memory",
                "summary": _bounded_text(record.body, 220),
                "action_tokens": {"demote_crystallized": demote_token, "revoke_crystallized": token},
                "action_targets": {
                    "demote_crystallized": {
                        "target_type": "crystallized_record",
                        "target_id": record_id,
                    },
                    "revoke_crystallized": {
                        "target_type": "crystallized_record",
                        "target_id": record_id,
                    }
                },
                "safe_source_ids": [f"crystallized:{record_id}"],
                "raw_body_included": False,
            }
            result[token] = {
                "item": item,
                "action_type": "revoke_crystallized",
                "target_type": "crystallized_record",
                "target_id": record_id,
            }
            result[demote_token] = {
                "item": item,
                "action_type": "demote_crystallized",
                "target_type": "crystallized_record",
                "target_id": record_id,
            }
    return result


def _proposal_followup_action_token_map(roots: MemoryOSRoots) -> dict[str, dict[str, Any]]:
    """Stable apply tokens for approved proposal follow-ups surfaced outside digests."""

    result: dict[str, dict[str, Any]] = {}
    store = MemoryOSStore(roots)
    report = approved_proposal_followups_report(store, limit=1_000_000)
    _attach_proposal_followup_apply_actions(report)
    for item in report.get("items") if isinstance(report.get("items"), list) else []:
        if not isinstance(item, dict):
            continue
        proposal_id = str(item.get("proposal_id") or "")
        token = str((item.get("action_tokens") or {}).get("apply_proposal") or "").lower()
        if not proposal_id or not token:
            continue
        result[token] = {
            "item": item,
            "action_type": "apply_proposal",
            "target_type": "proposal",
            "target_id": proposal_id,
        }
    return result


def _attach_proposal_followup_apply_actions(report: dict[str, Any]) -> None:
    """Attach owner/agent apply affordances to bounded follow-up report items."""

    items = report.get("items") if isinstance(report.get("items"), list) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        if str(item.get("followup_state") or "") != "supported_apply_ready":
            continue
        if str(item.get("ops_gate_decision") or "") != "would_allow":
            continue
        proposal_kind = str(item.get("proposal_kind") or "")
        if proposal_kind not in {"expression_policy", "memory_sources_policy", "proposal_queue_cleanup"}:
            continue
        proposal_id = str(item.get("proposal_id") or "")
        if not proposal_id:
            continue
        token = _action_token(action_type="apply_proposal", target_type="proposal", target_id=proposal_id)
        item["action_tokens"] = {"apply_proposal": token}
        item["action_targets"] = {"apply_proposal": {"target_type": "proposal", "target_id": proposal_id}}
        item["owner_utterance_examples"] = [
            _owner_utterance_example(action="apply", action_token=token)
        ]
        item["agent_tool_calls"] = [
            _owner_review_reply_tool_call(action="apply", action_token=token)
        ]
        item["explicit_apply_warning"] = (
            "This applies only this bounded proposal kind after OpsGate would_allow; "
            "it does not create a generic executor or execution ticket."
        )


def _expression_feedback_action_token_map(roots: MemoryOSRoots) -> dict[str, dict[str, Any]]:
    """Stable token map for right-brain outcome feedback surfaced outside digests."""

    result: dict[str, dict[str, Any]] = {}
    for outcome in _read_jsonl(right_brain_expression_outcomes_path(roots)):
        if not isinstance(outcome, dict):
            continue
        outcome_id = str(outcome.get("outcome_id") or "")
        if not outcome_id:
            continue
        item = _right_brain_expression_feedback_item(outcome)
        for action_type, token in (item.get("action_tokens") or {}).items():
            clean = str(token or "").lower()
            if not clean:
                continue
            result[clean] = {
                "item": item,
                "action_type": str(action_type),
                "target_type": "expression",
                "target_id": outcome_id,
            }
    return result


def _memory_sources_feedback_action_token_map(roots: MemoryOSRoots) -> dict[str, dict[str, Any]]:
    """Stable token map for MemorySources feedback surfaced outside digests."""

    result: dict[str, dict[str, Any]] = {}
    for record in read_memory_source_records(roots, limit=50):
        if not isinstance(record, dict):
            continue
        record_id = str(record.get("record_id") or "")
        if not record_id:
            continue
        item = _memory_source_feedback_item(record)
        token = str((item.get("action_tokens") or {}).get("mark_feedback") or "").lower()
        if not token:
            continue
        result[token] = {
            "item": item,
            "action_type": "mark_feedback",
            "target_type": "memory_source",
            "target_id": record_id,
        }
    return result


def _right_brain_expression_feedback_item(outcome: dict[str, Any]) -> dict[str, Any]:
    outcome_id = str(outcome.get("outcome_id") or "")
    actions = [
        _review_action("feedback", action_type, "expression", outcome_id)
        for action_type in EXPRESSION_FEEDBACK_ACTION_TYPES
    ]
    observed_at = str(outcome.get("observed_at") or "")
    policy_version = outcome.get("policy_version")
    preview = _bounded_text(str(outcome.get("outcome_preview") or ""), 280)
    return {
        "anchor": "EXPR",
        "target_type": "expression",
        "target_id": outcome_id,
        "source_module": "right_brain_expression_adapter",
        "section": "feedback_context",
        "question": "你对最近一次右脑表达的感觉是什么？",
        "suggested_action": "Hermes agent 应先听 owner 的自然反馈，再用对应 token 调 memory_os_review_reply。",
        "reason": _bounded_text(
            f"最近一次右脑表达 outcome={outcome_id}; policy_version={policy_version}; observed_at={observed_at}。",
            220,
        ),
        "consequence": "反馈只写入 expression_feedback ledger；不会直接改 prompt、policy、cadence、route 或发送行为。",
        "expression_preview": preview,
        "outcome_preview_chars": int(outcome.get("outcome_preview_chars") or len(preview)),
        "outcome_silent": bool(outcome.get("silent")),
        "policy_version": policy_version,
        "request_id": str(outcome.get("request_id") or ""),
        "observed_at": observed_at,
        "action_tokens": {action["action_type"]: action["token"] for action in actions},
        "action_targets": {
            action["action_type"]: {
                "target_type": action["target_type"],
                "target_id": action["target_id"],
            }
            for action in actions
        },
        "owner_utterance_scope": "owner_chat_utterance",
        "owner_utterance_examples": [action["owner_utterance_example"] for action in actions],
        "agent_tool_calls": [
            action["agent_tool_call"]
            for action in actions
            if isinstance(action.get("agent_tool_call"), dict) and action["agent_tool_call"]
        ],
        "safe_source_ids": [f"right_brain_expression_outcome:{outcome_id}"],
        "raw_body_included": False,
    }


def _memory_source_feedback_item(record: dict[str, Any], *, roots: MemoryOSRoots | None = None) -> dict[str, Any]:
    record_id = str(record.get("record_id") or "")
    action = _review_action("feedback", "mark_feedback", "memory_source", record_id)
    selected = record.get("selected") if isinstance(record.get("selected"), list) else []
    source_classes: list[str] = []
    safe_source_ids: list[str] = []
    for entry in selected:
        if not isinstance(entry, dict):
            continue
        source_class = str(entry.get("source_class") or entry.get("class") or "").strip()
        if source_class:
            source_classes.append(source_class)
        safe_source_ids.extend(_safe_list(entry.get("safe_source_ids")))
    route = str(record.get("route") or "unknown")
    query_class = str(record.get("query_class") or route or "unknown")
    created_at = str(record.get("created_at") or "")
    owner_utterance_examples = [
        _owner_utterance_example(action="feedback", action_token=action["token"], rating=rating)
        for rating in MEMORY_SOURCE_FEEDBACK_CONTEXT_RATINGS
        if rating in ALLOWED_FEEDBACK_RATINGS
    ]
    item = {
        "anchor": "MSRC",
        "target_type": "memory_source",
        "target_id": record_id,
        "source_module": "memory_sources",
        "section": "feedback_context",
        "question": "这次注入的记忆/上下文对回答有帮助吗？",
        "suggested_action": "Hermes agent 应先听 owner 的自然反馈，再用对应 rating 和 token 调 memory_os_review_reply。",
        "reason": _bounded_text(
            f"最近一次 MemorySources 归因 record={record_id}; route={route}; query_class={query_class}; created_at={created_at}。",
            240,
        ),
        "consequence": "反馈只写入 MemorySources feedback ledger；不会直接改 live route、context、prompt、policy 或发送行为。",
        "route": route,
        "query_class": query_class,
        "route_reason_codes": _safe_list(record.get("route_reason_codes"))[:6],
        "source_classes": _dedupe_strings(source_classes)[:8],
        "safe_source_ids": _dedupe_strings(safe_source_ids)[:10],
        "selected_count": len(selected),
        "selected_chars_total": int(record.get("selected_chars_total") or 0),
        "created_at": created_at,
        "allowed_ratings": sorted(ALLOWED_FEEDBACK_RATINGS),
        "action_tokens": {"mark_feedback": action["token"]},
        "action_targets": {
            "mark_feedback": {
                "target_type": action["target_type"],
                "target_id": action["target_id"],
            }
        },
        "owner_utterance_scope": "owner_chat_utterance",
        "owner_utterance_examples": owner_utterance_examples,
        "raw_body_included": False,
    }
    if roots is not None:
        item["agent_tool_calls"] = [
            {
                "rating": rating,
                "agent_tool_call": _owner_review_reply_tool_call(
                    action="feedback",
                    action_token=action["token"],
                    rating=rating,
                ),
            }
            for rating in MEMORY_SOURCE_FEEDBACK_CONTEXT_RATINGS
            if rating in ALLOWED_FEEDBACK_RATINGS
        ]
    return item


def _dedupe_strings(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _parse_owner_reply_text(reply_text: str) -> dict[str, Any]:
    text = " ".join(str(reply_text or "").strip().split())
    if text.startswith("/memory "):
        text = "memory " + text[len("/memory ") :]
    parts = text.split()
    if len(parts) < 2:
        return {"status": "needs_clarification", "reason": "expected_action_and_anchor"}
    prefixed = False
    if parts[0].lower() in {"memory", "mos"}:
        prefixed = True
        parts = parts[1:]
        if len(parts) < 2:
            return {"status": "needs_clarification", "reason": "expected_action_and_token"}
    verb = _normalize_reply_verb(parts[0])
    if not verb:
        return {"status": "needs_clarification", "reason": "unknown_action_verb"}
    target = parts[1].strip("：:,.，。[]()")
    action_token = ""
    anchor = ""
    if target.lower().startswith("oa_"):
        action_token = target.lower()
    elif prefixed:
        return {"status": "needs_clarification", "reason": "expected_action_token"}
    else:
        anchor = target.upper()
    if not anchor and not action_token:
        return {"status": "needs_clarification", "reason": "missing_anchor_or_token"}
    rating = ""
    if verb == "feedback":
        if len(parts) < 3:
            return {
                "status": "needs_clarification",
                "reason": "missing_feedback_rating",
                "anchor": anchor,
                "action_token": action_token,
            }
        rating = parts[2].strip("：:,.，。")
        if rating not in ALLOWED_FEEDBACK_RATINGS and rating not in EXPRESSION_FEEDBACK_ACTION_TYPES:
            return {
                "status": "needs_clarification",
                "reason": "invalid_feedback_rating",
                "anchor": anchor,
                "action_token": action_token,
                "rating": rating,
            }
    return {"status": "ok", "verb": verb, "anchor": anchor, "action_token": action_token, "rating": rating}


def _normalize_reply_verb(value: str) -> str:
    verb = str(value or "").strip().lower()
    mapping = {
        "approve": "approve",
        "批准": "approve",
        "通过": "approve",
        "reject": "reject",
        "拒绝": "reject",
        "feedback": "feedback",
        "mark": "feedback",
        "反馈": "feedback",
        "allow": "allow",
        "允许": "allow",
        "demote": "demote",
        "降级": "demote",
        "降权": "demote",
        "revoke": "revoke",
        "撤销": "revoke",
        "撤回": "revoke",
        "apply": "apply",
        "应用": "apply",
        "执行": "apply",
    }
    return mapping.get(verb, "")


def _owner_action_type_from_reply(verb: str, item: dict[str, Any]) -> str:
    target_type = str(item.get("target_type") or "")
    if verb == "approve" and target_type == "candidate":
        return "approve_candidate"
    if verb == "reject" and target_type == "candidate":
        return "reject_candidate"
    if verb == "approve" and target_type == "proposal":
        return "approve_proposal"
    if verb == "reject" and target_type == "proposal":
        return "reject_proposal"
    if verb == "apply" and target_type == "proposal":
        return "apply_proposal"
    if verb == "demote" and target_type == "crystallized_record":
        return "demote_crystallized"
    if verb == "revoke" and target_type == "crystallized_record":
        return "revoke_crystallized"
    if verb == "feedback" and target_type == "memory_source":
        return "mark_feedback"
    if verb == "allow" and target_type == "speak":
        return "allow_speak_once"
    if verb == "approve" and target_type == "session_mirror_apply":
        return "approve_session_mirror_apply"
    if verb == "approve" and target_type == "hindsight_curation":
        return "retain_hindsight_curation"
    if verb == "reject" and target_type == "hindsight_curation":
        return "reject_hindsight_curation"
    if verb == "demote" and target_type == "hindsight_curation":
        return "demote_hindsight_curation"
    if verb in ("approve", "confirm") and target_type == "provisional_crystallized_record":
        return "confirm_provisional_crystallized_record"
    if verb == "reject" and target_type == "provisional_crystallized_record":
        return "reject_provisional_crystallized_record"
    if verb in ("approve", "confirm") and target_type == "knob_override":
        return "confirm_provisional_knob_override"
    if verb == "reject" and target_type == "knob_override":
        return "reject_provisional_knob_override"
    return ""


def _reply_verb_matches_action_type(verb: str, action_type: str) -> bool:
    if verb == "approve":
        return action_type in {
            "approve_candidate",
            "approve_proposal",
            "approve_session_mirror_apply",
            "retain_hindsight_curation",
            "approve_edge",
        }
    if verb == "reject":
        return action_type in {"reject_candidate", "reject_proposal", "reject_hindsight_curation", "reject_provisional_crystallized_record", "reject_provisional_knob_override", "reject_edge"}
    if verb == "feedback":
        return action_type == "mark_feedback" or action_type in EXPRESSION_FEEDBACK_ACTION_TYPES
    if verb == "allow":
        return action_type == "allow_speak_once"
    if verb == "apply":
        return action_type == "apply_proposal"
    if verb == "demote":
        return action_type in {"demote_crystallized", "demote_hindsight_curation"}
    if verb == "revoke":
        return action_type == "revoke_crystallized"
    if verb == "confirm":
        return action_type in {"confirm_provisional_crystallized_record", "confirm_provisional_knob_override"}
    return False


def _target_for_action_item(action_type: str, item: dict[str, Any]) -> tuple[str, str]:
    action_targets = item.get("action_targets") if isinstance(item.get("action_targets"), dict) else {}
    target = action_targets.get(action_type) if isinstance(action_targets.get(action_type), dict) else {}
    if target:
        return str(target.get("target_type") or ""), str(target.get("target_id") or "")
    if action_type in EXPRESSION_FEEDBACK_ACTION_TYPES:
        return "expression", str(item.get("target_id") or "")
    return str(item.get("target_type") or ""), str(item.get("target_id") or "")


def _owner_reply_action_context(
    *,
    rendered: dict[str, Any],
    binding: str,
    item: dict[str, Any],
    action_token: str,
    reply_text: str,
) -> dict[str, Any]:
    delivery_binding = rendered.get("delivery_binding") if isinstance(rendered.get("delivery_binding"), dict) else {}
    digest_id = str(rendered.get("digest_id") or "")
    token = str(action_token or "").lower()
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest() if token else ""
    reply_ingress_id = "reply_" + hashlib.sha256(
        "|".join([digest_id, token, str(reply_text or "")]).encode("utf-8")
    ).hexdigest()[:16]
    owner_home_bound = str(delivery_binding.get("scope") or "") == "owner_home"
    return {
        "source": "latest_owner_home_digest" if owner_home_bound else binding,
        "digest_id": digest_id,
        "reply_ingress_id": reply_ingress_id,
        "token_binding": {
            "scope": str(delivery_binding.get("scope") or ""),
            "digest_id": digest_id,
            "review_item_id": str(item.get("review_item_id") or f"{item.get('target_type')}:{item.get('target_id')}"),
            "action_token_hash": token_hash,
        },
        "session_mirror_approval": _bounded_session_mirror_approval(
            item.get("session_mirror_approval") if isinstance(item.get("session_mirror_approval"), dict) else {}
        ),
    }


def _reply_result(
    *,
    status: str,
    reply_text: str,
    owner_id: str,
    channel: str,
    apply: bool,
    reason: str,
    rendered: dict[str, Any],
    binding: str = "current_digest_fallback",
    parsed: dict[str, Any] | None = None,
    item: dict[str, Any] | None = None,
    action_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    anchors = sorted(_rendered_anchor_map(rendered))
    delivery_binding = rendered.get("delivery_binding") if isinstance(rendered.get("delivery_binding"), dict) else {}
    return {
        "schema_version": OWNER_REVIEW_REPLY_SCHEMA_VERSION,
        "profile": rendered.get("profile") or "default",
        "status": status,
        "dry_run": not apply,
        "owner_id": owner_id,
        "channel": channel,
        "reply_preview": _bounded_text(reply_text, 120),
        "reason": reason,
        "parsed": parsed or {},
        "matched_item": _bounded_matched_item(item or {}),
        "owner_action_result": action_result or {},
        "active_digest": {
            "digest_id": rendered.get("digest_id"),
            "binding": binding,
            "delivery_scope": delivery_binding.get("scope", ""),
            "delivery_channel": delivery_binding.get("channel", ""),
            "anchor_count": len(anchors),
            "anchors": anchors,
            "raw_body_included": False,
        },
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
        },
    }


def _bounded_matched_item(item: dict[str, Any]) -> dict[str, Any]:
    if not item:
        return {}
    return {
        "anchor": item.get("anchor"),
        "target_type": item.get("target_type"),
        "target_id": item.get("target_id"),
        "source_module": item.get("source_module"),
        "question": _bounded_text(str(item.get("question") or ""), 180),
        "raw_body_included": False,
    }


def _positive_limit(explicit: int | None, configured: Any, default: int) -> int:
    value = explicit if explicit is not None else configured
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return default


def _digest_mode(value: str | None) -> str:
    clean = str(value or "review").strip().lower().replace("-", "_")
    return clean if clean in {"review", "agenda", "debug"} else "review"


def _digest_id() -> str:
    created_at = datetime.now(timezone.utc)
    return f"odig_{created_at.strftime('%Y%m%dT%H%M%S%fZ')}_{uuid4().hex[:8]}"


def _safe_channel(value: str) -> str:
    channel = str(value or "").strip().lower().replace("-", "_")
    allowed = {
        "telegram",
        "cli",
        "web",
        "slack",
        "whatsapp",
        "wecom",
        "wechat",
        "weixin",
        "matrix",
        "discord",
        "signal",
        "origin",
        "unknown",
    }
    return channel if channel in allowed else "unknown"


def _safe_target_ref(value: str) -> str:
    text = " ".join(str(value or "").split())
    return _bounded_text(text, 180)


def _target_ref(platform: str, target: str) -> str:
    target = str(target or "").strip()
    if not target:
        return ""
    if ":" in target:
        return target
    platform = _safe_channel(platform)
    if platform == "unknown":
        return f"session:{target}"
    return f"{platform}:{target}"


def _direct_flag(value: Any, column_name: str) -> bool:
    text = str(value).strip().lower()
    truthy = text in {"1", "true", "yes", "y", "dm", "direct"}
    if column_name in {"is_group", "group"}:
        return not truthy
    return truthy


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute("select name from sqlite_master where type='table' and name=?", (table_name,)).fetchone()
    return row is not None


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"pragma table_info({table_name})").fetchall()}


def _first_existing(columns: set[str], names: tuple[str, ...]) -> str:
    for name in names:
        if name in columns:
            return name
    return ""


def _find_candidate(store: MemoryOSStore, candidate_id: str) -> CrystallizedCandidate | None:
    for candidate in read_candidate_queue(store.roots):
        if candidate.candidate_id == candidate_id:
            return candidate
    return None


def _find_crystallized_record(store: MemoryOSStore, record_id: str) -> dict[str, Any] | None:
    record = CrystallizedMemoryService(store).find_record(record_id)
    if record is None:
        return None
    return {
        "record_id": str(record.frontmatter.get("id") or ""),
        "file_name": record.file_name,
        "canonical_state": str(record.frontmatter.get("canonical_state") or "active"),
    }


def _find_proposal(store: MemoryOSStore, candidate_id: str) -> dict[str, Any] | None:
    for proposal in _read_proposal_queue(store):
        if str(proposal.get("candidate_id", "")) == candidate_id:
            return proposal
    return None


def _find_memory_source(store: MemoryOSStore, record_id: str) -> dict[str, Any] | None:
    for record in read_memory_source_records(store.roots, limit=1_000_000):
        if str(record.get("record_id", "")) == record_id:
            return record
    return None


def _hindsight_snapshot_id_for_store(store: MemoryOSStore) -> str:
    config = load_config(store.roots.hermes_home)
    substrate_root = config.get("substrate_providers") if isinstance(config.get("substrate_providers"), dict) else {}
    substrate = substrate_root.get("hindsight") if isinstance(substrate_root.get("hindsight"), dict) else {}
    configured = str(substrate.get("substrate_snapshot_id") or "")
    if configured:
        return configured
    bank_id = str(substrate.get("bank_id") or "unconfigured")
    return f"hindsight:{bank_id}:vcurrent"


def _read_proposal_queue(store: MemoryOSStore) -> list[dict[str, Any]]:
    path = store.roots.hermes_home / "system-modules" / "proposal_queue" / "queue.json"
    if not path.exists():
        return []
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    items = parsed.get("items", []) if isinstance(parsed, dict) else []
    return [item for item in items if isinstance(item, dict)]


def _latest_proposal_approval_by_target(actions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    approvals: dict[str, dict[str, Any]] = {}
    for action in actions:
        if action.get("result") != "applied":
            continue
        if action.get("action_type") != "approve_proposal":
            continue
        if action.get("target_type") != "proposal":
            continue
        target_id = str(action.get("target_id") or "")
        if not target_id:
            continue
        approvals[target_id] = action
    return approvals


def _ops_gate_reviews_by_proposal(store: MemoryOSStore) -> dict[str, dict[str, Any]]:
    path = store.roots.hermes_home / "system-modules" / "ops_gate" / "reports.jsonl"
    reviews: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return reviews
    for report in _read_jsonl(path):
        if not isinstance(report, dict):
            continue
        decisions = report.get("decisions")
        if not isinstance(decisions, list):
            continue
        for decision in decisions:
            if not isinstance(decision, dict):
                continue
            proposal_id = _proposal_id_from_ops_gate_action_id(str(decision.get("action_id") or ""))
            if not proposal_id:
                continue
            reviews[proposal_id] = {
                "report_id": str(report.get("report_id") or ""),
                "decision": str(decision.get("decision") or ""),
                "reason": str(decision.get("reason") or ""),
            }
    return reviews


def _proposal_id_from_ops_gate_action_id(action_id: str) -> str:
    prefix = "proposal_followup:"
    if action_id.startswith(prefix):
        return action_id[len(prefix) :]
    return ""


def _ops_gate_action_from_proposal(proposal: dict[str, Any]) -> dict[str, Any]:
    proposal_id = str(proposal.get("candidate_id") or "")
    return {
        "schema_version": "memory-os.ops_gate_proposed_action.v0",
        "id": f"proposal_followup:{proposal_id}",
        "kind": _bounded_text(str(proposal.get("kind") or "proposal"), 80),
        "target": f"proposal:{proposal_id}",
        "title": _bounded_text(str(proposal.get("title") or "Approved proposal"), 140),
        "source_module": "proposal_queue",
        "safe_source_ids": _safe_list(proposal.get("source_refs")),
        "raw_body_included": False,
        "execution_ticket_created": False,
        "actual_execute": False,
    }


def _approved_proposal_ops_gate_error(
    store: MemoryOSStore,
    *,
    proposal_id: str,
    owner_id: str,
    channel: str,
    reason: str,
    apply: bool,
) -> dict[str, Any]:
    return {
        "schema_version": APPROVED_PROPOSAL_OPS_GATE_SCHEMA_VERSION,
        "profile": store.roots.profile or "default",
        "status": "error",
        "dry_run": not apply,
        "owner_id": owner_id,
        "channel": channel,
        "proposal_id": proposal_id,
        "reason": reason,
        "ops_gate_report_written": False,
        "execution_ticket_created": False,
        "actual_execute": False,
        "raw_body_included": False,
        "boundary": _owner_review_false_boundary(),
    }


def _explicit_proposal_apply_kind(proposal: dict[str, Any]) -> str:
    kind = str(proposal.get("kind") or "").strip().lower()
    proposal_class = str(proposal.get("proposal_class") or "").strip().lower()
    dedupe_key = str(proposal.get("dedupe_key") or "").strip().lower()
    if kind == "expression_policy":
        return "expression_policy"
    if kind == "memory_sources_policy" or proposal_class.startswith("memory_sources_policy:"):
        return "memory_sources_policy"
    if kind == "proposal_queue_cleanup" and (
        proposal_class == "proposal_queue_legacy_template_cleanup"
        or dedupe_key == "proposal_queue_legacy_template_cleanup"
    ):
        return "proposal_queue_legacy_template_cleanup"
    return ""


def _unsupported_proposal_execution_ticket_kind(proposal: dict[str, Any]) -> str:
    kind = str(proposal.get("kind") or "").strip().lower()
    title = str(proposal.get("title") or "").strip().lower()
    if kind == "deep_reflection_self_evolution":
        return "deep_reflection_policy_plan"
    if kind == "weekly_consolidation":
        return "weekly_consolidation_evidence"
    if kind == "proposal" and "fresh deployment proposal queue validation" in title:
        return "validation_evidence"
    if kind == "proposal":
        return "typed_execution_plan_required"
    return ""


def _proposal_followup_next_step(followup_state: str) -> str:
    if followup_state == "supported_apply_ready":
        return "owner can explicitly apply this bounded policy/projection after OpsGate would_allow"
    if followup_state == "unsupported_requires_execution_ticket":
        return "create a typed execution ticket; do not run a generic apply"
    if followup_state == "awaiting_typed_execution_plan":
        return "implement or review the typed adapter/evidence path named by the execution ticket"
    if followup_state == "evidence_resolved":
        return "closed by linked validation evidence; no runtime execution required"
    if followup_state == "unsupported_apply_kind":
        return "manual decomposition required; no supported apply or ticket adapter exists"
    if followup_state == "awaiting_ops_gate_review":
        return "route through OpsGate report-only before any explicit owner decision"
    return "inspect bounded follow-up state"


def _approved_proposal_execution_ticket_result(
    store: MemoryOSStore,
    *,
    proposal: dict[str, Any],
    owner_id: str,
    channel: str,
    apply: bool,
    ticket_kind: str,
    ops_gate_review: dict[str, Any],
    evidence_refs: list[str],
    evidence_summary: str,
) -> dict[str, Any]:
    existing = _approved_proposal_execution_tickets_by_proposal(store).get(str(proposal.get("candidate_id") or ""), {})
    if apply and existing:
        if ticket_kind == "weekly_consolidation_evidence" and evidence_refs:
            ticket = _write_approved_proposal_execution_ticket(
                store,
                proposal=proposal,
                owner_id=owner_id,
                channel=channel,
                ticket_kind=ticket_kind,
                ops_gate_review=ops_gate_review,
                evidence_refs=evidence_refs,
                evidence_summary=evidence_summary,
                ticket_state="evidence_resolved",
                supersedes_ticket_id=str(existing.get("ticket_id") or ""),
            )
            return _approved_proposal_execution_ticket_apply_result(
                store,
                status="evidence_resolved",
                proposal=proposal,
                owner_id=owner_id,
                channel=channel,
                apply=apply,
                ticket_kind=ticket_kind,
                ops_gate_review=ops_gate_review,
                ticket=ticket,
            )
        if ticket_kind == "deep_reflection_policy_plan":
            if _deep_reflection_policy_applies_by_proposal(store).get(str(proposal.get("candidate_id") or "")):
                return _approved_proposal_execution_ticket_apply_result(
                    store,
                    status="duplicate_ignored",
                    proposal=proposal,
                    owner_id=owner_id,
                    channel=channel,
                    apply=apply,
                    ticket_kind=ticket_kind,
                    ops_gate_review=ops_gate_review,
                    ticket=existing,
                )
            policy_record = _write_deep_reflection_policy(
                store,
                proposal=proposal,
                owner_id=owner_id,
                channel=channel,
                ticket=existing,
                evidence_refs=evidence_refs,
                evidence_summary=evidence_summary,
            )
            ticket = _write_approved_proposal_execution_ticket(
                store,
                proposal=proposal,
                owner_id=owner_id,
                channel=channel,
                ticket_kind=ticket_kind,
                ops_gate_review=ops_gate_review,
                evidence_refs=evidence_refs,
                evidence_summary=evidence_summary,
                ticket_state="bounded_policy_written",
                supersedes_ticket_id=str(existing.get("ticket_id") or ""),
                policy_record=policy_record,
            )
            return _approved_proposal_execution_ticket_apply_result(
                store,
                status="bounded_policy_written",
                proposal=proposal,
                owner_id=owner_id,
                channel=channel,
                apply=apply,
                ticket_kind=ticket_kind,
                ops_gate_review=ops_gate_review,
                ticket=ticket,
            )
        return _approved_proposal_execution_ticket_apply_result(
            store,
            status="duplicate_ignored",
            proposal=proposal,
            owner_id=owner_id,
            channel=channel,
            apply=apply,
            ticket_kind=ticket_kind,
            ops_gate_review=ops_gate_review,
            ticket=existing,
        )
    ticket: dict[str, Any] = {}
    if apply:
        ticket = _write_approved_proposal_execution_ticket(
            store,
            proposal=proposal,
            owner_id=owner_id,
            channel=channel,
            ticket_kind=ticket_kind,
            ops_gate_review=ops_gate_review,
            evidence_refs=evidence_refs,
            evidence_summary=evidence_summary,
        )
    else:
        ticket = _planned_approved_proposal_execution_ticket(
            proposal=proposal,
            owner_id=owner_id,
            channel=channel,
            ticket_kind=ticket_kind,
            ops_gate_review=ops_gate_review,
            evidence_refs=evidence_refs,
            evidence_summary=evidence_summary,
        )
    result_status = str(ticket.get("ticket_state") or "ticket_created") if apply else "ready"
    if result_status == "awaiting_typed_execution_plan":
        result_status = "ticket_created" if apply else "ready"
    return _approved_proposal_execution_ticket_apply_result(
        store,
        status=result_status,
        proposal=proposal,
        owner_id=owner_id,
        channel=channel,
        apply=apply,
        ticket_kind=ticket_kind,
        ops_gate_review=ops_gate_review,
        ticket=ticket,
    )


def _approved_proposal_legacy_template_cleanup_apply_result(
    store: MemoryOSStore,
    *,
    status: str,
    proposal: dict[str, Any],
    owner_id: str,
    channel: str,
    apply: bool,
    ops_gate_review: dict[str, Any],
    apply_record: dict[str, Any],
    target_ids: list[str],
    closed_count: int,
    cleanup_written: bool,
) -> dict[str, Any]:
    proposal_id = str(proposal.get("candidate_id") or "")
    apply_id = str(apply_record.get("apply_id") or "")
    candidate_count = int(apply_record.get("matched_count") or len([item for item in target_ids if item]))
    return {
        "schema_version": APPROVED_PROPOSAL_EXECUTION_APPLY_SCHEMA_VERSION,
        "profile": store.roots.profile or "default",
        "status": status,
        "dry_run": not apply,
        "owner_id": owner_id,
        "channel": channel,
        "proposal_id": proposal_id,
        "proposal_state": str(proposal.get("state") or ""),
        "apply_kind": "proposal_queue_legacy_template_cleanup",
        "ops_gate_report_id": str(ops_gate_review.get("report_id") or ""),
        "ops_gate_decision": str(ops_gate_review.get("decision") or ""),
        "policy_write_planned": False,
        "policy_written": False,
        "cleanup_write_planned": True,
        "cleanup_written": cleanup_written,
        "legacy_template_candidate_count": candidate_count,
        "legacy_template_close_planned_count": candidate_count,
        "legacy_template_closed_count": closed_count,
        "legacy_template_candidate_ids": [item for item in target_ids if item][:50],
        "legacy_template_cleanup_apply_id": apply_id,
        "non_legacy_touched_count": 0,
        "execution_ticket_created": False,
        "actual_policy_write": False,
        "actual_execute": False,
        "actual_send": False,
        "raw_body_included": False,
        "rollback": "reopen pressure_blocked legacy template entries listed in legacy_template_cleanup_applies.jsonl if owner reverses the cleanup",
        "boundary": _owner_review_false_boundary(),
    }


def _approved_proposal_memory_sources_policy_apply_result(
    store: MemoryOSStore,
    *,
    status: str,
    proposal: dict[str, Any],
    owner_id: str,
    channel: str,
    apply: bool,
    ops_gate_review: dict[str, Any],
    apply_record: dict[str, Any],
    policy: dict[str, Any],
    policy_written: bool,
) -> dict[str, Any]:
    proposal_id = str(proposal.get("candidate_id") or "")
    return {
        "schema_version": APPROVED_PROPOSAL_EXECUTION_APPLY_SCHEMA_VERSION,
        "profile": store.roots.profile or "default",
        "status": status,
        "dry_run": not apply,
        "owner_id": owner_id,
        "channel": channel,
        "proposal_id": proposal_id,
        "proposal_state": str(proposal.get("state") or ""),
        "apply_kind": "memory_sources_policy",
        "ops_gate_report_id": str(ops_gate_review.get("report_id") or ""),
        "ops_gate_decision": str(ops_gate_review.get("decision") or ""),
        "policy_write_planned": True,
        "policy_written": policy_written,
        "memory_sources_policy_apply_id": str(apply_record.get("apply_id") or ""),
        "policy_version": int(apply_record.get("policy_version") or policy.get("policy_version") or 0),
        "policy_path": str(memory_sources_policy_path(store.roots)),
        "runtime_target": "context_retrieval_policy_review",
        "selection_policy_changed": False,
        "execution_ticket_created": False,
        "actual_policy_write": policy_written,
        "actual_execute": False,
        "actual_send": False,
        "raw_body_included": False,
        "rollback": "restore previous memory_sources/policy.json from policy_applies.jsonl previous_policy snapshot",
        "boundary": _owner_review_false_boundary(),
    }


def _approved_proposal_execution_apply_result(
    store: MemoryOSStore,
    *,
    status: str,
    proposal: dict[str, Any],
    owner_id: str,
    channel: str,
    apply: bool,
    ops_gate_review: dict[str, Any],
    existing_apply: dict[str, Any],
    policy: dict[str, Any],
    policy_written: bool,
) -> dict[str, Any]:
    proposal_id = str(proposal.get("candidate_id") or "")
    return {
        "schema_version": APPROVED_PROPOSAL_EXECUTION_APPLY_SCHEMA_VERSION,
        "profile": store.roots.profile or "default",
        "status": status,
        "dry_run": not apply,
        "owner_id": owner_id,
        "channel": channel,
        "proposal_id": proposal_id,
        "proposal_state": str(proposal.get("state") or ""),
        "apply_kind": "expression_policy",
        "ops_gate_report_id": str(ops_gate_review.get("report_id") or ""),
        "ops_gate_decision": str(ops_gate_review.get("decision") or ""),
        "policy_write_planned": True,
        "policy_written": policy_written,
        "policy_apply_id": str(existing_apply.get("apply_id") or ""),
        "policy_version": int(existing_apply.get("policy_version") or policy.get("policy_version") or 0),
        "policy_path": str(_right_brain_expression_policy_path(store)),
        "execution_ticket_created": False,
        "actual_policy_write": policy_written,
        "actual_execute": False,
        "actual_send": False,
        "raw_body_included": False,
        "rollback": "restore previous right_brain_expression_adapter/policy.json from policy_applies.jsonl previous_policy snapshot",
        "boundary": _owner_review_false_boundary(),
    }


def _approved_proposal_execution_apply_error(
    store: MemoryOSStore,
    *,
    proposal_id: str,
    owner_id: str,
    channel: str,
    reason: str,
    apply: bool,
) -> dict[str, Any]:
    return {
        "schema_version": APPROVED_PROPOSAL_EXECUTION_APPLY_SCHEMA_VERSION,
        "profile": store.roots.profile or "default",
        "status": "error",
        "dry_run": not apply,
        "owner_id": owner_id,
        "channel": channel,
        "proposal_id": proposal_id,
        "reason": reason,
        "apply_kind": "",
        "policy_write_planned": False,
        "policy_written": False,
        "execution_ticket_created": False,
        "actual_policy_write": False,
        "actual_execute": False,
        "actual_send": False,
        "raw_body_included": False,
        "boundary": _owner_review_false_boundary(),
    }


def _approved_proposal_execution_ticket_apply_result(
    store: MemoryOSStore,
    *,
    status: str,
    proposal: dict[str, Any],
    owner_id: str,
    channel: str,
    apply: bool,
    ticket_kind: str,
    ops_gate_review: dict[str, Any],
    ticket: dict[str, Any],
) -> dict[str, Any]:
    proposal_id = str(proposal.get("candidate_id") or "")
    return {
        "schema_version": APPROVED_PROPOSAL_EXECUTION_APPLY_SCHEMA_VERSION,
        "profile": store.roots.profile or "default",
        "status": status,
        "dry_run": not apply,
        "owner_id": owner_id,
        "channel": channel,
        "proposal_id": proposal_id,
        "proposal_state": str(proposal.get("state") or ""),
        "proposal_kind": str(proposal.get("kind") or ""),
        "apply_kind": "",
        "ticket_type": ticket_kind,
        "ticket_state": str(ticket.get("ticket_state") or ""),
        "ticket_id": str(ticket.get("ticket_id") or ""),
        "ops_gate_report_id": str(ops_gate_review.get("report_id") or ""),
        "ops_gate_decision": str(ops_gate_review.get("decision") or ""),
        "policy_write_planned": bool(ticket.get("policy_write_planned")),
        "policy_written": bool(ticket.get("policy_written")),
        "policy_version": int(ticket.get("policy_version") or 0),
        "policy_path": str(ticket.get("policy_path") or ""),
        "deep_reflection_policy_apply_id": str(ticket.get("deep_reflection_policy_apply_id") or ""),
        "ticket_write_planned": True,
        "execution_ticket_created": apply,
        "actual_policy_write": bool(ticket.get("actual_policy_write")),
        "actual_execute": False,
        "actual_send": False,
        "raw_body_included": False,
        "suggested_path": _bounded_text(str(ticket.get("suggested_path") or ""), 320),
        "evidence_required": _safe_list(ticket.get("evidence_required")),
        "evidence_refs": _safe_list(ticket.get("evidence_refs")),
        "rollback": _bounded_text(str(ticket.get("rollback") or ""), 320),
        "boundary": _owner_review_false_boundary(),
    }


def _planned_approved_proposal_execution_ticket(
    *,
    proposal: dict[str, Any],
    owner_id: str,
    channel: str,
    ticket_kind: str,
    ops_gate_review: dict[str, Any],
    evidence_refs: list[str],
    evidence_summary: str,
) -> dict[str, Any]:
    return _approved_proposal_execution_ticket_payload(
        proposal=proposal,
        owner_id=owner_id,
        channel=channel,
        ticket_kind=ticket_kind,
        ops_gate_review=ops_gate_review,
        evidence_refs=evidence_refs,
        evidence_summary=evidence_summary,
        ticket_id="",
        created_at="",
    )


def _write_approved_proposal_execution_ticket(
    store: MemoryOSStore,
    *,
    proposal: dict[str, Any],
    owner_id: str,
    channel: str,
    ticket_kind: str,
    ops_gate_review: dict[str, Any],
    evidence_refs: list[str],
    evidence_summary: str,
    ticket_state: str = "",
    supersedes_ticket_id: str = "",
    policy_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    created_at = datetime.now(timezone.utc)
    ticket = _approved_proposal_execution_ticket_payload(
        proposal=proposal,
        owner_id=owner_id,
        channel=channel,
        ticket_kind=ticket_kind,
        ops_gate_review=ops_gate_review,
        evidence_refs=evidence_refs,
        evidence_summary=evidence_summary,
        ticket_state=ticket_state,
        supersedes_ticket_id=supersedes_ticket_id,
        policy_record=policy_record or {},
        ticket_id=f"apxt_{created_at.strftime('%Y%m%dT%H%M%S%fZ')}_{uuid4().hex[:8]}",
        created_at=created_at.isoformat().replace("+00:00", "Z"),
    )
    _append_jsonl(approved_proposal_execution_tickets_path(store.roots), ticket)
    append_audit(
        store.roots.audit_path,
        action="approved_proposal_execution_ticket_created",
        status="ok",
        target=str(proposal.get("candidate_id") or ""),
        details={
            "ticket_id": ticket["ticket_id"],
            "ticket_type": ticket["ticket_type"],
            "ticket_state": ticket["ticket_state"],
            "actual_execute": False,
            "raw_body_included": False,
        },
    )
    return ticket


def _approved_proposal_execution_ticket_payload(
    *,
    proposal: dict[str, Any],
    owner_id: str,
    channel: str,
    ticket_kind: str,
    ops_gate_review: dict[str, Any],
    evidence_refs: list[str],
    evidence_summary: str,
    ticket_id: str,
    created_at: str,
    ticket_state: str = "",
    supersedes_ticket_id: str = "",
    policy_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    proposal_id = str(proposal.get("candidate_id") or "")
    resolved_state = ticket_state
    if not resolved_state:
        resolved_state = "evidence_resolved" if ticket_kind == "validation_evidence" and evidence_refs else "awaiting_typed_execution_plan"
    guidance = _approved_proposal_execution_ticket_guidance(ticket_kind)
    policy_record = policy_record or {}
    return {
        "schema_version": APPROVED_PROPOSAL_EXECUTION_TICKET_SCHEMA_VERSION,
        "ticket_id": ticket_id,
        "supersedes_ticket_id": supersedes_ticket_id,
        "created_at": created_at,
        "owner_id": owner_id,
        "channel": channel,
        "proposal_id": proposal_id,
        "proposal_kind": str(proposal.get("kind") or ""),
        "title": _bounded_text(str(proposal.get("title") or "Approved proposal"), 140),
        "safe_source_ids": _safe_list(proposal.get("source_refs")),
        "ops_gate_report_id": str(ops_gate_review.get("report_id") or ""),
        "ops_gate_decision": str(ops_gate_review.get("decision") or ""),
        "ticket_type": ticket_kind,
        "ticket_state": resolved_state,
        "suggested_path": guidance["suggested_path"],
        "evidence_required": guidance["evidence_required"],
        "evidence_refs": _safe_list(evidence_refs),
        "evidence_summary": _bounded_text(evidence_summary, 320),
        "reversible": True,
        "rollback": guidance["rollback"],
        "policy_write_planned": ticket_kind == "deep_reflection_policy_plan",
        "policy_written": bool(policy_record),
        "policy_version": int(policy_record.get("policy_version") or 0),
        "policy_path": str(policy_record.get("policy_path") or ""),
        "deep_reflection_policy_apply_id": str(policy_record.get("apply_id") or ""),
        "actual_policy_write": bool(policy_record),
        "execution_ticket_created": True,
        "actual_execute": False,
        "actual_send": False,
        "actual_identity_write": False,
        "raw_body_included": False,
        "boundary": _owner_review_false_boundary(),
    }


def _approved_proposal_execution_ticket_guidance(ticket_kind: str) -> dict[str, Any]:
    if ticket_kind == "validation_evidence":
        return {
            "suggested_path": "bind public-checkout, closure, and monitor evidence; close as evidence-resolved without runtime execution",
            "evidence_required": ["fresh_HEAD_archive", "closure_check", "monitor_FAIL_empty"],
            "rollback": "append a superseding ticket if the linked release evidence is invalidated",
        }
    if ticket_kind == "weekly_consolidation_evidence":
        return {
            "suggested_path": "verify the digest/consolidation artifact and source event trace, then resolve by evidence",
            "evidence_required": ["consolidation_artifact_present", "source_event_traceable", "raw_body_not_included"],
            "rollback": "append a superseding ticket if the digest artifact is invalidated",
        }
    if ticket_kind == "deep_reflection_policy_plan":
        return {
            "suggested_path": "decompose into a bounded deep_reflection policy surface before any apply",
            "evidence_required": ["bounded_policy_fields", "no_external_execution", "monitor_actual_execute_false"],
            "rollback": "remove or supersede the proposed deep_reflection policy before enabling any acting surface",
        }
    return {
        "suggested_path": "decompose into a typed adapter or evidence path; do not run a generic executor",
        "evidence_required": ["typed_adapter_defined", "rollback_named", "monitor_actual_execute_false"],
        "rollback": "append a superseding ticket that marks the plan withdrawn or replaced",
    }


def _write_deep_reflection_policy(
    store: MemoryOSStore,
    *,
    proposal: dict[str, Any],
    owner_id: str,
    channel: str,
    ticket: dict[str, Any],
    evidence_refs: list[str],
    evidence_summary: str,
) -> dict[str, Any]:
    path = deep_reflection_policy_path(store.roots)
    previous = _read_json_dict(path)
    previous_version = int(previous.get("policy_version") or 0)
    proposal_id = str(proposal.get("candidate_id") or "")
    proposal_class = _deep_reflection_policy_class(proposal)
    applied_from = [
        str(item)
        for item in (previous.get("applied_from_proposal_ids") if isinstance(previous.get("applied_from_proposal_ids"), list) else [])
        if str(item)
    ]
    if proposal_id and proposal_id not in applied_from:
        applied_from.append(proposal_id)
    policy = {
        "schema_version": "memory-os.deep_reflection_policy.v0",
        "policy_version": previous_version + 1,
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "active": True,
        "advisory_only": True,
        "live_applied": False,
        "automation_allowed": False,
        "applied_from_proposal_ids": applied_from,
        "latest_proposal_id": proposal_id,
        "latest_ticket_id": str(ticket.get("ticket_id") or ""),
        "continuity_behavior": previous.get("continuity_behavior")
        if isinstance(previous.get("continuity_behavior"), dict)
        else _default_deep_reflection_policy_section("continuity_behavior"),
        "ordinary_tone": previous.get("ordinary_tone")
        if isinstance(previous.get("ordinary_tone"), dict)
        else _default_deep_reflection_policy_section("ordinary_tone"),
        "expired_working_handling": {
            "mode": "skip_expired_working_inputs",
            "live_applied": False,
        },
        "boundary": _owner_review_false_boundary(),
        "actual_execute": False,
        "actual_send": False,
        "actual_identity_write": False,
        "raw_body_included": False,
    }
    target_key = "ordinary_tone" if proposal_class == "deep_reflection:ordinary_tone" else "continuity_behavior"
    policy[target_key] = {
        "mode": "bounded_review_only",
        "proposal_class": proposal_class,
        "source_proposal_id": proposal_id,
        "safe_source_ids": _safe_list(proposal.get("source_refs")),
        "evidence_refs": _safe_list(evidence_refs),
        "guidance": _deep_reflection_policy_guidance(proposal_class),
        "live_applied": False,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(policy, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    apply_record = {
        "schema_version": "memory-os.deep_reflection_policy_apply.v0",
        "apply_id": f"drpol_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}_{uuid4().hex[:8]}",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "owner_id": owner_id,
        "channel": channel,
        "proposal_id": proposal_id,
        "proposal_kind": str(proposal.get("kind") or ""),
        "proposal_class": proposal_class,
        "ticket_id": str(ticket.get("ticket_id") or ""),
        "policy_version": int(policy["policy_version"]),
        "policy_path": str(path),
        "previous_policy": previous,
        "evidence_refs": _safe_list(evidence_refs),
        "evidence_summary": _bounded_text(evidence_summary, 320),
        "actual_execute": False,
        "actual_send": False,
        "actual_identity_write": False,
        "raw_body_included": False,
        "boundary": _owner_review_false_boundary(),
    }
    _append_jsonl(deep_reflection_policy_applies_path(store.roots), apply_record)
    append_audit(
        store.roots.audit_path,
        action="deep_reflection_policy_written",
        status="ok",
        target=proposal_id,
        details={
            "apply_id": apply_record["apply_id"],
            "policy_version": apply_record["policy_version"],
            "actual_execute": False,
            "raw_body_included": False,
        },
    )
    return apply_record


def _deep_reflection_policy_class(proposal: dict[str, Any]) -> str:
    text = " ".join([str(proposal.get("title") or ""), str(proposal.get("body") or "")]).lower()
    if any(marker in text for marker in ("tone", "report-like", "too formal", "normal chat", "正常聊天", "像报告")):
        return "deep_reflection:ordinary_tone"
    return "deep_reflection:continuity_behavior"


def _default_deep_reflection_policy_section(kind: str) -> dict[str, Any]:
    return {
        "mode": "report_only",
        "proposal_class": f"deep_reflection:{kind}",
        "source_proposal_id": "",
        "safe_source_ids": [],
        "evidence_refs": [],
        "guidance": [],
        "live_applied": False,
    }


def _deep_reflection_policy_guidance(proposal_class: str) -> list[str]:
    if proposal_class == "deep_reflection:ordinary_tone":
        return [
            "keep ordinary memory conversation tone out of report-like self-evolution phrasing",
            "surface tone changes as bounded review guidance before runtime behavior changes",
        ]
    return [
        "keep continuity behavior changes in bounded review until owner-visible evidence is linked",
        "do not alter deep_reflection runtime selection without a later explicit apply gate",
    ]


def _right_brain_expression_policy_path(store: MemoryOSStore) -> Path:
    return store.roots.hermes_home / "system-modules" / "right_brain_expression_adapter" / "policy.json"


def _right_brain_expression_policy_applies_path(store: MemoryOSStore) -> Path:
    return store.roots.hermes_home / "system-modules" / "right_brain_expression_adapter" / "policy_applies.jsonl"


def _proposal_queue_legacy_template_cleanup_applies_path(store: MemoryOSStore) -> Path:
    return store.roots.hermes_home / "system-modules" / "proposal_queue" / "legacy_template_cleanup_applies.jsonl"


def _approved_proposal_execution_tickets_by_proposal(store: MemoryOSStore) -> dict[str, dict[str, Any]]:
    tickets: dict[str, dict[str, Any]] = {}
    for record in _read_jsonl(approved_proposal_execution_tickets_path(store.roots)):
        proposal_id = str(record.get("proposal_id") or "")
        if proposal_id:
            tickets[proposal_id] = record
    return tickets


def _deep_reflection_policy_applies_by_proposal(store: MemoryOSStore) -> dict[str, dict[str, Any]]:
    applies: dict[str, dict[str, Any]] = {}
    for record in _read_jsonl(deep_reflection_policy_applies_path(store.roots)):
        proposal_id = str(record.get("proposal_id") or "")
        if proposal_id:
            applies[proposal_id] = record
    return applies


def _memory_sources_policy_applies_by_proposal(store: MemoryOSStore) -> dict[str, dict[str, Any]]:
    applies: dict[str, dict[str, Any]] = {}
    for record in _read_jsonl(memory_sources_policy_applies_path(store.roots)):
        proposal_id = str(record.get("proposal_id") or "")
        if proposal_id:
            applies[proposal_id] = record
    return applies


def _policy_applies_by_proposal(store: MemoryOSStore) -> dict[str, dict[str, Any]]:
    applies: dict[str, dict[str, Any]] = {}
    for record in _read_jsonl(_right_brain_expression_policy_applies_path(store)):
        proposal_id = str(record.get("proposal_id") or "")
        if proposal_id:
            applies[proposal_id] = record
    return applies


def _legacy_template_cleanup_applies_by_proposal(store: MemoryOSStore) -> dict[str, dict[str, Any]]:
    applies: dict[str, dict[str, Any]] = {}
    for record in _read_jsonl(_proposal_queue_legacy_template_cleanup_applies_path(store)):
        proposal_id = str(record.get("proposal_id") or "")
        if proposal_id:
            applies[proposal_id] = record
    return applies


def _legacy_template_cleanup_targets(store: MemoryOSStore, *, exclude_proposal_id: str) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    for item in _read_proposal_queue(store):
        candidate_id = str(item.get("candidate_id") or "")
        if not candidate_id or candidate_id == exclude_proposal_id:
            continue
        if not _legacy_template_proposal(item):
            continue
        if _proposal_queue_item_terminal_for_cleanup(item):
            continue
        targets.append(item)
    return targets


def _proposal_queue_item_terminal_for_cleanup(item: dict[str, Any]) -> bool:
    state = str(item.get("state") or "")
    followup_state = str(item.get("followup_state") or "")
    if state in {"owner_declined", "expired", "pressure_blocked"}:
        return True
    return followup_state in {
        "closed",
        "applied_expression_policy",
        "applied_memory_sources_policy",
        "applied_legacy_template_cleanup",
    }


def _legacy_template_proposal(item: dict[str, Any]) -> bool:
    title = str(item.get("title") or "")
    body = " ".join(str(item.get("body") or "").split())
    if "Proposed change:" in body and "Acceptance criteria:" in body:
        return False
    if "具体改动:" in body and "验收标准:" in body:
        return False
    if title == "Self-Evolution dry-run proposal":
        return True
    if title == "Tune right-brain expression policy" and "prompt/cadence/policy proposal" in body:
        return True
    return False


def _memory_sources_policy_from_proposal(
    store: MemoryOSStore,
    *,
    proposal: dict[str, Any],
    owner_id: str,
    channel: str,
    ops_gate_review: dict[str, Any],
) -> dict[str, Any]:
    previous = read_memory_sources_policy(store.roots)
    previous_version = int(previous.get("policy_version") or 0) if previous else 0
    proposal_id = str(proposal.get("candidate_id") or "")
    quality = proposal.get("proposal_quality") if isinstance(proposal.get("proposal_quality"), dict) else {}
    body = str(proposal.get("body") or "")
    title = str(proposal.get("title") or "")
    rating = str(quality.get("feedback_rating") or _memory_sources_policy_rating(title=title, body=body))
    return {
        "schema_version": POLICY_SCHEMA_VERSION,
        "policy_id": f"mspol_{_stable_token(proposal_id, 12)}",
        "policy_version": previous_version + 1,
        "active": True,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "profile": store.roots.profile or "default",
        "owner_id": owner_id,
        "channel": channel,
        "applied_from_proposal_id": proposal_id,
        "proposal_title": _bounded_text(title, 180),
        "proposal_kind": str(proposal.get("kind") or "memory_sources_policy"),
        "proposal_class": str(proposal.get("proposal_class") or ""),
        "runtime_target": "context_retrieval_policy_review",
        "feedback_rating": rating,
        "routes": _safe_list(quality.get("routes"))[:12],
        "query_classes": _safe_list(quality.get("query_classes"))[:12],
        "memory_source_record_refs": _safe_list(quality.get("memory_source_record_refs"))[:12],
        "policy_guidance": _memory_sources_policy_guidance(rating=rating, title=title, body=body),
        "selection_policy_changed": False,
        "ops_gate_report_id": str(ops_gate_review.get("report_id") or ""),
        "ops_gate_decision": str(ops_gate_review.get("decision") or ""),
        "source_refs": _safe_list(proposal.get("source_refs"))[:12],
        "raw_body_included": False,
        "actual_send": False,
        "actual_execute": False,
        "actual_identity_write": False,
        "actual_unapproved_crystallized_approval": False,
    }


def _memory_sources_policy_rating(*, title: str, body: str) -> str:
    text = f"{title}\n{body}".lower()
    for rating in ("missing_context", "needs_specific_recall", "too_mechanistic", "overconfident", "irrelevant"):
        if rating in text:
            return rating
    if "缺" in text:
        return "missing_context"
    return "review_required"


def _memory_sources_policy_guidance(*, rating: str, title: str, body: str) -> list[str]:
    guidance = [
        "MemorySources 只记录和暴露 bounded attribution，不直接改 live route、prompt、send 或 execution。",
        "后续 MemorySources record 必须带 active policy_ref，方便评估该 policy 是否改善上下文质量。",
    ]
    if rating == "missing_context" or "missing_context" in f"{title}\n{body}":
        guidance.append("针对 missing_context：后续评估候选/审批上下文时，优先检查是否缺少关键 source class 或具体 recall anchor。")
    if rating == "needs_specific_recall":
        guidance.append("针对 needs_specific_recall：后续反馈提示应要求 Hermes agent 追问更具体的时间、项目、关键词或来源。")
    if rating == "too_mechanistic":
        guidance.append("针对 too_mechanistic：后续反馈提示应避免系统字段堆砌，要求 Hermes agent 用自然语言解释上下文用途。")
    return guidance[:6]


def _write_memory_sources_policy(
    store: MemoryOSStore,
    *,
    proposal: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    policy_path = memory_sources_policy_path(store.roots)
    previous = read_memory_sources_policy(store.roots)
    apply_id = f"msapply_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}_{uuid4().hex[:8]}"
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    policy_path.write_text(json.dumps(policy, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    record = {
        "schema_version": POLICY_APPLY_SCHEMA_VERSION,
        "apply_id": apply_id,
        "created_at": policy["created_at"],
        "proposal_id": str(proposal.get("candidate_id") or ""),
        "proposal_title": _bounded_text(str(proposal.get("title") or ""), 180),
        "policy_id": policy["policy_id"],
        "policy_version": policy["policy_version"],
        "policy_path": str(policy_path),
        "runtime_target": "context_retrieval_policy_review",
        "previous_policy_digest": _json_digest(previous) if previous else "",
        "previous_policy": previous,
        "selection_policy_changed": False,
        "actual_policy_write": True,
        "actual_execute": False,
        "actual_send": False,
        "raw_body_included": False,
    }
    _append_jsonl(memory_sources_policy_applies_path(store.roots), record)
    append_audit(
        store.roots.audit_path,
        action="memory_sources_policy_applied",
        status="ok",
        target=str(policy_path),
        details={
            "apply_id": apply_id,
            "proposal_id": record["proposal_id"],
            "policy_version": policy["policy_version"],
            "runtime_target": "context_retrieval_policy_review",
            "selection_policy_changed": False,
            "actual_policy_write": True,
            "actual_execute": False,
        },
    )
    return record


def _right_brain_expression_policy_from_proposal(
    store: MemoryOSStore,
    *,
    proposal: dict[str, Any],
    owner_id: str,
    channel: str,
    ops_gate_review: dict[str, Any],
) -> dict[str, Any]:
    previous = _read_json_dict(_right_brain_expression_policy_path(store))
    previous_version = int(previous.get("policy_version") or 0) if previous else 0
    proposal_id = str(proposal.get("candidate_id") or "")
    body = str(proposal.get("body") or "")
    title = str(proposal.get("title") or "")
    tone_guidance = _expression_policy_tone_guidance(title=title, body=body)
    return {
        "schema_version": "memory-os.right_brain_expression_policy.v0",
        "policy_id": f"rbpol_{_stable_token(proposal_id, 12)}",
        "policy_version": previous_version + 1,
        "active": True,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "profile": store.roots.profile or "default",
        "owner_id": owner_id,
        "channel": channel,
        "applied_from_proposal_id": proposal_id,
        "proposal_title": _bounded_text(title, 180),
        "proposal_kind": str(proposal.get("kind") or "expression_policy"),
        "ops_gate_report_id": str(ops_gate_review.get("report_id") or ""),
        "ops_gate_decision": str(ops_gate_review.get("decision") or ""),
        "tone_guidance": tone_guidance,
        "safety_constraints": [
            "不自动发送；表达仍由 Hermes cron/origin 低频投递链路控制。",
            "不自动执行任务、创建计划、改身份或写长期记忆。",
            "上下文不足时优先 [SILENT]，不要用系统报告填充。",
        ],
        "source_refs": _safe_list(proposal.get("source_refs"))[:12],
        "raw_body_included": False,
        "actual_send": False,
        "actual_execute": False,
        "actual_identity_write": False,
        "actual_unapproved_crystallized_approval": False,
    }


def _expression_policy_tone_guidance(*, title: str, body: str) -> list[str]:
    text = f"{title}\n{body}".lower()
    guidance = [
        "少报告腔、少流程腔，优先像 Hermes agent 对 owner 自然说话。",
        "表达要短、轻、非任务化；不要把右脑表达写成议程或总结报告。",
        "保留感受、联想和陪伴感，但不要承诺已经执行或改变系统。",
    ]
    if "too_mechanical" in text or "机械" in text or "报告腔" in text:
        guidance.insert(0, "针对 too_mechanical 反馈：降低机械感，多一点自然陪伴感。")
    if "off_voice" in text or "不像" in text:
        guidance.append("如果表达不像当前 Hermes 声音，宁可保持沉默或重写。")
    if "too_frequent" in text or "频繁" in text:
        guidance.append("如果最近已主动表达过，优先保持沉默，避免刷屏。")
    return guidance[:6]


def _write_right_brain_expression_policy(
    store: MemoryOSStore,
    *,
    proposal: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    policy_path = _right_brain_expression_policy_path(store)
    previous = _read_json_dict(policy_path)
    apply_id = f"rbapply_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}_{uuid4().hex[:8]}"
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    policy_path.write_text(json.dumps(policy, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    record = {
        "schema_version": "memory-os.expression_policy_apply.v0",
        "apply_id": apply_id,
        "created_at": policy["created_at"],
        "proposal_id": str(proposal.get("candidate_id") or ""),
        "proposal_title": _bounded_text(str(proposal.get("title") or ""), 180),
        "policy_id": policy["policy_id"],
        "policy_version": policy["policy_version"],
        "policy_path": str(policy_path),
        "previous_policy_digest": _json_digest(previous) if previous else "",
        "previous_policy": previous,
        "actual_policy_write": True,
        "actual_execute": False,
        "actual_send": False,
        "raw_body_included": False,
    }
    _append_jsonl(_right_brain_expression_policy_applies_path(store), record)
    append_audit(
        store.roots.audit_path,
        action="right_brain_expression_policy_applied",
        status="ok",
        target=str(policy_path),
        details={
            "apply_id": apply_id,
            "proposal_id": record["proposal_id"],
            "policy_version": policy["policy_version"],
            "actual_policy_write": True,
            "actual_execute": False,
        },
    )
    return record


def _write_proposal_queue_legacy_template_cleanup(
    store: MemoryOSStore,
    *,
    proposal: dict[str, Any],
    targets: list[dict[str, Any]],
    owner_id: str,
    channel: str,
    ops_gate_review: dict[str, Any],
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    proposal_id = str(proposal.get("candidate_id") or "")
    target_ids = {str(item.get("candidate_id") or "") for item in targets if str(item.get("candidate_id") or "")}
    apply_id = f"pqclean_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}_{uuid4().hex[:8]}"
    path = _proposal_queue_path(store)
    queue = _read_proposal_queue_document(path)
    closed_ids: list[str] = []
    archived_items: list[dict[str, Any]] = []
    non_legacy_touched_count = 0
    for item in queue.get("items", []):
        if not isinstance(item, dict):
            continue
        candidate_id = str(item.get("candidate_id") or "")
        if candidate_id in target_ids:
            if not _legacy_template_proposal(item) or _proposal_queue_item_terminal_for_cleanup(item):
                non_legacy_touched_count += 1
                continue
            archived_items.append(
                {
                    "candidate_id": candidate_id,
                    "kind": str(item.get("kind") or ""),
                    "title": _bounded_text(str(item.get("title") or ""), 180),
                    "state": str(item.get("state") or ""),
                    "followup_state": str(item.get("followup_state") or ""),
                    "source_refs": _safe_list(item.get("source_refs"))[:12],
                }
            )
            item["state"] = "pressure_blocked"
            item["followup_state"] = "closed"
            item["execution_decision_state"] = "owner_applied_legacy_template_cleanup"
            item["legacy_template_cleanup_apply_id"] = apply_id
            item["actual_execute"] = False
            item["updated_at"] = now
            item.setdefault("reviews", []).append(
                {
                    "reviewer": owner_id,
                    "decision": "apply_legacy_template_cleanup",
                    "note": "Closed by explicit proposal_queue_legacy_template_cleanup apply.",
                    "reviewed_at": now,
                }
            )
            closed_ids.append(candidate_id)
        elif candidate_id == proposal_id:
            item["followup_state"] = "applied_legacy_template_cleanup"
            item["execution_decision_state"] = "owner_applied_legacy_template_cleanup"
            item["legacy_template_cleanup_apply_id"] = apply_id
            item["legacy_template_closed_count"] = len(target_ids)
            item["actual_execute"] = False
            item["updated_at"] = now
    _write_proposal_queue_document(path, queue)
    record = {
        "schema_version": "memory-os.proposal_queue_legacy_template_cleanup_apply.v0",
        "apply_id": apply_id,
        "created_at": now,
        "profile": store.roots.profile or "default",
        "proposal_id": proposal_id,
        "proposal_title": _bounded_text(str(proposal.get("title") or ""), 180),
        "owner_id": owner_id,
        "channel": channel,
        "ops_gate_report_id": str(ops_gate_review.get("report_id") or ""),
        "ops_gate_decision": str(ops_gate_review.get("decision") or ""),
        "matched_count": len(target_ids),
        "closed_count": len(closed_ids),
        "closed_candidate_ids": closed_ids[:100],
        "archived_items": archived_items[:100],
        "non_legacy_touched_count": non_legacy_touched_count,
        "execution_ticket_created": False,
        "actual_execute": False,
        "actual_send": False,
        "raw_body_included": False,
    }
    _append_jsonl(_proposal_queue_legacy_template_cleanup_applies_path(store), record)
    append_audit(
        store.roots.audit_path,
        action="proposal_queue_legacy_template_cleanup_applied",
        status="ok",
        target=str(path),
        details={
            "apply_id": apply_id,
            "proposal_id": proposal_id,
            "closed_count": len(closed_ids),
            "non_legacy_touched_count": non_legacy_touched_count,
            "actual_execute": False,
        },
    )
    return record


def _mark_proposal_policy_applied(
    store: MemoryOSStore,
    *,
    proposal_id: str,
    apply_record: dict[str, Any],
) -> None:
    path = _proposal_queue_path(store)
    queue = _read_proposal_queue_document(path)
    changed = False
    for item in queue.get("items", []):
        if not isinstance(item, dict) or str(item.get("candidate_id") or "") != proposal_id:
            continue
        item["followup_state"] = "applied_expression_policy"
        item["execution_decision_state"] = "owner_applied_expression_policy"
        item["policy_apply_count"] = int(item.get("policy_apply_count") or 0) + 1
        item["policy_apply_id"] = str(apply_record.get("apply_id") or "")
        item["policy_version"] = int(apply_record.get("policy_version") or 0)
        item["policy_path"] = str(apply_record.get("policy_path") or "")
        item["actual_execute"] = False
        item["updated_at"] = str(apply_record.get("created_at") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
        changed = True
        break
    if changed:
        _write_proposal_queue_document(path, queue)


def _mark_proposal_memory_sources_policy_applied(
    store: MemoryOSStore,
    *,
    proposal_id: str,
    apply_record: dict[str, Any],
) -> None:
    path = _proposal_queue_path(store)
    queue = _read_proposal_queue_document(path)
    changed = False
    for item in queue.get("items", []):
        if not isinstance(item, dict) or str(item.get("candidate_id") or "") != proposal_id:
            continue
        item["followup_state"] = "applied_memory_sources_policy"
        item["execution_decision_state"] = "owner_applied_memory_sources_policy"
        item["memory_sources_policy_apply_count"] = int(item.get("memory_sources_policy_apply_count") or 0) + 1
        item["memory_sources_policy_apply_id"] = str(apply_record.get("apply_id") or "")
        item["memory_sources_policy_version"] = int(apply_record.get("policy_version") or 0)
        item["memory_sources_policy_path"] = str(apply_record.get("policy_path") or "")
        item["actual_execute"] = False
        item["updated_at"] = str(apply_record.get("created_at") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
        changed = True
        break
    if changed:
        _write_proposal_queue_document(path, queue)


def _proposal_queue_path(store: MemoryOSStore) -> Path:
    return store.roots.hermes_home / "system-modules" / "proposal_queue" / "queue.json"


def _read_proposal_queue_document(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": "hermes.proposal_queue.v0", "profile": "default", "items": []}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"schema_version": "hermes.proposal_queue.v0", "profile": "default", "items": []}
    if not isinstance(parsed, dict):
        return {"schema_version": "hermes.proposal_queue.v0", "profile": "default", "items": []}
    parsed.setdefault("items", [])
    return parsed


def _write_proposal_queue_document(path: Path, queue: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(queue, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_json_dict(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _stable_token(value: str, length: int) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[: max(int(length), 1)]


def _owner_review_false_boundary() -> dict[str, bool]:
    return {
        "actual_send": False,
        "actual_execute": False,
        "actual_identity_write": False,
        "actual_unapproved_crystallized_approval": False,
    }


def _safe_review_section(section: str) -> str:
    clean = str(section or "all").strip().lower()
    if clean in {"action", "action_required", "required"}:
        return "action_required"
    if clean in {"suggested", "review_suggested", "review"}:
        return "review_suggested"
    if clean in {"fyi", "info"}:
        return "fyi"
    return "all"


def _selected_review_sections(section: str) -> tuple[str, ...]:
    if section in {"action_required", "review_suggested", "fyi"}:
        return (section,)
    return ("action_required", "review_suggested", "fyi")


def _surface_offsets(
    *,
    operation: str,
    section: str,
    explicit_offset: int,
    latest_counts: dict[str, Any],
) -> dict[str, int]:
    sections = _selected_review_sections(section)
    if operation == "next_page":
        return {
            "action_required": int(latest_counts.get("action_required_shown") or 0),
            "review_suggested": int(latest_counts.get("review_suggested_shown") or 0),
            "fyi": int(latest_counts.get("fyi_shown") or 0),
        }
    return {priority: explicit_offset for priority in sections}


def _owner_review_surface_expression_feedback_context(
    store: MemoryOSStore,
    *,
    owner_id: str,
    limit: int,
) -> dict[str, Any]:
    outcomes = [
        record
        for record in _read_jsonl(right_brain_expression_outcomes_path(store.roots))
        if isinstance(record, dict) and str(record.get("outcome_id") or "")
    ]
    feedback_records = [
        record
        for record in _read_jsonl(expression_feedback_ledger_path(store.roots))
        if isinstance(record, dict)
    ]
    if not outcomes:
        return {
            "schema_version": OWNER_REVIEW_SURFACE_SCHEMA_VERSION,
            "profile": store.roots.profile or "default",
            "owner_id": owner_id,
            "status": "empty",
            "operation": "expression_feedback_context",
            "reason": "no_right_brain_expression_outcome",
            "latest_outcome": {},
            "feedback_actions": {},
            "existing_feedback": {"count": 0, "ratings": {}},
            "raw_body_included": False,
            "boundary": _owner_review_false_boundary(),
        }
    latest = outcomes[-1]
    latest_id = str(latest.get("outcome_id") or "")
    item = _right_brain_expression_feedback_item(latest)
    rating_counts = Counter(
        str(record.get("action_type") or record.get("rating") or "")
        for record in feedback_records
        if str(record.get("outcome_id") or "") == latest_id
    )
    action_tokens = item.get("action_tokens") if isinstance(item.get("action_tokens"), dict) else {}
    examples = (
        item.get("owner_utterance_examples") if isinstance(item.get("owner_utterance_examples"), list) else []
    )
    actions: dict[str, dict[str, Any]] = {}
    ordered_feedback_actions = list(EXPRESSION_FEEDBACK_DIGEST_ACTIONS) + [
        action_type
        for action_type in sorted(EXPRESSION_FEEDBACK_ACTION_TYPES)
        if action_type not in EXPRESSION_FEEDBACK_DIGEST_ACTIONS
    ]
    for action_type in ordered_feedback_actions:
        token = str(action_tokens.get(action_type) or "")
        if not token:
            continue
        example = next((str(value) for value in examples if token and token in str(value)), "")
        actions[action_type] = {
            "action": "feedback",
            "rating": action_type,
            "action_token": token,
            "owner_utterance_example": example,
            "owner_utterance_scope": "owner_chat_utterance",
            "agent_tool_call": _owner_review_reply_tool_call(
                action="feedback",
                action_token=token,
                rating=action_type,
            ),
            "target_type": "expression",
            "target_id": latest_id,
        }
    return {
        "schema_version": OWNER_REVIEW_SURFACE_SCHEMA_VERSION,
        "profile": store.roots.profile or "default",
        "owner_id": owner_id,
        "status": "ok",
        "operation": "expression_feedback_context",
        "source": "right_brain_expression_adapter_latest_outcome",
        "latest_outcome": item,
        "feedback_actions": dict(list(actions.items())[: max(min(int(limit or 6), 6), 1)]),
        "existing_feedback": {
            "count": sum(1 for record in feedback_records if str(record.get("outcome_id") or "") == latest_id),
            "ratings": dict(sorted(rating_counts.items())),
        },
        "agent_instruction": (
            "Hermes agent owns the conversation. Ask a natural clarification if the owner feedback is vague; "
            "when intent is clear, call memory_os_review_reply with action=feedback, the matching action_token, "
            "and rating. Do not decide feedback on behalf of the owner."
        ),
        "raw_body_included": False,
        "boundary": _owner_review_false_boundary(),
    }


def _owner_review_surface_memory_sources_feedback_context(
    store: MemoryOSStore,
    *,
    owner_id: str,
    limit: int,
) -> dict[str, Any]:
    records = [
        record
        for record in read_memory_source_records(store.roots, limit=50)
        if isinstance(record, dict) and str(record.get("record_id") or "")
    ]
    feedback_records = read_memory_source_feedback_records(store.roots, limit=1_000_000)
    if not records:
        return {
            "schema_version": OWNER_REVIEW_SURFACE_SCHEMA_VERSION,
            "profile": store.roots.profile or "default",
            "owner_id": owner_id,
            "status": "empty",
            "operation": "memory_sources_feedback_context",
            "reason": "no_memory_sources_record",
            "latest_memory_source": {},
            "feedback_actions": {},
            "existing_feedback": {"count": 0, "ratings": {}},
            "raw_body_included": False,
            "boundary": _owner_review_false_boundary(),
        }
    latest = records[-1]
    latest_id = str(latest.get("record_id") or "")
    item = _memory_source_feedback_item(latest, roots=store.roots)
    token = str((item.get("action_tokens") or {}).get("mark_feedback") or "")
    rating_counts = Counter(
        str(record.get("rating") or "")
        for record in feedback_records
        if isinstance(record, dict) and str(record.get("memory_source_record_id") or "") == latest_id
    )
    ordered_ratings = [
        rating
        for rating in MEMORY_SOURCE_FEEDBACK_CONTEXT_RATINGS
        if rating in ALLOWED_FEEDBACK_RATINGS
    ]
    ordered_ratings.extend(
        rating
        for rating in sorted(ALLOWED_FEEDBACK_RATINGS)
        if rating not in ordered_ratings
    )
    actions: dict[str, dict[str, Any]] = {}
    for rating in ordered_ratings:
        example = _owner_utterance_example(action="feedback", action_token=token, rating=rating)
        actions[rating] = {
            "action": "feedback",
            "rating": rating,
            "action_token": token,
            "owner_utterance_example": example,
            "owner_utterance_scope": "owner_chat_utterance",
            "agent_tool_call": _owner_review_reply_tool_call(
                action="feedback",
                action_token=token,
                rating=rating,
            ),
            "target_type": "memory_source",
            "target_id": latest_id,
        }
    return {
        "schema_version": OWNER_REVIEW_SURFACE_SCHEMA_VERSION,
        "profile": store.roots.profile or "default",
        "owner_id": owner_id,
        "status": "ok",
        "operation": "memory_sources_feedback_context",
        "source": "memory_sources_latest_record",
        "latest_memory_source": item,
        "feedback_actions": dict(list(actions.items())[: max(min(int(limit or 5), len(actions)), 1)]),
        "existing_feedback": {
            "count": sum(
                1
                for record in feedback_records
                if isinstance(record, dict) and str(record.get("memory_source_record_id") or "") == latest_id
            ),
            "ratings": dict(sorted(rating_counts.items())),
        },
        "agent_instruction": (
            "Hermes agent owns the conversation. Ask whether the latest recalled context helped, misled, "
            "felt too mechanical, missed context, or needed a more specific recall. When owner intent is clear, "
            "call memory_os_review_reply with action=feedback, the action_token, and rating. "
            "Do not decide feedback on behalf of the owner."
        ),
        "raw_body_included": False,
        "boundary": _owner_review_false_boundary(),
    }


def _owner_utterance_example(*, action: str, action_token: str, rating: str = "") -> str:
    if action == "feedback":
        return " ".join(part for part in ["memory feedback", str(action_token or ""), str(rating or "")] if part)
    return " ".join(part for part in ["memory", str(action or ""), str(action_token or "")] if part)


def _owner_review_reply_tool_call(*, action: str, action_token: str, rating: str = "") -> dict[str, Any]:
    arguments = {
        "action": str(action or ""),
        "action_token": str(action_token or ""),
    }
    if str(action or "") == "feedback" and rating:
        arguments["rating"] = str(rating or "")
    return {
        "tool_name": "memory_os_review_reply",
        "arguments": arguments,
    }


def _owner_review_surface_detail(
    store: MemoryOSStore,
    *,
    owner_id: str,
    channel: str,
    anchor: str,
    action_token: str,
) -> dict[str, Any]:
    clean_anchor = str(anchor or "").strip().upper()
    clean_token = str(action_token or "").strip().lower()
    if not clean_anchor and not clean_token:
        return _owner_review_surface_needs_clarification(
            store,
            owner_id=owner_id,
            operation="detail",
            reason="missing_anchor_or_action_token",
        )
    rendered, binding = _resolve_reply_digest(
        store,
        owner_id=owner_id,
        channel=channel,
        digest_id="",
        require_recorded_digest=True,
        anchor=clean_anchor,
        action_token=clean_token,
        max_action_required=None,
        max_review_suggested=None,
        max_fyi=None,
    )
    if binding == "digest_not_found":
        return _owner_review_surface_needs_clarification(
            store,
            owner_id=owner_id,
            operation="detail",
            reason="digest_not_found_or_expired",
        )
    item: dict[str, Any] | None = None
    match = ""
    if clean_token:
        match_record = _rendered_action_token_map(rendered).get(clean_token)
        if match_record:
            item = match_record.get("item") if isinstance(match_record.get("item"), dict) else None
            match = "action_token"
    if item is None and clean_anchor:
        item = _rendered_anchor_map(rendered).get(clean_anchor)
        match = "anchor" if item else ""
    if item is None:
        return _owner_review_surface_needs_clarification(
            store,
            owner_id=owner_id,
            operation="detail",
            reason="review_item_not_found_in_latest_digest",
            digest_id=str(rendered.get("digest_id") or ""),
        )
    actions_stale = _owner_review_surface_detail_actions_stale(
        store,
        owner_id=owner_id,
        binding=binding,
        rendered=rendered,
    )
    display_item = _stale_owner_review_surface_item(item) if actions_stale else item
    return {
        "schema_version": OWNER_REVIEW_SURFACE_SCHEMA_VERSION,
        "profile": store.roots.profile or "default",
        "owner_id": owner_id,
        "status": "report_only" if actions_stale else "ok",
        "operation": "detail",
        "binding": binding,
        "match": match,
        "digest_id": str(rendered.get("digest_id") or ""),
        "actions_stale": actions_stale,
        "stale_reason": "detail_from_non_latest_digest" if actions_stale else "",
        "item": display_item,
        "text": "\n".join(_rendered_digest_item_lines(display_item)),
        "agent_instruction": (
            "这条详情来自旧 digest。只能作为只读上下文解释给 owner；如果 owner 要操作，"
            "请先拉取最新 overview/下一页，使用当前 digest 的 action token。"
            if actions_stale
            else "Explain the bounded detail. If the owner chooses an action, call memory_os_review_reply with the stable token."
        ),
        "raw_body_included": False,
        "boundary": _owner_review_false_boundary(),
    }


def _owner_review_surface_detail_actions_stale(
    store: MemoryOSStore,
    *,
    owner_id: str,
    binding: str,
    rendered: dict[str, Any],
) -> bool:
    if binding == "latest_recorded_digest":
        return False
    if binding != "latest_owner_home_digest":
        return True
    latest = _latest_owner_home_digest_record(store.roots, owner_id=owner_id)
    if not latest:
        return True
    latest_digest_id = str(latest.get("digest_id") or "")
    return str(rendered.get("digest_id") or "") != latest_digest_id


def _stale_owner_review_surface_item(item: dict[str, Any]) -> dict[str, Any]:
    safe = dict(item)
    for key in (
        "action_tokens",
        "action_targets",
        "agent_tool_calls",
        "owner_utterance_examples",
        "action_commands",
    ):
        safe.pop(key, None)
    safe["actions_stale"] = True
    safe["stale_reason"] = "detail_from_non_latest_digest"
    safe["suggested_action"] = (
        "这条详情来自旧 digest，只能查看；请先查看最新 overview/下一页，再使用当前 action token 操作。"
    )
    safe["consequence"] = (
        str(safe.get("consequence") or "")
        + " 旧 digest 的 action token 已失效，不能从这条历史详情直接执行。"
    ).strip()
    return safe


def _owner_review_surface_needs_clarification(
    store: MemoryOSStore,
    *,
    owner_id: str,
    operation: str,
    reason: str,
    digest_id: str = "",
) -> dict[str, Any]:
    return {
        "schema_version": OWNER_REVIEW_SURFACE_SCHEMA_VERSION,
        "profile": store.roots.profile or "default",
        "owner_id": owner_id,
        "status": "needs_clarification",
        "operation": operation,
        "reason": reason,
        "digest_id": digest_id,
        "raw_body_included": False,
        "boundary": _owner_review_false_boundary(),
    }


def _closed_targets(actions: list[dict[str, Any]]) -> set[str]:
    closed: set[str] = set()
    for action in actions:
        if action.get("result") not in {"applied", "duplicate_ignored"}:
            continue
        target_type = str(action.get("target_type", ""))
        action_type = str(action.get("action_type", ""))
        if action_type not in TERMINAL_ACTIONS_BY_TARGET_TYPE.get(target_type, set()):
            continue
        closed.add(f"{target_type}:{action.get('target_id', '')}")
    return closed


def _normalize_target(action_type: str, target: str) -> tuple[str, str]:
    value = str(target or "").strip()
    if ":" in value:
        prefix, suffix = value.split(":", 1)
        normalized_prefix = {
            "candidate": "candidate",
            "cand": "candidate",
            "candidate_cluster": "candidate_cluster",
            "candidate-cluster": "candidate_cluster",
            "ccluster": "candidate_cluster",
            "proposal": "proposal",
            "prop": "proposal",
            "crystallized": "crystallized_record",
            "crystallized_record": "crystallized_record",
            "crystallized-record": "crystallized_record",
            "cmem": "crystallized_record",
            "memory_source": "memory_source",
            "memory-source": "memory_source",
            "msrc": "memory_source",
            "speak": "speak",
            "session_mirror_apply": "session_mirror_apply",
            "session-mirror-apply": "session_mirror_apply",
            "smap": "session_mirror_apply",
            "hindsight_curation": "hindsight_curation",
            "hindsight-curation": "hindsight_curation",
            "hcur": "hindsight_curation",
            "pcrystal": "provisional_crystallized_record",
            "provisional-crystallized": "provisional_crystallized_record",
            "provisional_crystallized_record": "provisional_crystallized_record",
        }.get(prefix.strip(), prefix.strip())
        return normalized_prefix, suffix.strip()
    if action_type in {"approve_candidate", "reject_candidate", "approve_external_evidence"}:
        return "candidate", value
    if action_type in {"approve_candidate_cluster", "reject_candidate_cluster", "defer_candidate_cluster"}:
        return "candidate_cluster", value
    if action_type in {"revoke_crystallized", "demote_crystallized"}:
        return "crystallized_record", value
    if action_type in {"approve_proposal", "reject_proposal"}:
        return "proposal", value
    if action_type == "apply_proposal":
        return "proposal", value
    if action_type == "mark_feedback":
        return "memory_source", value
    if action_type == "allow_speak_once":
        return "speak", value
    if action_type == "approve_session_mirror_apply":
        return "session_mirror_apply", value
    if action_type in HINDSIGHT_CURATION_ACTION_TYPES:
        return "hindsight_curation", value
    if action_type in EXPRESSION_FEEDBACK_ACTION_TYPES:
        return "expression", value
    if action_type in {"confirm_provisional_crystallized_record", "reject_provisional_crystallized_record"}:
        return "provisional_crystallized_record", value
    return "unknown", value


def _idempotency_key(*, owner_id: str, target_type: str, target_id: str, action_type: str) -> str:
    return "|".join([str(owner_id), str(target_type), str(target_id), str(action_type)])


def _idempotency_action_type(action_type: str, *, rating: str = "") -> str:
    if action_type == "mark_feedback":
        clean_rating = str(rating or "").strip().lower()
        if clean_rating:
            return f"mark_feedback:{clean_rating}"
    return action_type


def _find_idempotent_action(roots: MemoryOSRoots, idempotency_key: str) -> dict[str, Any] | None:
    for record in read_owner_action_records(roots):
        if record.get("idempotency_key") == idempotency_key and record.get("result") == "applied":
            return record
    return None


def _find_delivery_by_key(roots: MemoryOSRoots, delivery_key: str) -> dict[str, Any] | None:
    for record in read_owner_review_delivery_records(roots):
        if record.get("delivery_key") == delivery_key:
            return record
    return None


def _find_hindsight_curation_finding(store: MemoryOSStore, target_id: str) -> dict[str, Any] | None:
    from .left_brain_advisor import read_left_brain_advisor_reports

    clean = str(target_id or "")
    if not clean:
        return None
    for report in reversed(read_left_brain_advisor_reports(store.roots, limit=50)):
        findings = report.get("findings") if isinstance(report.get("findings"), list) else []
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            if str(finding.get("finding_id") or finding.get("target_id") or "") != clean:
                continue
            if str(finding.get("target_type") or "") != "hindsight_curation":
                continue
            if str(finding.get("source_key") or "") not in {"hindsight_provider_stats", "hindsight_governance_signals"}:
                continue
            return finding
    return None


def _read_hermes_cron_jobs(hermes_home: Path) -> list[dict[str, Any]]:
    path = hermes_home / "cron" / "jobs.json"
    if not path.exists():
        return []
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(loaded, list):
        jobs = loaded
    elif isinstance(loaded, dict):
        jobs = loaded.get("jobs", [])
    else:
        jobs = []
    return [dict(item) for item in jobs if isinstance(item, dict)]


def _find_owner_review_cron_job(
    jobs: list[dict[str, Any]],
    *,
    job_name: str,
    helper_name: str,
) -> dict[str, Any] | None:
    for job in jobs:
        name = str(job.get("name") or "")
        script = str(job.get("script") or "")
        if name == job_name or script.endswith(helper_name):
            return job
    return None


def _cron_schedule_display(job: dict[str, Any]) -> str:
    schedule = job.get("schedule")
    if isinstance(schedule, dict):
        return str(schedule.get("display") or schedule.get("expr") or "")
    return str(schedule or "")


def _delivery_target_class(target: str) -> str:
    value = str(target or "").strip()
    if not value:
        return "missing"
    if value == "origin":
        return "origin"
    if value == "local":
        return "local"
    if ":" in value:
        return "explicit_target"
    return "platform_home"


def _owner_review_finding(code: str, severity: str) -> dict[str, str]:
    return {"code": code, "severity": severity}


def _apply_review_aging(store: MemoryOSStore, items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    config = load_config(store.roots.hermes_home).get("owner_review", {})
    if not isinstance(config, dict):
        config = {}
    enabled = bool(config.get("aging_enabled", True))
    action_days = _positive_limit(None, config.get("aging_action_required_days"), 7)
    fyi_days = _positive_limit(None, config.get("aging_fyi_days"), 30)
    if fyi_days < action_days:
        fyi_days = action_days
    now = datetime.now(timezone.utc)
    aged_items: list[dict[str, Any]] = []
    for item in items:
        source_priority = str(item.get("source_priority") or item.get("priority") or "review_suggested")
        effective_priority = source_priority
        reason = "not_action_required"
        age_days = _review_item_age_days(item, now=now)
        if not enabled:
            reason = "aging_disabled"
        elif source_priority == "action_required":
            if age_days is None:
                effective_priority = "review_suggested"
                reason = "unknown_timestamp"
            elif age_days > fyi_days:
                effective_priority = "fyi"
                reason = f"older_than_{fyi_days}_days"
            elif age_days > action_days:
                effective_priority = "review_suggested"
                reason = f"older_than_{action_days}_days"
            else:
                reason = "recent_action_required"
        aged = dict(item)
        aged["source_priority"] = source_priority
        aged["effective_priority"] = effective_priority
        aged["priority"] = effective_priority
        aged["aging_reason"] = reason
        aged["age_days"] = age_days
        aged_items.append(aged)
    return aged_items, {
        "enabled": enabled,
        "action_required_days": action_days,
        "fyi_days": fyi_days,
        "now": now.isoformat().replace("+00:00", "Z"),
    }


def _review_item_age_days(item: dict[str, Any], *, now: datetime) -> int | None:
    created_at = _parse_dt(str(item.get("created_at") or ""))
    if not created_at:
        return None
    delta = now - created_at
    return max(int(delta.total_seconds() // 86400), 0)


def _review_aging_summary(items: list[dict[str, Any]], aging: dict[str, Any]) -> dict[str, Any]:
    raw_counts = Counter(str(item.get("source_priority") or item.get("priority") or "") for item in items)
    effective_counts = Counter(str(item.get("effective_priority") or item.get("priority") or "") for item in items)
    unknown_timestamp_count = sum(
        1 for item in items if item.get("source_priority") == "action_required" and item.get("age_days") is None
    )
    unknown_timestamp_by_item_type = Counter(
        str(item.get("target_type") or "unknown")
        for item in items
        if item.get("source_priority") == "action_required" and item.get("age_days") is None
    )
    known_created_at_count = sum(1 for item in items if _parse_dt(str(item.get("created_at") or "")))
    created_at_source_distribution = Counter(_created_at_source(item) for item in items)
    created_at_source_by_item_type: dict[str, Counter[str]] = {}
    for item in items:
        item_type = str(item.get("target_type") or "unknown")
        created_at_source_by_item_type.setdefault(item_type, Counter())[_created_at_source(item)] += 1
    true_aged_count = sum(1 for item in items if str(item.get("aging_reason") or "").startswith("older_than_"))
    unknown_aged_count = sum(1 for item in items if item.get("aging_reason") == "unknown_timestamp")
    action_required_ages = [
        int(item["age_days"])
        for item in items
        if item.get("effective_priority") == "action_required" and isinstance(item.get("age_days"), int)
    ]
    informational_retention_days = int(aging.get("fyi_days") or 0)
    stale_review_suggested_count = sum(
        1
        for item in items
        if item.get("source_priority") == "review_suggested"
        and isinstance(item.get("age_days"), int)
        and int(item.get("age_days") or 0) > informational_retention_days
    )
    stale_fyi_count = sum(
        1
        for item in items
        if item.get("source_priority") == "fyi"
        and isinstance(item.get("age_days"), int)
        and int(item.get("age_days") or 0) > informational_retention_days
    )
    return {
        "schema_version": OWNER_REVIEW_AGING_SCHEMA_VERSION,
        "enabled": bool(aging.get("enabled")),
        "action_required_days": int(aging.get("action_required_days") or 0),
        "fyi_days": int(aging.get("fyi_days") or 0),
        "informational_retention_days": informational_retention_days,
        "raw_action_required_count": int(raw_counts.get("action_required", 0)),
        "effective_action_required_count": int(effective_counts.get("action_required", 0)),
        "raw_review_suggested_count": int(raw_counts.get("review_suggested", 0)),
        "effective_review_suggested_count": int(effective_counts.get("review_suggested", 0)),
        "raw_fyi_count": int(raw_counts.get("fyi", 0)),
        "effective_fyi_count": int(effective_counts.get("fyi", 0)),
        "aged_to_review_suggested_count": sum(
            1
            for item in items
            if item.get("source_priority") == "action_required"
            and item.get("effective_priority") == "review_suggested"
        ),
        "aged_to_fyi_count": sum(
            1 for item in items if item.get("source_priority") == "action_required" and item.get("effective_priority") == "fyi"
        ),
        "unknown_timestamp_count": unknown_timestamp_count,
        "unknown_timestamp_by_item_type": dict(unknown_timestamp_by_item_type),
        "stale_informational_count": stale_review_suggested_count + stale_fyi_count,
        "stale_review_suggested_count": stale_review_suggested_count,
        "stale_fyi_count": stale_fyi_count,
        "created_at_coverage_ratio": round(known_created_at_count / len(items), 3) if items else 1.0,
        "created_at_source_distribution": dict(created_at_source_distribution),
        "created_at_source_by_item_type": {
            item_type: dict(counter) for item_type, counter in created_at_source_by_item_type.items()
        },
        "true_aged_count": true_aged_count,
        "unknown_aged_count": unknown_aged_count,
        "oldest_action_required_age_days": max(action_required_ages) if action_required_ages else None,
        "raw_body_included": False,
        "canonical_state_changed": False,
        "owner_action_created": False,
    }


def _created_at_source(item: dict[str, Any]) -> str:
    source = str(item.get("created_at_source") or "")
    if source:
        return source
    if _parse_dt(str(item.get("created_at") or "")):
        return "producer"
    return "missing"


def _with_anchors(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counters: Counter[str] = Counter()
    prefixes = {"action_required": "A", "review_suggested": "R", "fyi": "F"}
    result: list[dict[str, Any]] = []
    for item in items:
        priority = str(item.get("priority", "review_suggested"))
        counters[priority] += 1
        anchored = dict(item)
        anchored["anchor"] = f"{prefixes.get(priority, 'R')}{counters[priority]}"
        result.append(anchored)
    return result


def _priority_sort_key(priority: str) -> int:
    return {"action_required": 0, "review_suggested": 1, "fyi": 2}.get(priority, 9)


def _feedback_by_rating(actions: list[dict[str, Any]]) -> dict[str, int]:
    counter = Counter(
        str(record.get("rating", ""))
        for record in actions
        if record.get("action_type") == "mark_feedback" and str(record.get("rating", ""))
    )
    return dict(sorted(counter.items()))


def _owner_active_period(actions: list[dict[str, Any]]) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    for record in actions:
        created_at = _parse_dt(str(record.get("created_at", "")))
        if created_at and created_at >= cutoff and record.get("result") == "applied":
            return True
    return False


def _records_since(records: list[dict[str, Any]], *, hours: int) -> list[dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(int(hours), 0))
    return [record for record in records if (_parse_dt(str(record.get("created_at", ""))) or cutoff) >= cutoff]


def _parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    append_jsonl_locked(path, record, durable=True)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _safe_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _candidate_needs_consolidation(value: str) -> bool:
    text = " ".join(str(value or "").split())
    if _contains_transcript_marker(text):
        return True
    if "evt_" in text and len(text) > 120:
        return True
    if len(text) > 240 and ("|" in text or "：" in text):
        return True
    return False


def _bounded_text(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)].rstrip() + "…"
