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
            "low_clue_recall_ok": True,
            "modules_ok": True,
            "eval_ok": True,
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

    rendered = render_chinese_summary(snapshot)

    assert "host=debian" in rendered
    assert "context_router=apply" in rendered
    assert "cognitive_loop=ok" in rendered
    assert "shell_alias_no_env" in rendered
    assert "MemorySources" in rendered
    assert "feedback_ratings" in rendered
    assert "audit_actions" in rendered
    assert "heartbeat_state" in rendered
    assert "working_status" in rendered
    assert "selected_headings" in rendered
    assert "audit_entries=+10" in rendered
    assert "events=+2" in rendered
    assert "raw event" not in rendered.lower()
    assert "User:" not in rendered
    assert json.dumps(snapshot, ensure_ascii=False)


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
                "shell_alias_no_env": {"status_ok": True, "doctor_ok": True, "memory_sources_ok": True, "low_clue_recall_ok": True, "modules_ok": True, "eval_ok": True},
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
        "shell_alias_no_env": {"status_ok": True, "doctor_ok": True, "memory_sources_ok": True, "low_clue_recall_ok": True, "modules_ok": True, "eval_ok": True},
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
