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
    for index, name in enumerate(
        (
            "memory-os-owner-review-digest",
            "memory-os-right-brain-expression",
            "memory-os-module-cadence-report",
            "memory-os-right-brain-expression-outcome",
            "memory-os-proposal-followups-opsgate",
            "memory-os-expression-feedback-request",
            "memory-os-memory-sources-feedback-request",
        ),
        start=1,
    ):
        jobs.append(
            {
                "id": f"job-{index}",
                "name": name,
                "schedule": "*/30 * * * *",
                "deliver": "local" if index > 2 else "owner",
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
    assert snapshot["cron"]["enabled"] == 7
    assert {item["key"]: item["unit"] for item in snapshot["kpis"]}["cron_ok"] == "enabled jobs"
    assert snapshot["ownerReview"]["counts"]["action_required_shown"] == 1
    assert snapshot["ownerReview"]["queue"][0]["token"] == "oa_abcdef12"
    assert snapshot["memory"]["working"] == 1
    assert snapshot["memory"]["crystallized"] == 2
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
