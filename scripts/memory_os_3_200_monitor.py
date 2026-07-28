"""Read-only Memory-OS monitor for the 10.20.3.200 test host.

The script intentionally reports metadata, counters, headings, and trend
signals only. It must not print raw event summaries, private transcript bodies,
or selected context text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
IMPORT_ROOT = (
    REPO_ROOT
    if (REPO_ROOT / "plugins" / "modules").is_dir()
    else REPO_ROOT / "memory-os" / "runtime" / "python"
)
if str(IMPORT_ROOT) not in sys.path:
    sys.path.insert(0, str(IMPORT_ROOT))

from plugins.memory.memory_os.permanent_promotion import read_permanent_promotion_ledger_counts
from plugins.modules.governance.live_guard import live_guard_registration_report
from plugins.seam.hermes_memory_os.host_capability_adapter import (
    HOST_CAPABILITY_ALLOWED_STATUSES,
    HOST_CAPABILITY_REQUIRED_FIELDS,
    HOST_CAPABILITY_REQUIRED_KEYS,
)
try:
    from scripts.memory_os_host_profile import resolve_host_runtime_profile
except ModuleNotFoundError:
    from memory_os_host_profile import resolve_host_runtime_profile


EXPECTED_RH26_HEADINGS: dict[str, list[str]] = {
    "cancel_failed_video": ["Current Foreground Task"],
    "continue_current_task": ["Current Foreground Task"],
    "casual_memory_system_change": [],
    "diagnostic_current_architecture": ["Diagnostic Grounding", "Current Memory-OS Runtime Facts"],
    "candidate_vs_crystallized": ["Crystallized Review Candidates", "Crystallized Memory"],
    "active_comfyui_install": ["Current Foreground Task", "Indexed Recall"],
    "deferred_cancellation": ["Current Foreground Task"],
}
ALLOWED_RH26_EXTRA_HEADINGS: dict[str, set[str]] = {
    "candidate_vs_crystallized": {"Indexed Recall"},
    "active_comfyui_install": {"Working Memory", "Crystallized Memory", "Recent Event Summaries"},
}
SAFE_CASUAL_HEADINGS = {"Conversation Carryover", "Recent Event Summaries"}
FORBIDDEN_CASUAL_HEADINGS = {
    "Current Foreground Task",
    "Diagnostic Grounding",
    "Current Memory-OS Runtime Facts",
    "Crystallized Review Candidates",
}

V7_GOVERNANCE_COMPONENTS = (
    "promotion_matrix",
    "live_guard_registry",
    "eval_adapter_registry",
    "derived_evidence_profile",
    "confidence_router",
    "judge_calibration",
    "candidate_review",
    "shadow_recall",
    "provisional",
    "cascade_routing_policy",
    "migration_controller",
    "symbolic_offloader",
    "abstraction_distillation",
    "retractable_label_miner",
    "imagination_loop",
    "confabulation_detector",
    "crystallized_revalidator",
    "grounded_expression_judge",
)
V7_OPTIONAL_COMPONENT_REASONS = {
    "symbolic_offloader": "optional_audit_level_default_disabled",
}
V7_REQUIRED_COMPONENTS_PRODUCTION = tuple(
    component for component in V7_GOVERNANCE_COMPONENTS if component not in V7_OPTIONAL_COMPONENT_REASONS
)
V7_ACTING_AUTONOMY_LEVELS = {"owner_approved_apply", "autonomous_acting"}
V7_MEMORY_SOURCES_FEEDBACK_CANARY_TARGET = 20
INDEX_CATCHUP_MAX_AGE_SECONDS = 900
INDEX_CATCHUP_MAX_EVENT_BACKLOG = 1
FULL_MONITOR_LIVE_TARGET_SECONDS = 180
FULL_MONITOR_CLEAN_HOST_TARGET_SECONDS = 240
FULL_MONITOR_MIN_CALLER_TIMEOUT_SECONDS = 300
FAST_PROBE_RECOMMENDED_TIMEOUT_SECONDS = 120
MEMORY_PROJECTION_55C_REQUIRED_PAYLOAD_FIELDS: dict[str, set[str]] = {
    "hindsight_provider_stats": {
        "operation_count",
        "retain_count",
        "recall_count",
        "projection_stale_count",
        "raw_retained_count",
    },
    "mailbox_status": {
        "mailbox_exists",
        "inbox_count",
        "outbox_count",
        "would_send_count",
        "actual_send_count",
    },
    "wandering_mind_state": {
        "state_exists",
        "output_count",
        "would_send_count",
        "latest_output_at",
        "actual_send_count",
    },
    "mcp_server_health": {
        "config_file_count",
        "configured_server_count",
        "directory_server_count",
        "failed_server_count",
    },
    "runtime_logs": {
        "log_file_count",
        "latest_log_age_seconds",
        "error_log_exists",
        "gateway_log_exists",
        "rotated_log_count",
    },
}
MEMORY_PROJECTION_55D_REQUIRED_PAYLOAD_FIELDS: dict[str, set[str]] = {
    "cognitive_loop_status": {
        "report_count",
        "latest_cycle_id",
        "step_count",
        "error_step_count",
        "required_step_missing_count",
    },
    "gateway_runtime_status": {
        "heartbeat_state_exists",
        "heartbeat_age_seconds",
        "processed_event_count",
        "gateway_capability_status",
        "gateway_log_exists",
    },
    "proposal_queue_pressure": {
        "proposal_count",
        "state_candidate_count",
        "approved_for_proposal_count",
        "awaiting_ops_gate_count",
        "actual_execute_count",
    },
    "candidate_queue_pressure": {
        "candidate_count",
        "private_candidate_count",
        "public_candidate_count",
        "latest_candidate_at",
        "source_event_ref_count",
    },
    "owner_review_pressure": {
        "owner_action_count",
        "action_required_estimate_count",
        "review_suggested_estimate_count",
        "advisor_finding_count",
        "pending_candidate_count",
        "pending_proposal_count",
    },
}
MEMORY_PROJECTION_55E_REQUIRED_PAYLOAD_FIELDS: dict[str, set[str]] = {
    "skills_inventory": {
        "skill_count",
        "skill_directory_count",
        "skill_file_count",
        "skill_manifest_count",
        "latest_skill_age_seconds",
    },
    "profile_config": {
        "profile_id",
        "config_exists",
        "config_file_count",
        "profile_count",
        "memory_provider_configured",
        "hindsight_provider_configured",
        "channel_config_count",
        "model_config_present",
    },
    "kanban_state": {
        "card_count",
        "column_count",
        "open_card_count",
        "done_card_count",
        "latest_card_age_seconds",
    },
    "tool_registry": {
        "tool_count",
        "plugin_count",
        "mcp_tool_count",
        "tool_manifest_count",
        "tool_config_exists",
        "latest_tool_age_seconds",
    },
}
MEMORY_PROJECTION_55F_REQUIRED_PAYLOAD_FIELDS: dict[str, set[str]] = {
    "host_capability_contract": {
        "capability_count",
        "required_capability_count",
        "missing_required_capability_count",
        "incomplete_capability_count",
        "invalid_status_count",
        "contract_status",
        "migration_needed_count",
        "adapter_required_count",
        "adapter_missing_count",
        "owner_channel_status",
        "memory_provider_status",
        "memory_provider_name",
        "hindsight_status",
        "structural_write_gate_status",
        "execution_gate_status",
        "cron_status",
        "deployment_status",
        "deployed_head_present",
        "active_runtime_version_present",
        "hermes_version_available",
    },
}
MEMORY_PROJECTION_55G_REQUIRED_PAYLOAD_FIELDS: dict[str, set[str]] = {
    "hindsight_governance_signals": {
        "suggestion_count",
        "curation_review_suggested_count",
        "curation_decision_count",
        "retain_decision_count",
        "reject_decision_count",
        "demote_decision_count",
    },
    "hermes_session_index": {
        "session_file_count",
        "conversation_file_count",
        "session_event_count",
        "recent_session_event_count",
        "platform_count",
        "latest_session_age_seconds",
    },
    "hindsight_bank_inventory": {
        "bank_directory_count",
        "bank_file_count",
        "strategy_file_count",
        "latest_bank_age_seconds",
        "substrate_operation_count",
        "memory_os_config_present",
        "raw_payload_file_count",
    },
    "mailbox_delivery_trace": {
        "delivery_record_count",
        "owner_channel_delivery_count",
        "failed_delivery_count",
        "latest_delivery_at",
        "latest_failure_at",
        "cron_output_file_count",
        "cooldown_marker_count",
    },
    "wandering_mind_cadence": {
        "state_exists",
        "cadence_config_present",
        "latest_output_age_seconds",
        "generated_count",
        "skipped_count",
        "would_send_pending_count",
        "cooldown_active",
    },
    "mcp_tool_inventory": {
        "server_name_count",
        "stdio_server_count",
        "http_server_count",
        "disabled_server_count",
        "tool_candidate_count",
        "config_file_count",
        "latest_config_age_seconds",
    },
}
CLEAN_HOST_WARN_CLASSIFICATIONS: dict[str, dict[str, str]] = {
    "left_brain_pipeline_check_warn": {
        "classification": "next_lane",
        "reason": "left_brain_pipeline is present but still reports warning on clean-host warmup",
        "production_behavior": "warn_if_production",
    },
    "left_brain_proposal_agenda_trace_missing": {
        "classification": "next_lane",
        "reason": "agenda trace coverage is a V7 quality lane, not a clean-host install blocker",
        "production_behavior": "warn_if_production",
    },
    "grounded_expression_alternate_left_map_substrate_pending": {
        "classification": "next_lane",
        "reason": "alternate-left-map substrate evidence can be pending before clean-host traffic warms up",
        "production_behavior": "warn_if_production",
    },
    "module_cadence_split_pending": {
        "classification": "next_lane",
        "reason": "module cadence split evidence is historical/current semantics cleanup",
        "production_behavior": "warn_if_production",
    },
    "right_brain_review_speak_preview_missing": {
        "classification": "next_lane",
        "reason": "right-brain speak preview is a product live lane, not a clean-host install blocker",
        "production_behavior": "warn_if_production",
    },
    "right_brain_expression_outcome_missing": {
        "classification": "expected_clean_host",
        "reason": "clean-host can render right-brain prompts before a Hermes-delivered outcome exists",
        "production_behavior": "warn_if_production",
    },
    "index_not_healthy": {
        "classification": "expected_clean_host",
        "reason": "clean-host can be inspected before indexed recall has warmed; production must keep the index healthy",
        "production_behavior": "fail_if_production",
    },
    "index_catchup_pending": {
        "classification": "bounded_catchup",
        "reason": "index is behind but heartbeat/write age are still inside the bounded catch-up window",
        "production_behavior": "warn_if_production",
    },
    "monitor_error_observability_suppressed_errors": {
        "classification": "expected_clean_host",
        "reason": "clean-host can expose bounded component suppressed-error counters without proving runtime unhealthy",
        "production_behavior": "warn_if_production",
    },
    "doctor_warning_finding": {
        "classification": "expected_clean_host",
        "reason": "clean-host can surface non-blocking doctor warnings during bootstrap compatibility checks",
        "production_behavior": "warn_if_production",
    },
    "context_router_not_apply": {
        "classification": "expected_clean_host",
        "reason": "clean-host compatibility may run without production apply routing",
        "production_behavior": "fail_if_production",
    },
    "memory_sources_feedback_volume_missing": {
        "classification": "next_lane",
        "reason": "MemorySources owner feedback volume is accumulated through owner-channel activation",
        "production_behavior": "warn_if_production",
    },
    "v7_memory_sources_feedback_volume_pending": {
        "classification": "next_lane",
        "reason": "V7 owner-signal canary volume is a promotion lane, not a clean-host install blocker",
        "production_behavior": "warn_if_production",
    },
    "session_mirror_pending_source_gap": {
        "classification": "next_lane",
        "reason": "clean-host pending-only sessions need owner decision or bounded apply only if tied to recall/candidate gaps",
        "production_behavior": "warn_if_production",
    },
    "owner_review_proposal_auto_route_boundary_requires_owner": {
        "classification": "expected_clean_host",
        "reason": "proposal follow-up auto-route correctly stops at owner-boundary items on clean-host",
        "production_behavior": "warn_if_production",
    },
    "owner_review_approved_proposals_pending_followup": {
        "classification": "next_lane",
        "reason": "clean-host may contain approved proposal follow-ups before the local OpsGate/report-only lane catches up",
        "production_behavior": "warn_if_production",
    },
    "execution_gate_memory_os_cron_known_optional_enabled_outside_active_registry": {
        "classification": "expected_clean_host",
        "reason": "clean-host may retain enabled legacy optional Memory-OS cron jobs until active-closure onboarding is applied",
        "production_behavior": "fail_if_production",
    },
    "cognitive_loop_step_evidence_missing": {
        "classification": "expected_clean_host",
        "reason": "clean-host may be inspected before a persisted cognitive-loop report exists",
        "production_behavior": "fail_if_production",
    },
    "memory_projection_freshness_missing": {
        "classification": "expected_clean_host",
        "reason": "clean-host may not have a post-deploy projection artifact before the cognitive-loop lane warms",
        "production_behavior": "fail_if_production",
    },
    "memory_projection_stale_after_deploy": {
        "classification": "expected_clean_host",
        "reason": "clean-host compatibility smoke is not equivalent to 53 production live closure until a post-deploy projection cycle runs",
        "production_behavior": "fail_if_production",
    },
    "memory_projection_retention_compaction_missing": {
        "classification": "expected_clean_host",
        "reason": "clean-host projection retention can be un-compacted before enough signal volume accumulates",
        "production_behavior": "warn_if_production",
    },
    "memory_sources_stats_unavailable": {
        "classification": "expected_clean_host",
        "reason": "clean-host may not have MemorySources stats before live traffic and feedback are generated",
        "production_behavior": "warn_if_production",
    },
    "low_clue_recall_probe_unavailable": {
        "classification": "expected_clean_host",
        "reason": "clean-host compatibility does not require the low-clue recall probe to be warmed",
        "production_behavior": "warn_if_production",
    },
    "clean_host_v7_required_components_missing": {
        "classification": "fail_if_production",
        "reason": "clean-host can surface missing V7 required components, production must not hide them",
        "production_behavior": "fail_if_production",
    },
    "clean_host_v7_optional_component_intentionally_absent": {
        "classification": "expected_clean_host",
        "reason": "optional V7 component is intentionally absent with an explicit reason",
        "production_behavior": "warn_if_production",
    },
    "clearance_snapshot_not_fresh": {
        "classification": "expected_clean_host",
        "reason": "clean-host may not have a fresh clearance snapshot before V2C unfreeze readiness accumulates",
        "production_behavior": "warn_if_production",
    },
    "v2_exposure_monitor_collection_failed": {
        "classification": "expected_clean_host",
        "reason": "clean-host remote projection collection (SSH/runtime) may be unavailable during compatibility smoke",
        "production_behavior": "fail_if_production",
    },
    "clearance_snapshot_freshness_collection_failed": {
        "classification": "expected_clean_host",
        "reason": "clean-host remote projection collection (SSH/runtime) may be unavailable during compatibility smoke",
        "production_behavior": "fail_if_production",
    },
    "living_memory_promotion_ledger_state_collection_failed": {
        "classification": "expected_clean_host",
        "reason": "clean-host remote projection collection (SSH/runtime) may be unavailable during compatibility smoke",
        "production_behavior": "fail_if_production",
    },
    "living_memory_stale_open_evaluation_unavailable": {
        "classification": "expected_clean_host",
        "reason": "clean-host may not have a warmed crystallized-record store, so stale-open evaluation can be unavailable during compatibility smoke",
        "production_behavior": "fail_if_production",
    },
}


def _strip_degradation_suffix(heading: str) -> str:
    """Strip degradation annotation suffix for heading contract matching.

    prefetch.py appends informational suffixes such as
    ``"Crystallized Memory (deterministic floor recall)"`` when the
    embedding / FTS5 retrieval runs at degradation level >= 2.  The
    suffix is runtime metadata — not part of the heading contract — and
    is already stripped by ``_section_source_class`` and
    ``_budget_keep_priority`` (prefetch.py).  This function applies the
    same normalization to probe response headings so the comparison is
    "contract heading" to "contract heading".
    """
    return heading.split(" (")[0] if " (" in heading else heading


def find_rh26_heading_anomalies(probes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    anomalies: list[dict[str, Any]] = []
    for probe in probes:
        prompt_id = str(probe.get("id") or "")
        # Normalize away degradation suffixes so "Crystallized Memory
        # (deterministic floor recall)" matches the contract heading
        # "Crystallized Memory" (see _strip_degradation_suffix).
        actual = [_strip_degradation_suffix(h) for h in (probe.get("headings") or [])]
        expected_raw = EXPECTED_RH26_HEADINGS.get(prompt_id)
        if expected_raw is None:
            continue
        expected = [_strip_degradation_suffix(h) for h in expected_raw]
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
        allowed_raw = set(expected_raw) | ALLOWED_RH26_EXTRA_HEADINGS.get(prompt_id, set())
        allowed = {_strip_degradation_suffix(h) for h in allowed_raw}
        missing_expected = [h for h in expected if h not in actual]
        extra_unexpected = [h for h in actual if h not in allowed]

        if missing_expected:
            # Missing a required heading — hard fail (the probe response is
            # structurally incomplete, likely indicating a real problem).
            anomalies.append(
                {
                    "id": prompt_id,
                    "severity": "fail",
                    "code": "rh26_missing_expected_heading",
                    "expected": expected,
                    "actual": actual,
                    "missing": missing_expected,
                }
            )
        elif extra_unexpected:
            # Extra heading that isn't in the allowed set — warning only.
            # Heading drift (e.g. a new prefetch section appearing) is a
            # content-level signal, not a service-health failure.  The
            # heading should be reviewed and either added to
            # ALLOWED_RH26_EXTRA_HEADINGS or investigated.
            anomalies.append(
                {
                    "id": prompt_id,
                    "severity": "warning",
                    "code": "rh26_extra_unexpected_heading",
                    "expected": expected,
                    "actual": actual,
                    "extra": extra_unexpected,
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
    failure_attribution = _rh31_failure_attribution(summary)
    live_guard_candidate_count = sum(
        1 for item in failure_attribution if item.get("guard_decision") == "candidate_live_guard"
    )
    compact = {
        "schema_version": summary.get("schema_version"),
        "status": summary.get("status"),
        "adapter_count": summary.get("adapter_count"),
        "case_count": summary.get("case_count"),
        "score_count": summary.get("score_count"),
        "failure_count": summary.get("failure_count"),
        "failure_class_distribution": summary.get("failure_class_distribution") or {},
        "failure_attribution": failure_attribution,
        "live_guard_candidate_count": live_guard_candidate_count,
        "measurement_signal_count": len(failure_attribution) - live_guard_candidate_count,
        "boundary_true_count": summary.get("boundary_true_count"),
        "forbidden_field_count": summary.get("forbidden_field_count"),
        "report_written": bool(summary.get("report_dir")),
        "source_distribution": summary.get("source_distribution") or {},
    }
    retrieval_shadow = _rh31_retrieval_shadow_summary(summary)
    if retrieval_shadow:
        compact["retrieval_shadow"] = retrieval_shadow
    return compact


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _count_deltas(store_counts: dict[str, Any], index_counts: dict[str, Any]) -> dict[str, int]:
    keys = sorted(set(store_counts) | set(index_counts))
    deltas: dict[str, int] = {}
    for key in keys:
        store_value = _optional_int(store_counts.get(key)) or 0
        index_value = _optional_int(index_counts.get(key)) or 0
        deltas[key] = store_value - index_value
    return deltas


def index_catchup_contract(snapshot: dict[str, Any]) -> dict[str, Any]:
    memory_status = snapshot.get("memory_status") if isinstance(snapshot.get("memory_status"), dict) else {}
    index_health = (
        memory_status.get("index_health") if isinstance(memory_status.get("index_health"), dict) else {}
    )
    store_counts = memory_status.get("counts") if isinstance(memory_status.get("counts"), dict) else {}
    index_counts = memory_status.get("index_counts") if isinstance(memory_status.get("index_counts"), dict) else {}
    count_deltas = _count_deltas(store_counts, index_counts) if index_counts else {}
    heartbeat_state = (
        snapshot.get("heartbeat_state") if isinstance(snapshot.get("heartbeat_state"), dict) else {}
    )
    observed_max_age_seconds = _optional_int(heartbeat_state.get("max_age_seconds"))
    max_age_seconds = (
        min(observed_max_age_seconds, INDEX_CATCHUP_MAX_AGE_SECONDS)
        if observed_max_age_seconds is not None
        else INDEX_CATCHUP_MAX_AGE_SECONDS
    )
    max_event_backlog = INDEX_CATCHUP_MAX_EVENT_BACKLOG
    last_write_age_seconds = _optional_int(memory_status.get("last_write_age_seconds"))
    heartbeat_age_seconds = _optional_int(heartbeat_state.get("age_seconds"))
    heartbeat_fresh = heartbeat_state.get("fresh") is True
    event_backlog = _optional_int(count_deltas.get("events")) if count_deltas else None
    within_catchup_window = (
        str(index_health.get("state") or "") == "stale"
        and event_backlog is not None
        and event_backlog > 0
        and event_backlog <= max_event_backlog
        and heartbeat_fresh
        and last_write_age_seconds is not None
        and last_write_age_seconds <= max_age_seconds
    )
    return {
        "state": str(index_health.get("state") or "unknown"),
        "fts_tokenizer": str(index_health.get("fts_tokenizer") or ""),
        "store_counts": dict(store_counts),
        "index_counts": dict(index_counts),
        "count_deltas": count_deltas,
        "event_backlog": event_backlog,
        "max_event_backlog": max_event_backlog,
        "last_write_age_seconds": last_write_age_seconds,
        "heartbeat_age_seconds": heartbeat_age_seconds,
        "heartbeat_fresh": heartbeat_fresh,
        "max_catchup_age_seconds": max_age_seconds,
        "within_catchup_window": within_catchup_window,
    }


def _index_catchup_summary(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "state": contract.get("state"),
        "event_backlog": contract.get("event_backlog"),
        "max_event_backlog": contract.get("max_event_backlog"),
        "last_write_age_seconds": contract.get("last_write_age_seconds"),
        "heartbeat_age_seconds": contract.get("heartbeat_age_seconds"),
        "within_catchup_window": contract.get("within_catchup_window"),
        "max_catchup_age_seconds": contract.get("max_catchup_age_seconds"),
    }


def _rh31_retrieval_shadow_summary(summary: dict[str, Any]) -> dict[str, Any]:
    for score in summary.get("scores") or []:
        if not isinstance(score, dict) or score.get("adapter") != "retrieval_shadow":
            continue
        details = score.get("details") if isinstance(score.get("details"), dict) else {}
        if details.get("schema_version") != "memory-os.retrieval_shadow_eval.v0":
            continue
        return {
            "run_count": int(details.get("run_count") or 0),
            "semantic_gap_count": int(details.get("semantic_gap_count") or 0),
            "hybrid_would_retrieve_count": int(details.get("hybrid_would_retrieve_count") or 0),
            "rrf_would_rank_count": int(details.get("rrf_would_rank_count") or 0),
            "live_input_available": details.get("live_input_available") is True,
            "live_memory_sources_record_count": int(details.get("live_memory_sources_record_count") or 0),
            "live_bounded_source_ref_count": int(details.get("live_bounded_source_ref_count") or 0),
            "live_shadow_source_selection_miss_count": int(
                details.get("live_shadow_source_selection_miss_count") or 0
            ),
            "live_shadow_diversification_gap_count": int(
                details.get("live_shadow_diversification_gap_count") or 0
            ),
            "live_shadow_low_coverage_count": int(details.get("live_shadow_low_coverage_count") or 0),
            "live_shadow_would_rank_count": int(details.get("live_shadow_would_rank_count") or 0),
            "live_route_distribution": details.get("live_route_distribution") or {},
            "live_selected_source_class_distribution": details.get("live_selected_source_class_distribution") or {},
            "live_dropped_source_class_distribution": details.get("live_dropped_source_class_distribution") or {},
            "live_route_live_applied": details.get("live_route_live_applied") is True,
            "live_score_live_applied": details.get("live_score_live_applied") is True,
            "live_canonical_state_changed": details.get("live_canonical_state_changed") is True,
            "route_live_applied": details.get("route_live_applied") is True,
            "score_live_applied": details.get("score_live_applied") is True,
            "boundary_true_count": int(details.get("boundary_true_count") or 0),
            "forbidden_field_count": int(details.get("forbidden_field_count") or 0),
        }
    return {}


def _rh31_failure_attribution(summary: dict[str, Any]) -> list[dict[str, Any]]:
    attribution: list[dict[str, Any]] = []
    for score in summary.get("scores") or []:
        if not isinstance(score, dict) or score.get("status") != "fail":
            continue
        live_behavior_changed = score.get("live_behavior_changed") is True
        boundary_true = score.get("boundary_true") is True
        forbidden_count = int(score.get("forbidden_field_count") or 0)
        if live_behavior_changed and not boundary_true and forbidden_count == 0:
            guard_decision = "candidate_live_guard"
        else:
            guard_decision = "measurement_only"
        attribution.append(
            {
                "adapter": str(score.get("adapter") or ""),
                "case_id": str(score.get("case_id") or ""),
                "failure_class": str(score.get("failure_class") or ""),
                "metric_scope": str(score.get("metric_scope") or ""),
                "live_behavior_changed": live_behavior_changed,
                "guard_decision": guard_decision,
            }
        )
    return attribution


def summarize_v7_governance(snapshot: dict[str, Any]) -> dict[str, Any]:
    existing = snapshot.get("v7_governance") if isinstance(snapshot.get("v7_governance"), dict) else {}
    existing_components = {
        str(item.get("component") or ""): item
        for item in existing.get("components", [])
        if isinstance(item, dict) and item.get("component")
    }
    memory_sources = snapshot.get("memory_sources") if isinstance(snapshot.get("memory_sources"), dict) else {}
    memory_sources_feedback_count = _memory_sources_feedback_count(memory_sources)
    owner_signal_owner_approved_apply_count = memory_sources_feedback_count
    owner_signal_lane = "memory_sources_feedback" if owner_signal_owner_approved_apply_count > 0 else ""
    owner_signal_owner_approved_apply_ready = (
        owner_signal_owner_approved_apply_count >= V7_MEMORY_SOURCES_FEEDBACK_CANARY_TARGET
    )
    inferred_components = _infer_v7_components_from_artifacts(snapshot)
    components: list[dict[str, Any]] = []
    for component in V7_GOVERNANCE_COMPONENTS:
        item = dict(inferred_components.get(component) or {})
        for key, value in (existing_components.get(component) or {}).items():
            if key == "pipeline_liveness" and item and str(value or "") in {"", "missing"}:
                continue
            if key == "task_installed" and item and value is False:
                continue
            item[key] = value
        pipeline_liveness = str(item.get("pipeline_liveness") or "missing")
        autonomy_level = str(item.get("autonomy_level") or "none")
        task_installed = bool(item.get("task_installed")) or pipeline_liveness != "missing"
        if (
            component == "retractable_label_miner"
            and task_installed
            and owner_signal_owner_approved_apply_ready
            and autonomy_level != "autonomous_acting"
        ):
            autonomy_level = "owner_approved_apply"
        components.append(
            {
                "component": component,
                "task_installed": task_installed,
                "pipeline_liveness": pipeline_liveness,
                "autonomy_level": autonomy_level,
                "owner_signal_lane": owner_signal_lane if component == "retractable_label_miner" else "",
                "owner_approved_apply_count": owner_signal_owner_approved_apply_count
                if component == "retractable_label_miner"
                else 0,
                "owner_approved_apply_ready": owner_signal_owner_approved_apply_ready
                if component == "retractable_label_miner"
                else False,
                "live_guard_registered": bool(item.get("live_guard_registered")),
                "live_applied": bool(item.get("live_applied")),
                "actual_send": bool(item.get("actual_send")),
                "actual_execute": bool(item.get("actual_execute")),
                "actual_identity_write": bool(item.get("actual_identity_write")),
                "actual_crystallized_approval": bool(item.get("actual_crystallized_approval")),
            }
        )

    memory_sources_feedback_volume_ready = bool(existing.get("memory_sources_feedback_volume_ready"))
    memory_sources_feedback_volume_ready = (
        memory_sources_feedback_volume_ready or memory_sources_feedback_count > 0
    )
    memory_sources_feedback_canary_remaining = max(
        V7_MEMORY_SOURCES_FEEDBACK_CANARY_TARGET - memory_sources_feedback_count,
        0,
    )
    component_status = {item["component"]: item["pipeline_liveness"] for item in components}
    profile = _normalize_monitor_profile(snapshot.get("monitor_profile"))
    policy = snapshot.get("v7_component_policy") if isinstance(snapshot.get("v7_component_policy"), dict) else {}
    raw_enabled_optional = policy.get("enabled_optional_components")
    if not isinstance(raw_enabled_optional, (list, tuple, set)):
        raw_enabled_optional = []
    enabled_optional = {
        str(component)
        for component in raw_enabled_optional
        if str(component)
    }
    explicit_absence_reasons = _v7_explicit_absence_reasons(policy)
    missing_required_components = [
        component
        for component in V7_REQUIRED_COMPONENTS_PRODUCTION
        if not _v7_component_present(component_status.get(component))
    ]
    optional_components: dict[str, dict[str, Any]] = {}
    intentionally_absent_components: list[dict[str, str]] = []
    enabled_optional_missing_components: list[str] = []
    for component, default_reason in V7_OPTIONAL_COMPONENT_REASONS.items():
        status = str(component_status.get(component) or "missing")
        enabled = component in enabled_optional
        absence_reason = ""
        intentionally_absent = False
        if not _v7_component_present(status):
            if enabled:
                enabled_optional_missing_components.append(component)
            else:
                absence_reason = explicit_absence_reasons.get(component) or default_reason
                intentionally_absent = True
                intentionally_absent_components.append({"component": component, "reason": absence_reason})
        optional_components[component] = {
            "status": status,
            "enabled": enabled,
            "intentionally_absent": intentionally_absent,
            "absence_reason": absence_reason,
        }
    live_guard_report = live_guard_registration_report(components)
    return {
        "schema_version": "memory-os.v7_governance_summary.v0",
        "component_count": len(components),
        "profile_expected_component_policy": "clean_host" if profile == "clean_host" else "production",
        "required_components": list(V7_REQUIRED_COMPONENTS_PRODUCTION),
        "required_component_count": len(V7_REQUIRED_COMPONENTS_PRODUCTION),
        "present_required_component_count": len(V7_REQUIRED_COMPONENTS_PRODUCTION) - len(missing_required_components),
        "missing_required_components": missing_required_components,
        "optional_components": optional_components,
        "intentionally_absent_components": intentionally_absent_components,
        "enabled_optional_missing_components": enabled_optional_missing_components,
        "shadow_live_component_count": sum(
            1 for item in components if item["pipeline_liveness"] == "live-shadow"
        ),
        "acting_component_count": sum(
            1 for item in components if str(item["autonomy_level"]) in V7_ACTING_AUTONOMY_LEVELS
        ),
        "live_guard_registered_count": sum(1 for item in components if item["live_guard_registered"]),
        "live_guard_missing_registration_count": live_guard_report["missing_registration_count"],
        "live_guard_missing_registration_components": live_guard_report["missing_registration_components"],
        "live_guard_exempted_component_count": live_guard_report["exempted_component_count"],
        "live_guard_exempted_components": live_guard_report["exempted_components"],
        "memory_sources_feedback_volume_ready": memory_sources_feedback_volume_ready,
        "memory_sources_feedback_count": memory_sources_feedback_count,
        "memory_sources_feedback_canary_target": V7_MEMORY_SOURCES_FEEDBACK_CANARY_TARGET,
        "memory_sources_feedback_canary_remaining": memory_sources_feedback_canary_remaining,
        "memory_sources_feedback_canary_complete": memory_sources_feedback_canary_remaining == 0,
        "owner_signal_lane": owner_signal_lane,
        "owner_signal_owner_approved_apply_count": owner_signal_owner_approved_apply_count,
        "owner_signal_owner_approved_apply_ready": owner_signal_owner_approved_apply_ready,
        "owner_signal_selected_component": "retractable_label_miner" if owner_signal_lane else "",
        "confidence_router_status": component_status["confidence_router"],
        "judge_consistency_status": component_status["judge_calibration"],
        "review_accuracy_status": component_status["candidate_review"],
        "shadow_recall_status": component_status["shadow_recall"],
        "deferral_accuracy_status": component_status["cascade_routing_policy"],
        "migration_regression_status": component_status["migration_controller"],
        "offload_integrity_status": component_status["symbolic_offloader"],
        "distillation_fidelity_status": component_status["abstraction_distillation"],
        "simulation_coverage_status": component_status["imagination_loop"],
        "confabulation_detection_status": component_status["confabulation_detector"],
        "crystallized_revalidator_status": component_status["crystallized_revalidator"],
        "cross_check_anchoring_status": component_status["grounded_expression_judge"],
        "component_status": component_status,
        "components": components,
    }


def _v7_component_present(status: Any) -> bool:
    return str(status or "missing") != "missing"


def _v7_explicit_absence_reasons(policy: dict[str, Any]) -> dict[str, str]:
    raw = policy.get("intentionally_absent_components")
    if isinstance(raw, dict):
        return {str(component): str(reason) for component, reason in raw.items() if str(component)}
    reasons: dict[str, str] = {}
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                component = str(item.get("component") or "")
                reason = str(item.get("reason") or "")
                if component:
                    reasons[component] = reason
            elif str(item):
                reasons[str(item)] = ""
    return reasons


def _infer_v7_components_from_artifacts(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    module_artifacts = snapshot.get("module_artifacts") if isinstance(snapshot.get("module_artifacts"), dict) else {}
    inferred: dict[str, dict[str, Any]] = {}

    evidence = module_artifacts.get("evidence") if isinstance(module_artifacts.get("evidence"), dict) else {}
    if int(evidence.get("derived_evidence_profile_count") or 0) > 0:
        inferred["derived_evidence_profile"] = {
            "task_installed": True,
            "pipeline_liveness": "live-shadow",
            "autonomy_level": "shadow",
            "live_guard_registered": True,
            "live_applied": bool(evidence.get("feature_score_live_applied")) or bool(evidence.get("maturity_live_applied")),
            "actual_execute": bool(evidence.get("actual_execute")),
        }
    meta = module_artifacts.get("v7_meta") if isinstance(module_artifacts.get("v7_meta"), dict) else {}
    promotion_matrix = meta.get("promotion_matrix_component")
    if isinstance(promotion_matrix, dict) and promotion_matrix.get("component") == "promotion_matrix":
        inferred["promotion_matrix"] = dict(promotion_matrix)
    elif meta.get("promotion_matrix_present") is True:
        inferred["promotion_matrix"] = {
            "task_installed": True,
            "pipeline_liveness": "live-shadow",
            "autonomy_level": "shadow",
            "live_guard_registered": True,
            "live_applied": False,
            "actual_execute": False,
        }
    if meta.get("live_guard_registry_present") is True:
        inferred["live_guard_registry"] = {
            "task_installed": True,
            "pipeline_liveness": "live-shadow",
            "autonomy_level": "shadow",
            "live_guard_registered": True,
            "live_applied": False,
            "actual_execute": False,
        }
    if meta.get("eval_adapter_registry_present") is True:
        inferred["eval_adapter_registry"] = {
            "task_installed": True,
            "pipeline_liveness": "live-shadow",
            "autonomy_level": "shadow",
            "live_guard_registered": True,
            "live_applied": False,
            "actual_execute": False,
        }

    imagination = (
        module_artifacts.get("imagination_loop")
        if isinstance(module_artifacts.get("imagination_loop"), dict)
        else {}
    )
    if int(imagination.get("scenario_count") or 0) > 0:
        inferred["imagination_loop"] = {
            "task_installed": True,
            "pipeline_liveness": "live-shadow",
            "autonomy_level": "shadow",
            "live_guard_registered": True,
            "live_applied": bool(imagination.get("live_applied")) or bool(imagination.get("live_behavior_changed")),
            "actual_send": bool(imagination.get("actual_send")),
            "actual_execute": bool(imagination.get("actual_execute")),
            "actual_identity_write": bool(imagination.get("actual_identity_write")),
        }

    confabulation = (
        module_artifacts.get("confabulation_detector")
        if isinstance(module_artifacts.get("confabulation_detector"), dict)
        else {}
    )
    if str(confabulation.get("status") or "") == "ok" or confabulation.get("flag_count") is not None:
        inferred["confabulation_detector"] = {
            "task_installed": True,
            "pipeline_liveness": "live-shadow",
            "autonomy_level": "shadow",
            "live_guard_registered": True,
            "live_applied": bool(confabulation.get("score_live_applied")) or bool(confabulation.get("route_live_applied")),
            "actual_send": bool(confabulation.get("actual_send")),
            "actual_execute": bool(confabulation.get("actual_execute")),
            "actual_identity_write": bool(confabulation.get("actual_identity_write")),
        }
    ground_truth = (
        module_artifacts.get("ground_truth_miner")
        if isinstance(module_artifacts.get("ground_truth_miner"), dict)
        else {}
    )
    if str(ground_truth.get("status") or "") == "ok" or ground_truth.get("label_count") is not None:
        inferred["retractable_label_miner"] = {
            "task_installed": True,
            "pipeline_liveness": "live-shadow",
            "autonomy_level": "shadow",
            "live_guard_registered": True,
            "live_applied": bool(ground_truth.get("score_live_applied")) or bool(ground_truth.get("route_live_applied")),
            "actual_send": bool(ground_truth.get("actual_send")),
            "actual_execute": bool(ground_truth.get("actual_execute")),
            "actual_identity_write": bool(ground_truth.get("actual_identity_write")),
        }
    confidence_router = (
        module_artifacts.get("confidence_router")
        if isinstance(module_artifacts.get("confidence_router"), dict)
        else {}
    )
    if str(confidence_router.get("status") or "") == "ok" or confidence_router.get("route_count") is not None:
        inferred["confidence_router"] = {
            "task_installed": True,
            "pipeline_liveness": "live-shadow",
            "autonomy_level": "shadow",
            "live_guard_registered": True,
            "live_applied": bool(confidence_router.get("route_live_applied")) or bool(
                confidence_router.get("score_live_applied")
            ),
            "actual_send": bool(confidence_router.get("actual_send")),
            "actual_execute": bool(confidence_router.get("actual_execute")),
            "actual_identity_write": bool(confidence_router.get("actual_identity_write")),
        }
    inferred.update(
        _infer_v7_shadow_module(
            module_artifacts,
            component="judge_calibration",
            status_key="judge_calibration",
            count_keys=("run_count",),
            live_applied_keys=("calibration_live_applied",),
        )
    )
    inferred.update(
        _infer_v7_shadow_module(
            module_artifacts,
            component="candidate_review",
            status_key="candidate_review",
            count_keys=("decision_count", "run_count"),
            live_applied_keys=("candidate_review_live_applied",),
        )
    )
    inferred.update(
        _infer_v7_shadow_module(
            module_artifacts,
            component="shadow_recall",
            status_key="shadow_recall",
            count_keys=("fingerprint_count", "run_count"),
            live_applied_keys=("auto_discard_live_applied",),
        )
    )
    inferred.update(
        _infer_v7_shadow_module(
            module_artifacts,
            component="provisional",
            status_key="provisional",
            count_keys=("record_count", "run_count"),
            live_applied_keys=("auto_promote_live_applied",),
            extra_boundary_keys=("actual_crystallized_approval",),
        )
    )
    inferred.update(
        _infer_v7_shadow_module(
            module_artifacts,
            component="cascade_routing_policy",
            status_key="cascade_routing_policy",
            count_keys=("proposal_count",),
            live_applied_keys=("route_strategy_live_applied",),
        )
    )
    inferred.update(
        _infer_v7_shadow_module(
            module_artifacts,
            component="migration_controller",
            status_key="migration_controller",
            count_keys=("run_count",),
            live_applied_keys=("migration_live_applied",),
        )
    )
    inferred.update(
        _infer_v7_shadow_module(
            module_artifacts,
            component="symbolic_offloader",
            status_key="symbolic_offloader",
            count_keys=("report_count", "ref_count"),
            live_applied_keys=("canonical_state_changed",),
        )
    )
    inferred.update(
        _infer_v7_shadow_module(
            module_artifacts,
            component="abstraction_distillation",
            status_key="abstraction_distillation",
            count_keys=("item_count",),
            live_applied_keys=("distillation_live_applied",),
        )
    )
    crystallized = (
        module_artifacts.get("crystallized_revalidator")
        if isinstance(module_artifacts.get("crystallized_revalidator"), dict)
        else {}
    )
    if str(crystallized.get("status") or "") == "ok" or crystallized.get("flag_count") is not None:
        inferred["crystallized_revalidator"] = {
            "task_installed": True,
            "pipeline_liveness": "live-shadow",
            "autonomy_level": "shadow",
            "live_guard_registered": True,
            "live_applied": bool(crystallized.get("demotion_live_applied")),
            "actual_send": bool(crystallized.get("actual_send")),
            "actual_execute": bool(crystallized.get("actual_execute")),
            "actual_identity_write": bool(crystallized.get("actual_identity_write")),
            "actual_crystallized_approval": bool(crystallized.get("actual_crystallized_approval")),
        }
    grounded_expression = (
        module_artifacts.get("grounded_expression_judge")
        if isinstance(module_artifacts.get("grounded_expression_judge"), dict)
        else {}
    )
    if int(grounded_expression.get("verdict_count") or 0) > 0:
        inferred["grounded_expression_judge"] = {
            "task_installed": True,
            "pipeline_liveness": "live-shadow",
            "autonomy_level": "shadow",
            "live_guard_registered": True,
            "live_applied": bool(grounded_expression.get("policy_live_applied"))
            or bool(grounded_expression.get("delivery_affected"))
            or bool(grounded_expression.get("delivery_gated")),
            "actual_send": bool(grounded_expression.get("actual_send")),
            "actual_execute": bool(grounded_expression.get("actual_execute")),
            "actual_identity_write": bool(grounded_expression.get("actual_identity_write")),
        }
    return inferred


def _infer_v7_shadow_module(
    module_artifacts: dict[str, Any],
    *,
    component: str,
    status_key: str,
    count_keys: tuple[str, ...],
    live_applied_keys: tuple[str, ...],
    extra_boundary_keys: tuple[str, ...] = (),
) -> dict[str, dict[str, Any]]:
    artifact = module_artifacts.get(status_key) if isinstance(module_artifacts.get(status_key), dict) else {}
    has_count = any(int(artifact.get(key) or 0) > 0 for key in count_keys)
    if str(artifact.get("status") or "") != "ok" and not has_count:
        return {}
    item = {
        "task_installed": True,
        "pipeline_liveness": "live-shadow",
        "autonomy_level": "shadow",
        "live_guard_registered": True,
        "live_applied": any(bool(artifact.get(key)) for key in live_applied_keys),
        "actual_send": bool(artifact.get("actual_send")),
        "actual_execute": bool(artifact.get("actual_execute")),
        "actual_identity_write": bool(artifact.get("actual_identity_write")),
    }
    for key in extra_boundary_keys:
        item[key] = bool(artifact.get(key))
    return {component: item}


def summarize_l4_guard(snapshot: dict[str, Any]) -> dict[str, Any]:
    config = snapshot.get("memory_os_config") if isinstance(snapshot.get("memory_os_config"), dict) else {}
    l4 = config.get("l4") if isinstance(config.get("l4"), dict) else {}
    v7_governance = summarize_v7_governance(snapshot)
    evidence = (
        snapshot.get("module_artifacts", {}).get("evidence", {})
        if isinstance(snapshot.get("module_artifacts", {}), dict)
        and isinstance(snapshot.get("module_artifacts", {}).get("evidence", {}), dict)
        else {}
    )
    live_applied_finding_count = int(bool(evidence.get("feature_score_live_applied"))) + int(
        bool(evidence.get("maturity_live_applied"))
    )
    return {
        "schema_version": "memory-os.l4_guard_summary.v0",
        "kill_switch_enabled": bool(l4.get("kill_switch_enabled")),
        "registered_component_count": max(1, int(v7_governance.get("live_guard_registered_count") or 0)),
        "missing_registration_count": int(v7_governance.get("live_guard_missing_registration_count") or 0),
        "missing_registration_components": list(v7_governance.get("live_guard_missing_registration_components") or []),
        "live_applied_finding_count": live_applied_finding_count,
    }


def summarize_living_memory_promotion(
    *,
    delivery_items: list[dict[str, Any]] | None = None,
    review_items: list[dict[str, Any]] | None = None,
    automatic_permanent_promotion_count: int = 0,
    memory_os_root: Path | None = None,
    ledger_counts: dict[str, Any] | None = None,
    ledger_collection_error: str | None = None,
) -> dict[str, Any]:
    """Derive the Living Memory V2-0 permanent-promotion monitor section.

    Counts only registered ``LIVING_MEMORY_TARGET_TYPES`` so unrelated owner
    systems (speak, knob, route/score) never enter the hard-zero counters.
    ``delivery_items`` are what would be proactively delivered to the owner
    (post Task-7 choke point, promotion-only); ``review_items`` are the
    owner-initiated query surface (queue/aging), which may include provisional
    non-promotion items by design.

    Ledger state (proposal/token counts, recovery/stale-open counters) is
    read locally when ``memory_os_root`` is given, or supplied pre-collected
    via ``ledger_counts`` for a remote host (see ``living_memory_promotion_probe``
    in ``_remote_probe_script``). If neither is available, ``ledger_collection_error``
    marks the section as explicitly uncollected rather than leaving the
    hard-zero placeholders below indistinguishable from a verified zero.
    When ALL THREE ledger parameters are omitted the section is still marked
    explicitly unavailable with error_code ``ledger_state_not_supplied`` —
    there is deliberately no implicit fourth path that keeps the hard-zero
    placeholders without a ``ledger_state_collection_status`` key.
    """
    try:
        from plugins.memory.memory_os.owner_actions import LIVING_MEMORY_TARGET_TYPES
    except Exception:
        LIVING_MEMORY_TARGET_TYPES = frozenset({
            "candidate_cluster", "crystallized_record",
            "provisional_crystallized_record", "permanent_memory_promotion",
        })
    promo = "permanent_memory_promotion"
    delivery = delivery_items or []
    review = review_items or []

    def _lm(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [i for i in items if str(i.get("target_type") or "") in LIVING_MEMORY_TARGET_TYPES]

    lm_delivery = _lm(delivery)
    lm_review = _lm(review)
    section: dict[str, Any] = {
        "schema_version": "memory-os.living_memory_promotion.v0",
        "permanent_promotion_review_item_count": sum(
            1 for i in lm_review if str(i.get("target_type")) == promo
        ),
        "living_memory_nonpromotion_review_item_count": sum(
            1 for i in lm_review if str(i.get("target_type")) != promo
        ),
        "living_memory_owner_delivery_nonpromotion_count": sum(
            1 for i in lm_delivery if str(i.get("target_type")) != promo
        ),
        "automatic_permanent_promotion_count": int(automatic_permanent_promotion_count or 0),
        "proposal_ledger_counts": {
            "open": 0, "deciding": 0, "approved": 0, "rejected": 0, "deferred": 0, "revoked": 0, "expired": 0,
        },
        "token_ledger_counts": {"open": 0, "consumed": 0, "revoked": 0, "expired": 0},
        "open_proposal_backlog_count": 0,
        "never_delivered_open_count": 0,
        "due_reminder_count": 0,
        "deferred_past_due_count": 0,
        "deciding_proposal_count": 0,
        "decision_recovery_attempt_count": 0,
        "decision_recovery_success_count": 0,
        "decision_recovery_failure_count": 0,
        "stale_open_proposal_count": 0,
        "target_retired_close_count": 0,
        "approved_reconcile_count": 0,
        "duplicate_delivery_suppressed_count": 0,
    }
    if memory_os_root is not None:
        try:
            section.update(read_permanent_promotion_ledger_counts(memory_os_root))
            section["ledger_state_collection_status"] = "collected"
        except Exception as exc:
            # A corrupted / non-UTF-8 ledger file must degrade to the same
            # explicit unavailable+error_code shape as a remote collection
            # failure (ledger_collection_error below) instead of crashing
            # the entire local monitor run — classify_snapshot turns this
            # into the ledger-collection-failed WARN (never a silent pass).
            section["ledger_state_collection_status"] = "unavailable"
            section["ledger_state_collection_error_code"] = type(exc).__name__
    elif ledger_counts is not None:
        section.update(ledger_counts)
        section["ledger_state_collection_status"] = "collected"
    elif ledger_collection_error is not None:
        section["ledger_state_collection_status"] = "unavailable"
        section["ledger_state_collection_error_code"] = ledger_collection_error
    else:
        # P2 #9 (Section W rule 4 — default parameters must never be traps):
        # with no ledger source at all (all three params None) the section
        # previously kept its hard-zero placeholders with NO
        # ledger_state_collection_status key — indistinguishable from healthy
        # verified zeros to any consumer that does not defensively check key
        # presence.  The unconditional else makes the absence explicit:
        # "ledger_state_not_supplied" marks a section built without any
        # ledger source, and classify_snapshot turns it into the
        # ledger-collection-failed WARN (fail_if_production).  The real
        # caller collect_snapshot always supplies exactly one of the three
        # parameters, so reaching this branch from production would itself
        # be the silent-zero bug this fix surfaces.
        section["ledger_state_collection_status"] = "unavailable"
        section["ledger_state_collection_error_code"] = "ledger_state_not_supplied"
    if section.get("ledger_state_collection_status") == "collected":
        # A "collected" ledger dict that omits the stale-open evaluation
        # status (e.g. a version-skewed remote plugin whose
        # read_permanent_promotion_ledger_counts predates the field) must
        # never read as a healthy evaluation — deliberately mark it
        # unavailable so classify_snapshot warns instead of trusting an
        # un-evaluated stale_open_proposal_count zero. On an uncollected
        # section the stronger ledger-collection-failed signal already
        # covers the whole ledger state, evaluation included.
        section.setdefault("stale_open_evaluation_status", "unavailable")
        section.setdefault("stale_open_evaluation_error_code", "missing_from_collected_counts")
    return section


def classify_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    passed: list[dict[str, Any]] = []
    warn: list[dict[str, Any]] = []
    fail: list[dict[str, Any]] = []
    info: list[dict[str, Any]] = []
    monitor_profile = _normalize_monitor_profile(snapshot.get("monitor_profile"))
    clean_host = monitor_profile == "clean_host"
    legacy_retired = (
        isinstance(snapshot.get("legacy_right_brain_archive"), dict)
        and snapshot["legacy_right_brain_archive"].get("lifecycle")
        in {"retirement_pending", "retired"}
    )
    runtime_contract = (
        snapshot.get("full_monitor_runtime_contract")
        if isinstance(snapshot.get("full_monitor_runtime_contract"), dict)
        else {}
    )
    _classify_full_monitor_runtime_contract(runtime_contract, passed, warn)
    hermes_status = snapshot.get("hermes_status") if isinstance(snapshot.get("hermes_status"), dict) else {}
    hermes_gateway_running = hermes_status.get("gateway_running") is True

    raw_v2_exposure = snapshot.get("v2_exposure_monitor")
    v2_exposure: dict[str, Any] = raw_v2_exposure if isinstance(raw_v2_exposure, dict) else {}
    v2_health = str(v2_exposure.get("schema_era_health") or "unavailable")
    if v2_health in {"PASS", "healthy_no_sample"}:
        passed.append({"code": "v2_exposure_schema_era_healthy", "value": v2_health})
    elif v2_health == "FAIL":
        # A real schema-era attribution gap / conservation break / telemetry
        # degradation inside natural production records is a correctness bug
        # on any host — it must FAIL the monitor outright, not warn (Fix 2a).
        fail.append({"code": "v2_exposure_schema_era_unhealthy", "value": v2_exposure})
    elif v2_health == "unavailable_remote_projection" or v2_exposure.get("error_code"):
        # Collection was attempted (locally or via remote SSH projection) and
        # failed — this must never be a silent pass (Fix 1 / Fix 2).
        warn.append({"code": "v2_exposure_monitor_collection_failed", "value": v2_exposure})
    schema_era_conservation_failure_count = int(v2_exposure.get("schema_era_conservation_failure_count") or 0)
    if schema_era_conservation_failure_count > 0:
        # Only a conservation break inside the schema era (natural production
        # records) is a real FAIL driver — all-history/migration-era breaks
        # are surfaced separately below as INFO (Fix 2b).
        fail.append({"code": "v2_exposure_conservation_failed", "value": v2_exposure})
    all_history_gap_count = int(v2_exposure.get("all_history_attribution_gap_count") or 0)
    schema_era_gap_count = int(v2_exposure.get("schema_era_attribution_gap_count") or 0)
    migration_debt_gap_count = max(0, all_history_gap_count - schema_era_gap_count)
    all_history_conservation_ok = v2_exposure.get("conservation_total_passes")
    migration_debt_conservation_issue = (
        all_history_conservation_ok is False and schema_era_conservation_failure_count == 0
    )
    if v2_exposure and (migration_debt_gap_count > 0 or migration_debt_conservation_issue):
        # All-history migration debt (pre-schema-era data) is visible but must
        # never drive FAIL/WARN on its own (Fix 2c).
        info.append({
            "code": "v2_exposure_all_history_migration_debt",
            "value": {
                "migration_debt_attribution_gap_count": migration_debt_gap_count,
                "all_history_attribution_gap_count": all_history_gap_count,
                "schema_era_attribution_gap_count": schema_era_gap_count,
                "conservation_total_passes": all_history_conservation_ok,
            },
        })
    if v2_exposure.get("downstream_clearance_closure_frozen") is True:
        passed.append({"code": "v2_downstream_clearance_frozen_by_evidence_gates", "reasons": v2_exposure.get("freeze_reasons")})

    raw_clearance_freshness = snapshot.get("clearance_snapshot_freshness")
    clearance_freshness: dict[str, Any] = raw_clearance_freshness if isinstance(raw_clearance_freshness, dict) else {}
    clearance_status = str(clearance_freshness.get("status") or "unavailable")
    if clearance_status == "fresh":
        passed.append({"code": "clearance_snapshot_fresh"})
    elif v2_exposure.get("v2c_unfreeze_ready") is True:
        fail.append({"code": "clearance_snapshot_not_fresh", "value": clearance_freshness})
    elif clearance_status in {"stale", "missing"}:
        warn.append({"code": "clearance_snapshot_not_fresh", "value": clearance_freshness})
    elif clearance_status == "unavailable_remote_projection" or clearance_freshness.get("error_code"):
        # Same "never silent" requirement as v2_exposure above (Fix 1 / Fix 2).
        warn.append({"code": "clearance_snapshot_freshness_collection_failed", "value": clearance_freshness})

    if snapshot.get("gateway", {}).get("ActiveState") == "active":
        passed.append({"code": "gateway_active"})
    elif hermes_gateway_running:
        passed.append(
            {
                "code": "clean_host_gateway_active_via_hermes_status"
                if clean_host
                else "gateway_active_via_hermes_status",
                "manager": hermes_status.get("gateway_manager"),
                "pids": hermes_status.get("gateway_pids"),
            }
        )
    elif clean_host:
        passed.append({"code": "clean_host_gateway_inactive_expected", "value": snapshot.get("gateway")})
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
    cognitive_loop_step_evidence = snapshot.get("cognitive_loop_step_evidence")
    if isinstance(cognitive_loop_step_evidence, dict) and cognitive_loop_step_evidence:
        evidence_status = str(cognitive_loop_step_evidence.get("status") or "")
        if evidence_status == "ok":
            missing_required_steps = cognitive_loop_step_evidence.get("missing_required_steps") or []
            if missing_required_steps:
                fail.append(
                    {
                        "code": "cognitive_loop_required_step_missing",
                        "missing_required_steps": missing_required_steps,
                    }
                )
            omitted_step_count = int(cognitive_loop_step_evidence.get("omitted_step_count") or 0)
            tail_step_omitted_count = int(cognitive_loop_step_evidence.get("tail_step_omitted_count") or 0)
            if omitted_step_count or tail_step_omitted_count:
                fail.append(
                    {
                        "code": "cognitive_loop_tail_step_omitted_by_bounded_report",
                        "omitted_step_count": omitted_step_count,
                        "tail_step_omitted_count": tail_step_omitted_count,
                    }
                )
            if not missing_required_steps and not omitted_step_count and not tail_step_omitted_count:
                passed.append(
                    {
                        "code": "cognitive_loop_required_steps_visible",
                        "latest_step_count": cognitive_loop_step_evidence.get("latest_step_count"),
                    }
                )
        elif clean_host:
            warn.append({"code": "cognitive_loop_step_evidence_missing", "value": cognitive_loop_step_evidence})
        else:
            fail.append({"code": "cognitive_loop_step_evidence_missing", "value": cognitive_loop_step_evidence})
    elif cognitive_loop.get("last_cycle_id"):
        if clean_host:
            warn.append({"code": "cognitive_loop_step_evidence_missing"})
        else:
            fail.append({"code": "cognitive_loop_step_evidence_missing"})

    _classify_left_brain_signal_weaving(snapshot, passed, warn, fail, clean_host=clean_host)

    memory_status_raw = snapshot.get("memory_status")
    memory_status = memory_status_raw if isinstance(memory_status_raw, dict) else {}
    index_health_raw = memory_status.get("index_health")
    index_health = index_health_raw if isinstance(index_health_raw, dict) else {}
    catchup_contract = (
        snapshot.get("index_catchup_contract")
        if isinstance(snapshot.get("index_catchup_contract"), dict)
        else index_catchup_contract(snapshot)
    )
    if index_health.get("state") == "healthy":
        passed.append({"code": "index_healthy"})
    elif catchup_contract.get("within_catchup_window") is True:
        warn.append({"code": "index_catchup_pending", "value": catchup_contract})
    else:
        warn.append({"code": "index_not_healthy", "value": catchup_contract})
    if memory_status.get("prefetch_mode") != "indexed":
        warn.append({"code": "prefetch_not_indexed", "value": memory_status.get("prefetch_mode")})
    counts_raw = memory_status.get("counts")
    counts = counts_raw if isinstance(counts_raw, dict) else {}
    crystallized_record_count = int(counts.get("crystallized_records", 0) or 0)
    if crystallized_record_count > 0:
        passed.append(
            {
                "code": "crystallized_records_present",
                "value": crystallized_record_count,
            }
        )
    _classify_hindsight_substrate(snapshot, passed, fail)

    doctor_raw = snapshot.get("doctor")
    doctor = doctor_raw if isinstance(doctor_raw, dict) else {}
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
        and shell_alias.get("host_probe_ok", True) is True
        and shell_alias.get("signal_sources_ok", True) is True
        and shell_alias.get("memory_projection_ok", True) is True
        and shell_alias.get("left_brain_ok", True) is True
        and shell_alias.get("review_surface_ok", True) is True
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
        ops_gate = module_artifacts.get("ops_gate") if isinstance(module_artifacts.get("ops_gate"), dict) else {}
        if int(ops_gate.get("duplicate_proposal_followup_count") or 0) > 0:
            fail.append(
                {
                    "code": "ops_gate_duplicate_proposal_followup_report",
                    "value": {
                        "duplicate_count": ops_gate.get("duplicate_proposal_followup_count"),
                        "duplicate_extra_count": ops_gate.get("duplicate_proposal_followup_extra_count"),
                    },
                }
            )
        if int(ops_gate.get("skipped_run_count") or 0) > 0 and ops_gate.get("latest_cadence_skipped") is True:
            passed.append(
                {
                    "code": "ops_gate_no_pending_skip_visible",
                    "value": {
                        "skipped_run_count": ops_gate.get("skipped_run_count"),
                        "latest_skip_reason": ops_gate.get("latest_skip_reason"),
                    },
                }
            )
        proposal_queue = (
            module_artifacts.get("proposal_queue")
            if isinstance(module_artifacts.get("proposal_queue"), dict)
            else {}
        )
        if proposal_queue:
            if int(proposal_queue.get("legacy_template_cleanup_actual_execute_count") or 0) > 0:
                fail.append(
                    {
                        "code": "proposal_queue_legacy_template_cleanup_actual_execute_true",
                        "value": proposal_queue,
                    }
                )
            elif int(proposal_queue.get("legacy_template_cleanup_non_legacy_touched_count") or 0) > 0:
                fail.append(
                    {
                        "code": "proposal_queue_legacy_template_cleanup_non_legacy_touched",
                        "value": proposal_queue,
                    }
                )
            elif int(proposal_queue.get("legacy_template_cleanup_raw_body_included_count") or 0) > 0:
                fail.append(
                    {
                        "code": "proposal_queue_legacy_template_cleanup_raw_body_included",
                        "value": proposal_queue,
                    }
                )
            elif int(proposal_queue.get("legacy_template_cleanup_apply_count") or 0) > 0:
                passed.append(
                    {
                        "code": "proposal_queue_legacy_template_cleanup_visible",
                        "apply_count": proposal_queue.get("legacy_template_cleanup_apply_count"),
                        "closed_count": proposal_queue.get("legacy_template_cleanup_closed_count"),
                    }
                )
        evidence = module_artifacts.get("evidence") if isinstance(module_artifacts.get("evidence"), dict) else {}
        self_evolution = (
            module_artifacts.get("self_evolution")
            if isinstance(module_artifacts.get("self_evolution"), dict)
            else {}
        )
        if self_evolution and self_evolution.get("agenda_candidate_count") is not None:
            passed.append(
                {
                    "code": "left_brain_agenda_candidate_maturity_visible",
                    "agenda_candidate_count": self_evolution.get("agenda_candidate_count"),
                    "agenda_candidate_promoted_count": self_evolution.get("agenda_candidate_promoted_count"),
                    "agenda_candidate_blocked_count": self_evolution.get("agenda_candidate_blocked_count"),
                    "latest_agenda_candidate_status": self_evolution.get("latest_agenda_candidate_status"),
                }
            )
        pipeline_check = (
            module_artifacts.get("left_brain_pipeline_check")
            if isinstance(module_artifacts.get("left_brain_pipeline_check"), dict)
            else {}
        )
        if pipeline_check:
            if pipeline_check.get("actual_execute") is True:
                fail.append({"code": "left_brain_pipeline_check_actual_execute_true", "value": pipeline_check})
            elif pipeline_check.get("status") in {"ok", "warn", "fail"}:
                passed.append({"code": "left_brain_pipeline_check_visible"})
            if pipeline_check.get("status") == "fail":
                fail.append({"code": "left_brain_pipeline_check_failed", "value": pipeline_check})
            elif pipeline_check.get("status") == "warn":
                warn.append({"code": "left_brain_pipeline_check_warn", "value": pipeline_check})
            if int(pipeline_check.get("expression_policy_quality_ready_count") or 0) > 0:
                passed.append(
                    {
                        "code": "left_brain_feedback_proposal_quality_ready",
                        "expression_policy_quality_ready_count": pipeline_check.get(
                            "expression_policy_quality_ready_count"
                        ),
                    }
                )
            if int(pipeline_check.get("expression_policy_quality_blocked_count") or 0) > 0:
                warn.append(
                    {
                        "code": "left_brain_feedback_proposal_quality_blocked",
                        "expression_policy_quality_blocked_count": pipeline_check.get(
                            "expression_policy_quality_blocked_count"
                        ),
                    }
                )
            if int(pipeline_check.get("memory_sources_policy_quality_ready_count") or 0) > 0:
                passed.append(
                    {
                        "code": "left_brain_memory_sources_policy_quality_ready",
                        "memory_sources_policy_quality_ready_count": pipeline_check.get(
                            "memory_sources_policy_quality_ready_count"
                        ),
                    }
                )
            if int(pipeline_check.get("memory_sources_policy_quality_blocked_count") or 0) > 0:
                warn.append(
                    {
                        "code": "left_brain_memory_sources_policy_quality_blocked",
                        "memory_sources_policy_quality_blocked_count": pipeline_check.get(
                            "memory_sources_policy_quality_blocked_count"
                        ),
                    }
                )
            if int(pipeline_check.get("proposal_quality_missing_count") or 0) > 0:
                warn.append(
                    {
                        "code": "left_brain_proposal_quality_metadata_missing",
                        "proposal_quality_missing_count": pipeline_check.get("proposal_quality_missing_count"),
                    }
                )
            if int(pipeline_check.get("agenda_trace_missing_count") or 0) > 0:
                warn.append(
                    {
                        "code": "left_brain_proposal_agenda_trace_missing",
                        "agenda_trace_missing_count": pipeline_check.get("agenda_trace_missing_count"),
                    }
                )
        expression_feedback = (
            module_artifacts.get("expression_feedback")
            if isinstance(module_artifacts.get("expression_feedback"), dict)
            else {}
        )
        if expression_feedback:
            if int(expression_feedback.get("raw_body_included_count") or 0) > 0:
                fail.append({"code": "expression_feedback_raw_body_included"})
            if int(expression_feedback.get("live_policy_changed_count") or 0) > 0:
                fail.append({"code": "expression_feedback_live_policy_changed"})
            else:
                passed.append({"code": "expression_feedback_report_only"})
            linked_missing = int(expression_feedback.get("linked_outcome_missing_count") or 0)
            linked_count = int(expression_feedback.get("linked_outcome_count") or 0)
            if not legacy_retired and linked_missing > 0:
                fail.append(
                    {
                        "code": "right_brain_expression_feedback_missing_outcome",
                        "linked_outcome_missing_count": linked_missing,
                    }
                )
            elif not legacy_retired and linked_count > 0:
                passed.append(
                    {
                        "code": "right_brain_expression_feedback_linked",
                        "linked_outcome_count": linked_count,
                    }
                )
        expired_used = int(evidence.get("expired_used_in_scoring_count") or 0)
        if expired_used > 0:
            warn.append(
                {
                    "code": "left_brain_expired_working_used_in_scoring",
                    "expired_used_in_scoring_count": expired_used,
                }
            )
        else:
            passed.append({"code": "left_brain_expired_working_not_scored"})
        score_mode = evidence.get("score_mode")
        feature_count = int(evidence.get("feature_score_count") or 0)
        legacy_count = int(evidence.get("hash_score_legacy_count") or 0)
        legacy_comparison_count = int(evidence.get("legacy_hash_comparison_count") or evidence.get("comparison_count") or 0)
        if legacy_count > 0:
            fail.append({"code": "left_brain_legacy_hash_scores_still_primary", "value": evidence})
        elif feature_count > 0:
            if (
                score_mode == "feature_maturity_v2"
                and evidence.get("feature_score_mode") == "primary"
                and legacy_comparison_count >= feature_count
            ):
                passed.append(
                    {
                        "code": "left_brain_feature_scoring_primary_ok",
                        "feature_score_count": feature_count,
                        "legacy_hash_comparison_count": legacy_comparison_count,
                    }
                )
            else:
                warn.append({"code": "left_brain_feature_scoring_primary_incomplete", "value": evidence})
        elif int(evidence.get("score_count") or 0) > 0:
            warn.append({"code": "left_brain_feature_scoring_missing", "score_count": evidence.get("score_count")})
        skipped_run_count = int(evidence.get("skipped_run_count") or 0)
        if skipped_run_count > 0 and evidence.get("latest_cadence_skipped") is True:
            passed.append(
                {
                    "code": "evidence_scoring_cadence_skip_visible",
                    "skipped_run_count": skipped_run_count,
                    "latest_skip_reason": evidence.get("latest_skip_reason"),
                }
            )
        expression_feedback_subject_count = int(evidence.get("expression_feedback_subject_count") or 0)
        expression_feedback_linked_subject_count = int(
            evidence.get("expression_feedback_linked_subject_count") or 0
        )
        if expression_feedback_subject_count > 0:
            if expression_feedback_linked_subject_count > 0:
                passed.append(
                    {
                        "code": "left_brain_expression_feedback_context_linked",
                        "expression_feedback_subject_count": expression_feedback_subject_count,
                        "expression_feedback_linked_subject_count": expression_feedback_linked_subject_count,
                        "expression_feedback_unlinked_subject_count": evidence.get(
                            "expression_feedback_unlinked_subject_count"
                        ),
                    }
                )
            else:
                warn.append(
                    {
                        "code": "left_brain_expression_feedback_unlinked_only",
                        "expression_feedback_subject_count": expression_feedback_subject_count,
                    }
                )
        maturity_live_applied = evidence.get("maturity_live_applied") is True
        prototype_aligned_count = int(evidence.get("prototype_aligned_score_count") or 0)
        maturity_dimension_count = int(evidence.get("maturity_dimension_count") or 0)
        if maturity_live_applied:
            fail.append({"code": "left_brain_maturity_scoring_live_applied", "value": evidence})
        elif prototype_aligned_count > 0:
            if evidence.get("feature_score_mode") == "primary" and maturity_dimension_count >= 9:
                passed.append(
                    {
                        "code": "left_brain_maturity_scoring_primary_ok",
                        "prototype_aligned_score_count": prototype_aligned_count,
                        "maturity_dimension_count": maturity_dimension_count,
                    }
                )
            else:
                warn.append({"code": "left_brain_maturity_scoring_primary_incomplete", "value": evidence})
        grounded_expression = (
            {}
            if legacy_retired
            else module_artifacts.get("grounded_expression_judge")
            if isinstance(module_artifacts.get("grounded_expression_judge"), dict)
            else {}
        )
        if grounded_expression:
            if grounded_expression.get("actual_send") is True:
                fail.append({"code": "grounded_expression_actual_send_true", "value": grounded_expression})
            if grounded_expression.get("actual_execute") is True:
                fail.append({"code": "grounded_expression_actual_execute_true", "value": grounded_expression})
            if grounded_expression.get("actual_identity_write") is True:
                fail.append({"code": "grounded_expression_actual_identity_write_true", "value": grounded_expression})
            if grounded_expression.get("delivery_affected") is True:
                fail.append({"code": "grounded_expression_delivery_affected_true", "value": grounded_expression})
            if grounded_expression.get("policy_live_applied") is True:
                fail.append({"code": "grounded_expression_policy_live_applied_true", "value": grounded_expression})
            verdict_distribution = (
                grounded_expression.get("verdict_distribution")
                if isinstance(grounded_expression.get("verdict_distribution"), dict)
                else {}
            )
            if verdict_distribution:
                passed.append(
                    {
                        "code": "grounded_expression_verdict_distribution_visible",
                        "verdict_count": grounded_expression.get("verdict_count"),
                        "verdict_distribution": verdict_distribution,
                        "latest_left_map_snapshot_version": grounded_expression.get("latest_left_map_snapshot_version"),
                    }
                )
                if grounded_expression.get("verdict_distribution_degenerate") is True:
                    warn.append(
                        {
                            "code": "grounded_expression_verdict_distribution_degenerate",
                            "verdict_distribution": verdict_distribution,
                        }
                    )
            elif int(grounded_expression.get("verdict_count") or 0) > 0:
                warn.append(
                    {
                        "code": "grounded_expression_verdict_distribution_missing",
                        "verdict_count": grounded_expression.get("verdict_count"),
                    }
                )
            if grounded_expression.get("substrate_unavailable_blocker_cleared") is True:
                passed.append(
                    {
                        "code": "grounded_expression_alternate_left_map_substrate_ready",
                        "left_map_coverage_floor_met_count": grounded_expression.get(
                            "left_map_coverage_floor_met_count"
                        ),
                    }
                )
            elif int(grounded_expression.get("verdict_count") or 0) > 0:
                warn.append(
                    {
                        "code": "grounded_expression_alternate_left_map_substrate_pending",
                        "left_map_coverage_floor_met_count": grounded_expression.get(
                            "left_map_coverage_floor_met_count"
                        ),
                        "verdict_distribution_degenerate": grounded_expression.get(
                            "verdict_distribution_degenerate"
                        ),
                    }
                )
        right_brain_adapter = (
            {}
            if legacy_retired
            else module_artifacts.get("right_brain_expression_adapter")
            if isinstance(module_artifacts.get("right_brain_expression_adapter"), dict)
            else {}
        )
        if right_brain_adapter:
            if right_brain_adapter.get("latest_actual_send") is True:
                fail.append({"code": "right_brain_expression_adapter_actual_send_true", "value": right_brain_adapter})
            elif int(right_brain_adapter.get("raw_body_included_count") or 0) > 0:
                fail.append({"code": "right_brain_expression_adapter_raw_body_included", "value": right_brain_adapter})
            elif int(right_brain_adapter.get("policy_actual_execute_count") or 0) > 0:
                fail.append({"code": "right_brain_expression_policy_actual_execute_true", "value": right_brain_adapter})
            elif int(right_brain_adapter.get("policy_raw_body_included_count") or 0) > 0:
                fail.append({"code": "right_brain_expression_policy_raw_body_included", "value": right_brain_adapter})
            elif int(right_brain_adapter.get("outcome_actual_send_count") or 0) > 0:
                fail.append({"code": "right_brain_expression_outcome_actual_send_true", "value": right_brain_adapter})
            elif int(right_brain_adapter.get("outcome_actual_execute_count") or 0) > 0:
                fail.append({"code": "right_brain_expression_outcome_actual_execute_true", "value": right_brain_adapter})
            elif int(right_brain_adapter.get("outcome_raw_body_included_count") or 0) > 0:
                fail.append({"code": "right_brain_expression_outcome_raw_body_included", "value": right_brain_adapter})
            elif int(right_brain_adapter.get("outcome_internal_marker_count") or 0) > 0:
                fail.append({"code": "right_brain_expression_outcome_internal_marker", "value": right_brain_adapter})
            elif int(right_brain_adapter.get("outcome_feedback_missing_count") or 0) > 0:
                fail.append({"code": "right_brain_expression_feedback_missing_outcome", "value": right_brain_adapter})
            elif int(right_brain_adapter.get("outcome_count") or 0) > 0:
                outcome_count = int(right_brain_adapter.get("outcome_count") or 0)
                outcome_feedback_count = int(right_brain_adapter.get("outcome_feedback_count") or 0)
                passed.append(
                    {
                        "code": "right_brain_expression_outcome_recorded",
                        "outcome_count": outcome_count,
                        "latest_policy_version": right_brain_adapter.get("latest_outcome_policy_version"),
                        "latest_silent": right_brain_adapter.get("latest_outcome_silent"),
                        "outcome_feedback_count": outcome_feedback_count,
                    }
                )
                if outcome_feedback_count >= 3:
                    passed.append(
                        {
                            "code": "right_brain_expression_reaction_volume_sufficient",
                            "outcome_count": outcome_count,
                            "outcome_feedback_count": outcome_feedback_count,
                        }
                    )
                else:
                    warn.append(
                        {
                            "code": "right_brain_expression_reaction_volume_thin",
                            "outcome_count": outcome_count,
                            "outcome_feedback_count": outcome_feedback_count,
                            "minimum_feedback_count": 3,
                        }
                    )
            elif int(right_brain_adapter.get("request_count") or 0) > 0:
                warn.append(
                    {
                        "code": "right_brain_expression_outcome_missing",
                        "request_count": right_brain_adapter.get("request_count"),
                    }
                )
                passed.append(
                    {
                        "code": "right_brain_expression_adapter_visible",
                        "request_count": right_brain_adapter.get("request_count"),
                        "delivery_mode": right_brain_adapter.get("latest_delivery_mode"),
                    }
                )
        speak_permission = (
            module_artifacts.get("speak_permission")
            if isinstance(module_artifacts.get("speak_permission"), dict)
            else {}
        )
        if speak_permission:
            if int(speak_permission.get("raw_body_included_count") or 0) > 0:
                fail.append({"code": "right_brain_allow_speak_once_raw_body_included", "value": speak_permission})
            elif int(speak_permission.get("unapproved_send_count") or 0) > 0:
                fail.append({"code": "right_brain_allow_speak_once_unapproved_send", "value": speak_permission})
            elif int(speak_permission.get("error_count") or 0) > 0:
                warn.append({"code": "right_brain_allow_speak_once_errors", "value": speak_permission})
            elif int(speak_permission.get("sent_count") or 0) > 0:
                passed.append(
                    {
                        "code": "right_brain_allow_speak_once_sent",
                        "sent_count": speak_permission.get("sent_count"),
                    }
                )
    else:
        warn.append({"code": "module_artifact_summary_unavailable", "value": module_artifacts})

    error_observability = (
        snapshot.get("error_observability")
        if isinstance(snapshot.get("error_observability"), dict)
        else monitor_error_observability(snapshot)
    )
    if error_observability.get("schema_version") == "memory-os.monitor_error_observability.v0":
        passed.append(
            {
                "code": "monitor_error_observability_visible",
                "suppressed_error_count": error_observability.get("suppressed_error_count"),
                "degraded_component_count": error_observability.get("degraded_component_count"),
                "live_write_error_count": error_observability.get("live_write_error_count"),
            }
        )
        if error_observability.get("raw_body_included") is True:
            fail.append({"code": "monitor_error_observability_raw_body_included"})
        if int(error_observability.get("suppressed_error_count") or 0) > 0:
            warn.append(
                {
                    "code": "monitor_error_observability_suppressed_errors",
                    "value": {
                        "suppressed_error_count": error_observability.get("suppressed_error_count"),
                        "component_counts": error_observability.get("component_counts"),
                        "recent_error_codes": error_observability.get("recent_error_codes"),
                    },
                }
            )
        if int(error_observability.get("live_write_error_count") or 0) > 0:
            warn.append(
                {
                    "code": "monitor_live_write_errors_visible",
                    "live_write_error_count": error_observability.get("live_write_error_count"),
                    "component_counts": error_observability.get("component_counts"),
                }
            )
        if int(error_observability.get("monitor_probe_error_count") or 0) > 0:
            passed.append(
                {
                    "code": "monitor_error_observability_self_probe_error_visible",
                    "monitor_probe_error_count": error_observability.get("monitor_probe_error_count"),
                    "monitor_probe_error_codes": error_observability.get("monitor_probe_error_codes") or [],
                }
            )
    else:
        warn.append({"code": "monitor_error_observability_unavailable", "value": error_observability})

    module_cadence = snapshot.get("module_cadence", {})
    if isinstance(module_cadence, dict) and module_cadence:
        if module_cadence.get("schema_version") == "memory-os.module_cadence_monitor_summary.v0":
            boundary = module_cadence.get("boundary") if isinstance(module_cadence.get("boundary"), dict) else {}
            if any(boundary.get(key) is True for key in ("actual_send", "actual_execute", "actual_identity_write", "actual_unapproved_crystallized_approval", "cron_modified")):
                fail.append({"code": "module_cadence_boundary_true", "value": module_cadence})
            else:
                passed.append({"code": "module_cadence_report_visible"})
            if int(module_cadence.get("expected_hermes_cron_missing_count") or 0) > 0:
                warn.append({"code": "module_cadence_expected_cron_missing", "value": module_cadence})
            has_current_window_field = module_cadence.get("current_window_error_count") is not None
            current_window_error_count = int(module_cadence.get("current_window_error_count") or 0)
            historical_error_count = int(
                module_cadence.get("historical_error_count")
                if module_cadence.get("historical_error_count") is not None
                else module_cadence.get("error_count") or 0
            )
            if not has_current_window_field and int(module_cadence.get("error_count") or 0) > 0:
                warn.append({"code": "module_cadence_error_window_unknown", "value": module_cadence})
            elif current_window_error_count > 0:
                fail.append(
                    {
                        "code": "module_cadence_current_window_errors",
                        "current_window_error_count": current_window_error_count,
                        "module_counts": module_cadence.get("module_current_window_error_counts") or {},
                    }
                )
            elif historical_error_count > 0:
                passed.append(
                    {
                        "code": "module_cadence_historical_errors_visible",
                        "historical_error_count": historical_error_count,
                    }
                )
            if int(module_cadence.get("finding_count") or 0) > 0:
                warn.append({"code": "module_cadence_split_pending", "value": module_cadence})
        else:
            warn.append({"code": "module_cadence_report_unavailable", "value": module_cadence})

    legacy_archive = snapshot.get("legacy_right_brain_archive", {})
    if (
        legacy_archive.get("lifecycle") in {"retirement_pending", "retired"}
        and legacy_archive.get("status") != "ok"
    ):
        fail.append({"code": "legacy_right_brain_retirement_integrity_failed", "value": legacy_archive})

    expression_artifacts = snapshot.get("expression_artifacts", {})
    if not legacy_retired and expression_artifacts.get("schema_version") == "memory-os.expression_artifact_summary.v0":
        if expression_artifacts.get("speak_gate_actual_send") is True:
            fail.append({"code": "expression_artifact_speak_gate_actual_send_true", "value": expression_artifacts})
        else:
            passed.append({"code": "expression_artifact_summary_ok"})
        missing_eval_count = int(
            expression_artifacts.get("latest_speak_gate_missing_evaluation_count")
            if expression_artifacts.get("latest_speak_gate_missing_evaluation_count") is not None
            else expression_artifacts.get("speak_gate_missing_evaluation_count")
            or 0
        )
        missing_draft_count = int(
            expression_artifacts.get("latest_expression_draft_missing_count")
            if expression_artifacts.get("latest_expression_draft_missing_count") is not None
            else expression_artifacts.get("expression_draft_missing_count")
            or 0
        )
        if missing_draft_count > 0:
            warn.append(
                {
                    "code": "right_brain_expression_draft_missing",
                    "missing_count": missing_draft_count,
                }
            )
        else:
            passed.append({"code": "right_brain_expression_draft_created"})
        if missing_eval_count > 0:
            warn.append(
                {
                    "code": "right_brain_speak_gate_missing_evaluation",
                    "missing_count": missing_eval_count,
                }
            )
        else:
            passed.append({"code": "right_brain_speak_gate_evaluation_complete"})
    elif expression_artifacts and not legacy_retired:
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
        if session_mirror.get("raw_private_body_printed") is True:
            fail.append({"code": "session_mirror_correlation_raw_body_printed"})
        if int(session_mirror.get("written_event_ids_count") or 0) > 0:
            fail.append(
                {
                    "code": "session_mirror_correlation_wrote_events",
                    "value": session_mirror.get("written_event_ids_count"),
                }
            )
        if session_mirror.get("latest_apply_status"):
            latest_apply_written = int(session_mirror.get("latest_apply_written_event_ids_count") or 0)
            latest_apply_duplicates = int(session_mirror.get("latest_apply_duplicate_ignored_count") or 0)
            if session_mirror.get("latest_apply_raw_private_body_printed") is True:
                fail.append({"code": "session_mirror_apply_raw_private_body_printed"})
            if latest_apply_duplicates > 0:
                fail.append(
                    {
                        "code": "session_mirror_apply_duplicate_ignored",
                        "value": latest_apply_duplicates,
                    }
                )
            if latest_apply_written > 0 and session_mirror.get("latest_apply_bounded") is not True:
                fail.append({"code": "session_mirror_apply_unbounded_write", "value": latest_apply_written})
            if int(session_mirror.get("latest_apply_boundary_true_count") or 0) > 0:
                fail.append(
                    {
                        "code": "session_mirror_apply_boundary_true",
                        "boundary": session_mirror.get("latest_apply_boundary") or {},
                    }
                )
            latest_owner_approved = session_mirror.get("latest_apply_owner_approved") is True
            latest_approval_resolved = session_mirror.get("latest_apply_approval_resolved") is True
            latest_owner_channel_bound = session_mirror.get("latest_apply_owner_channel_bound") is True
            latest_auto_apply = session_mirror.get("latest_apply_auto_apply") is True
            latest_lane_graduated = session_mirror.get("latest_apply_lane_graduated") is True
            if (
                latest_apply_written > 0
                and latest_auto_apply
                and latest_lane_graduated
                and session_mirror.get("session_mirror_auto_apply_execution_gate_bound") is not True
            ):
                fail.append({"code": "session_mirror_auto_apply_execution_gate_missing"})
            if latest_owner_approved and not latest_approval_resolved:
                fail.append({"code": "session_mirror_apply_owner_approved_without_resolver"})
            if latest_approval_resolved and not latest_owner_channel_bound:
                fail.append({"code": "session_mirror_apply_owner_ref_not_owner_channel_bound"})
            if session_mirror.get("latest_apply_reused_approval_ref") is True:
                fail.append({"code": "session_mirror_apply_approval_ref_reused"})
            if (
                session_mirror.get("latest_apply_status") == "ok"
                and session_mirror.get("latest_apply_bounded") is True
                and latest_apply_written > 0
                and latest_apply_duplicates == 0
                and session_mirror.get("latest_apply_raw_private_body_printed") is not True
            ):
                passed.append(
                    {
                        "code": "session_mirror_apply_bounded_ok",
                        "written_event_ids_count": latest_apply_written,
                    }
                )
            if (
                latest_apply_written > 0
                and latest_approval_resolved
                and latest_owner_channel_bound
                and latest_owner_approved
                and session_mirror.get("latest_apply_approval_source")
                in {"owner_action_ledger", "owner_action_lane_graduation"}
                and session_mirror.get("latest_apply_reused_approval_ref") is not True
            ):
                passed.append(
                    {
                        "code": "session_mirror_apply_governed_owner_ref_ok",
                        "stable_scope_id": session_mirror.get("latest_apply_stable_scope_id") or "",
                    }
                )
            if (
                latest_apply_written > 0
                and latest_approval_resolved
                and latest_owner_channel_bound
                and latest_owner_approved
                and session_mirror.get("latest_apply_approval_source") == "owner_action_lane_graduation"
            ):
                passed.append(
                    {
                        "code": "session_mirror_apply_lane_graduated_auto_ok",
                        "stable_scope_id": session_mirror.get("latest_apply_stable_scope_id") or "",
                    }
                )
            if (
                latest_apply_written > 0
                and latest_auto_apply
                and latest_lane_graduated
                and session_mirror.get("session_mirror_auto_apply_execution_gate_bound") is True
            ):
                permit_integrity = (
                    session_mirror.get("session_mirror_auto_apply_permit_integrity")
                    if isinstance(session_mirror.get("session_mirror_auto_apply_permit_integrity"), dict)
                    else {}
                )
                if permit_integrity.get("status") == "ok":
                    passed.append(
                        {
                            "code": "session_mirror_auto_apply_execution_gate_bound",
                            "execution_gate_envelope_id": session_mirror.get("latest_apply_execution_gate_envelope_id") or "",
                        }
                    )
                    passed.append(
                        {
                            "code": "session_mirror_auto_apply_permit_integrity_ok",
                            "execution_gate_envelope_id": permit_integrity.get("execution_gate_envelope_id") or "",
                        }
                    )
                else:
                    fail.append(
                        {
                            "code": "session_mirror_auto_apply_permit_integrity_invalid",
                            "value": permit_integrity,
                        }
                    )
        if session_mirror.get("dry_run_status") == "ok" and int(session_mirror.get("dry_run_written_event_ids_count") or 0) == 0:
            passed.append({"code": "session_mirror_dry_run_ok"})
        else:
            warn.append({"code": "session_mirror_dry_run_not_ok", "value": session_mirror})
        if int(session_mirror.get("pending_session_count") or 0) > 0:
            if session_mirror.get("correlation_status") == "ok":
                pending_only_group_count = int(session_mirror.get("pending_only_group_count") or 0)
                if pending_only_group_count > 0:
                    warn.append(
                        {
                            "code": "session_mirror_pending_source_gap",
                            "pending_session_count": session_mirror.get("pending_session_count"),
                            "pending_only_groups": session_mirror.get("pending_only_groups") or [],
                        }
                    )
                else:
                    passed.append(
                        {
                            "code": "session_mirror_pending_no_correlated_gap",
                            "pending_session_count": session_mirror.get("pending_session_count"),
                        }
                    )
            else:
                warn.append(
                    {
                        "code": "session_mirror_pending_sessions",
                        "pending_session_count": session_mirror.get("pending_session_count"),
                    }
                )
    elif session_mirror:
        warn.append({"code": "session_mirror_summary_unavailable", "value": session_mirror})

    execution_gate_cron = snapshot.get("execution_gate_cron", {})
    if execution_gate_cron:
        if execution_gate_cron.get("schema_version") == "memory-os.execution_gate_cron_summary.v0":
            expected = int(execution_gate_cron.get("memory_os_owned_expected_count") or 0)
            wrapped = int(execution_gate_cron.get("memory_os_owned_wrapped_count") or 0)
            naked = int(execution_gate_cron.get("memory_os_owned_naked_count") or 0)
            unregistered_like = int(execution_gate_cron.get("memory_os_like_unregistered_count") or 0)
            if naked > 0:
                fail.append(
                    {
                        "code": "execution_gate_memory_os_cron_naked_job",
                        "count": naked,
                        "jobs": execution_gate_cron.get("naked_jobs") or [],
                    }
                )
            if unregistered_like > 0:
                fail.append(
                    {
                        "code": "execution_gate_memory_os_cron_unregistered_like_job",
                        "count": unregistered_like,
                        "jobs": execution_gate_cron.get("unregistered_like_jobs") or [],
                    }
                )
            if expected and wrapped < expected:
                warn.append(
                    {
                        "code": "execution_gate_memory_os_cron_wrapper_coverage_incomplete",
                        "expected": expected,
                        "wrapped": wrapped,
                    }
                )
            if expected and wrapped >= expected and naked == 0 and unregistered_like == 0:
                passed.append(
                    {
                        "code": "execution_gate_memory_os_cron_wrapped_ok",
                        "expected": expected,
                        "wrapped": wrapped,
                    }
                )
            if execution_gate_cron.get("classification_source") == "hermes_cron_adapter_probe":
                if execution_gate_cron.get("adapter_owner") == "hermes_memory_os_seam":
                    passed.append({"code": "execution_gate_cron_adapter_host_owned"})
                else:
                    fail.append(
                        {
                            "code": "execution_gate_cron_adapter_not_host_owned",
                            "owner": execution_gate_cron.get("adapter_owner"),
                        }
                    )
            enabled_optional_count = int(
                execution_gate_cron.get("enabled_known_optional_outside_active_registry_count") or 0
            )
            if enabled_optional_count > 0:
                warn.append(
                    {
                        "code": "execution_gate_memory_os_cron_known_optional_enabled_outside_active_registry",
                        "count": enabled_optional_count,
                        "jobs": execution_gate_cron.get("enabled_known_optional_outside_active_registry_jobs") or [],
                        "active_registry_job_count": execution_gate_cron.get("active_registry_job_count"),
                        "enabled_memory_os_job_count": execution_gate_cron.get("enabled_memory_os_job_count"),
                    }
                )
            helper_boundary_true = int(execution_gate_cron.get("helper_boundary_true_count") or 0)
            helper_boundary_unobserved = int(execution_gate_cron.get("helper_boundary_unobserved_count") or 0)
            helper_missing = int(execution_gate_cron.get("helper_completion_missing_count") or 0)
            helper_stale = int(execution_gate_cron.get("helper_completion_stale_count") or 0)
            helper_error = int(execution_gate_cron.get("helper_completion_error_count") or 0)
            if str(execution_gate_cron.get("registry_snapshot_status") or "ok") != "ok":
                fail.append(
                    {
                        "code": "execution_gate_memory_os_cron_registry_snapshot_missing_or_invalid",
                        "status": str(execution_gate_cron.get("registry_snapshot_status") or ""),
                    }
                )
            if helper_boundary_true > 0:
                fail.append(
                    {
                        "code": "execution_gate_memory_os_cron_helper_boundary_true",
                        "count": helper_boundary_true,
                    }
                )
            if helper_error > 0:
                fail.append(
                    {
                        "code": "execution_gate_memory_os_cron_helper_completion_error",
                        "count": helper_error,
                        "lanes": execution_gate_cron.get("helper_completion_error_lanes") or [],
                    }
                )
            if helper_missing > 0:
                warn.append(
                    {
                        "code": "execution_gate_memory_os_cron_helper_completion_missing",
                        "count": helper_missing,
                    }
                )
            if helper_stale > 0:
                warn.append(
                    {
                        "code": "execution_gate_memory_os_cron_helper_completion_stale",
                        "count": helper_stale,
                    }
                )
            if helper_boundary_unobserved > 0:
                warn.append(
                    {
                        "code": "execution_gate_memory_os_cron_helper_boundary_unobserved",
                        "count": helper_boundary_unobserved,
                    }
                )
            if int(execution_gate_cron.get("unclassified_count") or 0) > 0:
                warn.append(
                    {
                        "code": "execution_gate_cron_unclassified_jobs",
                        "count": execution_gate_cron.get("unclassified_count"),
                    }
                )
        else:
            warn.append({"code": "execution_gate_cron_summary_unavailable", "value": execution_gate_cron})

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
            if int(owner_review.get("owner_approved_crystallized_write_count") or 0) > 0:
                passed.append(
                    {
                        "code": "owner_review_owner_approved_crystallized_write",
                        "value": owner_review.get("owner_approved_crystallized_write_count"),
                    }
                )
            if int(owner_review.get("error_count") or 0) > 0:
                warn.append({"code": "owner_review_action_errors", "value": owner_review.get("error_count")})
            stale_count = _int_at(owner_review, ("review_queue", "stale_count"))
            if stale_count > 0:
                warn.append({"code": "owner_review_stale_items", "value": stale_count})
            burden = owner_review.get("digest_burden") if isinstance(owner_review.get("digest_burden"), dict) else {}
            if burden.get("schema_version") == "memory-os.owner_burden_budget.v0":
                passed.append(
                    {
                        "code": "owner_review_burden_budget_visible",
                        "budget_status": burden.get("budget_status"),
                        "pending_total": burden.get("pending_total"),
                        "informational_count": burden.get("informational_count"),
                        "stale_count": burden.get("stale_count"),
                    }
                )
        else:
            warn.append({"code": "owner_review_status_unavailable", "value": owner_review})

    review_aging = snapshot.get("owner_review_aging", {})
    if review_aging:
        if review_aging.get("schema_version") == "memory-os.owner_review_aging.v0":
            passed.append({"code": "owner_review_aging_ok"})
            if review_aging.get("informational_retention_days") is not None:
                passed.append(
                    {
                        "code": "owner_review_informational_aging_visible",
                        "informational_retention_days": review_aging.get("informational_retention_days"),
                        "stale_informational_count": review_aging.get("stale_informational_count"),
                        "stale_review_suggested_count": review_aging.get("stale_review_suggested_count"),
                        "stale_fyi_count": review_aging.get("stale_fyi_count"),
                    }
                )
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
            if rendered_digest.get("response_header_present") is False:
                fail.append({"code": "owner_review_rendered_digest_missing_response_header"})
            if rendered_digest.get("overview_present") is False:
                fail.append({"code": "owner_review_rendered_digest_missing_overview"})
            if int(rendered_digest.get("speak_expression_preview_missing_count") or 0) > 0:
                warn.append(
                    {
                        "code": "right_brain_review_speak_preview_missing",
                        "value": rendered_digest.get("speak_expression_preview_missing_count"),
                    }
                )
            for key in ("actual_send", "actual_execute", "actual_identity_write", "actual_unapproved_crystallized_approval"):
                if (rendered_digest.get("boundary") or {}).get(key) is True:
                    fail.append({"code": f"owner_review_rendered_digest_{key}_true"})
            if (
                rendered_digest.get("raw_body_included") is not True
                and rendered_digest.get("will_send") is not True
                and rendered_digest.get("text_has_internal_schema") is not True
                and rendered_digest.get("text_has_transcript_marker") is not True
                and int(rendered_digest.get("text_char_count") or 0) <= 2400
                and rendered_digest.get("response_header_present") is not False
                and rendered_digest.get("overview_present") is not False
            ):
                passed.append({"code": "owner_review_rendered_digest_ok"})
                passed.append({"code": "owner_review_rendered_digest_response_header_ok"})
                passed.append({"code": "owner_review_rendered_digest_overview_ok"})
                if int(rendered_digest.get("speak_item_count") or 0) > 0:
                    passed.append({"code": "right_brain_review_speak_preview_visible"})
        else:
            warn.append({"code": "owner_review_rendered_digest_unavailable", "value": rendered_digest})

    agenda_digest = snapshot.get("owner_review_agenda_digest", {})
    if agenda_digest:
        if agenda_digest.get("schema_version") == "memory-os.owner_review_rendered_digest.v0":
            if agenda_digest.get("raw_body_included") is True:
                fail.append({"code": "owner_review_agenda_digest_raw_body_included"})
            if agenda_digest.get("text_has_internal_schema") is True:
                fail.append({"code": "owner_review_agenda_digest_internal_schema_text"})
            if agenda_digest.get("text_has_transcript_marker") is True:
                fail.append({"code": "owner_review_agenda_digest_transcript_marker"})
            if int(agenda_digest.get("text_char_count") or 0) > 2400:
                fail.append({"code": "owner_review_agenda_digest_too_long", "value": agenda_digest.get("text_char_count")})
            if agenda_digest.get("digest_mode") != "agenda":
                fail.append({"code": "owner_review_agenda_digest_wrong_mode", "value": agenda_digest.get("digest_mode")})
            if agenda_digest.get("review_suggested_suppressed") is False:
                fail.append({"code": "owner_review_agenda_digest_review_suggested_not_suppressed"})
            if agenda_digest.get("fyi_suppressed") is False:
                fail.append({"code": "owner_review_agenda_digest_fyi_not_suppressed"})
            if agenda_digest.get("backlog_totals_suppressed") is False:
                fail.append({"code": "owner_review_agenda_digest_backlog_totals_visible"})
            if agenda_digest.get("decision_summary_present") is False:
                fail.append({"code": "owner_review_agenda_digest_missing_decision_summary"})
            if not any(str(item.get("code", "")).startswith("owner_review_agenda_digest_") for item in fail):
                passed.append({"code": "owner_review_agenda_digest_ok"})
        else:
            warn.append({"code": "owner_review_agenda_digest_unavailable", "value": agenda_digest})

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

    review_surface = snapshot.get("owner_review_surface", {})
    if review_surface:
        if review_surface.get("schema_version") == "memory-os.owner_review_surface_monitor.v0":
            if review_surface.get("status") == "ok":
                passed.append({"code": "owner_review_surface_ok"})
            else:
                warn.append({"code": "owner_review_surface_not_ok", "value": review_surface.get("status")})
            if int(review_surface.get("raw_body_included_count") or 0) > 0:
                fail.append({"code": "owner_review_surface_raw_body_included"})
            if int(review_surface.get("boundary_true_count") or 0) > 0:
                fail.append({"code": "owner_review_surface_boundary_true"})
            if int(review_surface.get("forbidden_owner_command_field_count") or 0) > 0:
                fail.append({
                    "code": "owner_review_surface_forbidden_command_fields",
                    "value": review_surface.get("forbidden_owner_command_fields") or [],
                })
            operations = review_surface.get("operations") if isinstance(review_surface.get("operations"), dict) else {}
            expression_context = (
                operations.get("expression_feedback_context")
                if isinstance(operations.get("expression_feedback_context"), dict)
                else {}
            )
            if expression_context.get("status") == "ok" and int(expression_context.get("feedback_action_count") or 0) > 0:
                passed.append({"code": "owner_review_surface_expression_feedback_context_visible"})
            memory_sources_context = (
                operations.get("memory_sources_feedback_context")
                if isinstance(operations.get("memory_sources_feedback_context"), dict)
                else {}
            )
            if (
                memory_sources_context.get("status") == "ok"
                and int(memory_sources_context.get("feedback_action_count") or 0) > 0
            ):
                passed.append({"code": "owner_review_surface_memory_sources_feedback_context_visible"})
            if (
                int(review_surface.get("forbidden_owner_command_field_count") or 0) == 0
                and int(review_surface.get("owner_utterance_example_count") or 0) > 0
                and int(review_surface.get("agent_tool_call_count") or 0) > 0
            ):
                passed.append({"code": "owner_review_surface_agent_tool_contract_ok"})
        else:
            warn.append({"code": "owner_review_surface_unavailable", "value": review_surface})

    ingress_guard = snapshot.get("owner_review_ingress_guard", {})
    if ingress_guard:
        if ingress_guard.get("schema_version") == "memory-os.owner_review_ingress_guard.v0":
            probe_status = str(ingress_guard.get("probe_status") or "legacy")
            if probe_status in {"bootstrap_error", "probe_error"}:
                code = (
                    "owner_review_ingress_probe_bootstrap_error"
                    if probe_status == "bootstrap_error"
                    else "owner_review_ingress_probe_error"
                )
                fail.append(
                    {
                        "code": code,
                        "stage": str(ingress_guard.get("bootstrap_stage") or "unknown"),
                        "reason": str(ingress_guard.get("bootstrap_reason_code") or "unknown"),
                    }
                )
            else:
                if ingress_guard.get("legacy_anchor_accepted") is True:
                    fail.append({"code": "owner_review_legacy_anchor_accepted", "value": "approve A2"})
                if ingress_guard.get("legacy_reject_anchor_accepted") is True:
                    fail.append({"code": "owner_review_legacy_reject_anchor_accepted", "value": "reject R1"})
                if ingress_guard.get("ordinary_anchor_text_accepted") is True:
                    fail.append({"code": "owner_review_ordinary_anchor_text_accepted"})
                if ingress_guard.get("token_command_accepted") is not True:
                    fail.append({"code": "owner_review_token_command_not_accepted"})
                if ingress_guard.get("bare_token_command_accepted") is not True:
                    fail.append({"code": "owner_review_bare_token_command_not_accepted"})
                if ingress_guard.get("slash_token_command_accepted") is not True:
                    fail.append({"code": "owner_review_slash_token_command_not_accepted"})
                if ingress_guard.get("feedback_token_command_accepted") is not True:
                    fail.append({"code": "owner_review_feedback_token_command_not_accepted"})
                if ingress_guard.get("bare_feedback_token_command_accepted") is not True:
                    fail.append({"code": "owner_review_bare_feedback_token_command_not_accepted"})
                if ingress_guard.get("gateway_hook_registered") is True:
                    fail.append({"code": "owner_review_gateway_hook_still_registered"})
                if ingress_guard.get("review_reply_tool_available") is not True:
                    fail.append({"code": "owner_review_agent_tool_unavailable"})
                if ingress_guard.get("review_reply_tool_status") != "ok":
                    fail.append({"code": "owner_review_agent_tool_not_ok", "value": ingress_guard})
                if ingress_guard.get("review_reply_tool_input_mode") != "structured":
                    fail.append({"code": "owner_review_agent_tool_not_structured", "value": ingress_guard})
                if int(ingress_guard.get("structured_review_reply_count") or 0) < 1:
                    fail.append({"code": "owner_review_structured_reply_probe_missing"})
                if int(ingress_guard.get("reply_fallback_used_count") or 0) > 0:
                    warn.append({"code": "owner_review_reply_fallback_used", "value": ingress_guard.get("reply_fallback_used_count")})
                if int(ingress_guard.get("owner_command_event_count") or 0) > 0:
                    fail.append({"code": "owner_review_command_captured_as_event"})
                if int(ingress_guard.get("owner_command_working_count") or 0) > 0:
                    fail.append({"code": "owner_review_command_promoted_to_working"})
                if int(ingress_guard.get("owner_command_candidate_count") or 0) > 0:
                    fail.append({"code": "owner_review_command_promoted_to_candidate"})
                if ingress_guard.get("owner_command_promoted_to_candidate") is True:
                    fail.append({"code": "owner_review_command_candidate_pollution"})
                if int(ingress_guard.get("owner_review_command_pollution_count") or 0) > 0:
                    fail.append({"code": "owner_review_command_pollution_count_nonzero"})
                if (
                    ingress_guard.get("legacy_anchor_accepted") is not True
                    and ingress_guard.get("legacy_reject_anchor_accepted") is not True
                    and ingress_guard.get("ordinary_anchor_text_accepted") is not True
                    and ingress_guard.get("token_command_accepted") is True
                    and ingress_guard.get("bare_token_command_accepted") is True
                    and ingress_guard.get("slash_token_command_accepted") is True
                    and ingress_guard.get("feedback_token_command_accepted") is True
                    and ingress_guard.get("bare_feedback_token_command_accepted") is True
                    and ingress_guard.get("gateway_hook_registered") is not True
                    and ingress_guard.get("review_reply_tool_available") is True
                    and ingress_guard.get("review_reply_tool_status") == "ok"
                    and ingress_guard.get("review_reply_tool_input_mode") == "structured"
                    and int(ingress_guard.get("structured_review_reply_count") or 0) >= 1
                    and int(ingress_guard.get("reply_fallback_used_count") or 0) == 0
                    and int(ingress_guard.get("owner_command_event_count") or 0) == 0
                    and int(ingress_guard.get("owner_command_working_count") or 0) == 0
                    and int(ingress_guard.get("owner_command_candidate_count") or 0) == 0
                    and int(ingress_guard.get("owner_review_command_pollution_count") or 0) == 0
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
                passed.append(
                    {
                        "code": "owner_review_proposal_followups_execution_tickets_visible",
                        "value": proposal_followups.get("execution_ticket_count"),
                    }
                )
            if proposal_followups.get("actual_execute") is True:
                fail.append({"code": "owner_review_proposal_followups_actual_execute_true"})
            boundary = proposal_followups.get("boundary") if isinstance(proposal_followups.get("boundary"), dict) else {}
            for key in ("actual_send", "actual_execute", "actual_identity_write", "actual_unapproved_crystallized_approval"):
                if boundary.get(key) is True:
                    fail.append({"code": f"owner_review_proposal_followups_{key}_true"})
            items = proposal_followups.get("items") if isinstance(proposal_followups.get("items"), list) else []
            if any(isinstance(item, dict) and item.get("actual_execute") is True for item in items):
                fail.append({"code": "owner_review_proposal_followups_item_actual_execute_true"})
            if any(isinstance(item, dict) and item.get("raw_body_included") is True for item in items):
                fail.append({"code": "owner_review_proposal_followups_item_raw_body_included"})
            awaiting_ops_gate_count = int(
                proposal_followups.get("awaiting_ops_gate_count")
                if proposal_followups.get("awaiting_ops_gate_count") is not None
                else proposal_followups.get("pending_followup_count")
                or 0
            )
            if awaiting_ops_gate_count > 0:
                warn.append(
                    {
                        "code": "owner_review_approved_proposals_pending_followup",
                        "value": awaiting_ops_gate_count,
                    }
                )
        else:
            warn.append({"code": "owner_review_proposal_followups_unavailable", "value": proposal_followups})

    proposal_auto_route = snapshot.get("owner_review_proposal_auto_route", {})
    if proposal_auto_route:
        if proposal_auto_route.get("schema_version") == "memory-os.proposal_followup_auto_route.v0":
            passed.append({"code": "owner_review_proposal_auto_route_ok"})
            lane_mode = str(proposal_auto_route.get("lane_mode") or "")
            valid_lane_modes = {
                "live_shadow_calibration",
                "limited_auto",
                "full_auto",
                "demoted_to_gated",
                "insufficient_volume_running",
            }
            if lane_mode not in valid_lane_modes:
                fail.append({"code": "owner_review_proposal_auto_route_lane_mode_invalid", "lane_mode": lane_mode})
            required_shadow_fields = {
                "sample_window_days",
                "minimum_real_samples_for_full_auto",
                "eligible_sample_count",
                "shadow_decision_count",
                "owner_agreement_count",
                "owner_disagreement_count",
                "owner_agreement_rate",
                "wilson_95_lower_bound",
                "proposal_kind_coverage",
                "current_auto_route_cap_per_day",
                "limited_auto_graduated",
                "limited_auto_evidence_source",
            }
            missing_shadow_fields = sorted(key for key in required_shadow_fields if key not in proposal_auto_route)
            if missing_shadow_fields:
                fail.append(
                    {
                        "code": "owner_review_proposal_auto_route_shadow_metrics_missing",
                        "missing_fields": missing_shadow_fields,
                    }
                )
            else:
                passed.append(
                    {
                        "code": "owner_review_proposal_auto_route_shadow_metrics_visible",
                        "lane_mode": lane_mode,
                        "eligible_sample_count": proposal_auto_route.get("eligible_sample_count"),
                        "wilson_95_lower_bound": proposal_auto_route.get("wilson_95_lower_bound"),
                    }
                )
            if proposal_auto_route.get("continue_shadow_comparison") is not True:
                fail.append({"code": "owner_review_proposal_auto_route_shadow_comparison_disabled"})
            if proposal_auto_route.get("auto_demote_on_first_boundary_or_owner_disagreement") is not True:
                fail.append({"code": "owner_review_proposal_auto_route_auto_demote_disabled"})
            if int(proposal_auto_route.get("limited_auto_first_canary_max_auto_routes_per_day") or 0) != 1:
                fail.append(
                    {
                        "code": "owner_review_proposal_auto_route_first_canary_cap_invalid",
                        "value": proposal_auto_route.get("limited_auto_first_canary_max_auto_routes_per_day"),
                    }
                )
            elif int(proposal_auto_route.get("current_auto_route_cap_per_day") or 0) > 3:
                fail.append(
                    {
                        "code": "owner_review_proposal_auto_route_current_cap_too_high",
                        "value": proposal_auto_route.get("current_auto_route_cap_per_day"),
                    }
                )
            else:
                passed.append(
                    {
                        "code": "owner_review_proposal_auto_route_probation_guard_visible",
                        "current_cap": proposal_auto_route.get("current_auto_route_cap_per_day"),
                    }
                )
            if proposal_auto_route.get("full_auto_eligible") is True and int(
                proposal_auto_route.get("shadow_decision_count") or 0
            ) < 20:
                fail.append(
                    {
                        "code": "owner_review_proposal_auto_route_full_auto_sample_floor_bypass",
                        "shadow_decision_count": proposal_auto_route.get("shadow_decision_count"),
                    }
                )
            if proposal_auto_route.get("actual_execute") is True:
                fail.append({"code": "owner_review_proposal_auto_route_actual_execute_true"})
            if int(proposal_auto_route.get("auto_followup_actual_execute_count") or 0) > 0:
                fail.append(
                    {
                        "code": "owner_review_proposal_auto_route_actual_execute_count_nonzero",
                        "value": proposal_auto_route.get("auto_followup_actual_execute_count"),
                    }
                )
            if int(proposal_auto_route.get("auto_followup_policy_write_count") or 0) > 0:
                fail.append(
                    {
                        "code": "owner_review_proposal_auto_route_policy_write_count_nonzero",
                        "value": proposal_auto_route.get("auto_followup_policy_write_count"),
                    }
                )
            if int(proposal_auto_route.get("auto_followup_actual_send_count") or 0) > 0:
                fail.append(
                    {
                        "code": "owner_review_proposal_auto_route_actual_send_count_nonzero",
                        "value": proposal_auto_route.get("auto_followup_actual_send_count"),
                    }
                )
            if int(proposal_auto_route.get("owner_action_required_boundary_count") or 0) > 0:
                passed.append(
                    {
                        "code": "owner_review_proposal_auto_route_boundary_guard_visible",
                        "value": proposal_auto_route.get("owner_action_required_boundary_count"),
                    }
                )
            boundary = (
                proposal_auto_route.get("boundary")
                if isinstance(proposal_auto_route.get("boundary"), dict)
                else {}
            )
            for key in ("actual_send", "actual_execute", "actual_identity_write", "actual_unapproved_crystallized_approval"):
                if boundary.get(key) is True:
                    fail.append({"code": f"owner_review_proposal_auto_route_{key}_true"})
        else:
            warn.append({"code": "owner_review_proposal_auto_route_unavailable", "value": proposal_auto_route})

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
                live_guard_candidate_count = int(rh31.get("live_guard_candidate_count") or 0)
                if live_guard_candidate_count > 0:
                    warn.append(
                        {
                            "code": "rh31_eval_live_guard_candidates",
                            "failure_count": rh31.get("failure_count"),
                            "live_guard_candidate_count": live_guard_candidate_count,
                        }
                    )
                else:
                    warn.append(
                        {
                            "code": "rh31_eval_measurement_signals",
                            "failure_count": rh31.get("failure_count"),
                            "measurement_signal_count": rh31.get("measurement_signal_count"),
                            "failure_class_distribution": rh31.get("failure_class_distribution") or {},
                        }
                    )
            elif rh31.get("status") == "fail":
                fail.append({"code": "rh31_eval_failed", "failure_count": rh31.get("failure_count")})
            retrieval_shadow = rh31.get("retrieval_shadow") if isinstance(rh31.get("retrieval_shadow"), dict) else {}
            if retrieval_shadow:
                if int(retrieval_shadow.get("boundary_true_count") or 0) > 0:
                    fail.append(
                        {
                            "code": "retrieval_shadow_boundary_true",
                            "value": retrieval_shadow.get("boundary_true_count"),
                        }
                    )
                if int(retrieval_shadow.get("forbidden_field_count") or 0) > 0:
                    fail.append(
                        {
                            "code": "retrieval_shadow_forbidden_fields",
                            "value": retrieval_shadow.get("forbidden_field_count"),
                        }
                    )
                if retrieval_shadow.get("route_live_applied") is True or retrieval_shadow.get("score_live_applied") is True:
                    fail.append(
                        {
                            "code": "retrieval_shadow_live_applied",
                            "route_live_applied": retrieval_shadow.get("route_live_applied") is True,
                            "score_live_applied": retrieval_shadow.get("score_live_applied") is True,
                        }
                    )
                else:
                    passed.append({"code": "retrieval_shadow_report_only"})
                if (
                    retrieval_shadow.get("live_route_live_applied") is True
                    or retrieval_shadow.get("live_score_live_applied") is True
                    or retrieval_shadow.get("live_canonical_state_changed") is True
                ):
                    fail.append(
                        {
                            "code": "retrieval_shadow_live_memory_sources_applied",
                            "live_route_live_applied": retrieval_shadow.get("live_route_live_applied") is True,
                            "live_score_live_applied": retrieval_shadow.get("live_score_live_applied") is True,
                            "live_canonical_state_changed": retrieval_shadow.get("live_canonical_state_changed") is True,
                        }
                    )
                if int(retrieval_shadow.get("run_count") or 0) > 0:
                    passed.append({"code": "retrieval_shadow_visible"})
                if retrieval_shadow.get("live_input_available") is True:
                    passed.append(
                        {
                            "code": "retrieval_shadow_live_memory_sources_visible",
                            "live_memory_sources_record_count": retrieval_shadow.get("live_memory_sources_record_count"),
                            "live_bounded_source_ref_count": retrieval_shadow.get("live_bounded_source_ref_count"),
                        }
                    )
                elif int((snapshot.get("memory_sources") or {}).get("record_count") or 0) > 0:
                    warn.append(
                        {
                            "code": "retrieval_shadow_live_memory_sources_missing",
                            "memory_sources_record_count": (snapshot.get("memory_sources") or {}).get("record_count"),
                        }
                    )
                live_gap_count = (
                    int(retrieval_shadow.get("live_shadow_source_selection_miss_count") or 0)
                    + int(retrieval_shadow.get("live_shadow_diversification_gap_count") or 0)
                    + int(retrieval_shadow.get("live_shadow_low_coverage_count") or 0)
                )
                if live_gap_count > 0:
                    passed.append(
                        {
                            "code": "retrieval_shadow_live_memory_sources_gap_visible",
                            "live_shadow_source_selection_miss_count": retrieval_shadow.get(
                                "live_shadow_source_selection_miss_count"
                            ),
                            "live_shadow_diversification_gap_count": retrieval_shadow.get(
                                "live_shadow_diversification_gap_count"
                            ),
                            "live_shadow_low_coverage_count": retrieval_shadow.get("live_shadow_low_coverage_count"),
                        }
                    )
                if int(retrieval_shadow.get("semantic_gap_count") or 0) > 0:
                    passed.append(
                        {
                            "code": "retrieval_shadow_semantic_gap_visible",
                            "semantic_gap_count": retrieval_shadow.get("semantic_gap_count"),
                        }
                    )
                else:
                    warn.append({"code": "retrieval_shadow_semantic_gap_missing"})
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
        memory_sources_surface = (
            snapshot.get("owner_review_surface", {})
            .get("operations", {})
            .get("memory_sources_feedback_context", {})
        )
        memory_sources_feedback_count = _memory_sources_feedback_count(memory_sources)
        if (
            memory_sources_feedback_count == 0
            and isinstance(memory_sources_surface, dict)
            and memory_sources_surface.get("status") == "ok"
            and int(memory_sources_surface.get("feedback_action_count") or 0) > 0
        ):
            warn.append(
                {
                    "code": "memory_sources_feedback_volume_missing",
                    "latest_memory_source_id": memory_sources_surface.get("latest_memory_source_id"),
                    "feedback_action_count": memory_sources_surface.get("feedback_action_count"),
                }
            )
        elif memory_sources_feedback_count > 0:
            passed.append(
                {
                    "code": "memory_sources_feedback_volume_present",
                    "feedback_count": memory_sources_feedback_count,
                    "window_feedback_count": memory_sources.get("feedback_count"),
                    "total_feedback_count": memory_sources.get("total_feedback_count"),
                }
            )
        if bool(memory_sources.get("policy_present")):
            passed.append(
                {
                    "code": "memory_sources_policy_present",
                    "policy_version": memory_sources.get("policy_version"),
                    "policy_apply_count": memory_sources.get("policy_apply_count"),
                }
            )
        if int(memory_sources.get("policy_actual_execute_count") or 0) > 0:
            fail.append(
                {
                    "code": "memory_sources_policy_actual_execute_true",
                    "value": memory_sources.get("policy_actual_execute_count"),
                }
            )
        if int(memory_sources.get("policy_raw_body_included_count") or 0) > 0:
            fail.append(
                {
                    "code": "memory_sources_policy_raw_body_included",
                    "value": memory_sources.get("policy_raw_body_included_count"),
                }
            )
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
        if configured_judge.get("enabled") and configured_judge.get("mode") in {"report_only", "bounded_vote"}:
            if judge_status and judge_status not in {"error", "skipped"}:
                passed.append({"code": "low_clue_llm_judge_available"})
            else:
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

    low_clue_ingress = list(snapshot.get("low_clue_ingress_matrix") or [])
    if clean_host and low_clue_ingress:
        passed.append({"code": "clean_host_low_clue_ingress_contract_not_required"})
    else:
        for item in low_clue_ingress:
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

    rh26_probes = list(snapshot.get("rh26_apply_probe") or [])
    if clean_host and rh26_probes:
        passed.append({"code": "clean_host_rh26_probe_contract_not_required"})
    else:
        rh26_anomalies = find_rh26_heading_anomalies(rh26_probes)
        for anomaly in rh26_anomalies:
            if anomaly.get("severity") == "fail":
                fail.append(anomaly)
            else:
                warn.append(anomaly)
        for probe in rh26_probes:
            if probe.get("id") == "casual_memory_system_change" and int(probe.get("chars", 0)) == 0:
                passed.append({"code": "rh26_casual_empty_precision_preserving"})

    deep_reflection = snapshot.get("deep_reflection", {})
    for key in ("actual_send", "actual_execute", "actual_identity_write", "actual_crystallized_approval"):
        if deep_reflection.get(key) is True:
            fail.append({"code": f"deep_reflection_{key}_true"})
    rolling = deep_reflection.get("rolling_injection_source_classes", {})
    selected_by_source = rolling.get("selected_by_source_class", {}) if isinstance(rolling, dict) else {}
    if selected_by_source and set(selected_by_source) == {"working"}:
        warn.append({"code": "deep_reflection_source_skew", "selected_by_source_class": selected_by_source})
    if "latest_expired_working_used_in_analysis_count" in deep_reflection:
        expired_used_in_dr = int(deep_reflection.get("latest_expired_working_used_in_analysis_count") or 0)
        if expired_used_in_dr > 0:
            warn.append(
                {
                    "code": "deep_reflection_expired_working_used_in_analysis",
                    "expired_used_in_analysis_count": expired_used_in_dr,
                }
            )
        else:
            passed.append(
                {
                    "code": "deep_reflection_expired_working_not_used",
                    "expired_skipped_count": int(deep_reflection.get("latest_expired_working_skipped_count") or 0),
                    "active_input_count": int(deep_reflection.get("latest_active_working_input_count") or 0),
                }
            )
    if int(deep_reflection.get("cadence_skipped_count") or 0) > 0:
        passed.append(
            {
                "code": "deep_reflection_cadence_skip_visible",
                "cadence_skipped_count": int(deep_reflection.get("cadence_skipped_count") or 0),
                "latest_skip_reason": str(deep_reflection.get("latest_skip_reason") or ""),
            }
        )
    if deep_reflection.get("policy_present") is True:
        passed.append(
            {
                "code": "deep_reflection_bounded_policy_visible",
                "policy_version": deep_reflection.get("policy_version"),
                "policy_apply_count": deep_reflection.get("policy_apply_count"),
            }
        )
    if deep_reflection.get("policy_live_applied") is True:
        fail.append({"code": "deep_reflection_policy_live_applied_true"})
    if int(deep_reflection.get("policy_actual_execute_count") or 0) > 0:
        fail.append({"code": "deep_reflection_policy_actual_execute_true"})
    if int(deep_reflection.get("policy_raw_body_included_count") or 0) > 0:
        fail.append({"code": "deep_reflection_policy_raw_body_included"})

    compaction = snapshot.get("compaction", {})
    if int(compaction.get("focus_none_count") or 0) > 0:
        warn.append(
            {
                "code": "compression_focus_none",
                "recent_count": compaction.get("recent_count"),
                "focus_none_count": compaction.get("focus_none_count"),
            }
        )

    l4_guard = summarize_l4_guard(snapshot)
    if int(l4_guard.get("registered_component_count") or 0) > 0:
        passed.append({"code": "l4_guard_visible", "registered_component_count": l4_guard["registered_component_count"]})
    if int(l4_guard.get("missing_registration_count") or 0) > 0:
        fail.append(
            {
                "code": "l4_guard_missing_registration",
                "components": l4_guard.get("missing_registration_components") or [],
            }
        )
    if l4_guard.get("kill_switch_enabled") is True:
        warn.append({"code": "l4_kill_switch_enabled"})

    v7_governance = summarize_v7_governance(snapshot)
    if v7_governance["shadow_live_component_count"]:
        passed.append(
            {
                "code": "v7_shadow_live_components_visible",
                "shadow_live_component_count": v7_governance["shadow_live_component_count"],
            }
        )
    if v7_governance["acting_component_count"]:
        passed.append(
            {
                "code": "v7_acting_components_visible",
                "acting_component_count": v7_governance["acting_component_count"],
            }
        )
    if int(v7_governance.get("owner_signal_owner_approved_apply_count") or 0) > 0:
        passed.append(
            {
                "code": "v7_owner_signal_owner_approved_apply_visible",
                "component": v7_governance.get("owner_signal_selected_component") or "retractable_label_miner",
                "lane": v7_governance.get("owner_signal_lane"),
                "feedback_count": v7_governance["owner_signal_owner_approved_apply_count"],
                "ready": bool(v7_governance.get("owner_signal_owner_approved_apply_ready")),
            }
        )
    enforce_expected_components = "v7_governance" in snapshot or bool(snapshot.get("v7_component_policy"))
    missing_required_components = list(v7_governance.get("missing_required_components") or [])
    if legacy_retired:
        missing_required_components = [
            component for component in missing_required_components if component != "grounded_expression_judge"
        ]
    enabled_optional_missing_components = list(v7_governance.get("enabled_optional_missing_components") or [])
    if enforce_expected_components and clean_host:
        if missing_required_components:
            warn.append(
                {
                    "code": "clean_host_v7_required_components_missing",
                    "components": missing_required_components,
                }
            )
        for item in v7_governance.get("intentionally_absent_components") or []:
            if not isinstance(item, dict):
                continue
            warn.append(
                {
                    "code": "clean_host_v7_optional_component_intentionally_absent",
                    "component": str(item.get("component") or ""),
                    "reason": str(item.get("reason") or ""),
                }
            )
    elif enforce_expected_components:
        if missing_required_components:
            fail.append(
                {
                    "code": "v7_required_components_missing",
                    "components": missing_required_components,
                }
            )
        if enabled_optional_missing_components:
            fail.append(
                {
                    "code": "v7_enabled_optional_components_missing",
                    "components": enabled_optional_missing_components,
                }
            )
        intentionally_absent_components = list(v7_governance.get("intentionally_absent_components") or [])
        if intentionally_absent_components:
            passed.append(
                {
                    "code": "v7_optional_components_intentionally_absent",
                    "components": intentionally_absent_components,
                }
            )
    installed_components = [item for item in v7_governance["components"] if item["task_installed"]]
    if installed_components and not v7_governance["memory_sources_feedback_volume_ready"]:
        warn.append({"code": "v7_memory_sources_feedback_volume_pending"})
    if installed_components and v7_governance["memory_sources_feedback_count"] > 0:
        canary_code = (
            "v7_memory_sources_feedback_canary_complete"
            if v7_governance["memory_sources_feedback_canary_complete"]
            else "v7_memory_sources_feedback_canary_running"
        )
        passed.append(
            {
                "code": canary_code,
                "feedback_count": v7_governance["memory_sources_feedback_count"],
                "target": v7_governance["memory_sources_feedback_canary_target"],
                "remaining": v7_governance["memory_sources_feedback_canary_remaining"],
            }
        )
    for item in installed_components:
        acting = str(item["autonomy_level"]) in V7_ACTING_AUTONOMY_LEVELS
        if item["pipeline_liveness"] != "live-shadow" and not acting:
            warn.append(
                {
                    "code": "v7_installed_component_not_shadow_live",
                    "component": item["component"],
                    "pipeline_liveness": item["pipeline_liveness"],
                }
            )
        if item["live_applied"] and not acting:
            fail.append(
                {
                    "code": "v7_component_live_applied_without_acting_gate",
                    "component": item["component"],
                }
            )
        for flag in ("actual_send", "actual_execute", "actual_identity_write", "actual_crystallized_approval"):
            if item[flag] and not acting:
                fail.append(
                    {
                        "code": f"v7_component_{flag}_without_acting_gate",
                        "component": item["component"],
                    }
                )

    # ── Living Memory V2-0 permanent-promotion invariants (Task 8) ──────────
    # This block must run BEFORE the clean-host/production WARN classification
    # loop below: its WARN codes (notably
    # living_memory_promotion_ledger_state_collection_failed, registered as
    # fail_if_production) are consumed by that loop for production escalation.
    # Appending them after the loop would make the production contract dead
    # code — a remote ledger-collection failure could only ever WARN.
    living_memory_promotion = snapshot.get("living_memory_promotion", {})
    if isinstance(living_memory_promotion, dict) and living_memory_promotion:
        if living_memory_promotion.get("schema_version") == "memory-os.living_memory_promotion.v0":
            auto_count = int(living_memory_promotion.get("automatic_permanent_promotion_count") or 0)
            delivery_nonpromo = int(
                living_memory_promotion.get("living_memory_owner_delivery_nonpromotion_count") or 0
            )
            # Hard-zero: no silent auto-promotion and no non-promotion Living
            # Memory item in proactive owner delivery. Query-surface provisional
            # visibility (nonpromotion_review_item_count) is intentionally NOT a
            # failure — mother-spec §2.2 preserves it.
            if auto_count > 0:
                fail.append({"code": "living_memory_automatic_permanent_promotion", "value": auto_count})
            if delivery_nonpromo > 0:
                fail.append({"code": "living_memory_owner_delivery_nonpromotion", "value": delivery_nonpromo})
            recovery_failures = int(
                living_memory_promotion.get("decision_recovery_failure_count") or 0
            )
            stale_open = int(living_memory_promotion.get("stale_open_proposal_count") or 0)
            if recovery_failures > 0:
                fail.append({
                    "code": "living_memory_decision_recovery_failure",
                    "value": recovery_failures,
                })
            if stale_open > 0:
                fail.append({"code": "living_memory_stale_open_proposal", "value": stale_open})
            if living_memory_promotion.get("ledger_state_collection_status") == "unavailable":
                # Ledger counts were explicitly not collected (e.g. remote
                # SSH/runtime probe failure) — the recovery_failures/stale_open
                # checks above ran against un-collected placeholder zeros, so
                # this must never be a silent pass (mirrors Fix 1/2 for
                # v2_exposure_monitor / clearance_snapshot_freshness), and on
                # production it must escalate to FAIL via the classification
                # loop below (fail_if_production).
                warn.append({
                    "code": "living_memory_promotion_ledger_state_collection_failed",
                    "value": living_memory_promotion.get("ledger_state_collection_error_code"),
                })
            suppressed_ledger_errors = int(
                living_memory_promotion.get("ledger_read_suppressed_error_count") or 0
            )
            if suppressed_ledger_errors > 0:
                fail.append({
                    "code": "living_memory_promotion_ledger_partial_read",
                    "value": suppressed_ledger_errors,
                })
            if living_memory_promotion.get("stale_open_evaluation_status") == "unavailable":
                # The stale-open evaluation inside
                # read_permanent_promotion_ledger_counts failed (its broad
                # except previously swallowed the exception with no consumer
                # anywhere) — the stale_open check above ran against an
                # un-evaluated zero, not a verified-clean zero. Never a
                # silent pass; registered fail_if_production, escalated by
                # the classification loop at the end of this function.
                warn.append({
                    "code": "living_memory_stale_open_evaluation_unavailable",
                    "value": living_memory_promotion.get("stale_open_evaluation_error_code"),
                })
            if auto_count == 0 and delivery_nonpromo == 0:
                passed.append({"code": "living_memory_promotion_hard_zero_ok"})
            passed.append({
                "code": "living_memory_promotion_ledger_state_visible",
                "value": {
                    "proposal_ledger_counts": living_memory_promotion.get("proposal_ledger_counts"),
                    "token_ledger_counts": living_memory_promotion.get("token_ledger_counts"),
                    "permanent_promotion_review_item_count":
                        living_memory_promotion.get("permanent_promotion_review_item_count"),
                    "living_memory_nonpromotion_review_item_count":
                        living_memory_promotion.get("living_memory_nonpromotion_review_item_count"),
                    "open_proposal_backlog_count": living_memory_promotion.get("open_proposal_backlog_count"),
                    "never_delivered_open_count": living_memory_promotion.get("never_delivered_open_count"),
                    "due_reminder_count": living_memory_promotion.get("due_reminder_count"),
                    "deferred_past_due_count": living_memory_promotion.get("deferred_past_due_count"),
                    "deciding_proposal_count": living_memory_promotion.get("deciding_proposal_count"),
                    "decision_recovery_attempt_count":
                        living_memory_promotion.get("decision_recovery_attempt_count"),
                    "decision_recovery_success_count":
                        living_memory_promotion.get("decision_recovery_success_count"),
                    "decision_recovery_failure_count": recovery_failures,
                    "stale_open_proposal_count": stale_open,
                    "target_retired_close_count":
                        living_memory_promotion.get("target_retired_close_count"),
                    "approved_reconcile_count": living_memory_promotion.get("approved_reconcile_count"),
                    "duplicate_delivery_suppressed_count":
                        living_memory_promotion.get("duplicate_delivery_suppressed_count"),
                },
            })
        else:
            warn.append({"code": "living_memory_promotion_unavailable", "value": living_memory_promotion})

    clean_host_warn_classification: list[dict[str, str]] = []
    if clean_host:
        for item in warn:
            code = str(item.get("code") or "")
            policy = CLEAN_HOST_WARN_CLASSIFICATIONS.get(code)
            if policy is None:
                fail.append({"code": "clean_host_warn_unclassified", "warn_code": code})
                continue
            clean_host_warn_classification.append({"code": code, **policy})
    else:
        for item in warn:
            code = str(item.get("code") or "")
            policy = CLEAN_HOST_WARN_CLASSIFICATIONS.get(code)
            if policy and policy.get("production_behavior") == "fail_if_production":
                failure = {
                    "code": f"{code}_in_production",
                    "reason": policy["reason"],
                    "production_behavior": policy["production_behavior"],
                }
                if "value" in item:
                    failure["value"] = item["value"]
                if "finding" in item:
                    failure["finding"] = item["finding"]
                fail.append(failure)

    status = "FAIL" if fail else "WARN" if warn else "PASS"
    evidence_labels = _monitor_evidence_labels(monitor_profile=monitor_profile, status=status)
    return {
        "status": status,
        "pass": passed,
        "warn": warn,
        "fail": fail,
        "info": info,
        "clean_host_warn_classification": clean_host_warn_classification,
        "evidence_labels": evidence_labels,
    }


def _monitor_evidence_labels(*, monitor_profile: str, status: str) -> list[str]:
    normalized_status = str(status or "").strip().lower()
    if monitor_profile == "clean_host":
        return [f"clean_host_{normalized_status}"] if normalized_status else ["clean_host_unknown"]
    return [f"live_monitor_{normalized_status}"] if normalized_status else ["live_monitor_unknown"]


def _systemd_service_failed(service: dict[str, Any]) -> bool:
    if not service:
        return False
    return service.get("ActiveState") == "failed" or service.get("Result") not in {"", "success"}


def _classify_hindsight_substrate(
    snapshot: dict[str, Any],
    passed: list[dict[str, Any]],
    fail: list[dict[str, Any]],
) -> None:
    memory_status = snapshot.get("memory_status") if isinstance(snapshot.get("memory_status"), dict) else {}
    status = snapshot.get("hindsight_substrate")
    if not isinstance(status, dict):
        status = memory_status.get("hindsight_substrate") if isinstance(memory_status.get("hindsight_substrate"), dict) else {}
    if not status:
        return
    if status.get("schema_version") != "memory-os.hindsight_substrate_status.v0":
        fail.append({"code": "hindsight_status_schema_mismatch"})
        return
    if status.get("enabled") is False and status.get("status") == "optional_not_configured":
        passed.append({"code": "hindsight_optional_off_ok"})
        return
    if status.get("enabled") is not True:
        fail.append({"code": "hindsight_status_invalid", "status": status.get("status")})
        return
    monitor = status.get("substrate_monitor") if isinstance(status.get("substrate_monitor"), dict) else {}
    substrate_recall = snapshot.get("substrate_recall")
    if isinstance(substrate_recall, dict):
        monitor = {**monitor, **substrate_recall}
    if int(monitor.get("raw_retained_count") or 0) > 0 or monitor.get("no_raw_retained") is False:
        fail.append({"code": "hindsight_raw_retain_detected"})
    if int(monitor.get("projection_stale_count") or 0) > 0:
        fail.append({"code": "hindsight_projection_stale"})
    if monitor.get("local_first_authority_preserved") is False or int(
        monitor.get("external_authoritative_count") or 0
    ) > 0:
        fail.append({"code": "hindsight_overrode_local_authority"})
    if not [item for item in fail if str(item.get("code", "")).startswith("hindsight_")]:
        passed.append({"code": "hindsight_configured_ok"})


def _classify_left_brain_signal_weaving(
    snapshot: dict[str, Any],
    passed: list[dict[str, Any]],
    warn: list[dict[str, Any]],
    fail: list[dict[str, Any]],
    *,
    clean_host: bool,
) -> None:
    if not _left_brain_signal_weaving_expected(snapshot):
        return

    host_probe = snapshot.get("host_capability_probe") if isinstance(snapshot.get("host_capability_probe"), dict) else {}
    if host_probe.get("schema_version") in {"memory-os.host_capability_probe.v0", "memory-os.host_capability_probe.v2"}:
        if host_probe.get("raw_body_included") is True or host_probe.get("secret_values_included") is True:
            fail.append({"code": "host_capability_probe_sensitive_payload"})
        else:
            contract_gap = _host_capability_contract_gap(host_probe)
            if contract_gap:
                fail.append(contract_gap)
            else:
                passed.append({"code": "host_capability_probe_contract_ok"})
                if host_probe.get("schema_version") == "memory-os.host_capability_probe.v2":
                    if host_probe.get("host_observation_owner") == "hermes_memory_os_seam":
                        passed.append({"code": "host_capability_probe_host_owned"})
                    else:
                        fail.append(
                            {
                                "code": "host_capability_probe_not_host_owned",
                                "owner": host_probe.get("host_observation_owner"),
                            }
                        )
                capabilities = host_probe.get("capabilities") if isinstance(host_probe.get("capabilities"), dict) else {}
                structural = capabilities.get("structural_write_gate") if isinstance(capabilities.get("structural_write_gate"), dict) else {}
                if host_probe.get("schema_version") == "memory-os.host_capability_probe.v2":
                    if structural.get("status") == "available":
                        passed.append({"code": "structural_write_gate_available"})
                    else:
                        fail.append(
                            {
                                "code": "structural_write_gate_not_available",
                                "status": structural.get("status"),
                                "migration_hint": structural.get("migration_hint"),
                            }
                        )
            passed.append(
                {
                    "code": "host_capability_probe_ok",
                    "capability_count": len(host_probe.get("capabilities") or {}),
                }
            )
            deployment_manifest = (
                host_probe.get("deployment_runtime_manifest")
                if isinstance(host_probe.get("deployment_runtime_manifest"), dict)
                else {}
            )
            if deployment_manifest.get("schema_version") == "memory-os.deployment_runtime_manifest.v0":
                if deployment_manifest.get("status") == "present":
                    passed.append(
                        {
                            "code": "deployment_runtime_manifest_present",
                            "deployed_head": deployment_manifest.get("deployed_head"),
                            "deployed_at": deployment_manifest.get("deployed_at"),
                        }
                    )
                elif clean_host:
                    warn.append({"code": "deployment_runtime_manifest_missing", "value": deployment_manifest})
                else:
                    fail.append({"code": "deployment_runtime_manifest_missing", "value": deployment_manifest})
    elif clean_host:
        warn.append({"code": "host_capability_probe_missing", "value": host_probe})
    else:
        fail.append({"code": "host_capability_probe_missing", "value": host_probe})

    requirements = (
        snapshot.get("signal_source_requirements")
        if isinstance(snapshot.get("signal_source_requirements"), dict)
        else {}
    )
    if requirements.get("schema_version") == "memory-os.signal_source_requirement_report.v0":
        required_missing = int(requirements.get("required_missing_count") or 0)
        if required_missing:
            target = warn if clean_host else fail
            target.append(
                {
                    "code": "signal_source_required_missing",
                    "required_missing_count": required_missing,
                    "sources": [
                        item.get("source_key")
                        for item in requirements.get("sources", [])
                        if isinstance(item, dict) and item.get("required_missing")
                    ],
                }
            )
        else:
            passed.append(
                {
                    "code": "signal_source_requirements_ok",
                    "source_count": requirements.get("source_count"),
                    "optional_missing_count": requirements.get("optional_missing_count"),
                }
            )
    elif clean_host:
        warn.append({"code": "signal_source_requirements_missing", "value": requirements})
    else:
        fail.append({"code": "signal_source_requirements_missing", "value": requirements})

    projection = snapshot.get("memory_projection") if isinstance(snapshot.get("memory_projection"), dict) else {}
    if projection.get("schema_version") == "memory-os.memory_projection_status.v0":
        projection_freshness_failed = _memory_projection_stale_after_deploy(host_probe, projection)
        if projection_freshness_failed:
            target = warn if clean_host else fail
            target.append(projection_freshness_failed)
        if projection.get("raw_body_included") is True:
            fail.append({"code": "memory_projection_raw_body_included"})
        boundary_true_count = int(projection.get("boundary_true_count") or 0)
        if boundary_true_count:
            fail.append({"code": "memory_projection_boundary_true", "count": boundary_true_count})
        source_scope_missing_count = int(projection.get("source_scope_missing_count") or 0)
        if source_scope_missing_count:
            fail.append(
                {
                    "code": "memory_projection_source_scope_missing",
                    "count": source_scope_missing_count,
                }
            )
        duplicate_source_hash_count = int(projection.get("duplicate_source_hash_count") or 0)
        duplicate_dedup_key_count = int(projection.get("duplicate_dedup_key_count") or 0)
        if duplicate_source_hash_count or duplicate_dedup_key_count:
            fail.append(
                {
                    "code": "memory_projection_duplicate_records",
                    "duplicate_source_hash_count": duplicate_source_hash_count,
                    "duplicate_dedup_key_count": duplicate_dedup_key_count,
                }
            )
        registered_source_missing_count = int(projection.get("registered_source_missing_count") or 0)
        if registered_source_missing_count:
            fail.append(
                {
                    "code": "memory_projection_registered_source_missing",
                    "count": registered_source_missing_count,
                    "sources": projection.get("registered_source_missing_keys"),
                }
            )
        else:
            passed.append(
                {
                    "code": "memory_projection_registered_source_coverage_ok",
                    "unique_source_count": projection.get("unique_source_count"),
                    "registered_source_count": projection.get("registered_source_count"),
                }
            )
        payload_fields = (
            projection.get("source_payload_fields")
            if isinstance(projection.get("source_payload_fields"), dict)
            else {}
        )
        missing_payload_fields_55c: list[dict[str, Any]] = []
        for source_key, expected_fields in MEMORY_PROJECTION_55C_REQUIRED_PAYLOAD_FIELDS.items():
            observed_fields = set(payload_fields.get(source_key) or [])
            missing_fields = sorted(expected_fields - observed_fields)
            if missing_fields:
                missing_payload_fields_55c.append({"source_key": source_key, "missing_fields": missing_fields})
        if missing_payload_fields_55c:
            target = warn if clean_host else fail
            target.append(
                {
                    "code": "memory_projection_55c_payload_field_coverage_missing",
                    "missing": missing_payload_fields_55c,
                }
            )
        else:
            passed.append(
                {
                    "code": "memory_projection_55c_payload_field_coverage_ok",
                    "source_count": len(MEMORY_PROJECTION_55C_REQUIRED_PAYLOAD_FIELDS),
                }
            )
        missing_payload_fields_55d: list[dict[str, Any]] = []
        for source_key, expected_fields in MEMORY_PROJECTION_55D_REQUIRED_PAYLOAD_FIELDS.items():
            observed_fields = set(payload_fields.get(source_key) or [])
            missing_fields = sorted(expected_fields - observed_fields)
            if missing_fields:
                missing_payload_fields_55d.append({"source_key": source_key, "missing_fields": missing_fields})
        if missing_payload_fields_55d:
            target = warn if clean_host else fail
            target.append(
                {
                    "code": "memory_projection_55d_payload_field_coverage_missing",
                    "missing": missing_payload_fields_55d,
                }
            )
        else:
            passed.append(
                {
                    "code": "memory_projection_55d_payload_field_coverage_ok",
                    "source_count": len(MEMORY_PROJECTION_55D_REQUIRED_PAYLOAD_FIELDS),
                }
            )
        missing_payload_fields_55e: list[dict[str, Any]] = []
        for source_key, expected_fields in MEMORY_PROJECTION_55E_REQUIRED_PAYLOAD_FIELDS.items():
            observed_fields = set(payload_fields.get(source_key) or [])
            missing_fields = sorted(expected_fields - observed_fields)
            if missing_fields:
                missing_payload_fields_55e.append({"source_key": source_key, "missing_fields": missing_fields})
        if missing_payload_fields_55e:
            target = warn if clean_host else fail
            target.append(
                {
                    "code": "memory_projection_55e_payload_field_coverage_missing",
                    "missing": missing_payload_fields_55e,
                }
            )
        else:
            passed.append(
                {
                    "code": "memory_projection_55e_payload_field_coverage_ok",
                    "source_count": len(MEMORY_PROJECTION_55E_REQUIRED_PAYLOAD_FIELDS),
                }
            )
        missing_payload_fields_55f: list[dict[str, Any]] = []
        for source_key, expected_fields in MEMORY_PROJECTION_55F_REQUIRED_PAYLOAD_FIELDS.items():
            observed_fields = set(payload_fields.get(source_key) or [])
            missing_fields = sorted(expected_fields - observed_fields)
            if missing_fields:
                missing_payload_fields_55f.append({"source_key": source_key, "missing_fields": missing_fields})
        if missing_payload_fields_55f:
            target = warn if clean_host else fail
            target.append(
                {
                    "code": "memory_projection_55f_payload_field_coverage_missing",
                    "missing": missing_payload_fields_55f,
                }
            )
        else:
            passed.append(
                {
                    "code": "memory_projection_55f_payload_field_coverage_ok",
                    "source_count": len(MEMORY_PROJECTION_55F_REQUIRED_PAYLOAD_FIELDS),
                }
            )
        missing_payload_fields_55g: list[dict[str, Any]] = []
        for source_key, expected_fields in MEMORY_PROJECTION_55G_REQUIRED_PAYLOAD_FIELDS.items():
            observed_fields = set(payload_fields.get(source_key) or [])
            missing_fields = sorted(expected_fields - observed_fields)
            if missing_fields:
                missing_payload_fields_55g.append({"source_key": source_key, "missing_fields": missing_fields})
        if missing_payload_fields_55g:
            target = warn if clean_host else fail
            target.append(
                {
                    "code": "memory_projection_55g_payload_field_coverage_missing",
                    "missing": missing_payload_fields_55g,
                }
            )
        else:
            passed.append(
                {
                    "code": "memory_projection_55g_payload_field_coverage_ok",
                    "source_count": len(MEMORY_PROJECTION_55G_REQUIRED_PAYLOAD_FIELDS),
                }
            )
        projection_count = int(projection.get("projection_count") or 0)
        projection_ok = (
            projection_count > 0
            and not boundary_true_count
            and not source_scope_missing_count
            and not duplicate_source_hash_count
            and not duplicate_dedup_key_count
            and not registered_source_missing_count
            and not missing_payload_fields_55c
            and not missing_payload_fields_55d
            and not missing_payload_fields_55e
            and not missing_payload_fields_55f
            and not missing_payload_fields_55g
            and not projection_freshness_failed
            and projection.get("raw_body_included") is not True
        )
        if projection_ok:
            pass_item = {"code": "memory_projection_online", "projection_count": projection_count}
            freshness_pass = _memory_projection_fresh_after_deploy(host_probe, projection)
            if freshness_pass:
                pass_item.update(freshness_pass)
            passed.append(pass_item)
        elif projection_count <= 0:
            target = warn if clean_host else fail
            target.append({"code": "memory_projection_missing_or_empty", "value": projection})
    elif clean_host:
        warn.append({"code": "memory_projection_status_missing", "value": projection})
    else:
        fail.append({"code": "memory_projection_status_missing", "value": projection})

    projection_retention = (
        snapshot.get("memory_projection_retention")
        if isinstance(snapshot.get("memory_projection_retention"), dict)
        else {}
    )
    if projection_retention.get("schema_version") == "memory-os.memory_projection_retention_status.v0":
        if projection_retention.get("raw_body_included") is True:
            fail.append({"code": "memory_projection_retention_raw_body_included"})
        if int(projection_retention.get("boundary_true_count") or 0) > 0:
            fail.append(
                {
                    "code": "memory_projection_retention_boundary_true",
                    "count": projection_retention.get("boundary_true_count"),
                }
            )
        archived_safety_count = int(projection_retention.get("latest_boundary_true_archived_count") or 0) + int(
            projection_retention.get("latest_raw_body_included_archived_count") or 0
        )
        if archived_safety_count:
            fail.append(
                {
                    "code": "memory_projection_retention_archived_safety_evidence",
                    "latest_boundary_true_archived_count": projection_retention.get("latest_boundary_true_archived_count"),
                    "latest_raw_body_included_archived_count": projection_retention.get("latest_raw_body_included_archived_count"),
                }
            )
        elif int(projection_retention.get("compaction_count") or 0) > 0:
            passed.append(
                {
                    "code": "memory_projection_retention_compaction_visible",
                    "compaction_count": projection_retention.get("compaction_count"),
                    "latest_archived_count": projection_retention.get("latest_archived_count"),
                }
            )
        elif int(projection.get("projection_count") or 0) > 0:
            target = warn if clean_host else fail
            target.append({"code": "memory_projection_retention_compaction_missing"})
    elif projection:
        target = warn if clean_host else fail
        target.append({"code": "memory_projection_retention_status_missing", "value": projection_retention})

    advisor = snapshot.get("left_brain_advisor") if isinstance(snapshot.get("left_brain_advisor"), dict) else {}
    if advisor.get("schema_version") == "memory-os.left_brain_advisor_status.v0":
        if advisor.get("raw_body_included") is True:
            fail.append({"code": "left_brain_advisor_raw_body_included"})
        boundary_true_count = int(advisor.get("boundary_true_count") or 0)
        if boundary_true_count:
            fail.append({"code": "left_brain_advisor_boundary_true", "count": boundary_true_count})
        report_count = int(advisor.get("report_count") or 0)
        if advisor.get("latest_live_closure_eligible") is True:
            if advisor.get("latest_structural_write_governance_present") is not True:
                fail.append({"code": "left_brain_advisor_structural_write_gate_missing"})
            elif (
                advisor.get("latest_structural_write_permit_status") == "valid"
                and advisor.get("latest_structural_write_lane_id") == "left_brain_advisor_report"
                and advisor.get("latest_structural_write_risk_class") == "governance_projection"
                and advisor.get("latest_structural_write_boundary_true") is not True
            ):
                passed.append({"code": "left_brain_advisor_structural_write_gate_bound"})
            else:
                fail.append(
                    {
                        "code": "left_brain_advisor_structural_write_gate_invalid",
                        "permit_status": advisor.get("latest_structural_write_permit_status"),
                        "lane_id": advisor.get("latest_structural_write_lane_id"),
                        "risk_class": advisor.get("latest_structural_write_risk_class"),
                        "boundary_true": advisor.get("latest_structural_write_boundary_true"),
                    }
                )
        if report_count > 0 and not boundary_true_count and advisor.get("raw_body_included") is not True:
            passed.append(
                {
                    "code": "left_brain_advisor_report_only_online",
                    "report_count": report_count,
                    "finding_count": advisor.get("finding_count"),
                }
            )
        else:
            target = warn if clean_host else fail
            target.append({"code": "left_brain_advisor_missing_or_empty", "value": advisor})
    elif clean_host:
        warn.append({"code": "left_brain_advisor_status_missing", "value": advisor})
    else:
        fail.append({"code": "left_brain_advisor_status_missing", "value": advisor})


def _host_capability_contract_gap(host_probe: dict[str, Any]) -> dict[str, Any] | None:
    if host_probe.get("schema_version") != "memory-os.host_capability_probe.v2":
        return None
    capabilities = host_probe.get("capabilities") if isinstance(host_probe.get("capabilities"), dict) else {}
    missing_keys = sorted(key for key in HOST_CAPABILITY_REQUIRED_KEYS if key not in capabilities)
    incomplete: list[dict[str, Any]] = []
    invalid_status: list[dict[str, Any]] = []
    for key, capability in capabilities.items():
        if not isinstance(capability, dict):
            incomplete.append({"capability_key": key, "missing_fields": sorted(HOST_CAPABILITY_REQUIRED_FIELDS)})
            continue
        missing_fields = sorted(field for field in HOST_CAPABILITY_REQUIRED_FIELDS if field not in capability)
        if missing_fields:
            incomplete.append({"capability_key": key, "missing_fields": missing_fields})
        if str(capability.get("status") or "") not in HOST_CAPABILITY_ALLOWED_STATUSES:
            invalid_status.append({"capability_key": key, "status": capability.get("status")})
    declared_contract = host_probe.get("capability_contract") if isinstance(host_probe.get("capability_contract"), dict) else {}
    declared_error = declared_contract.get("contract_status") not in {"", None, "ok"}
    if not missing_keys and not incomplete and not invalid_status and not declared_error:
        return None
    return {
        "code": "host_capability_probe_contract_incomplete",
        "missing_required_capability_keys": missing_keys,
        "incomplete_capability_count": len(incomplete),
        "incomplete_capabilities": incomplete[:20],
        "invalid_status_count": len(invalid_status),
        "invalid_status_capabilities": invalid_status[:20],
        "declared_contract_status": declared_contract.get("contract_status"),
    }


def _memory_projection_stale_after_deploy(
    host_probe: dict[str, Any],
    projection: dict[str, Any],
) -> dict[str, Any]:
    manifest = (
        host_probe.get("deployment_runtime_manifest")
        if isinstance(host_probe.get("deployment_runtime_manifest"), dict)
        else {}
    )
    if manifest.get("schema_version") != "memory-os.deployment_runtime_manifest.v0" or manifest.get("status") != "present":
        return {}
    deployed_at = _parse_utc_timestamp(str(manifest.get("deployed_at") or ""))
    if deployed_at is None:
        return {}
    latest_created_at = str(projection.get("latest_created_at") or "")
    latest_at = _parse_utc_timestamp(latest_created_at)
    if latest_at is None:
        return {
            "code": "memory_projection_freshness_missing",
            "deployed_at": manifest.get("deployed_at"),
            "latest_created_at": latest_created_at,
        }
    if latest_at < deployed_at:
        return {
            "code": "memory_projection_stale_after_deploy",
            "deployed_at": manifest.get("deployed_at"),
            "latest_created_at": latest_created_at,
            "deployed_head": manifest.get("deployed_head"),
        }
    return {}


def _memory_projection_fresh_after_deploy(
    host_probe: dict[str, Any],
    projection: dict[str, Any],
) -> dict[str, Any]:
    manifest = (
        host_probe.get("deployment_runtime_manifest")
        if isinstance(host_probe.get("deployment_runtime_manifest"), dict)
        else {}
    )
    if manifest.get("schema_version") != "memory-os.deployment_runtime_manifest.v0" or manifest.get("status") != "present":
        return {}
    deployed_at = _parse_utc_timestamp(str(manifest.get("deployed_at") or ""))
    latest_at = _parse_utc_timestamp(str(projection.get("latest_created_at") or ""))
    if deployed_at is None or latest_at is None or latest_at < deployed_at:
        return {}
    return {
        "fresh_after_deploy": True,
        "deployed_head": manifest.get("deployed_head"),
        "latest_created_at": projection.get("latest_created_at"),
    }


def _parse_utc_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _left_brain_signal_weaving_expected(snapshot: dict[str, Any]) -> bool:
    marker_steps = {"host_capability_probe", "signal_collection", "memory_projection", "left_brain_advisor"}
    evidence = snapshot.get("cognitive_loop_step_evidence")
    if isinstance(evidence, dict):
        for key in ("required_steps", "latest_step_names"):
            values = evidence.get(key)
            if isinstance(values, list) and marker_steps.intersection(str(item) for item in values):
                return True
        summary = evidence.get("latest_step_summary") if isinstance(evidence.get("latest_step_summary"), dict) else {}
        tail = summary.get("tail_step_statuses") if isinstance(summary.get("tail_step_statuses"), dict) else {}
        if marker_steps.intersection(str(key) for key in tail.keys()):
            return True
    return any(
        isinstance(snapshot.get(key), dict) and bool(snapshot.get(key))
        for key in (
            "host_capability_probe",
            "signal_source_requirements",
            "memory_projection",
            "left_brain_advisor",
        )
    )


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


def _memory_sources_feedback_count(stats: dict[str, Any]) -> int:
    return max(_to_int(stats.get("feedback_count")), _to_int(stats.get("total_feedback_count")))


def _int_at(payload: dict[str, Any], path: tuple[str, ...]) -> int:
    current: Any = payload
    for part in path:
        if not isinstance(current, dict):
            return 0
        current = current.get(part)
    return _to_int(current)


def monitor_error_observability(snapshot: dict[str, Any]) -> dict[str, Any]:
    module_artifacts = snapshot.get("module_artifacts") if isinstance(snapshot.get("module_artifacts"), dict) else {}
    component_sources = {
        "runtime": snapshot.get("heartbeat_state") if isinstance(snapshot.get("heartbeat_state"), dict) else {},
        "memory_projection": (
            snapshot.get("memory_projection") if isinstance(snapshot.get("memory_projection"), dict) else {}
        ),
        "session_mirror": snapshot.get("session_mirror") if isinstance(snapshot.get("session_mirror"), dict) else {},
        "prefetch": (
            module_artifacts.get("prefetch_observability")
            if isinstance(module_artifacts.get("prefetch_observability"), dict)
            else {}
        ),
    }
    component_counts: dict[str, int] = {}
    component_recent_codes: dict[str, list[str]] = {}
    recent_codes: list[str] = []
    live_write_error_count = 0
    monitor_probe_error_count = 0
    monitor_probe_error_codes: list[str] = []
    raw_body_included = False
    for component, payload in component_sources.items():
        error_records = _error_records_from_payload(payload if isinstance(payload, dict) else {})
        monitor_probe_records = [record for record in error_records if _is_monitor_probe_error_record(record)]
        monitor_probe_error_count += len(monitor_probe_records)
        monitor_probe_error_codes.extend(
            str(record.get("error_code") or "")
            for record in monitor_probe_records
            if str(record.get("error_code") or "")
        )
        count = _to_int(payload.get("suppressed_error_count")) if isinstance(payload, dict) else 0
        if monitor_probe_records:
            count = max(count - len(monitor_probe_records), 0)
        component_counts[component] = count
        codes = [
            code
            for code in _bounded_error_codes(payload.get("recent_error_codes") if isinstance(payload, dict) else [])
            if code not in {str(record.get("error_code") or "") for record in monitor_probe_records}
        ]
        component_recent_codes[component] = codes
        recent_codes.extend(codes)
        raw_body_included = raw_body_included or bool(payload.get("raw_body_included")) if isinstance(payload, dict) else raw_body_included
        raw_body_included = raw_body_included or any(record.get("raw_body_included") is True for record in error_records)
        live_write_error_count += sum(
            1
            for record in error_records
            if not _is_monitor_probe_error_record(record) and _is_live_write_error_record(component, record)
        )
    total_suppressed = sum(component_counts.values())
    return {
        "schema_version": "memory-os.monitor_error_observability.v0",
        "suppressed_error_count": total_suppressed,
        "degraded_component_count": sum(1 for value in component_counts.values() if value > 0),
        "live_write_error_count": live_write_error_count,
        "monitor_probe_error_count": monitor_probe_error_count,
        "monitor_probe_error_codes": _bounded_error_codes(monitor_probe_error_codes, limit=10),
        "component_counts": {key: value for key, value in sorted(component_counts.items()) if value > 0},
        "component_recent_error_codes": {
            key: value for key, value in sorted(component_recent_codes.items()) if value
        },
        "recent_error_codes": _bounded_error_codes(recent_codes, limit=10),
        "raw_body_included": raw_body_included,
    }


def _bounded_error_codes(value: Any, *, limit: int = 5) -> list[str]:
    if not isinstance(value, list):
        return []
    codes = [str(item) for item in value if str(item or "")]
    return codes[-limit:]


def _error_records_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    last_record = payload.get("last_error_record")
    if isinstance(last_record, dict):
        records.append(last_record)
    error_records = payload.get("error_records")
    if isinstance(error_records, list):
        records.extend(record for record in error_records if isinstance(record, dict))
    return records[-5:]


def _is_live_write_error_record(component: str, record: dict[str, Any]) -> bool:
    if record.get("schema_version") != "memory-os.error_record.v0":
        return False
    if str(record.get("severity") or "").lower() != "error":
        return False
    operation = str(record.get("operation") or "").lower()
    error_code = str(record.get("error_code") or "").lower()
    if component == "runtime" and operation == "heartbeat":
        return True
    write_markers = ("write", "append", "apply", "heartbeat")
    return any(marker in operation or marker in error_code for marker in write_markers)


def _is_monitor_probe_error_record(record: dict[str, Any]) -> bool:
    operation = str(record.get("operation") or "").lower()
    error_code = str(record.get("error_code") or "").lower()
    return operation.startswith("monitor_") or error_code in {"prefetch_observability_probe_error"}


def render_chinese_summary(snapshot: dict[str, Any]) -> str:
    classification = snapshot.get("classification") or classify_snapshot(snapshot)
    memory_status_raw = snapshot.get("memory_status")
    memory_status = memory_status_raw if isinstance(memory_status_raw, dict) else {}
    catchup_contract = (
        snapshot.get("index_catchup_contract")
        if isinstance(snapshot.get("index_catchup_contract"), dict)
        else index_catchup_contract(snapshot)
    )
    counts_raw = memory_status.get("counts")
    counts = counts_raw if isinstance(counts_raw, dict) else {}
    router_raw = snapshot.get("context_router")
    router = router_raw if isinstance(router_raw, dict) else {}
    deltas_raw = snapshot.get("deltas")
    deltas = deltas_raw if isinstance(deltas_raw, dict) else {}
    counts_delta_raw = deltas.get("counts_delta")
    counts_delta = counts_delta_raw if isinstance(counts_delta_raw, dict) else {}
    gateway_raw = snapshot.get("gateway")
    gateway = gateway_raw if isinstance(gateway_raw, dict) else {}
    doctor_raw = snapshot.get("doctor")
    doctor = doctor_raw if isinstance(doctor_raw, dict) else {}
    hermes_status = snapshot.get("hermes_status") if isinstance(snapshot.get("hermes_status"), dict) else {}
    lines = [
        f"监控结果: {classification['status']}",
        "",
        f"- host={snapshot.get('hostname')} profile={snapshot.get('monitor_profile', 'live')} time={snapshot.get('date_utc')}",
        f"- evidence_labels={classification.get('evidence_labels') or []}",
        (
            f"- gateway={gateway.get('ActiveState')} "
            f"pid={gateway.get('MainPID')} "
            f"hermes_gateway_running={hermes_status.get('gateway_running')} "
            f"manager={hermes_status.get('gateway_manager')} "
            f"pids={hermes_status.get('gateway_pids')}"
        ),
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
            f"prefetch_mode={memory_status.get('prefetch_mode')} "
            f"index_catchup={_index_catchup_summary(catchup_contract)}"
        ),
        f"- doctor={doctor.get('status')} findings={doctor.get('findings')}",
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
        f"- LegacyRightBrainArchive={snapshot.get('legacy_right_brain_archive')}",
        f"- ErrorObservability={_error_observability_summary(snapshot.get('error_observability') or monitor_error_observability(snapshot))}",
        f"- ModuleCadence={snapshot.get('module_cadence')}",
        f"- ExpressionArtifacts={_expression_artifacts_summary(snapshot.get('expression_artifacts') or {})}",
        f"- SessionMirror={_session_mirror_summary(snapshot.get('session_mirror') or {})}",
        f"- OwnerReview={_owner_review_summary(snapshot.get('owner_review') or {})}",
        f"- OwnerReviewAging={_owner_review_aging_summary(snapshot.get('owner_review_aging') or {})}",
        f"- OwnerReviewChannel={_owner_review_channel_summary(snapshot.get('owner_review_channel') or {})}",
        f"- OwnerDigestPreview={_owner_digest_preview_summary(snapshot.get('owner_review_digest_preview') or {})}",
        f"- OwnerRenderedDigest={_owner_rendered_digest_summary(snapshot.get('owner_review_rendered_digest') or {})}",
        f"- OwnerAgendaDigest={_owner_agenda_digest_summary(snapshot.get('owner_review_agenda_digest') or {})}",
        f"- OwnerReplyDryRun={_owner_reply_dry_run_summary(snapshot.get('owner_review_reply_dry_run') or {})}",
        f"- OwnerReviewSurface={_owner_review_surface_summary(snapshot.get('owner_review_surface') or {})}",
        f"- OwnerIngressGuard={_owner_ingress_guard_summary(snapshot.get('owner_review_ingress_guard') or {})}",
        f"- OwnerProposalFollowups={_owner_proposal_followups_summary(snapshot.get('owner_review_proposal_followups') or {})}",
        f"- OwnerProposalAutoRoute={_owner_proposal_auto_route_summary(snapshot.get('owner_review_proposal_auto_route') or {})}",
        f"- LeftBrainSignals={_left_brain_signal_summary(snapshot)}",
        f"- OwnerDeliveryStatus={_owner_delivery_status_summary(snapshot.get('owner_review_delivery_status') or {})}",
        f"- OwnerDeliveryGate={_owner_delivery_gate_summary(snapshot.get('owner_review_delivery_gate') or {})}",
        f"- OwnerCronIntegration={_owner_cron_integration_summary(snapshot.get('owner_review_cron_integration') or {})}",
        f"- RH31Eval={_rh31_summary(snapshot.get('rh31_eval') or {})}",
        f"- compaction={snapshot.get('compaction')}",
        f"- DeepReflection={_deep_reflection_summary(snapshot.get('deep_reflection') or {})}",
        f"- L4Guard={summarize_l4_guard(snapshot)}",
        f"- V7Governance={summarize_v7_governance(snapshot)}",
        f"- FullMonitorRuntime={_full_monitor_runtime_summary(snapshot.get('full_monitor_runtime_contract') or {})}",
        f"- disk={snapshot.get('disk_du')}",
        "",
        f"PASS: {[item.get('code') for item in classification['pass']]}",
        f"WARN: {[item.get('code') for item in classification['warn']]}",
        f"FAIL: {[item.get('code') for item in classification['fail']]}",
    ]
    return "\n".join(lines)


def _normalize_monitor_profile(value: Any) -> str:
    profile = str(value or "live").strip().lower().replace("-", "_")
    if profile in {"clean", "clean_host", "cleanhost", "install", "fresh_install"}:
        return "clean_host"
    return "live"


def full_monitor_runtime_contract(
    *,
    monitor_profile: str,
    elapsed_seconds: float,
    caller_timeout_seconds: int = 0,
) -> dict[str, Any]:
    profile = _normalize_monitor_profile(monitor_profile)
    target = FULL_MONITOR_CLEAN_HOST_TARGET_SECONDS if profile == "clean_host" else FULL_MONITOR_LIVE_TARGET_SECONDS
    elapsed = round(max(float(elapsed_seconds), 0.0), 3)
    caller_timeout = max(int(caller_timeout_seconds or 0), 0)
    return {
        "schema_version": "memory-os.full_monitor_runtime_contract.v0",
        "monitor_profile": profile,
        "elapsed_seconds": elapsed,
        "target_seconds": target,
        "runtime_over_target": elapsed > target,
        "minimum_caller_timeout_seconds": FULL_MONITOR_MIN_CALLER_TIMEOUT_SECONDS,
        "caller_timeout_seconds": caller_timeout,
        "caller_timeout_under_minimum": bool(caller_timeout and caller_timeout < FULL_MONITOR_MIN_CALLER_TIMEOUT_SECONDS),
        "fast_probe_recommended_timeout_seconds": FAST_PROBE_RECOMMENDED_TIMEOUT_SECONDS,
        "timeout_classification": "monitor_performance",
    }


def _classify_full_monitor_runtime_contract(
    runtime_contract: dict[str, Any],
    passed: list[dict[str, Any]],
    warn: list[dict[str, Any]],
) -> None:
    if runtime_contract.get("schema_version") != "memory-os.full_monitor_runtime_contract.v0":
        return
    passed.append(
        {
            "code": "full_monitor_runtime_contract_visible",
            "elapsed_seconds": runtime_contract.get("elapsed_seconds"),
            "target_seconds": runtime_contract.get("target_seconds"),
            "minimum_caller_timeout_seconds": runtime_contract.get("minimum_caller_timeout_seconds"),
        }
    )
    if runtime_contract.get("runtime_over_target") is True:
        warn.append(
            {
                "code": "full_monitor_runtime_over_target",
                "value": {
                    "elapsed_seconds": runtime_contract.get("elapsed_seconds"),
                    "target_seconds": runtime_contract.get("target_seconds"),
                    "evidence_level": "monitor_performance",
                },
            }
        )
    if runtime_contract.get("caller_timeout_under_minimum") is True:
        warn.append(
            {
                "code": "full_monitor_caller_timeout_below_contract",
                "value": {
                    "caller_timeout_seconds": runtime_contract.get("caller_timeout_seconds"),
                    "minimum_caller_timeout_seconds": runtime_contract.get("minimum_caller_timeout_seconds"),
                },
            }
        )


def _merge_runtime_contract_classification(snapshot: dict[str, Any]) -> None:
    classification = snapshot.get("classification")
    if not isinstance(classification, dict):
        snapshot["classification"] = classify_snapshot(snapshot)
        return
    passed = classification.setdefault("pass", [])
    warn = classification.setdefault("warn", [])
    fail = classification.setdefault("fail", [])
    if not isinstance(passed, list) or not isinstance(warn, list) or not isinstance(fail, list):
        snapshot["classification"] = classify_snapshot(snapshot)
        return
    existing_codes = {str(item.get("code") or "") for item in passed + warn if isinstance(item, dict)}
    runtime_pass: list[dict[str, Any]] = []
    runtime_warn: list[dict[str, Any]] = []
    _classify_full_monitor_runtime_contract(
        snapshot.get("full_monitor_runtime_contract")
        if isinstance(snapshot.get("full_monitor_runtime_contract"), dict)
        else {},
        runtime_pass,
        runtime_warn,
    )
    passed.extend(item for item in runtime_pass if str(item.get("code") or "") not in existing_codes)
    existing_codes.update(str(item.get("code") or "") for item in runtime_pass)
    warn.extend(item for item in runtime_warn if str(item.get("code") or "") not in existing_codes)
    classification["status"] = "FAIL" if fail else ("WARN" if warn else "PASS")
    classification["evidence_labels"] = _monitor_evidence_labels(
        monitor_profile=_normalize_monitor_profile(snapshot.get("monitor_profile")),
        status=str(classification.get("status") or ""),
    )


def _consume_remote_probe(raw: dict[str, Any], probe_key: str) -> tuple[dict[str, Any] | None, str]:
    """Consume a remote SSH sub-probe result stored at ``raw[probe_key]``.

    P3 #14: the never-silent "isinstance-dict check -> ok is True -> extract
    payload; else derive an error code" shape was hand-copied at every
    collect_snapshot() remote-consumption call site. This is the single
    shared implementation.

    Returns ``(probe_dict, "")`` when the sub-probe reported ``ok is True``
    -- callers pick out their own payload fields from ``probe_dict`` with
    their existing ``or {}`` defaults, since different probes shape their
    payload differently (this helper does not know which fields a given
    probe carries).

    Returns ``(None, error_code)`` otherwise, where ``error_code`` is the
    probe dict's own ``error_code`` (when the key is present and truthy) or
    the fallback ``"remote_probe_field_missing"`` when the probe is absent,
    not a dict, or lacks a usable ``error_code`` -- never a silent pass.
    """
    probe = raw.get(probe_key)
    if isinstance(probe, dict) and probe.get("ok") is True:
        return probe, ""
    if isinstance(probe, dict):
        error_code = probe.get("error_code")
        if error_code:
            return None, error_code
    return None, "remote_probe_field_missing"


def collect_snapshot(
    *,
    host: str = "",
    hermes_home: str = "/root/.hermes",
    python_bin: str = "python3",
    previous: dict[str, Any] | None = None,
    monitor_profile: str = "live",
) -> dict[str, Any]:
    raw = _run_probe(host, _remote_probe_script(hermes_home), python_bin=python_bin)
    raw["monitor_profile"] = _normalize_monitor_profile(monitor_profile)
    raw["rh31_eval"] = compact_rh31_eval_summary(raw.get("rh31_eval") or {})
    raw["deltas"] = compute_deltas(raw, previous)
    raw["l4_guard"] = summarize_l4_guard(raw)
    raw["v7_governance"] = summarize_v7_governance(raw)
    raw["index_catchup_contract"] = index_catchup_contract(raw)
    raw["error_observability"] = monitor_error_observability(raw)
    # Living Memory V2-0 permanent-promotion invariants. The automatic-promotion
    # hard-zero is derived from the provisional module artifact (which must never
    # live-apply an auto-promote). Ledger state counts are read directly for a
    # local run (canonical store on this filesystem), or collected remotely via
    # living_memory_promotion_probe() below (BB.6-1).
    _provisional_artifact = (raw.get("module_artifacts") or {}).get("provisional") or {}
    _lm_kwargs: dict[str, Any] = {
        "automatic_permanent_promotion_count": 1 if _provisional_artifact.get("auto_promote_live_applied") else 0,
    }
    if not host:
        _lm_kwargs["memory_os_root"] = Path(hermes_home) / "memory-os"
        try:
            from plugins.memory.memory_os.clearance_receipts import clearance_snapshot_freshness
            from plugins.memory.memory_os.exposure_rollup import exposure_monitor_stats
            from plugins.memory.memory_os.roots import MemoryOSRoots
            from plugins.memory.memory_os.store import MemoryOSStore

            _roots = MemoryOSRoots.from_hermes_home(hermes_home, profile="default")
            _store = MemoryOSStore(_roots)
            _v2_exposure = exposure_monitor_stats(_store)
            raw["v2_exposure_monitor"] = _v2_exposure
            raw["clearance_snapshot_freshness"] = clearance_snapshot_freshness(
                _roots,
                for_activation=_v2_exposure.get("v2c_unfreeze_ready") is True,
            )
        except Exception as exc:
            raw["v2_exposure_monitor"] = {"schema_era_health": "unavailable", "error_code": type(exc).__name__}
            raw["clearance_snapshot_freshness"] = {"status": "unavailable", "error_code": type(exc).__name__}
    else:
        # Fix 1: collect exposure_monitor_stats / clearance_snapshot_freshness
        # on the remote host too, using the same SSH remote-execution pattern
        # as the rest of _remote_probe_script() (see
        # v2_exposure_and_clearance_probe() inside the generated script).
        # Production hosts must not silently skip these checks — if the
        # remote sub-probe is missing or reports failure (SSH error, missing
        # runtime, bad JSON), fall through to an explicit "unavailable" +
        # error_code shape, which classify_snapshot turns into a WARN
        # (never a silent pass).
        _v2_payload, _v2_error_code = _consume_remote_probe(raw, "v2_exposure_and_clearance_probe")
        if _v2_payload is not None:
            raw["v2_exposure_monitor"] = _v2_payload.get("v2_exposure_monitor") or {}
            raw["clearance_snapshot_freshness"] = _v2_payload.get("clearance_snapshot_freshness") or {}
        else:
            raw["v2_exposure_monitor"] = {"schema_era_health": "unavailable", "error_code": _v2_error_code}
            raw["clearance_snapshot_freshness"] = {"status": "unavailable", "error_code": _v2_error_code}

        # BB.6-1: collect permanent-promotion ledger counts on the remote
        # host too. Without this, decision_recovery_failure_count and
        # stale_open_proposal_count stayed hardcoded at 0 on every remote
        # (production) run, making their FAIL checks in classify_snapshot
        # structurally unreachable — a silent production false-negative.
        # Same never-silent contract as the v2_exposure block above.
        _lm_payload, _lm_error_code = _consume_remote_probe(raw, "living_memory_promotion_probe")
        if _lm_payload is not None:
            _lm_kwargs["ledger_counts"] = _lm_payload.get("counts") or {}
        else:
            _lm_kwargs["ledger_collection_error"] = _lm_error_code
    raw["schema_version"] = "memory-os.monitor.v1"
    raw["living_memory_promotion"] = summarize_living_memory_promotion(**_lm_kwargs)
    raw["classification"] = classify_snapshot(raw)
    return raw


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="")
    parser.add_argument("--hermes-home", default="/root/.hermes")
    parser.add_argument("--python-bin", default="python3")
    parser.add_argument("--previous-json")
    parser.add_argument("--snapshot-out")
    parser.add_argument("--output", choices=["summary", "json"], default="summary")
    parser.add_argument("--monitor-profile", choices=["live", "clean-host"], default="")
    parser.add_argument(
        "--caller-timeout-seconds",
        type=int,
        default=0,
        help="Optional wrapper timeout used by the caller; values below 300s are WARN evidence, not runtime failure.",
    )
    args = parser.parse_args(argv)
    try:
        host_profile = resolve_host_runtime_profile(
            host=str(args.host),
            hermes_home=str(args.hermes_home),
            python_bin=str(args.python_bin),
            monitor_profile=str(args.monitor_profile or ""),
            require_remote_repo_root=False,
        )
    except ValueError as exc:
        parser.error(str(exc))

    previous = None
    if args.previous_json:
        previous_path = Path(args.previous_json)
        if previous_path.exists():
            previous = json.loads(previous_path.read_text(encoding="utf-8"))
    monitor_profile = _normalize_monitor_profile(host_profile.monitor_profile)
    started = time.monotonic()
    snapshot = collect_snapshot(
        host=args.host,
        hermes_home=args.hermes_home,
        python_bin=args.python_bin,
        previous=previous,
        monitor_profile=monitor_profile,
    )
    elapsed = time.monotonic() - started
    snapshot.setdefault("host_runtime_profile", host_profile.to_dict())
    snapshot.setdefault("host_runtime_profile_source", host_profile.profile_source)
    snapshot.setdefault("monitor_profile", monitor_profile)
    snapshot["full_monitor_runtime_contract"] = full_monitor_runtime_contract(
        monitor_profile=monitor_profile,
        elapsed_seconds=elapsed,
        caller_timeout_seconds=int(args.caller_timeout_seconds or 0),
    )
    _merge_runtime_contract_classification(snapshot)
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
        "active_working_input_count": status.get("latest_active_working_input_count"),
        "expired_working_skipped_count": status.get("latest_expired_working_skipped_count"),
        "expired_working_used_in_analysis_count": status.get("latest_expired_working_used_in_analysis_count"),
        "policy_present": status.get("policy_present"),
        "policy_version": status.get("policy_version"),
        "policy_apply_count": status.get("policy_apply_count"),
        "policy_live_applied": status.get("policy_live_applied"),
        "actual_send": status.get("actual_send"),
        "actual_execute": status.get("actual_execute"),
        "actual_identity_write": status.get("actual_identity_write"),
        "actual_crystallized_approval": status.get("actual_crystallized_approval"),
    }


def _memory_sources_summary(stats: dict[str, Any]) -> dict[str, Any]:
    return {
        "record_count": stats.get("record_count"),
        "total_record_count": stats.get("total_record_count"),
        "file_size_bytes": stats.get("file_size_bytes"),
        "feedback_count": stats.get("feedback_count"),
        "total_feedback_count": stats.get("total_feedback_count"),
        "feedback_ratings": stats.get("feedback_rating_distribution"),
        "total_feedback_ratings": stats.get("total_feedback_rating_distribution"),
        "feedback_file_size_bytes": stats.get("feedback_file_size_bytes"),
        "policy_present": stats.get("policy_present"),
        "policy_version": stats.get("policy_version"),
        "policy_apply_count": stats.get("policy_apply_count"),
        "latest_policy_apply_id": stats.get("latest_policy_apply_id"),
        "policy_actual_execute_count": stats.get("policy_actual_execute_count"),
        "policy_raw_body_included_count": stats.get("policy_raw_body_included_count"),
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
        "failure_class_distribution": summary.get("failure_class_distribution"),
        "measurement_signal_count": summary.get("measurement_signal_count"),
        "live_guard_candidate_count": summary.get("live_guard_candidate_count"),
        "boundary_true_count": summary.get("boundary_true_count"),
        "forbidden_field_count": summary.get("forbidden_field_count"),
        "report_written": summary.get("report_written") if "report_written" in summary else bool(summary.get("report_dir")),
    }


def _module_artifacts_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "digest": summary.get("digest"),
        "evidence": summary.get("evidence"),
        "imagination_loop": summary.get("imagination_loop"),
        "proposal_queue": summary.get("proposal_queue"),
        "self_evolution": summary.get("self_evolution"),
        "governance_feedback": summary.get("governance_feedback"),
        "left_brain_pipeline_check": summary.get("left_brain_pipeline_check"),
        "deep_reflection": summary.get("deep_reflection"),
        "ops_gate": summary.get("ops_gate"),
        "speak_gate": summary.get("speak_gate"),
        "expression_draft": summary.get("expression_draft"),
        "expression_feedback": summary.get("expression_feedback"),
        "right_brain_expression_adapter": summary.get("right_brain_expression_adapter"),
        "symbolic_offloader": summary.get("symbolic_offloader"),
        "prefetch_observability": _error_component_summary(summary.get("prefetch_observability") or {}),
    }


def _error_component_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": summary.get("schema_version"),
        "suppressed_error_count": summary.get("suppressed_error_count"),
        "recent_error_codes": summary.get("recent_error_codes"),
    }


def _error_observability_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": summary.get("schema_version"),
        "suppressed_error_count": summary.get("suppressed_error_count"),
        "degraded_component_count": summary.get("degraded_component_count"),
        "live_write_error_count": summary.get("live_write_error_count"),
        "monitor_probe_error_count": summary.get("monitor_probe_error_count"),
        "monitor_probe_error_codes": summary.get("monitor_probe_error_codes"),
        "component_counts": summary.get("component_counts"),
        "recent_error_codes": summary.get("recent_error_codes"),
        "raw_body_included": summary.get("raw_body_included"),
    }


def _full_monitor_runtime_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": summary.get("schema_version"),
        "monitor_profile": summary.get("monitor_profile"),
        "elapsed_seconds": summary.get("elapsed_seconds"),
        "target_seconds": summary.get("target_seconds"),
        "runtime_over_target": summary.get("runtime_over_target"),
        "minimum_caller_timeout_seconds": summary.get("minimum_caller_timeout_seconds"),
        "caller_timeout_seconds": summary.get("caller_timeout_seconds"),
        "caller_timeout_under_minimum": summary.get("caller_timeout_under_minimum"),
        "fast_probe_recommended_timeout_seconds": summary.get("fast_probe_recommended_timeout_seconds"),
        "timeout_classification": summary.get("timeout_classification"),
    }


def _expression_artifacts_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "expression_draft_count": summary.get("expression_draft_count"),
        "expression_draft_created_count": summary.get("expression_draft_created_count"),
        "expression_draft_missing_count": summary.get("expression_draft_missing_count"),
        "latest_expression_draft_missing_count": summary.get("latest_expression_draft_missing_count"),
        "expression_feedback_count": summary.get("expression_feedback_count"),
        "expression_feedback_linked_outcome_count": summary.get("expression_feedback_linked_outcome_count"),
        "expression_feedback_unlinked_count": summary.get("expression_feedback_unlinked_count"),
        "speak_gate_evaluated_count": summary.get("speak_gate_evaluated_count"),
        "speak_gate_missing_evaluation_count": summary.get("speak_gate_missing_evaluation_count"),
        "latest_speak_gate_missing_evaluation_count": summary.get("latest_speak_gate_missing_evaluation_count"),
        "latest_speak_gate_evaluated_count": summary.get("latest_speak_gate_evaluated_count"),
        "speak_gate_decision_distribution": summary.get("speak_gate_decision_distribution"),
        "speak_gate_would_send_count": summary.get("speak_gate_would_send_count"),
        "speak_gate_blocked_count": summary.get("speak_gate_blocked_count"),
        "speak_gate_actual_send": summary.get("speak_gate_actual_send"),
        "right_brain_adapter_request_count": summary.get("right_brain_adapter_request_count"),
        "right_brain_adapter_latest_channel": summary.get("right_brain_adapter_latest_channel"),
        "right_brain_adapter_latest_delivery_mode": summary.get("right_brain_adapter_latest_delivery_mode"),
        "right_brain_adapter_latest_actual_send": summary.get("right_brain_adapter_latest_actual_send"),
        "right_brain_adapter_raw_body_included_count": summary.get("right_brain_adapter_raw_body_included_count"),
        "speak_permission_sent_count": summary.get("speak_permission_sent_count"),
        "speak_permission_error_count": summary.get("speak_permission_error_count"),
        "right_brain_adapter_policy_present": summary.get("right_brain_adapter_policy_present"),
        "right_brain_adapter_policy_version": summary.get("right_brain_adapter_policy_version"),
        "right_brain_adapter_policy_apply_count": summary.get("right_brain_adapter_policy_apply_count"),
        "right_brain_adapter_outcome_count": summary.get("right_brain_adapter_outcome_count"),
        "right_brain_adapter_latest_outcome_silent": summary.get("right_brain_adapter_latest_outcome_silent"),
        "right_brain_adapter_latest_outcome_policy_version": summary.get("right_brain_adapter_latest_outcome_policy_version"),
        "right_brain_adapter_outcome_internal_marker_count": summary.get("right_brain_adapter_outcome_internal_marker_count"),
        "right_brain_adapter_outcome_feedback_count": summary.get("right_brain_adapter_outcome_feedback_count"),
        "right_brain_adapter_latest_outcome_feedback_count": summary.get("right_brain_adapter_latest_outcome_feedback_count"),
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
        "correlation_status": summary.get("correlation_status"),
        "apply_count": summary.get("apply_count"),
        "latest_apply_status": summary.get("latest_apply_status"),
        "latest_apply_bounded": summary.get("latest_apply_bounded"),
        "latest_apply_written_event_ids_count": summary.get("latest_apply_written_event_ids_count"),
        "pending_only_groups": summary.get("pending_only_groups"),
        "internet_data_collection_pending_count": summary.get("internet_data_collection_pending_count"),
        "internet_data_collection_provider_count": summary.get("internet_data_collection_provider_count"),
        "suppressed_error_count": summary.get("suppressed_error_count"),
        "recent_error_codes": summary.get("recent_error_codes"),
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
        "burden_budget_status": burden.get("budget_status"),
        "pending_total": burden.get("pending_total"),
        "review_suggested": burden.get("review_suggested_count"),
        "fyi": burden.get("fyi_count"),
        "informational": burden.get("informational_count"),
        "stale_budget_count": burden.get("stale_count"),
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
        "unknown_timestamp_by_item_type": summary.get("unknown_timestamp_by_item_type"),
        "created_at_coverage_ratio": summary.get("created_at_coverage_ratio"),
        "created_at_source_distribution": summary.get("created_at_source_distribution"),
        "created_at_source_by_item_type": summary.get("created_at_source_by_item_type"),
        "true_aged": summary.get("true_aged_count"),
        "unknown_aged": summary.get("unknown_aged_count"),
        "informational_retention_days": summary.get("informational_retention_days"),
        "stale_informational": summary.get("stale_informational_count"),
        "stale_review_suggested": summary.get("stale_review_suggested_count"),
        "stale_fyi": summary.get("stale_fyi_count"),
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
        "speak_item_count": summary.get("speak_item_count"),
        "speak_expression_preview_count": summary.get("speak_expression_preview_count"),
        "speak_expression_preview_missing_count": summary.get("speak_expression_preview_missing_count"),
        "section_counts": summary.get("section_counts"),
    }


def _owner_agenda_digest_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": summary.get("status"),
        "digest_mode": summary.get("digest_mode"),
        "raw_body_included": summary.get("raw_body_included"),
        "text_char_count": summary.get("text_char_count"),
        "decision_summary_present": summary.get("decision_summary_present"),
        "review_suggested_suppressed": summary.get("review_suggested_suppressed"),
        "fyi_suppressed": summary.get("fyi_suppressed"),
        "backlog_totals_suppressed": summary.get("backlog_totals_suppressed"),
        "section_counts": summary.get("section_counts"),
        "counts": summary.get("counts"),
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
        "owner_utterance_source": summary.get("owner_utterance_source"),
    }


def _owner_review_surface_summary(summary: dict[str, Any]) -> dict[str, Any]:
    operations = summary.get("operations") if isinstance(summary.get("operations"), dict) else {}
    return {
        "status": summary.get("status"),
        "raw_body_included_count": summary.get("raw_body_included_count"),
        "boundary_true_count": summary.get("boundary_true_count"),
        "forbidden_owner_command_field_count": summary.get("forbidden_owner_command_field_count"),
        "forbidden_owner_command_fields": summary.get("forbidden_owner_command_fields"),
        "owner_utterance_example_count": summary.get("owner_utterance_example_count"),
        "agent_tool_call_count": summary.get("agent_tool_call_count"),
        "operations": {
            name: {
                "status": op.get("status"),
                "item_count": op.get("item_count"),
                "feedback_action_count": op.get("feedback_action_count"),
                "latest_outcome_id": op.get("latest_outcome_id"),
                "latest_memory_source_id": op.get("latest_memory_source_id"),
                "source": op.get("source"),
                "forbidden_owner_command_field_count": op.get("forbidden_owner_command_field_count"),
                "owner_utterance_example_count": op.get("owner_utterance_example_count"),
                "agent_tool_call_count": op.get("agent_tool_call_count"),
            }
            for name, op in operations.items()
            if isinstance(op, dict)
        },
    }


def _owner_ingress_guard_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "legacy_anchor_accepted": summary.get("legacy_anchor_accepted"),
        "legacy_reject_anchor_accepted": summary.get("legacy_reject_anchor_accepted"),
        "ordinary_anchor_text_accepted": summary.get("ordinary_anchor_text_accepted"),
        "token_command_accepted": summary.get("token_command_accepted"),
        "bare_token_command_accepted": summary.get("bare_token_command_accepted"),
        "slash_token_command_accepted": summary.get("slash_token_command_accepted"),
        "feedback_token_command_accepted": summary.get("feedback_token_command_accepted"),
        "bare_feedback_token_command_accepted": summary.get("bare_feedback_token_command_accepted"),
        "gateway_hook_registered": summary.get("gateway_hook_registered"),
        "gateway_safety_skip_count": summary.get("gateway_safety_skip_count"),
        "review_reply_tool_available": summary.get("review_reply_tool_available"),
        "review_reply_tool_status": summary.get("review_reply_tool_status"),
        "structured_review_reply_count": summary.get("structured_review_reply_count"),
        "reply_fallback_used_count": summary.get("reply_fallback_used_count"),
        "owner_command_event_count": summary.get("owner_command_event_count"),
        "owner_command_working_count": summary.get("owner_command_working_count"),
        "owner_command_candidate_count": summary.get("owner_command_candidate_count"),
        "owner_review_command_pollution_count": summary.get("owner_review_command_pollution_count"),
    }


def _owner_proposal_followups_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "approved": summary.get("approved_proposal_count"),
        "pending": summary.get("pending_followup_count"),
        "open": summary.get("open_followup_count"),
        "shown": summary.get("shown_count"),
        "overflow": summary.get("overflow_count"),
        "awaiting_ops_gate": summary.get("awaiting_ops_gate_count"),
        "ops_gate_reviewed": summary.get("ops_gate_reviewed_count"),
        "supported_apply_ready": summary.get("supported_apply_ready_count"),
        "unsupported_requires_execution_ticket": summary.get("unsupported_requires_execution_ticket_count"),
        "awaiting_explicit_execution": summary.get("awaiting_explicit_execution_count"),
        "ticket_created": summary.get("ticket_created_count"),
        "awaiting_typed_execution_plan": summary.get("awaiting_typed_execution_plan_count"),
        "evidence_resolved": summary.get("evidence_resolved_count"),
        "bounded_policy_written": summary.get("bounded_policy_written_count"),
        "policy_apply_count": summary.get("policy_apply_count"),
        "memory_sources_policy_apply_count": summary.get("memory_sources_policy_apply_count"),
        "deep_reflection_policy_apply_count": summary.get("deep_reflection_policy_apply_count"),
        "execution_tickets": summary.get("execution_ticket_count"),
        "actual_execute": summary.get("actual_execute"),
        "raw_body_included": summary.get("raw_body_included"),
    }


def _owner_proposal_auto_route_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "lane_mode": summary.get("lane_mode"),
        "sample_window_days": summary.get("sample_window_days"),
        "eligible_sample_count": summary.get("eligible_sample_count"),
        "shadow_decision_count": summary.get("shadow_decision_count"),
        "owner_agreement_rate": summary.get("owner_agreement_rate"),
        "wilson_95_lower_bound": summary.get("wilson_95_lower_bound"),
        "full_auto_eligible": summary.get("full_auto_eligible"),
        "limited_auto_eligible": summary.get("limited_auto_eligible"),
        "limited_auto_graduated": summary.get("limited_auto_graduated"),
        "limited_auto_evidence_source": summary.get("limited_auto_evidence_source"),
        "current_auto_route_cap_per_day": summary.get("current_auto_route_cap_per_day"),
        "continue_shadow_comparison": summary.get("continue_shadow_comparison"),
        "auto_demote_on_first_boundary_or_owner_disagreement": summary.get("auto_demote_on_first_boundary_or_owner_disagreement"),
        "eligible": summary.get("eligible_count"),
        "selected": summary.get("selected_count"),
        "routed": summary.get("auto_followup_routed_count"),
        "actual_execute_count": summary.get("auto_followup_actual_execute_count"),
        "policy_write_count": summary.get("auto_followup_policy_write_count"),
        "actual_send_count": summary.get("auto_followup_actual_send_count"),
        "owner_boundary_count": summary.get("owner_action_required_boundary_count"),
        "boundary_rejected": summary.get("auto_followup_boundary_rejected_count"),
        "dry_run": summary.get("dry_run"),
        "actual_execute": summary.get("actual_execute"),
    }


def _left_brain_signal_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    host_probe = snapshot.get("host_capability_probe") if isinstance(snapshot.get("host_capability_probe"), dict) else {}
    requirements = (
        snapshot.get("signal_source_requirements")
        if isinstance(snapshot.get("signal_source_requirements"), dict)
        else {}
    )
    projection = snapshot.get("memory_projection") if isinstance(snapshot.get("memory_projection"), dict) else {}
    advisor = snapshot.get("left_brain_advisor") if isinstance(snapshot.get("left_brain_advisor"), dict) else {}
    return {
        "host_probe_schema": host_probe.get("schema_version"),
        "capability_count": len(host_probe.get("capabilities") or {}),
        "source_count": requirements.get("source_count"),
        "required_missing_count": requirements.get("required_missing_count"),
        "optional_missing_count": requirements.get("optional_missing_count"),
        "projection_status": projection.get("status"),
        "projection_count": projection.get("projection_count"),
        "projection_boundary_true_count": projection.get("boundary_true_count"),
        "advisor_status": advisor.get("status"),
        "advisor_report_count": advisor.get("report_count"),
        "advisor_finding_count": advisor.get("finding_count"),
        "advisor_boundary_true_count": advisor.get("boundary_true_count"),
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
        "llm_available": judge.get("status") not in {"error", "skipped", "", None},
    }


def _audit_actions_summary(stats: dict[str, Any], deltas: dict[str, Any]) -> dict[str, Any]:
    return {
        "total": stats.get("total_count"),
        "recent_window": stats.get("recent_window"),
        "recent_top": _top_dict(stats.get("recent_action_counts") or {}, 8),
        "delta": _top_dict(deltas.get("audit_action_delta") or {}, 8),
        "structured_review_reply_count": stats.get("structured_review_reply_count"),
        "reply_fallback_used_count": stats.get("reply_fallback_used_count"),
        "recent_structured_review_reply_count": stats.get("recent_structured_review_reply_count"),
        "recent_reply_fallback_used_count": stats.get("recent_reply_fallback_used_count"),
        "gateway_safety_skip_count": stats.get("gateway_safety_skip_count"),
        "recent_gateway_safety_skip_count": stats.get("recent_gateway_safety_skip_count"),
    }


def _heartbeat_state_summary(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "exists": state.get("exists"),
        "fresh": state.get("fresh"),
        "age_seconds": state.get("age_seconds"),
        "last_heartbeat_at": state.get("last_heartbeat_at"),
        "processed_event_count": state.get("processed_event_count"),
        "last_processed_event_id": state.get("last_processed_event_id"),
        "suppressed_error_count": state.get("suppressed_error_count"),
        "recent_error_codes": state.get("recent_error_codes"),
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


def _run_probe(host: str, script: str, python_bin: str = "python3") -> dict[str, Any]:
    """Run a probe script locally or via SSH.

    When *host* is empty, the script runs in a local subprocess.
    Otherwise it is sent to the named SSH host via stdin.
    """
    if host:
        completed = subprocess.run(
            ["ssh", host, f"{python_bin} -"],
            input=script,
            text=True,
            capture_output=True,
            check=True,
        )
    else:
        completed = subprocess.run(
            [python_bin, "-"],
            input=script,
            text=True,
            capture_output=True,
            check=True,
        )
    return json.loads(completed.stdout)


def _remote_probe_script(hermes_home: str = "/root/.hermes") -> str:
    _hh = json.dumps(str(hermes_home))
    return r'''
import concurrent.futures, hashlib, json, os, re, subprocess, sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

_hermes_home = ''' + _hh + r'''
for _path in (
    os.path.join(_hermes_home, "memory-os/runtime/python"),
    os.path.join(_hermes_home, "plugins/memory_os"),
):
    if os.path.isdir(_path) and _path not in sys.path:
        sys.path.insert(0, _path)

def _command_timeout_seconds():
    try:
        return max(1, min(int(os.environ.get("MEMORY_OS_MONITOR_COMMAND_TIMEOUT_SECONDS", "20")), 300))
    except (TypeError, ValueError):
        return 20


def run(cmd, env=None, timeout_seconds=None):
    effective_timeout = _command_timeout_seconds() if timeout_seconds is None else max(1, min(int(timeout_seconds), 300))
    try:
        out = subprocess.check_output(
            cmd,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            stdin=subprocess.DEVNULL,
            timeout=effective_timeout,
        )
        return {"ok": True, "out": out.strip(), "code": 0}
    except subprocess.TimeoutExpired as exc:
        output = exc.output or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        detail = str(output).strip()
        suffix = "command_timeout_seconds=" + str(effective_timeout)
        return {"ok": False, "out": (detail + "\n" + suffix).strip(), "code": 124}
    except subprocess.CalledProcessError as exc:
        return {"ok": False, "out": (exc.output or "").strip(), "code": exc.returncode}
    except OSError as exc:
        return {"ok": False, "out": str(exc), "code": 127}

def system_show(unit):
    r = run(["systemctl", "--user", "show", unit, "-p", "LoadState", "-p", "ActiveState", "-p", "SubState", "-p", "UnitFileState", "-p", "MainPID", "-p", "Result", "-p", "ExecMainStatus", "--no-pager"])
    data = {"ok": r["ok"], "code": r["code"]}
    for line in r["out"].splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            data[key] = value
    return data

def hermes_status_summary():
    r = run(["hermes", "status"])
    text = r["out"] or ""
    data = {
        "ok": r["ok"],
        "code": r["code"],
        "gateway_running": False,
        "gateway_manager": "",
        "gateway_pids": "",
        "weixin_configured": False,
        "telegram_configured": False,
        "model": "",
        "provider": "",
    }
    if not r["ok"]:
        return data
    section = ""
    for line in text.splitlines():
        stripped = line.strip()
        lower = stripped.lower()
        if stripped.startswith("◆"):
            section = stripped.lstrip("◆ ").strip().lower()
            continue
        if section == "gateway service" and lower.startswith("status:"):
            value = stripped.split(":", 1)[1].strip().lower()
            data["gateway_running"] = "running" in value or "active" in value
        elif section == "gateway service" and lower.startswith("manager:"):
            data["gateway_manager"] = stripped.split(":", 1)[1].strip()
        elif section == "gateway service" and lower.startswith("pid(s):"):
            data["gateway_pids"] = stripped.split(":", 1)[1].strip()
        elif section == "messaging platforms" and lower.startswith("weixin"):
            value = stripped.lower()
            data["weixin_configured"] = "configured" in value and "not configured" not in value
        elif section == "messaging platforms" and lower.startswith("telegram"):
            value = stripped.lower()
            data["telegram_configured"] = "configured" in value and "not configured" not in value
        elif lower.startswith("model:"):
            data["model"] = stripped.split(":", 1)[1].strip()
        elif lower.startswith("provider:"):
            data["provider"] = stripped.split(":", 1)[1].strip()
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
    env["HERMES_HOME"] = _hermes_home
    env["PYTHONPATH"] = _hermes_home + "/memory-os/runtime/python:" + _hermes_home + "/plugins:" + env.get("PYTHONPATH", "")
    return load_json_cmd(["python3", "-m", "plugins.memory.memory_os"] + list(args), env=env)

def seam_host_probe():
    try:
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.seam.hermes_memory_os.host_capability_adapter import probe_host_capabilities as _seam_probe
        _roots = MemoryOSRoots.from_hermes_home(_hermes_home, profile="default")
        return _seam_probe(_roots)
    except ImportError:
        return memory_os_cli(["host-probe", "--json"])

def v2_exposure_and_clearance_probe():
    # Fix 1: remote collection of V2 exposure telemetry and clearance
    # snapshot freshness, mirroring collect_snapshot()'s local-run branch.
    # Any failure here (missing runtime package, corrupt local state, etc.)
    # must not crash the rest of this probe script — report it explicitly
    # so the caller can turn it into a WARN instead of a silent pass.
    try:
        from plugins.memory.memory_os.clearance_receipts import clearance_snapshot_freshness
        from plugins.memory.memory_os.exposure_rollup import exposure_monitor_stats
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore
        _roots = MemoryOSRoots.from_hermes_home(_hermes_home, profile="default")
        _store = MemoryOSStore(_roots)
        _v2_exposure = exposure_monitor_stats(_store)
        _clearance = clearance_snapshot_freshness(
            _roots, for_activation=_v2_exposure.get("v2c_unfreeze_ready") is True
        )
        return {"ok": True, "v2_exposure_monitor": _v2_exposure, "clearance_snapshot_freshness": _clearance}
    except Exception as exc:
        return {"ok": False, "error_code": type(exc).__name__, "error_detail": str(exc)[:200]}

def living_memory_promotion_probe():
    # BB.6-1: remote collection of permanent-promotion ledger state counts,
    # mirroring collect_snapshot()'s local-run branch. Without this,
    # decision_recovery_failure_count / stale_open_proposal_count stay
    # hardcoded at 0 on every remote run, so those FAIL checks in
    # classify_snapshot never fire in production. Any failure here must not
    # crash the rest of this probe script -- report it explicitly.
    try:
        from plugins.memory.memory_os.permanent_promotion import read_permanent_promotion_ledger_counts
        counts = read_permanent_promotion_ledger_counts(Path(_hermes_home) / "memory-os")
        return {"ok": True, "counts": counts}
    except Exception as exc:
        return {"ok": False, "error_code": type(exc).__name__, "error_detail": str(exc)[:200]}

def compaction_stats():
    r = run(["journalctl", "--user", "-u", "hermes-gateway.service", "--since", "6 hours ago", "--no-pager", "-o", "cat"])
    text = r["out"] if r["ok"] else ""
    starts = len(re.findall(r"context compression started|Compacting context|Preflight compression", text))
    focus_none = len(re.findall(r"focus=None", text))
    return {"recent_count": starts, "focus_none_count": focus_none}

def hook_marker_counts():
    r = run(["grep", "-R", '"action": "agent_os_shell_session_', os.path.join(_hermes_home, "memory-os/audit")])
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

def _read_json(path):
    p = Path(path)
    if not p.exists():
        return {}
    try:
        parsed = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"_parse_error": True}
    return parsed if isinstance(parsed, dict) else {}

def session_activity_stats(recent_window=250):
    root = Path(_hermes_home) / "memory-os" / "events"
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

def audit_action_stats(recent_window=250, hermes_home=None):
    from plugins.memory.memory_os.audit import read_audit_records
    if hermes_home is None:
        hermes_home = _hermes_home
    audit_path = Path(hermes_home) / "memory-os" / "audit" / "write_audit.jsonl"
    records = read_audit_records(audit_path)
    action_counts = Counter()
    recent_action_counts = Counter()
    owner_review_reply_input_modes = Counter()
    recent_owner_review_reply_input_modes = Counter()
    gateway_safety_skip_count = 0
    recent_gateway_safety_skip_count = 0
    for index, record in enumerate(records):
        action = str(record.get("action") or "unknown")
        action_counts[action] += 1
        is_recent = index >= max(0, len(records) - int(recent_window))
        details = record.get("details") if isinstance(record.get("details"), dict) else {}
        if action == "owner_review_reply_ingress":
            mode = str(details.get("input_mode") or "unknown")
            owner_review_reply_input_modes[mode] += 1
            if is_recent:
                recent_owner_review_reply_input_modes[mode] += 1
        if action == "owner_review_reply_sync_turn_skipped":
            gateway_safety_skip_count += 1
            if is_recent:
                recent_gateway_safety_skip_count += 1
        if is_recent:
            recent_action_counts[action] += 1
    return {
        "total_count": len(records),
        "recent_window": int(recent_window),
        "action_counts": dict(action_counts),
        "recent_action_counts": dict(recent_action_counts),
        "owner_review_reply_input_modes": dict(owner_review_reply_input_modes),
        "recent_owner_review_reply_input_modes": dict(recent_owner_review_reply_input_modes),
        "reply_fallback_used_count": int(owner_review_reply_input_modes.get("reply_fallback") or 0),
        "structured_review_reply_count": int(owner_review_reply_input_modes.get("structured") or 0),
        "recent_reply_fallback_used_count": int(recent_owner_review_reply_input_modes.get("reply_fallback") or 0),
        "recent_structured_review_reply_count": int(recent_owner_review_reply_input_modes.get("structured") or 0),
        "gateway_safety_skip_count": gateway_safety_skip_count,
        "recent_gateway_safety_skip_count": recent_gateway_safety_skip_count,
    }

def heartbeat_state(max_age_seconds=900):
    path = Path(_hermes_home) / "memory-os" / "runtime" / "heartbeat_state.json"
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
    last_error_record = state.get("last_error_record") if isinstance(state.get("last_error_record"), dict) else {}
    bounded_error_record = {
        key: last_error_record.get(key)
        for key in (
            "schema_version",
            "component",
            "operation",
            "error_code",
            "severity",
            "recoverable",
            "ts",
        )
        if key in last_error_record
    }
    return {
        "exists": True,
        "fresh": fresh,
        "age_seconds": age_seconds,
        "max_age_seconds": int(max_age_seconds),
        "last_heartbeat_at": raw_last,
        "last_attempt_at": str(state.get("last_attempt_at") or ""),
        "processed_event_count": int(state.get("processed_event_count") or processed_count),
        "last_processed_event_id": str(state.get("last_processed_event_id") or last_processed),
        "suppressed_error_count": int(state.get("suppressed_error_count") or 0),
        "recent_error_codes": [
            str(code)
            for code in (
                state.get("recent_error_codes")
                if isinstance(state.get("recent_error_codes"), list)
                else []
            )
            if str(code)
        ][-5:],
        "last_error_record": bounded_error_record,
    }

def working_status():
    root = Path(_hermes_home) / "memory-os" / "working"
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
    records = _read_jsonl(os.path.join(_hermes_home, "memory-os/system/memory_sources.jsonl"))
    feedback_records = _read_jsonl(os.path.join(_hermes_home, "memory-os/system/memory_sources_feedback.jsonl"))
    selected_headings = Counter()
    dropped_headings = Counter()
    selected_source_classes = Counter()
    total_feedback_ratings = Counter()
    for record in records:
        for section in record.get("selected", []) if isinstance(record.get("selected"), list) else []:
            if isinstance(section, dict):
                selected_headings[str(section.get("heading") or "unknown")] += 1
                selected_source_classes[str(section.get("source_class") or "unknown")] += 1
        for section in record.get("dropped", []) if isinstance(record.get("dropped"), list) else []:
            if isinstance(section, dict):
                dropped_headings[str(section.get("heading") or "unknown")] += 1
    valid_feedback_records = []
    for record in feedback_records:
        if str(record.get("schema_version") or "") == "memory-os.memory_sources_feedback.v0":
            valid_feedback_records.append(record)
            total_feedback_ratings[str(record.get("rating") or "unknown")] += 1
    enriched = dict(stats)
    enriched["total_record_count"] = len(records)
    enriched["total_feedback_count"] = len(valid_feedback_records)
    enriched["total_feedback_rating_distribution"] = dict(total_feedback_ratings)
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
from plugins.memory.memory_os.audit import read_audit_records
home=""" + json.dumps(_hermes_home) + r"""
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
    env["PYTHONPATH"] = _hermes_home + "/memory-os/runtime/python"
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
home=""" + json.dumps(_hermes_home) + r"""
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
    env["PYTHONPATH"] = _hermes_home + "/memory-os/runtime/python"
    r = run(["python3", "-c", code], env=env)
    return json.loads(r["out"]) if r["ok"] else {"_error": r["out"], "_code": r["code"]}

def deep_reflection_status():
    code = r"""
import json
from plugins.modules.cognition.deep_reflection import DeepReflectionModule
status = DeepReflectionModule(""" + json.dumps(_hermes_home) + r""", profile="default").status()
keys = [
  "enabled","injection_mode","working_updates_enabled","llm_enabled",
  "self_evolution_proposals_enabled","wandering_seed_enabled",
  "current_injection_exists","latest_injection_source_classes",
  "rolling_injection_source_classes","actual_send","actual_execute",
  "actual_identity_write","actual_crystallized_approval",
  "latest_active_working_input_count","latest_expired_working_skipped_count",
  "latest_expired_working_used_in_analysis_count",
  "latest_cadence_skipped","latest_skip_reason","cadence_skipped_count"
]
summary = {k:status.get(k) for k in keys if k in status}
from pathlib import Path
def read_json(path):
    p = Path(path)
    if not p.exists():
        return {}
    try:
        value = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}
def read_jsonl(path):
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except Exception:
            continue
        if isinstance(value, dict):
            out.append(value)
    return out
policy = read_json(os.path.join(""" + json.dumps(_hermes_home) + r""", "system-modules/deep_reflection/policy.json"))
policy_applies = read_jsonl(os.path.join(""" + json.dumps(_hermes_home) + r""", "system-modules/deep_reflection/policy_applies.jsonl"))
summary.update({
  "policy_present": bool(policy),
  "policy_version": int(policy.get("policy_version") or 0) if policy else 0,
  "policy_live_applied": bool(policy.get("live_applied")) if policy else False,
  "policy_apply_count": len(policy_applies),
  "policy_actual_execute_count": sum(1 for item in policy_applies if item.get("actual_execute") is True),
  "policy_raw_body_included_count": sum(1 for item in policy_applies if item.get("raw_body_included") is True),
})
print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = _hermes_home + "/memory-os/runtime/python"
    r = run(["python3", "-c", code], env=env)
    return json.loads(r["out"]) if r["ok"] else {"_error": r["out"], "_code": r["code"]}

def low_clue_recall_probe():
    cfg_path = Path(_hermes_home) / "memory-os" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
    low_clue_cfg = cfg.get("low_clue_recall") if isinstance(cfg.get("low_clue_recall"), dict) else {}
    judge = low_clue_cfg.get("llm_judge") if isinstance(low_clue_cfg.get("llm_judge"), dict) else {}
    judge_mode = "config" if judge.get("enabled") and judge.get("mode") in {"report_only", "bounded_vote"} else "none"
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

def module_artifact_summary(*, include_retired_legacy=None):
    if include_retired_legacy is None:
        include_retired_legacy = legacy_right_brain_archive_summary().get("lifecycle") not in {
            "retirement_pending",
            "retired",
        }
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
    wandering = status("wandering_mind") if include_retired_legacy else {}
    evidence = status("evidence_scoring")
    imagination_loop = status("imagination_loop")
    confabulation_detector = status("confabulation_detector")
    proposal = status("proposal_queue")
    self_evolution = status("self_evolution")
    governance = status("governance_feedback")
    left_brain_pipeline = status("left_brain_pipeline_check")
    ground_truth_miner = status("ground_truth_miner")
    confidence_router = status("confidence_router")
    judge_calibration = status("judge_calibration")
    candidate_review = status("candidate_review")
    shadow_recall = status("shadow_recall")
    provisional = status("provisional")
    cascade_routing_policy = status("cascade_routing_policy")
    migration_controller = status("migration_controller")
    symbolic_offloader = status("symbolic_offloader")
    abstraction_distillation = status("abstraction_distillation")
    crystallized_revalidator = status("crystallized_revalidator")
    deep_reflection = status("deep_reflection")
    ops_gate = status("ops_gate")
    speak_gate = status("speak_gate") if include_retired_legacy else {}
    expression_draft = status("expression_draft") if include_retired_legacy else {}
    grounded_expression_judge = status("grounded_expression_judge") if include_retired_legacy else {}
    mailbox = status("mailbox")

    def prefetch_observability_summary():
        try:
            from plugins.memory.memory_os.index import MemoryOSIndex
            from plugins.memory.memory_os.prefetch import build_prefetch_with_observability
            from plugins.memory.memory_os.roots import MemoryOSRoots
            from plugins.memory.memory_os.store import MemoryOSStore

            roots = MemoryOSRoots.from_hermes_home(_hermes_home, profile="default")
            store = MemoryOSStore(roots)
            return build_prefetch_with_observability(
                "memory-os monitor prefetch observability",
                budget_chars=0,
                store=store,
                index=MemoryOSIndex(roots),
            )
        except Exception as exc:
            return {
                "schema_version": "memory-os.prefetch_observability.v0",
                "status": "error",
                "context": "",
                "suppressed_error_count": 0,
                "recent_error_codes": [],
                "monitor_probe_error_count": 1,
                "monitor_probe_error_codes": ["prefetch_observability_probe_error"],
                "error_records": [
                    {
                        "schema_version": "memory-os.error_record.v0",
                        "component": "prefetch",
                        "operation": "monitor_observability_probe",
                        "error_code": "prefetch_observability_probe_error",
                        "severity": "warning",
                        "recoverable": True,
                        "message": str(exc)[:160],
                    }
                ],
            }

    prefetch_observability = prefetch_observability_summary()
    expression_feedback = _read_jsonl(os.path.join(_hermes_home, "memory-os/system/expression_feedback_ledger.jsonl"))
    speak_permission_tickets = (
        _read_jsonl(os.path.join(_hermes_home, "memory-os/system/speak_permission_tickets.jsonl"))
        if include_retired_legacy
        else []
    )
    right_brain_expression_requests = (
        _read_jsonl(os.path.join(_hermes_home, "system-modules/right_brain_expression_adapter/requests.jsonl"))
        if include_retired_legacy
        else []
    )
    right_brain_expression_policy = (
        _read_json(os.path.join(_hermes_home, "system-modules/right_brain_expression_adapter/policy.json"))
        if include_retired_legacy
        else {}
    )
    right_brain_expression_policy_applies = (
        _read_jsonl(os.path.join(_hermes_home, "system-modules/right_brain_expression_adapter/policy_applies.jsonl"))
        if include_retired_legacy
        else []
    )
    repo_roots = (
        os.path.join(_hermes_home, "plugins/memory_os"),
        os.path.join(_hermes_home, "memory-os/runtime/python"),
    )
    def repo_file_exists(*parts):
        return any(os.path.exists(os.path.join(root, *parts)) for root in repo_roots)

    def promotion_matrix_component():
        try:
            from plugins.memory.memory_os.v7_promotion import promotion_matrix_component as _component
            component = _component()
            if isinstance(component, dict) and component.get("component") == "promotion_matrix":
                return component
        except Exception:
            pass
        return {}

    proposal_queue_legacy_template_cleanup_applies = _read_jsonl(
        os.path.join(_hermes_home, "system-modules/proposal_queue/legacy_template_cleanup_applies.jsonl")
    )
    right_brain_expression_outcomes = (
        _read_jsonl(os.path.join(_hermes_home, "system-modules/right_brain_expression_adapter/outcomes.jsonl"))
        if include_retired_legacy
        else []
    )
    latest_right_brain_expression_request = (
        right_brain_expression_requests[-1]
        if right_brain_expression_requests and isinstance(right_brain_expression_requests[-1], dict)
        else {}
    )
    latest_right_brain_expression_outcome = (
        right_brain_expression_outcomes[-1]
        if right_brain_expression_outcomes and isinstance(right_brain_expression_outcomes[-1], dict)
        else {}
    )
    latest_speak_permission_ticket = (
        speak_permission_tickets[-1]
        if speak_permission_tickets and isinstance(speak_permission_tickets[-1], dict)
        else {}
    )
    right_brain_outcome_ids = {
        str(item.get("outcome_id") or "")
        for item in right_brain_expression_outcomes
        if isinstance(item, dict) and str(item.get("outcome_id") or "")
    }
    latest_right_brain_outcome_id = str(latest_right_brain_expression_outcome.get("outcome_id") or "")
    expression_feedback_linked = [
        item
        for item in expression_feedback
        if isinstance(item, dict) and str(item.get("outcome_id") or "")
    ]
    expression_feedback_linked_missing = [
        item
        for item in expression_feedback_linked
        if str(item.get("outcome_id") or "") not in right_brain_outcome_ids
    ]
    right_brain_outcome_feedback_count = sum(
        1
        for item in expression_feedback_linked
        if str(item.get("outcome_id") or "") in right_brain_outcome_ids
    )
    latest_right_brain_outcome_feedback_count = sum(
        1
        for item in expression_feedback_linked
        if latest_right_brain_outcome_id and str(item.get("outcome_id") or "") == latest_right_brain_outcome_id
    )
    ops_gate_reports = _read_jsonl(os.path.join(_hermes_home, "system-modules/ops_gate/reports.jsonl"))
    proposal_followup_action_counts = {}
    for report_item in ops_gate_reports:
        if not isinstance(report_item, dict):
            continue
        decisions = report_item.get("decisions")
        if not isinstance(decisions, list):
            continue
        for decision in decisions:
            if not isinstance(decision, dict):
                continue
            action_id = str(decision.get("action_id") or "")
            if not action_id.startswith("proposal_followup:"):
                continue
            proposal_followup_action_counts[action_id] = proposal_followup_action_counts.get(action_id, 0) + 1
    duplicate_proposal_followup_count = sum(1 for count in proposal_followup_action_counts.values() if count > 1)
    duplicate_proposal_followup_extra_count = sum(
        max(count - 1, 0) for count in proposal_followup_action_counts.values()
    )
    summary = {
      "schema_version": "memory-os.module_artifact_summary.v0",
      "status": "ok",
      "module_count": report.get("module_count"),
      "digest": {
        "daily_artifact_count": digest.get("daily_artifact_count"),
        "weekly_artifact_count": digest.get("weekly_artifact_count"),
        "household_artifact_exists": household.get("artifact_exists"),
      },
      "wandering": {
        "output_count": len(_read_jsonl(os.path.join(_hermes_home, "system-modules/wandering_mind/outputs.jsonl"))),
        "would_send_count": wandering.get("would_send_count"),
      },
      "evidence": {
        "evidence_count": evidence.get("evidence_count"),
        "score_count": evidence.get("score_count"),
        "derived_evidence_profile_count": evidence.get("derived_evidence_profile_count"),
        "score_mode": evidence.get("score_mode"),
        "feature_score_mode": evidence.get("feature_score_mode"),
        "feature_score_count": evidence.get("feature_score_count"),
        "hash_score_legacy_count": evidence.get("hash_score_legacy_count"),
        "legacy_hash_comparison_count": evidence.get("legacy_hash_comparison_count"),
        "comparison_count": evidence.get("comparison_count"),
        "feature_score_report_count": evidence.get("feature_score_report_count"),
        "feature_score_live_applied": evidence.get("feature_score_live_applied"),
        "prototype_aligned_score_count": evidence.get("prototype_aligned_score_count"),
        "maturity_dimension_count": evidence.get("maturity_dimension_count"),
        "maturity_dimension_keys": evidence.get("maturity_dimension_keys"),
        "maturity_live_applied": evidence.get("maturity_live_applied"),
            "owner_feedback_signal_count": evidence.get("owner_feedback_signal_count"),
            "expression_feedback_subject_count": evidence.get("expression_feedback_subject_count"),
            "expression_feedback_linked_subject_count": evidence.get("expression_feedback_linked_subject_count"),
            "expression_feedback_unlinked_subject_count": evidence.get("expression_feedback_unlinked_subject_count"),
            "subject_counts": evidence.get("subject_counts"),
            "working_subject_count": evidence.get("working_subject_count"),
            "expired_used_in_scoring_count": evidence.get("expired_used_in_scoring_count"),
        "run_report_count": evidence.get("run_report_count"),
        "skipped_run_count": evidence.get("skipped_run_count"),
        "latest_cadence_skipped": evidence.get("latest_cadence_skipped"),
        "latest_skip_reason": evidence.get("latest_skip_reason"),
      },
      "v7_meta": {
        "promotion_matrix_component": promotion_matrix_component(),
        "live_guard_registry_present": repo_file_exists("plugins", "modules", "governance", "live_guard.py"),
        "eval_adapter_registry_present": repo_file_exists("eval", "memory_os", "runner", "registry.py"),
      },
      "imagination_loop": {
        "status": imagination_loop.get("status"),
        "scenario_count": imagination_loop.get("scenario_count"),
        "simulated_count": imagination_loop.get("simulated_count"),
        "suppressed_error_count": imagination_loop.get("suppressed_error_count"),
        "recent_error_codes": imagination_loop.get("recent_error_codes"),
        "actual_send": imagination_loop.get("actual_send"),
        "actual_execute": imagination_loop.get("actual_execute"),
        "actual_identity_write": imagination_loop.get("actual_identity_write"),
        "live_behavior_changed": imagination_loop.get("live_behavior_changed"),
      },
      "confabulation_detector": {
        "status": confabulation_detector.get("status"),
        "flag_count": confabulation_detector.get("flag_count"),
        "run_count": confabulation_detector.get("run_count"),
        "actual_send": confabulation_detector.get("actual_send"),
        "actual_execute": confabulation_detector.get("actual_execute"),
        "actual_identity_write": confabulation_detector.get("actual_identity_write"),
        "score_live_applied": confabulation_detector.get("score_live_applied"),
        "route_live_applied": confabulation_detector.get("route_live_applied"),
      },
      "proposal_queue": {
        "candidate_count": proposal.get("candidate_count"),
        "state_counts": proposal.get("state_counts"),
        "legacy_template_cleanup_apply_count": len(proposal_queue_legacy_template_cleanup_applies),
        "legacy_template_cleanup_closed_count": sum(
            int(item.get("closed_count") or 0)
            for item in proposal_queue_legacy_template_cleanup_applies
            if isinstance(item, dict)
        ),
        "legacy_template_cleanup_non_legacy_touched_count": sum(
            int(item.get("non_legacy_touched_count") or 0)
            for item in proposal_queue_legacy_template_cleanup_applies
            if isinstance(item, dict)
        ),
        "legacy_template_cleanup_actual_execute_count": sum(
            1
            for item in proposal_queue_legacy_template_cleanup_applies
            if isinstance(item, dict) and item.get("actual_execute") is True
        ),
        "legacy_template_cleanup_raw_body_included_count": sum(
            1
            for item in proposal_queue_legacy_template_cleanup_applies
            if isinstance(item, dict) and item.get("raw_body_included") is True
        ),
      },
      "self_evolution": {
        "report_count": self_evolution.get("report_count"),
            "agenda_candidate_count": self_evolution.get("agenda_candidate_count"),
            "agenda_candidate_promoted_count": self_evolution.get("agenda_candidate_promoted_count"),
            "agenda_candidate_blocked_count": self_evolution.get("agenda_candidate_blocked_count"),
            "agenda_candidate_ready_count": self_evolution.get("agenda_candidate_ready_count"),
            "latest_agenda_candidate_status": self_evolution.get("latest_agenda_candidate_status"),
            "proposal_count": self_evolution.get("proposal_count"),
            "novelty_skipped_count": self_evolution.get("novelty_skipped_count"),
            "proposal_quality_gate_failed_count": self_evolution.get("proposal_quality_gate_failed_count"),
            "duplicate_unresolved_proposal_count": self_evolution.get("duplicate_unresolved_proposal_count"),
            "cadence_skipped_count": self_evolution.get("cadence_skipped_count"),
            "same_signal_skipped_count": self_evolution.get("same_signal_skipped_count"),
            "last_quality_gate_reason": self_evolution.get("last_quality_gate_reason"),
            "last_status": self_evolution.get("last_status"),
          },
      "governance_feedback": {
        "emitted_event_count": governance.get("emitted_event_count"),
      },
        "left_brain_pipeline_check": {
        "status": left_brain_pipeline.get("status"),
        "finding_count": left_brain_pipeline.get("finding_count"),
        "active_duplicate_group_count": left_brain_pipeline.get("active_duplicate_group_count"),
        "followup_duplicate_group_count": left_brain_pipeline.get("followup_duplicate_group_count"),
        "legacy_template_duplicate_group_count": left_brain_pipeline.get("legacy_template_duplicate_group_count"),
        "proposal_quality_missing_count": left_brain_pipeline.get("proposal_quality_missing_count"),
        "expression_policy_quality_ready_count": left_brain_pipeline.get("expression_policy_quality_ready_count"),
        "expression_policy_quality_blocked_count": left_brain_pipeline.get("expression_policy_quality_blocked_count"),
        "expression_policy_unlinked_quality_count": left_brain_pipeline.get("expression_policy_unlinked_quality_count"),
        "memory_sources_policy_quality_ready_count": left_brain_pipeline.get(
            "memory_sources_policy_quality_ready_count"
        ),
        "memory_sources_policy_quality_blocked_count": left_brain_pipeline.get(
            "memory_sources_policy_quality_blocked_count"
        ),
        "memory_sources_policy_unlinked_quality_count": left_brain_pipeline.get(
            "memory_sources_policy_unlinked_quality_count"
        ),
        "agenda_trace_missing_count": left_brain_pipeline.get("agenda_trace_missing_count"),
        "actual_execute": left_brain_pipeline.get("actual_execute"),
      },
      "ground_truth_miner": {
        "status": ground_truth_miner.get("status"),
        "label_count": ground_truth_miner.get("label_count"),
        "run_count": ground_truth_miner.get("run_count"),
        "active_label_count": ground_truth_miner.get("active_label_count"),
        "retracted_label_count": ground_truth_miner.get("retracted_label_count"),
        "actual_send": ground_truth_miner.get("actual_send"),
        "actual_execute": ground_truth_miner.get("actual_execute"),
        "actual_identity_write": ground_truth_miner.get("actual_identity_write"),
        "score_live_applied": ground_truth_miner.get("score_live_applied"),
        "route_live_applied": ground_truth_miner.get("route_live_applied"),
      },
      "confidence_router": {
        "status": confidence_router.get("status"),
        "route_count": confidence_router.get("route_count"),
        "run_count": confidence_router.get("run_count"),
        "band_distribution": confidence_router.get("band_distribution"),
        "actual_send": confidence_router.get("actual_send"),
        "actual_execute": confidence_router.get("actual_execute"),
        "actual_identity_write": confidence_router.get("actual_identity_write"),
        "score_live_applied": confidence_router.get("score_live_applied"),
        "route_live_applied": confidence_router.get("route_live_applied"),
      },
      "judge_calibration": {
        "status": judge_calibration.get("status"),
        "run_count": judge_calibration.get("run_count"),
        "calibration_live_applied": judge_calibration.get("calibration_live_applied"),
        "actual_send": judge_calibration.get("actual_send"),
        "actual_execute": judge_calibration.get("actual_execute"),
      },
      "candidate_review": {
        "status": candidate_review.get("status"),
        "decision_count": candidate_review.get("decision_count"),
        "run_count": candidate_review.get("run_count"),
        "candidate_review_live_applied": candidate_review.get("candidate_review_live_applied"),
        "actual_send": candidate_review.get("actual_send"),
        "actual_execute": candidate_review.get("actual_execute"),
      },
      "shadow_recall": {
        "status": shadow_recall.get("status"),
        "fingerprint_count": shadow_recall.get("fingerprint_count"),
        "run_count": shadow_recall.get("run_count"),
        "auto_discard_live_applied": shadow_recall.get("auto_discard_live_applied"),
        "actual_send": shadow_recall.get("actual_send"),
        "actual_execute": shadow_recall.get("actual_execute"),
      },
      "provisional": {
        "status": provisional.get("status"),
        "record_count": provisional.get("record_count"),
        "run_count": provisional.get("run_count"),
        "auto_promote_live_applied": provisional.get("auto_promote_live_applied"),
        "actual_send": provisional.get("actual_send"),
        "actual_execute": provisional.get("actual_execute"),
        "actual_crystallized_approval": provisional.get("actual_crystallized_approval"),
      },
      "cascade_routing_policy": {
        "status": cascade_routing_policy.get("status"),
        "proposal_count": cascade_routing_policy.get("proposal_count"),
        "route_strategy_live_applied": cascade_routing_policy.get("route_strategy_live_applied"),
        "actual_send": cascade_routing_policy.get("actual_send"),
        "actual_execute": cascade_routing_policy.get("actual_execute"),
      },
      "migration_controller": {
        "status": migration_controller.get("status"),
        "run_count": migration_controller.get("run_count"),
        "last_regime": migration_controller.get("last_regime"),
        "last_owner_label_count": migration_controller.get("last_owner_label_count"),
        "last_owner_feedback_count": migration_controller.get("last_owner_feedback_count"),
        "last_owner_signal_count": migration_controller.get("last_owner_signal_count"),
        "label_floor": migration_controller.get("label_floor"),
        "automation_allowed": migration_controller.get("automation_allowed"),
        "migration_live_applied": migration_controller.get("migration_live_applied"),
        "actual_send": migration_controller.get("actual_send"),
        "actual_execute": migration_controller.get("actual_execute"),
      },
      "symbolic_offloader": {
        "status": symbolic_offloader.get("status"),
        "report_count": symbolic_offloader.get("report_count"),
        "ref_count": symbolic_offloader.get("ref_count"),
        "suppressed_error_count": symbolic_offloader.get("suppressed_error_count"),
        "recent_error_codes": symbolic_offloader.get("recent_error_codes"),
        "canonical_state_changed": symbolic_offloader.get("canonical_state_changed"),
        "actual_send": symbolic_offloader.get("actual_send"),
        "actual_execute": symbolic_offloader.get("actual_execute"),
      },
      "abstraction_distillation": {
        "status": abstraction_distillation.get("status"),
        "item_count": abstraction_distillation.get("item_count"),
        "distillation_live_applied": abstraction_distillation.get("distillation_live_applied"),
        "actual_send": abstraction_distillation.get("actual_send"),
        "actual_execute": abstraction_distillation.get("actual_execute"),
      },
      "crystallized_revalidator": {
        "status": crystallized_revalidator.get("status"),
        "flag_count": crystallized_revalidator.get("flag_count"),
        "run_count": crystallized_revalidator.get("run_count"),
        "would_demote_count": crystallized_revalidator.get("would_demote_count"),
        "actual_send": crystallized_revalidator.get("actual_send"),
        "actual_execute": crystallized_revalidator.get("actual_execute"),
        "actual_identity_write": crystallized_revalidator.get("actual_identity_write"),
        "actual_crystallized_approval": crystallized_revalidator.get("actual_crystallized_approval"),
        "demotion_live_applied": crystallized_revalidator.get("demotion_live_applied"),
      },
      "deep_reflection": {
        "report_count": deep_reflection.get("report_count"),
        "analysis_artifact_count": deep_reflection.get("analysis_artifact_count"),
        "current_injection_exists": deep_reflection.get("current_injection_exists"),
        "latest_active_working_input_count": deep_reflection.get("latest_active_working_input_count"),
        "latest_expired_working_skipped_count": deep_reflection.get("latest_expired_working_skipped_count"),
        "latest_expired_working_used_in_analysis_count": deep_reflection.get(
            "latest_expired_working_used_in_analysis_count"
        ),
        "latest_cadence_skipped": deep_reflection.get("latest_cadence_skipped"),
        "latest_skip_reason": deep_reflection.get("latest_skip_reason"),
        "cadence_skipped_count": deep_reflection.get("cadence_skipped_count"),
        "wandering_seed_count": len(_read_jsonl(os.path.join(_hermes_home, "system-modules/deep_reflection/wandering_seeds.jsonl"))),
      },
      "ops_gate": {
        "report_count": ops_gate.get("report_count"),
        "run_report_count": ops_gate.get("run_report_count"),
        "skipped_run_count": ops_gate.get("skipped_run_count"),
        "latest_cadence_skipped": ops_gate.get("latest_cadence_skipped"),
        "latest_skip_reason": ops_gate.get("latest_skip_reason"),
        "blocked_decision_count": ops_gate.get("blocked_decision_count"),
        "proposal_followup_action_count": len(proposal_followup_action_counts),
        "duplicate_proposal_followup_count": duplicate_proposal_followup_count,
        "duplicate_proposal_followup_extra_count": duplicate_proposal_followup_extra_count,
      },
      "speak_gate": {
        "would_send_count": speak_gate.get("would_send_count"),
        "actual_send": speak_gate.get("actual_send"),
      },
      "expression_draft": {
        "draft_count": expression_draft.get("draft_count"),
        "silent_count": expression_draft.get("silent_count"),
        "draft_error_count": expression_draft.get("draft_error_count"),
        "raw_body_included": expression_draft.get("body_included"),
      },
      "grounded_expression_judge": {
        "status": grounded_expression_judge.get("status"),
        "hindsight_adapter_enabled": grounded_expression_judge.get("hindsight_adapter_enabled"),
        "alternate_left_map_substrate_configured": grounded_expression_judge.get("alternate_left_map_substrate_configured"),
        "verdict_count": grounded_expression_judge.get("verdict_count"),
        "verdict_distribution": grounded_expression_judge.get("verdict_distribution"),
        "grounded_count": grounded_expression_judge.get("grounded_count"),
        "confabulation_count": grounded_expression_judge.get("confabulation_count"),
        "blind_spot_count": grounded_expression_judge.get("blind_spot_count"),
        "unresolvable_count": grounded_expression_judge.get("unresolvable_count"),
        "left_map_substrate_warning_count": grounded_expression_judge.get("left_map_substrate_warning_count"),
        "left_map_coverage_floor_met_count": grounded_expression_judge.get("left_map_coverage_floor_met_count"),
        "latest_left_map_snapshot_version": grounded_expression_judge.get("latest_left_map_snapshot_version"),
        "verdict_distribution_degenerate": grounded_expression_judge.get("verdict_distribution_degenerate"),
        "substrate_unavailable_blocker_cleared": grounded_expression_judge.get("substrate_unavailable_blocker_cleared"),
        "actual_send": grounded_expression_judge.get("actual_send"),
        "actual_execute": grounded_expression_judge.get("actual_execute"),
        "actual_identity_write": grounded_expression_judge.get("actual_identity_write"),
        "delivery_affected": grounded_expression_judge.get("delivery_affected"),
        "delivery_gated": grounded_expression_judge.get("delivery_gated"),
        "policy_live_applied": grounded_expression_judge.get("policy_live_applied"),
      },
      "expression_feedback": {
        "feedback_count": len(expression_feedback),
        "live_policy_changed_count": sum(1 for item in expression_feedback if isinstance(item, dict) and item.get("live_policy_changed") is True),
        "raw_body_included_count": sum(1 for item in expression_feedback if isinstance(item, dict) and item.get("raw_body_included") is True),
        "linked_outcome_count": len(expression_feedback_linked),
        "unlinked_count": sum(1 for item in expression_feedback if isinstance(item, dict) and not str(item.get("outcome_id") or "")),
        "linked_outcome_missing_count": len(expression_feedback_linked_missing),
        "latest_linked_outcome_id": (
            expression_feedback_linked[-1].get("outcome_id")
            if expression_feedback_linked and isinstance(expression_feedback_linked[-1], dict)
            else ""
        ),
      },
      "right_brain_expression_adapter": {
        "request_count": len(right_brain_expression_requests),
        "policy_present": bool(right_brain_expression_policy),
        "policy_version": right_brain_expression_policy.get("policy_version") if isinstance(right_brain_expression_policy, dict) else None,
        "policy_apply_count": len(right_brain_expression_policy_applies),
        "latest_policy_apply_id": (
            right_brain_expression_policy_applies[-1].get("apply_id")
            if right_brain_expression_policy_applies and isinstance(right_brain_expression_policy_applies[-1], dict)
            else ""
        ),
        "policy_actual_execute_count": sum(
            1
            for item in right_brain_expression_policy_applies
            if isinstance(item, dict) and item.get("actual_execute") is True
        ),
        "policy_raw_body_included_count": sum(
            1
            for item in right_brain_expression_policy_applies
            if isinstance(item, dict) and item.get("raw_body_included") is True
        ),
        "silent_request_count": sum(
            1
            for item in right_brain_expression_requests
            if isinstance(item, dict) and item.get("silent") is True
        ),
        "latest_channel": latest_right_brain_expression_request.get("channel"),
        "latest_delivery_mode": latest_right_brain_expression_request.get("delivery_mode"),
        "latest_actual_send": latest_right_brain_expression_request.get("actual_send"),
        "latest_raw_body_included": latest_right_brain_expression_request.get("raw_body_included"),
        "raw_body_included_count": sum(
            1
            for item in right_brain_expression_requests
            if isinstance(item, dict) and item.get("raw_body_included") is True
        ),
        "outcome_count": len(right_brain_expression_outcomes),
        "latest_outcome_id": latest_right_brain_expression_outcome.get("outcome_id"),
        "latest_outcome_request_id": latest_right_brain_expression_outcome.get("request_id"),
        "latest_outcome_policy_version": latest_right_brain_expression_outcome.get("policy_version"),
        "latest_outcome_silent": latest_right_brain_expression_outcome.get("silent"),
        "latest_outcome_preview_chars": latest_right_brain_expression_outcome.get("outcome_preview_chars"),
        "outcome_actual_send_count": sum(
            1
            for item in right_brain_expression_outcomes
            if isinstance(item, dict) and item.get("actual_send") is True
        ),
        "outcome_actual_execute_count": sum(
            1
            for item in right_brain_expression_outcomes
            if isinstance(item, dict) and item.get("actual_execute") is True
        ),
        "outcome_raw_body_included_count": sum(
            1
            for item in right_brain_expression_outcomes
            if isinstance(item, dict) and item.get("raw_body_included") is True
        ),
        "outcome_internal_marker_count": sum(
            int(item.get("internal_marker_count") or 0)
            for item in right_brain_expression_outcomes
            if isinstance(item, dict)
        ),
        "outcome_feedback_count": right_brain_outcome_feedback_count,
        "latest_outcome_feedback_count": latest_right_brain_outcome_feedback_count,
        "outcome_feedback_missing_count": len(expression_feedback_linked_missing),
      },
      "speak_permission": {
        "ticket_count": len(speak_permission_tickets),
        "sent_count": sum(
            1
            for item in speak_permission_tickets
            if isinstance(item, dict) and item.get("status") == "sent" and item.get("actual_send") is True
        ),
        "pending_count": sum(
            1
            for item in speak_permission_tickets
            if isinstance(item, dict) and item.get("status") == "pending"
        ),
        "error_count": sum(
            1
            for item in speak_permission_tickets
            if isinstance(item, dict) and item.get("status") == "error"
        ),
        "unapproved_send_count": sum(
            1
            for item in speak_permission_tickets
            if isinstance(item, dict) and item.get("actual_unapproved_send") is True
        ),
        "raw_body_included_count": sum(
            1
            for item in speak_permission_tickets
            if isinstance(item, dict) and item.get("raw_body_included") is True
        ),
        "latest_ticket_id": latest_speak_permission_ticket.get("ticket_id"),
        "latest_status": latest_speak_permission_ticket.get("status"),
        "latest_actual_send": latest_speak_permission_ticket.get("actual_send"),
        "latest_delivery_target_class": (
            latest_speak_permission_ticket.get("delivery_ref", {}).get("target_class")
            if isinstance(latest_speak_permission_ticket.get("delivery_ref"), dict)
            else None
        ),
      },
      "mailbox": {
        "mailbox_exists": mailbox.get("mailbox_exists"),
        "would_send_count": mailbox.get("would_send_count"),
      },
      "prefetch_observability": {
        "schema_version": prefetch_observability.get("schema_version") if isinstance(prefetch_observability, dict) else "",
        "status": prefetch_observability.get("status") if isinstance(prefetch_observability, dict) else None,
        "suppressed_error_count": prefetch_observability.get("suppressed_error_count") if isinstance(prefetch_observability, dict) else None,
        "recent_error_codes": prefetch_observability.get("recent_error_codes") if isinstance(prefetch_observability, dict) else [],
        "error_records": prefetch_observability.get("error_records") if isinstance(prefetch_observability, dict) else [],
        "raw_body_included": False,
      },
    }
    if not include_retired_legacy:
        for key in (
            "wandering",
            "grounded_expression_judge",
            "expression_draft",
            "speak_gate",
            "right_brain_expression_adapter",
            "speak_permission",
        ):
            summary.pop(key, None)
    return summary

def legacy_right_brain_archive_summary():
    from plugins.memory.memory_os.legacy_right_brain_retirement import retirement_status

    return retirement_status(_hermes_home)


def active_module_artifact_summary():
    summary = module_artifact_summary()
    if legacy_right_brain_archive_summary().get("lifecycle") not in {"retirement_pending", "retired"}:
        return summary
    for key in (
        "wandering",
        "grounded_expression_judge",
        "expression_draft",
        "speak_gate",
        "right_brain_expression_adapter",
        "speak_permission",
    ):
        summary.pop(key, None)
    deep_reflection = summary.get("deep_reflection")
    if isinstance(deep_reflection, dict):
        deep_reflection.pop("wandering_seed_count", None)
    return summary


def expression_artifact_summary():
    legacy_archive = legacy_right_brain_archive_summary()
    legacy_retired = legacy_archive.get("lifecycle") in {"retirement_pending", "retired"}
    if legacy_retired:
        return {
            "schema_version": "memory-os.expression_artifact_summary.v0",
            "status": "retired",
            "active_observation": False,
            "actual_send": False,
            "actual_execute": False,
            "raw_body_included": False,
        }
    modules = module_artifact_summary()
    wandering = (
        {}
        if legacy_retired
        else modules.get("wandering") if isinstance(modules.get("wandering"), dict) else {}
    )
    speak_gate = modules.get("speak_gate") if isinstance(modules.get("speak_gate"), dict) else {}
    expression_draft = modules.get("expression_draft") if isinstance(modules.get("expression_draft"), dict) else {}
    right_brain_adapter = (
        modules.get("right_brain_expression_adapter")
        if isinstance(modules.get("right_brain_expression_adapter"), dict)
        else {}
    )
    speak_permission = modules.get("speak_permission") if isinstance(modules.get("speak_permission"), dict) else {}
    reports = (
        []
        if legacy_retired
        else _read_jsonl(os.path.join(_hermes_home, "system-modules/cognitive_loop/reports.jsonl"))
    )
    wandering_result_count = 0
    wandering_would_send_result_count = 0
    wandering_silent_count = 0
    expression_draft_created_count = 0
    expression_draft_skipped_count = 0
    expression_draft_missing_count = 0
    speak_gate_evaluated_count = 0
    speak_gate_skipped_count = 0
    speak_gate_missing_evaluation_count = 0
    speak_gate_decision_distribution = {}
    latest_expression_draft_missing_count = 0
    latest_speak_gate_missing_evaluation_count = 0
    latest_speak_gate_evaluated_count = 0
    latest_wandering_result_count = 0
    for report in reports:
        report_expression_missing = 0
        report_speak_gate_missing = 0
        report_speak_gate_evaluated = 0
        report_wandering_result_count = 0
        steps = report.get("steps") if isinstance(report.get("steps"), list) else []
        for step in steps:
            if not isinstance(step, dict):
                continue
            step_name = str(step.get("step") or "")
            result = step.get("result") if isinstance(step.get("result"), dict) else {}

            # V1: wandering_mind handles expression_draft generation
            if step_name == "wandering_mind":
                wandering_result_count += 1
                report_wandering_result_count += 1
                if result.get("would_send") is True:
                    wandering_would_send_result_count += 1
                    if not isinstance(result.get("speak_gate_decision"), dict):
                        speak_gate_missing_evaluation_count += 1
                        report_speak_gate_missing += 1
                if result.get("output") == "[SILENT]" or (result.get("would_send") is False and result.get("reason")):
                    wandering_silent_count += 1
                if result.get("expression_draft_created") is True or isinstance(result.get("expression_draft"), dict):
                    expression_draft_created_count += 1
                elif result.get("expression_draft_skipped") is True:
                    expression_draft_skipped_count += 1
                elif result.get("output") not in {None, ""}:
                    expression_draft_missing_count += 1
                    report_expression_missing += 1

            # V1: spontaneous_expression handles speak_gate evaluation and delivery
            elif step_name == "spontaneous_expression":
                spontaneous_decision = result.get("spontaneous_decision")
                if spontaneous_decision is not None:
                    if spontaneous_decision == "delivered":
                        speak_gate_evaluated_count += 1
                        report_speak_gate_evaluated += 1
                        speak_gate_decision_distribution["delivered"] = speak_gate_decision_distribution.get("delivered", 0) + 1
                    elif spontaneous_decision in ("no_draft", "judge_blocked", "rate_limited", "send_blocked"):
                        speak_gate_skipped_count += 1
                        decision_name = str(spontaneous_decision)
                        speak_gate_decision_distribution[decision_name] = speak_gate_decision_distribution.get(decision_name, 0) + 1
                    else:
                        speak_gate_evaluated_count += 1
                        report_speak_gate_evaluated += 1
                        decision_name = str(spontaneous_decision)
                        speak_gate_decision_distribution[decision_name] = speak_gate_decision_distribution.get(decision_name, 0) + 1
        if report_wandering_result_count:
            latest_expression_draft_missing_count = report_expression_missing
            latest_speak_gate_missing_evaluation_count = report_speak_gate_missing
            latest_speak_gate_evaluated_count = report_speak_gate_evaluated
            latest_wandering_result_count = report_wandering_result_count
    return {
      "schema_version": "memory-os.expression_artifact_summary.v0",
      "wandering_output_count": wandering.get("output_count"),
      "wandering_would_send_count": wandering.get("would_send_count"),
      "wandering_result_count": wandering_result_count,
      "wandering_would_send_result_count": wandering_would_send_result_count,
      "wandering_silent_count": wandering_silent_count,
      "expression_draft_count": expression_draft.get("draft_count"),
      "expression_draft_created_count": expression_draft_created_count,
      "expression_draft_skipped_count": expression_draft_skipped_count,
      "expression_draft_missing_count": expression_draft_missing_count,
      "latest_expression_draft_missing_count": latest_expression_draft_missing_count,
      "expression_feedback_count": modules.get("expression_feedback", {}).get("feedback_count") if isinstance(modules.get("expression_feedback"), dict) else None,
      "expression_feedback_linked_outcome_count": modules.get("expression_feedback", {}).get("linked_outcome_count") if isinstance(modules.get("expression_feedback"), dict) else None,
      "expression_feedback_unlinked_count": modules.get("expression_feedback", {}).get("unlinked_count") if isinstance(modules.get("expression_feedback"), dict) else None,
      "speak_gate_evaluated_count": speak_gate_evaluated_count,
      "speak_gate_skipped_count": speak_gate_skipped_count,
      "speak_gate_missing_evaluation_count": speak_gate_missing_evaluation_count,
      "latest_speak_gate_missing_evaluation_count": latest_speak_gate_missing_evaluation_count,
      "latest_speak_gate_evaluated_count": latest_speak_gate_evaluated_count,
      "latest_wandering_result_count": latest_wandering_result_count,
      "speak_gate_decision_distribution": speak_gate_decision_distribution,
      "speak_gate_would_send_count": speak_gate.get("would_send_count"),
      "speak_gate_blocked_count": speak_gate.get("blocked_send_count", 0),
      "speak_gate_actual_send": speak_gate.get("actual_send"),
      "right_brain_adapter_request_count": right_brain_adapter.get("request_count"),
      "right_brain_adapter_latest_channel": right_brain_adapter.get("latest_channel"),
      "right_brain_adapter_latest_delivery_mode": right_brain_adapter.get("latest_delivery_mode"),
      "right_brain_adapter_latest_actual_send": right_brain_adapter.get("latest_actual_send"),
      "right_brain_adapter_raw_body_included_count": right_brain_adapter.get("raw_body_included_count"),
      "right_brain_adapter_policy_present": right_brain_adapter.get("policy_present"),
      "right_brain_adapter_policy_version": right_brain_adapter.get("policy_version"),
      "right_brain_adapter_policy_apply_count": right_brain_adapter.get("policy_apply_count"),
      "right_brain_adapter_outcome_count": right_brain_adapter.get("outcome_count"),
      "right_brain_adapter_latest_outcome_silent": right_brain_adapter.get("latest_outcome_silent"),
      "right_brain_adapter_latest_outcome_policy_version": right_brain_adapter.get("latest_outcome_policy_version"),
      "right_brain_adapter_outcome_internal_marker_count": right_brain_adapter.get("outcome_internal_marker_count"),
      "right_brain_adapter_outcome_feedback_count": right_brain_adapter.get("outcome_feedback_count"),
      "right_brain_adapter_latest_outcome_feedback_count": right_brain_adapter.get("latest_outcome_feedback_count"),
      "speak_permission_sent_count": speak_permission.get("sent_count"),
      "speak_permission_error_count": speak_permission.get("error_count"),
    }

def cognitive_loop_step_evidence():
    required_steps = [
      "left_brain_pipeline_check",
      "host_capability_probe",
      "signal_collection",
      "memory_projection",
      "left_brain_advisor",
      "governance_feedback",
      "deep_reflection",
      "heartbeat_post",
      "doctor_boundary_report",
    ]
    reports = _read_jsonl(os.path.join(_hermes_home, "system-modules/cognitive_loop/reports.jsonl"))
    latest = reports[-1] if reports and isinstance(reports[-1], dict) else {}
    if not latest:
        return {
          "schema_version": "memory-os.cognitive_loop_step_evidence.v0",
          "status": "missing",
          "required_steps": required_steps,
          "report_count": len(reports),
          "missing_required_steps": required_steps,
        }
    steps = latest.get("steps") if isinstance(latest.get("steps"), list) else []
    step_names = [
      str(step.get("step") or "")
      for step in steps
      if isinstance(step, dict) and step.get("step")
    ]
    step_summary = latest.get("step_summary") if isinstance(latest.get("step_summary"), dict) else {}
    tail_step_statuses = (
      step_summary.get("tail_step_statuses")
      if isinstance(step_summary.get("tail_step_statuses"), dict)
      else {}
    )
    visible_or_summarized = set(step_names) | set(tail_step_statuses.keys())
    missing_required_steps = [step for step in required_steps if step not in visible_or_summarized]
    omitted_step_count = int(step_summary.get("omitted_step_count") or 0)
    tail_step_omitted = [
      step
      for step, status in tail_step_statuses.items()
      if isinstance(status, dict) and status.get("status") == "omitted"
    ]
    return {
      "schema_version": "memory-os.cognitive_loop_step_evidence.v0",
      "status": "ok",
      "required_steps": required_steps,
      "report_count": len(reports),
      "latest_cycle_id": latest.get("cycle_id"),
      "latest_status": latest.get("status"),
      "latest_step_count": len(step_names),
      "latest_step_names": step_names,
      "latest_step_summary": step_summary,
      "missing_required_steps": missing_required_steps,
      "omitted_step_count": omitted_step_count,
      "tail_step_omitted": tail_step_omitted,
      "tail_step_omitted_count": len(tail_step_omitted),
    }

def module_cadence_summary():
    reports = _read_jsonl(os.path.join(_hermes_home, "system-modules/module_cadence/reports.jsonl"))
    latest = reports[-1] if reports and isinstance(reports[-1], dict) else {}
    boundary = latest.get("boundary") if isinstance(latest.get("boundary"), dict) else {}
    module_counters = {}
    module_current_window_error_counts = {}
    for item in latest.get("modules", []) if isinstance(latest.get("modules"), list) else []:
        if not isinstance(item, dict):
            continue
        counters = item.get("cadence_counters") if isinstance(item.get("cadence_counters"), dict) else {}
        module_id = str(item.get("module") or "")
        if module_id and counters:
            module_counters[module_id] = counters
            module_current_window_error_counts[module_id] = int(item.get("current_window_error_count") or 0)
    current_window_error_count = latest.get("current_window_error_count")
    if current_window_error_count is None and module_current_window_error_counts:
        current_window_error_count = sum(module_current_window_error_counts.values())
    return {
      "schema_version": "memory-os.module_cadence_monitor_summary.v0",
      "report_count": len(reports),
      "latest_report_id": latest.get("report_id"),
      "latest_status": latest.get("status"),
      "module_count": latest.get("module_count"),
      "cron_job_count": latest.get("cron_job_count"),
      "cognitive_loop_report_count": latest.get("cognitive_loop_report_count"),
      "integration_harness_member_count": latest.get("integration_harness_member_count"),
      "split_recommended_count": latest.get("split_recommended_count"),
      "expected_hermes_cron_missing_count": latest.get("expected_hermes_cron_missing_count"),
      "finding_count": latest.get("finding_count"),
      "generated_count": latest.get("generated_count"),
      "skipped_count": latest.get("skipped_count"),
      "error_count": latest.get("error_count"),
      "historical_error_count": latest.get("historical_error_count", latest.get("error_count")),
      "current_window_error_count": current_window_error_count,
      "duplicate_count": latest.get("duplicate_count"),
      "counter_coverage_count": latest.get("counter_coverage_count"),
      "module_counters": module_counters,
      "module_current_window_error_counts": module_current_window_error_counts,
      "boundary": {
        "actual_send": boundary.get("actual_send"),
        "actual_execute": boundary.get("actual_execute"),
        "actual_identity_write": boundary.get("actual_identity_write"),
        "actual_unapproved_crystallized_approval": boundary.get("actual_unapproved_crystallized_approval"),
        "cron_modified": boundary.get("cron_modified"),
      },
    }

def session_mirror_correlation_summary():
    code = r"""
import json
from collections import Counter
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.session_mirror import SessionMirror, _read_event_records
from plugins.memory.memory_os.store import MemoryOSStore

home = """ + json.dumps(_hermes_home) + r"""
roots = MemoryOSRoots.from_hermes_home(home, profile="default")
store = MemoryOSStore(roots)
mirror = SessionMirror(store)
state, state_rebuilt, findings = mirror._load_state(persist_repair=False)
sessions = mirror._discover_sessions()
covered = mirror._provider_captured_session_ids()
pending = [
    session
    for session in sessions
    if session["session_id"] not in covered and session["dedup_key"] not in state["seen_sessions"]
]
event_records = _read_event_records(store)

TOPIC_PATTERNS = {
    "approval_governance": ("审批", "approve", "reject", "proposal", "owner review", "oa_", "人工 follow-up"),
    "automation_orchestration": ("自动化", "automation", "workflow", "orchestration", "cron", "定时任务"),
    "hermes_voice_skill": ("voice", "voicebox", "语音", "skill", "built-in", "hermes skill"),
    "internet_data_collection": ("互联网数据采集", "数据采集", "采集系统", "n8n", "make.com", "crawler"),
    "memory_os": ("memory-os", "memory os", "记忆系统", "记忆架构", "crystallized", "deepreflection", "rh-"),
    "right_brain_expression": ("右脑", "表达", "wandering", "speakgate", "speak gate", "too_mechanical"),
}

def topic_groups(value):
    text = str(value or "").lower()
    groups = []
    for group, patterns in TOPIC_PATTERNS.items():
        if any(pattern.lower() in text for pattern in patterns):
            groups.append(group)
    return groups

def count_groups(values):
    counter = Counter()
    for value in values:
        for group in topic_groups(value):
            counter[group] += 1
    return counter

pending_counts = count_groups(
    [
        " ".join(
            [
                str(session.get("summary") or ""),
                str(session.get("platform") or ""),
                str(session.get("event_kind") or ""),
            ]
        )
        for session in pending
    ]
)
provider_counts = count_groups(
    [
        " ".join(
            [
                str(event.get("summary") or ""),
                str(event.get("kind") or ""),
                str(event.get("source") or ""),
                " ".join(str(tag) for tag in event.get("tags") or []),
            ]
        )
        for event in event_records
        if event.get("kind") == "conversation_turn"
    ]
)
mirrored_counts = count_groups(
    [
        " ".join(
            [
                str(event.get("summary") or ""),
                str(event.get("kind") or ""),
                str(event.get("source") or ""),
                " ".join(str(tag) for tag in event.get("tags") or []),
            ]
        )
        for event in event_records
        if event.get("kind") == "conversation_turn_mirrored"
    ]
)
pending_only = sorted(
    group
    for group, count in pending_counts.items()
    if count > 0 and provider_counts.get(group, 0) == 0 and mirrored_counts.get(group, 0) == 0
)
message_counts = [int(session.get("message_count") or 0) for session in pending]
result = {
    "schema_version": "memory-os.session_mirror_correlation_probe.v2",
    "status": "ok",
    "dry_run_only": True,
    "raw_private_body_printed": False,
    "written_event_ids_count": 0,
    "state_rebuilt": bool(state_rebuilt),
    "finding_count": len(findings),
    "session_count": len(sessions),
    "covered_session_count": sum(1 for session in sessions if session["session_id"] in covered),
    "pending_session_count": len(pending),
    "pending_platform_counts": dict(Counter(str(session.get("platform") or "unknown") for session in pending)),
    "pending_event_kind_counts": dict(Counter(str(session.get("event_kind") or "unknown") for session in pending)),
    "pending_message_count_min": min(message_counts) if message_counts else 0,
    "pending_message_count_max": max(message_counts) if message_counts else 0,
    "topic_group_counts": {
        "pending_sessions": dict(pending_counts),
        "provider_captured_events": dict(provider_counts),
        "existing_mirrored_events": dict(mirrored_counts),
    },
    "pending_only_groups": pending_only,
    "pending_only_group_count": len(pending_only),
    "internet_data_collection_pending_count": int(pending_counts.get("internet_data_collection") or 0),
    "internet_data_collection_provider_count": int(provider_counts.get("internet_data_collection") or 0),
}
print(json.dumps(result, ensure_ascii=False, sort_keys=True))
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = _hermes_home + "/memory-os/runtime/python"
    report = load_json_cmd(["python3", "-c", code], env=env)
    if isinstance(report, dict) and report.get("_error"):
        report.setdefault("schema_version", "memory-os.session_mirror_correlation_probe.v2")
        report.setdefault("status", "error")
    return report

def _execution_gate_scope_hash(scope):
    try:
        encoded = json.dumps(scope or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except Exception:
        encoded = "{}"
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

def _parse_aware_utc(value):
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)

def _execution_gate_expiry_status(value, reference_time=None):
    raw = str(value or "").strip()
    if not raw:
        return "missing"
    expires_at = _parse_aware_utc(raw)
    if expires_at is None:
        return "invalid"
    if reference_time is not None:
        return "expired_before_completion" if expires_at < reference_time else "valid_at_completion"
    return "expired" if expires_at <= datetime.now(timezone.utc) else "valid"

def session_mirror_auto_apply_permit_integrity(latest_apply, latest_governance):
    envelope_id = str(latest_governance.get("execution_gate_envelope_id") or "")
    if not envelope_id:
        return {"status": "missing", "reason": "execution_gate_envelope_id_missing"}
    stored_resolution = (
      latest_governance.get("execution_gate_permit_resolution")
      if isinstance(latest_governance.get("execution_gate_permit_resolution"), dict)
      else {}
    )
    records = _read_jsonl(os.path.join(_hermes_home, "memory-os/system/execution_gate_envelopes.jsonl"))
    permits = [
      record for record in records
      if isinstance(record, dict)
      and record.get("stage") == "permit"
      and str(record.get("execution_gate_envelope_id") or "") == envelope_id
    ]
    completions = [
      record for record in records
      if isinstance(record, dict)
      and record.get("stage") == "completion"
      and str(record.get("execution_gate_envelope_id") or "") == envelope_id
    ]
    expected_scope = {
      "approval_ref": str(latest_governance.get("approval_ref") or ""),
      "stable_scope_id": str(latest_governance.get("stable_scope_id") or ""),
      "max_sessions_per_run": int(latest_apply.get("max_sessions") or 0),
      "platform_allowlist": sorted([str(item).lower() for item in latest_apply.get("platform_allowlist", []) if str(item or "").strip()])
          if isinstance(latest_apply.get("platform_allowlist"), list)
          else [],
      "selected_session_fingerprints": [
        str(item)
        for item in (latest_apply.get("selected_session_fingerprints") if isinstance(latest_apply.get("selected_session_fingerprints"), list) else [])
      ],
    }
    expected_scope_hash = _execution_gate_scope_hash(expected_scope)
    if len(permits) != 1:
        return {
          "status": "invalid",
          "reason": "execution_gate_permit_missing_or_conflict",
          "execution_gate_envelope_id": envelope_id,
          "permit_count": len(permits),
          "completion_count": len(completions),
          "expected_scope_hash": expected_scope_hash,
        }
    permit = permits[0]
    completion_times = [
      parsed for parsed in (_parse_aware_utc(record.get("created_at")) for record in completions)
      if parsed is not None
    ]
    completion_time = min(completion_times) if completion_times else None
    expires_at_status = _execution_gate_expiry_status(permit.get("expires_at"), completion_time)
    permit_scope_hash = str(permit.get("scope_hash") or "")
    if not permit_scope_hash:
        permit_scope_hash = _execution_gate_scope_hash(permit.get("scope") if isinstance(permit.get("scope"), dict) else {})
    scope_match = permit_scope_hash == expected_scope_hash
    lane_match = str(permit.get("lane_id") or "") == "session_mirror_auto_apply"
    risk_match = str(permit.get("risk_class") or "") == "bounded_append_only_data_ingress"
    boundary_false = permit.get("boundary_true") is not True and _boundary_true_count(permit.get("boundary")) == 0
    unused_before_apply = stored_resolution.get("unused_before_apply") is True
    consumed_after_apply = len(completions) > 0
    completion_count_exactly_one = len(completions) == 1
    status = (
      "ok"
      if lane_match
      and risk_match
      and expires_at_status in {"valid", "valid_at_completion"}
      and boundary_false
      and scope_match
      and unused_before_apply
      and completion_count_exactly_one
      else "invalid"
    )
    reason = ""
    if status != "ok":
        if not lane_match:
            reason = "execution_gate_lane_mismatch"
        elif not risk_match:
            reason = "execution_gate_risk_class_mismatch"
        elif expires_at_status not in {"valid", "valid_at_completion"}:
            reason = f"execution_gate_permit_expiry_{expires_at_status}"
        elif not boundary_false:
            reason = "execution_gate_boundary_true"
        elif not scope_match:
            reason = "execution_gate_scope_mismatch"
        elif not unused_before_apply:
            reason = "execution_gate_permit_not_unused_before_apply"
        elif not completion_count_exactly_one:
            reason = "execution_gate_completion_missing" if not consumed_after_apply else "execution_gate_completion_count_not_one"
        else:
            reason = "execution_gate_permit_integrity_invalid"
    return {
      "status": status,
      "reason": reason,
      "execution_gate_envelope_id": envelope_id,
      "lane_id": str(permit.get("lane_id") or ""),
      "risk_class": str(permit.get("risk_class") or ""),
      "expires_at_status": expires_at_status,
      "completion_created_at": completion_time.isoformat() if completion_time is not None else "",
      "unused_before_apply": unused_before_apply,
      "consumed_after_apply": consumed_after_apply,
      "completion_count_exactly_one": completion_count_exactly_one,
      "scope_match": scope_match,
      "expected_scope_hash": expected_scope_hash,
      "permit_scope_hash": permit_scope_hash,
      "permit_count": len(permits),
      "completion_count": len(completions),
    }

def session_mirror_summary():
    status_report = load_json_cmd(["hermes", "memory-os-agent-os", "modules", "status"])
    dry_run = load_json_cmd(["hermes", "memory-os-agent-os", "modules", "run-once", "--module", "session_mirror", "--dry-run"])
    apply_status = load_json_cmd(["hermes", "memory-os-agent-os", "session-mirror", "apply-status"])
    correlation = session_mirror_correlation_summary()
    session_status = {}
    if isinstance(status_report, dict):
        for item in status_report.get("modules", []) if isinstance(status_report.get("modules"), list) else []:
            if isinstance(item, dict) and item.get("module") == "session_mirror":
                session_status = item.get("status") if isinstance(item.get("status"), dict) else {}
                break
    latest_apply = (
        apply_status.get("latest_apply")
        if isinstance(apply_status, dict) and isinstance(apply_status.get("latest_apply"), dict)
        else {}
    )
    latest_governance = (
        latest_apply.get("apply_governance")
        if isinstance(latest_apply.get("apply_governance"), dict)
        else {}
    )
    latest_boundary = latest_apply.get("boundary") if isinstance(latest_apply.get("boundary"), dict) else {}
    written_ids = dry_run.get("written_event_ids") if isinstance(dry_run, dict) and isinstance(dry_run.get("written_event_ids"), list) else []
    findings = dry_run.get("findings") if isinstance(dry_run, dict) and isinstance(dry_run.get("findings"), list) else []
    session_error_record = (
        session_status.get("last_error_record")
        if isinstance(session_status.get("last_error_record"), dict)
        else dry_run.get("last_error_record") if isinstance(dry_run, dict) and isinstance(dry_run.get("last_error_record"), dict)
        else {}
    )
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
      "suppressed_error_count": int(
          session_status.get("suppressed_error_count")
          or (dry_run.get("suppressed_error_count") if isinstance(dry_run, dict) else 0)
          or 0
      ),
      "recent_error_codes": (
          session_status.get("recent_error_codes")
          if isinstance(session_status.get("recent_error_codes"), list)
          else dry_run.get("recent_error_codes") if isinstance(dry_run, dict) and isinstance(dry_run.get("recent_error_codes"), list)
          else []
      )[-5:],
      "last_error_record": session_error_record,
      "correlation_schema_version": correlation.get("schema_version") if isinstance(correlation, dict) else None,
      "correlation_status": correlation.get("status") if isinstance(correlation, dict) else None,
      "correlation_finding_count": correlation.get("finding_count") if isinstance(correlation, dict) else None,
      "raw_private_body_printed": correlation.get("raw_private_body_printed") if isinstance(correlation, dict) else None,
      "written_event_ids_count": correlation.get("written_event_ids_count") if isinstance(correlation, dict) else None,
      "apply_status_schema_version": apply_status.get("schema_version") if isinstance(apply_status, dict) else None,
      "apply_count": apply_status.get("apply_count") if isinstance(apply_status, dict) else None,
      "latest_apply_status": latest_apply.get("status"),
      "latest_apply_bounded": latest_apply.get("apply_bounded"),
      "latest_apply_written_event_ids_count": latest_apply.get("written_event_ids_count"),
      "latest_apply_duplicate_ignored_count": latest_apply.get("duplicate_ignored_count"),
      "latest_apply_raw_private_body_printed": latest_apply.get("raw_private_body_printed"),
      "latest_apply_selected_session_count": latest_apply.get("selected_session_count"),
      "latest_apply_skipped_by_platform_count": latest_apply.get("skipped_by_platform_count"),
      "latest_apply_skipped_by_limit_count": latest_apply.get("skipped_by_limit_count"),
      "latest_apply_owner_approved": latest_governance.get("owner_approved"),
      "latest_apply_approval_resolved": latest_governance.get("approval_resolved"),
      "latest_apply_approval_source": latest_governance.get("approval_source"),
      "latest_apply_approval_ref": latest_governance.get("approval_ref"),
      "latest_apply_owner_channel_bound": latest_governance.get("owner_channel_bound"),
      "latest_apply_stable_scope_id": latest_governance.get("stable_scope_id"),
      "latest_apply_auto_apply": latest_governance.get("auto_apply"),
      "latest_apply_lane_graduated": latest_governance.get("lane_graduated"),
      "latest_apply_execution_gate_envelope_id": latest_governance.get("execution_gate_envelope_id"),
      "session_mirror_auto_apply_execution_gate_bound": bool(
          latest_governance.get("auto_apply")
          and latest_governance.get("lane_graduated")
          and latest_governance.get("execution_gate_envelope_id")
      ),
      "session_mirror_auto_apply_permit_integrity": session_mirror_auto_apply_permit_integrity(latest_apply, latest_governance)
          if latest_governance.get("auto_apply") and latest_governance.get("lane_graduated")
          else {},
      "latest_apply_boundary": latest_boundary,
      "latest_apply_boundary_true_count": _boundary_true_count(latest_boundary),
      "latest_apply_reused_approval_ref": False,
      "pending_platform_counts": correlation.get("pending_platform_counts") if isinstance(correlation, dict) else {},
      "pending_event_kind_counts": correlation.get("pending_event_kind_counts") if isinstance(correlation, dict) else {},
      "topic_group_counts": correlation.get("topic_group_counts") if isinstance(correlation, dict) else {},
      "pending_only_groups": correlation.get("pending_only_groups") if isinstance(correlation, dict) else [],
      "pending_only_group_count": correlation.get("pending_only_group_count") if isinstance(correlation, dict) else None,
      "internet_data_collection_pending_count": correlation.get("internet_data_collection_pending_count") if isinstance(correlation, dict) else None,
      "internet_data_collection_provider_count": correlation.get("internet_data_collection_provider_count") if isinstance(correlation, dict) else None,
    }

def _boundary_true_count(value):
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, dict):
        return sum(_boundary_true_count(item) for item in value.values())
    if isinstance(value, list):
        return sum(_boundary_true_count(item) for item in value)
    return 0

def execution_gate_cron_summary():
    specs = _memory_os_cron_specs_from_snapshot()
    specs_by_name = {str(item.get("name") or ""): item for item in specs}
    specs_by_lane = {str(item.get("lane_id") or ""): item for item in specs}
    known_specs = _memory_os_known_cron_specs()
    known_specs_by_name = {str(item.get("name") or ""): item for item in known_specs}
    known_specs_by_wrapper = {str(item.get("wrapper_script") or ""): item for item in known_specs}
    known_specs_by_raw = {str(item.get("raw_script") or ""): item for item in known_specs}
    adapter_probe = _execution_gate_cron_adapter_probe_summary()
    jobs_path = Path(_hermes_home) / "cron" / "jobs.json"
    try:
        loaded = json.loads(jobs_path.read_text(encoding="utf-8")) if jobs_path.exists() else {"jobs": []}
    except Exception as exc:
        return {
            "schema_version": "memory-os.execution_gate_cron_summary.v0",
            "status": "warning",
            "error": str(exc)[:200],
            "active_registry_job_count": len(specs_by_name),
            "memory_os_owned_expected_count": len(specs_by_name),
            "memory_os_owned_wrapped_count": 0,
            "memory_os_owned_naked_count": 0,
            "enabled_memory_os_job_count": 0,
            "memory_os_known_optional_count": 0,
            "enabled_known_optional_outside_active_registry_count": 0,
            "enabled_known_optional_outside_active_registry_jobs": [],
            "memory_os_like_unregistered_count": 0,
            "hermes_host_owned_count": 0,
            "external_unmanaged_count": 0,
            "unclassified_count": 0,
        }
    jobs = loaded.get("jobs", loaded) if isinstance(loaded, dict) else loaded
    jobs = [dict(item) for item in jobs if isinstance(item, dict)] if isinstance(jobs, list) else []
    wrapped = []
    naked = []
    known_optional = []
    unregistered_like = []
    hermes_host_owned = []
    external_unmanaged = []
    unclassified = []
    for job in jobs:
        name = str(job.get("name") or "")
        script = str(job.get("script") or "")
        spec = specs_by_name.get(name)
        safe = {
            "name": name,
            "script": script,
            "enabled": bool(job.get("enabled")),
            "deliver": str(job.get("deliver") or ""),
            "no_agent": bool(job.get("no_agent")),
        }
        if spec:
            if script == spec["wrapper_script"]:
                wrapped.append(safe)
            else:
                naked.append(safe)
            continue
        known_spec = known_specs_by_name.get(name) or known_specs_by_wrapper.get(script) or known_specs_by_raw.get(script)
        if known_spec:
            safe["known_registry_key"] = str(known_spec.get("key") or "")
            safe["known_optional_reason"] = "not_in_active_installed_snapshot"
            known_optional.append(safe)
            continue
        if name.startswith("memory-os-") or script.startswith("memory_os_"):
            unregistered_like.append(safe)
            continue
        if name.startswith("hermes-") or script.startswith("hermes_"):
            hermes_host_owned.append(safe)
            continue
        if name or script:
            external_unmanaged.append(safe)
        else:
            unclassified.append(safe)
    jobs_by_name = {str(job.get("name") or ""): job for job in jobs}
    completion_summary = _execution_gate_helper_completion_summary(specs_by_lane, jobs_by_name)
    summary = {
        "schema_version": "memory-os.execution_gate_cron_summary.v0",
        "status": "ok",
        "registry_snapshot_status": "ok" if specs else "missing_or_invalid",
        "classification_source": "registry_snapshot",
        "adapter_probe_status": str(adapter_probe.get("status") or ""),
        "adapter_owner": str(adapter_probe.get("adapter_owner") or ""),
        "active_registry_job_count": len(specs_by_name),
        "memory_os_owned_expected_count": len(specs_by_name),
        "memory_os_owned_wrapped_count": len(wrapped),
        "memory_os_owned_naked_count": len(naked),
        "enabled_memory_os_job_count": _enabled_job_count(wrapped)
        + _enabled_job_count(naked)
        + _enabled_job_count(known_optional)
        + _enabled_job_count(unregistered_like),
        "memory_os_known_optional_count": len(known_optional),
        "enabled_known_optional_outside_active_registry_count": _enabled_job_count(known_optional),
        "memory_os_like_unregistered_count": len(unregistered_like),
        "hermes_host_owned_count": len(hermes_host_owned),
        "external_unmanaged_count": len(external_unmanaged),
        "unclassified_count": len(unclassified),
        "wrapped_jobs": wrapped,
        "naked_jobs": naked,
        "known_optional_jobs": known_optional,
        "enabled_known_optional_outside_active_registry_jobs": [
            job for job in known_optional if job.get("enabled") is True
        ],
        "unregistered_like_jobs": unregistered_like,
        "external_unmanaged_jobs": external_unmanaged,
    }
    adapter_classification = (
        adapter_probe.get("classification") if isinstance(adapter_probe.get("classification"), dict) else {}
    )
    if adapter_probe.get("schema_version") == "memory-os.hermes_cron_adapter_probe.v0" and adapter_classification:
        for key in (
            "memory_os_owned_expected_count",
            "memory_os_owned_wrapped_count",
            "memory_os_owned_naked_count",
            "active_registry_job_count",
            "enabled_memory_os_job_count",
            "memory_os_known_optional_count",
            "enabled_known_optional_outside_active_registry_count",
            "memory_os_like_unregistered_count",
            "hermes_host_owned_count",
            "external_unmanaged_count",
            "unclassified_count",
            "wrapped_jobs",
            "naked_jobs",
            "known_optional_jobs",
            "enabled_known_optional_outside_active_registry_jobs",
            "unregistered_like_jobs",
            "external_unmanaged_jobs",
        ):
            if key in adapter_classification:
                summary[key] = adapter_classification.get(key)
        summary["classification_source"] = "hermes_cron_adapter_probe"
    summary.update(completion_summary)
    return summary

def _execution_gate_cron_adapter_probe_summary():
    # Resolve the probe script via HERMES_HOME first (installed location),
    # then fall back to common clone locations for hosts where the probe
    # hasn't been installed yet.
    #
    # NOTE: this function runs inside _remote_probe_script()'s generated
    # string — REPO_ROOT (module-level) is NOT in scope here.  All
    # candidates must use _hermes_home (enclosing-scope string), absolute
    # paths, or os.environ.
    hermes_home = _hermes_home
    candidates = [
        Path(hermes_home) / "scripts" / "memory_os_cron_adapter_probe.py",
        Path("/opt/Hermes-Memory-OS/scripts/memory_os_cron_adapter_probe.py"),
        Path.home() / "Hermes-Memory-OS" / "scripts" / "memory_os_cron_adapter_probe.py",
    ]
    script = None
    for candidate in candidates:
        if candidate.exists():
            script = candidate
            break
    if script is None:
        return {"status": "unavailable", "reason": "probe_script_missing"}
    result = run(
        ["python3", str(script), "--hermes-home", hermes_home, "--output", "json"],
        env={**os.environ, "HERMES_HOME": hermes_home},
        timeout_seconds=60,
    )
    if not result.get("ok"):
        return {"status": "error", "reason": "probe_command_failed", "code": result.get("code")}
    try:
        loaded = json.loads(result.get("out") or "{}")
    except Exception:
        return {"status": "error", "reason": "probe_json_invalid"}
    return loaded if isinstance(loaded, dict) else {"status": "error", "reason": "probe_json_not_object"}

def _memory_os_cron_specs_from_snapshot():
    snapshot_path = Path(_hermes_home) / "memory-os" / "system" / "memory_os_cron_registry.json"
    try:
        loaded = json.loads(snapshot_path.read_text(encoding="utf-8")) if snapshot_path.exists() else {}
    except Exception:
        loaded = {}
    specs = loaded.get("specs") if isinstance(loaded, dict) else []
    if isinstance(specs, list) and specs:
        return [dict(item) for item in specs if isinstance(item, dict)]
    return []

def _memory_os_known_cron_specs():
    try:
        from plugins.memory.memory_os.cron_registry import (
            RETIRED_MEMORY_OS_CRON_SCRIPTS,
            memory_os_cron_specs,
        )

        active = [
            {
                "key": item.key,
                "name": item.name,
                "raw_script": item.raw_script,
                "wrapper_script": item.wrapper_script,
            }
            for item in memory_os_cron_specs()
        ]
        retired = [
            {
                "key": "retired:" + name,
                "name": name,
                "raw_script": script,
                "wrapper_script": script,
                "retired": True,
            }
            for name, script in sorted(RETIRED_MEMORY_OS_CRON_SCRIPTS.items())
        ]
        return active + retired
    except Exception:
        return []

def _enabled_job_count(jobs):
    return sum(1 for item in jobs if item.get("enabled") is True)

def _execution_gate_helper_completion_summary(specs_by_lane, jobs_by_name=None):
    records_path = Path(_hermes_home) / "memory-os" / "system" / "execution_gate_envelopes.jsonl"
    completions = {}
    if records_path.exists():
        try:
            lines = records_path.read_text(encoding="utf-8").splitlines()
        except Exception:
            lines = []
        for line in lines[-5000:]:
            try:
                record = json.loads(line)
            except Exception:
                continue
            if not isinstance(record, dict) or record.get("stage") != "completion":
                continue
            lane = str(record.get("lane_id") or "")
            if lane in specs_by_lane:
                completions[lane] = record
    expected_lanes = set(specs_by_lane)
    completed = []
    missing = []
    stale = []
    not_due = []
    error = []
    # Envelope accounting gaps: cron job last_status=ok but no completion
    # record exists.  This is an envelope bookkeeping issue, not an
    # execution failure — the job ran successfully.
    reconciled_via_cron_status: list[str] = []
    boundary_true = 0
    boundary_observed = 0
    boundary_unobserved = 0
    boundary_not_required = 0
    now = datetime.now(timezone.utc)
    jobs_by_name = jobs_by_name or {}
    for lane in sorted(expected_lanes):
        record = completions.get(lane)
        if not record:
            # ── Cross-reference with cron job status ──────────────────
            spec = specs_by_lane.get(lane) if isinstance(specs_by_lane.get(lane), dict) else {}
            job_name = str(spec.get("name") or "")
            cron_job = jobs_by_name.get(job_name) if isinstance(jobs_by_name, dict) else {}
            if isinstance(cron_job, dict) and str(cron_job.get("last_status") or "") == "ok":
                schedule = _cron_schedule_display(cron_job)
                last_run = _parse_monitor_timestamp(str(cron_job.get("last_run_at") or ""))
                freshness = _helper_completion_freshness_window(schedule)
                if last_run is not None and now - last_run <= freshness:
                    # Fresh cron success is useful degraded evidence, but it is
                    # not a completion envelope and carries no boundary proof.
                    reconciled_via_cron_status.append(lane)
                    boundary_unobserved += 1
                    continue
            missing.append(lane)
            continue
        completed.append(lane)
        spec = specs_by_lane.get(lane) if isinstance(specs_by_lane.get(lane), dict) else {}
        schedule = ""
        job = jobs_by_name.get(str(spec.get("name") or "")) if isinstance(jobs_by_name, dict) else {}
        if isinstance(job, dict):
            schedule = _cron_schedule_display(job)
        record_time = _parse_monitor_timestamp(str(record.get("created_at") or ""))
        freshness = _helper_completion_freshness_window(schedule)
        if record_time and now - record_time > freshness:
            stale.append(lane)
        else:
            not_due.append(lane)
        postcheck = record.get("postcheck") if isinstance(record.get("postcheck"), dict) else {}
        try:
            returncode = int(postcheck.get("returncode") or 0)
        except Exception:
            returncode = 0
        if str(record.get("execution_status") or "") != "ok" or returncode != 0:
            error.append(lane)
        if record.get("postcheck_boundary_true") is True:
            boundary_true += 1
        if postcheck.get("postcheck_boundary_not_required") is True:
            boundary_not_required += 1
        elif postcheck.get("postcheck_boundary_observed") is True:
            boundary_observed += 1
        else:
            boundary_unobserved += 1
    return {
        "helper_completion_expected_count": len(expected_lanes),
        "helper_completion_completed_count": len(completed),
        "helper_completion_missing_count": len(missing),
        "helper_completion_reconciled_count": len(reconciled_via_cron_status),
        "helper_completion_stale_count": len(stale),
        "helper_completion_error_count": len(error),
        "helper_completion_not_due_count": len(not_due),
        "helper_completion_due_count": len(missing) + len(stale),
        "helper_completion_completed_lanes": completed,
        "helper_completion_missing_lanes": missing,
        "helper_completion_reconciled_lanes": reconciled_via_cron_status,
        "helper_completion_reconciliation_status": "degraded" if reconciled_via_cron_status else "not_used",
        "helper_completion_accounted_count": len(completed) + len(missing) + len(reconciled_via_cron_status),
        "helper_completion_stale_lanes": stale,
        "helper_completion_error_lanes": error,
        "helper_completion_not_due_lanes": not_due,
        "helper_boundary_true_count": boundary_true,
        "helper_boundary_observed_count": boundary_observed,
        "helper_boundary_unobserved_count": boundary_unobserved,
    }

def _parse_monitor_timestamp(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)

def _cron_schedule_display(job):
    if not isinstance(job, dict):
        return ""
    if str(job.get("schedule_display") or ""):
        return str(job.get("schedule_display") or "")
    schedule = job.get("schedule")
    if isinstance(schedule, dict):
        return str(schedule.get("expr") or schedule.get("display") or "")
    return str(schedule or "")

def _helper_completion_freshness_window(schedule):
    interval = _cron_schedule_interval(str(schedule or ""))
    minimum = timedelta(hours=12)
    grace = timedelta(hours=6)
    return max(interval * 2 + grace, minimum)

def _cron_schedule_interval(schedule):
    fields = str(schedule or "").split()
    if len(fields) != 5:
        return timedelta(hours=24)
    minute, hour, day_of_month, month, day_of_week = fields
    if day_of_week != "*":
        return timedelta(days=7)
    if day_of_month != "*" or month != "*":
        return timedelta(days=30)
    if minute.startswith("*/") and hour == "*":
        try:
            return timedelta(minutes=max(int(minute[2:]), 1))
        except ValueError:
            return timedelta(hours=1)
    if hour.startswith("*/"):
        try:
            return timedelta(hours=max(int(hour[2:]), 1))
        except ValueError:
            return timedelta(hours=24)
    if minute != "*" and hour != "*":
        return timedelta(days=1)
    return timedelta(hours=1)

def shell_alias_no_env():
    commands = {
      "status": ["hermes", "memory-os-agent-os", "status"],
      "doctor": ["hermes", "memory-os-agent-os", "doctor"],
      "memory_sources": ["hermes", "memory-os-agent-os", "memory-sources", "stats", "--hours", "24"],
      "metadata_retention": ["hermes", "memory-os-agent-os", "metadata-retention"],
      "low_clue": ["hermes", "memory-os-agent-os", "low-clue-recall", "dry-run", "--query", "继续昨天那个。", "--llm-judge", "none"],
      "modules": ["hermes", "memory-os-agent-os", "modules", "status"],
      "eval_report": ["hermes", "memory-os-agent-os", "eval", "rh31", "run", "--fixture", "synthetic", "--adapter", "all", "--no-write-report"],
      "review": ["hermes", "memory-os-agent-os", "review", "status"],
      "review_aging": ["hermes", "memory-os-agent-os", "review", "aging-report"],
      "review_channel": ["hermes", "memory-os-agent-os", "review", "channel"],
      "review_cron_status": ["hermes", "memory-os-agent-os", "review", "cron-status"],
      "review_delivery_status": ["hermes", "memory-os-agent-os", "review", "delivery-status"],
      "review_delivery_gate": ["hermes", "memory-os-agent-os", "review", "delivery-gate"],
      "review_followups": ["hermes", "memory-os-agent-os", "review", "proposal-followups"],
      "review_digest": ["hermes", "memory-os-agent-os", "review", "preview-digest"],
      "review_render": ["hermes", "memory-os-agent-os", "review", "render-digest"],
      "review_reply": ["hermes", "memory-os-agent-os", "review", "reply", "memory", "approve", "oa_deadbeef"],
      "host_probe": ["hermes", "memory-os-agent-os", "host-probe", "--json"],
      "signal_sources": ["hermes", "memory-os-agent-os", "signal-sources", "--json"],
      "memory_projection": ["hermes", "memory-os-agent-os", "projection", "status"],
      "left_brain": ["hermes", "memory-os-agent-os", "left-brain", "status"],
      "review_surface": [
        "hermes", "memory-os-agent-os", "review", "surface",
        "--operation", "next_page", "--section", "action_required", "--limit", "1",
      ],
    }
    try:
        workers = max(1, min(int(os.environ.get("MEMORY_OS_MONITOR_COMMAND_WORKERS", "4")), 8))
    except (TypeError, ValueError):
        workers = 4
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {name: executor.submit(load_json_cmd, command) for name, command in commands.items()}
        results = {}
        for name, future in futures.items():
            try:
                results[name] = future.result()
            except Exception as exc:
                results[name] = {"_error": "probe_exception:" + str(exc), "_code": 1}
    status = results["status"]
    doctor = results["doctor"]
    memory_sources = results["memory_sources"]
    metadata_retention = results["metadata_retention"]
    low_clue = results["low_clue"]
    modules = results["modules"]
    eval_report = results["eval_report"]
    review = results["review"]
    review_aging = results["review_aging"]
    review_channel = results["review_channel"]
    review_cron_status = results["review_cron_status"]
    review_delivery_status = results["review_delivery_status"]
    review_delivery_gate = results["review_delivery_gate"]
    review_followups = results["review_followups"]
    review_digest = results["review_digest"]
    review_render = results["review_render"]
    review_reply = results["review_reply"]
    host_probe = results["host_probe"]
    signal_sources = results["signal_sources"]
    memory_projection = results["memory_projection"]
    left_brain = results["left_brain"]
    review_surface = results["review_surface"]
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
      "host_probe_ok": (
          isinstance(host_probe, dict)
          and host_probe.get("schema_version")
          in {"memory-os.host_capability_probe.v0", "memory-os.host_capability_probe.v2"}
      ),
      "signal_sources_ok": isinstance(signal_sources, dict) and signal_sources.get("schema_version") == "memory-os.signal_source_requirement_report.v0",
      "memory_projection_ok": isinstance(memory_projection, dict) and memory_projection.get("schema_version") == "memory-os.memory_projection_status.v0",
      "left_brain_ok": isinstance(left_brain, dict) and left_brain.get("schema_version") == "memory-os.left_brain_advisor_status.v0",
      "review_surface_ok": isinstance(review_surface, dict) and review_surface.get("schema_version") == "memory-os.owner_review_surface.v0",
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
      "host_probe_error": host_probe.get("_error") if isinstance(host_probe, dict) else None,
      "signal_sources_error": signal_sources.get("_error") if isinstance(signal_sources, dict) else None,
      "memory_projection_error": memory_projection.get("_error") if isinstance(memory_projection, dict) else None,
      "left_brain_error": left_brain.get("_error") if isinstance(left_brain, dict) else None,
      "review_surface_error": review_surface.get("_error") if isinstance(review_surface, dict) else None,
    }

def owner_review_rendered_digest_summary():
    report = memory_os_cli(["review", "render-digest", "--max-action-required", "2", "--max-review-suggested", "2", "--max-fyi", "2"])
    if not isinstance(report, dict) or report.get("_error"):
        return report
    text = str(report.get("text") or "")
    sections = report.get("sections") if isinstance(report.get("sections"), dict) else {}
    rendered_items = [
      item
      for value in sections.values()
      if isinstance(value, list)
      for item in value
      if isinstance(item, dict)
    ]
    speak_items = [item for item in rendered_items if item.get("target_type") == "speak"]
    speak_preview_count = sum(1 for item in speak_items if str(item.get("expression_preview") or "").strip())
    return {
      "schema_version": report.get("schema_version"),
      "status": report.get("status"),
      "will_send": report.get("will_send"),
      "raw_body_included": report.get("raw_body_included"),
      "text_char_count": len(text),
      "text_has_internal_schema": any(token in text for token in ("Candidate kind=", "source_events=", "sensitivity=")),
      "text_has_transcript_marker": any(token in text for token in ("User:", "Assistant:", "用户:", "助手:", "用户：", "助手：", "| Assistant:", "| User:")),
      "response_header_present": all(token in text for token in ("回复方式", "A1/R1/F1 只是列表编号", "oa_")),
      "overview_present": all(token in text for token in ("全貌", "待处理", "未展示")),
      "speak_item_count": len(speak_items),
      "speak_expression_preview_count": speak_preview_count,
      "speak_expression_preview_missing_count": max(len(speak_items) - speak_preview_count, 0),
      "section_counts": {key: len(value) for key, value in sections.items() if isinstance(value, list)},
      "anchors": {
        key: [str(item.get("anchor") or "") for item in value if isinstance(item, dict)]
        for key, value in sections.items()
        if isinstance(value, list)
      },
      "boundary": report.get("boundary") if isinstance(report.get("boundary"), dict) else {},
    }

def owner_review_agenda_digest_summary():
    report = memory_os_cli(["review", "render-digest", "--mode", "agenda", "--max-action-required", "3"])
    if not isinstance(report, dict) or report.get("_error"):
        return report
    text = str(report.get("text") or "")
    sections = report.get("sections") if isinstance(report.get("sections"), dict) else {}
    section_counts = {key: len(value) for key, value in sections.items() if isinstance(value, list)}
    return {
      "schema_version": report.get("schema_version"),
      "status": report.get("status"),
      "digest_mode": report.get("digest_mode"),
      "raw_body_included": report.get("raw_body_included"),
      "text_char_count": len(text),
      "text_has_internal_schema": any(token in text for token in ("Candidate kind=", "source_events=", "sensitivity=")),
      "text_has_transcript_marker": any(token in text for token in ("User:", "Assistant:", "用户:", "助手:", "用户：", "助手：", "| Assistant:", "| User:")),
      "decision_summary_present": all(token in text for token in ("今日议程", "需要你决定", "本推送只包含审批项和真实告警")),
      "review_suggested_suppressed": section_counts.get("review_suggested", 0) == 0 and "建议你看:" not in text,
      "fyi_suppressed": section_counts.get("fyi", 0) == 0 and "仅供了解:" not in text,
      "backlog_totals_suppressed": "待处理" not in text and "仅供了解:" not in text and "建议你看:" not in text,
      "section_counts": section_counts,
      "counts": report.get("counts") if isinstance(report.get("counts"), dict) else {},
      "boundary": report.get("boundary") if isinstance(report.get("boundary"), dict) else {},
    }

def owner_review_reply_dry_run_summary():
    owner_utterance = _latest_recorded_owner_utterance()
    owner_utterance_source = "latest_recorded_digest" if owner_utterance else ""
    if not owner_utterance:
        owner_utterance_source = "fresh_render_no_record"
        rendered = memory_os_cli(["review", "render-digest", "--max-action-required", "2", "--max-review-suggested", "2", "--max-fyi", "2"])
        if isinstance(rendered, dict):
            owner_utterance = _first_rendered_owner_utterance(rendered)
    if not owner_utterance:
        return {
          "schema_version": "memory-os.owner_review_reply.v0",
          "status": "needs_clarification",
          "dry_run": True,
          "reason": "no_owner_utterance_available",
          "owner_utterance_source": owner_utterance_source,
        }
    report = memory_os_cli(["review", "reply", *owner_utterance.split(), "--max-action-required", "2", "--max-review-suggested", "2", "--max-fyi", "2"])
    if not isinstance(report, dict) or report.get("_error"):
        return report
    parsed = report.get("parsed") if isinstance(report.get("parsed"), dict) else {}
    owner_action = report.get("owner_action_result") if isinstance(report.get("owner_action_result"), dict) else {}
    return {
      "schema_version": report.get("schema_version"),
      "status": report.get("status"),
      "dry_run": report.get("dry_run"),
      "reason": report.get("reason"),
      "owner_utterance_source": owner_utterance_source,
      "parsed_action_type": parsed.get("action_type"),
      "parsed_target_type": parsed.get("target_type"),
      "owner_action_status": owner_action.get("status"),
      "owner_action_dry_run": owner_action.get("dry_run"),
      "boundary": report.get("boundary") if isinstance(report.get("boundary"), dict) else {},
    }

def _surface_operation_summary(report):
    if not isinstance(report, dict):
        return {"status": "unavailable"}
    boundary = report.get("boundary") if isinstance(report.get("boundary"), dict) else {}
    sections = report.get("sections") if isinstance(report.get("sections"), dict) else {}
    item = report.get("item") if isinstance(report.get("item"), dict) else {}
    items = []
    for value in sections.values():
        if isinstance(value, list):
            items.extend([entry for entry in value if isinstance(entry, dict)])
    if item:
        items.append(item)
    latest_outcome = report.get("latest_outcome") if isinstance(report.get("latest_outcome"), dict) else {}
    latest_memory_source = (
        report.get("latest_memory_source") if isinstance(report.get("latest_memory_source"), dict) else {}
    )
    feedback_actions = report.get("feedback_actions") if isinstance(report.get("feedback_actions"), dict) else {}
    if latest_outcome:
        items.append(latest_outcome)
    if latest_memory_source:
        items.append(latest_memory_source)
    forbidden_counts = _owner_surface_forbidden_field_counts(report)
    owner_utterance_example_count = _owner_surface_field_count(report, {"owner_utterance_example", "owner_utterance_examples"})
    agent_tool_call_count = _owner_surface_field_count(report, {"agent_tool_call", "agent_tool_calls"})
    return {
      "schema_version": report.get("schema_version"),
      "status": report.get("status"),
      "operation": report.get("operation"),
      "source": report.get("source") or report.get("binding_source"),
      "item_count": len(items),
      "feedback_action_count": len(feedback_actions),
      "latest_outcome_id": latest_outcome.get("target_id") if latest_outcome else "",
      "latest_memory_source_id": latest_memory_source.get("target_id") if latest_memory_source else "",
      "raw_body_included": report.get("raw_body_included") is True or any(
          entry.get("raw_body_included") is True for entry in items
      ),
      "boundary_true_count": sum(1 for value in boundary.values() if value is True),
      "forbidden_owner_command_field_count": sum(forbidden_counts.values()),
      "forbidden_owner_command_fields": sorted(key for key, count in forbidden_counts.items() if count),
      "owner_utterance_example_count": owner_utterance_example_count,
      "agent_tool_call_count": agent_tool_call_count,
    }

def owner_review_surface_summary():
    next_page = memory_os_cli([
        "review",
        "surface",
        "--operation",
        "next_page",
        "--section",
        "action_required",
        "--limit",
        "2",
    ])
    detail = memory_os_cli([
        "review",
        "surface",
        "--operation",
        "detail",
        "--anchor",
        "R1",
        "--channel",
        "telegram",
    ])
    followups = memory_os_cli([
        "review",
        "surface",
        "--operation",
        "proposal_followups",
        "--limit",
        "2",
    ])
    expression_feedback_context = memory_os_cli([
        "review",
        "surface",
        "--operation",
        "expression_feedback_context",
        "--limit",
        "6",
    ])
    memory_sources_feedback_context = memory_os_cli([
        "review",
        "surface",
        "--operation",
        "memory_sources_feedback_context",
        "--limit",
        "9",
    ])
    operations = {
      "next_page": _surface_operation_summary(next_page),
      "detail": _surface_operation_summary(detail),
      "proposal_followups": _surface_operation_summary(followups),
      "expression_feedback_context": _surface_operation_summary(expression_feedback_context),
      "memory_sources_feedback_context": _surface_operation_summary(memory_sources_feedback_context),
    }
    raw_body_count = sum(1 for item in operations.values() if item.get("raw_body_included") is True)
    boundary_true_count = sum(int(item.get("boundary_true_count") or 0) for item in operations.values())
    forbidden_counts = {}
    for item in operations.values():
        for key in item.get("forbidden_owner_command_fields") or []:
            forbidden_counts[key] = forbidden_counts.get(key, 0) + 1
    forbidden_owner_command_field_count = sum(
        int(item.get("forbidden_owner_command_field_count") or 0) for item in operations.values()
    )
    owner_utterance_example_count = sum(int(item.get("owner_utterance_example_count") or 0) for item in operations.values())
    agent_tool_call_count = sum(int(item.get("agent_tool_call_count") or 0) for item in operations.values())
    statuses = {str(item.get("status") or "") for item in operations.values()}
    allowed_statuses = {"ok", "needs_clarification", "empty", "unavailable"}
    return {
      "schema_version": "memory-os.owner_review_surface_monitor.v0",
      "status": "ok" if statuses <= allowed_statuses and "unavailable" not in statuses else "warning",
      "operations": operations,
      "raw_body_included_count": raw_body_count,
      "boundary_true_count": boundary_true_count,
      "forbidden_owner_command_field_count": forbidden_owner_command_field_count,
      "forbidden_owner_command_fields": sorted(forbidden_counts),
      "owner_utterance_example_count": owner_utterance_example_count,
      "agent_tool_call_count": agent_tool_call_count,
    }

def _owner_surface_forbidden_field_counts(value):
    forbidden = {"operator_cli", "command", "command_scope", "action_commands", "available_actions"}
    counts = {key: 0 for key in forbidden}
    _owner_surface_count_keys(value, forbidden, counts)
    return counts

def _owner_surface_field_count(value, keys):
    counts = {key: 0 for key in keys}
    _owner_surface_count_keys(value, keys, counts)
    return sum(counts.values())

def _owner_surface_count_keys(value, keys, counts):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in keys:
                if isinstance(child, list):
                    counts[key] = counts.get(key, 0) + len(child)
                elif child not in (None, "", {}):
                    counts[key] = counts.get(key, 0) + 1
            _owner_surface_count_keys(child, keys, counts)
    elif isinstance(value, list):
        for child in value:
            _owner_surface_count_keys(child, keys, counts)

def _first_rendered_owner_utterance(rendered):
    for items in (rendered.get("sections") or {}).values():
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            examples = (
                item.get("owner_utterance_examples")
                if isinstance(item.get("owner_utterance_examples"), list)
                else item.get("action_commands")
                if isinstance(item.get("action_commands"), list)
                else []
            )
            example = str(examples[0] if examples else "")
            if example:
                return example
    return ""

def _latest_recorded_owner_utterance():
    path = Path(_hermes_home) / "memory-os" / "system" / "owner_review_rendered_digests.jsonl"
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
        command = _first_rendered_owner_utterance(digest)
        if command:
            return command
    return ""

def owner_review_ingress_guard_summary():
    env = {
        key: value
        for key in ("PATH", "HOME", "LANG", "LC_ALL", "SYSTEMROOT", "WINDIR", "PATHEXT", "TMP", "TEMP", "TMPDIR")
        if (value := os.environ.get(key))
    }
    python_roots = [
        os.path.join(_hermes_home, "memory-os", "runtime", "python"),
        _hermes_home,
    ]
    env["HERMES_HOME"] = _hermes_home
    env["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(python_roots))
    env["PYTHONIOENCODING"] = "utf-8"
    code = """
import json
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

SCHEMA_VERSION = "memory-os.owner_review_ingress_guard.v0"


def module_origin_class(module_file, hermes_home):
    try:
        module_path = Path(module_file).resolve()
        runtime_root = (hermes_home / "memory-os" / "runtime" / "python").resolve()
        home_root = hermes_home.resolve()
        if module_path.is_relative_to(runtime_root):
            return "installed_runtime"
        if module_path.is_relative_to(home_root):
            return "hermes_home"
    except Exception:
        return "unknown"
    return "external"


def probe():
    base = {
        "schema_version": SCHEMA_VERSION,
        "probe_status": "bootstrap_error",
        "bootstrap_stage": "environment",
        "bootstrap_reason_code": "hermes_home_missing",
        "capability_observation_status": "unobserved",
        "module_origin_class": "unknown",
    }
    hermes_home_value = str(os.environ.get("HERMES_HOME") or "").strip()
    if not hermes_home_value:
        return base
    hermes_home = Path(hermes_home_value)
    base["bootstrap_stage"] = "import"
    base["bootstrap_reason_code"] = "module_import_failed"
    try:
        from plugins.memory.memory_os.__init__ import _looks_like_owner_review_reply
        from plugins.memory.memory_os import MemoryOSProvider
        from plugins.memory.memory_os.crystallized import CrystallizedCandidate, append_candidate_queue
        from plugins.memory.memory_os.owner_actions import owner_actions_path, render_owner_review_digest
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.runtime import MemoryOSRuntime
        from plugins.memory.memory_os.store import MemoryOSStore
    except Exception as exc:
        base["bootstrap_error_type"] = type(exc).__name__
        return base

    provider_module = sys.modules.get(MemoryOSProvider.__module__)
    base["module_origin_class"] = module_origin_class(getattr(provider_module, "__file__", ""), hermes_home)
    cases = {
        "legacy_anchor_accepted": _looks_like_owner_review_reply("approve A2"),
        "legacy_reject_anchor_accepted": _looks_like_owner_review_reply("reject R1"),
        "ordinary_anchor_text_accepted": _looks_like_owner_review_reply("普通聊天里提到 approve A2"),
        "token_command_accepted": _looks_like_owner_review_reply("memory approve oa_12345678"),
        "bare_token_command_accepted": _looks_like_owner_review_reply("approve oa_12345678"),
        "slash_token_command_accepted": _looks_like_owner_review_reply("/memory reject oa_12345678"),
        "feedback_token_command_accepted": _looks_like_owner_review_reply("memory feedback oa_12345678 too_mechanistic"),
        "bare_feedback_token_command_accepted": _looks_like_owner_review_reply("feedback oa_12345678 too_mechanistic"),
    }
    control_plane = {
        "owner_command_event_count": 0,
        "owner_command_working_count": 0,
        "owner_command_candidate_count": 0,
        "owner_command_promoted_to_candidate": False,
        "owner_review_command_pollution_count": 0,
        "gateway_hook_plugin_present": False,
        "gateway_hook_registered": False,
        "gateway_safety_skip_count": 0,
        "review_reply_tool_available": False,
        "review_reply_tool_status": "",
        "review_reply_tool_input_mode": "",
        "structured_review_reply_count": 0,
        "reply_fallback_used_count": 0,
    }
    try:
        plugin_path = hermes_home / "plugins" / "memory-os-agent-os" / "__init__.py"
        if plugin_path.exists():
            control_plane["gateway_hook_plugin_present"] = True
            spec = importlib.util.spec_from_file_location("memory_os_agent_os_monitor_probe", plugin_path)
            if spec is not None and spec.loader is not None:
                shell = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(shell)
                hooks = []

                class Ctx:
                    def register_cli_command(self, **kwargs):
                        return None

                    def register_hook(self, name, callback):
                        hooks.append(name)

                    def register_command(self, *args, **kwargs):
                        return None

                shell.register(Ctx())
                control_plane["gateway_hook_registered"] = "pre_gateway_dispatch" in hooks
        with tempfile.TemporaryDirectory() as tmp:
            roots = MemoryOSRoots.from_hermes_home(tmp, profile="default")
            store = MemoryOSStore(roots)
            store.initialize()
            append_candidate_queue(
                store,
                CrystallizedCandidate(
                    candidate_id="cand_monitor_owner_ingress",
                    kind="preference",
                    body="Bounded monitor candidate for owner ingress guard.",
                    source_event_ids=["evt_monitor_owner_ingress"],
                    sensitivity="private",
                ),
            )
            rendered = render_owner_review_digest(
                store,
                channel="telegram",
                max_action_required=1,
                max_review_suggested=0,
                max_fyi=0,
                record_active=True,
            )
            command = ""
            for item in (rendered.get("sections") or {}).get("action_required", []):
                if item.get("anchor") == "A1":
                    command = "memory reject " + str((item.get("action_tokens") or {}).get("reject_candidate") or "")
                    break
            provider = MemoryOSProvider()
            provider.initialize(
                "session-monitor-owner-ingress",
                hermes_home=tmp,
                platform="telegram",
                agent_identity="default",
                worker_autostart=False,
            )
            control_plane["review_reply_tool_available"] = any(
                schema.get("name") == "memory_os_review_reply" for schema in provider.get_tool_schemas()
            )
            if not command.strip():
                raise RuntimeError("missing_review_token")
            parts = command.split()
            token = parts[2] if len(parts) >= 3 else ""
            tool_result = json.loads(
                provider.handle_tool_call(
                    "memory_os_review_reply",
                    {
                        "action": "reject",
                        "action_token": token,
                        "owner_utterance": "reject A1",
                    },
                )
            )
            control_plane["review_reply_tool_status"] = str(tool_result.get("status") or "")
            control_plane["review_reply_tool_input_mode"] = str((tool_result.get("tool_input") or {}).get("mode") or "")
            if control_plane["review_reply_tool_input_mode"] == "structured":
                control_plane["structured_review_reply_count"] = 1
            elif control_plane["review_reply_tool_input_mode"] == "reply_fallback":
                control_plane["reply_fallback_used_count"] = 1
            provider.sync_turn("reject A1", "ack", session_id="session-monitor-owner-ingress")
            provider.shutdown()
            heartbeat = MemoryOSRuntime(store).heartbeat()
            control_plane["owner_command_event_count"] = len(store.read_events())
            control_plane["owner_command_working_count"] = int(heartbeat.get("working_created_count") or 0)
            control_plane["owner_command_candidate_count"] = int(heartbeat.get("candidate_created_count") or 0)
            control_plane["owner_command_promoted_to_candidate"] = bool(control_plane["owner_command_candidate_count"])
            control_plane["owner_review_command_pollution_count"] = (
                int(control_plane["owner_command_event_count"])
                + int(control_plane["owner_command_working_count"])
                + int(control_plane["owner_command_candidate_count"])
            )
            control_plane["owner_command_action_count"] = len(
                [line for line in owner_actions_path(roots).read_text(encoding="utf-8").splitlines() if line.strip()]
            ) if owner_actions_path(roots).exists() else 0
    except Exception as exc:
        return {
            **base,
            **cases,
            **control_plane,
            "probe_status": "probe_error",
            "bootstrap_stage": "execute",
            "bootstrap_reason_code": "probe_execution_failed",
            "probe_error_type": type(exc).__name__,
        }
    return {
        **base,
        **cases,
        **control_plane,
        "probe_status": "ok",
        "bootstrap_stage": "complete",
        "bootstrap_reason_code": "",
        "capability_observation_status": "observed",
    }


print(json.dumps(probe(), ensure_ascii=False, sort_keys=True))
"""
    report = load_json_cmd([sys.executable, "-c", code], env=env)
    if isinstance(report, dict) and report.get("_error"):
        return {
            "schema_version": "memory-os.owner_review_ingress_guard.v0",
            "probe_status": "bootstrap_error",
            "bootstrap_stage": "process",
            "bootstrap_reason_code": "child_process_failed",
            "capability_observation_status": "unobserved",
            "child_exit_code": report.get("_code"),
        }
    return report

status = load_json_cmd(["hermes", "memory-os-agent-os", "status"])
doctor = load_json_cmd(["hermes", "memory-os-agent-os", "doctor"])
contract = memory_os_cli(["conversation-regression", "status-tool-contract"])
memory_sources = memory_os_cli(["memory-sources", "stats", "--hours", "24"])
memory_sources = enrich_memory_sources_stats(memory_sources)
rh31_eval = memory_os_cli(["eval", "rh31", "run", "--fixture", "synthetic", "--adapter", "all", "--adapter", "retrieval_shadow", "--no-write-report"])
owner_review = memory_os_cli(["review", "status"])
owner_review_aging = memory_os_cli(["review", "aging-report"])
owner_review_channel = memory_os_cli(["review", "channel"])
owner_review_cron_integration = memory_os_cli(["review", "cron-status"])
owner_review_delivery_status = memory_os_cli(["review", "delivery-status"])
owner_review_delivery_gate = memory_os_cli(["review", "delivery-gate"])
owner_review_proposal_followups = memory_os_cli(["review", "proposal-followups", "--limit", "10"])
owner_review_proposal_auto_route = memory_os_cli(["review", "proposal-followups", "--auto-route", "--limit", "10"])
host_capability_probe = seam_host_probe()
v2_exposure_and_clearance_probe_result = v2_exposure_and_clearance_probe()
living_memory_promotion_probe_result = living_memory_promotion_probe()
signal_source_requirements = memory_os_cli(["signal-sources", "--json"])
memory_projection = memory_os_cli(["projection", "status"])
memory_projection_retention = memory_os_cli(["projection", "retention-status"])
left_brain_advisor = memory_os_cli(["left-brain", "status"])
owner_review_digest_preview = memory_os_cli(["review", "preview-digest"])
owner_review_rendered_digest = owner_review_rendered_digest_summary()
owner_review_agenda_digest = owner_review_agenda_digest_summary()
owner_review_reply_dry_run = owner_review_reply_dry_run_summary()
owner_review_surface = owner_review_surface_summary()
owner_review_ingress_guard = owner_review_ingress_guard_summary()
cfg_path = Path(_hermes_home) / "memory-os" / "config.json"
cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
df = run(["df", "-h", os.path.join(_hermes_home, "memory-os")])["out"]
du = run(["du", "-sh", os.path.join(_hermes_home, "memory-os")])["out"]
heartbeat_list = run(["systemctl", "--user", "list-timers", "hermes-memory-os-heartbeat.timer", "--no-pager"])["out"]

print(json.dumps({
  "hostname": run(["hostname"])["out"],
  "date_utc": run(["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"])["out"],
  "date_local": run(["date", "+%Y-%m-%d %H:%M:%S %Z"])["out"],
  "gateway": system_show("hermes-gateway.service"),
  "hermes_status": hermes_status_summary(),
  "heartbeat_timer": system_show("hermes-memory-os-heartbeat.timer"),
  "heartbeat_service": system_show("hermes-memory-os-heartbeat.service"),
  "heartbeat_state": heartbeat_state(),
  "heartbeat_listed": "hermes-memory-os-heartbeat.timer" in heartbeat_list,
  "cognitive_loop_timer": system_show("hermes-memory-os-cognitive-loop.timer"),
  "cognitive_loop_service": system_show("hermes-memory-os-cognitive-loop.service"),
  "cognitive_loop_listed": "hermes-memory-os-cognitive-loop.timer" in run(["systemctl", "--user", "list-timers", "hermes-memory-os-cognitive-loop.timer", "--no-pager"])["out"],
  "memory_status": {
    "counts": status.get("counts") if isinstance(status, dict) else None,
    "index_counts": status.get("index_counts") if isinstance(status, dict) else None,
    "index_health": status.get("index_health") if isinstance(status, dict) else None,
    "prefetch_mode": status.get("prefetch_mode") if isinstance(status, dict) else None,
    "last_write_age_seconds": status.get("last_write_age_seconds") if isinstance(status, dict) else None,
    "hindsight_adapter_enabled": status.get("hindsight_adapter_enabled") if isinstance(status, dict) else None,
    "hindsight_substrate": status.get("hindsight_substrate") if isinstance(status, dict) else None,
    "queue_backlog": status.get("queue_backlog") if isinstance(status, dict) else None,
  },
  "hindsight_substrate": status.get("hindsight_substrate") if isinstance(status, dict) else None,
  "doctor": {
    "status": doctor.get("status") if isinstance(doctor, dict) else None,
    "exit_code": doctor.get("exit_code") if isinstance(doctor, dict) else None,
    "findings": [(x.get("code"), x.get("severity")) for x in doctor.get("findings", [])] if isinstance(doctor, dict) else None,
  },
  "status_tool_contract": contract.get("validation") if isinstance(contract, dict) else contract,
  "shell_alias_no_env": shell_alias_no_env(),
  "cognitive_loop": memory_os_cli(["cognitive-loop", "status"]),
  "cognitive_loop_step_evidence": cognitive_loop_step_evidence(),
  "memory_sources": memory_sources,
  "rh31_eval": rh31_eval,
  "owner_review": owner_review,
  "owner_review_aging": owner_review_aging,
  "owner_review_channel": owner_review_channel,
  "owner_review_cron_integration": owner_review_cron_integration,
  "owner_review_delivery_status": owner_review_delivery_status,
  "owner_review_delivery_gate": owner_review_delivery_gate,
  "owner_review_proposal_followups": owner_review_proposal_followups,
  "owner_review_proposal_auto_route": owner_review_proposal_auto_route,
  "host_capability_probe": host_capability_probe,
  "v2_exposure_and_clearance_probe": v2_exposure_and_clearance_probe_result,
  "living_memory_promotion_probe": living_memory_promotion_probe_result,
  "signal_source_requirements": signal_source_requirements,
  "memory_projection": memory_projection,
  "memory_projection_retention": memory_projection_retention,
  "left_brain_advisor": left_brain_advisor,
  "execution_gate_cron": execution_gate_cron_summary(),
  "owner_review_digest_preview": owner_review_digest_preview,
  "owner_review_rendered_digest": owner_review_rendered_digest,
  "owner_review_agenda_digest": owner_review_agenda_digest,
  "owner_review_reply_dry_run": owner_review_reply_dry_run,
  "owner_review_surface": owner_review_surface,
  "owner_review_ingress_guard": owner_review_ingress_guard,
  "module_artifacts": active_module_artifact_summary(),
  "legacy_right_brain_archive": legacy_right_brain_archive_summary(),
  "module_cadence": module_cadence_summary(),
  "expression_artifacts": expression_artifact_summary(),
  "session_mirror": session_mirror_summary(),
  "audit_actions": audit_action_stats(hermes_home=_hermes_home),
  "working_status": working_status(),
  "memory_os_config": {"l4": cfg.get("l4", {})},
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
