import json

import scripts.memory_os_3_200_monitor as monitor
from scripts.memory_os_3_200_monitor import (
    classify_snapshot,
    compute_deltas,
    find_rh26_heading_anomalies,
    main,
    render_chinese_summary,
)


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
            "headings": ["Crystallized Review Candidates", "Indexed Recall"],
        },
        {
            "id": "active_comfyui_install",
            "chars": 2051,
            "headings": ["Current Foreground Task", "Indexed Recall", "Recent Event Summaries"],
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
    }

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "rh31_eval_safety_ok" for item in classification["pass"])
    assert any(item["code"] == "rh31_eval_has_failures" for item in classification["warn"])

    snapshot["rh31_eval"]["forbidden_field_count"] = 1
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "rh31_eval_forbidden_fields" for item in classification["fail"])


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
    assert "OwnerReview" in rendered
    assert "'owner_approved_crystallized': 1" in rendered

    snapshot["owner_review"]["unapproved_crystallized_write_count"] = 1
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_unapproved_crystallized_write" for item in classification["fail"])


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
    assert any(item["code"] == "owner_review_reply_dry_run_ok" for item in classification["pass"])
    assert any(item["code"] == "owner_review_surface_ok" for item in classification["pass"])
    assert any(item["code"] == "owner_review_ingress_guard_token_only" for item in classification["pass"])
    assert any(item["code"] == "owner_review_proposal_followups_ok" for item in classification["pass"])
    assert any(item["code"] == "owner_review_cron_integration_status_ok" for item in classification["pass"])
    assert "OwnerReviewAging" in rendered
    assert "OwnerReviewChannel" in rendered
    assert "OwnerCronIntegration" in rendered
    assert "OwnerDeliveryGate" in rendered
    assert "OwnerDeliveryStatus" in rendered
    assert "OwnerDigestPreview" in rendered
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

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "owner_review_proposal_followups_item_execution_ticket_created" for item in classification["fail"])

    snapshot = _healthy_snapshot()
    snapshot["owner_review_proposal_followups"]["pending_followup_count"] = 1
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "WARN"
    assert any(item["code"] == "owner_review_approved_proposals_pending_followup" for item in classification["warn"])

    snapshot = _healthy_snapshot()
    snapshot["module_artifacts"]["ops_gate"]["duplicate_proposal_followup_count"] = 1
    snapshot["module_artifacts"]["ops_gate"]["duplicate_proposal_followup_extra_count"] = 1
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "ops_gate_duplicate_proposal_followup_report" for item in classification["fail"])

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
        "ops_gate": {"report_count": 22, "blocked_decision_count": 0},
        "speak_gate": {"would_send_count": 0, "actual_send": False},
    }

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "module_artifact_summary_ok" for item in classification["pass"])

    snapshot["module_artifacts"]["speak_gate"]["actual_send"] = True
    classification = classify_snapshot(snapshot)

    assert classification["status"] == "FAIL"
    assert any(item["code"] == "module_artifact_speak_gate_actual_send_true" for item in classification["fail"])


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
    }

    classification = classify_snapshot(snapshot)

    assert any(item["code"] == "session_mirror_dry_run_ok" for item in classification["pass"])
    assert any(item["code"] == "session_mirror_pending_sessions" for item in classification["warn"])
    assert not any(item["code"].startswith("session_mirror_") for item in classification["fail"])


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
        "scores": [{"case_id": "private_case", "details": {"raw": "should not be retained"}}],
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
        "boundary_true_count": 0,
        "forbidden_field_count": 0,
        "report_written": False,
        "source_distribution": {"working": 8},
    }


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


def test_main_can_save_current_snapshot_for_next_delta(tmp_path, monkeypatch, capsys):
    previous = tmp_path / "previous.json"
    output = tmp_path / "current.json"
    previous.write_text(
        json.dumps({"memory_status": {"counts": {"audit_entries": 5, "events": 1}}}),
        encoding="utf-8",
    )

    def fake_collect_snapshot(*, host, previous):
        assert host == "fake-host"
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
        ]
    ) == 0

    saved = json.loads(output.read_text(encoding="utf-8"))
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
        "owner_review": _healthy_owner_review(),
        "owner_review_aging": _healthy_owner_review_aging(),
        "owner_review_channel": _healthy_owner_review_channel(),
        "owner_review_cron_integration": _healthy_owner_cron_integration(),
        "owner_review_delivery_status": _healthy_owner_delivery_status(),
        "owner_review_delivery_gate": _healthy_owner_delivery_gate(),
        "owner_review_digest_preview": _healthy_owner_digest_preview(),
        "owner_review_rendered_digest": _healthy_owner_rendered_digest(),
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
        "section_counts": {"action_required": 0, "review_suggested": 0, "fyi": 1},
        "anchors": {"action_required": [], "review_suggested": [], "fyi": ["F1"]},
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
        "command_source": "latest_recorded_digest",
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
            "next_page": {"status": "ok", "item_count": 1, "source": "latest_owner_home_digest"},
            "detail": {"status": "ok", "item_count": 1, "source": "latest_recorded_digest"},
            "proposal_followups": {"status": "ok", "item_count": 1, "source": ""},
        },
        "raw_body_included_count": 0,
        "boundary_true_count": 0,
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
        "shown_count": 0,
        "overflow_count": 0,
        "awaiting_ops_gate_count": 0,
        "ops_gate_reviewed_count": 0,
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
        "proposal_queue": {"candidate_count": 0, "state_counts": {}},
        "self_evolution": {"report_count": 0, "proposal_count": 0, "last_status": "missing"},
        "governance_feedback": {"emitted_event_count": 0},
        "deep_reflection": {"report_count": 0, "analysis_artifact_count": 0, "current_injection_exists": False},
        "ops_gate": {
            "report_count": 0,
            "blocked_decision_count": 0,
            "proposal_followup_action_count": 0,
            "duplicate_proposal_followup_count": 0,
            "duplicate_proposal_followup_extra_count": 0,
        },
        "speak_gate": {"would_send_count": 0, "actual_send": False},
        "mailbox": {"mailbox_exists": False, "would_send_count": 0},
    }
