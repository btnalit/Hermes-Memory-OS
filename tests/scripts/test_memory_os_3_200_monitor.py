import json
import sys

import scripts.memory_os_3_200_monitor as monitor
from scripts.memory_os_3_200_monitor import (
    classify_snapshot,
    compute_deltas,
    find_rh26_heading_anomalies,
    main,
    render_chinese_summary,
    summarize_l4_guard,
    summarize_v7_governance,
)


def _exec_remote_probe_prefix(namespace: dict[str, object]) -> None:
    original_sys_path = list(sys.path)
    try:
        exec(
            monitor._remote_probe_script().split(
                '\nstatus = load_json_cmd(["hermes", "memory-os-agent-os", "status"])',
                1,
            )[0],
            namespace,
        )
    finally:
        sys.path[:] = original_sys_path


def _v7_component_records(*, exclude: set[str] | None = None) -> list[dict]:
    excluded = set(exclude or set())
    return [
        {
            "component": component,
            "task_installed": True,
            "pipeline_liveness": "live-shadow",
            "autonomy_level": "shadow",
            "live_guard_registered": True,
            "live_applied": False,
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_crystallized_approval": False,
        }
        for component in monitor.V7_GOVERNANCE_COMPONENTS
        if component not in excluded
    ]


def test_rh26_heading_anomalies_allow_known_casual_empty_and_safe_carryover_state():
    probes = [
        {"id": "cancel_failed_video", "chars": 134, "headings": ["Current Foreground Task"]},
        {"id": "continue_current_task", "chars": 108, "headings": ["Current Foreground Task"]},
        {"id": "casual_memory_system_change", "chars": 0, "headings": []},
        {"id": "casual_memory_system_change", "chars": 1535, "headings": ["Recent Event Summaries"]},
        {
            "id": "diagnostic_current_architecture",
            "chars": 297,
            "headings": ["Diagnostic Grounding", "Current Memory-OS Runtime Facts"],
        },
        {
            "id": "candidate_vs_crystallized",
            "chars": 1306,
            "headings": ["Crystallized Review Candidates", "Crystallized Memory", "Indexed Recall"],
        },
        {
            "id": "candidate_vs_crystallized",
            "chars": 975,
            "headings": ["Crystallized Review Candidates", "Crystallized Memory"],
        },
        {
            "id": "active_comfyui_install",
            "chars": 2051,
            "headings": ["Current Foreground Task", "Crystallized Memory", "Indexed Recall", "Recent Event Summaries"],
        },
        {"id": "deferred_cancellation", "chars": 110, "headings": ["Current Foreground Task"]},
    ]

    assert find_rh26_heading_anomalies(probes) == []


def test_rh26_heading_anomalies_flag_background_context_on_cancel_and_casual():
    probes = [
        {
            "id": "cancel_failed_video",
            "chars": 800,
            "headings": ["Current Foreground Task", "Working Memory"],
        },
        {
            "id": "casual_memory_system_change",
            "chars": 1200,
            "headings": ["Current Foreground Task", "Indexed Recall"],
        },
    ]

    anomalies = find_rh26_heading_anomalies(probes)

    assert {
        "id": "cancel_failed_video",
        "severity": "fail",
        "code": "unexpected_rh26_headings",
        "expected": ["Current Foreground Task"],
        "actual": ["Current Foreground Task", "Working Memory"],
    } in anomalies
    assert {
        "id": "casual_memory_system_change",
        "severity": "fail",
        "code": "casual_context_forbidden_heading",
        "expected": [],
        "actual": ["Current Foreground Task", "Indexed Recall"],
    } in anomalies


def test_rh26_heading_anomalies_warn_on_unclassified_casual_context():
    probes = [
        {
            "id": "casual_memory_system_change",
            "chars": 900,
            "headings": ["Working Memory"],
        }
    ]

    anomalies = find_rh26_heading_anomalies(probes)

    assert anomalies == [
        {
            "id": "casual_memory_system_change",
            "severity": "warning",
            "code": "casual_context_needs_review",
            "expected": [],
            "actual": ["Working Memory"],
        }
    ]


def test_compute_deltas_tracks_count_growth_and_audit_ratios():
    current = {
        "memory_status": {
            "counts": {
                "audit_entries": 110,
                "events": 12,
                "working_items": 7,
                "crystallized_candidates": 7,
                "crystallized_records": 0,
            }
        },
        "audit_actions": {
            "action_counts": {
                "runtime_heartbeat": 20,
                "write_working_document": 12,
                "append_event": 4,
            }
        },
    }
    previous = {
        "memory_status": {
            "counts": {
                "audit_entries": 100,
                "events": 10,
                "working_items": 5,
                "crystallized_candidates": 5,
                "crystallized_records": 0,
            }
        },
        "audit_actions": {
            "action_counts": {
                "runtime_heartbeat": 10,
                "write_working_document": 7,
                "append_event": 2,
            }
        },
    }

    deltas = compute_deltas(current, previous)

    assert deltas["counts_delta"] == {
        "audit_entries": 10,
        "events": 2,
        "working_items": 2,
        "crystallized_candidates": 2,
        "crystallized_records": 0,
    }
    assert deltas["audit_entries_per_new_event"] == 5.0
    assert deltas["audit_action_delta"] == {
        "append_event": 2,
        "runtime_heartbeat": 10,
        "write_working_document": 5,
    }


def test_compute_deltas_tracks_hook_marker_and_session_activity_growth():
    current = {
        "memory_status": {"counts": {"audit_entries": 10, "events": 5}},
        "hook_markers": {"started": 3, "reset": 2, "finalized": 1, "total": 6},
        "session_activity": {"total_session_events": 5},
    }
    previous = {
        "memory_status": {"counts": {"audit_entries": 8, "events": 3}},
        "hook_markers": {"started": 3, "reset": 2, "finalized": 1, "total": 6},
        "session_activity": {"total_session_events": 3},
    }

    deltas = compute_deltas(current, previous)

    assert deltas["hook_marker_delta"] == {"started": 0, "reset": 0, "finalized": 0, "total": 0}
    assert deltas["session_activity_delta"] == {"total_session_events": 2}


def test_compute_deltas_backfills_hook_marker_total_when_previous_snapshot_lacks_total():
    current = {
        "memory_status": {"counts": {"audit_entries": 10, "events": 5}},
        "hook_markers": {"started": 20, "reset": 19, "finalized": 22, "total": 61},
    }
    previous = {
        "memory_status": {"counts": {"audit_entries": 8, "events": 3}},
        "hook_markers": {"started": 17, "reset": 15, "finalized": 17},
    }

    deltas = compute_deltas(current, previous)

    assert deltas["hook_marker_delta"] == {"started": 3, "reset": 4, "finalized": 5, "total": 12}


def test_compute_deltas_does_not_backfill_action_delta_from_legacy_snapshot():
    current = {
        "memory_status": {"counts": {"audit_entries": 110, "events": 12}},
        "audit_actions": {"action_counts": {"runtime_heartbeat": 20}},
    }
    previous = {"memory_status": {"counts": {"audit_entries": 100, "events": 10}}}

    deltas = compute_deltas(current, previous)

    assert deltas["counts_delta"]["audit_entries"] == 10
    assert deltas["audit_action_delta"] == {}


def test_classify_snapshot_warns_on_expected_observation_items_without_fail():
    snapshot = {
        "gateway": {"ActiveState": "active"},
        "heartbeat_timer": {"ActiveState": "active", "UnitFileState": "enabled"},
        "heartbeat_listed": True,
        "cognitive_loop_timer": {"ActiveState": "active", "UnitFileState": "enabled"},
        "cognitive_loop_listed": True,
        "cognitive_loop": _healthy_cognitive_loop(),
        "memory_status": {
            "counts": {"crystallized_records": 0},
            "index_health": {"state": "healthy"},
            "prefetch_mode": "indexed",
        },
        "doctor": {"status": "ok", "findings": [("hindsight_adapter_disabled", "warning")]},
        "status_tool_contract": {"status": "ok", "findings": []},
        "shell_alias_no_env": {
            "status_ok": True,
            "doctor_ok": True,
            "memory_sources_ok": True,
            "metadata_retention_ok": True,
            "low_clue_recall_ok": True,
            "modules_ok": True,
            "eval_ok": True,
            "review_ok": True,
            "review_aging_ok": True,
        },
        "context_router": {"enabled": True, "mode": "apply", "apply_routes": ["all"]},
        "rh26_apply_probe": [{"id": "casual_memory_system_change", "chars": 0, "headings": []}],
        "deep_reflection": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_crystallized_approval": False,
            "rolling_injection_source_classes": {
                "selected_by_source_class": {"working": 14},
                "window_report_count": 7,
            },
        },
        "compaction": {"recent_count": 2, "focus_none_count": 2},
        "low_clue_recall": {
            "schema_version": "memory-os.low_clue_recall.v0",
            "decision": "ask_choice",
            "candidate_count": 2,
            "llm_judge": {"status": "disabled", "mode": "none"},
        },
        "low_clue_ingress_matrix": [
            {
                "id": "deictic_yesterday",
                "route": "ambiguous_recall",
                "headings": ["Recall Clarification Guard"],
                "expected_route": "ambiguous_recall",
                "expected_heading": "Recall Clarification Guard",
                "guard_contract_ok": True,
            }
        ],
    }

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "WARN"
    assert not classification["fail"]
    assert any(item["code"] == "rh26_casual_empty" for item in classification["warn"])
    assert any(item["code"] == "deep_reflection_source_skew" for item in classification["warn"])
    assert any(item["code"] == "compression_focus_none" for item in classification["warn"])
    assert any(item["code"] == "shell_alias_no_env_ok" for item in classification["pass"])


def test_classify_snapshot_tracks_rh31_eval_safety_and_status():
    snapshot = _healthy_snapshot()
    snapshot["rh31_eval"] = {
        "schema_version": "memory-os.rh31_summary.v0",
        "status": "warning",
        "boundary_true_count": 0,
        "forbidden_field_count": 0,
        "adapter_count": 6,
        "failure_count": 2,
        "measurement_signal_count": 2,
        "live_guard_candidate_count": 0,
        "failure_class_distribution": {"fts_miss": 1, "lexical_miss": 1},
    }

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "rh31_eval_safety_ok" for item in classification["pass"])
    assert any(item["code"] == "rh31_eval_measurement_signals" for item in classification["warn"])
    assert not any(item["code"] == "rh31_eval_has_failures" for item in classification["warn"])

    snapshot["rh31_eval"]["forbidden_field_count"] = 1
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "rh31_eval_forbidden_fields" for item in classification["fail"])


def test_classify_snapshot_accepts_optional_hindsight_off():
    snapshot = _healthy_snapshot()
    snapshot["hindsight_substrate"] = {
        "schema_version": "memory-os.hindsight_substrate_status.v0",
        "enabled": False,
        "status": "optional_not_configured",
    }

    classification = classify_snapshot(snapshot)

    assert {"code": "hindsight_optional_off_ok"} in classification["pass"]
    assert not [item for item in classification["fail"] if item["code"].startswith("hindsight")]


def test_classify_snapshot_accepts_nested_memory_status_hindsight_configured():
    snapshot = _healthy_snapshot()
    snapshot["memory_status"]["hindsight_substrate"] = {
        "schema_version": "memory-os.hindsight_substrate_status.v0",
        "enabled": True,
        "status": "configured",
        "recall_mode": "shadow",
        "substrate_monitor": {
            "raw_retained_count": 0,
            "no_raw_retained": True,
            "projection_stale_count": 0,
            "external_authoritative_count": 0,
            "reflect_off_hot_path": True,
            "recall_llm_triggered": False,
        },
    }

    classification = classify_snapshot(snapshot)

    assert {"code": "hindsight_configured_ok"} in classification["pass"]
    assert not [item for item in classification["fail"] if item["code"].startswith("hindsight")]


def test_classify_snapshot_fails_on_hindsight_raw_retain_projection_or_authority():
    snapshot = _healthy_snapshot()
    snapshot["hindsight_substrate"] = {
        "schema_version": "memory-os.hindsight_substrate_status.v0",
        "enabled": True,
        "status": "configured",
        "recall_mode": "shadow",
        "substrate_monitor": {
            "raw_retained_count": 1,
            "no_raw_retained": False,
            "projection_stale_count": 1,
            "local_first_authority_preserved": False,
            "external_authoritative_count": 1,
        },
    }

    classification = classify_snapshot(snapshot)
    fail_codes = {item["code"] for item in classification["fail"]}

    assert "hindsight_raw_retain_detected" in fail_codes
    assert "hindsight_projection_stale" in fail_codes
    assert "hindsight_overrode_local_authority" in fail_codes


def test_v7_governance_summary_defaults_to_missing_shadow_components():
    snapshot = _healthy_snapshot()

    summary = summarize_v7_governance(snapshot)

    assert summary["schema_version"] == "memory-os.v7_governance_summary.v0"
    assert summary["component_count"] == 18
    assert summary["shadow_live_component_count"] == 0
    assert summary["acting_component_count"] == 0
    assert summary["live_guard_registered_count"] == 0
    assert summary["memory_sources_feedback_volume_ready"] is False
    assert summary["component_status"]["promotion_matrix"] == "missing"
    assert summary["component_status"]["live_guard_registry"] == "missing"
    assert summary["confidence_router_status"] == "missing"
    assert summary["simulation_coverage_status"] == "missing"
    assert summary["confabulation_detection_status"] == "missing"
    assert summary["crystallized_revalidator_status"] == "missing"
    assert summary["cross_check_anchoring_status"] == "missing"
    assert summary["component_status"]["symbolic_offloader"] == "missing"
    assert summary["component_status"]["judge_calibration"] == "missing"
    assert summary["component_status"]["candidate_review"] == "missing"
    assert summary["component_status"]["shadow_recall"] == "missing"
    assert summary["component_status"]["provisional"] == "missing"
    assert summary["component_status"]["cascade_routing_policy"] == "missing"
    assert summary["component_status"]["migration_controller"] == "missing"
    assert summary["component_status"]["abstraction_distillation"] == "missing"


def test_v7_governance_summary_reports_required_and_optional_component_policy():
    snapshot = _healthy_snapshot()

    summary = summarize_v7_governance(snapshot)

    assert summary["required_component_count"] == 17
    assert summary["present_required_component_count"] == 0
    assert "confidence_router" in summary["missing_required_components"]
    assert "symbolic_offloader" not in summary["missing_required_components"]
    assert summary["optional_components"]["symbolic_offloader"]["status"] == "missing"
    assert summary["optional_components"]["symbolic_offloader"]["intentionally_absent"] is True
    assert summary["optional_components"]["symbolic_offloader"]["absence_reason"] == "optional_audit_level_default_disabled"
    assert summary["profile_expected_component_policy"] == "production"


def test_classify_snapshot_fails_live_profile_when_required_v7_component_missing():
    snapshot = _healthy_snapshot()
    snapshot["v7_governance"] = {"components": _v7_component_records(exclude={"confidence_router"})}

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(
        item["code"] == "v7_required_components_missing" and item["components"] == ["confidence_router"]
        for item in classification["fail"]
    )


def test_classify_snapshot_warns_clean_host_when_optional_v7_component_is_absent_with_reason():
    snapshot = _healthy_snapshot()
    snapshot["monitor_profile"] = "clean_host"
    snapshot["v7_governance"] = {"components": _v7_component_records(exclude={"symbolic_offloader"})}

    classification = classify_snapshot(snapshot)

    assert not any(item["code"] == "v7_required_components_missing" for item in classification["fail"])
    assert any(
        item["code"] == "clean_host_v7_optional_component_intentionally_absent"
        and item["component"] == "symbolic_offloader"
        and item["reason"] == "optional_audit_level_default_disabled"
        for item in classification["warn"]
    )


def test_v7_governance_summary_uses_total_memory_sources_feedback_when_window_empty():
    snapshot = _healthy_snapshot()
    snapshot["memory_sources"] = {
        "schema_version": "memory-os.memory_sources_stats.v0",
        "ledger_exists": True,
        "record_count": 0,
        "feedback_count": 0,
        "total_feedback_count": 2,
        "boundary_true_count": 0,
        "forbidden_field_findings": [],
    }

    summary = summarize_v7_governance(snapshot)

    assert summary["memory_sources_feedback_volume_ready"] is True
    assert summary["memory_sources_feedback_count"] == 2
    assert summary["memory_sources_feedback_canary_target"] == 20
    assert summary["memory_sources_feedback_canary_remaining"] == 18
    assert summary["memory_sources_feedback_canary_complete"] is False


def test_classify_snapshot_tracks_memory_sources_feedback_canary_without_blocking_shadow_live():
    snapshot = _healthy_snapshot()
    snapshot["memory_sources"] = {
        "schema_version": "memory-os.memory_sources_stats.v0",
        "ledger_exists": True,
        "record_count": 0,
        "feedback_count": 1,
        "total_feedback_count": 4,
        "boundary_true_count": 0,
        "forbidden_field_findings": [],
    }
    snapshot["module_artifacts"]["v7_meta"] = {
        "promotion_matrix_component": {
            "component": "promotion_matrix",
            "pipeline_liveness": "live-shadow",
            "autonomy_level": "none",
            "task_installed": True,
        }
    }

    classification = classify_snapshot(snapshot)

    assert any(
        item["code"] == "v7_memory_sources_feedback_canary_running"
        and item["feedback_count"] == 4
        and item["target"] == 20
        and item["remaining"] == 16
        for item in classification["pass"]
    )
    assert not any(item["code"] == "v7_memory_sources_feedback_volume_pending" for item in classification["warn"])


def test_v7_owner_signal_lane_promotes_only_retractable_label_miner_to_owner_approved_apply():
    snapshot = _healthy_snapshot()
    snapshot["memory_sources"] = {
        "schema_version": "memory-os.memory_sources_stats.v0",
        "ledger_exists": True,
        "record_count": 0,
        "feedback_count": 1,
        "total_feedback_count": 5,
        "boundary_true_count": 0,
        "forbidden_field_findings": [],
    }
    snapshot["module_artifacts"]["ground_truth_miner"] = {
        "status": "ok",
        "label_count": 0,
        "run_count": 1,
        "active_label_count": 0,
        "retracted_label_count": 0,
        "actual_execute": False,
        "score_live_applied": False,
        "route_live_applied": False,
    }

    summary = summarize_v7_governance(snapshot)
    classification = classify_snapshot(snapshot)
    label_miner = next(item for item in summary["components"] if item["component"] == "retractable_label_miner")
    other_acting = [
        item
        for item in summary["components"]
        if item["component"] != "retractable_label_miner" and item["autonomy_level"] in {"owner_approved_apply", "autonomous_acting"}
    ]

    assert summary["acting_component_count"] == 1
    assert summary["owner_signal_lane"] == "memory_sources_feedback"
    assert summary["owner_signal_owner_approved_apply_count"] == 5
    assert label_miner["autonomy_level"] == "owner_approved_apply"
    assert label_miner["owner_signal_lane"] == "memory_sources_feedback"
    assert label_miner["owner_approved_apply_count"] == 5
    assert other_acting == []
    assert any(
        item["code"] == "v7_owner_signal_owner_approved_apply_visible" and item["feedback_count"] == 5
        for item in classification["pass"]
    )
    assert not any(item["code"] == "v7_component_live_applied_without_acting_gate" for item in classification["fail"])


def test_v7_governance_summary_infers_wave1_live_shadow_from_module_artifacts():
    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"]["evidence"] = {
        "evidence_count": 4,
        "score_count": 4,
        "derived_evidence_profile_count": 4,
        "feature_score_live_applied": False,
        "maturity_live_applied": False,
    }
    snapshot["module_artifacts"]["v7_meta"] = {
        "promotion_matrix_component": {
            "component": "promotion_matrix",
            "task_installed": True,
            "pipeline_liveness": "live-shadow",
            "autonomy_level": "shadow",
            "live_guard_registered": True,
            "live_applied": False,
            "actual_execute": False,
        },
        "live_guard_registry_present": True,
        "eval_adapter_registry_present": True,
        "eval_adapter_count": 14,
    }
    snapshot["module_artifacts"]["imagination_loop"] = {
        "status": "ok",
        "scenario_count": 5,
        "simulated_count": 5,
        "actual_execute": False,
        "live_behavior_changed": False,
    }
    snapshot["module_artifacts"]["confabulation_detector"] = {
        "status": "ok",
        "flag_count": 1,
        "actual_execute": False,
        "score_live_applied": False,
        "route_live_applied": False,
    }
    snapshot["module_artifacts"]["ground_truth_miner"] = {
        "status": "ok",
        "label_count": 0,
        "run_count": 1,
        "active_label_count": 0,
        "retracted_label_count": 0,
        "actual_execute": False,
        "score_live_applied": False,
        "route_live_applied": False,
    }
    snapshot["module_artifacts"]["confidence_router"] = {
        "status": "ok",
        "route_count": 0,
        "run_count": 1,
        "band_distribution": {},
        "actual_execute": False,
        "score_live_applied": False,
        "route_live_applied": False,
    }
    snapshot["module_artifacts"]["judge_calibration"] = {
        "status": "ok",
        "run_count": 1,
        "calibration_live_applied": False,
        "actual_execute": False,
    }
    snapshot["module_artifacts"]["candidate_review"] = {
        "status": "ok",
        "decision_count": 3,
        "run_count": 1,
        "candidate_review_live_applied": False,
        "actual_execute": False,
    }
    snapshot["module_artifacts"]["shadow_recall"] = {
        "status": "ok",
        "fingerprint_count": 1,
        "run_count": 1,
        "auto_discard_live_applied": False,
        "actual_execute": False,
    }
    snapshot["module_artifacts"]["provisional"] = {
        "status": "ok",
        "record_count": 1,
        "run_count": 1,
        "auto_promote_live_applied": False,
        "actual_crystallized_approval": False,
        "actual_execute": False,
    }
    snapshot["module_artifacts"]["cascade_routing_policy"] = {
        "status": "ok",
        "proposal_count": 1,
        "route_strategy_live_applied": False,
        "actual_execute": False,
    }
    snapshot["module_artifacts"]["migration_controller"] = {
        "status": "ok",
        "run_count": 1,
        "last_regime": "cold_start",
        "migration_live_applied": False,
        "actual_execute": False,
    }
    snapshot["module_artifacts"]["symbolic_offloader"] = {
        "status": "ok",
        "report_count": 1,
        "ref_count": 1,
        "canonical_state_changed": False,
        "actual_execute": False,
    }
    snapshot["module_artifacts"]["abstraction_distillation"] = {
        "status": "ok",
        "item_count": 3,
        "distillation_live_applied": False,
        "actual_execute": False,
    }
    snapshot["module_artifacts"]["crystallized_revalidator"] = {
        "status": "ok",
        "flag_count": 0,
        "run_count": 1,
        "would_demote_count": 0,
        "actual_execute": False,
        "actual_crystallized_approval": False,
        "demotion_live_applied": False,
    }
    snapshot["module_artifacts"]["grounded_expression_judge"] = {
        "status": "ok",
        "verdict_count": 4,
        "verdict_distribution": {
            "grounded": 1,
            "confabulation": 1,
            "blind_spot": 1,
            "unresolvable": 1,
        },
        "unresolvable_count": 1,
        "left_map_substrate_warning_count": 0,
        "left_map_coverage_floor_met_count": 2,
        "latest_left_map_snapshot_version": "leftmap_abc123",
        "verdict_distribution_degenerate": False,
        "substrate_unavailable_blocker_cleared": True,
        "actual_send": False,
        "actual_execute": False,
        "actual_identity_write": False,
        "delivery_affected": False,
        "delivery_gated": False,
        "policy_live_applied": False,
    }

    summary = summarize_v7_governance(snapshot)
    classification = classify_snapshot(snapshot)

    assert summary["component_status"]["derived_evidence_profile"] == "live-shadow"
    assert summary["component_status"]["promotion_matrix"] == "live-shadow"
    assert summary["component_status"]["live_guard_registry"] == "live-shadow"
    assert summary["component_status"]["eval_adapter_registry"] == "live-shadow"
    assert summary["confidence_router_status"] == "live-shadow"
    assert summary["component_status"]["retractable_label_miner"] == "live-shadow"
    assert summary["component_status"]["judge_calibration"] == "live-shadow"
    assert summary["component_status"]["candidate_review"] == "live-shadow"
    assert summary["component_status"]["shadow_recall"] == "live-shadow"
    assert summary["component_status"]["provisional"] == "live-shadow"
    assert summary["component_status"]["cascade_routing_policy"] == "live-shadow"
    assert summary["component_status"]["migration_controller"] == "live-shadow"
    assert summary["component_status"]["symbolic_offloader"] == "live-shadow"
    assert summary["component_status"]["abstraction_distillation"] == "live-shadow"
    assert summary["simulation_coverage_status"] == "live-shadow"
    assert summary["confabulation_detection_status"] == "live-shadow"
    assert summary["crystallized_revalidator_status"] == "live-shadow"
    assert summary["cross_check_anchoring_status"] == "live-shadow"
    assert summary["shadow_live_component_count"] >= 18
    assert any(item["code"] == "v7_shadow_live_components_visible" for item in classification["pass"])
    assert any(item["code"] == "grounded_expression_verdict_distribution_visible" for item in classification["pass"])
    assert any(item["code"] == "grounded_expression_alternate_left_map_substrate_ready" for item in classification["pass"])


def test_classify_snapshot_fails_grounded_expression_if_delivery_affected():
    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"]["grounded_expression_judge"] = {
        "status": "ok",
        "verdict_count": 1,
        "verdict_distribution": {
            "grounded": 1,
            "confabulation": 0,
            "blind_spot": 0,
            "unresolvable": 0,
        },
        "left_map_coverage_floor_met_count": 1,
        "delivery_affected": True,
        "actual_send": False,
        "actual_execute": False,
        "actual_identity_write": False,
        "policy_live_applied": False,
    }

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "grounded_expression_delivery_affected_true" for item in classification["fail"])


def test_v7_governance_summary_uses_code_promotion_matrix_not_docs():
    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"]["v7_meta"] = {
        "promotion_matrix_component": {
            "component": "promotion_matrix",
            "task_installed": True,
            "pipeline_liveness": "live-shadow",
            "autonomy_level": "shadow",
            "live_guard_registered": True,
            "live_applied": False,
            "actual_execute": False,
        },
        "promotion_matrix_present": False,
    }

    summary = summarize_v7_governance(snapshot)

    assert summary["component_status"]["promotion_matrix"] == "live-shadow"
    assert summary["shadow_live_component_count"] == 1
    assert summary["live_guard_registered_count"] == 1


def test_classify_snapshot_accepts_v7_live_shadow_without_acting():
    snapshot = _healthy_snapshot()
    snapshot["v7_governance"] = {
        "schema_version": "memory-os.v7_governance_summary.v0",
        "components": [
            {
                "component": "live_guard_registry",
                "task_installed": True,
                "pipeline_liveness": "live-shadow",
                "autonomy_level": "shadow",
                "live_guard_registered": True,
                "live_applied": False,
                "actual_send": False,
                "actual_execute": False,
                "actual_identity_write": False,
                "actual_crystallized_approval": False,
            }
        ],
    }

    classification = classify_snapshot(snapshot)
    rendered = render_chinese_summary({**snapshot, "classification": classification})

    assert any(item["code"] == "v7_shadow_live_components_visible" for item in classification["pass"])
    assert not any(item["code"] == "v7_component_live_applied_without_acting_gate" for item in classification["fail"])
    assert "V7Governance" in rendered
    assert "shadow_live_component_count" in rendered


def test_l4_guard_summary_tracks_kill_switch_and_live_apply_findings():
    snapshot = _healthy_snapshot()
    snapshot["memory_os_config"] = {"l4": {"kill_switch_enabled": True}}
    snapshot["module_artifacts"]["evidence"] = {
        "feature_score_live_applied": True,
        "maturity_live_applied": False,
    }

    summary = summarize_l4_guard(snapshot)

    assert summary == {
        "schema_version": "memory-os.l4_guard_summary.v0",
        "kill_switch_enabled": True,
        "registered_component_count": 1,
        "live_applied_finding_count": 1,
    }


def test_classify_snapshot_fails_v7_live_apply_without_acting_gate():
    snapshot = _healthy_snapshot()
    snapshot["v7_governance"] = {
        "schema_version": "memory-os.v7_governance_summary.v0",
        "components": [
            {
                "component": "confidence_router",
                "task_installed": True,
                "pipeline_liveness": "live-shadow",
                "autonomy_level": "shadow",
                "live_guard_registered": True,
                "live_applied": True,
                "actual_send": False,
                "actual_execute": False,
                "actual_identity_write": False,
                "actual_crystallized_approval": False,
            }
        ],
    }

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(
        item["code"] == "v7_component_live_applied_without_acting_gate"
        and item["component"] == "confidence_router"
        for item in classification["fail"]
    )


def test_classify_snapshot_tracks_owner_review_status_and_illegal_crystallized_writes():
    snapshot = _healthy_snapshot()
    snapshot["owner_review"] = {
        "schema_version": "memory-os.owner_review_status.v0",
        "review_queue": {"pending_count": 3, "action_required_count": 2, "stale_count": 0},
        "owner_action_count": 4,
        "action_type_counts": {"approve_candidate": 1, "reject_candidate": 1},
        "duplicate_ignored_count": 0,
        "error_count": 0,
        "owner_approved_crystallized_write_count": 1,
        "unapproved_crystallized_write_count": 0,
        "digest_burden": {"owner_active_period": True},
        "feedback_backflow": {"feedback_action_count": 1},
    }

    classification = classify_snapshot(snapshot)
    rendered = render_chinese_summary({**snapshot, "classification": classification})

    assert any(item["code"] == "owner_review_status_ok" for item in classification["pass"])
    assert any(item["code"] == "owner_review_owner_approved_crystallized_write" for item in classification["pass"])
    assert "OwnerReview" in rendered
    assert "'owner_approved_crystallized': 1" in rendered

    snapshot["owner_review"]["unapproved_crystallized_write_count"] = 1
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_unapproved_crystallized_write" for item in classification["fail"])


def test_classify_snapshot_allows_owner_approved_crystallized_records():
    snapshot = _healthy_snapshot()
    snapshot["memory_status"]["counts"]["crystallized_records"] = 1
    snapshot["owner_review"] = {
        "schema_version": "memory-os.owner_review_status.v0",
        "review_queue": {"pending_count": 0, "action_required_count": 0, "stale_count": 0},
        "owner_action_count": 1,
        "action_type_counts": {"approve_candidate": 1},
        "duplicate_ignored_count": 0,
        "error_count": 0,
        "owner_approved_crystallized_write_count": 1,
        "unapproved_crystallized_write_count": 0,
        "digest_burden": {"owner_active_period": True},
    }

    classification = classify_snapshot(snapshot)

    assert not any(item["code"] == "unexpected_crystallized_records" for item in classification["fail"])
    assert any(item["code"] == "crystallized_records_present" for item in classification["pass"])
    assert any(item["code"] == "owner_review_owner_approved_crystallized_write" for item in classification["pass"])


def test_classify_snapshot_tracks_owner_review_channel_and_digest_preview_boundaries():
    snapshot = _healthy_snapshot()

    classification = classify_snapshot(snapshot)
    rendered = render_chinese_summary({**snapshot, "classification": classification})

    assert any(item["code"] == "owner_review_aging_ok" for item in classification["pass"])
    assert any(item["code"] == "owner_review_channel_resolver_ok" for item in classification["pass"])
    assert any(item["code"] == "owner_review_delivery_status_ok" for item in classification["pass"])
    assert any(item["code"] == "owner_review_delivery_gate_ok" for item in classification["pass"])
    assert any(item["code"] == "owner_review_digest_preview_ok" for item in classification["pass"])
    assert any(item["code"] == "owner_review_rendered_digest_ok" for item in classification["pass"])
    assert any(item["code"] == "owner_review_rendered_digest_response_header_ok" for item in classification["pass"])
    assert any(item["code"] == "owner_review_rendered_digest_overview_ok" for item in classification["pass"])
    assert any(item["code"] == "owner_review_agenda_digest_ok" for item in classification["pass"])
    assert any(item["code"] == "owner_review_reply_dry_run_ok" for item in classification["pass"])
    assert any(item["code"] == "owner_review_surface_ok" for item in classification["pass"])
    assert any(item["code"] == "owner_review_surface_expression_feedback_context_visible" for item in classification["pass"])
    assert any(
        item["code"] == "owner_review_surface_memory_sources_feedback_context_visible"
        for item in classification["pass"]
    )
    assert any(item["code"] == "owner_review_surface_agent_tool_contract_ok" for item in classification["pass"])
    assert "latest_memory_source_id" in rendered
    assert any(item["code"] == "owner_review_ingress_guard_token_only" for item in classification["pass"])
    assert any(item["code"] == "owner_review_proposal_followups_ok" for item in classification["pass"])
    assert any(item["code"] == "owner_review_cron_integration_status_ok" for item in classification["pass"])
    assert "OwnerReviewAging" in rendered
    assert "OwnerReviewChannel" in rendered
    assert "OwnerCronIntegration" in rendered
    assert "OwnerDeliveryGate" in rendered
    assert "OwnerDeliveryStatus" in rendered
    assert "OwnerDigestPreview" in rendered
    assert "OwnerAgendaDigest" in rendered
    assert "OwnerReviewSurface" in rendered

    snapshot["owner_review_digest_preview"]["will_send"] = True
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_digest_would_send_true" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_channel"]["raw_body_included"] = True
    snapshot["owner_review_digest_preview"]["raw_body_included"] = True
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_channel_raw_body_included" for item in classification["fail"])
    assert any(item["code"] == "owner_review_digest_raw_body_included" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_rendered_digest"]["text_has_internal_schema"] = True
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_rendered_digest_internal_schema_text" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_rendered_digest"]["text_has_transcript_marker"] = True
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_rendered_digest_transcript_marker" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_rendered_digest"]["text_char_count"] = 2401
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_rendered_digest_too_long" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_rendered_digest"]["response_header_present"] = False
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_rendered_digest_missing_response_header" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_rendered_digest"]["overview_present"] = False
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_rendered_digest_missing_overview" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_rendered_digest"]["speak_item_count"] = 2
    snapshot["owner_review_rendered_digest"]["speak_expression_preview_count"] = 1
    snapshot["owner_review_rendered_digest"]["speak_expression_preview_missing_count"] = 1
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "WARN"
    assert any(item["code"] == "right_brain_review_speak_preview_missing" for item in classification["warn"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_agenda_digest"]["review_suggested_suppressed"] = False
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_agenda_digest_review_suggested_not_suppressed" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_agenda_digest"]["backlog_totals_suppressed"] = False
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_agenda_digest_backlog_totals_visible" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_reply_dry_run"]["dry_run"] = False
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_reply_dry_run_mutated_state" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_reply_dry_run"]["status"] = "needs_clarification"
    snapshot["owner_review_reply_dry_run"]["owner_action_dry_run"] = None
    classification = classify_snapshot(snapshot)

    assert not any(item["code"] == "owner_review_reply_owner_action_not_dry_run" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_surface"]["raw_body_included_count"] = 1
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_surface_raw_body_included" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_surface"]["boundary_true_count"] = 1
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_surface_boundary_true" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_surface"]["forbidden_owner_command_field_count"] = 1
    snapshot["owner_review_surface"]["forbidden_owner_command_fields"] = ["operator_cli"]
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_surface_forbidden_command_fields" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_ingress_guard"]["legacy_anchor_accepted"] = True
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_legacy_anchor_accepted" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_ingress_guard"]["token_command_accepted"] = False
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_token_command_not_accepted" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_ingress_guard"]["owner_command_event_count"] = 1
    snapshot["owner_review_ingress_guard"]["owner_command_working_count"] = 1
    snapshot["owner_review_ingress_guard"]["owner_command_candidate_count"] = 1
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_command_captured_as_event" for item in classification["fail"])
    assert any(item["code"] == "owner_review_command_promoted_to_working" for item in classification["fail"])
    assert any(item["code"] == "owner_review_command_promoted_to_candidate" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_ingress_guard"]["review_reply_tool_input_mode"] = "reply_fallback"
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_agent_tool_not_structured" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_ingress_guard"]["reply_fallback_used_count"] = 1
    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "owner_review_reply_fallback_used" for item in classification["warn"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_ingress_guard"]["owner_review_command_pollution_count"] = 1
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_command_pollution_count_nonzero" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_proposal_followups"]["boundary"]["actual_execute"] = True
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_proposal_followups_actual_execute_true" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_proposal_followups"]["actual_execute"] = True
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_proposal_followups_actual_execute_true" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_proposal_followups"]["items"] = [{"actual_execute": True}]
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_proposal_followups_item_actual_execute_true" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_proposal_followups"]["items"] = [{"execution_ticket_created": True}]
    classification = classify_snapshot(snapshot)

    assert not any(item["code"] == "owner_review_proposal_followups_item_execution_ticket_created" for item in classification["fail"])
    assert any(item["code"] == "owner_review_proposal_followups_ok" for item in classification["pass"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_proposal_followups"]["execution_ticket_count"] = 4
    snapshot["owner_review_proposal_followups"]["ticket_created_count"] = 4
    snapshot["owner_review_proposal_followups"]["awaiting_typed_execution_plan_count"] = 3
    snapshot["owner_review_proposal_followups"]["evidence_resolved_count"] = 1
    classification = classify_snapshot(snapshot)

    assert not classification["fail"]
    assert any(item["code"] == "owner_review_proposal_followups_execution_tickets_visible" for item in classification["pass"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_proposal_followups"]["pending_followup_count"] = 1
    snapshot["owner_review_proposal_followups"]["awaiting_ops_gate_count"] = 1
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "WARN"
    assert any(item["code"] == "owner_review_approved_proposals_pending_followup" for item in classification["warn"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_proposal_followups"]["pending_followup_count"] = 0
    snapshot["owner_review_proposal_followups"]["open_followup_count"] = 2
    snapshot["owner_review_proposal_followups"]["awaiting_ops_gate_count"] = 0
    snapshot["owner_review_proposal_followups"]["ops_gate_reviewed_count"] = 2
    snapshot["owner_review_proposal_followups"]["awaiting_explicit_execution_count"] = 2
    classification = classify_snapshot(snapshot)

    assert not any(item["code"] == "owner_review_approved_proposals_pending_followup" for item in classification["warn"])

    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"]["ops_gate"]["duplicate_proposal_followup_count"] = 1
    snapshot["module_artifacts"]["ops_gate"]["duplicate_proposal_followup_extra_count"] = 1
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "ops_gate_duplicate_proposal_followup_report" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"]["proposal_queue"]["legacy_template_cleanup_apply_count"] = 1
    snapshot["module_artifacts"]["proposal_queue"]["legacy_template_cleanup_closed_count"] = 2
    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "proposal_queue_legacy_template_cleanup_visible" for item in classification["pass"])

    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"]["proposal_queue"]["legacy_template_cleanup_actual_execute_count"] = 1
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "proposal_queue_legacy_template_cleanup_actual_execute_true" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"]["proposal_queue"]["legacy_template_cleanup_non_legacy_touched_count"] = 1
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "proposal_queue_legacy_template_cleanup_non_legacy_touched" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_delivery_gate"]["boundary"]["actual_send"] = True
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_delivery_gate_actual_send_true" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_delivery_gate"]["status"] = "ready"
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "WARN"
    assert any(item["code"] == "owner_review_delivery_gate_ready_for_review" for item in classification["warn"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_delivery_status"]["unapproved_send_count"] = 1
    snapshot["owner_review_delivery_status"]["raw_body_included_count"] = 1
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_unapproved_send" for item in classification["fail"])
    assert any(item["code"] == "owner_review_delivery_raw_body_included" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_cron_integration"]["enabled"] = True
    snapshot["owner_review_cron_integration"]["helper_script_present"] = False
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_cron_helper_missing" for item in classification["fail"])


def test_classify_snapshot_fails_when_owner_review_aging_mutates_state_or_body():
    snapshot = _healthy_snapshot()
    snapshot["owner_review_aging"]["canonical_state_changed"] = True
    snapshot["owner_review_aging"]["owner_action_created"] = True
    snapshot["owner_review_aging"]["raw_body_included"] = True

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_aging_canonical_state_changed_true" for item in classification["fail"])
    assert any(item["code"] == "owner_review_aging_owner_action_created_true" for item in classification["fail"])
    assert any(item["code"] == "owner_review_aging_raw_body_included_true" for item in classification["fail"])


def test_classify_snapshot_passes_module_artifact_summary_and_fails_on_actual_send():
    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"] = {
        "schema_version": "memory-os.module_artifact_summary.v0",
        "status": "ok",
        "digest": {"daily_artifact_count": 2, "weekly_artifact_count": 1},
        "wandering": {"output_count": 10, "would_send_count": 10},
        "evidence": {"score_count": 545, "subject_counts": {"candidate": 158}},
        "proposal_queue": {"candidate_count": 14, "state_counts": {"candidate": 13}},
        "self_evolution": {"report_count": 11, "proposal_count": 11, "last_status": "ok"},
        "governance_feedback": {"emitted_event_count": 57},
        "deep_reflection": {"report_count": 17, "current_injection_exists": True},
        "ops_gate": {
            "report_count": 22,
            "blocked_decision_count": 0,
            "run_report_count": 23,
            "skipped_run_count": 1,
            "latest_cadence_skipped": True,
            "latest_skip_reason": "no_pending_proposed_actions",
        },
        "speak_gate": {"would_send_count": 0, "actual_send": False},
    }

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "module_artifact_summary_ok" for item in classification["pass"])
    assert any(item["code"] == "ops_gate_no_pending_skip_visible" for item in classification["pass"])

    snapshot["module_artifacts"]["speak_gate"]["actual_send"] = True
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "module_artifact_speak_gate_actual_send_true" for item in classification["fail"])


def test_classify_snapshot_tracks_expression_feedback_and_left_brain_pipeline():
    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"]["evidence"] = {
        "expression_feedback_subject_count": 3,
        "expression_feedback_linked_subject_count": 1,
        "expression_feedback_unlinked_subject_count": 2,
        "expired_used_in_scoring_count": 0,
    }

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "left_brain_pipeline_check_visible" for item in classification["pass"])
    assert any(item["code"] == "expression_feedback_report_only" for item in classification["pass"])
    assert any(item["code"] == "left_brain_expression_feedback_context_linked" for item in classification["pass"])
    assert any(item["code"] == "left_brain_feedback_proposal_quality_ready" for item in classification["pass"])

    snapshot["module_artifacts"]["left_brain_pipeline_check"]["memory_sources_policy_quality_ready_count"] = 1
    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "left_brain_memory_sources_policy_quality_ready" for item in classification["pass"])

    snapshot["module_artifacts"]["left_brain_pipeline_check"]["status"] = "fail"
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "left_brain_pipeline_check_failed" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"]["expression_feedback"]["live_policy_changed_count"] = 1
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "expression_feedback_live_policy_changed" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"]["left_brain_pipeline_check"]["expression_policy_quality_ready_count"] = 0
    snapshot["module_artifacts"]["left_brain_pipeline_check"]["expression_policy_quality_blocked_count"] = 1
    snapshot["module_artifacts"]["left_brain_pipeline_check"]["proposal_quality_missing_count"] = 1
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "WARN"
    assert any(item["code"] == "left_brain_feedback_proposal_quality_blocked" for item in classification["warn"])
    assert any(item["code"] == "left_brain_proposal_quality_metadata_missing" for item in classification["warn"])

    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"]["left_brain_pipeline_check"]["memory_sources_policy_quality_blocked_count"] = 1
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "WARN"
    assert any(item["code"] == "left_brain_memory_sources_policy_quality_blocked" for item in classification["warn"])

    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"]["left_brain_pipeline_check"]["agenda_trace_missing_count"] = 1
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "WARN"
    assert any(item["code"] == "left_brain_proposal_agenda_trace_missing" for item in classification["warn"])

    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"]["evidence"] = {
        "expression_feedback_subject_count": 2,
        "expression_feedback_linked_subject_count": 0,
        "expression_feedback_unlinked_subject_count": 2,
        "expired_used_in_scoring_count": 0,
    }
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "WARN"
    assert any(item["code"] == "left_brain_expression_feedback_unlinked_only" for item in classification["warn"])


def test_classify_snapshot_warns_when_expired_working_is_scored():
    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"] = {
        "schema_version": "memory-os.module_artifact_summary.v0",
        "status": "ok",
        "speak_gate": {"would_send_count": 0, "actual_send": False},
        "evidence": {"expired_used_in_scoring_count": 3},
    }

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "WARN"
    assert any(item["code"] == "left_brain_expired_working_used_in_scoring" for item in classification["warn"])


def test_classify_snapshot_tracks_deep_reflection_expired_working_hygiene():
    snapshot = _healthy_snapshot()
    snapshot["deep_reflection"]["latest_active_working_input_count"] = 3
    snapshot["deep_reflection"]["latest_expired_working_skipped_count"] = 12
    snapshot["deep_reflection"]["latest_expired_working_used_in_analysis_count"] = 0
    snapshot["deep_reflection"]["cadence_skipped_count"] = 1
    snapshot["deep_reflection"]["latest_skip_reason"] = "unchanged_input_fingerprint"

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "deep_reflection_expired_working_not_used" for item in classification["pass"])
    assert any(item["code"] == "deep_reflection_cadence_skip_visible" for item in classification["pass"])

    snapshot["deep_reflection"]["latest_expired_working_used_in_analysis_count"] = 2
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "WARN"
    assert any(item["code"] == "deep_reflection_expired_working_used_in_analysis" for item in classification["warn"])


def test_classify_snapshot_tracks_deep_reflection_bounded_policy():
    snapshot = _healthy_snapshot()
    snapshot["deep_reflection"]["policy_present"] = True
    snapshot["deep_reflection"]["policy_version"] = 2
    snapshot["deep_reflection"]["policy_apply_count"] = 2
    snapshot["deep_reflection"]["policy_live_applied"] = False
    snapshot["deep_reflection"]["policy_actual_execute_count"] = 0
    snapshot["deep_reflection"]["policy_raw_body_included_count"] = 0

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "deep_reflection_bounded_policy_visible" for item in classification["pass"])

    snapshot["deep_reflection"]["policy_actual_execute_count"] = 1
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "deep_reflection_policy_actual_execute_true" for item in classification["fail"])


def test_classify_snapshot_tracks_primary_feature_scoring_and_legacy_comparison():
    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"]["evidence"] = {
        "evidence_count": 4,
        "score_count": 4,
        "score_mode": "feature_maturity_v2",
        "subject_counts": {"event": 1, "working": 1, "proposal": 1, "crystallized_candidate": 1},
        "working_subject_count": 1,
        "expired_used_in_scoring_count": 0,
        "feature_score_mode": "primary",
        "feature_score_count": 4,
        "hash_score_legacy_count": 0,
        "legacy_hash_comparison_count": 4,
        "comparison_count": 4,
        "feature_score_live_applied": False,
        "owner_feedback_signal_count": 0,
        "expression_feedback_subject_count": 0,
        "run_report_count": 2,
        "skipped_run_count": 1,
        "latest_cadence_skipped": True,
        "latest_skip_reason": "unchanged_input_fingerprint",
    }

    classification = classify_snapshot(snapshot)
    rendered = render_chinese_summary({**snapshot, "classification": classification})

    assert any(item["code"] == "left_brain_feature_scoring_primary_ok" for item in classification["pass"])
    assert any(item["code"] == "evidence_scoring_cadence_skip_visible" for item in classification["pass"])
    assert "feature_score_count" in rendered
    assert "legacy_hash_comparison_count" in rendered
    assert "skipped_run_count" in rendered

    snapshot["module_artifacts"]["evidence"]["hash_score_legacy_count"] = 4
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "left_brain_legacy_hash_scores_still_primary" for item in classification["fail"])


def test_classify_snapshot_tracks_prototype_aligned_maturity_scoring_primary():
    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"]["evidence"] = {
        "evidence_count": 4,
        "score_count": 4,
        "expired_used_in_scoring_count": 0,
        "score_mode": "feature_maturity_v2",
        "feature_score_mode": "primary",
        "feature_score_count": 4,
        "hash_score_legacy_count": 0,
        "legacy_hash_comparison_count": 4,
        "comparison_count": 4,
        "feature_score_live_applied": False,
        "prototype_aligned_score_count": 4,
        "maturity_dimension_count": 9,
        "maturity_dimension_keys": [
            "actionability",
            "duplicate_backlog",
            "evidence_strength",
            "freshness_decay",
            "gate_state",
            "owner_feedback",
            "recurrence",
            "risk",
            "source_diversity",
        ],
        "maturity_live_applied": False,
    }

    classification = classify_snapshot(snapshot)
    rendered = render_chinese_summary({**snapshot, "classification": classification})

    assert any(item["code"] == "left_brain_maturity_scoring_primary_ok" for item in classification["pass"])
    assert "prototype_aligned_score_count" in rendered
    assert "maturity_dimension_count" in rendered

    snapshot["module_artifacts"]["evidence"]["maturity_live_applied"] = True
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "left_brain_maturity_scoring_live_applied" for item in classification["fail"])


def test_classify_snapshot_tracks_right_brain_expression_adapter_requests():
    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"]["right_brain_expression_adapter"] = {
        "request_count": 2,
        "latest_channel": "origin",
        "latest_delivery_mode": "hermes_cron_agent",
        "latest_actual_send": False,
        "raw_body_included_count": 0,
        "silent_request_count": 0,
        "outcome_count": 0,
        "outcome_actual_send_count": 0,
        "outcome_actual_execute_count": 0,
        "outcome_raw_body_included_count": 0,
        "outcome_internal_marker_count": 0,
    }
    snapshot["expression_artifacts"]["right_brain_adapter_request_count"] = 2
    snapshot["expression_artifacts"]["right_brain_adapter_latest_channel"] = "origin"
    snapshot["expression_artifacts"]["right_brain_adapter_latest_delivery_mode"] = "hermes_cron_agent"
    snapshot["expression_artifacts"]["right_brain_adapter_raw_body_included_count"] = 0

    classification = classify_snapshot(snapshot)
    rendered = render_chinese_summary({**snapshot, "classification": classification})

    assert any(item["code"] == "right_brain_expression_adapter_visible" for item in classification["pass"])
    assert any(item["code"] == "right_brain_expression_outcome_missing" for item in classification["warn"])
    assert "right_brain_adapter_request_count" in rendered

    snapshot["module_artifacts"]["right_brain_expression_adapter"]["latest_actual_send"] = True
    snapshot["expression_artifacts"]["right_brain_adapter_latest_actual_send"] = True
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "right_brain_expression_adapter_actual_send_true" for item in classification["fail"])


def test_classify_snapshot_tracks_right_brain_expression_outcomes():
    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"]["right_brain_expression_adapter"] = {
        "request_count": 2,
        "latest_channel": "origin",
        "latest_delivery_mode": "hermes_cron_agent",
        "latest_actual_send": False,
        "raw_body_included_count": 0,
        "silent_request_count": 0,
        "outcome_count": 1,
        "latest_outcome_id": "rbout_123",
        "latest_outcome_request_id": "rbexpr_123",
        "latest_outcome_policy_version": 1,
        "latest_outcome_silent": False,
        "latest_outcome_preview_chars": 38,
        "outcome_actual_send_count": 0,
        "outcome_actual_execute_count": 0,
        "outcome_raw_body_included_count": 0,
        "outcome_internal_marker_count": 0,
        "outcome_feedback_count": 1,
        "latest_outcome_feedback_count": 1,
        "outcome_feedback_missing_count": 0,
    }
    snapshot["module_artifacts"]["expression_feedback"] = {
        "feedback_count": 1,
        "live_policy_changed_count": 0,
        "raw_body_included_count": 0,
        "linked_outcome_count": 1,
        "unlinked_count": 0,
        "linked_outcome_missing_count": 0,
    }
    snapshot["expression_artifacts"]["right_brain_adapter_request_count"] = 2
    snapshot["expression_artifacts"]["right_brain_adapter_outcome_count"] = 1
    snapshot["expression_artifacts"]["right_brain_adapter_latest_outcome_silent"] = False
    snapshot["expression_artifacts"]["right_brain_adapter_latest_outcome_policy_version"] = 1
    snapshot["expression_artifacts"]["right_brain_adapter_outcome_internal_marker_count"] = 0
    snapshot["expression_artifacts"]["right_brain_adapter_outcome_feedback_count"] = 1
    snapshot["expression_artifacts"]["right_brain_adapter_latest_outcome_feedback_count"] = 1
    snapshot["expression_artifacts"]["expression_feedback_linked_outcome_count"] = 1

    classification = classify_snapshot(snapshot)
    rendered = render_chinese_summary({**snapshot, "classification": classification})

    assert not any(item["code"] == "right_brain_expression_outcome_missing" for item in classification["warn"])
    assert any(item["code"] == "right_brain_expression_outcome_recorded" for item in classification["pass"])
    assert any(item["code"] == "right_brain_expression_feedback_linked" for item in classification["pass"])
    assert "right_brain_adapter_outcome_count" in rendered
    assert "right_brain_adapter_outcome_feedback_count" in rendered

    snapshot["module_artifacts"]["right_brain_expression_adapter"]["outcome_internal_marker_count"] = 1
    snapshot["expression_artifacts"]["right_brain_adapter_outcome_internal_marker_count"] = 1
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "right_brain_expression_outcome_internal_marker" for item in classification["fail"])


def test_classify_snapshot_fails_when_expression_feedback_links_missing_outcome():
    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"]["right_brain_expression_adapter"]["outcome_count"] = 1
    snapshot["module_artifacts"]["right_brain_expression_adapter"]["outcome_feedback_missing_count"] = 1
    snapshot["module_artifacts"]["expression_feedback"] = {
        "feedback_count": 1,
        "live_policy_changed_count": 0,
        "raw_body_included_count": 0,
        "linked_outcome_count": 1,
        "unlinked_count": 0,
        "linked_outcome_missing_count": 1,
    }

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "right_brain_expression_feedback_missing_outcome" for item in classification["fail"])


def test_classify_snapshot_warns_when_right_brain_reaction_volume_is_thin():
    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"]["right_brain_expression_adapter"] = {
        "request_count": 2,
        "latest_actual_send": False,
        "raw_body_included_count": 0,
        "policy_actual_execute_count": 0,
        "policy_raw_body_included_count": 0,
        "outcome_count": 2,
        "outcome_actual_send_count": 0,
        "outcome_actual_execute_count": 0,
        "outcome_raw_body_included_count": 0,
        "outcome_internal_marker_count": 0,
        "outcome_feedback_count": 1,
        "outcome_feedback_missing_count": 0,
        "latest_outcome_feedback_count": 1,
    }

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "WARN"
    assert any(item["code"] == "right_brain_expression_reaction_volume_thin" for item in classification["warn"])


def test_classify_snapshot_passes_when_right_brain_reaction_volume_is_sufficient():
    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"]["right_brain_expression_adapter"] = {
        "request_count": 3,
        "latest_actual_send": False,
        "raw_body_included_count": 0,
        "policy_actual_execute_count": 0,
        "policy_raw_body_included_count": 0,
        "outcome_count": 3,
        "outcome_actual_send_count": 0,
        "outcome_actual_execute_count": 0,
        "outcome_raw_body_included_count": 0,
        "outcome_internal_marker_count": 0,
        "outcome_feedback_count": 3,
        "outcome_feedback_missing_count": 0,
        "latest_outcome_feedback_count": 1,
    }

    classification = classify_snapshot(snapshot)

    assert any(
        item["code"] == "right_brain_expression_reaction_volume_sufficient" for item in classification["pass"]
    )
    assert not any(item["code"] == "right_brain_expression_reaction_volume_thin" for item in classification["warn"])


def test_classify_snapshot_tracks_module_cadence_report():
    snapshot = _healthy_snapshot()
    snapshot["module_cadence"] = {
        "schema_version": "memory-os.module_cadence_monitor_summary.v0",
        "report_count": 1,
        "latest_report_id": "cadence_123",
        "latest_status": "warning",
        "module_count": 18,
        "cron_job_count": 2,
        "cognitive_loop_report_count": 30,
        "integration_harness_member_count": 11,
        "split_recommended_count": 10,
        "expected_hermes_cron_missing_count": 0,
        "finding_count": 10,
        "generated_count": 17,
        "skipped_count": 3,
        "error_count": 1,
        "duplicate_count": 2,
        "counter_coverage_count": 18,
        "module_counters": {
            "self_evolution": {
                "run_count": 2,
                "generated_count": 1,
                "skipped_count": 1,
                "error_count": 0,
                "duplicate_count": 1,
                "last_run_at": "2026-05-26T02:00:00+00:00",
                "last_status": "ok",
            }
        },
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
            "cron_modified": False,
        },
    }

    classification = classify_snapshot(snapshot)
    rendered = render_chinese_summary({**snapshot, "classification": classification})

    assert any(item["code"] == "module_cadence_report_visible" for item in classification["pass"])
    assert any(item["code"] == "module_cadence_split_pending" for item in classification["warn"])
    assert "ModuleCadence" in rendered
    assert snapshot["module_cadence"]["module_counters"]["self_evolution"]["duplicate_count"] == 1

    snapshot["module_cadence"]["finding_count"] = 0
    snapshot["module_cadence"]["latest_status"] = "ok"
    classification = classify_snapshot(snapshot)

    assert not any(item["code"] == "module_cadence_split_pending" for item in classification["warn"])

    snapshot["module_cadence"]["finding_count"] = 10
    snapshot["module_cadence"]["boundary"]["cron_modified"] = True
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "module_cadence_boundary_true" for item in classification["fail"])


def test_module_cadence_summary_exposes_generated_skipped_error_duplicate_counters(monkeypatch):
    report = {
        "schema_version": "memory-os.module_cadence_report.v0",
        "report_id": "cadence_123",
        "status": "warning",
        "module_count": 18,
        "cron_job_count": 2,
        "cognitive_loop_report_count": 30,
        "integration_harness_member_count": 11,
        "split_recommended_count": 10,
        "expected_hermes_cron_missing_count": 0,
        "finding_count": 10,
        "generated_count": 17,
        "skipped_count": 3,
        "error_count": 1,
        "duplicate_count": 2,
        "counter_coverage_count": 18,
        "modules": [
            {
                "module": "self_evolution",
                "cadence_counters": {
                    "run_count": 2,
                    "generated_count": 1,
                    "skipped_count": 1,
                    "error_count": 0,
                    "duplicate_count": 1,
                    "last_run_at": "2026-05-26T02:00:00+00:00",
                    "last_status": "ok",
                },
            }
        ],
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
            "cron_modified": False,
        },
    }
    namespace: dict[str, object] = {}
    _exec_remote_probe_prefix(namespace)
    monkeypatch.setitem(namespace, "_read_jsonl", lambda path: [report])

    summary = namespace["module_cadence_summary"]()

    assert summary["generated_count"] == 17
    assert summary["skipped_count"] == 3
    assert summary["error_count"] == 1
    assert summary["duplicate_count"] == 2
    assert summary["counter_coverage_count"] == 18
    assert summary["module_counters"]["self_evolution"]["duplicate_count"] == 1


def test_classify_snapshot_warns_when_session_activity_has_no_hook_marker_delta():
    snapshot = _healthy_snapshot()
    snapshot["session_activity"] = {"total_session_events": 12}
    snapshot["hook_markers"] = {"started": 5, "reset": 4, "finalized": 4, "total": 13}
    snapshot["deltas"] = {
        "session_activity_delta": {"total_session_events": 2},
        "hook_marker_delta": {"started": 0, "reset": 0, "finalized": 0, "total": 0},
    }

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "WARN"
    assert any(item["code"] == "hook_markers_missing_for_session_activity" for item in classification["warn"])


def test_classify_snapshot_passes_hook_coverage_when_no_session_activity_delta():
    snapshot = _healthy_snapshot()
    snapshot["session_activity"] = {"total_session_events": 12}
    snapshot["hook_markers"] = {"started": 5, "reset": 4, "finalized": 4, "total": 13}
    snapshot["deltas"] = {
        "session_activity_delta": {"total_session_events": 0},
        "hook_marker_delta": {"started": 0, "reset": 0, "finalized": 0, "total": 0},
    }

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "hook_coverage_no_session_activity" for item in classification["pass"])
    assert not any(item["code"] == "hook_markers_missing_for_session_activity" for item in classification["warn"])


def test_classify_snapshot_tracks_session_mirror_pending_as_observation():
    snapshot = _healthy_snapshot()
    snapshot["session_mirror"] = {
        "schema_version": "memory-os.session_mirror_monitor_summary.v0",
        "status": "ok",
        "session_count": 54,
        "covered_session_count": 29,
        "pending_session_count": 25,
        "dry_run_status": "ok",
        "dry_run_new_event_count": 25,
        "dry_run_written_event_ids_count": 0,
        "dry_run_findings_count": 0,
        "correlation_status": "ok",
        "pending_only_group_count": 0,
        "pending_only_groups": [],
        "raw_private_body_printed": False,
    }

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "session_mirror_dry_run_ok" for item in classification["pass"])
    assert any(item["code"] == "session_mirror_pending_no_correlated_gap" for item in classification["pass"])
    assert not any(item["code"] == "session_mirror_pending_sessions" for item in classification["warn"])
    assert not any(item["code"].startswith("session_mirror_") for item in classification["fail"])


def test_classify_snapshot_warns_when_session_mirror_pending_only_groups_exist():
    snapshot = _healthy_snapshot()
    snapshot["session_mirror"] = {
        "schema_version": "memory-os.session_mirror_monitor_summary.v0",
        "status": "ok",
        "session_count": 54,
        "covered_session_count": 29,
        "pending_session_count": 25,
        "dry_run_status": "ok",
        "dry_run_new_event_count": 25,
        "dry_run_written_event_ids_count": 0,
        "dry_run_findings_count": 0,
        "correlation_status": "ok",
        "pending_only_group_count": 1,
        "pending_only_groups": ["new_owner_topic"],
        "raw_private_body_printed": False,
    }

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "session_mirror_pending_source_gap" for item in classification["warn"])
    assert not any(item["code"] == "session_mirror_pending_sessions" for item in classification["warn"])


def test_classify_snapshot_fails_when_session_mirror_dry_run_writes_or_has_findings():
    snapshot = _healthy_snapshot()
    snapshot["session_mirror"] = {
        "schema_version": "memory-os.session_mirror_monitor_summary.v0",
        "status": "ok",
        "session_count": 54,
        "covered_session_count": 29,
        "pending_session_count": 25,
        "dry_run_status": "ok",
        "dry_run_new_event_count": 25,
        "dry_run_written_event_ids_count": 1,
        "dry_run_findings_count": 2,
    }

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "session_mirror_dry_run_wrote_events" for item in classification["fail"])
    assert any(item["code"] == "session_mirror_dry_run_findings" for item in classification["fail"])


def test_compact_rh31_eval_summary_strips_scores_from_monitor_snapshot():
    summary = {
        "schema_version": "memory-os.rh31_summary.v0",
        "status": "warning",
        "adapter_count": 6,
        "case_count": 6,
        "score_count": 27,
        "failure_count": 4,
        "failure_class_distribution": {"projection_miss": 1},
        "boundary_true_count": 0,
        "forbidden_field_count": 0,
        "report_dir": "",
        "scores": [
            {
                "adapter": "memory_os_fts",
                "case_id": "private_case",
                "status": "fail",
                "failure_class": "fts_miss",
                "metric_scope": "context",
                "live_behavior_changed": False,
                "details": {"raw": "should not be retained"},
            }
        ],
        "source_distribution": {"working": 8},
    }

    compact = monitor.compact_rh31_eval_summary(summary)

    assert compact == {
        "schema_version": "memory-os.rh31_summary.v0",
        "status": "warning",
        "adapter_count": 6,
        "case_count": 6,
        "score_count": 27,
        "failure_count": 4,
        "failure_class_distribution": {"projection_miss": 1},
        "failure_attribution": [
            {
                "adapter": "memory_os_fts",
                "case_id": "private_case",
                "failure_class": "fts_miss",
                "metric_scope": "context",
                "live_behavior_changed": False,
                "guard_decision": "measurement_only",
            }
        ],
        "live_guard_candidate_count": 0,
        "measurement_signal_count": 1,
        "boundary_true_count": 0,
        "forbidden_field_count": 0,
        "report_written": False,
        "source_distribution": {"working": 8},
    }


def test_compact_rh31_eval_summary_surfaces_retrieval_shadow_without_raw_details():
    summary = {
        "schema_version": "memory-os.rh31_summary.v0",
        "status": "pass",
        "adapter_count": 1,
        "case_count": 1,
        "score_count": 1,
        "failure_count": 0,
        "failure_class_distribution": {},
        "boundary_true_count": 0,
        "forbidden_field_count": 0,
        "report_dir": "",
        "scores": [
            {
                "adapter": "retrieval_shadow",
                "case_id": "retrieval_shadow_summary",
                "status": "pass",
                "metric_scope": "retrieval_shadow",
                "details": {
                    "schema_version": "memory-os.retrieval_shadow_eval.v0",
                    "run_count": 1,
                    "semantic_gap_count": 2,
                    "hybrid_would_retrieve_count": 3,
                    "rrf_would_rank_count": 2,
                    "live_input_available": True,
                    "live_memory_sources_record_count": 4,
                    "live_bounded_source_ref_count": 3,
                    "live_shadow_source_selection_miss_count": 1,
                    "live_shadow_diversification_gap_count": 2,
                    "live_shadow_low_coverage_count": 1,
                    "live_shadow_would_rank_count": 4,
                    "live_route_distribution": {"personal_recall": 4},
                    "live_selected_source_class_distribution": {"event": 3},
                    "live_dropped_source_class_distribution": {"candidate": 2},
                    "live_route_live_applied": False,
                    "live_score_live_applied": False,
                    "live_canonical_state_changed": False,
                    "route_live_applied": False,
                    "score_live_applied": False,
                    "boundary_true_count": 0,
                    "forbidden_field_count": 0,
                    "raw": "should not be retained",
                },
            }
        ],
    }

    compact = monitor.compact_rh31_eval_summary(summary)

    assert compact["retrieval_shadow"] == {
        "run_count": 1,
        "semantic_gap_count": 2,
        "hybrid_would_retrieve_count": 3,
        "rrf_would_rank_count": 2,
        "live_input_available": True,
        "live_memory_sources_record_count": 4,
        "live_bounded_source_ref_count": 3,
        "live_shadow_source_selection_miss_count": 1,
        "live_shadow_diversification_gap_count": 2,
        "live_shadow_low_coverage_count": 1,
        "live_shadow_would_rank_count": 4,
        "live_route_distribution": {"personal_recall": 4},
        "live_selected_source_class_distribution": {"event": 3},
        "live_dropped_source_class_distribution": {"candidate": 2},
        "live_route_live_applied": False,
        "live_score_live_applied": False,
        "live_canonical_state_changed": False,
        "route_live_applied": False,
        "score_live_applied": False,
        "boundary_true_count": 0,
        "forbidden_field_count": 0,
    }
    assert "should not be retained" not in json.dumps(compact)


def test_classify_snapshot_tracks_retrieval_shadow_report_only_fields():
    snapshot = _healthy_snapshot()
    snapshot["rh31_eval"] = {
        "schema_version": "memory-os.rh31_summary.v0",
        "status": "pass",
        "boundary_true_count": 0,
        "forbidden_field_count": 0,
        "adapter_count": 7,
        "failure_count": 0,
        "measurement_signal_count": 0,
        "live_guard_candidate_count": 0,
        "failure_class_distribution": {},
        "retrieval_shadow": {
            "run_count": 1,
            "semantic_gap_count": 1,
            "hybrid_would_retrieve_count": 1,
            "rrf_would_rank_count": 1,
            "live_input_available": True,
            "live_memory_sources_record_count": 4,
            "live_bounded_source_ref_count": 2,
            "live_shadow_source_selection_miss_count": 1,
            "live_shadow_diversification_gap_count": 1,
            "live_shadow_low_coverage_count": 1,
            "live_shadow_would_rank_count": 4,
            "route_live_applied": False,
            "score_live_applied": False,
            "live_route_live_applied": False,
            "live_score_live_applied": False,
            "live_canonical_state_changed": False,
            "boundary_true_count": 0,
            "forbidden_field_count": 0,
        },
    }

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "retrieval_shadow_visible" for item in classification["pass"])
    assert any(item["code"] == "retrieval_shadow_live_memory_sources_visible" for item in classification["pass"])
    assert any(item["code"] == "retrieval_shadow_live_memory_sources_gap_visible" for item in classification["pass"])
    assert any(item["code"] == "retrieval_shadow_semantic_gap_visible" for item in classification["pass"])
    assert any(item["code"] == "retrieval_shadow_report_only" for item in classification["pass"])

    snapshot["rh31_eval"]["retrieval_shadow"]["route_live_applied"] = True
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "retrieval_shadow_live_applied" for item in classification["fail"])


def test_classify_snapshot_fails_on_low_clue_ingress_route_mismatch():
    snapshot = _healthy_snapshot()
    snapshot["low_clue_ingress_matrix"] = [
        {
            "id": "deictic_just_now_no_punctuation",
            "route": "foreground_control",
            "headings": ["Current Foreground Task"],
            "expected_route": "ambiguous_recall",
            "expected_heading": "Recall Clarification Guard",
        }
    ]

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "low_clue_ingress_route_mismatch" for item in classification["fail"])
    assert any(item["code"] == "low_clue_ingress_heading_mismatch" for item in classification["fail"])


def test_classify_snapshot_fails_when_low_clue_guard_contract_missing():
    snapshot = _healthy_snapshot()
    snapshot["low_clue_ingress_matrix"] = [
        {
            "id": "deictic_yesterday",
            "route": "ambiguous_recall",
            "headings": ["Recall Clarification Guard"],
            "expected_route": "ambiguous_recall",
            "expected_heading": "Recall Clarification Guard",
            "guard_contract_ok": False,
        }
    ]

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "low_clue_guard_contract_missing" for item in classification["fail"])


def test_classify_snapshot_clean_host_does_not_fail_on_live_host_assumptions():
    snapshot = _healthy_snapshot()
    snapshot["monitor_profile"] = "clean_host"
    snapshot["gateway"] = {"ActiveState": "inactive", "MainPID": "0"}
    snapshot["low_clue_ingress_matrix"] = [
        {
            "id": "deictic_yesterday",
            "route": "ambiguous_recall",
            "headings": ["Recall Clarification Guard", "Conversation Carryover"],
            "expected_route": "ambiguous_recall",
            "expected_heading": "Recall Clarification Guard",
            "guard_contract_ok": False,
        }
    ]
    snapshot["rh26_apply_probe"] = [
        {
            "id": "cancel_failed_video",
            "chars": 800,
            "headings": ["Current Foreground Task", "Working Memory"],
        }
    ]

    classification = classify_snapshot(snapshot)

    assert classification["status"] != "FAIL"
    assert not any(item["code"] == "gateway_inactive" for item in classification["fail"])
    assert not any(item["code"] == "low_clue_guard_contract_missing" for item in classification["fail"])
    assert not any(item["code"] == "unexpected_rh26_headings" for item in classification["fail"])
    assert any(item["code"] == "clean_host_gateway_inactive_expected" for item in classification["pass"])
    assert any(item["code"] == "clean_host_low_clue_ingress_contract_not_required" for item in classification["pass"])
    assert any(item["code"] == "clean_host_rh26_probe_contract_not_required" for item in classification["pass"])


def test_classify_snapshot_clean_host_accepts_system_gateway_from_hermes_status():
    snapshot = _healthy_snapshot()
    snapshot["monitor_profile"] = "clean_host"
    snapshot["gateway"] = {"ActiveState": "inactive", "MainPID": "0"}
    snapshot["hermes_status"] = {
        "ok": True,
        "code": 0,
        "gateway_running": True,
        "gateway_manager": "systemd (system)",
        "gateway_pids": "787558",
        "weixin_configured": True,
        "telegram_configured": False,
    }

    classification = classify_snapshot(snapshot)
    rendered = render_chinese_summary({**snapshot, "classification": classification})

    assert classification["status"] != "FAIL"
    assert not any(item["code"] == "gateway_inactive" for item in classification["fail"])
    assert any(
        item["code"] == "clean_host_gateway_active_via_hermes_status"
        and item["manager"] == "systemd (system)"
        and item["pids"] == "787558"
        for item in classification["pass"]
    )
    assert not any(item["code"] == "clean_host_gateway_inactive_expected" for item in classification["pass"])
    assert "hermes_gateway_running=True" in rendered
    assert "manager=systemd (system)" in rendered


def test_classify_snapshot_fails_when_low_clue_candidate_uses_internal_label():
    snapshot = _healthy_snapshot()
    snapshot["low_clue_recall"] = {
        "schema_version": "memory-os.low_clue_recall.v0",
        "decision": "ask_choice",
        "candidate_count": 4,
        "internal_label_count": 1,
        "llm_judge": {"status": "disabled", "mode": "none"},
    }

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "low_clue_internal_candidate_label" for item in classification["fail"])


def test_classify_snapshot_treats_no_selection_judge_as_available():
    snapshot = _healthy_snapshot()
    snapshot["low_clue_recall_config"] = {
        "enabled": True,
        "llm_judge": {"enabled": True, "mode": "report_only"},
    }
    snapshot["low_clue_recall"] = {
        "schema_version": "memory-os.low_clue_recall.v0",
        "decision": "ask_choice",
        "candidate_count": 4,
        "llm_judge": {"status": "no_selection", "mode": "report_only"},
    }

    classification = classify_snapshot(snapshot)
    summary = render_chinese_summary({**snapshot, "classification": classification})

    assert any(item["code"] == "low_clue_llm_judge_available" for item in classification["pass"])
    assert not any(item["code"] == "low_clue_llm_judge_unavailable" for item in classification["warn"])
    assert "'llm_available': True" in summary


def test_classify_snapshot_fails_when_shell_alias_without_env_breaks():
    snapshot = {
        "gateway": {"ActiveState": "active"},
        "heartbeat_timer": {"ActiveState": "active", "UnitFileState": "enabled"},
        "heartbeat_listed": True,
        "cognitive_loop_timer": {"ActiveState": "active", "UnitFileState": "enabled"},
        "cognitive_loop_listed": True,
        "cognitive_loop": _healthy_cognitive_loop(),
        "memory_status": {
            "counts": {"crystallized_records": 0},
            "index_health": {"state": "healthy"},
            "prefetch_mode": "indexed",
        },
        "doctor": {"status": "ok", "findings": []},
        "status_tool_contract": {"status": "ok", "findings": []},
        "shell_alias_no_env": {
            "status_ok": False,
            "doctor_ok": False,
            "status_error": "No module named 'memory_os'",
        },
        "context_router": {"enabled": True, "mode": "apply", "apply_routes": ["all"]},
        "rh26_apply_probe": [],
        "deep_reflection": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_crystallized_approval": False,
        },
        "compaction": {},
    }

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "shell_alias_no_env_failed" for item in classification["fail"])


def test_classify_snapshot_fails_when_shell_modules_alias_without_env_breaks():
    snapshot = _healthy_snapshot()
    snapshot["shell_alias_no_env"]["modules_ok"] = False
    snapshot["shell_alias_no_env"]["modules_error"] = "invalid choice: 'modules'"

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "shell_alias_no_env_failed" for item in classification["fail"])


def test_classify_snapshot_fails_when_metadata_retention_alias_without_env_breaks():
    snapshot = _healthy_snapshot()
    snapshot["shell_alias_no_env"]["metadata_retention_ok"] = False
    snapshot["shell_alias_no_env"]["metadata_retention_error"] = "invalid choice: 'metadata-retention'"

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "shell_alias_no_env_failed" for item in classification["fail"])


def test_classify_snapshot_fails_when_cognitive_loop_service_last_result_failed():
    snapshot = _healthy_snapshot()
    snapshot["cognitive_loop_service"] = {
        "ActiveState": "failed",
        "SubState": "failed",
        "Result": "exit-code",
        "ExecMainStatus": "2",
    }

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "cognitive_loop_service_failed" for item in classification["fail"])


def test_classify_snapshot_passes_memory_sources_stats_and_fails_for_forbidden_fields():
    snapshot = _healthy_snapshot()
    snapshot["memory_sources"] = {
        "schema_version": "memory-os.memory_sources_stats.v0",
        "ledger_exists": True,
        "record_count": 12,
        "file_size_bytes": 4096,
        "boundary_true_count": 0,
        "forbidden_field_findings": [],
    }

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "memory_sources_stats_ok" for item in classification["pass"])

    snapshot["memory_sources"]["forbidden_field_findings"] = [{"path": "$.selected[0].preview"}]
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "memory_sources_forbidden_fields" for item in classification["fail"])


def test_classify_snapshot_warns_when_memory_sources_feedback_surface_has_no_real_feedback():
    snapshot = _healthy_snapshot()
    snapshot["memory_sources"] = {
        "schema_version": "memory-os.memory_sources_stats.v0",
        "ledger_exists": True,
        "record_count": 12,
        "feedback_count": 0,
        "file_size_bytes": 4096,
        "boundary_true_count": 0,
        "forbidden_field_findings": [],
    }
    snapshot["owner_review_surface"]["operations"]["memory_sources_feedback_context"] = {
        "status": "ok",
        "item_count": 1,
        "feedback_action_count": 9,
        "latest_memory_source_id": "msrc_123",
    }

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "memory_sources_feedback_volume_missing" for item in classification["warn"])
    assert classification["status"] == "WARN"


def test_classify_snapshot_passes_when_memory_sources_feedback_volume_exists():
    snapshot = _healthy_snapshot()
    snapshot["memory_sources"] = {
        "schema_version": "memory-os.memory_sources_stats.v0",
        "ledger_exists": True,
        "record_count": 12,
        "feedback_count": 2,
        "file_size_bytes": 4096,
        "boundary_true_count": 0,
        "forbidden_field_findings": [],
    }
    snapshot["owner_review_surface"]["operations"]["memory_sources_feedback_context"] = {
        "status": "ok",
        "item_count": 1,
        "feedback_action_count": 9,
        "latest_memory_source_id": "msrc_123",
    }

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "memory_sources_feedback_volume_present" for item in classification["pass"])
    assert not any(item["code"] == "memory_sources_feedback_volume_missing" for item in classification["warn"])


def test_classify_snapshot_uses_total_memory_sources_feedback_when_window_empty():
    snapshot = _healthy_snapshot()
    snapshot["memory_sources"] = {
        "schema_version": "memory-os.memory_sources_stats.v0",
        "ledger_exists": True,
        "record_count": 12,
        "feedback_count": 0,
        "total_feedback_count": 2,
        "file_size_bytes": 4096,
        "boundary_true_count": 0,
        "forbidden_field_findings": [],
    }
    snapshot["owner_review_surface"]["operations"]["memory_sources_feedback_context"] = {
        "status": "ok",
        "item_count": 1,
        "feedback_action_count": 9,
        "latest_memory_source_id": "msrc_123",
    }

    classification = classify_snapshot(snapshot)

    assert any(
        item["code"] == "memory_sources_feedback_volume_present" and item["feedback_count"] == 2
        for item in classification["pass"]
    )
    assert not any(item["code"] == "memory_sources_feedback_volume_missing" for item in classification["warn"])


def test_enrich_memory_sources_stats_preserves_window_and_total_feedback_counts(monkeypatch):
    namespace: dict[str, object] = {}
    _exec_remote_probe_prefix(namespace)

    def fake_read_jsonl(path):
        if str(path).endswith("memory_sources_feedback.jsonl"):
            return [
                {
                    "schema_version": "memory-os.memory_sources_feedback.v0",
                    "feedback_id": "fb_1",
                    "rating": "useful",
                },
                {
                    "schema_version": "memory-os.memory_sources_feedback.v0",
                    "feedback_id": "fb_2",
                    "rating": "missing_context",
                },
            ]
        return []

    monkeypatch.setitem(namespace, "_read_jsonl", fake_read_jsonl)

    enriched = namespace["enrich_memory_sources_stats"](
        {
            "schema_version": "memory-os.memory_sources_stats.v0",
            "hours": 24,
            "record_count": 0,
            "feedback_count": 0,
            "feedback_rating_distribution": {},
        }
    )

    assert enriched["feedback_count"] == 0
    assert enriched["total_feedback_count"] == 2
    assert enriched["total_feedback_rating_distribution"] == {
        "missing_context": 1,
        "useful": 1,
    }


def test_hermes_status_summary_detects_system_gateway_without_raw_status(monkeypatch):
    namespace: dict[str, object] = {}
    _exec_remote_probe_prefix(namespace)

    def fake_run(cmd, env=None):
        assert env is None
        if cmd == ["hermes", "status"]:
            return {
                "ok": True,
                "code": 0,
                "out": "\n".join(
                    [
                        "Hermes Agent v0.15.1",
                        "◆ Environment",
                        "Model: deepseek-v4-flash",
                        "Provider: DeepSeek",
                        "◆ Messaging Platforms",
                        "Telegram      ✗ not configured",
                        "Weixin        ✓ configured (home: wxid)",
                        "◆ Gateway Service",
                        "Status:       ✓ running",
                        "Manager:      systemd (system)",
                        "PID(s):       787558",
                        "API key: sk-redacted",
                    ]
                ),
            }
        return {"ok": False, "code": 1, "out": ""}

    monkeypatch.setitem(namespace, "run", fake_run)

    summary = namespace["hermes_status_summary"]()

    assert summary == {
        "ok": True,
        "code": 0,
        "gateway_running": True,
        "gateway_manager": "systemd (system)",
        "gateway_pids": "787558",
        "weixin_configured": True,
        "telegram_configured": False,
        "model": "deepseek-v4-flash",
        "provider": "DeepSeek",
    }
    assert "out" not in summary
    assert "API key" not in json.dumps(summary)


def test_classify_snapshot_tracks_memory_sources_policy_apply():
    snapshot = _healthy_snapshot()
    snapshot["memory_sources"] = {
        "schema_version": "memory-os.memory_sources_stats.v0",
        "ledger_exists": True,
        "record_count": 12,
        "feedback_count": 2,
        "file_size_bytes": 4096,
        "boundary_true_count": 0,
        "forbidden_field_findings": [],
        "policy_present": True,
        "policy_version": 1,
        "policy_apply_count": 1,
        "policy_actual_execute_count": 0,
        "policy_raw_body_included_count": 0,
    }

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "memory_sources_policy_present" for item in classification["pass"])
    assert not any(item["code"] == "memory_sources_policy_actual_execute_true" for item in classification["fail"])
    assert not any(item["code"] == "memory_sources_policy_raw_body_included" for item in classification["fail"])


def test_classify_snapshot_fails_when_memory_sources_policy_violates_boundary():
    snapshot = _healthy_snapshot()
    snapshot["memory_sources"] = {
        "schema_version": "memory-os.memory_sources_stats.v0",
        "ledger_exists": True,
        "record_count": 12,
        "feedback_count": 2,
        "file_size_bytes": 4096,
        "boundary_true_count": 0,
        "forbidden_field_findings": [],
        "policy_present": True,
        "policy_version": 1,
        "policy_apply_count": 1,
        "policy_actual_execute_count": 1,
        "policy_raw_body_included_count": 1,
    }

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "memory_sources_policy_actual_execute_true" for item in classification["fail"])
    assert any(item["code"] == "memory_sources_policy_raw_body_included" for item in classification["fail"])


def test_classify_snapshot_fails_when_memory_sources_boundary_is_true():
    snapshot = _healthy_snapshot()
    snapshot["memory_sources"] = {
        "schema_version": "memory-os.memory_sources_stats.v0",
        "ledger_exists": True,
        "record_count": 12,
        "file_size_bytes": 4096,
        "boundary_true_count": 1,
        "forbidden_field_findings": [],
    }

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "memory_sources_boundary_true" for item in classification["fail"])


def test_classify_snapshot_fails_when_heartbeat_state_is_stale():
    snapshot = _healthy_snapshot()
    snapshot["heartbeat_state"] = {
        "exists": True,
        "last_heartbeat_at": "2026-05-22T00:00:00Z",
        "fresh": False,
        "age_seconds": 9999,
    }

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "heartbeat_state_stale" for item in classification["fail"])


def test_classify_snapshot_passes_when_heartbeat_state_is_fresh():
    snapshot = _healthy_snapshot()
    snapshot["heartbeat_state"] = {
        "exists": True,
        "last_heartbeat_at": "2026-05-22T00:00:00Z",
        "fresh": True,
        "age_seconds": 60,
    }

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "heartbeat_state_fresh" for item in classification["pass"])


def test_classify_snapshot_fails_when_cognitive_loop_is_not_active_or_violates_boundary():
    snapshot = {
        "gateway": {"ActiveState": "active"},
        "heartbeat_timer": {"ActiveState": "active", "UnitFileState": "enabled"},
        "heartbeat_listed": True,
        "cognitive_loop_timer": {"ActiveState": "inactive", "UnitFileState": "disabled"},
        "cognitive_loop_listed": False,
        "cognitive_loop": {
            "last_status": "error",
            "boundaries": {
                "actual_send": True,
                "actual_execute": False,
                "actual_identity_write": False,
                "actual_crystallized_approval": False,
            },
        },
        "memory_status": {
            "counts": {"crystallized_records": 0},
            "index_health": {"state": "healthy"},
            "prefetch_mode": "indexed",
        },
        "doctor": {"status": "ok", "findings": []},
        "status_tool_contract": {"status": "ok", "findings": []},
        "shell_alias_no_env": {
            "status_ok": True,
            "doctor_ok": True,
            "memory_sources_ok": True,
            "metadata_retention_ok": True,
            "low_clue_recall_ok": True,
            "modules_ok": True,
            "eval_ok": True,
        },
        "context_router": {"enabled": True, "mode": "apply", "apply_routes": ["all"]},
        "rh26_apply_probe": [],
        "deep_reflection": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_crystallized_approval": False,
        },
        "compaction": {},
    }

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "cognitive_loop_timer_inactive" for item in classification["fail"])
    assert any(item["code"] == "cognitive_loop_timer_not_listed" for item in classification["fail"])
    assert any(item["code"] == "cognitive_loop_last_cycle_error" for item in classification["fail"])
    assert any(item["code"] == "cognitive_loop_actual_send_true" for item in classification["fail"])


def test_render_chinese_summary_omits_private_bodies_and_reports_trends():
    snapshot = _healthy_snapshot()
    snapshot["deltas"] = {
        "counts_delta": {"audit_entries": 10, "events": 2},
        "audit_entries_per_new_event": 5.0,
        "audit_action_delta": {"runtime_heartbeat": 3, "write_working_document": 2},
    }
    snapshot["classification"] = {"status": "WARN", "pass": [{"code": "doctor_ok"}], "warn": [], "fail": []}
    snapshot["audit_actions"] = {
        "total_count": 20,
        "recent_window": 250,
        "recent_action_counts": {"runtime_heartbeat": 8, "write_working_document": 7},
        "action_counts": {"runtime_heartbeat": 10, "write_working_document": 8},
    }
    snapshot["heartbeat_state"] = {"exists": True, "last_heartbeat_at": "2026-05-22T00:00:00Z", "fresh": True}
    snapshot["working_status"] = {
        "documents": {
            "lingering.json": {
                "items": 4,
                "statuses": {"active": 2, "expired": 2},
                "min_weight": 0.1,
                "max_weight": 0.8,
                "avg_weight": 0.45,
            }
        }
    }
    snapshot["memory_sources"] = {
        "schema_version": "memory-os.memory_sources_stats.v0",
        "record_count": 3,
        "file_size_bytes": 2048,
        "feedback_count": 2,
        "feedback_rating_distribution": {"useful": 1, "too_mechanistic": 1},
        "feedback_file_size_bytes": 512,
        "route_distribution": {"ambiguous_recall": 1},
        "selected_source_class_distribution": {"recall_guard": 1},
        "selected_heading_distribution": {"Recent Event Summaries": 2},
        "dropped_heading_distribution": {"Working Memory": 1},
        "forbidden_field_findings": [],
        "boundary_true_count": 0,
    }
    snapshot["hook_markers"] = {"started": 5, "reset": 4, "finalized": 4, "total": 13}
    snapshot["session_activity"] = {"total_session_events": 12}
    snapshot["expression_artifacts"] = {
        "schema_version": "memory-os.expression_artifact_summary.v0",
        "wandering_output_count": 10,
        "wandering_would_send_count": 10,
        "wandering_silent_count": 2,
        "speak_gate_evaluated_count": 8,
        "speak_gate_missing_evaluation_count": 2,
        "speak_gate_decision_distribution": {"would_send": 8},
        "speak_gate_would_send_count": 0,
        "speak_gate_blocked_count": 0,
        "speak_gate_actual_send": False,
    }
    snapshot["session_mirror"] = {
        "schema_version": "memory-os.session_mirror_monitor_summary.v0",
        "status": "ok",
        "session_count": 54,
        "covered_session_count": 29,
        "pending_session_count": 25,
        "dry_run_status": "ok",
        "dry_run_new_event_count": 25,
        "dry_run_written_event_ids_count": 0,
        "dry_run_findings_count": 0,
    }

    rendered = render_chinese_summary(snapshot)

    assert "host=debian" in rendered
    assert "context_router=apply" in rendered
    assert "cognitive_loop=ok" in rendered
    assert "shell_alias_no_env" in rendered
    assert "MemorySources" in rendered
    assert "ModuleArtifacts" in rendered
    assert "feedback_ratings" in rendered
    assert "audit_actions" in rendered
    assert "heartbeat_state" in rendered
    assert "working_status" in rendered
    assert "HookCoverage" in rendered
    assert "ExpressionArtifacts" in rendered
    assert "SessionMirror" in rendered
    assert "selected_headings" in rendered
    assert "audit_entries=+10" in rendered
    assert "events=+2" in rendered
    assert "raw event" not in rendered.lower()
    assert "User:" not in rendered
    assert json.dumps(snapshot, ensure_ascii=False)


def test_classify_snapshot_warns_when_wandering_outputs_skip_speak_gate():
    snapshot = _healthy_snapshot()
    snapshot["expression_artifacts"] = {
        "schema_version": "memory-os.expression_artifact_summary.v0",
        "wandering_would_send_result_count": 3,
        "speak_gate_evaluated_count": 1,
        "speak_gate_missing_evaluation_count": 2,
        "speak_gate_decision_distribution": {"would_send": 1},
        "speak_gate_actual_send": False,
    }

    classification = classify_snapshot(snapshot)
    rendered = render_chinese_summary({**snapshot, "classification": classification})

    assert classification["status"] == "WARN"
    assert any(item["code"] == "right_brain_speak_gate_missing_evaluation" for item in classification["warn"])
    assert "speak_gate_missing_evaluation_count" in rendered


def test_classify_snapshot_warns_when_expression_draft_is_missing():
    snapshot = _healthy_snapshot()
    snapshot["expression_artifacts"] = {
        "schema_version": "memory-os.expression_artifact_summary.v0",
        "expression_draft_missing_count": 2,
        "speak_gate_missing_evaluation_count": 0,
        "speak_gate_actual_send": False,
    }

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "WARN"
    assert any(item["code"] == "right_brain_expression_draft_missing" for item in classification["warn"])


def test_classify_snapshot_uses_latest_expression_cycle_for_current_closure():
    snapshot = _healthy_snapshot()
    snapshot["expression_artifacts"] = {
        "schema_version": "memory-os.expression_artifact_summary.v0",
        "expression_draft_missing_count": 23,
        "latest_expression_draft_missing_count": 0,
        "speak_gate_missing_evaluation_count": 15,
        "latest_speak_gate_missing_evaluation_count": 0,
        "speak_gate_actual_send": False,
    }

    classification = classify_snapshot(snapshot)

    assert not any(item["code"] == "right_brain_expression_draft_missing" for item in classification["warn"])
    assert not any(item["code"] == "right_brain_speak_gate_missing_evaluation" for item in classification["warn"])
    assert any(item["code"] == "right_brain_expression_draft_created" for item in classification["pass"])
    assert any(item["code"] == "right_brain_speak_gate_evaluation_complete" for item in classification["pass"])


def test_main_can_save_current_snapshot_for_next_delta(tmp_path, monkeypatch, capsys):
    previous = tmp_path / "previous.json"
    output = tmp_path / "current.json"
    previous.write_text(
        json.dumps({"memory_status": {"counts": {"audit_entries": 5, "events": 1}}}),
        encoding="utf-8",
    )

    def fake_collect_snapshot(*, host, previous, monitor_profile):
        assert host == "fake-host"
        assert monitor_profile == "clean_host"
        assert previous["memory_status"]["counts"]["audit_entries"] == 5
        return {
            "hostname": "debian",
            "date_utc": "2026-05-22T00:00:00Z",
            "gateway": {"ActiveState": "active", "MainPID": "1"},
            "heartbeat_timer": {"ActiveState": "active", "UnitFileState": "enabled"},
            "heartbeat_listed": True,
            "cognitive_loop_timer": {"ActiveState": "active", "UnitFileState": "enabled"},
            "cognitive_loop_listed": True,
            "cognitive_loop": _healthy_cognitive_loop(),
            "memory_status": {
                "counts": {"audit_entries": 9, "events": 2, "crystallized_records": 0},
                "index_health": {"state": "healthy"},
                "prefetch_mode": "indexed",
            },
            "doctor": {"status": "ok", "findings": []},
            "status_tool_contract": {"status": "ok", "findings": []},
            "shell_alias_no_env": {"status_ok": True, "doctor_ok": True, "memory_sources_ok": True, "metadata_retention_ok": True, "low_clue_recall_ok": True, "modules_ok": True, "eval_ok": True, "review_ok": True, "review_aging_ok": True},
            "context_router": {"enabled": True, "mode": "apply", "apply_routes": ["all"]},
            "rh26_apply_probe": [],
            "deep_reflection": {},
            "compaction": {},
            "disk_du": "1M",
            "deltas": {"counts_delta": {"audit_entries": 4, "events": 1}, "audit_entries_per_new_event": 4.0},
            "classification": {"status": "PASS", "pass": [], "warn": [], "fail": []},
        }

    monkeypatch.setattr(monitor, "collect_snapshot", fake_collect_snapshot)

    assert main(
        [
            "--host",
            "fake-host",
            "--previous-json",
            str(previous),
            "--snapshot-out",
            str(output),
            "--output",
            "summary",
            "--monitor-profile",
            "clean-host",
        ]
    ) == 0

    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["monitor_profile"] == "clean_host"
    assert saved["memory_status"]["counts"]["audit_entries"] == 9
    assert saved["deltas"]["counts_delta"]["audit_entries"] == 4
    assert "audit_entries=+4" in capsys.readouterr().out


def _healthy_cognitive_loop() -> dict:
    return {
        "last_status": "ok",
        "last_cycle_id": "cloop_test",
        "boundaries": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_crystallized_approval": False,
        },
    }


def _healthy_snapshot() -> dict:
    return {
        "hostname": "debian",
        "date_utc": "2026-05-22T07:07:41Z",
        "gateway": {"ActiveState": "active", "MainPID": "451894"},
        "heartbeat_timer": {"ActiveState": "active", "UnitFileState": "enabled"},
        "heartbeat_listed": True,
        "cognitive_loop_timer": {"ActiveState": "active", "UnitFileState": "enabled"},
        "cognitive_loop_listed": True,
        "cognitive_loop": _healthy_cognitive_loop(),
        "memory_status": {
            "counts": {"audit_entries": 110, "events": 12, "working_items": 7, "crystallized_records": 0},
            "index_health": {"state": "healthy"},
            "prefetch_mode": "indexed",
        },
        "doctor": {"status": "ok", "findings": [("hindsight_adapter_disabled", "warning")]},
        "status_tool_contract": {"status": "ok", "findings": []},
        "shell_alias_no_env": {
            "status_ok": True,
            "doctor_ok": True,
            "memory_sources_ok": True,
            "metadata_retention_ok": True,
            "low_clue_recall_ok": True,
            "modules_ok": True,
            "eval_ok": True,
            "review_ok": True,
            "review_aging_ok": True,
            "review_channel_ok": True,
            "review_cron_status_ok": True,
            "review_delivery_status_ok": True,
            "review_delivery_gate_ok": True,
            "review_digest_ok": True,
            "review_render_ok": True,
            "review_reply_ok": True,
            "review_surface_ok": True,
        },
        "context_router": {"enabled": True, "mode": "apply", "apply_routes": ["all"]},
        "rh26_apply_probe": [],
        "deep_reflection": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_crystallized_approval": False,
        },
        "compaction": {},
        "module_artifacts": _healthy_module_artifacts(),
        "expression_artifacts": _healthy_expression_artifacts(),
        "owner_review": _healthy_owner_review(),
        "owner_review_aging": _healthy_owner_review_aging(),
        "owner_review_channel": _healthy_owner_review_channel(),
        "owner_review_cron_integration": _healthy_owner_cron_integration(),
        "owner_review_delivery_status": _healthy_owner_delivery_status(),
        "owner_review_delivery_gate": _healthy_owner_delivery_gate(),
        "owner_review_digest_preview": _healthy_owner_digest_preview(),
        "owner_review_rendered_digest": _healthy_owner_rendered_digest(),
        "owner_review_agenda_digest": _healthy_owner_agenda_digest(),
        "owner_review_reply_dry_run": _healthy_owner_reply_dry_run(),
        "owner_review_surface": _healthy_owner_review_surface(),
        "owner_review_ingress_guard": _healthy_owner_ingress_guard(),
        "owner_review_proposal_followups": _healthy_owner_proposal_followups(),
    }


def _healthy_owner_review() -> dict:
    return {
        "schema_version": "memory-os.owner_review_status.v0",
        "review_queue": {"pending_count": 0, "action_required_count": 0, "stale_count": 0},
        "owner_action_count": 0,
        "action_type_counts": {},
        "duplicate_ignored_count": 0,
        "error_count": 0,
        "owner_approved_crystallized_write_count": 0,
        "unapproved_crystallized_write_count": 0,
        "digest_burden": {"owner_active_period": False, "phase": "cold_start"},
        "feedback_backflow": {"feedback_action_count": 0},
    }


def _healthy_owner_review_aging() -> dict:
    return {
        "schema_version": "memory-os.owner_review_aging.v0",
        "enabled": True,
        "action_required_days": 7,
        "fyi_days": 30,
        "raw_action_required_count": 0,
        "effective_action_required_count": 0,
        "aged_to_review_suggested_count": 0,
        "aged_to_fyi_count": 0,
        "unknown_timestamp_count": 0,
        "unknown_timestamp_by_item_type": {},
        "created_at_coverage_ratio": 1.0,
        "created_at_source_distribution": {"producer": 3},
        "created_at_source_by_item_type": {"proposal": {"producer": 3}},
        "true_aged_count": 0,
        "unknown_aged_count": 0,
        "raw_body_included": False,
        "canonical_state_changed": False,
        "owner_action_created": False,
    }


def _healthy_owner_review_channel() -> dict:
    return {
        "schema_version": "memory-os.owner_review_channel.v0",
        "status": "dry_run_only",
        "reason": "cli_preview_fallback",
        "profile": "default",
        "owner_id": "owner",
        "channel": "cli",
        "target_ref": "",
        "direct_message": False,
        "last_owner_activity_at": "",
        "configured_by_owner": False,
        "fallback_used": True,
        "raw_body_included": False,
    }


def _healthy_owner_cron_integration() -> dict:
    return {
        "schema_version": "memory-os.owner_review_cron_integration.v0",
        "status": "ok",
        "enabled": False,
        "mode": "disabled",
        "job_name": "memory-os-owner-review-digest",
        "job_present": False,
        "job_enabled": False,
        "job_id": "",
        "schedule_display": "",
        "helper_script_present": False,
        "helper_script_path": "/root/.hermes/scripts/memory_os_owner_review_digest.py",
        "helper_script_name": "memory_os_owner_review_digest.py",
        "hermes_delivery_configured": False,
        "hermes_delivery_target_class": "missing",
        "rendered_count_24h": 0,
        "skipped_count_24h": 0,
        "error_count_24h": 0,
        "raw_body_included_count": 0,
        "unapproved_send_count": 0,
        "findings": [],
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
        },
    }


def _healthy_owner_digest_preview() -> dict:
    return {
        "schema_version": "memory-os.owner_review_digest_preview.v0",
        "status": "ok",
        "digest_id": "digest_test",
        "owner_id": "owner",
        "will_send": False,
        "delivery_skipped": True,
        "actions_enabled": False,
        "raw_body_included": False,
        "counts": {
            "action_required_total": 0,
            "action_required_shown": 0,
            "review_suggested_total": 0,
            "review_suggested_shown": 0,
            "fyi_total": 1,
            "fyi_shown": 1,
        },
        "overflow": {"action_required": 0, "review_suggested": 0, "fyi": 0},
        "sections": {"action_required": [], "review_suggested": [], "fyi": []},
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
        },
    }


def _healthy_owner_rendered_digest() -> dict:
    return {
        "schema_version": "memory-os.owner_review_rendered_digest.v0",
        "status": "ok",
        "will_send": False,
        "raw_body_included": False,
        "text_char_count": 120,
        "text_has_internal_schema": False,
        "text_has_transcript_marker": False,
        "response_header_present": True,
        "overview_present": True,
        "speak_item_count": 0,
        "speak_expression_preview_count": 0,
        "speak_expression_preview_missing_count": 0,
        "section_counts": {"action_required": 0, "review_suggested": 0, "fyi": 1},
        "anchors": {"action_required": [], "review_suggested": [], "fyi": ["F1"]},
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
        },
    }


def _healthy_owner_agenda_digest() -> dict:
    return {
        "schema_version": "memory-os.owner_review_rendered_digest.v0",
        "status": "ok",
        "digest_mode": "agenda",
        "raw_body_included": False,
        "text_char_count": 900,
        "text_has_internal_schema": False,
        "text_has_transcript_marker": False,
        "decision_summary_present": True,
        "review_suggested_suppressed": True,
        "fyi_suppressed": True,
        "backlog_totals_suppressed": True,
        "section_counts": {"action_required": 2, "review_suggested": 0, "fyi": 0},
        "counts": {"action_required_total": 2, "action_required_shown": 2},
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
        },
    }


def _healthy_owner_reply_dry_run() -> dict:
    return {
        "schema_version": "memory-os.owner_review_reply.v0",
        "status": "ok",
        "dry_run": True,
        "reason": "",
        "owner_utterance_source": "latest_recorded_digest",
        "parsed_action_type": "approve_proposal",
        "parsed_target_type": "proposal",
        "owner_action_status": "ok",
        "owner_action_dry_run": True,
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
        },
    }


def _healthy_owner_review_surface() -> dict:
    return {
        "schema_version": "memory-os.owner_review_surface_monitor.v0",
        "status": "ok",
        "operations": {
            "next_page": {
                "status": "ok",
                "item_count": 1,
                "source": "latest_owner_home_digest",
                "forbidden_owner_command_field_count": 0,
                "owner_utterance_example_count": 1,
                "agent_tool_call_count": 1,
            },
            "detail": {
                "status": "ok",
                "item_count": 1,
                "source": "latest_recorded_digest",
                "forbidden_owner_command_field_count": 0,
                "owner_utterance_example_count": 1,
                "agent_tool_call_count": 1,
            },
            "proposal_followups": {
                "status": "ok",
                "item_count": 1,
                "source": "",
                "forbidden_owner_command_field_count": 0,
                "owner_utterance_example_count": 1,
                "agent_tool_call_count": 1,
            },
            "expression_feedback_context": {
                "status": "ok",
                "item_count": 1,
                "feedback_action_count": 6,
                "latest_outcome_id": "rbout_123",
                "forbidden_owner_command_field_count": 0,
                "owner_utterance_example_count": 6,
                "agent_tool_call_count": 6,
            },
            "memory_sources_feedback_context": {
                "status": "ok",
                "item_count": 1,
                "feedback_action_count": 9,
                "latest_memory_source_id": "msrc_123",
                "forbidden_owner_command_field_count": 0,
                "owner_utterance_example_count": 9,
                "agent_tool_call_count": 9,
            },
        },
        "raw_body_included_count": 0,
        "boundary_true_count": 0,
        "forbidden_owner_command_field_count": 0,
        "forbidden_owner_command_fields": [],
        "owner_utterance_example_count": 18,
        "agent_tool_call_count": 18,
    }


def _healthy_owner_ingress_guard() -> dict:
    return {
        "schema_version": "memory-os.owner_review_ingress_guard.v0",
        "legacy_anchor_accepted": False,
        "legacy_reject_anchor_accepted": False,
        "ordinary_anchor_text_accepted": False,
        "token_command_accepted": True,
        "bare_token_command_accepted": True,
        "slash_token_command_accepted": True,
        "feedback_token_command_accepted": True,
        "bare_feedback_token_command_accepted": True,
        "gateway_hook_plugin_present": True,
        "gateway_hook_registered": False,
        "gateway_safety_skip_count": 0,
        "review_reply_tool_available": True,
        "review_reply_tool_status": "ok",
        "review_reply_tool_input_mode": "structured",
        "structured_review_reply_count": 1,
        "reply_fallback_used_count": 0,
        "owner_command_event_count": 0,
        "owner_command_working_count": 0,
        "owner_command_candidate_count": 0,
        "owner_command_promoted_to_candidate": False,
        "owner_review_command_pollution_count": 0,
    }


def _healthy_owner_proposal_followups() -> dict:
    return {
        "schema_version": "memory-os.approved_proposal_followups.v0",
        "status": "ok",
        "approved_proposal_count": 0,
        "pending_followup_count": 0,
        "open_followup_count": 0,
        "shown_count": 0,
        "overflow_count": 0,
        "awaiting_ops_gate_count": 0,
        "ops_gate_reviewed_count": 0,
        "awaiting_explicit_execution_count": 0,
        "execution_ticket_count": 0,
        "actual_execute": False,
        "raw_body_included": False,
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
        },
        "items": [],
    }


def _healthy_owner_delivery_status() -> dict:
    return {
        "schema_version": "memory-os.owner_review_delivery_status.v0",
        "delivery_count": 0,
        "sent_count": 0,
        "skipped_count": 0,
        "error_count": 0,
        "duplicate_ignored_count": 0,
        "owner_approved_digest_delivery_count": 0,
        "unapproved_send_count": 0,
        "raw_body_included_count": 0,
        "last_delivery": {},
    }


def _healthy_owner_delivery_gate() -> dict:
    return {
        "schema_version": "memory-os.owner_review_delivery_gate.v0",
        "profile": "default",
        "owner_id": "owner",
        "status": "disabled",
        "ready_for_delivery": False,
        "delivery_enabled": False,
        "delivery_adapter": "none",
        "blocked_reasons": ["delivery_not_enabled", "delivery_adapter_not_configured"],
        "review_channel": {
            "status": "dry_run_only",
            "reason": "cli_preview_fallback",
            "channel": "cli",
            "target_ref": "",
            "direct_message": False,
            "configured_by_owner": False,
            "fallback_used": True,
            "raw_body_included": False,
        },
        "digest": {
            "schema_version": "memory-os.owner_review_digest_preview.v0",
            "status": "ok",
            "raw_body_included": False,
            "will_send": False,
            "actions_enabled": False,
        },
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
        },
    }


def _healthy_module_artifacts() -> dict:
    return {
        "schema_version": "memory-os.module_artifact_summary.v0",
        "status": "ok",
        "digest": {"daily_artifact_count": 0, "weekly_artifact_count": 0, "household_artifact_exists": False},
        "wandering": {"output_count": 0, "would_send_count": 0},
        "evidence": {"evidence_count": 0, "score_count": 0, "subject_counts": {}},
        "proposal_queue": {
            "candidate_count": 0,
            "state_counts": {},
            "legacy_template_cleanup_apply_count": 0,
            "legacy_template_cleanup_closed_count": 0,
            "legacy_template_cleanup_non_legacy_touched_count": 0,
            "legacy_template_cleanup_actual_execute_count": 0,
            "legacy_template_cleanup_raw_body_included_count": 0,
        },
        "self_evolution": {"report_count": 0, "proposal_count": 0, "last_status": "missing"},
        "governance_feedback": {"emitted_event_count": 0},
        "left_brain_pipeline_check": {
            "status": "ok",
            "finding_count": 0,
            "active_duplicate_group_count": 0,
            "followup_duplicate_group_count": 0,
            "legacy_template_duplicate_group_count": 0,
            "proposal_quality_missing_count": 0,
            "expression_policy_quality_ready_count": 1,
            "expression_policy_quality_blocked_count": 0,
            "expression_policy_unlinked_quality_count": 0,
            "memory_sources_policy_quality_ready_count": 0,
            "memory_sources_policy_quality_blocked_count": 0,
            "memory_sources_policy_unlinked_quality_count": 0,
            "agenda_trace_missing_count": 0,
            "actual_execute": False,
        },
        "deep_reflection": {"report_count": 0, "analysis_artifact_count": 0, "current_injection_exists": False},
        "ops_gate": {
            "report_count": 0,
            "blocked_decision_count": 0,
            "proposal_followup_action_count": 0,
            "duplicate_proposal_followup_count": 0,
            "duplicate_proposal_followup_extra_count": 0,
        },
        "speak_gate": {"would_send_count": 0, "actual_send": False},
        "expression_draft": {
            "draft_count": 0,
            "silent_count": 0,
            "draft_error_count": 0,
            "raw_body_included": False,
        },
        "expression_feedback": {
            "feedback_count": 0,
            "live_policy_changed_count": 0,
            "raw_body_included_count": 0,
            "linked_outcome_count": 0,
            "unlinked_count": 0,
            "linked_outcome_missing_count": 0,
        },
        "right_brain_expression_adapter": {
            "request_count": 0,
            "silent_request_count": 0,
            "latest_channel": None,
            "latest_delivery_mode": None,
            "latest_actual_send": False,
            "raw_body_included_count": 0,
            "outcome_count": 0,
            "latest_outcome_id": "",
            "latest_outcome_request_id": "",
            "latest_outcome_policy_version": None,
            "latest_outcome_silent": None,
            "latest_outcome_preview_chars": None,
            "outcome_actual_send_count": 0,
            "outcome_actual_execute_count": 0,
            "outcome_raw_body_included_count": 0,
            "outcome_internal_marker_count": 0,
            "outcome_feedback_count": 0,
            "latest_outcome_feedback_count": 0,
            "outcome_feedback_missing_count": 0,
        },
        "mailbox": {"mailbox_exists": False, "would_send_count": 0},
    }


def _healthy_expression_artifacts() -> dict:
    return {
        "schema_version": "memory-os.expression_artifact_summary.v0",
        "wandering_output_count": 0,
        "wandering_would_send_count": 0,
        "wandering_silent_count": 0,
        "expression_draft_count": 0,
        "expression_draft_created_count": 0,
        "expression_draft_missing_count": 0,
        "latest_expression_draft_missing_count": 0,
        "expression_feedback_count": 0,
        "expression_feedback_linked_outcome_count": 0,
        "expression_feedback_unlinked_count": 0,
        "speak_gate_evaluated_count": 0,
        "speak_gate_missing_evaluation_count": 0,
        "latest_speak_gate_missing_evaluation_count": 0,
        "latest_speak_gate_evaluated_count": 0,
        "speak_gate_decision_distribution": {},
        "speak_gate_would_send_count": 0,
        "speak_gate_blocked_count": 0,
        "speak_gate_actual_send": False,
        "right_brain_adapter_request_count": 0,
        "right_brain_adapter_latest_channel": None,
        "right_brain_adapter_latest_delivery_mode": None,
        "right_brain_adapter_latest_actual_send": False,
        "right_brain_adapter_raw_body_included_count": 0,
        "right_brain_adapter_outcome_count": 0,
        "right_brain_adapter_latest_outcome_silent": None,
        "right_brain_adapter_latest_outcome_policy_version": None,
        "right_brain_adapter_outcome_internal_marker_count": 0,
        "right_brain_adapter_outcome_feedback_count": 0,
        "right_brain_adapter_latest_outcome_feedback_count": 0,
    }
