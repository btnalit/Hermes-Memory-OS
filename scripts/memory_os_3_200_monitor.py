"""Read-only Memory-OS monitor for the 10.20.3.200 test host.

The script intentionally reports metadata, counters, headings, and trend
signals only. It must not print raw event summaries, private transcript bodies,
or selected context text.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any


EXPECTED_RH26_HEADINGS: dict[str, list[str]] = {
    "cancel_failed_video": ["Current Foreground Task"],
    "continue_current_task": ["Current Foreground Task"],
    "casual_memory_system_change": [],
    "diagnostic_current_architecture": ["Diagnostic Grounding", "Current Memory-OS Runtime Facts"],
    "candidate_vs_crystallized": ["Crystallized Review Candidates", "Indexed Recall"],
    "active_comfyui_install": ["Current Foreground Task", "Indexed Recall"],
    "deferred_cancellation": ["Current Foreground Task"],
}
ALLOWED_RH26_EXTRA_HEADINGS: dict[str, set[str]] = {
    "active_comfyui_install": {"Working Memory", "Recent Event Summaries"},
}
SAFE_CASUAL_HEADINGS = {"Conversation Carryover", "Recent Event Summaries"}
FORBIDDEN_CASUAL_HEADINGS = {
    "Current Foreground Task",
    "Diagnostic Grounding",
    "Current Memory-OS Runtime Facts",
    "Crystallized Review Candidates",
}


def find_rh26_heading_anomalies(probes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    anomalies: list[dict[str, Any]] = []
    for probe in probes:
        prompt_id = str(probe.get("id") or "")
        actual = list(probe.get("headings") or [])
        expected = EXPECTED_RH26_HEADINGS.get(prompt_id)
        if expected is None:
            continue
        if prompt_id == "casual_memory_system_change":
            if not actual or all(heading in SAFE_CASUAL_HEADINGS for heading in actual):
                continue
            forbidden = [heading for heading in actual if heading in FORBIDDEN_CASUAL_HEADINGS]
            anomalies.append(
                {
                    "id": prompt_id,
                    "severity": "fail" if forbidden else "warning",
                    "code": "casual_context_forbidden_heading" if forbidden else "casual_context_needs_review",
                    "expected": expected,
                    "actual": actual,
                }
            )
            continue
        allowed = set(expected) | ALLOWED_RH26_EXTRA_HEADINGS.get(prompt_id, set())
        if not all(heading in actual for heading in expected) or any(heading not in allowed for heading in actual):
            anomalies.append(
                {
                    "id": prompt_id,
                    "severity": "fail",
                    "code": "unexpected_rh26_headings",
                    "expected": expected,
                    "actual": actual,
                }
            )
    return anomalies


def compute_deltas(current: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    if not previous:
        return {
            "counts_delta": {},
            "audit_entries_per_new_event": None,
            "audit_action_delta": {},
            "hook_marker_delta": {},
            "session_activity_delta": {},
        }
    current_counts = _counts(current)
    previous_counts = _counts(previous)
    keys = sorted(set(current_counts) | set(previous_counts))
    deltas = {key: int(current_counts.get(key, 0)) - int(previous_counts.get(key, 0)) for key in keys}
    new_events = int(deltas.get("events", 0))
    if new_events > 0:
        audit_per_event: float | None = round(float(deltas.get("audit_entries", 0)) / float(new_events), 3)
    else:
        audit_per_event = None
    current_actions = current.get("audit_actions", {}).get("action_counts", {})
    previous_actions = previous.get("audit_actions", {}).get("action_counts", {})
    action_delta = _counter_delta(current_actions, previous_actions) if previous_actions else {}
    hook_marker_delta = _hook_marker_delta(current.get("hook_markers", {}), previous.get("hook_markers", {}))
    session_activity_delta = _fixed_counter_delta(
        current.get("session_activity", {}),
        previous.get("session_activity", {}),
        ("total_session_events",),
    )
    return {
        "counts_delta": deltas,
        "audit_entries_per_new_event": audit_per_event,
        "audit_action_delta": action_delta,
        "hook_marker_delta": hook_marker_delta,
        "session_activity_delta": session_activity_delta,
    }


def compact_rh31_eval_summary(summary: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(summary, dict):
        return {}
    if summary.get("schema_version") != "memory-os.rh31_summary.v0":
        return dict(summary)
    return {
        "schema_version": summary.get("schema_version"),
        "status": summary.get("status"),
        "adapter_count": summary.get("adapter_count"),
        "case_count": summary.get("case_count"),
        "score_count": summary.get("score_count"),
        "failure_count": summary.get("failure_count"),
        "failure_class_distribution": summary.get("failure_class_distribution") or {},
        "boundary_true_count": summary.get("boundary_true_count"),
        "forbidden_field_count": summary.get("forbidden_field_count"),
        "report_written": bool(summary.get("report_dir")),
        "source_distribution": summary.get("source_distribution") or {},
    }


def classify_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    passed: list[dict[str, Any]] = []
    warn: list[dict[str, Any]] = []
    fail: list[dict[str, Any]] = []

    if snapshot.get("gateway", {}).get("ActiveState") == "active":
        passed.append({"code": "gateway_active"})
    else:
        fail.append({"code": "gateway_inactive", "value": snapshot.get("gateway")})

    heartbeat = snapshot.get("heartbeat_timer", {})
    if heartbeat.get("ActiveState") == "active" and heartbeat.get("UnitFileState") == "enabled":
        passed.append({"code": "heartbeat_timer_active"})
    else:
        fail.append({"code": "heartbeat_timer_inactive", "value": heartbeat})
    if not snapshot.get("heartbeat_listed", False):
        fail.append({"code": "heartbeat_timer_not_listed"})
    heartbeat_service = snapshot.get("heartbeat_service", {})
    if _systemd_service_failed(heartbeat_service):
        fail.append({"code": "heartbeat_service_failed", "value": heartbeat_service})
    heartbeat_state = snapshot.get("heartbeat_state", {})
    if heartbeat_state:
        if heartbeat_state.get("fresh") is True:
            passed.append({"code": "heartbeat_state_fresh"})
        else:
            fail.append({"code": "heartbeat_state_stale", "value": heartbeat_state})

    cognitive_loop_timer = snapshot.get("cognitive_loop_timer", {})
    if (
        cognitive_loop_timer.get("ActiveState") == "active"
        and cognitive_loop_timer.get("UnitFileState") == "enabled"
    ):
        passed.append({"code": "cognitive_loop_timer_active"})
    else:
        fail.append({"code": "cognitive_loop_timer_inactive", "value": cognitive_loop_timer})
    if not snapshot.get("cognitive_loop_listed", False):
        fail.append({"code": "cognitive_loop_timer_not_listed"})
    cognitive_loop_service = snapshot.get("cognitive_loop_service", {})
    if _systemd_service_failed(cognitive_loop_service):
        fail.append({"code": "cognitive_loop_service_failed", "value": cognitive_loop_service})

    cognitive_loop = snapshot.get("cognitive_loop", {})
    if cognitive_loop.get("last_status") == "error":
        fail.append({"code": "cognitive_loop_last_cycle_error", "value": cognitive_loop})
    elif cognitive_loop.get("last_status") in {"ok", "warning"}:
        passed.append({"code": "cognitive_loop_last_cycle_present"})
    else:
        warn.append({"code": "cognitive_loop_no_cycle_yet", "value": cognitive_loop})
    for key in ("actual_send", "actual_execute", "actual_identity_write", "actual_crystallized_approval"):
        if (cognitive_loop.get("boundaries") or {}).get(key) is True:
            fail.append({"code": f"cognitive_loop_{key}_true"})

    memory_status = snapshot.get("memory_status", {})
    if memory_status.get("index_health", {}).get("state") == "healthy":
        passed.append({"code": "index_healthy"})
    else:
        warn.append({"code": "index_not_healthy", "value": memory_status.get("index_health")})
    if memory_status.get("prefetch_mode") != "indexed":
        warn.append({"code": "prefetch_not_indexed", "value": memory_status.get("prefetch_mode")})
    if int(memory_status.get("counts", {}).get("crystallized_records", 0)) != 0:
        fail.append({"code": "unexpected_crystallized_records", "value": memory_status.get("counts", {})})

    doctor = snapshot.get("doctor", {})
    if doctor.get("status") == "ok":
        passed.append({"code": "doctor_ok"})
    else:
        fail.append({"code": "doctor_not_ok", "value": doctor})
    for code, severity in doctor.get("findings", []) or []:
        if code == "hindsight_adapter_disabled":
            continue
        if severity == "error":
            fail.append({"code": "doctor_error_finding", "finding": code})
        else:
            warn.append({"code": "doctor_warning_finding", "finding": code})

    contract = snapshot.get("status_tool_contract", {})
    if contract.get("status") == "ok":
        passed.append({"code": "status_tool_contract_ok"})
    else:
        fail.append({"code": "status_tool_contract_failed", "value": contract})

    shell_alias = snapshot.get("shell_alias_no_env", {})
    if (
        shell_alias.get("status_ok") is True
        and shell_alias.get("doctor_ok") is True
        and shell_alias.get("memory_sources_ok") is True
        and shell_alias.get("metadata_retention_ok") is True
        and shell_alias.get("low_clue_recall_ok") is True
        and shell_alias.get("modules_ok") is True
        and shell_alias.get("eval_ok") is True
        and shell_alias.get("review_ok", True) is True
        and shell_alias.get("review_aging_ok", True) is True
        and shell_alias.get("review_channel_ok", True) is True
        and shell_alias.get("review_delivery_status_ok", True) is True
        and shell_alias.get("review_delivery_gate_ok", True) is True
        and shell_alias.get("review_digest_ok", True) is True
        and shell_alias.get("review_render_ok", True) is True
        and shell_alias.get("review_reply_ok", True) is True
    ):
        passed.append({"code": "shell_alias_no_env_ok"})
    else:
        fail.append({"code": "shell_alias_no_env_failed", "value": shell_alias})

    hook_markers = snapshot.get("hook_markers", {})
    session_activity = snapshot.get("session_activity", {})
    if isinstance(hook_markers, dict) and isinstance(session_activity, dict):
        deltas = snapshot.get("deltas", {}) if isinstance(snapshot.get("deltas"), dict) else {}
        session_delta = _int_at(deltas, ("session_activity_delta", "total_session_events"))
        hook_delta = _int_at(deltas, ("hook_marker_delta", "total"))
        if session_delta > 0 and hook_delta <= 0:
            warn.append(
                {
                    "code": "hook_markers_missing_for_session_activity",
                    "session_event_delta": session_delta,
                    "hook_marker_delta": hook_delta,
                }
            )
        elif session_delta == 0:
            passed.append({"code": "hook_coverage_no_session_activity"})
        else:
            passed.append({"code": "hook_coverage_session_activity_with_markers"})

    module_artifacts = snapshot.get("module_artifacts", {})
    if module_artifacts.get("schema_version") == "memory-os.module_artifact_summary.v0":
        passed.append({"code": "module_artifact_summary_ok"})
        speak_gate = module_artifacts.get("speak_gate") if isinstance(module_artifacts.get("speak_gate"), dict) else {}
        if speak_gate.get("actual_send") is True:
            fail.append({"code": "module_artifact_speak_gate_actual_send_true", "value": speak_gate})
    else:
        warn.append({"code": "module_artifact_summary_unavailable", "value": module_artifacts})

    expression_artifacts = snapshot.get("expression_artifacts", {})
    if expression_artifacts.get("schema_version") == "memory-os.expression_artifact_summary.v0":
        if expression_artifacts.get("speak_gate_actual_send") is True:
            fail.append({"code": "expression_artifact_speak_gate_actual_send_true", "value": expression_artifacts})
        else:
            passed.append({"code": "expression_artifact_summary_ok"})
    elif expression_artifacts:
        warn.append({"code": "expression_artifact_summary_unavailable", "value": expression_artifacts})

    session_mirror = snapshot.get("session_mirror", {})
    if session_mirror.get("schema_version") == "memory-os.session_mirror_monitor_summary.v0":
        if int(session_mirror.get("dry_run_written_event_ids_count") or 0) > 0:
            fail.append(
                {
                    "code": "session_mirror_dry_run_wrote_events",
                    "value": session_mirror.get("dry_run_written_event_ids_count"),
                }
            )
        if int(session_mirror.get("dry_run_findings_count") or 0) > 0:
            fail.append(
                {
                    "code": "session_mirror_dry_run_findings",
                    "value": session_mirror.get("dry_run_findings_count"),
                }
            )
        if session_mirror.get("dry_run_status") == "ok" and int(session_mirror.get("dry_run_written_event_ids_count") or 0) == 0:
            passed.append({"code": "session_mirror_dry_run_ok"})
        else:
            warn.append({"code": "session_mirror_dry_run_not_ok", "value": session_mirror})
        if int(session_mirror.get("pending_session_count") or 0) > 0:
            warn.append(
                {
                    "code": "session_mirror_pending_sessions",
                    "pending_session_count": session_mirror.get("pending_session_count"),
                }
            )
    elif session_mirror:
        warn.append({"code": "session_mirror_summary_unavailable", "value": session_mirror})

    owner_review = snapshot.get("owner_review", {})
    if owner_review:
        if owner_review.get("schema_version") == "memory-os.owner_review_status.v0":
            passed.append({"code": "owner_review_status_ok"})
            if int(owner_review.get("unapproved_crystallized_write_count") or 0) > 0:
                fail.append(
                    {
                        "code": "owner_review_unapproved_crystallized_write",
                        "value": owner_review.get("unapproved_crystallized_write_count"),
                    }
                )
            if int(owner_review.get("error_count") or 0) > 0:
                warn.append({"code": "owner_review_action_errors", "value": owner_review.get("error_count")})
            stale_count = _int_at(owner_review, ("review_queue", "stale_count"))
            if stale_count > 0:
                warn.append({"code": "owner_review_stale_items", "value": stale_count})
        else:
            warn.append({"code": "owner_review_status_unavailable", "value": owner_review})

    review_aging = snapshot.get("owner_review_aging", {})
    if review_aging:
        if review_aging.get("schema_version") == "memory-os.owner_review_aging.v0":
            passed.append({"code": "owner_review_aging_ok"})
            for key in ("raw_body_included", "canonical_state_changed", "owner_action_created"):
                if review_aging.get(key) is True:
                    fail.append({"code": f"owner_review_aging_{key}_true"})
        else:
            warn.append({"code": "owner_review_aging_unavailable", "value": review_aging})

    review_channel = snapshot.get("owner_review_channel", {})
    if review_channel:
        if review_channel.get("schema_version") == "memory-os.owner_review_channel.v0":
            if review_channel.get("status") in {"selected", "dry_run_only", "disabled"}:
                passed.append({"code": "owner_review_channel_resolver_ok"})
            elif review_channel.get("status") == "unresolved":
                warn.append({"code": "owner_review_channel_unresolved", "value": review_channel})
            if review_channel.get("raw_body_included") is True:
                fail.append({"code": "owner_review_channel_raw_body_included"})
        else:
            warn.append({"code": "owner_review_channel_unavailable", "value": review_channel})

    digest_preview = snapshot.get("owner_review_digest_preview", {})
    if digest_preview:
        if digest_preview.get("schema_version") == "memory-os.owner_review_digest_preview.v0":
            if digest_preview.get("raw_body_included") is True:
                fail.append({"code": "owner_review_digest_raw_body_included"})
            if digest_preview.get("will_send") is True:
                fail.append({"code": "owner_review_digest_would_send_true"})
            for key in ("actual_send", "actual_execute", "actual_identity_write", "actual_unapproved_crystallized_approval"):
                if (digest_preview.get("boundary") or {}).get(key) is True:
                    fail.append({"code": f"owner_review_digest_{key}_true"})
            if digest_preview.get("raw_body_included") is not True and digest_preview.get("will_send") is not True:
                passed.append({"code": "owner_review_digest_preview_ok"})
        else:
            warn.append({"code": "owner_review_digest_preview_unavailable", "value": digest_preview})

    rendered_digest = snapshot.get("owner_review_rendered_digest", {})
    if rendered_digest:
        if rendered_digest.get("schema_version") == "memory-os.owner_review_rendered_digest.v0":
            if rendered_digest.get("raw_body_included") is True:
                fail.append({"code": "owner_review_rendered_digest_raw_body_included"})
            if rendered_digest.get("will_send") is True:
                fail.append({"code": "owner_review_rendered_digest_would_send_true"})
            if rendered_digest.get("text_has_internal_schema") is True:
                fail.append({"code": "owner_review_rendered_digest_internal_schema_text"})
            if rendered_digest.get("text_has_transcript_marker") is True:
                fail.append({"code": "owner_review_rendered_digest_transcript_marker"})
            if int(rendered_digest.get("text_char_count") or 0) > 2400:
                fail.append({"code": "owner_review_rendered_digest_too_long", "value": rendered_digest.get("text_char_count")})
            for key in ("actual_send", "actual_execute", "actual_identity_write", "actual_unapproved_crystallized_approval"):
                if (rendered_digest.get("boundary") or {}).get(key) is True:
                    fail.append({"code": f"owner_review_rendered_digest_{key}_true"})
            if (
                rendered_digest.get("raw_body_included") is not True
                and rendered_digest.get("will_send") is not True
                and rendered_digest.get("text_has_internal_schema") is not True
                and rendered_digest.get("text_has_transcript_marker") is not True
                and int(rendered_digest.get("text_char_count") or 0) <= 2400
            ):
                passed.append({"code": "owner_review_rendered_digest_ok"})
        else:
            warn.append({"code": "owner_review_rendered_digest_unavailable", "value": rendered_digest})

    reply_dry_run = snapshot.get("owner_review_reply_dry_run", {})
    if reply_dry_run:
        if reply_dry_run.get("schema_version") == "memory-os.owner_review_reply.v0":
            if reply_dry_run.get("dry_run") is not True:
                fail.append({"code": "owner_review_reply_dry_run_mutated_state", "value": reply_dry_run})
            if reply_dry_run.get("status") == "ok" and reply_dry_run.get("owner_action_dry_run") is not True:
                fail.append({"code": "owner_review_reply_owner_action_not_dry_run", "value": reply_dry_run})
            for key in ("actual_send", "actual_execute", "actual_identity_write", "actual_unapproved_crystallized_approval"):
                if (reply_dry_run.get("boundary") or {}).get(key) is True:
                    fail.append({"code": f"owner_review_reply_{key}_true"})
            if reply_dry_run.get("status") in {"ok", "needs_clarification", "unsupported"}:
                passed.append({"code": "owner_review_reply_dry_run_ok"})
        else:
            warn.append({"code": "owner_review_reply_dry_run_unavailable", "value": reply_dry_run})

    ingress_guard = snapshot.get("owner_review_ingress_guard", {})
    if ingress_guard:
        if ingress_guard.get("schema_version") == "memory-os.owner_review_ingress_guard.v0":
            if ingress_guard.get("legacy_anchor_accepted") is True:
                fail.append({"code": "owner_review_legacy_anchor_accepted", "value": "approve A2"})
            if ingress_guard.get("legacy_reject_anchor_accepted") is True:
                fail.append({"code": "owner_review_legacy_reject_anchor_accepted", "value": "reject R1"})
            if ingress_guard.get("ordinary_anchor_text_accepted") is True:
                fail.append({"code": "owner_review_ordinary_anchor_text_accepted"})
            if ingress_guard.get("token_command_accepted") is not True:
                fail.append({"code": "owner_review_token_command_not_accepted"})
            if ingress_guard.get("slash_token_command_accepted") is not True:
                fail.append({"code": "owner_review_slash_token_command_not_accepted"})
            if ingress_guard.get("feedback_token_command_accepted") is not True:
                fail.append({"code": "owner_review_feedback_token_command_not_accepted"})
            if (
                ingress_guard.get("legacy_anchor_accepted") is not True
                and ingress_guard.get("legacy_reject_anchor_accepted") is not True
                and ingress_guard.get("ordinary_anchor_text_accepted") is not True
                and ingress_guard.get("token_command_accepted") is True
                and ingress_guard.get("slash_token_command_accepted") is True
                and ingress_guard.get("feedback_token_command_accepted") is True
            ):
                passed.append({"code": "owner_review_ingress_guard_token_only"})
        else:
            warn.append({"code": "owner_review_ingress_guard_unavailable", "value": ingress_guard})


    delivery_gate = snapshot.get("owner_review_delivery_gate", {})
    delivery_status = snapshot.get("owner_review_delivery_status", {})
    if delivery_status:
        if delivery_status.get("schema_version") == "memory-os.owner_review_delivery_status.v0":
            passed.append({"code": "owner_review_delivery_status_ok"})
            if int(delivery_status.get("unapproved_send_count") or 0) > 0:
                fail.append({"code": "owner_review_unapproved_send", "value": delivery_status.get("unapproved_send_count")})
            if int(delivery_status.get("raw_body_included_count") or 0) > 0:
                fail.append({"code": "owner_review_delivery_raw_body_included"})
            if int(delivery_status.get("error_count") or 0) > 0:
                warn.append({"code": "owner_review_delivery_errors", "value": delivery_status.get("error_count")})
        else:
            warn.append({"code": "owner_review_delivery_status_unavailable", "value": delivery_status})
    if delivery_gate:
        if delivery_gate.get("schema_version") == "memory-os.owner_review_delivery_gate.v0":
            if delivery_gate.get("status") in {"disabled", "blocked", "ready"}:
                passed.append({"code": "owner_review_delivery_gate_ok"})
            if delivery_gate.get("status") == "ready":
                warn.append({"code": "owner_review_delivery_gate_ready_for_review", "value": delivery_gate})
            boundary = delivery_gate.get("boundary") if isinstance(delivery_gate.get("boundary"), dict) else {}
            for key in ("actual_send", "actual_execute", "actual_identity_write", "actual_unapproved_crystallized_approval"):
                if boundary.get(key) is True:
                    fail.append({"code": f"owner_review_delivery_gate_{key}_true"})
            digest = delivery_gate.get("digest") if isinstance(delivery_gate.get("digest"), dict) else {}
            channel = delivery_gate.get("review_channel") if isinstance(delivery_gate.get("review_channel"), dict) else {}
            if digest.get("raw_body_included") is True or channel.get("raw_body_included") is True:
                fail.append({"code": "owner_review_delivery_gate_raw_body_included"})
        else:
            warn.append({"code": "owner_review_delivery_gate_unavailable", "value": delivery_gate})

    proposal_followups = snapshot.get("owner_review_proposal_followups", {})
    if proposal_followups:
        if proposal_followups.get("schema_version") == "memory-os.approved_proposal_followups.v0":
            passed.append({"code": "owner_review_proposal_followups_ok"})
            if proposal_followups.get("raw_body_included") is True:
                fail.append({"code": "owner_review_proposal_followups_raw_body_included"})
            if int(proposal_followups.get("execution_ticket_count") or 0) > 0:
                fail.append({"code": "owner_review_proposal_followups_execution_ticket_created"})
            boundary = proposal_followups.get("boundary") if isinstance(proposal_followups.get("boundary"), dict) else {}
            for key in ("actual_send", "actual_execute", "actual_identity_write", "actual_unapproved_crystallized_approval"):
                if boundary.get(key) is True:
                    fail.append({"code": f"owner_review_proposal_followups_{key}_true"})
            if int(proposal_followups.get("pending_followup_count") or 0) > 0:
                warn.append(
                    {
                        "code": "owner_review_approved_proposals_pending_followup",
                        "value": proposal_followups.get("pending_followup_count"),
                    }
                )
        else:
            warn.append({"code": "owner_review_proposal_followups_unavailable", "value": proposal_followups})

    cron_integration = snapshot.get("owner_review_cron_integration", {})
    if cron_integration:
        if cron_integration.get("schema_version") == "memory-os.owner_review_cron_integration.v0":
            passed.append({"code": "owner_review_cron_integration_status_ok"})
            if int(cron_integration.get("raw_body_included_count") or 0) > 0:
                fail.append({"code": "owner_review_cron_raw_body_included"})
            if int(cron_integration.get("unapproved_send_count") or 0) > 0:
                fail.append({"code": "owner_review_cron_unapproved_send"})
            if cron_integration.get("enabled") is True and cron_integration.get("job_present") is not True:
                warn.append({"code": "owner_review_cron_job_missing"})
            if cron_integration.get("enabled") is True and cron_integration.get("helper_script_present") is not True:
                fail.append({"code": "owner_review_cron_helper_missing"})
            for item in cron_integration.get("findings") or []:
                if isinstance(item, dict) and item.get("severity") == "error":
                    fail.append({"code": f"owner_review_cron_{item.get('code')}"})
        else:
            warn.append({"code": "owner_review_cron_integration_unavailable", "value": cron_integration})

    rh31 = snapshot.get("rh31_eval", {})
    if rh31:
        if rh31.get("schema_version") == "memory-os.rh31_summary.v0":
            if int(rh31.get("boundary_true_count") or 0) > 0:
                fail.append({"code": "rh31_eval_boundary_true", "value": rh31.get("boundary_true_count")})
            if int(rh31.get("forbidden_field_count") or 0) > 0:
                fail.append({"code": "rh31_eval_forbidden_fields", "value": rh31.get("forbidden_field_count")})
            if int(rh31.get("boundary_true_count") or 0) == 0 and int(rh31.get("forbidden_field_count") or 0) == 0:
                passed.append({"code": "rh31_eval_safety_ok"})
            if rh31.get("status") == "warning":
                warn.append({"code": "rh31_eval_has_failures", "failure_count": rh31.get("failure_count")})
            elif rh31.get("status") == "fail":
                fail.append({"code": "rh31_eval_failed", "failure_count": rh31.get("failure_count")})
        else:
            warn.append({"code": "rh31_eval_unavailable", "value": rh31})

    router = snapshot.get("context_router", {})
    if router.get("enabled") is True and router.get("mode") == "apply":
        passed.append({"code": "context_router_apply"})
    else:
        warn.append({"code": "context_router_not_apply", "value": router})

    memory_sources = snapshot.get("memory_sources", {})
    if memory_sources.get("schema_version") == "memory-os.memory_sources_stats.v0":
        if memory_sources.get("forbidden_field_findings"):
            fail.append(
                {
                    "code": "memory_sources_forbidden_fields",
                    "findings": memory_sources.get("forbidden_field_findings"),
                }
            )
        if int(memory_sources.get("boundary_true_count") or 0) > 0:
            fail.append({"code": "memory_sources_boundary_true", "value": memory_sources.get("boundary_true_count")})
        if bool(memory_sources.get("ledger_exists")) and not memory_sources.get("forbidden_field_findings"):
            passed.append({"code": "memory_sources_stats_ok"})
        else:
            warn.append({"code": "memory_sources_no_records_yet", "value": memory_sources})
    else:
        warn.append({"code": "memory_sources_stats_unavailable", "value": memory_sources})

    low_clue = snapshot.get("low_clue_recall", {})
    if low_clue.get("schema_version") == "memory-os.low_clue_recall.v0":
        judge = low_clue.get("llm_judge", {}) if isinstance(low_clue.get("llm_judge"), dict) else {}
        configured_judge = (
            snapshot.get("low_clue_recall_config", {}).get("llm_judge", {})
            if isinstance(snapshot.get("low_clue_recall_config", {}).get("llm_judge", {}), dict)
            else {}
        )
        judge_status = judge.get("status")
        if configured_judge.get("enabled") and configured_judge.get("mode") == "report_only":
            if judge_status in {"ok", "no_clear_match", "no_match", "no_selection"}:
                passed.append({"code": "low_clue_llm_judge_available"})
            elif judge_status in {"error", "skipped"}:
                warn.append({"code": "low_clue_llm_judge_unavailable", "value": judge})
        if int(low_clue.get("internal_label_count") or 0) > 0:
            fail.append(
                {
                    "code": "low_clue_internal_candidate_label",
                    "value": low_clue.get("internal_label_count"),
                    "source_classes": low_clue.get("internal_label_source_classes"),
                }
            )
        passed.append({"code": "low_clue_recall_probe_ok"})
    else:
        warn.append({"code": "low_clue_recall_probe_unavailable", "value": low_clue})

    for item in snapshot.get("low_clue_ingress_matrix") or []:
        if not isinstance(item, dict):
            continue
        expected_route = str(item.get("expected_route") or "")
        route = str(item.get("route") or "")
        if expected_route and route != expected_route:
            fail.append(
                {
                    "code": "low_clue_ingress_route_mismatch",
                    "id": item.get("id"),
                    "expected": expected_route,
                    "actual": route,
                }
            )
        expected_heading = str(item.get("expected_heading") or "")
        headings = [str(heading) for heading in item.get("headings") or []]
        if expected_heading and expected_heading not in headings:
            fail.append(
                {
                    "code": "low_clue_ingress_heading_mismatch",
                    "id": item.get("id"),
                    "expected": expected_heading,
                    "actual": headings,
                }
            )
        if (
            expected_route == "ambiguous_recall"
            and expected_heading == "Recall Clarification Guard"
            and item.get("guard_contract_ok") is not True
        ):
            fail.append(
                {
                    "code": "low_clue_guard_contract_missing",
                    "id": item.get("id"),
                    "value": item.get("guard_contract_ok"),
                }
            )

    rh26_anomalies = find_rh26_heading_anomalies(list(snapshot.get("rh26_apply_probe") or []))
    for anomaly in rh26_anomalies:
        if anomaly.get("severity") == "fail":
            fail.append(anomaly)
        else:
            warn.append(anomaly)
    for probe in snapshot.get("rh26_apply_probe") or []:
        if probe.get("id") == "casual_memory_system_change" and int(probe.get("chars", 0)) == 0:
            warn.append({"code": "rh26_casual_empty"})

    deep_reflection = snapshot.get("deep_reflection", {})
    for key in ("actual_send", "actual_execute", "actual_identity_write", "actual_crystallized_approval"):
        if deep_reflection.get(key) is True:
            fail.append({"code": f"deep_reflection_{key}_true"})
    rolling = deep_reflection.get("rolling_injection_source_classes", {})
    selected_by_source = rolling.get("selected_by_source_class", {}) if isinstance(rolling, dict) else {}
    if selected_by_source and set(selected_by_source) == {"working"}:
        warn.append({"code": "deep_reflection_source_skew", "selected_by_source_class": selected_by_source})

    compaction = snapshot.get("compaction", {})
    if int(compaction.get("focus_none_count") or 0) > 0:
        warn.append(
            {
                "code": "compression_focus_none",
                "recent_count": compaction.get("recent_count"),
                "focus_none_count": compaction.get("focus_none_count"),
            }
        )

    status = "FAIL" if fail else "WARN" if warn else "PASS"
    return {"status": status, "pass": passed, "warn": warn, "fail": fail}


def _systemd_service_failed(service: dict[str, Any]) -> bool:
    if not service:
        return False
    return service.get("ActiveState") == "failed" or service.get("Result") not in {"", "success"}


def _counter_delta(current: Any, previous: Any) -> dict[str, int]:
    if not isinstance(current, dict):
        current = {}
    if not isinstance(previous, dict):
        previous = {}
    keys = sorted(set(current) | set(previous))
    result: dict[str, int] = {}
    for key in keys:
        try:
            value = int(current.get(key, 0)) - int(previous.get(key, 0))
        except (TypeError, ValueError):
            value = 0
        if value:
            result[str(key)] = value
    return result


def _fixed_counter_delta(current: Any, previous: Any, keys: tuple[str, ...]) -> dict[str, int]:
    if not isinstance(current, dict):
        current = {}
    if not isinstance(previous, dict):
        previous = {}
    return {key: _to_int(current.get(key)) - _to_int(previous.get(key)) for key in keys}


def _hook_marker_delta(current: Any, previous: Any) -> dict[str, int]:
    delta = _fixed_counter_delta(current, previous, ("started", "reset", "finalized"))
    if isinstance(current, dict) and isinstance(previous, dict) and "total" in current and "total" in previous:
        delta["total"] = _to_int(current.get("total")) - _to_int(previous.get("total"))
    else:
        delta["total"] = delta["started"] + delta["reset"] + delta["finalized"]
    return delta


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _int_at(payload: dict[str, Any], path: tuple[str, ...]) -> int:
    current: Any = payload
    for part in path:
        if not isinstance(current, dict):
            return 0
        current = current.get(part)
    return _to_int(current)


def render_chinese_summary(snapshot: dict[str, Any]) -> str:
    classification = snapshot.get("classification") or classify_snapshot(snapshot)
    memory_status = snapshot.get("memory_status", {})
    counts = memory_status.get("counts", {})
    router = snapshot.get("context_router", {})
    deltas = snapshot.get("deltas", {})
    counts_delta = deltas.get("counts_delta", {})
    lines = [
        f"监控结果: {classification['status']}",
        "",
        f"- host={snapshot.get('hostname')} time={snapshot.get('date_utc')}",
        f"- gateway={snapshot.get('gateway', {}).get('ActiveState')} pid={snapshot.get('gateway', {}).get('MainPID')}",
        (
            f"- heartbeat={snapshot.get('heartbeat_timer', {}).get('ActiveState')}/"
            f"{snapshot.get('heartbeat_timer', {}).get('UnitFileState')} "
            f"service_result={snapshot.get('heartbeat_service', {}).get('Result')}"
        ),
        (
            f"- cognitive_loop={snapshot.get('cognitive_loop', {}).get('last_status')} "
            f"timer={snapshot.get('cognitive_loop_timer', {}).get('ActiveState')}/"
            f"{snapshot.get('cognitive_loop_timer', {}).get('UnitFileState')} "
            f"service_result={snapshot.get('cognitive_loop_service', {}).get('Result')}"
        ),
        (
            f"- counts: audit_entries={counts.get('audit_entries')}, events={counts.get('events')}, "
            f"working_items={counts.get('working_items')}, candidates={counts.get('crystallized_candidates')}, "
            f"crystallized_records={counts.get('crystallized_records')}"
        ),
        (
            f"- deltas: audit_entries={_signed(counts_delta.get('audit_entries'))}, "
            f"events={_signed(counts_delta.get('events'))}, "
            f"working_items={_signed(counts_delta.get('working_items'))}, "
            f"candidates={_signed(counts_delta.get('crystallized_candidates'))}, "
            f"audit_per_new_event={deltas.get('audit_entries_per_new_event')}"
        ),
        f"- audit_actions={_audit_actions_summary(snapshot.get('audit_actions') or {}, deltas)}",
        f"- heartbeat_state={_heartbeat_state_summary(snapshot.get('heartbeat_state') or {})}",
        f"- working_status={_working_status_summary(snapshot.get('working_status') or {})}",
        f"- HookCoverage={_hook_coverage_summary(snapshot.get('hook_markers') or {}, snapshot.get('session_activity') or {}, deltas)}",
        (
            f"- index_health={memory_status.get('index_health')} "
            f"prefetch_mode={memory_status.get('prefetch_mode')}"
        ),
        f"- doctor={snapshot.get('doctor', {}).get('status')} findings={snapshot.get('doctor', {}).get('findings')}",
        f"- shell_alias_no_env={snapshot.get('shell_alias_no_env')}",
        (
            f"- context_router={router.get('mode')} apply_routes={router.get('apply_routes')} "
            f"llm_judge={router.get('llm_judge_mode')}"
        ),
        f"- low_clue_recall={_low_clue_summary(snapshot.get('low_clue_recall') or {}, snapshot.get('low_clue_recall_config') or {})}",
        f"- low_clue_ingress={_probe_summary(snapshot.get('low_clue_ingress_matrix') or [])}",
        f"- RH-26 probe={_probe_summary(snapshot.get('rh26_apply_probe') or [])}",
        f"- MemorySources={_memory_sources_summary(snapshot.get('memory_sources') or {})}",
        f"- ModuleArtifacts={_module_artifacts_summary(snapshot.get('module_artifacts') or {})}",
        f"- ExpressionArtifacts={_expression_artifacts_summary(snapshot.get('expression_artifacts') or {})}",
        f"- SessionMirror={_session_mirror_summary(snapshot.get('session_mirror') or {})}",
        f"- OwnerReview={_owner_review_summary(snapshot.get('owner_review') or {})}",
        f"- OwnerReviewAging={_owner_review_aging_summary(snapshot.get('owner_review_aging') or {})}",
        f"- OwnerReviewChannel={_owner_review_channel_summary(snapshot.get('owner_review_channel') or {})}",
        f"- OwnerDigestPreview={_owner_digest_preview_summary(snapshot.get('owner_review_digest_preview') or {})}",
        f"- OwnerRenderedDigest={_owner_rendered_digest_summary(snapshot.get('owner_review_rendered_digest') or {})}",
        f"- OwnerReplyDryRun={_owner_reply_dry_run_summary(snapshot.get('owner_review_reply_dry_run') or {})}",
        f"- OwnerIngressGuard={_owner_ingress_guard_summary(snapshot.get('owner_review_ingress_guard') or {})}",
        f"- OwnerProposalFollowups={_owner_proposal_followups_summary(snapshot.get('owner_review_proposal_followups') or {})}",
        f"- OwnerDeliveryStatus={_owner_delivery_status_summary(snapshot.get('owner_review_delivery_status') or {})}",
        f"- OwnerDeliveryGate={_owner_delivery_gate_summary(snapshot.get('owner_review_delivery_gate') or {})}",
        f"- OwnerCronIntegration={_owner_cron_integration_summary(snapshot.get('owner_review_cron_integration') or {})}",
        f"- RH31Eval={_rh31_summary(snapshot.get('rh31_eval') or {})}",
        f"- compaction={snapshot.get('compaction')}",
        f"- DeepReflection={_deep_reflection_summary(snapshot.get('deep_reflection') or {})}",
        f"- disk={snapshot.get('disk_du')}",
        "",
        f"PASS: {[item.get('code') for item in classification['pass']]}",
        f"WARN: {[item.get('code') for item in classification['warn']]}",
        f"FAIL: {[item.get('code') for item in classification['fail']]}",
    ]
    return "\n".join(lines)


def collect_snapshot(*, host: str = "hermes-media", previous: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = _ssh_json(host, _remote_probe_script())
    raw["rh31_eval"] = compact_rh31_eval_summary(raw.get("rh31_eval") or {})
    raw["deltas"] = compute_deltas(raw, previous)
    raw["classification"] = classify_snapshot(raw)
    return raw


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="hermes-media")
    parser.add_argument("--previous-json")
    parser.add_argument("--snapshot-out")
    parser.add_argument("--output", choices=["summary", "json"], default="summary")
    args = parser.parse_args(argv)

    previous = None
    if args.previous_json:
        previous_path = Path(args.previous_json)
        if previous_path.exists():
            previous = json.loads(previous_path.read_text(encoding="utf-8"))
    snapshot = collect_snapshot(host=args.host, previous=previous)
    if args.snapshot_out:
        output_path = Path(args.snapshot_out)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if args.output == "json":
        print(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render_chinese_summary(snapshot))
    return 0 if snapshot["classification"]["status"] != "FAIL" else 2


def _counts(snapshot: dict[str, Any]) -> dict[str, int]:
    counts = snapshot.get("memory_status", {}).get("counts", {})
    if not isinstance(counts, dict):
        return {}
    result: dict[str, int] = {}
    for key, value in counts.items():
        try:
            result[str(key)] = int(value)
        except (TypeError, ValueError):
            continue
    return result


def _signed(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        number = int(value)
    except (TypeError, ValueError):
        return "n/a"
    return f"{number:+d}"


def _probe_summary(probes: list[dict[str, Any]]) -> str:
    parts = []
    for probe in probes:
        parts.append(f"{probe.get('id')}:{probe.get('chars')}:{'/'.join(probe.get('headings') or [])}")
    return "; ".join(parts)


def _deep_reflection_summary(status: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": status.get("enabled"),
        "injection_mode": status.get("injection_mode"),
        "latest": status.get("latest_injection_source_classes"),
        "rolling": status.get("rolling_injection_source_classes"),
        "actual_send": status.get("actual_send"),
        "actual_execute": status.get("actual_execute"),
        "actual_identity_write": status.get("actual_identity_write"),
        "actual_crystallized_approval": status.get("actual_crystallized_approval"),
    }


def _memory_sources_summary(stats: dict[str, Any]) -> dict[str, Any]:
    return {
        "record_count": stats.get("record_count"),
        "file_size_bytes": stats.get("file_size_bytes"),
        "feedback_count": stats.get("feedback_count"),
        "feedback_ratings": stats.get("feedback_rating_distribution"),
        "feedback_file_size_bytes": stats.get("feedback_file_size_bytes"),
        "routes": stats.get("route_distribution"),
        "selected_sources": stats.get("selected_source_class_distribution"),
        "selected_headings": stats.get("selected_heading_distribution"),
        "dropped_headings": stats.get("dropped_heading_distribution"),
        "boundary_true_count": stats.get("boundary_true_count"),
        "forbidden_field_count": len(stats.get("forbidden_field_findings") or []),
    }


def _rh31_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": summary.get("status"),
        "adapter_count": summary.get("adapter_count"),
        "failure_count": summary.get("failure_count"),
        "boundary_true_count": summary.get("boundary_true_count"),
        "forbidden_field_count": summary.get("forbidden_field_count"),
        "report_written": bool(summary.get("report_dir")),
    }


def _module_artifacts_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "digest": summary.get("digest"),
        "wandering": summary.get("wandering"),
        "evidence": summary.get("evidence"),
        "proposal_queue": summary.get("proposal_queue"),
        "self_evolution": summary.get("self_evolution"),
        "governance_feedback": summary.get("governance_feedback"),
        "deep_reflection": summary.get("deep_reflection"),
        "ops_gate": summary.get("ops_gate"),
        "speak_gate": summary.get("speak_gate"),
    }


def _expression_artifacts_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "wandering_output_count": summary.get("wandering_output_count"),
        "wandering_would_send_count": summary.get("wandering_would_send_count"),
        "wandering_silent_count": summary.get("wandering_silent_count"),
        "speak_gate_would_send_count": summary.get("speak_gate_would_send_count"),
        "speak_gate_blocked_count": summary.get("speak_gate_blocked_count"),
        "speak_gate_actual_send": summary.get("speak_gate_actual_send"),
    }


def _session_mirror_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": summary.get("status"),
        "session_count": summary.get("session_count"),
        "covered_session_count": summary.get("covered_session_count"),
        "pending_session_count": summary.get("pending_session_count"),
        "dry_run_status": summary.get("dry_run_status"),
        "dry_run_new_event_count": summary.get("dry_run_new_event_count"),
        "dry_run_written_event_ids_count": summary.get("dry_run_written_event_ids_count"),
        "dry_run_findings_count": summary.get("dry_run_findings_count"),
    }


def _owner_review_summary(summary: dict[str, Any]) -> dict[str, Any]:
    queue = summary.get("review_queue") if isinstance(summary.get("review_queue"), dict) else {}
    burden = summary.get("digest_burden") if isinstance(summary.get("digest_burden"), dict) else {}
    backflow = summary.get("feedback_backflow") if isinstance(summary.get("feedback_backflow"), dict) else {}
    return {
        "pending": queue.get("pending_count"),
        "action_required": queue.get("action_required_count"),
        "stale": queue.get("stale_count"),
        "owner_actions": summary.get("owner_action_count"),
        "by_type": summary.get("action_type_counts"),
        "duplicates": summary.get("duplicate_ignored_count"),
        "errors": summary.get("error_count"),
        "owner_approved_crystallized": summary.get("owner_approved_crystallized_write_count"),
        "unapproved_crystallized": summary.get("unapproved_crystallized_write_count"),
        "owner_active_period": burden.get("owner_active_period"),
        "feedback_backflow": backflow,
    }


def _owner_review_aging_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": summary.get("enabled"),
        "raw_action_required": summary.get("raw_action_required_count"),
        "effective_action_required": summary.get("effective_action_required_count"),
        "aged_to_review_suggested": summary.get("aged_to_review_suggested_count"),
        "aged_to_fyi": summary.get("aged_to_fyi_count"),
        "unknown_timestamp": summary.get("unknown_timestamp_count"),
        "canonical_state_changed": summary.get("canonical_state_changed"),
        "owner_action_created": summary.get("owner_action_created"),
    }


def _owner_review_channel_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": summary.get("status"),
        "reason": summary.get("reason"),
        "channel": summary.get("channel"),
        "configured_by_owner": summary.get("configured_by_owner"),
        "fallback_used": summary.get("fallback_used"),
        "candidate_count": summary.get("candidate_count"),
        "raw_body_included": summary.get("raw_body_included"),
    }


def _owner_digest_preview_summary(summary: dict[str, Any]) -> dict[str, Any]:
    counts = summary.get("counts") if isinstance(summary.get("counts"), dict) else {}
    overflow = summary.get("overflow") if isinstance(summary.get("overflow"), dict) else {}
    return {
        "status": summary.get("status"),
        "will_send": summary.get("will_send"),
        "actions_enabled": summary.get("actions_enabled"),
        "raw_body_included": summary.get("raw_body_included"),
        "counts": counts,
        "overflow": overflow,
    }


def _owner_rendered_digest_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": summary.get("status"),
        "will_send": summary.get("will_send"),
        "raw_body_included": summary.get("raw_body_included"),
        "text_char_count": summary.get("text_char_count"),
        "text_has_internal_schema": summary.get("text_has_internal_schema"),
        "text_has_transcript_marker": summary.get("text_has_transcript_marker"),
        "section_counts": summary.get("section_counts"),
    }


def _owner_reply_dry_run_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": summary.get("status"),
        "dry_run": summary.get("dry_run"),
        "parsed_action_type": summary.get("parsed_action_type"),
        "parsed_target_type": summary.get("parsed_target_type"),
        "owner_action_status": summary.get("owner_action_status"),
        "owner_action_dry_run": summary.get("owner_action_dry_run"),
        "reason": summary.get("reason"),
        "command_source": summary.get("command_source"),
    }


def _owner_ingress_guard_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "legacy_anchor_accepted": summary.get("legacy_anchor_accepted"),
        "legacy_reject_anchor_accepted": summary.get("legacy_reject_anchor_accepted"),
        "ordinary_anchor_text_accepted": summary.get("ordinary_anchor_text_accepted"),
        "token_command_accepted": summary.get("token_command_accepted"),
        "slash_token_command_accepted": summary.get("slash_token_command_accepted"),
        "feedback_token_command_accepted": summary.get("feedback_token_command_accepted"),
    }


def _owner_proposal_followups_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "pending": summary.get("pending_followup_count"),
        "shown": summary.get("shown_count"),
        "overflow": summary.get("overflow_count"),
        "execution_tickets": summary.get("execution_ticket_count"),
        "raw_body_included": summary.get("raw_body_included"),
    }


def _owner_delivery_status_summary(summary: dict[str, Any]) -> dict[str, Any]:
    last = summary.get("last_delivery") if isinstance(summary.get("last_delivery"), dict) else {}
    return {
        "delivery_count": summary.get("delivery_count"),
        "sent_count": summary.get("sent_count"),
        "skipped_count": summary.get("skipped_count"),
        "error_count": summary.get("error_count"),
        "duplicate_ignored_count": summary.get("duplicate_ignored_count"),
        "owner_approved_digest_delivery": summary.get("owner_approved_digest_delivery_count"),
        "unapproved_send": summary.get("unapproved_send_count"),
        "raw_body_included": summary.get("raw_body_included_count"),
        "last_result": last.get("result"),
        "last_delivery_id": last.get("delivery_id"),
    }


def _owner_delivery_gate_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": summary.get("status"),
        "ready_for_delivery": summary.get("ready_for_delivery"),
        "delivery_enabled": summary.get("delivery_enabled"),
        "delivery_adapter": summary.get("delivery_adapter"),
        "blocked_reasons": summary.get("blocked_reasons"),
        "boundary": summary.get("boundary"),
    }


def _owner_cron_integration_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": summary.get("status"),
        "enabled": summary.get("enabled"),
        "job_present": summary.get("job_present"),
        "job_enabled": summary.get("job_enabled"),
        "helper_script_present": summary.get("helper_script_present"),
        "delivery_configured": summary.get("hermes_delivery_configured"),
        "delivery_target_class": summary.get("hermes_delivery_target_class"),
        "rendered_count_24h": summary.get("rendered_count_24h"),
        "raw_body_included": summary.get("raw_body_included_count"),
    }


def _hook_coverage_summary(
    markers: dict[str, Any], session_activity: dict[str, Any], deltas: dict[str, Any]
) -> dict[str, Any]:
    return {
        "markers": {
            "started": markers.get("started"),
            "reset": markers.get("reset"),
            "finalized": markers.get("finalized"),
            "total": markers.get("total"),
        },
        "session_activity": {
            "total_session_events": session_activity.get("total_session_events"),
            "recent_session_events": session_activity.get("recent_session_events"),
        },
        "marker_delta": deltas.get("hook_marker_delta"),
        "session_delta": deltas.get("session_activity_delta"),
    }


def _low_clue_summary(report: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    judge = report.get("llm_judge") if isinstance(report.get("llm_judge"), dict) else {}
    configured_judge = config.get("llm_judge") if isinstance(config.get("llm_judge"), dict) else {}
    return {
        "enabled": config.get("enabled"),
        "judge_mode": configured_judge.get("mode"),
        "decision": report.get("decision"),
        "candidate_count": report.get("candidate_count"),
        "internal_label_count": report.get("internal_label_count"),
        "llm_status": judge.get("status"),
        "llm_available": judge.get("status") in {"ok", "no_clear_match", "no_match", "no_selection"},
    }


def _audit_actions_summary(stats: dict[str, Any], deltas: dict[str, Any]) -> dict[str, Any]:
    return {
        "total": stats.get("total_count"),
        "recent_window": stats.get("recent_window"),
        "recent_top": _top_dict(stats.get("recent_action_counts") or {}, 8),
        "delta": _top_dict(deltas.get("audit_action_delta") or {}, 8),
    }


def _heartbeat_state_summary(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "exists": state.get("exists"),
        "fresh": state.get("fresh"),
        "age_seconds": state.get("age_seconds"),
        "last_heartbeat_at": state.get("last_heartbeat_at"),
        "processed_event_count": state.get("processed_event_count"),
        "last_processed_event_id": state.get("last_processed_event_id"),
    }


def _working_status_summary(status: dict[str, Any]) -> dict[str, Any]:
    documents = status.get("documents") if isinstance(status.get("documents"), dict) else {}
    summary: dict[str, Any] = {}
    for name, doc in documents.items():
        if not isinstance(doc, dict):
            continue
        summary[str(name)] = {
            "items": doc.get("items"),
            "statuses": doc.get("statuses"),
            "min_weight": doc.get("min_weight"),
            "max_weight": doc.get("max_weight"),
            "avg_weight": doc.get("avg_weight"),
        }
    return summary


def _top_dict(data: dict[str, Any], limit: int) -> dict[str, Any]:
    items: list[tuple[str, int]] = []
    for key, value in data.items():
        try:
            items.append((str(key), int(value)))
        except (TypeError, ValueError):
            continue
    return dict(sorted(items, key=lambda item: (-item[1], item[0]))[:limit])


def _ssh_json(host: str, script: str) -> dict[str, Any]:
    completed = subprocess.run(
        ["ssh", host, "python3 -"],
        input=script,
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout)


def _remote_probe_script() -> str:
    return r'''
import json, os, re, subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

def run(cmd, env=None):
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True, env=env)
        return {"ok": True, "out": out.strip(), "code": 0}
    except subprocess.CalledProcessError as exc:
        return {"ok": False, "out": (exc.output or "").strip(), "code": exc.returncode}

def system_show(unit):
    r = run(["systemctl", "--user", "show", unit, "-p", "LoadState", "-p", "ActiveState", "-p", "SubState", "-p", "UnitFileState", "-p", "MainPID", "-p", "Result", "-p", "ExecMainStatus", "--no-pager"])
    data = {"ok": r["ok"], "code": r["code"]}
    for line in r["out"].splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            data[key] = value
    return data

def load_json_cmd(cmd, env=None):
    r = run(cmd, env=env)
    if not r["ok"]:
        return {"_error": r["out"], "_code": r["code"]}
    try:
        return json.loads(r["out"])
    except Exception as exc:
        text = r["out"] or ""
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except Exception:
                pass
        return {"_parse_error": str(exc), "_raw_prefix": text[:240]}

def memory_os_cli(args):
    env = dict(os.environ)
    env["HERMES_HOME"] = "/root/.hermes"
    env["PYTHONPATH"] = "/root/.hermes/memory-os/runtime/python:/root/.hermes/plugins:" + env.get("PYTHONPATH", "")
    return load_json_cmd(["python3", "-m", "plugins.memory.memory_os"] + list(args), env=env)

def compaction_stats():
    r = run(["journalctl", "--user", "-u", "hermes-gateway.service", "--since", "6 hours ago", "--no-pager", "-o", "cat"])
    text = r["out"] if r["ok"] else ""
    starts = len(re.findall(r"context compression started|Compacting context|Preflight compression", text))
    focus_none = len(re.findall(r"focus=None", text))
    return {"recent_count": starts, "focus_none_count": focus_none}

def hook_marker_counts():
    r = run(["grep", "-R", '"action": "agent_os_shell_session_', "/root/.hermes/memory-os/audit"])
    text = r["out"] if r["ok"] else ""
    started = text.count("agent_os_shell_session_started")
    reset = text.count("agent_os_shell_session_reset")
    finalized = text.count("agent_os_shell_session_finalized")
    return {
        "started": started,
        "reset": reset,
        "finalized": finalized,
        "total": started + reset + finalized,
    }

def _read_jsonl(path):
    records = []
    p = Path(path)
    if not p.exists():
        return records
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except Exception:
            records.append({"_parse_error": True})
    return records

def session_activity_stats(recent_window=250):
    root = Path("/root/.hermes/memory-os/events")
    records = []
    if root.exists():
        for path in sorted(root.glob("*/*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    records.append(json.loads(line))
                except Exception:
                    continue
    session_events = []
    by_source = Counter()
    by_kind = Counter()
    for record in records:
        safe_ref = record.get("safe_ref") if isinstance(record.get("safe_ref"), dict) else {}
        if safe_ref.get("session_id"):
            session_events.append(record)
            by_source[str(record.get("source") or "unknown")] += 1
            by_kind[str(record.get("kind") or "unknown")] += 1
    recent_records = records[-int(recent_window):]
    recent_session_events = 0
    for record in recent_records:
        safe_ref = record.get("safe_ref") if isinstance(record.get("safe_ref"), dict) else {}
        if safe_ref.get("session_id"):
            recent_session_events += 1
    return {
        "total_events": len(records),
        "total_session_events": len(session_events),
        "recent_window": int(recent_window),
        "recent_session_events": recent_session_events,
        "by_source": dict(by_source),
        "by_kind": dict(by_kind),
    }

def audit_action_stats(recent_window=250):
    records = _read_jsonl("/root/.hermes/memory-os/audit/write_audit.jsonl")
    action_counts = Counter()
    recent_action_counts = Counter()
    for index, record in enumerate(records):
        action = str(record.get("action") or "unknown")
        action_counts[action] += 1
        if index >= max(0, len(records) - int(recent_window)):
            recent_action_counts[action] += 1
    return {
        "total_count": len(records),
        "recent_window": int(recent_window),
        "action_counts": dict(action_counts),
        "recent_action_counts": dict(recent_action_counts),
    }

def heartbeat_state(max_age_seconds=900):
    path = Path("/root/.hermes/memory-os/runtime/heartbeat_state.json")
    if not path.exists():
        return {"exists": False, "fresh": False, "age_seconds": None}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"exists": True, "fresh": False, "parse_error": str(exc), "age_seconds": None}
    raw_last = str(state.get("last_heartbeat_at") or "")
    age_seconds = None
    fresh = False
    if raw_last:
        try:
            parsed = datetime.fromisoformat(raw_last.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            age_seconds = max(0, int((datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()))
            fresh = age_seconds <= int(max_age_seconds)
        except Exception:
            fresh = False
    processed_ids = state.get("processed_event_ids")
    last_processed = ""
    processed_count = 0
    if isinstance(processed_ids, list):
        processed_count = len(processed_ids)
        last_processed = str(processed_ids[-1]) if processed_ids else ""
    return {
        "exists": True,
        "fresh": fresh,
        "age_seconds": age_seconds,
        "max_age_seconds": int(max_age_seconds),
        "last_heartbeat_at": raw_last,
        "last_attempt_at": str(state.get("last_attempt_at") or ""),
        "processed_event_count": int(state.get("processed_event_count") or processed_count),
        "last_processed_event_id": str(state.get("last_processed_event_id") or last_processed),
    }

def working_status():
    root = Path("/root/.hermes/memory-os/working")
    documents = {}
    if not root.exists():
        return {"documents": documents}
    for path in sorted(root.glob("*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            documents[path.name] = {"error": str(exc)}
            continue
        statuses = Counter()
        weights = []
        for item in document.get("items", []) if isinstance(document.get("items"), list) else []:
            if not isinstance(item, dict):
                continue
            statuses[str(item.get("status") or "unknown")] += 1
            try:
                weights.append(float(item.get("weight", 0)))
            except Exception:
                pass
        documents[path.name] = {
            "items": len(document.get("items", [])) if isinstance(document.get("items"), list) else 0,
            "statuses": dict(statuses),
            "min_weight": min(weights) if weights else None,
            "max_weight": max(weights) if weights else None,
            "avg_weight": round(sum(weights) / len(weights), 6) if weights else None,
            "updated_at": str(document.get("updated_at") or ""),
        }
    return {"documents": documents}

def enrich_memory_sources_stats(stats):
    if not isinstance(stats, dict):
        return stats
    records = _read_jsonl("/root/.hermes/memory-os/system/memory_sources.jsonl")
    selected_headings = Counter()
    dropped_headings = Counter()
    selected_source_classes = Counter()
    for record in records:
        for section in record.get("selected", []) if isinstance(record.get("selected"), list) else []:
            if isinstance(section, dict):
                selected_headings[str(section.get("heading") or "unknown")] += 1
                selected_source_classes[str(section.get("source_class") or "unknown")] += 1
        for section in record.get("dropped", []) if isinstance(record.get("dropped"), list) else []:
            if isinstance(section, dict):
                dropped_headings[str(section.get("heading") or "unknown")] += 1
    enriched = dict(stats)
    enriched["selected_heading_distribution"] = dict(selected_headings)
    enriched["dropped_heading_distribution"] = dict(dropped_headings)
    enriched["selected_source_class_distribution"] = dict(
        enriched.get("selected_source_class_distribution") or selected_source_classes
    )
    return enriched

def rh26_probe():
    code = r"""
import json, re
from plugins.memory.memory_os.config import load_config
from plugins.memory.memory_os.index import MemoryOSIndex
from plugins.memory.memory_os.prefetch import build_prefetch
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore
home="/root/.hermes"
roots=MemoryOSRoots.from_hermes_home(home, profile="default")
store=MemoryOSStore(roots)
config=load_config(home)
cases=[
 ("cancel_failed_video","太垃圾了，算了，你还是别做视频了","Current task: render ComfyUI tutorial video and fix missing content."),
 ("continue_current_task","继续当前任务","Current task: install ComfyUI Impact Pack."),
 ("casual_memory_system_change","我们继续聊刚才那套记忆系统，你觉得它现在带来的变化是什么？",""),
 ("diagnostic_current_architecture","当前记忆架构是什么？",""),
 ("candidate_vs_crystallized","那些 crystallized candidates 是已经沉淀的长期记忆吗？",""),
 ("active_comfyui_install","帮我继续安装 ComfyUI 插件","Current task: install ComfyUI plugins."),
 ("deferred_cancellation","这个先放一下，明天再说","Current task: render ComfyUI tutorial video."),
]
summary=[]
for cid, query, anchor_text in cases:
    anchor=("### Memory-OS Current Task Anchor\n- current task: "+anchor_text) if anchor_text else ""
    context=build_prefetch(query, budget_chars=2200, store=store, index=MemoryOSIndex(roots), runtime_facts={"provider":"memory_os","prefetch_mode":"indexed"}, current_task_anchor=anchor, context_router_config=config.get("context_router"))
    headings=re.findall(r"^### (.+)$", context, flags=re.M)
    summary.append({"id":cid,"chars":len(context),"headings":headings})
print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = "/root/.hermes/memory-os/runtime/python"
    r = run(["python3", "-c", code], env=env)
    return json.loads(r["out"]) if r["ok"] else {"_error": r["out"], "_code": r["code"]}

def low_clue_ingress_matrix():
    code = r"""
import json, re
from plugins.memory.memory_os.config import load_config
from plugins.memory.memory_os.context_router import plan_context_route
from plugins.memory.memory_os.index import MemoryOSIndex
from plugins.memory.memory_os.prefetch import build_prefetch
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore
home="/root/.hermes"
roots=MemoryOSRoots.from_hermes_home(home, profile="default")
store=MemoryOSStore(roots)
config=load_config(home)
cases=[
 ("deictic_yesterday","继续昨天那个。","", "ambiguous_recall", "Recall Clarification Guard"),
 ("deictic_just_now_no_punctuation","继续刚才那个","Current task: inspect ComfyUI layout_report.json.", "ambiguous_recall", "Recall Clarification Guard"),
 ("deictic_just_now_punctuation","继续刚才那个。","Current task: inspect ComfyUI layout_report.json.", "ambiguous_recall", "Recall Clarification Guard"),
 ("continue_current_task","继续当前任务","Current task: inspect ComfyUI layout_report.json.", "foreground_control", "Current Foreground Task"),
 ("explicit_deferred_en","continue the deferred task","Current task: inspect ComfyUI layout_report.json.", "foreground_control", "Current Foreground Task"),
 ("explicit_deferred_zh","继续搁置的任务","Current task: inspect ComfyUI layout_report.json.", "foreground_control", "Current Foreground Task"),
]
def guard_contract_ok(context):
    required=[
      "authoritative shortlist",
      "Do not create a competing shortlist from raw session_search/tool results.",
      "merge duplicate variants into the existing candidate topics",
      "ask for a keyword instead of guessing",
    ]
    return all(item in context for item in required)
summary=[]
for cid, query, anchor_text, expected_route, expected_heading in cases:
    anchor=("### Memory-OS Current Task Anchor\n- current task: "+anchor_text) if anchor_text else ""
    route=plan_context_route(query, current_task_anchor=anchor)
    context=build_prefetch(query, budget_chars=1600, store=store, index=MemoryOSIndex(roots), runtime_facts={"provider":"memory_os","prefetch_mode":"indexed"}, current_task_anchor=anchor, context_router_config=config.get("context_router"), low_clue_recall_config=config.get("low_clue_recall"))
    headings=re.findall(r"^### (.+)$", context, flags=re.M)
    summary.append({"id":cid,"query_class":str(route.get("route") or ""),"route":str(route.get("route") or ""),"reason_codes":route.get("reason_codes") or [],"chars":len(context),"headings":headings,"expected_route":expected_route,"expected_heading":expected_heading,"guard_contract_ok":guard_contract_ok(context) if expected_route == "ambiguous_recall" else None})
print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = "/root/.hermes/memory-os/runtime/python"
    r = run(["python3", "-c", code], env=env)
    return json.loads(r["out"]) if r["ok"] else {"_error": r["out"], "_code": r["code"]}

def deep_reflection_status():
    code = r"""
import json
from plugins.modules.cognition.deep_reflection import DeepReflectionModule
status = DeepReflectionModule("/root/.hermes", profile="default").status()
keys = [
  "enabled","injection_mode","working_updates_enabled","llm_enabled",
  "self_evolution_proposals_enabled","wandering_seed_enabled",
  "current_injection_exists","latest_injection_source_classes",
  "rolling_injection_source_classes","actual_send","actual_execute",
  "actual_identity_write","actual_crystallized_approval"
]
print(json.dumps({k:status.get(k) for k in keys if k in status}, ensure_ascii=False, sort_keys=True))
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = "/root/.hermes/memory-os/runtime/python"
    r = run(["python3", "-c", code], env=env)
    return json.loads(r["out"]) if r["ok"] else {"_error": r["out"], "_code": r["code"]}

def low_clue_recall_probe():
    cfg_path = Path("/root/.hermes/memory-os/config.json")
    cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
    low_clue_cfg = cfg.get("low_clue_recall") if isinstance(cfg.get("low_clue_recall"), dict) else {}
    judge = low_clue_cfg.get("llm_judge") if isinstance(low_clue_cfg.get("llm_judge"), dict) else {}
    judge_mode = "config" if judge.get("enabled") and judge.get("mode") == "report_only" else "none"
    report = load_json_cmd(["hermes", "memory-os-agent-os", "low-clue-recall", "dry-run", "--query", "继续昨天那个。", "--llm-judge", judge_mode])
    if isinstance(report, dict):
        internal_terms = (
          "ambiguous_recall",
          "casual_continuity",
          "foreground_control",
          "Current Foreground Task",
          "Recall Clarification Guard",
          "Conversation Carryover",
          "Working Memory",
          "Indexed Recall",
          "Recent Event Summaries",
          "Diagnostic Grounding",
        )
        candidates = report.get("candidates") if isinstance(report.get("candidates"), list) else []
        internal_label_source_classes = sorted({
          str(candidate.get("source_class") or "unknown")
          for candidate in candidates
          if any(term in str(candidate.get("label") or "") for term in internal_terms)
        })
        return {
          "schema_version": report.get("schema_version"),
          "decision": report.get("decision"),
          "candidate_count": report.get("candidate_count"),
          "reason_codes": report.get("reason_codes"),
          "llm_judge": report.get("llm_judge"),
          "internal_label_count": sum(
            1 for candidate in candidates
            if any(term in str(candidate.get("label") or "") for term in internal_terms)
          ),
          "internal_label_source_classes": internal_label_source_classes,
        }
    return report

def module_artifact_summary():
    report = load_json_cmd(["hermes", "memory-os-agent-os", "modules", "status"])
    if not isinstance(report, dict) or report.get("schema_version") != "memory-os.modules_status.v0":
        return {
          "schema_version": "memory-os.module_artifact_summary.v0",
          "status": "unavailable",
          "error": report.get("_error") if isinstance(report, dict) else "modules status unavailable",
        }
    modules = {}
    for item in report.get("modules", []) if isinstance(report.get("modules"), list) else []:
        if isinstance(item, dict):
            status = item.get("status") if isinstance(item.get("status"), dict) else {}
            modules[str(item.get("module") or "")] = status

    def status(module_id):
        return modules.get(module_id, {})

    digest = status("digest_consolidation")
    household = status("household_digest")
    wandering = status("wandering_mind")
    evidence = status("evidence_scoring")
    proposal = status("proposal_queue")
    self_evolution = status("self_evolution")
    governance = status("governance_feedback")
    deep_reflection = status("deep_reflection")
    ops_gate = status("ops_gate")
    speak_gate = status("speak_gate")
    mailbox = status("mailbox")
    return {
      "schema_version": "memory-os.module_artifact_summary.v0",
      "status": "ok",
      "module_count": report.get("module_count"),
      "digest": {
        "daily_artifact_count": digest.get("daily_artifact_count"),
        "weekly_artifact_count": digest.get("weekly_artifact_count"),
        "household_artifact_exists": household.get("artifact_exists"),
      },
      "wandering": {
        "output_count": len(_read_jsonl("/root/.hermes/system-modules/wandering_mind/outputs.jsonl")),
        "would_send_count": wandering.get("would_send_count"),
      },
      "evidence": {
        "evidence_count": evidence.get("evidence_count"),
        "score_count": evidence.get("score_count"),
        "subject_counts": evidence.get("subject_counts"),
      },
      "proposal_queue": {
        "candidate_count": proposal.get("candidate_count"),
        "state_counts": proposal.get("state_counts"),
      },
      "self_evolution": {
        "report_count": self_evolution.get("report_count"),
        "proposal_count": self_evolution.get("proposal_count"),
        "last_status": self_evolution.get("last_status"),
      },
      "governance_feedback": {
        "emitted_event_count": governance.get("emitted_event_count"),
      },
      "deep_reflection": {
        "report_count": deep_reflection.get("report_count"),
        "analysis_artifact_count": deep_reflection.get("analysis_artifact_count"),
        "current_injection_exists": deep_reflection.get("current_injection_exists"),
        "wandering_seed_count": len(_read_jsonl("/root/.hermes/system-modules/deep_reflection/wandering_seeds.jsonl")),
      },
      "ops_gate": {
        "report_count": ops_gate.get("report_count"),
        "blocked_decision_count": ops_gate.get("blocked_decision_count"),
      },
      "speak_gate": {
        "would_send_count": speak_gate.get("would_send_count"),
        "actual_send": speak_gate.get("actual_send"),
      },
      "mailbox": {
        "mailbox_exists": mailbox.get("mailbox_exists"),
        "would_send_count": mailbox.get("would_send_count"),
      },
    }

def expression_artifact_summary():
    modules = module_artifact_summary()
    wandering = modules.get("wandering") if isinstance(modules.get("wandering"), dict) else {}
    speak_gate = modules.get("speak_gate") if isinstance(modules.get("speak_gate"), dict) else {}
    reports = _read_jsonl("/root/.hermes/system-modules/cognitive_loop/reports.jsonl")
    wandering_result_count = 0
    wandering_would_send_result_count = 0
    wandering_silent_count = 0
    for report in reports:
        steps = report.get("steps") if isinstance(report.get("steps"), list) else []
        for step in steps:
            if not isinstance(step, dict) or step.get("step") != "wandering_mind":
                continue
            result = step.get("result") if isinstance(step.get("result"), dict) else {}
            wandering_result_count += 1
            if result.get("would_send") is True:
                wandering_would_send_result_count += 1
            if result.get("output") == "[SILENT]" or (result.get("would_send") is False and result.get("reason")):
                wandering_silent_count += 1
    return {
      "schema_version": "memory-os.expression_artifact_summary.v0",
      "wandering_output_count": wandering.get("output_count"),
      "wandering_would_send_count": wandering.get("would_send_count"),
      "wandering_result_count": wandering_result_count,
      "wandering_would_send_result_count": wandering_would_send_result_count,
      "wandering_silent_count": wandering_silent_count,
      "speak_gate_would_send_count": speak_gate.get("would_send_count"),
      "speak_gate_blocked_count": speak_gate.get("blocked_send_count", 0),
      "speak_gate_actual_send": speak_gate.get("actual_send"),
    }

def session_mirror_summary():
    status_report = load_json_cmd(["hermes", "memory-os-agent-os", "modules", "status"])
    dry_run = load_json_cmd(["hermes", "memory-os-agent-os", "modules", "run-once", "--module", "session_mirror", "--dry-run"])
    session_status = {}
    if isinstance(status_report, dict):
        for item in status_report.get("modules", []) if isinstance(status_report.get("modules"), list) else []:
            if isinstance(item, dict) and item.get("module") == "session_mirror":
                session_status = item.get("status") if isinstance(item.get("status"), dict) else {}
                break
    written_ids = dry_run.get("written_event_ids") if isinstance(dry_run, dict) and isinstance(dry_run.get("written_event_ids"), list) else []
    findings = dry_run.get("findings") if isinstance(dry_run, dict) and isinstance(dry_run.get("findings"), list) else []
    return {
      "schema_version": "memory-os.session_mirror_monitor_summary.v0",
      "status": session_status.get("status") or (dry_run.get("status") if isinstance(dry_run, dict) else None),
      "session_count": session_status.get("session_count") or (dry_run.get("session_count") if isinstance(dry_run, dict) else None),
      "covered_session_count": session_status.get("covered_session_count") or (dry_run.get("covered_session_count") if isinstance(dry_run, dict) else None),
      "pending_session_count": session_status.get("pending_session_count"),
      "sessions_root_present": session_status.get("sessions_root_present"),
      "state_db_present": session_status.get("state_db_present"),
      "dry_run_schema_version": dry_run.get("schema_version") if isinstance(dry_run, dict) else None,
      "dry_run_status": dry_run.get("status") if isinstance(dry_run, dict) else None,
      "dry_run_new_event_count": dry_run.get("new_event_count") if isinstance(dry_run, dict) else None,
      "dry_run_written_event_ids_count": len(written_ids),
      "dry_run_findings_count": len(findings),
    }

def shell_alias_no_env():
    status = load_json_cmd(["hermes", "memory-os-agent-os", "status"])
    doctor = load_json_cmd(["hermes", "memory-os-agent-os", "doctor"])
    memory_sources = load_json_cmd(["hermes", "memory-os-agent-os", "memory-sources", "stats", "--hours", "24"])
    metadata_retention = load_json_cmd(["hermes", "memory-os-agent-os", "metadata-retention"])
    low_clue = load_json_cmd(["hermes", "memory-os-agent-os", "low-clue-recall", "dry-run", "--query", "继续昨天那个。", "--llm-judge", "none"])
    modules = load_json_cmd(["hermes", "memory-os-agent-os", "modules", "status"])
    eval_report = load_json_cmd(["hermes", "memory-os-agent-os", "eval", "rh31", "run", "--fixture", "synthetic", "--adapter", "all", "--no-write-report"])
    review = load_json_cmd(["hermes", "memory-os-agent-os", "review", "status"])
    review_aging = load_json_cmd(["hermes", "memory-os-agent-os", "review", "aging-report"])
    review_channel = load_json_cmd(["hermes", "memory-os-agent-os", "review", "channel"])
    review_cron_status = load_json_cmd(["hermes", "memory-os-agent-os", "review", "cron-status"])
    review_delivery_status = load_json_cmd(["hermes", "memory-os-agent-os", "review", "delivery-status"])
    review_delivery_gate = load_json_cmd(["hermes", "memory-os-agent-os", "review", "delivery-gate"])
    review_followups = load_json_cmd(["hermes", "memory-os-agent-os", "review", "proposal-followups"])
    review_digest = load_json_cmd(["hermes", "memory-os-agent-os", "review", "preview-digest"])
    review_render = load_json_cmd(["hermes", "memory-os-agent-os", "review", "render-digest"])
    review_reply = load_json_cmd(["hermes", "memory-os-agent-os", "review", "reply", "memory", "approve", "oa_deadbeef"])
    return {
      "status_ok": isinstance(status, dict) and status.get("schema_version") == "memory-os.status.v0",
      "doctor_ok": isinstance(doctor, dict) and doctor.get("schema_version") == "memory-os.doctor.v0" and doctor.get("status") == "ok",
      "memory_sources_ok": isinstance(memory_sources, dict) and memory_sources.get("schema_version") == "memory-os.memory_sources_stats.v0",
      "metadata_retention_ok": isinstance(metadata_retention, dict) and metadata_retention.get("schema_version") == "memory-os.metadata_retention_plan.v0",
      "low_clue_recall_ok": isinstance(low_clue, dict) and low_clue.get("schema_version") == "memory-os.low_clue_recall.v0",
      "modules_ok": isinstance(modules, dict) and modules.get("schema_version") == "memory-os.modules_status.v0",
      "eval_ok": isinstance(eval_report, dict) and eval_report.get("schema_version") == "memory-os.rh31_summary.v0",
      "review_ok": isinstance(review, dict) and review.get("schema_version") == "memory-os.owner_review_status.v0",
      "review_aging_ok": isinstance(review_aging, dict) and review_aging.get("schema_version") == "memory-os.owner_review_aging.v0",
      "review_channel_ok": isinstance(review_channel, dict) and review_channel.get("schema_version") == "memory-os.owner_review_channel.v0",
      "review_cron_status_ok": isinstance(review_cron_status, dict) and review_cron_status.get("schema_version") == "memory-os.owner_review_cron_integration.v0",
      "review_delivery_status_ok": isinstance(review_delivery_status, dict) and review_delivery_status.get("schema_version") == "memory-os.owner_review_delivery_status.v0",
      "review_delivery_gate_ok": isinstance(review_delivery_gate, dict) and review_delivery_gate.get("schema_version") == "memory-os.owner_review_delivery_gate.v0",
      "review_followups_ok": isinstance(review_followups, dict) and review_followups.get("schema_version") == "memory-os.approved_proposal_followups.v0",
      "review_digest_ok": isinstance(review_digest, dict) and review_digest.get("schema_version") == "memory-os.owner_review_digest_preview.v0",
      "review_render_ok": isinstance(review_render, dict) and review_render.get("schema_version") == "memory-os.owner_review_rendered_digest.v0",
      "review_reply_ok": isinstance(review_reply, dict) and review_reply.get("schema_version") == "memory-os.owner_review_reply.v0",
      "status_error": status.get("_error") if isinstance(status, dict) else None,
      "doctor_error": doctor.get("_error") if isinstance(doctor, dict) else None,
      "memory_sources_error": memory_sources.get("_error") if isinstance(memory_sources, dict) else None,
      "metadata_retention_error": metadata_retention.get("_error") if isinstance(metadata_retention, dict) else None,
      "low_clue_recall_error": low_clue.get("_error") if isinstance(low_clue, dict) else None,
      "modules_error": modules.get("_error") if isinstance(modules, dict) else None,
      "eval_error": eval_report.get("_error") if isinstance(eval_report, dict) else None,
      "review_error": review.get("_error") if isinstance(review, dict) else None,
      "review_aging_error": review_aging.get("_error") if isinstance(review_aging, dict) else None,
      "review_channel_error": review_channel.get("_error") if isinstance(review_channel, dict) else None,
      "review_cron_status_error": review_cron_status.get("_error") if isinstance(review_cron_status, dict) else None,
      "review_delivery_status_error": review_delivery_status.get("_error") if isinstance(review_delivery_status, dict) else None,
      "review_delivery_gate_error": review_delivery_gate.get("_error") if isinstance(review_delivery_gate, dict) else None,
      "review_followups_error": review_followups.get("_error") if isinstance(review_followups, dict) else None,
      "review_digest_error": review_digest.get("_error") if isinstance(review_digest, dict) else None,
      "review_render_error": review_render.get("_error") if isinstance(review_render, dict) else None,
      "review_reply_error": review_reply.get("_error") if isinstance(review_reply, dict) else None,
    }

def owner_review_rendered_digest_summary():
    report = memory_os_cli(["review", "render-digest", "--max-action-required", "2", "--max-review-suggested", "2", "--max-fyi", "2"])
    if not isinstance(report, dict) or report.get("_error"):
        return report
    text = str(report.get("text") or "")
    sections = report.get("sections") if isinstance(report.get("sections"), dict) else {}
    return {
      "schema_version": report.get("schema_version"),
      "status": report.get("status"),
      "will_send": report.get("will_send"),
      "raw_body_included": report.get("raw_body_included"),
      "text_char_count": len(text),
      "text_has_internal_schema": any(token in text for token in ("Candidate kind=", "source_events=", "sensitivity=")),
      "text_has_transcript_marker": any(token in text for token in ("User:", "Assistant:", "用户:", "助手:", "用户：", "助手：", "| Assistant:", "| User:")),
      "section_counts": {key: len(value) for key, value in sections.items() if isinstance(value, list)},
      "anchors": {
        key: [str(item.get("anchor") or "") for item in value if isinstance(item, dict)]
        for key, value in sections.items()
        if isinstance(value, list)
      },
      "boundary": report.get("boundary") if isinstance(report.get("boundary"), dict) else {},
    }

def owner_review_reply_dry_run_summary():
    command = _latest_recorded_owner_command()
    command_source = "latest_recorded_digest" if command else ""
    if not command:
        command_source = "fresh_render_no_record"
        rendered = memory_os_cli(["review", "render-digest", "--max-action-required", "2", "--max-review-suggested", "2", "--max-fyi", "2"])
        if isinstance(rendered, dict):
            command = _first_rendered_action_command(rendered)
    if not command:
        return {
          "schema_version": "memory-os.owner_review_reply.v0",
          "status": "needs_clarification",
          "dry_run": True,
          "reason": "no_action_command_available",
          "command_source": command_source,
        }
    report = memory_os_cli(["review", "reply", *command.split(), "--max-action-required", "2", "--max-review-suggested", "2", "--max-fyi", "2"])
    if not isinstance(report, dict) or report.get("_error"):
        return report
    parsed = report.get("parsed") if isinstance(report.get("parsed"), dict) else {}
    owner_action = report.get("owner_action_result") if isinstance(report.get("owner_action_result"), dict) else {}
    return {
      "schema_version": report.get("schema_version"),
      "status": report.get("status"),
      "dry_run": report.get("dry_run"),
      "reason": report.get("reason"),
      "command_source": command_source,
      "parsed_action_type": parsed.get("action_type"),
      "parsed_target_type": parsed.get("target_type"),
      "owner_action_status": owner_action.get("status"),
      "owner_action_dry_run": owner_action.get("dry_run"),
      "boundary": report.get("boundary") if isinstance(report.get("boundary"), dict) else {},
    }

def _first_rendered_action_command(rendered):
    for items in (rendered.get("sections") or {}).values():
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            commands = item.get("action_commands") if isinstance(item.get("action_commands"), list) else []
            command = str(commands[0] if commands else "")
            if command:
                return command
    return ""

def _latest_recorded_owner_command():
    path = Path("/root/.hermes/memory-os/system/owner_review_rendered_digests.jsonl")
    if not path.exists():
        return ""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return ""
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except Exception:
            continue
        digest = record.get("rendered_digest") if isinstance(record.get("rendered_digest"), dict) else {}
        command = _first_rendered_action_command(digest)
        if command:
            return command
    return ""

def owner_review_ingress_guard_summary():
    env = dict(os.environ)
    env["HERMES_HOME"] = "/root/.hermes"
    env["PYTHONPATH"] = "/root/.hermes/memory-os/runtime/python:/root/.hermes/plugins:" + env.get("PYTHONPATH", "")
    code = """
import json
from plugins.memory.memory_os.__init__ import _looks_like_owner_review_reply
cases = {
    "legacy_anchor_accepted": _looks_like_owner_review_reply("approve A2"),
    "legacy_reject_anchor_accepted": _looks_like_owner_review_reply("reject R1"),
    "ordinary_anchor_text_accepted": _looks_like_owner_review_reply("普通聊天里提到 approve A2"),
    "token_command_accepted": _looks_like_owner_review_reply("memory approve oa_12345678"),
    "slash_token_command_accepted": _looks_like_owner_review_reply("/memory reject oa_12345678"),
    "feedback_token_command_accepted": _looks_like_owner_review_reply("memory feedback oa_12345678 too_mechanistic"),
}
print(json.dumps({"schema_version": "memory-os.owner_review_ingress_guard.v0", **cases}, ensure_ascii=False, sort_keys=True))
"""
    report = load_json_cmd(["python3", "-c", code], env=env)
    if isinstance(report, dict) and report.get("_error"):
        report.setdefault("schema_version", "memory-os.owner_review_ingress_guard.v0")
    return report

status = load_json_cmd(["hermes", "memory-os-agent-os", "status"])
doctor = load_json_cmd(["hermes", "memory-os-agent-os", "doctor"])
contract = memory_os_cli(["conversation-regression", "status-tool-contract"])
memory_sources = memory_os_cli(["memory-sources", "stats", "--hours", "24"])
memory_sources = enrich_memory_sources_stats(memory_sources)
rh31_eval = memory_os_cli(["eval", "rh31", "run", "--fixture", "synthetic", "--adapter", "all", "--no-write-report"])
owner_review = memory_os_cli(["review", "status"])
owner_review_aging = memory_os_cli(["review", "aging-report"])
owner_review_channel = memory_os_cli(["review", "channel"])
owner_review_cron_integration = memory_os_cli(["review", "cron-status"])
owner_review_delivery_status = memory_os_cli(["review", "delivery-status"])
owner_review_delivery_gate = memory_os_cli(["review", "delivery-gate"])
owner_review_proposal_followups = memory_os_cli(["review", "proposal-followups", "--limit", "10"])
owner_review_digest_preview = memory_os_cli(["review", "preview-digest"])
owner_review_rendered_digest = owner_review_rendered_digest_summary()
owner_review_reply_dry_run = owner_review_reply_dry_run_summary()
owner_review_ingress_guard = owner_review_ingress_guard_summary()
cfg_path = Path("/root/.hermes/memory-os/config.json")
cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
df = run(["df", "-h", "/root/.hermes/memory-os"])["out"]
du = run(["du", "-sh", "/root/.hermes/memory-os"])["out"]
heartbeat_list = run(["systemctl", "--user", "list-timers", "hermes-memory-os-heartbeat.timer", "--no-pager"])["out"]

print(json.dumps({
  "hostname": run(["hostname"])["out"],
  "date_utc": run(["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"])["out"],
  "date_local": run(["date", "+%Y-%m-%d %H:%M:%S %Z"])["out"],
  "gateway": system_show("hermes-gateway.service"),
  "heartbeat_timer": system_show("hermes-memory-os-heartbeat.timer"),
  "heartbeat_service": system_show("hermes-memory-os-heartbeat.service"),
  "heartbeat_state": heartbeat_state(),
  "heartbeat_listed": "hermes-memory-os-heartbeat.timer" in heartbeat_list,
  "cognitive_loop_timer": system_show("hermes-memory-os-cognitive-loop.timer"),
  "cognitive_loop_service": system_show("hermes-memory-os-cognitive-loop.service"),
  "cognitive_loop_listed": "hermes-memory-os-cognitive-loop.timer" in run(["systemctl", "--user", "list-timers", "hermes-memory-os-cognitive-loop.timer", "--no-pager"])["out"],
  "memory_status": {
    "counts": status.get("counts") if isinstance(status, dict) else None,
    "index_health": status.get("index_health") if isinstance(status, dict) else None,
    "prefetch_mode": status.get("prefetch_mode") if isinstance(status, dict) else None,
    "hindsight_adapter_enabled": status.get("hindsight_adapter_enabled") if isinstance(status, dict) else None,
    "queue_backlog": status.get("queue_backlog") if isinstance(status, dict) else None,
  },
  "doctor": {
    "status": doctor.get("status") if isinstance(doctor, dict) else None,
    "exit_code": doctor.get("exit_code") if isinstance(doctor, dict) else None,
    "findings": [(x.get("code"), x.get("severity")) for x in doctor.get("findings", [])] if isinstance(doctor, dict) else None,
  },
  "status_tool_contract": contract.get("validation") if isinstance(contract, dict) else contract,
  "shell_alias_no_env": shell_alias_no_env(),
  "cognitive_loop": memory_os_cli(["cognitive-loop", "status"]),
  "memory_sources": memory_sources,
  "rh31_eval": rh31_eval,
  "owner_review": owner_review,
  "owner_review_aging": owner_review_aging,
  "owner_review_channel": owner_review_channel,
  "owner_review_cron_integration": owner_review_cron_integration,
  "owner_review_delivery_status": owner_review_delivery_status,
  "owner_review_delivery_gate": owner_review_delivery_gate,
  "owner_review_proposal_followups": owner_review_proposal_followups,
  "owner_review_digest_preview": owner_review_digest_preview,
  "owner_review_rendered_digest": owner_review_rendered_digest,
  "owner_review_reply_dry_run": owner_review_reply_dry_run,
  "owner_review_ingress_guard": owner_review_ingress_guard,
  "module_artifacts": module_artifact_summary(),
  "expression_artifacts": expression_artifact_summary(),
  "session_mirror": session_mirror_summary(),
  "audit_actions": audit_action_stats(),
  "working_status": working_status(),
  "context_router": cfg.get("context_router", {}),
  "low_clue_recall_config": cfg.get("low_clue_recall", {}),
  "low_clue_recall": low_clue_recall_probe(),
  "low_clue_ingress_matrix": low_clue_ingress_matrix(),
  "rh26_apply_probe": rh26_probe(),
  "deep_reflection": deep_reflection_status(),
  "hook_markers": hook_marker_counts(),
  "session_activity": session_activity_stats(),
  "compaction": compaction_stats(),
  "disk_df": df,
  "disk_du": du,
}, ensure_ascii=False, sort_keys=True))
'''


if __name__ == "__main__":
    raise SystemExit(main())
