import json

import scripts.memory_os_3_200_monitor as monitor
from scripts.memory_os_3_200_monitor import (
    classify_snapshot,
    compute_deltas,
    find_rh26_heading_anomalies,
    main,
    render_chinese_summary,
)


def test_rh26_heading_anomalies_allow_known_casual_empty_state():
    probes = [
        {"id": "cancel_failed_video", "chars": 134, "headings": ["Current Foreground Task"]},
        {"id": "continue_current_task", "chars": 108, "headings": ["Current Foreground Task"]},
        {"id": "casual_memory_system_change", "chars": 0, "headings": []},
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
        {"id": "active_comfyui_install", "chars": 1516, "headings": ["Current Foreground Task", "Indexed Recall"]},
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
        "code": "casual_context_not_empty",
        "expected": [],
        "actual": ["Current Foreground Task", "Indexed Recall"],
    } in anomalies


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
        }
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
        }
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


def test_classify_snapshot_warns_on_expected_observation_items_without_fail():
    snapshot = {
        "gateway": {"ActiveState": "active"},
        "heartbeat_timer": {"ActiveState": "active", "UnitFileState": "enabled"},
        "heartbeat_listed": True,
        "memory_status": {
            "counts": {"crystallized_records": 0},
            "index_health": {"state": "healthy"},
            "prefetch_mode": "indexed",
        },
        "doctor": {"status": "ok", "findings": [("hindsight_adapter_disabled", "warning")]},
        "status_tool_contract": {"status": "ok", "findings": []},
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
    }

    classification = classify_snapshot(snapshot)

    assert classification["status"] == "WARN"
    assert not classification["fail"]
    assert any(item["code"] == "rh26_casual_empty" for item in classification["warn"])
    assert any(item["code"] == "deep_reflection_source_skew" for item in classification["warn"])
    assert any(item["code"] == "compression_focus_none" for item in classification["warn"])


def test_render_chinese_summary_omits_private_bodies_and_reports_trends():
    snapshot = {
        "hostname": "debian",
        "date_utc": "2026-05-22T07:07:41Z",
        "gateway": {"ActiveState": "active", "MainPID": "451894"},
        "heartbeat_timer": {"ActiveState": "active", "UnitFileState": "enabled"},
        "memory_status": {
            "counts": {"audit_entries": 110, "events": 12, "working_items": 7, "crystallized_records": 0},
            "index_health": {"state": "healthy"},
            "prefetch_mode": "indexed",
        },
        "doctor": {"status": "ok", "findings": [("hindsight_adapter_disabled", "warning")]},
        "context_router": {"enabled": True, "mode": "apply", "apply_routes": ["all"]},
        "rh26_apply_probe": [{"id": "casual_memory_system_change", "chars": 0, "headings": []}],
        "deltas": {"counts_delta": {"audit_entries": 10, "events": 2}, "audit_entries_per_new_event": 5.0},
        "classification": {"status": "WARN", "pass": [{"code": "doctor_ok"}], "warn": [], "fail": []},
    }

    rendered = render_chinese_summary(snapshot)

    assert "host=debian" in rendered
    assert "context_router=apply" in rendered
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
            "memory_status": {
                "counts": {"audit_entries": 9, "events": 2, "crystallized_records": 0},
                "index_health": {"state": "healthy"},
                "prefetch_mode": "indexed",
            },
            "doctor": {"status": "ok", "findings": []},
            "status_tool_contract": {"status": "ok", "findings": []},
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
