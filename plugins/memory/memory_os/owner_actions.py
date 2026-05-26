"""Owner review and action state machine for Memory-OS."""

from __future__ import annotations

import json
import sqlite3
import hashlib
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .approval import ApprovalDecision, ApprovalPurpose
from .audit import append_audit
from .config import load_config
from .crystallized import CrystallizedCandidate, CrystallizedMemoryService, read_candidate_queue
from .memory_sources import (
    ALLOWED_FEEDBACK_RATINGS,
    append_memory_source_feedback_record,
    memory_sources_feedback_path,
    read_memory_source_records,
)
from .roots import MemoryOSRoots
from .store import MemoryOSStore


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
APPROVED_PROPOSAL_OPS_GATE_SCHEMA_VERSION = "memory-os.approved_proposal_ops_gate.v0"
OWNER_ACTION_RESULT_SCHEMA_VERSION = "memory-os.owner_action_result.v0"
SPEAK_PERMISSION_SCHEMA_VERSION = "memory-os.speak_permission_ticket.v0"
OWNER_REVIEW_TEXT_LIMIT = 2400

ACTION_TYPES = {
    "approve_candidate",
    "reject_candidate",
    "mark_feedback",
    "approve_proposal",
    "reject_proposal",
    "allow_speak_once",
}

TERMINAL_ACTIONS_BY_TARGET_TYPE = {
    "candidate": {"approve_candidate", "reject_candidate"},
    "proposal": {"approve_proposal", "reject_proposal"},
    "memory_source": {"mark_feedback"},
    "speak": {"allow_speak_once"},
}


def owner_actions_path(roots: MemoryOSRoots) -> Path:
    return roots.memory_os_root / "system" / "owner_actions.jsonl"


def feedback_ledger_path(roots: MemoryOSRoots) -> Path:
    return roots.memory_os_root / "system" / "feedback_ledger.jsonl"


def crystallization_approvals_path(roots: MemoryOSRoots) -> Path:
    return roots.memory_os_root / "system" / "crystallization_approvals.jsonl"


def proposal_action_ledger_path(roots: MemoryOSRoots) -> Path:
    return roots.memory_os_root / "system" / "proposal_action_ledger.jsonl"


def speak_permission_tickets_path(roots: MemoryOSRoots) -> Path:
    return roots.memory_os_root / "system" / "speak_permission_tickets.jsonl"


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
            "unapproved_crystallized_write_count": unapproved_crystallized_write_count,
        },
        "candidate_approved_count": int(by_type.get("approve_candidate", 0)),
        "candidate_rejected_count": int(by_type.get("reject_candidate", 0)),
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
        "digest_burden": {
            "owner_active_period": owner_active_period,
            "action_required_per_digest": None,
            "owner_response_latency_hours": None,
            "action_completion_rate": None if not owner_active_period else 0.0,
        },
        "feedback_backflow": {
            "by_action_type": dict(sorted(by_type.items())),
            "by_route": {},
            "by_source_class": {},
            "apply_ready_count": 0,
        },
        "approved_proposal_followups": _approved_proposal_followups_summary(store),
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
    items: list[dict[str, Any]] = []
    for proposal in proposals:
        proposal_id = str(proposal.get("candidate_id") or "")
        if not proposal_id:
            continue
        approval = approvals.get(proposal_id, {})
        ops_gate_review = ops_gate_reviews.get(proposal_id, {})
        followup_state = (
            "ops_gate_reviewed_awaiting_explicit_execution"
            if ops_gate_review
            else "awaiting_ops_gate_review"
        )
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
                "safe_source_ids": _safe_list(proposal.get("source_refs")),
                "next_step": "inspect or route through OpsGate; actual execution requires a separate explicit apply command",
                "execution_ticket_created": False,
                "actual_execute": False,
                "raw_body_included": False,
            }
        )
    items = sorted(items, key=lambda item: (str(item.get("approved_at") or ""), str(item.get("proposal_id") or "")), reverse=True)
    bounded_limit = max(int(limit), 0)
    shown = items[:bounded_limit]
    return {
        "schema_version": APPROVED_PROPOSAL_FOLLOWUPS_SCHEMA_VERSION,
        "profile": store.roots.profile or "default",
        "status": "ok",
        "pending_followup_count": len(items),
        "shown_count": len(shown),
        "overflow_count": max(len(items) - bounded_limit, 0),
        "awaiting_ops_gate_count": sum(1 for item in items if item.get("followup_state") == "awaiting_ops_gate_review"),
        "ops_gate_reviewed_count": sum(
            1 for item in items if item.get("followup_state") == "ops_gate_reviewed_awaiting_explicit_execution"
        ),
        "execution_ticket_count": 0,
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
        "pending_followup_count": report["pending_followup_count"],
        "shown_count": report["shown_count"],
        "overflow_count": report["overflow_count"],
        "awaiting_ops_gate_count": report["awaiting_ops_gate_count"],
        "ops_gate_reviewed_count": report["ops_gate_reviewed_count"],
        "execution_ticket_count": report["execution_ticket_count"],
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
    if safe_operation not in {"overview", "page", "next_page", "detail", "proposal_followups"}:
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
    items = _candidate_review_items(store, closed)
    items.extend(_proposal_review_items(store, closed))
    items.extend(_speak_review_items(store, closed))
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
) -> dict[str, Any]:
    config = load_config(store.roots.hermes_home).get("owner_review", {})
    if not isinstance(config, dict):
        config = {}
    resolved_owner = str(owner_id or config.get("owner_id") or "owner")
    action_limit = _positive_limit(max_action_required, config.get("max_action_required"), 3)
    suggested_limit = _positive_limit(max_review_suggested, config.get("max_review_suggested"), 2)
    fyi_limit = _positive_limit(max_fyi, config.get("max_fyi"), 2)
    queue = owner_review_queue_report(store, limit=1000)
    status = owner_review_status_report(store)
    channel = resolve_owner_review_channel(store, owner_id=resolved_owner)
    action_items = _digest_items(queue.get("items") or [], "action_required", action_limit)
    suggested_items = _digest_items(queue.get("items") or [], "review_suggested", suggested_limit)
    queue_fyi_items = _digest_items(queue.get("items") or [], "fyi", fyi_limit)
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
    fyi_total = int(queue.get("fyi_count") or 0) + len(memory_fyi_items) + 2
    digest_id = _digest_id()
    preview = {
        "schema_version": OWNER_REVIEW_DIGEST_PREVIEW_SCHEMA_VERSION,
        "digest_id": digest_id,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "profile": store.roots.profile or "default",
        "owner_id": resolved_owner,
        "status": "ok",
        "mode": "preview",
        "will_send": False,
        "delivery_skipped": True,
        "actions_enabled": False,
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
        },
        "review_aging": queue.get("review_aging") if isinstance(queue.get("review_aging"), dict) else {},
        "overflow": {
            "action_required": max(int(queue.get("action_required_count") or 0) - len(action_items), 0),
            "review_suggested": max(int(queue.get("review_suggested_count") or 0) - len(suggested_items), 0),
            "fyi": max(fyi_total - len(fyi_items), 0),
        },
        "sections": {
            "action_required": action_items,
            "review_suggested": suggested_items,
            "fyi": fyi_items,
        },
        "text_preview": _digest_text_preview(action_items, suggested_items, fyi_items),
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
    record_active: bool = False,
) -> dict[str, Any]:
    preview = owner_review_digest_preview(
        store,
        owner_id=owner_id,
        max_action_required=max_action_required,
        max_review_suggested=max_review_suggested,
        max_fyi=max_fyi,
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
        "will_send": False,
        "delivery_skipped": True,
        "actions_enabled": False,
        "raw_body_included": False,
        "delivery_binding": _owner_review_delivery_binding(store, channel),
        "review_channel": preview.get("review_channel"),
        "limits": preview.get("limits"),
        "counts": preview.get("counts"),
        "review_aging": preview.get("review_aging"),
        "overflow": preview.get("overflow"),
        "sections": rendered_sections,
        "text": _rendered_digest_text(rendered_sections, counts=preview.get("counts"), overflow=preview.get("overflow")),
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
    target_type = str(item.get("target_type") or "")
    target_id = str(item.get("target_id") or "")
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
    action_result = apply_owner_action(
        store,
        action_type=action_type,
        target=f"{target_type}:{target_id}",
        owner_id=owner_id,
        channel=channel,
        note=f"owner command: {action_token or anchor}",
        rating=str(parsed.get("rating") or ""),
        apply=apply,
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
    blocked_reasons: list[str] = []
    if not delivery_enabled:
        blocked_reasons.append("delivery_not_enabled")
    if delivery_adapter in {"", "none", "disabled"}:
        blocked_reasons.append("delivery_adapter_not_configured")
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
    record["result"] = "smoke_only"
    record["blocked_reasons"] = ["legacy_smoke_only_use_hermes_cron"]
    status = "smoke_only"
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
    items = _candidate_review_items(store, closed)
    items.extend(_proposal_review_items(store, closed))
    items.extend(_speak_review_items(store, closed))
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
) -> dict[str, Any]:
    if action_type not in ACTION_TYPES:
        return _action_error(store, action_type, target, owner_id, channel, "invalid_action_type", apply=apply)
    target_type, target_id = _normalize_target(action_type, target)
    idempotency_key = _idempotency_key(
        owner_id=owner_id,
        target_type=target_type,
        target_id=target_id,
        action_type=action_type,
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
    if recurring_enabled and recurring_mode == "hermes_cron" and recurring_channel == safe_channel:
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
        "target_type": str(item.get("target_type") or ""),
        "target_id": str(item.get("target_id") or ""),
        "source_module": str(item.get("source_module") or ""),
        "section": str(item.get("section") or ""),
        "question": _bounded_text(str(item.get("question") or ""), 220),
        "suggested_action": _bounded_text(str(item.get("suggested_action") or ""), 220),
        "reason": _bounded_text(str(item.get("reason") or ""), 240),
        "consequence": _bounded_text(str(item.get("consequence") or ""), 240),
        "proposed_memory_text": _bounded_text(str(item.get("proposed_memory_text") or ""), 360),
        "available_actions": [str(action) for action in item.get("available_actions") or []][:8],
        "action_tokens": {
            str(key): str(value)
            for key, value in (item.get("action_tokens") if isinstance(item.get("action_tokens"), dict) else {}).items()
        },
        "action_commands": [str(command) for command in item.get("action_commands") or []][:8],
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
    if action_type == "mark_feedback":
        feedback = _append_feedback(store, record, rating=rating, note=note)
        return {"feedback_id": feedback["feedback_id"], "memory_source_record_id": target_id}
    if action_type == "allow_speak_once":
        ticket = _append_speak_ticket(store, record)
        return {"ticket_id": ticket["ticket_id"], "target_id": target_id}
    return {}


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
    if action_type in {"approve_proposal", "reject_proposal"}:
        proposal = _find_proposal(store, target_id)
        if not proposal:
            return "proposal_not_found"
        if str(proposal.get("state", "")) not in {"candidate", "owner_eligible", "owner_defer"}:
            return "proposal_not_pending"
    if action_type == "mark_feedback":
        if rating not in ALLOWED_FEEDBACK_RATINGS:
            return "invalid_feedback_rating"
        if not _find_memory_source(store, target_id):
            return "memory_source_not_found"
    if action_type == "allow_speak_once" and target_type != "speak":
        return "invalid_speak_target"
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
    ticket = {
        "schema_version": SPEAK_PERMISSION_SCHEMA_VERSION,
        "ticket_id": f"spt_{created_at.strftime('%Y%m%dT%H%M%S%fZ')}_{uuid4().hex[:8]}",
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
        "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
        "profile": store.roots.profile or "default",
        "owner_action_id": record["owner_action_id"],
        "payload_ref": str(record["target_id"]),
        "status": "pending",
        "actual_send": False,
    }
    _append_jsonl(speak_permission_tickets_path(store.roots), ticket)
    return ticket


def _append_action_specific_ledger(store: MemoryOSStore, record: dict[str, Any]) -> None:
    action_type = str(record.get("action_type", ""))
    if action_type in {"approve_candidate", "reject_candidate"}:
        _append_jsonl(crystallization_approvals_path(store.roots), record)
    elif action_type in {"approve_proposal", "reject_proposal"}:
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
        "boundary": record.get("boundary") if isinstance(record.get("boundary"), dict) else {},
        "owner_effect": record.get("owner_effect") if isinstance(record.get("owner_effect"), dict) else {},
    }


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


def _candidate_review_items(store: MemoryOSStore, closed: set[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for candidate in read_candidate_queue(store.roots):
        target_ref = f"candidate:{candidate.candidate_id}"
        if target_ref in closed:
            continue
        needs_consolidation = _candidate_needs_consolidation(candidate.body)
        items.append(
            {
                "schema_version": "memory-os.review_item.v0",
                "review_item_id": f"review:{target_ref}",
                "target_type": "candidate_cleanup" if needs_consolidation else "candidate",
                "target_id": candidate.candidate_id,
                "source_module": "crystallized_candidates",
                "priority": "fyi" if needs_consolidation else "action_required",
                "created_at": "",
                "status": "pending",
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


def _proposal_review_items(store: MemoryOSStore, closed: set[str]) -> list[dict[str, Any]]:
    proposals = _read_proposal_queue(store)
    items: list[dict[str, Any]] = []
    for proposal in proposals:
        proposal_id = str(proposal.get("candidate_id", ""))
        if not proposal_id or f"proposal:{proposal_id}" in closed:
            continue
        state = str(proposal.get("state", ""))
        if state not in {"candidate", "owner_eligible", "owner_defer"}:
            continue
        items.append(
            {
                "schema_version": "memory-os.review_item.v0",
                "review_item_id": f"review:proposal:{proposal_id}",
                "target_type": "proposal",
                "target_id": proposal_id,
                "source_module": "proposal_queue",
                "priority": "action_required",
                "created_at": str(proposal.get("created_at") or proposal.get("updated_at") or ""),
                "status": "pending",
                "summary": _bounded_text(str(proposal.get("title") or "Proposal candidate"), 160),
                "safe_source_ids": _safe_list(proposal.get("source_refs")),
                "raw_body_included": False,
            }
        )
    return items


def _speak_review_items(store: MemoryOSStore, closed: set[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for module_name in ("wandering_mind", "speak_gate"):
        path = store.roots.hermes_home / "system-modules" / module_name / "would_send.jsonl"
        for record in _read_jsonl(path):
            target_id = str(record.get("id") or record.get("payload_ref") or "")
            if not target_id or f"speak:{target_id}" in closed:
                continue
            items.append(
                {
                    "schema_version": "memory-os.review_item.v0",
                    "review_item_id": f"review:speak:{target_id}",
                    "target_type": "speak",
                    "target_id": target_id,
                    "source_module": module_name,
                    "priority": "review_suggested",
                    "created_at": str(record.get("created_at") or record.get("ts") or ""),
                    "status": "pending",
                    "summary": f"{module_name} would-send artifact; payload_ref={record.get('payload_ref', '')}",
                    "safe_source_ids": [],
                    "raw_body_included": False,
                }
            )
    return items


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
    selected: list[dict[str, Any]] = []
    for item in items:
        if item.get("priority") != priority:
            continue
        selected.append(_digest_item(item))
        if len(selected) >= limit:
            break
    return selected


def _digest_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "anchor": item.get("anchor"),
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
        "safe_source_ids": item.get("safe_source_ids") or [],
        "raw_body_included": False,
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
    actions = _review_actions(target_type, target_id)
    question = _review_question(target_type, item)
    suggested_action = _review_suggested_action(actions, target_type)
    return {
        "anchor": anchor,
        "target_type": target_type,
        "target_id": target_id,
        "source_module": source_module,
        "section": section,
        "question": question,
        "suggested_action": suggested_action,
        "reason": _review_reason(target_type, item),
        "consequence": _review_consequence(target_type),
        "proposed_memory_text": _bounded_text(str(item.get("proposed_memory_text") or ""), 360)
        if target_type == "candidate"
        else "",
        "available_actions": [action["command"] for action in actions],
        "action_tokens": {action["action_type"]: action["token"] for action in actions},
        "action_commands": [action["command"] for action in actions],
        "safe_source_ids": item.get("safe_source_ids") or [],
        "raw_body_included": False,
    }


def _review_question(target_type: str, item: dict[str, Any]) -> str:
    if target_type == "candidate":
        proposed = _bounded_text(str(item.get("proposed_memory_text") or item.get("summary") or ""), 160)
        if proposed:
            return f"这条候选记忆要批准为长期记忆吗？{proposed}"
        return "这条候选记忆要批准为长期记忆吗？"
    if target_type == "candidate_cleanup":
        return "这条候选记忆还像原始对话片段，批准前需要先整理。"
    if target_type == "proposal":
        summary = str(item.get("summary") or "this proposal")
        return _bounded_text(f"这个 proposal 要进入人工后续处理吗？{summary}", 180)
    if target_type == "memory_source":
        return "这次注入的记忆/上下文对回答有帮助吗？"
    if target_type == "speak":
        return "这条例外主动发言内容要给一次性临时许可吗？"
    return "请看一下这条 Memory-OS 状态信号。"


def _review_suggested_action(actions: list[dict[str, str]], target_type: str) -> str:
    commands = [action["command"] for action in actions]
    if target_type in {"candidate", "proposal"} and len(commands) >= 2:
        return f"{commands[0]} or {commands[1]}"
    if target_type == "memory_source" and commands:
        return commands[0]
    if target_type == "speak" and commands:
        return f"{commands[0]}，只在你接受这次例外主动发言时使用"
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
    if target_type == "candidate_cleanup":
        source_count = len(item.get("safe_source_ids") or [])
        return _bounded_text(
            f"{source_module} 从 {source_count} 个安全引用里提出了候选，但它仍像原始对话/事件摘录，不像稳定记忆。",
            220,
        )
    if target_type == "proposal":
        summary = str(item.get("summary") or "proposal candidate")
        return _bounded_text(f"{source_module} 排入了这个 proposal：{summary}。", 220)
    if target_type == "memory_source":
        route = str(item.get("route") or "unknown")
        query_class = str(item.get("query_class") or "unknown")
        return _bounded_text(
            f"{source_module} 记录了上下文归因：route={route} / query={query_class}。",
            220,
        )
    if target_type == "speak":
        return _bounded_text(f"{source_module} 产生了一条 would-send 主动发言草案。", 220)
    return _bounded_text(str(item.get("summary") or "只是状态趋势。"), 220)


def _review_consequence(target_type: str) -> str:
    if target_type == "candidate":
        return "批准会写入一条 owner-approved crystallized memory；拒绝会保留审计证据并关闭该项。"
    if target_type == "candidate_cleanup":
        return "不会写入长期记忆；该项会留在 review backlog，直到整理或显式清理处理。"
    if target_type == "proposal":
        return "批准只表示允许进入人工 follow-up；不会执行任何工作。拒绝会降权/关闭该 proposal。"
    if target_type == "memory_source":
        return "反馈先作为证据入 ledger；不会直接改变 live routing，除非之后经过单独 apply gate。"
    if target_type == "speak":
        return "允许会创建一个会过期的一次性许可；默认主动发言策略不变。"
    return "仅供了解；不需要状态变更。"


def _review_actions(target_type: str, target_id: str) -> list[dict[str, str]]:
    if not target_id:
        return []
    if target_type == "candidate":
        return [
            _review_action("approve", "approve_candidate", target_type, target_id),
            _review_action("reject", "reject_candidate", target_type, target_id),
        ]
    if target_type == "proposal":
        return [
            _review_action("approve", "approve_proposal", target_type, target_id),
            _review_action("reject", "reject_proposal", target_type, target_id),
        ]
    if target_type == "memory_source":
        return [_review_action("feedback", "mark_feedback", target_type, target_id)]
    if target_type == "speak":
        return [_review_action("allow", "allow_speak_once", target_type, target_id)]
    return []


def _review_action(verb: str, action_type: str, target_type: str, target_id: str) -> dict[str, str]:
    token = _action_token(action_type=action_type, target_type=target_type, target_id=target_id)
    command = f"memory {verb} {token}"
    if action_type == "mark_feedback":
        command += " useful|irrelevant|too_mechanistic|missing_context|overconfident|needs_specific_recall"
    return {
        "verb": verb,
        "action_type": action_type,
        "target_type": target_type,
        "target_id": target_id,
        "token": token,
        "command": command,
    }


def _action_token(*, action_type: str, target_type: str, target_id: str) -> str:
    payload = "|".join([str(action_type), str(target_type), str(target_id)])
    return "oa_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:14]


def _digest_text_preview(
    action_items: list[dict[str, Any]],
    suggested_items: list[dict[str, Any]],
    fyi_items: list[dict[str, Any]],
) -> str:
    rendered_sections = {
        "action_required": [_render_review_item(item, section="action_required") for item in action_items],
        "review_suggested": [_render_review_item(item, section="review_suggested") for item in suggested_items],
        "fyi": [_render_review_item(item, section="fyi") for item in fyi_items],
    }
    return _rendered_digest_text(rendered_sections)[:2000]


def _rendered_digest_text(
    sections: dict[str, list[dict[str, Any]]],
    *,
    counts: dict[str, Any] | None = None,
    overflow: dict[str, Any] | None = None,
) -> str:
    max_chars = OWNER_REVIEW_TEXT_LIMIT
    lines = [
        "Memory-OS 审批摘要",
        "",
        *_rendered_overview_lines(counts or {}, overflow or {}),
        "",
        "回复方式：",
        "- 直接复制完整命令，例如：memory approve oa_...",
        "- 也可以只回复 oa_...，Hermes 会继续问你要 approve/reject/allow/feedback。",
        "- A1/R1/F1 只是列表编号，不是审批 ID。",
        "",
    ]
    omitted = 0
    for title, key in (
        ("需要你决定", "action_required"),
        ("建议你看", "review_suggested"),
        ("仅供了解", "fyi"),
    ):
        section_lines = [f"{title}:"]
        items = sections.get(key, [])
        if not items:
            section_lines.append("- 无")
        for item in items:
            item_lines = _rendered_digest_item_lines(item)
            candidate = lines + section_lines + item_lines + [""]
            if len("\n".join(candidate).rstrip()) > max_chars:
                omitted += 1
                continue
            section_lines.extend(item_lines)
        if key == "fyi" and omitted:
            summary_line = f"- 还有 {omitted} 项为了控制 Telegram 摘要长度被省略。"
            candidate = lines + section_lines + [summary_line, ""]
            if len("\n".join(candidate).rstrip()) <= max_chars:
                section_lines.append(summary_line)
        lines.extend(section_lines)
        lines.append("")
    return "\n".join(lines).rstrip()


def _rendered_overview_lines(counts: dict[str, Any], overflow: dict[str, Any]) -> list[str]:
    if not counts:
        return ["全貌：本条摘要只展示当前优先项；未展示项会在后续摘要或你主动要求时继续展开。"]
    pending = int(counts.get("pending") or 0)
    action_total = int(counts.get("action_required_total") or 0)
    action_shown = int(counts.get("action_required_shown") or 0)
    suggested_total = int(counts.get("review_suggested_total") or 0)
    suggested_shown = int(counts.get("review_suggested_shown") or 0)
    fyi_total = int(counts.get("fyi_total") or 0)
    fyi_shown = int(counts.get("fyi_shown") or 0)
    action_omitted = max(int(overflow.get("action_required") or 0), max(action_total - action_shown, 0))
    suggested_omitted = max(int(overflow.get("review_suggested") or 0), max(suggested_total - suggested_shown, 0))
    fyi_omitted = max(int(overflow.get("fyi") or 0), max(fyi_total - fyi_shown, 0))
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
    commands = [str(command) for command in item.get("action_commands") or []]
    action_line = " / ".join(commands) if commands else str(item.get("suggested_action") or "no action required")
    return [
        f"- [{item.get('anchor')}] {item.get('question')}",
        f"  操作: {action_line}",
        f"  引用: {target_ref}",
        f"  原因: {item.get('reason')}",
        f"  结果: {item.get('consequence')}",
        f"  来源: {item.get('source_module')}",
    ]


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
                result[clean] = {"item": item, "action_type": str(action_type)}
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
        if rating not in ALLOWED_FEEDBACK_RATINGS:
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
    if verb == "feedback" and target_type == "memory_source":
        return "mark_feedback"
    if verb == "allow" and target_type == "speak":
        return "allow_speak_once"
    return ""


def _reply_verb_matches_action_type(verb: str, action_type: str) -> bool:
    if verb == "approve":
        return action_type in {"approve_candidate", "approve_proposal"}
    if verb == "reject":
        return action_type in {"reject_candidate", "reject_proposal"}
    if verb == "feedback":
        return action_type == "mark_feedback"
    if verb == "allow":
        return action_type == "allow_speak_once"
    return False


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


def _digest_id() -> str:
    created_at = datetime.now(timezone.utc)
    return f"odig_{created_at.strftime('%Y%m%dT%H%M%S%fZ')}_{uuid4().hex[:8]}"


def _safe_channel(value: str) -> str:
    channel = str(value or "").strip().lower().replace("-", "_")
    allowed = {"telegram", "cli", "web", "slack", "whatsapp", "wecom", "matrix", "discord", "origin", "unknown"}
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
    return {
        "schema_version": OWNER_REVIEW_SURFACE_SCHEMA_VERSION,
        "profile": store.roots.profile or "default",
        "owner_id": owner_id,
        "status": "ok",
        "operation": "detail",
        "binding": binding,
        "match": match,
        "digest_id": str(rendered.get("digest_id") or ""),
        "item": item,
        "text": "\n".join(_rendered_digest_item_lines(item)),
        "raw_body_included": False,
        "boundary": _owner_review_false_boundary(),
    }


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
            "proposal": "proposal",
            "prop": "proposal",
            "memory_source": "memory_source",
            "memory-source": "memory_source",
            "msrc": "memory_source",
            "speak": "speak",
        }.get(prefix.strip(), prefix.strip())
        return normalized_prefix, suffix.strip()
    if action_type in {"approve_candidate", "reject_candidate"}:
        return "candidate", value
    if action_type in {"approve_proposal", "reject_proposal"}:
        return "proposal", value
    if action_type == "mark_feedback":
        return "memory_source", value
    if action_type == "allow_speak_once":
        return "speak", value
    return "unknown", value


def _idempotency_key(*, owner_id: str, target_type: str, target_id: str, action_type: str) -> str:
    return "|".join([str(owner_id), str(target_type), str(target_id), str(action_type)])


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
    action_required_ages = [
        int(item["age_days"])
        for item in items
        if item.get("effective_priority") == "action_required" and isinstance(item.get("age_days"), int)
    ]
    return {
        "schema_version": OWNER_REVIEW_AGING_SCHEMA_VERSION,
        "enabled": bool(aging.get("enabled")),
        "action_required_days": int(aging.get("action_required_days") or 0),
        "fyi_days": int(aging.get("fyi_days") or 0),
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
        "oldest_action_required_age_days": max(action_required_ages) if action_required_ages else None,
        "raw_body_included": False,
        "canonical_state_changed": False,
        "owner_action_created": False,
    }


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
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
        handle.write("\n")


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
    lowered = text.lower()
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
    if any(marker in lowered for marker in transcript_markers):
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
