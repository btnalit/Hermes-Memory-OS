"""RED-first arbitration tests for audit findings in b2037d4."""
from __future__ import annotations


def test_context_router_does_not_mutate_candidate_metadata():
    from plugins.memory.memory_os.context_router import ContextSection, route_context_sections

    metadata = {"origin": "fixture"}
    section = ContextSection(
        section="Crystallized Review Candidates",
        text="candidate",
        source_class="derived",
        metadata=metadata,
    )
    route_context_sections(
        "请审查候选记忆",
        sections=[section],
        current_task_anchor="current task",
        budget_chars=2000,
        mode="apply",
    )
    assert metadata == {"origin": "fixture"}


def test_execution_gate_reconcile_requires_fresh_cron_evidence(tmp_path, monkeypatch):
    from scripts import memory_os_3_200_monitor as monitor

    import sys
    namespace = {"__name__": "remote_probe_test"}
    original_sys_path = list(sys.path)
    try:
        exec(monitor._remote_probe_script().split('\nstatus = load_json_cmd', 1)[0], namespace)
    finally:
        sys.path[:] = original_sys_path
    namespace["_hermes_home"] = str(tmp_path)
    summary = namespace["_execution_gate_helper_completion_summary"](
        {"lane": {"name": "job"}},
        {"job": {"last_status": "ok", "last_run_at": "2020-01-01T00:00:00Z", "schedule": "* * * * *"}},
    )
    assert summary["helper_completion_missing_lanes"] == ["lane"]
    assert summary["helper_completion_reconciled_count"] == 0


def test_execution_gate_fresh_reconcile_is_degraded_and_accounted(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    from scripts import memory_os_3_200_monitor as monitor

    import sys
    namespace = {"__name__": "remote_probe_test"}
    original_sys_path = list(sys.path)
    try:
        exec(monitor._remote_probe_script().split('\nstatus = load_json_cmd', 1)[0], namespace)
    finally:
        sys.path[:] = original_sys_path
    namespace["_hermes_home"] = str(tmp_path)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    summary = namespace["_execution_gate_helper_completion_summary"](
        {"lane": {"name": "job"}},
        {"job": {"last_status": "ok", "last_run_at": now, "schedule": "* * * * *"}},
    )
    assert summary["helper_completion_reconciliation_status"] == "degraded"
    assert summary["helper_completion_reconciled_lanes"] == ["lane"]
    assert summary["helper_boundary_unobserved_count"] == 1
    assert summary["helper_completion_expected_count"] == (
        summary["helper_completion_completed_count"]
        + summary["helper_completion_missing_count"]
        + summary["helper_completion_reconciled_count"]
        + summary["helper_completion_disabled_count"]
    )


def test_execution_gate_disabled_job_is_not_reported_as_missing(tmp_path):
    from scripts import memory_os_3_200_monitor as monitor

    import sys
    namespace = {"__name__": "remote_probe_test"}
    original_sys_path = list(sys.path)
    try:
        exec(monitor._remote_probe_script().split('\nstatus = load_json_cmd', 1)[0], namespace)
    finally:
        sys.path[:] = original_sys_path
    namespace["_hermes_home"] = str(tmp_path)
    summary = namespace["_execution_gate_helper_completion_summary"](
        {"lane": {"name": "job"}},
        {"job": {"enabled": False, "last_status": "ok", "last_run_at": "2020-01-01T00:00:00Z", "schedule": "* * * * *"}},
    )
    assert summary["helper_completion_disabled_lanes"] == ["lane"]
    assert summary["helper_completion_disabled_count"] == 1
    assert summary["helper_completion_missing_lanes"] == []
    assert summary["helper_completion_missing_count"] == 0
    assert summary["helper_boundary_unobserved_count"] == 0
    assert summary["helper_completion_expected_count"] == (
        summary["helper_completion_completed_count"]
        + summary["helper_completion_missing_count"]
        + summary["helper_completion_reconciled_count"]
        + summary["helper_completion_disabled_count"]
    )


def test_execution_gate_disabled_job_with_no_last_status_is_still_disabled_not_missing(tmp_path):
    from scripts import memory_os_3_200_monitor as monitor

    import sys
    namespace = {"__name__": "remote_probe_test"}
    original_sys_path = list(sys.path)
    try:
        exec(monitor._remote_probe_script().split('\nstatus = load_json_cmd', 1)[0], namespace)
    finally:
        sys.path[:] = original_sys_path
    namespace["_hermes_home"] = str(tmp_path)
    summary = namespace["_execution_gate_helper_completion_summary"](
        {"lane": {"name": "job"}},
        {"job": {"enabled": False}},
    )
    assert summary["helper_completion_disabled_lanes"] == ["lane"]
    assert summary["helper_completion_missing_lanes"] == []


def test_ragflow_disabled_is_cron_success_through_host_wrapper(tmp_path):
    import json
    import os
    import shutil
    import subprocess
    import sys
    from pathlib import Path

    repo = Path(__file__).resolve().parents[3]
    home = tmp_path / ".hermes"
    scripts = home / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(repo / "scripts" / "memory_os_ragflow_readonly_probe.py", scripts)
    env = dict(
        os.environ,
        HERMES_HOME=str(home),
        MEMORY_OS_PYTHON_BIN=sys.executable,
        PYTHONPATH=str(repo),
    )
    result = subprocess.run(
        ["bash", str(repo / "scripts" / "external_evidence_ragflow_readonly_probe.sh")],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout)["status"] == "disabled"


def test_cadence_status_distinguishes_trigger_idle_scheduled_missing_and_unknown():
    from scripts.memory_os_monitor_dashboard_snapshot import _render_last_status

    assert _render_last_status(raw_status=None, cadence_class="on_signal") == "idle"
    assert _render_last_status(raw_status=None, cadence_class="daily") == "missing"
    assert _render_last_status(raw_status=None, cadence_class="unknown_custom") == "unobserved"


def test_latest_per_source_prefers_last_legacy_record_without_timestamp():
    from plugins.memory.memory_os.left_brain_advisor import _latest_per_source

    records = [
        {"projection_id": "old", "source_key": "mailbox_status", "payload": {"status": "error"}},
        {"projection_id": "new", "source_key": "mailbox_status", "payload": {"status": "ok"}},
    ]
    selected = _latest_per_source(records, governance_max=3, default_max=1)
    assert [item["projection_id"] for item in selected] == ["new"]


def test_left_brain_dedup_preserves_active_health_while_suppressing_notification():
    from plugins.memory.memory_os.left_brain_advisor import _build_findings

    projection = {
        "projection_id": "p1",
        "source_key": "mcp_server_health",
        "payload": {"status": "error"},
    }
    previous_keys: set[str] = set()
    cycle_findings = []
    for _ in range(4):
        findings = _build_findings(
            [projection],
            max_findings=10,
            suppress_dedup_keys=previous_keys,
        )
        assert len(findings) == 1  # health stays warning/active every cycle
        cycle_findings.append(findings[0])
        previous_keys = {findings[0]["dedup_key"]}
    assert [item["owner_visible"] for item in cycle_findings] == [True, False, False, False]
    assert cycle_findings[1]["notification_suppressed"] is True


def test_optional_missing_finding_is_informational_and_not_owner_visible():
    from plugins.memory.memory_os.left_brain_advisor import _build_findings

    projection = {
        "projection_id": "mailbox",
        "source_key": "mailbox_status",
        "payload": {"status": "missing", "available": False},
    }
    finding = _build_findings([projection], max_findings=10)[0]
    assert finding["owner_burden_class"] == "informational"
    assert finding["priority"] == "fyi"
    assert finding["owner_visible"] is False


def test_candidate_review_required_heading_survives_empty_builder(monkeypatch):
    from plugins.memory.memory_os import prefetch

    monkeypatch.setattr(prefetch, "build_prefetch_section_candidates", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        prefetch,
        "route_context_sections",
        lambda *args, **kwargs: {
            "route": "candidate_review",
            "selected_sections": [],
            "dropped_sections": [],
        },
    )
    result = prefetch._build_context_router_apply_prefetch(
        "请审查候选记忆",
        budget_chars=2000,
        store=object(),
        context_router_config={"apply_routes": ["candidate_review"]},
    )
    assert result is not None
    assert "## Crystallized Review Candidates" in result["context"]
    assert any(
        section.section == "Crystallized Review Candidates"
        and section.metadata.get("empty_body_placeholder") is True
        for section in result["selected_sections"]
    )


def test_required_headings_fail_closed_below_minimum_budget():
    from plugins.memory.memory_os.prefetch import HEADER, _fit_budget, _format

    required = {"Crystallized Review Candidates", "Crystallized Memory"}
    context = _format(
        [
            ("Crystallized Review Candidates", ["candidate evidence"]),
            ("Crystallized Memory", ["approved evidence"]),
        ]
    )
    headings_only = _format([(title, []) for title in required])
    minimum = len(headings_only)

    below = _fit_budget(context, minimum - 1, required_titles=required)
    assert below == HEADER
    assert not any(line.startswith("### ") for line in below.splitlines())

    for budget in (minimum, minimum + 1):
        fitted = _fit_budget(context, budget, required_titles=required)
        assert len(fitted) <= budget
        assert "### Crystallized Review Candidates" in fitted
        assert "### Crystallized Memory" in fitted


def test_candidate_review_preserves_both_required_headings_under_budget(monkeypatch):
    from plugins.memory.memory_os import prefetch
    from plugins.memory.memory_os.context_router import ContextSection

    candidates = [
        ContextSection(
            section="Crystallized Review Candidates",
            text="- candidate only: " + ("candidate evidence " * 90),
            source_class="candidate",
            metadata={},
        ),
        ContextSection(
            section="Crystallized Memory (deterministic floor recall)",
            text="- approved memory: " + ("approved evidence " * 120),
            source_class="crystallized",
            metadata={},
        ),
    ]
    monkeypatch.setattr(prefetch, "build_prefetch_section_candidates", lambda *args, **kwargs: candidates)

    result = prefetch._build_context_router_apply_prefetch(
        "那些 crystallized candidates 是已经沉淀的长期记忆吗？",
        budget_chars=2200,
        store=object(),
        context_router_config={"apply_routes": ["candidate_review"]},
    )

    assert result is not None
    assert "### Crystallized Review Candidates" in result["context"]
    assert "### Crystallized Memory (deterministic floor recall)" in result["context"]
    assert len(result["context"]) <= 2200


def test_active_task_required_indexed_recall_survives_empty_builder(monkeypatch):
    from plugins.memory.memory_os import prefetch

    monkeypatch.setattr(prefetch, "build_prefetch_section_candidates", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        prefetch,
        "route_context_sections",
        lambda *args, **kwargs: {
            "route": "active_task",
            "selected_sections": [],
            "dropped_sections": [],
        },
    )
    result = prefetch._build_context_router_apply_prefetch(
        "继续当前任务",
        budget_chars=2000,
        store=object(),
        context_router_config={"apply_routes": ["active_task"]},
    )
    assert result is not None
    assert "## Indexed Recall" in result["context"]
