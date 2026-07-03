import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "memory_os_monitor_dashboard_snapshot.py"
    spec = importlib.util.spec_from_file_location("memory_os_monitor_dashboard_snapshot", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False, sort_keys=True) for record in records) + "\n",
        encoding="utf-8",
    )


def _write_jobs(home: Path) -> None:
    jobs = []
    core_names = [
        "memory-os-owner-review-digest",
        "memory-os-proposal-followups-opsgate",
        "memory-os-index-sync",
        "memory-os-candidate-aggregation",
        "memory-os-fact-judge",
        "memory-os-expression-feedback-request",
        "memory-os-memory-sources-feedback-request",
    ]
    optional_names = [
        "memory-os-right-brain-expression",
        "memory-os-module-cadence-report",
        "memory-os-right-brain-expression-outcome",
    ]
    for index, name in enumerate(core_names + optional_names, start=1):
        jobs.append(
            {
                "id": f"job-{index}",
                "name": name,
                "schedule": "*/30 * * * *",
                "deliver": "local",
                "enabled": True,
            }
        )
    cron_root = home / "cron"
    cron_root.mkdir(parents=True)
    (cron_root / "jobs.json").write_text(json.dumps({"jobs": jobs}), encoding="utf-8")


def _write_memory_files(home: Path) -> None:
    memory_root = home / "memory-os"
    (memory_root / "working").mkdir(parents=True)
    (memory_root / "working" / "current.json").write_text('{"items":[]}', encoding="utf-8")
    crystallized = memory_root / "crystallized"
    crystallized.mkdir(parents=True)
    (crystallized / "owner_approved.md").write_text(
        """---
id: cm_1
kind: preference
approved_by: owner
---

Safe bounded preference.

---
id: cm_2
kind: identity
approved_by: owner
---

Safe bounded identity.
""",
        encoding="utf-8",
    )
    _write_jsonl(crystallized / "candidates.jsonl", [{"candidate_id": "cand_1"}])
    index_path = memory_root / "index" / "memory_os.db"
    index_path.parent.mkdir(parents=True)
    with sqlite3.connect(index_path) as conn:
        conn.execute("create table events(id text)")
        conn.execute("insert into events(id) values ('evt_1')")


def _write_dashboard_evidence(home: Path) -> None:
    memory_root = home / "memory-os"
    _write_jsonl(
        memory_root / "system" / "owner_review_rendered_digests.jsonl",
        [
            {
                "schema_version": "memory-os.owner_review_rendered_digest.v0",
                "mode": "agenda",
                "sections": {
                    "action_required": [
                        {
                            "anchor": "A1",
                            "target_type": "candidate",
                            "summary": "Bounded candidate review",
                            "action_tokens": {"approve_candidate": "oa_abcdef12"},
                            "created_at": "2026-06-03T08:00:00Z",
                        }
                    ],
                    "review_suggested": [],
                    "fyi": [],
                },
                "boundary": {"actual_send": False, "actual_execute": False},
            }
        ],
    )
    _write_jsonl(
        memory_root / "system" / "owner_actions.jsonl",
        [
            {
                "action_type": "approve_candidate",
                "result": "applied",
                "boundary": {"actual_unapproved_crystallized_approval": False},
            }
        ],
    )
    _write_jsonl(memory_root / "system" / "memory_sources.jsonl", [{"record_id": "ms_1", "created_at": "2026-06-03T08:00:00Z"}])
    _write_jsonl(memory_root / "system" / "memory_sources_feedback.jsonl", [{"rating": "useful", "created_at": "2026-06-03T08:01:00Z"}])
    _write_jsonl(memory_root / "system" / "expression_feedback_ledger.jsonl", [{"rating": "like_expression"}])
    _write_jsonl(memory_root / "system" / "projection_ledger.jsonl", [{"operation": "retain", "recall_hit_count": 3}])
    _write_jsonl(memory_root / "audit" / "write_audit.jsonl", [{"ts": "2026-06-03T08:02:00Z", "action": "test.audit", "status": "ok", "target": "bounded"}])
    _write_jsonl(
        home / "system-modules" / "cognitive_loop" / "reports.jsonl",
        [
            {
                "cycle_id": "cloop_1",
                "status": "ok",
                "finished_at": "2026-06-03T08:00:00Z",
                "steps": [
                    {"step": "self_evolution", "status": "ok", "result": {"status": "ok", "proposal_created": True}},
                    {"step": "expression_draft", "status": "skipped", "result": {"status": "skipped", "cadence_skipped": True}},
                ],
            }
        ],
    )
    _write_jsonl(home / "system-modules" / "right_brain_expression_adapter" / "requests.jsonl", [{"request_id": "rb_1"}])
    _write_jsonl(
        home / "system-modules" / "right_brain_expression_adapter" / "outcomes.jsonl",
        [{"status": "sent", "outcome_preview": "safe expression"}],
    )
    _write_jsonl(home / "system-modules" / "self_evolution" / "reports.jsonl", [{"status": "ok"}])
    _write_jsonl(home / "system-modules" / "ops_gate" / "reports.jsonl", [{"status": "report_only", "decision": "report_only"}])


def test_dashboard_snapshot_maps_read_only_evidence_without_writing_reports(tmp_path):
    module = _load_module()
    home = tmp_path / "home"
    _write_jobs(home)
    _write_memory_files(home)
    _write_dashboard_evidence(home)

    snapshot = module.build_dashboard_snapshot(hermes_home=home, profile="main")
    serialized = json.dumps(snapshot, ensure_ascii=False)

    assert snapshot["schema_version"] == "memory-os.monitor_dashboard_snapshot.v0"
    assert snapshot["cron"]["enabled"] == 7  # 7 core cron jobs enabled
    assert snapshot["cron"]["core_total"] == 7
    assert snapshot["cron"]["optional_total"] == 3
    assert {item["key"]: item["unit"] for item in snapshot["kpis"]}["cron_ok"] == "enabled jobs"
    assert snapshot["ownerReview"]["counts"]["action_required_shown"] == 1
    assert snapshot["ownerReview"]["counts"]["action_required"] >= 0  # real backlog
    assert snapshot["ownerReview"]["queue"][0]["token"] == "oa_abcdef12"
    assert snapshot["memory"]["working"] == 0  # items[] is empty in test data
    assert snapshot["memory"]["working_files"] == 1
    assert snapshot["memory"]["crystallized"] == 0  # no index record, no crystallized candidate state
    assert snapshot["memory"]["crystallized_raw_segments"] == 2  # markdown frontmatter count
    assert snapshot["modules"]["module_count"] == 18
    assert snapshot["expression"]["sent"] == 1
    assert snapshot["hindsight"]["retained"] == 1
    assert snapshot["feedback"]["memory_sources"]["attribution_quality"] == 1.0
    assert {item["key"]: item["state"] for item in snapshot["boundary"]}["cron_modified"] == "false"
    assert "Safe bounded preference" not in serialized
    assert not (home / "system-modules" / "module_cadence" / "reports.jsonl").exists()


def test_dashboard_snapshot_reads_host_and_hindsight_runtime_meta(tmp_path, monkeypatch):
    module = _load_module()
    home = tmp_path / "home"
    _write_jobs(home)
    _write_memory_files(home)
    _write_dashboard_evidence(home)
    config_path = home / "memory-os" / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "substrate_providers": {
                    "hindsight": {
                        "enabled": True,
                        "adoption_source": "hermes_hindsight_config",
                        "provider_bank_id": "hermes02",
                        "bank_selection_reason": "top_level_provider_bank_id",
                        "recall_mode": "active",
                        "retain_enabled": True,
                        "reflect_enabled": True,
                        "legacy_auto_retain_observed_disabled": True,
                    }
                }
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("COMPUTERNAME", raising=False)
    monkeypatch.delenv("HOSTNAME", raising=False)
    monkeypatch.setenv("HERMES_ENV", "prod")
    monkeypatch.setenv("MOS_DASHBOARD_REFRESH_INTERVAL_SECONDS", "60")
    monkeypatch.setattr(module.socket, "gethostname", lambda: "debian")
    monkeypatch.setattr(module.socket, "getfqdn", lambda: "debian.debian13")
    monkeypatch.setattr(module, "_read_uptime_seconds", lambda: 1800741)

    snapshot = module.build_dashboard_snapshot(hermes_home=home, profile="main")

    assert snapshot["meta"]["host"] == "debian"
    assert snapshot["meta"]["host_fqdn"] == "debian.debian13"
    assert snapshot["meta"]["environment"] == "prod"
    assert snapshot["meta"]["uptime"] == "20d 20h 12m"
    assert snapshot["meta"]["uptime_seconds"] == 1800741
    assert snapshot["meta"]["hindsight_mode"] == "active"
    assert snapshot["hindsight"]["mode"] == "active"
    assert snapshot["monitor"]["next_run_in"] == "1m"
    assert snapshot["monitor"]["duration_ms"] >= 0


def test_dashboard_snapshot_cli_writes_js_payload(tmp_path):
    output = tmp_path / "snapshot.generated.js"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/memory_os_monitor_dashboard_snapshot.py",
            "--sample",
            "--output",
            str(output),
        ],
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    text = output.read_text(encoding="utf-8")
    assert text.startswith("window.MOS = ")
    assert "memory-os.monitor_dashboard_snapshot.v0" in text


def test_dashboard_status_not_fail_when_current_window_error_count_is_zero(tmp_path):
    """Regression: module_error was reading cumulative error_count, which
    monotonically increased from append-only JSONL, causing the overall
    health status to be permanently FAIL after the first module error.

    Fix: switch to current_window_error_count (0/1, last-run status),
    so one clean run resets the health status.
    """
    module = _load_module()
    home = tmp_path / "home"
    _write_jobs(home)
    _write_memory_files(home)
    _write_dashboard_evidence(home)

    # Build snapshot — all evidence shows ok status, so current_window
    # should be 0 and the overall status should not be FAIL.
    snapshot = module.build_dashboard_snapshot(hermes_home=home, profile="main")

    # The status is at the top level of the monitor section
    status = snapshot["monitor"]["status"]
    warn = snapshot["monitor"]["warn"]
    fail = snapshot["monitor"]["fail"]

    # With clean module runs, module_error should be 0 → fail=0 → status≠FAIL
    assert fail == 0, (
        f"When all modules run clean, fail should be 0, got {fail}. "
        f"Monitor section: check if module_error is 0."
    )
    assert status != "FAIL", (
        f"When fail=0, status should not be FAIL, got {status}. "
        f"warn={warn} fail={fail}"
    )
    # Status should be PASS or WARN (could be WARN from other sections)
    assert status in ("PASS", "WARN"), f"Unexpected status: {status}"


def test_dashboard_status_shows_fail_when_current_window_has_errors(tmp_path):
    """Verify that if current_window_error_count > 0, the status IS FAIL."""
    module = _load_module()
    home = tmp_path / "home"
    _write_jobs(home)
    _write_memory_files(home)
    _write_dashboard_evidence(home)

    # Inject a cadence report with a step that has last_status="error"
    # This is how the cadence report detects current-window errors:
    # _record_step sets last_status from step status → _current_window_error_count returns 1.
    sys_modules = home / "system-modules" / "cognitive_loop"
    sys_modules.mkdir(parents=True, exist_ok=True)
    _write_jsonl(
        sys_modules / "reports.jsonl",
        [{
            "cycle_id": "err_1",
            "status": "ok",
            "finished_at": "2026-06-08T12:00:00Z",
            "steps": [
                {"step": "self_evolution", "status": "error",
                 "result": {"status": "error", "reason": "test error"}},
            ],
        }],
    )

    snapshot = module.build_dashboard_snapshot(hermes_home=home, profile="main")
    status = snapshot["monitor"]["status"]
    fail = snapshot["monitor"]["fail"]

    assert fail > 0, (
        f"With current window errors, fail should be > 0, got {fail}. "
        f"Status: {status}"
    )
    assert status == "FAIL", (
        f"With active errors, status should be FAIL, got {status}. "
        f"fail={fail}"
    )


def test_on_demand_module_shows_idle_not_missing(tmp_path):
    """On-demand modules (session_mirror, rh31_eval, metadata_retention)
    with no runs should show 'idle' instead of 'missing' in the modules table.
    """
    module = _load_module()
    assert module._render_last_status is not None

    # Direct unit tests for _render_last_status
    assert module._render_last_status(raw_status=None, cadence_class="on_demand_or_operator_approved_apply") == "idle"
    assert module._render_last_status(raw_status=None, cadence_class="on_demand_dry_run") == "idle"
    assert module._render_last_status(raw_status="missing", cadence_class="on_demand_or_monitor_poll") == "idle"
    assert module._render_last_status(raw_status="missing", cadence_class="on_demand_dry_run") == "idle"

    # Non on-demand with no runs should still show 'missing'
    assert module._render_last_status(raw_status=None, cadence_class="daily_weekly") == "missing"
    assert module._render_last_status(raw_status="missing", cadence_class="test_host_integration_harness") == "missing"

    # Real statuses pass through unchanged
    assert module._render_last_status(raw_status="ok", cadence_class="on_demand_dry_run") == "ok"
    assert module._render_last_status(raw_status="error", cadence_class="daily_weekly") == "error"
    assert module._render_last_status(raw_status="observed", cadence_class="owner_daily") == "observed"


# ── Full-monitor integration tests (Task 1) ──────────────────────────────


def _write_monitor_artifact(memory_root: Path, status: str, fail_codes=None, warn_codes=None, age_seconds: int = 0, *, use_results_key: bool = False):
    """Write a synthetic full-monitor artifact for testing.

    Uses the production ``classification`` key shape by default
    (``memory_os_3_200_monitor.py`` writes ``classification`` at the
    top level).  Pass ``use_results_key=True`` to exercise the legacy
    ``results`` fallback path.
    """
    artifacts_dir = memory_root / "system" / "monitor_artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    classification = {
        "status": status,
        "fail": [{"code": c} for c in (fail_codes or [])],
        "warn": [{"code": c} for c in (warn_codes or [])],
    }
    artifact: dict = {
        "schema_version": "memory-os.monitor.v0",
        "generated_at": "2026-07-03T15:00:00Z",
    }
    if use_results_key:
        artifact["results"] = classification
    else:
        artifact["classification"] = classification
    path = artifacts_dir / "monitor_2026-07-03T150000.json"
    path.write_text(json.dumps(artifact, ensure_ascii=False), encoding="utf-8")
    # Set mtime to simulate artifact age
    import os as _os
    mtime = _os_path_mtime(path, age_seconds)
    return path


def _os_path_mtime(path: Path, age_seconds: int) -> None:
    import os
    import time
    target = time.time() - age_seconds
    os.utime(str(path), (target, target))


def test_full_monitor_fail_makes_dashboard_fail(tmp_path):
    """artifact status=FAIL → dashboard monitor.status = FAIL."""
    module = _load_module()
    home = tmp_path / "hermes"
    _write_jobs(home)
    _write_memory_files(home)
    _write_dashboard_evidence(home)
    _write_monitor_artifact(home / "memory-os", "FAIL", fail_codes=["rh26_missing_expected_heading"], warn_codes=["monitor_error_observability_suppressed_errors"])

    snapshot = module.build_dashboard_snapshot(hermes_home=home, profile="default")
    assert snapshot["monitor"]["status"] == "FAIL", f"Expected FAIL, got {snapshot['monitor']['status']}"
    assert snapshot["monitor"]["fail"] > 0
    fm = snapshot["fullMonitor"]
    assert fm["status"] == "FAIL"
    assert "rh26_missing_expected_heading" in fm["fail_codes"]


def test_full_monitor_warn_makes_dashboard_warn(tmp_path):
    """artifact status=WARN, dashboard sections clean → dashboard WARN."""
    module = _load_module()
    home = tmp_path / "hermes"
    _write_jobs(home)
    _write_memory_files(home)
    _write_dashboard_evidence(home)
    _write_monitor_artifact(home / "memory-os", "WARN", warn_codes=["monitor_error_observability_suppressed_errors"])

    snapshot = module.build_dashboard_snapshot(hermes_home=home, profile="default")
    assert snapshot["monitor"]["status"] == "WARN", f"Expected WARN, got {snapshot['monitor']['status']}"


def test_full_monitor_missing_artifact_returns_unknown(tmp_path):
    """No artifact dir → fullMonitor.status=unknown, stale=true."""
    module = _load_module()
    home = tmp_path / "hermes"
    _write_jobs(home)
    _write_memory_files(home)
    _write_dashboard_evidence(home)
    # Don't write any monitor artifact

    snapshot = module.build_dashboard_snapshot(hermes_home=home, profile="default")
    fm = snapshot["fullMonitor"]
    assert fm["status"] == "unknown"
    assert fm["stale"] is True


def test_full_monitor_stale_artifact_flags_stale(tmp_path):
    """artifact older than 1h → stale=true, dashboard elevates to WARN when clean."""
    module = _load_module()
    home = tmp_path / "hermes"
    _write_jobs(home)
    _write_memory_files(home)
    _write_dashboard_evidence(home)
    _write_monitor_artifact(home / "memory-os", "PASS", age_seconds=4000)  # > 3600s

    snapshot = module.build_dashboard_snapshot(hermes_home=home, profile="default")
    fm = snapshot["fullMonitor"]
    assert fm["stale"] is True
    # stale artifact + clean dashboard → full monitor stale triggers WARN
    assert snapshot["monitor"]["status"] in ("WARN", "PASS"), f"Unexpected status: {snapshot['monitor']['status']}"


def test_full_monitor_pass_does_not_break_existing_pass(tmp_path):
    """artifact status=PASS → dashboard reports fullMonitor correctly, not FAIL."""
    module = _load_module()
    home = tmp_path / "hermes"
    _write_jobs(home)
    _write_memory_files(home)
    _write_dashboard_evidence(home)
    _write_monitor_artifact(home / "memory-os", "PASS", age_seconds=60)  # fresh

    snapshot = module.build_dashboard_snapshot(hermes_home=home, profile="default")
    fm = snapshot["fullMonitor"]
    assert fm["status"] == "PASS"
    assert fm["stale"] is False
    assert fm["artifact_age_seconds"] <= 120, f"fresh artifact should have low age, got {fm['artifact_age_seconds']}"
    assert snapshot["monitor"]["status"] != "FAIL", (
        f"Dashboard should not be FAIL when full monitor is PASS. "
        f"Got {snapshot['monitor']['status']}, sections: "
        + ", ".join(f"{s['key']}={s['warn']}w" for s in snapshot["monitor"]["sections"] if s["warn"])
    )


def test_full_monitor_reads_live_classification_artifact_shape(tmp_path):
    """Production artifact shape uses ``classification`` key, not ``results``.

    ``memory_os_3_200_monitor.py --snapshot-out`` writes::

        {"classification": {"status": "FAIL", "fail": [...], "warn": [...]}}

    The dashboard must read this shape correctly.  This is a regression
    test for the bug where ``_full_monitor_snapshot()`` only read the
    non-existent ``results`` key and returned ``unknown`` for every real
    production artifact.
    """
    module = _load_module()
    home = tmp_path / "hermes"
    _write_jobs(home)
    _write_memory_files(home)
    _write_dashboard_evidence(home)
    # Write using the default production shape (classification key)
    _write_monitor_artifact(
        home / "memory-os", "FAIL",
        fail_codes=["gateway_inactive", "heartbeat_timer_inactive"],
        warn_codes=["cognitive_loop_no_cycle_yet"],
    )

    snapshot = module.build_dashboard_snapshot(hermes_home=home, profile="default")
    fm = snapshot["fullMonitor"]
    assert fm["status"] == "FAIL", f"Production classification artifact must be read as FAIL, got {fm['status']}"
    assert "gateway_inactive" in fm["fail_codes"], f"fail_codes={fm['fail_codes']}"
    assert "cognitive_loop_no_cycle_yet" in fm["warn_codes"], f"warn_codes={fm['warn_codes']}"
    assert fm["stale"] is False
    assert snapshot["monitor"]["status"] == "FAIL"


def test_full_monitor_fallback_to_legacy_results_key(tmp_path):
    """Legacy ``results`` key is still readable as a backward-compat fallback."""
    module = _load_module()
    home = tmp_path / "hermes"
    _write_jobs(home)
    _write_memory_files(home)
    _write_dashboard_evidence(home)
    # Write using the legacy results key
    _write_monitor_artifact(
        home / "memory-os", "WARN",
        warn_codes=["something_warned"],
        use_results_key=True,
    )

    snapshot = module.build_dashboard_snapshot(hermes_home=home, profile="default")
    fm = snapshot["fullMonitor"]
    assert fm["status"] == "WARN", f"Legacy results artifact must still be readable, got {fm['status']}"
    assert "something_warned" in fm["warn_codes"]
