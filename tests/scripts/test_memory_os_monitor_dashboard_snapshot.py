import importlib.util
import json
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from plugins.memory.memory_os.cron_registry import memory_os_cron_specs
from plugins.memory.memory_os.legacy_right_brain_retirement import retire_legacy_right_brain


def _load_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "memory_os_monitor_dashboard_snapshot.py"
    spec = importlib.util.spec_from_file_location("memory_os_monitor_dashboard_snapshot", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _load_onboarding_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "memory_os_owner_cron_onboarding.py"
    spec = importlib.util.spec_from_file_location("memory_os_owner_cron_onboarding", path)
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


def _minimal_monitor_snapshot(module, full_monitor: dict):
    return module._monitor_snapshot(
        now=datetime.now(timezone.utc),
        profile="default",
        duration_ms=1,
        status_report={},
        cadence_report={},
        cron_jobs=[],
        owner={"counts": {}},
        memory={"index_fresh": True},
        expression={"drafts": 0, "sent": 0},
        hindsight={"mode": "disabled"},
        boundary=[],
        full_monitor=full_monitor,
    )


def test_invalid_full_monitor_is_fail_closed_not_weakened_to_warn():
    module = _load_module()
    snapshot = _minimal_monitor_snapshot(
        module,
        {"status": "unknown", "stale": True, "read_error": "v1_envelope_incomplete"},
    )
    assert snapshot["status"] == "UNKNOWN"
    assert snapshot["fail"] >= 1


def test_full_monitor_fail_remains_dashboard_fail():
    module = _load_module()
    snapshot = _minimal_monitor_snapshot(
        module,
        {"status": "FAIL", "stale": False, "read_error": None},
    )
    assert snapshot["status"] == "FAIL"
    assert snapshot["fail"] >= 1


def test_owner_backlog_failure_is_fail_visible_without_raw_candidate_fallback(tmp_path, monkeypatch):
    module = _load_module()
    memory_root = tmp_path / "memory-os"
    _write_jsonl(
        memory_root / "crystallized" / "candidates.jsonl",
        [{"candidate_id": "cand-raw", "bridge_state": "owner_eligible"}],
    )
    monkeypatch.setattr(module, "owner_review_queue_report", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    snapshot = module._owner_review_backlog_snapshot(memory_root)

    assert snapshot["agenda_source"] == "effective_owner_review_queue_unavailable"
    assert snapshot["backlog"]["pending_total"] == 0


def test_owner_aging_uses_effective_review_projection(tmp_path):
    module = _load_module()
    home = tmp_path / ".hermes"
    memory_root = home / "memory-os"
    _write_jsonl(
        memory_root / "crystallized" / "candidates.jsonl",
        [{
            "candidate_id": "cand-terminal",
            "kind": "fact",
            "body": "terminal candidate must not age in review",
            "bridge_state": "owner_eligible",
            "created_at": "2026-01-01T00:00:00Z",
        }],
    )
    _write_jsonl(
        memory_root / "crystallized" / "candidate_triage.jsonl",
        [{
            "candidate_id": "cand-terminal",
            "target_state": "demoted",
            "created_at": "2026-07-15T00:00:00Z",
        }],
    )

    snapshot = module._owner_aging_snapshot(memory_root)

    assert sum(snapshot["aging_buckets"].values()) == 0
    assert snapshot["source"] == "effective_owner_review_queue"


def test_execution_gate_snapshot_uses_canonical_stage_and_boundary_fields(tmp_path):
    module = _load_module()
    memory_root = tmp_path / "memory-os"
    _write_jsonl(
        memory_root / "system" / "execution_gate_envelopes.jsonl",
        [
            {
                "stage": "permit",
                "execution_gate_envelope_id": "xgate-resolver",
                "lane_id": "resolver_auto_approve",
                "boundary_true": False,
            },
            {
                "stage": "completion",
                "execution_gate_envelope_id": "xgate-resolver",
                "lane_id": "resolver_auto_approve",
                "postcheck_boundary_true": True,
            },
            {
                "stage": "permit",
                "execution_gate_envelope_id": "xgate-other",
                "lane_id": "other",
                "boundary_true": False,
            },
        ],
    )

    snapshot = module._execution_gate_snapshot(memory_root)

    assert snapshot["total_envelopes"] == 2
    assert snapshot["completions"] == 1
    assert snapshot["boundary_violations"] == 1
    assert snapshot["resolver_provisional_permits"] == 1
    assert snapshot["resolver_provisional_completions"] == 1
    assert snapshot["permanent_approvals"] == 0


def _core_cron_names() -> list[str]:
    """Core job names, derived from the registry rather than hand-typed.

    A hand-typed list silently rots whenever the cron surface changes (it did
    when per-lane jobs were consolidated into group ticks), which makes the
    fixture assert against a job set no host actually has.
    """
    return sorted(_load_module().CORE_MEMORY_OS_CRON)


def _write_jobs(home: Path) -> None:
    jobs = []
    core_names = _core_cron_names()
    optional_names = sorted(_load_module().OPTIONAL_MEMORY_OS_CRON) + [
        "memory-os-right-brain-expression",
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
    assert snapshot["cron"]["enabled"] == len(_core_cron_names())  # all core cron jobs enabled
    assert snapshot["cron"]["core_total"] == len(_core_cron_names())
    assert snapshot["cron"]["optional_total"] == 2
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


def test_v3_private_journal_distinguishes_operational_sweep_evidence_from_per_item_telemetry(tmp_path):
    module = _load_module()
    memory_root = tmp_path / "memory-os"
    _write_jsonl(
        memory_root / "system" / "execution_gate_envelopes.jsonl",
        [{
            "lane_id": "v3_journal_ttl_sweep",
            "stage": "completion",
            "scope": {"operation": "pending_ttl_sweep"},
        }],
    )

    snapshot = module._v3_private_journal_snapshot(memory_root)

    assert snapshot["per_item_annihilation_telemetry_persisted"] is False
    assert snapshot["sweep_execution_gate_evidence_persisted"] is True
    assert "annihilation_telemetry_persisted" not in snapshot


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
    _write_monitor_artifact(home / "memory-os", "PASS")

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
    _write_monitor_artifact(home / "memory-os", "PASS")

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

    # Trigger-gated modules without observed runs are legitimately idle.
    assert module._render_last_status(raw_status=None, cadence_class="on_demand_or_operator_approved_apply") == "idle"
    assert module._render_last_status(raw_status=None, cadence_class="on_demand_dry_run") == "idle"
    assert module._render_last_status(raw_status="missing", cadence_class="on_demand_or_monitor_poll") == "idle"
    assert module._render_last_status(raw_status="missing", cadence_class="on_demand_dry_run") == "idle"
    assert module._render_last_status(raw_status=None, cadence_class="on_signal") == "idle"

    # Scheduled cadence with no observed run is missing; an unknown cadence
    # is unobserved rather than silently healthy/idle.
    assert module._render_last_status(raw_status=None, cadence_class="daily_weekly") == "missing"
    assert module._render_last_status(raw_status="missing", cadence_class="test_host_integration_harness") == "unobserved"
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


def test_full_monitor_daily_artifact_stays_fresh_within_cadence_grace(tmp_path):
    """The daily 02:30 refresh contract keeps an artifact fresh for 30h."""
    module = _load_module()
    home = tmp_path / "hermes"
    _write_jobs(home)
    _write_memory_files(home)
    _write_dashboard_evidence(home)
    _write_monitor_artifact(home / "memory-os", "PASS", age_seconds=25 * 3600)

    snapshot = module.build_dashboard_snapshot(hermes_home=home, profile="default")
    assert snapshot["fullMonitor"]["stale"] is False


def test_full_monitor_stale_artifact_flags_stale(tmp_path):
    """Artifact older than the daily 30h grace is stale."""
    module = _load_module()
    home = tmp_path / "hermes"
    _write_jobs(home)
    _write_memory_files(home)
    _write_dashboard_evidence(home)
    _write_monitor_artifact(home / "memory-os", "PASS", age_seconds=31 * 3600)

    snapshot = module.build_dashboard_snapshot(hermes_home=home, profile="default")
    fm = snapshot["fullMonitor"]
    assert fm["stale"] is True
    # A stale canonical artifact is not current truth and must fail closed.
    assert snapshot["monitor"]["status"] == "UNKNOWN"
    assert snapshot["monitor"]["fail"] >= 1


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


def test_dashboard_exposes_shared_artifact_identity_and_count_conflict(tmp_path):
    module = _load_module()
    home = tmp_path / "hermes"
    _write_jobs(home)
    _write_memory_files(home)
    _write_dashboard_evidence(home)
    index_path = home / "memory-os" / "index" / "memory_os.db"
    with sqlite3.connect(index_path) as conn:
        conn.execute("create table crystallized_records(id text primary key)")
        conn.executemany(
            "insert into crystallized_records(id) values (?)",
            [(f"cm_{index}",) for index in range(31)],
        )
    generated_at = __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc
    ).isoformat().replace("+00:00", "Z")
    artifact_path = home / "memory-os" / "system" / "monitor_artifacts" / "monitor_enveloped.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        json.dumps({
            "schema_version": "memory-os.full_monitor_artifact.v1",
            "generated_at": generated_at,
            "source_head": "abc123",
            "runtime_digest": "sha256:runtime",
            "monitor_version": "memory-os.monitor.v0",
            "producer_receipt": {"receipt_id": "fmpr_1", "monitor_exit_code": 0},
            "classification": {"status": "PASS", "fail": [], "warn": []},
            "memory_status": {"counts": {
                "working_items": 999,
                "crystallized_candidates": 998,
                "crystallized_records": 13,
            }},
        }),
        encoding="utf-8",
    )

    snapshot = module.build_dashboard_snapshot(hermes_home=home, profile="default")
    full_monitor = snapshot["fullMonitor"]

    assert full_monitor["artifact_identity"]["source_head"] == "abc123"
    assert full_monitor["artifact_identity"]["producer_receipt_id"] == "fmpr_1"
    assert full_monitor["freshness"]["state"] == "fresh"
    observed = full_monitor["runtime_fields"]["crystallized_records"]
    assert observed["observed"] == {
        "dashboard.index.crystallized_records": 31,
        "full_monitor.memory_status.counts": 13,
    }
    assert observed["conflict"] is True
    assert observed["value"] is None
    for field in ("working_items", "crystallized_candidates", "crystallized_records"):
        assert full_monitor["runtime_fields"][field]["conflict"] is True
        assert snapshot["memory"]["display_counts"][field]["display"] == "conflict"
        assert snapshot["memory"]["display_counts"][field]["value"] is None
    kpis = {item["key"]: item for item in snapshot["kpis"]}
    assert kpis["working"]["display"] == "conflict"
    assert kpis["working"]["value"] is None
    assert kpis["crystallized"]["display"] == "conflict"
    assert kpis["crystallized"]["value"] is None
    assert kpis["candidates"]["display"] == "conflict"
    assert kpis["candidates"]["value"] is None
    dashboard_js = (Path(__file__).resolve().parents[2] / "monitor_dashboard" / "assets" / "dashboard.js").read_text()
    assert "k.display || fmt(k.value)" in dashboard_js
    assert "displayCount(data, \"working_items\"" in dashboard_js
    assert "hasCountConflict(data, \"working_items\")" in dashboard_js
    assert "hasCountConflict(data, \"crystallized_records\")" in dashboard_js
    assert "source conflict · raw trend hidden" in dashboard_js


def _job_name_for_lane(key):
    """The Hermes job that schedules a lane (its group tick after consolidation)."""
    from plugins.memory.memory_os.cron_registry import memory_os_cron_spec_by_key

    spec = memory_os_cron_spec_by_key(key)
    assert spec is not None, key
    return spec.name


def test_v3_crons_are_part_of_core_monitor_contract():
    module = _load_module()
    names = {
        _job_name_for_lane(key)
        for key in ("v3_seed_evidence", "v3_wandering", "v3_journal_sweep")
    }
    assert names.issubset(module.CORE_MEMORY_OS_CRON)


def test_no_agent_origin_job_is_not_misclassified_as_agent_work():
    module = _load_module()
    item = module._cron_job_snapshot(
        {
            "name": "memory-os-full-monitor-refresh",
            "deliver": "origin",
            "no_agent": True,
            "enabled": True,
        }
    )
    assert item["agent"] is False


def test_state_overlay_and_entity_index_are_part_of_core_monitor_contract():
    module = _load_module()
    names = {
        _job_name_for_lane(key)
        for key in ("state_overlay_refresh", "entity_index_refresh", "full_monitor_refresh")
    }
    assert names.issubset(module.CORE_MEMORY_OS_CRON)


def test_expression_feedback_is_optional_when_expression_is_disabled():
    module = _load_module()
    assert "memory-os-expression-feedback-request" not in module.CORE_MEMORY_OS_CRON
    assert "memory-os-expression-feedback-request" in module.OPTIONAL_MEMORY_OS_CRON


def test_core_and_optional_cron_sets_exhaustively_cover_the_registry():
    """Counterfactual for registry drift in the dashboard's cron health
    classification. CORE_MEMORY_OS_CRON and OPTIONAL_MEMORY_OS_CRON must
    together cover every name in memory_os_cron_specs() -- a name that
    falls into neither set silently lands in the "other" bucket
    (_cron_snapshot's other_jobs / classifications["other"]) and never
    increments missing_core or optional_paused, so the monitor never WARNs
    if that job is disabled or deleted on a host.

    Before this fix, memory-os-hindsight-advisory-digest,
    memory-os-hindsight-health-probe, and memory-os-clearance-cycle were
    all real registered, active-closure-installed cron jobs missing from
    both hand-typed sets. This test fails without the fix (both sets were
    static, hand-typed frozensets that predated those specs) and passes
    once CORE/OPTIONAL are derived from the registry.
    """
    module = _load_module()
    all_names = {spec.name for spec in memory_os_cron_specs()}

    assert module.CORE_MEMORY_OS_CRON.isdisjoint(module.OPTIONAL_MEMORY_OS_CRON)
    assert module.CORE_MEMORY_OS_CRON | module.OPTIONAL_MEMORY_OS_CRON == all_names


def test_hindsight_and_clearance_cron_are_not_left_unclassified():
    """Direct counterfactual for the three specific jobs identified as
    missing from the dashboard's hand-typed CORE/OPTIONAL sets.

    The two hindsight jobs are unconditionally onboarded on active-closure
    hosts, so their absence must WARN -- they belong in CORE.

    Deferral of a lane (clearance_cycle) is now enforced at LANE level -- the
    lane is left out of its group's member_keys in the installed snapshot --
    rather than by withholding a whole cron job. Its group tick
    (memory-os-tick-governance) is still installed for its core co-member
    proposal_followups_opsgate, so classifying that job CORE raises no
    spurious missing_core WARN.

    The invariant that must hold either way: every CORE job name is actually
    installed by active-closure onboarding, or the monitor WARNs forever.
    """
    module = _load_module()
    for name in (
        _job_name_for_lane("hindsight_advisory_digest"),
        _job_name_for_lane("hindsight_health_probe"),
    ):
        assert name in module.CORE_MEMORY_OS_CRON, name
        assert name not in module.OPTIONAL_MEMORY_OS_CRON, name

    # Nothing may be classified both CORE and OPTIONAL -- a group tick mixing
    # core and optional members would otherwise be counted as both missing
    # and paused.
    assert not (module.CORE_MEMORY_OS_CRON & module.OPTIONAL_MEMORY_OS_CRON)

    # Every CORE job must be one active-closure onboarding actually installs.
    from plugins.memory.memory_os.cron_registry import memory_os_cron_specs

    onboarding = _load_onboarding_module()
    installed_names = {
        spec.name
        for spec in memory_os_cron_specs()
        if spec.key not in onboarding.ACTIVE_CLOSURE_EXCLUDED_CRON_KEYS
    }
    missing = module.CORE_MEMORY_OS_CRON - installed_names
    assert not missing, (
        f"{sorted(missing)} classified CORE but not installed by active-closure "
        "onboarding, which would WARN on their expected absence"
    )


def test_retired_right_brain_is_removed_from_active_cron_surface(tmp_path):
    module = _load_module()
    home = tmp_path / "hermes"
    _write_jobs(home)
    _write_memory_files(home)
    _write_dashboard_evidence(home)
    jobs_path = home / "cron" / "jobs.json"
    jobs = json.loads(jobs_path.read_text(encoding="utf-8"))
    for job in jobs["jobs"]:
        if job["name"] in module.LEGACY_CRON_NAMES:
            job["enabled"] = False
            job["state"] = "paused"
    jobs_path.write_text(json.dumps(jobs) + "\n", encoding="utf-8")
    config_path = home / "memory-os" / "config.json"
    config_path.write_text(
        json.dumps({"right_brain_expression": {"legacy_cognitive_loop_enabled": False}}) + "\n",
        encoding="utf-8",
    )

    retired = retire_legacy_right_brain(home, apply=True)
    recreated = home / "system-modules" / "right_brain_expression_adapter"
    recreated.mkdir(parents=True)
    (recreated / "requests.jsonl").write_text('{"body":"PRIVATE_RECREATED_BODY"}\n', encoding="utf-8")
    (recreated / "outcomes.jsonl").write_text('{"actual_send":true}\n', encoding="utf-8")
    snapshot = module.build_dashboard_snapshot(hermes_home=home, profile="default")

    assert retired["retirement"]["status"] == "ok"
    assert snapshot["legacyRightBrainArchive"]["lifecycle"] == "retired"
    assert snapshot["legacyRightBrainArchive"]["raw_body_included"] is False
    active_job_names = {job["name"] for job in snapshot["cron"]["jobs"]}
    assert active_job_names.isdisjoint(module.LEGACY_CRON_NAMES)
    assert snapshot["expression"]["sent"] == 0
    assert snapshot["expression"]["outcomes_recorded"] == 0


def test_dashboard_snapshot_script_bootstraps_from_installed_layout(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    source_script = repo_root / "scripts" / "memory_os_monitor_dashboard_snapshot.py"
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir(parents=True)
    installed = scripts_dir / source_script.name
    shutil.copy2(source_script, installed)
    shutil.copy2(repo_root / "scripts" / "memory_os_module_cadence_report.py", scripts_dir)
    runtime = tmp_path / "memory-os" / "runtime" / "python"
    runtime.parent.mkdir(parents=True)
    runtime.symlink_to(repo_root, target_is_directory=True)

    completed = subprocess.run(
        [sys.executable, str(installed), "--hermes-home", str(tmp_path), "--help"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "--hermes-home" in completed.stdout


def _write_v3_inner_life_config(memory_root: Path, *, wandering_enabled: bool, synthesis_admission_enabled: bool = False) -> None:
    memory_root.mkdir(parents=True, exist_ok=True)
    (memory_root / "config.json").write_text(
        json.dumps({
            "v3_inner_life": {
                "wandering_enabled": wandering_enabled,
                "synthesis_admission_enabled": synthesis_admission_enabled,
            }
        }),
        encoding="utf-8",
    )


def test_wandering_admission_status_disabled_when_flag_off(tmp_path):
    module = _load_module()
    memory_root = tmp_path / "memory-os"
    _write_v3_inner_life_config(memory_root, wandering_enabled=False)

    snapshot = module._v3_inner_life_snapshot(memory_root, v3_seed_evidence={"activation_evidence_ready": True})

    assert snapshot["wandering_admission_status"] == "disabled"
    # Additive: existing raw fields remain unchanged.
    assert snapshot["wandering_enabled"] is False


def test_wandering_admission_status_blocked_when_seed_evidence_not_ready(tmp_path):
    """Fix 4: wandering_enabled=true with seed evidence not ready must read as
    configured_on_but_admission_blocked(reason=seed_evidence_not_ready), per
    the quiet-cognitive-partner plan (9.1) — not R3 active/validated."""
    module = _load_module()
    memory_root = tmp_path / "memory-os"
    _write_v3_inner_life_config(memory_root, wandering_enabled=True)

    snapshot = module._v3_inner_life_snapshot(
        memory_root,
        v3_seed_evidence={"activation_evidence_ready": False, "valid_day_count": 0, "consecutive_valid_day_count": 0},
    )

    assert snapshot["wandering_admission_status"] == "configured_on_but_admission_blocked(reason=seed_evidence_not_ready)"
    assert snapshot["wandering_enabled"] is True


def test_wandering_admission_status_pending_owner_gate_when_evidence_ready(tmp_path):
    module = _load_module()
    memory_root = tmp_path / "memory-os"
    _write_v3_inner_life_config(memory_root, wandering_enabled=True, synthesis_admission_enabled=False)

    snapshot = module._v3_inner_life_snapshot(memory_root, v3_seed_evidence={"activation_evidence_ready": True})

    assert snapshot["wandering_admission_status"] == "admission_evidence_ready_owner_gate_pending"


def test_wandering_admission_status_active_when_owner_gate_granted(tmp_path):
    module = _load_module()
    memory_root = tmp_path / "memory-os"
    _write_v3_inner_life_config(memory_root, wandering_enabled=True, synthesis_admission_enabled=True)

    snapshot = module._v3_inner_life_snapshot(memory_root, v3_seed_evidence={"activation_evidence_ready": True})

    assert snapshot["wandering_admission_status"] == "admission_active"


def test_wandering_admission_status_treats_missing_seed_evidence_as_not_ready(tmp_path):
    """A malformed/missing v3_seed_evidence snapshot must fail closed to
    'not ready' rather than crash or default to evidence-ready."""
    module = _load_module()
    memory_root = tmp_path / "memory-os"
    _write_v3_inner_life_config(memory_root, wandering_enabled=True)

    snapshot = module._v3_inner_life_snapshot(memory_root, v3_seed_evidence={})

    assert snapshot["wandering_admission_status"] == "configured_on_but_admission_blocked(reason=seed_evidence_not_ready)"


def test_dashboard_snapshot_wires_v3_seed_evidence_into_inner_life_composite(tmp_path):
    """End-to-end: build_dashboard_snapshot must pass the already-computed
    v3SeedEvidence into v3InnerLife so wandering_admission_status reflects
    real seed-evidence state, not a hardcoded default."""
    module = _load_module()
    home = tmp_path / "home"
    memory_root = home / "memory-os"
    _write_jobs(home)
    _write_memory_files(home)
    _write_dashboard_evidence(home)
    _write_v3_inner_life_config(memory_root, wandering_enabled=True)
    (memory_root / "system").mkdir(parents=True, exist_ok=True)
    (memory_root / "system" / "v3_seed_evidence_snapshot.json").write_text(
        json.dumps({
            "schema_version": "memory-os.v3_seed_evidence_snapshot.v0",
            "valid_day_count": 0,
            "consecutive_valid_day_count": 0,
            "activation_evidence_ready": False,
        }),
        encoding="utf-8",
    )

    snapshot = module.build_dashboard_snapshot(hermes_home=home, profile="default")

    assert snapshot["v3SeedEvidence"]["activation_evidence_ready"] is False
    assert (
        snapshot["v3InnerLife"]["wandering_admission_status"]
        == "configured_on_but_admission_blocked(reason=seed_evidence_not_ready)"
    )


def test_v3_seed_evidence_latest_fields_use_only_natural_cron_rows(tmp_path):
    """P3 #15: latest_valid, latest_coverage_ratio, latest_cursor_contiguous,
    latest_invalid_reasons must reflect ONLY natural_cron rows for consistency
    with the gated counts (valid_day_count, latest_natural_date, etc.).

    Counterfactual: a valid natural_cron row followed by an invalid manual row
    in the daily file. The latest_* fields must show the natural row's values,
    not the manual row's invalid state."""
    module = _load_module()
    memory_root = tmp_path / "memory-os"

    # Write snapshot with one valid day (from natural_cron row)
    _write_jsonl(
        memory_root / "system" / "v3_seed_evidence_snapshot.json" if False else (memory_root / "system" / "v3_seed_evidence_snapshot.json"),
        [{"valid_day_count": 1, "consecutive_valid_day_count": 1, "activation_evidence_ready": False}],
    )
    (memory_root / "system" / "v3_seed_evidence_snapshot.json").write_text(
        json.dumps({
            "schema_version": "memory-os.v3_seed_evidence_snapshot.v0",
            "valid_day_count": 1,
            "consecutive_valid_day_count": 1,
            "activation_evidence_ready": False,
            "latest_natural_date": "2026-07-12",
        }),
        encoding="utf-8",
    )

    # Write daily rows: valid natural_cron row, then a later invalid manual row
    _write_jsonl(
        memory_root / "system" / "v3_seed_edges_daily.jsonl",
        [
            {
                "schema_version": "memory-os.v3_seed_edges_daily.v0",
                "natural_date": "2026-07-12",
                "created_at": "2026-07-13T00:00:00Z",
                "valid": True,
                "coverage_ratio": 0.95,
                "source_cursor_contiguous": True,
                "invalid_reasons": [],
                "trigger_class": "natural_cron",
            },
            {
                "schema_version": "memory-os.v3_seed_edges_daily.v0",
                "natural_date": "2026-07-12",
                "created_at": "2026-07-14T00:00:00Z",  # Later than natural row
                "valid": False,
                "coverage_ratio": 0.0,
                "source_cursor_contiguous": False,
                "invalid_reasons": ["insufficient_coverage"],
                "trigger_class": "manual",
            },
        ],
    )

    snapshot = module._v3_seed_evidence_snapshot(memory_root)

    # latest_* fields must reflect the natural_cron row, not the manual row
    assert snapshot["latest_valid"] is True, "latest_valid should use natural_cron row"
    assert snapshot["latest_coverage_ratio"] == 0.95, "latest_coverage_ratio should use natural_cron row"
    assert snapshot["latest_cursor_contiguous"] is True, "latest_cursor_contiguous should use natural_cron row"
    assert snapshot["latest_invalid_reasons"] == [], "latest_invalid_reasons should use natural_cron row"


def test_v3_seed_evidence_latest_fields_empty_when_no_natural_cron_rows(tmp_path):
    """P3 #15: when daily file contains ONLY manual/legacy rows (no natural_cron),
    latest_* display fields must show empty-row defaults (False/0.0/[]) for
    consistency with the gate counts showing no valid days."""
    module = _load_module()
    memory_root = tmp_path / "memory-os"
    system_dir = memory_root / "system"
    system_dir.mkdir(parents=True, exist_ok=True)

    # Write snapshot with zero valid days (no natural_cron rows exist)
    (system_dir / "v3_seed_evidence_snapshot.json").write_text(
        json.dumps({
            "schema_version": "memory-os.v3_seed_evidence_snapshot.v0",
            "valid_day_count": 0,
            "consecutive_valid_day_count": 0,
            "activation_evidence_ready": False,
            "latest_natural_date": "",
        }),
        encoding="utf-8",
    )

    # Write daily rows with ONLY manual rows (no natural_cron)
    _write_jsonl(
        memory_root / "system" / "v3_seed_edges_daily.jsonl",
        [
            {
                "schema_version": "memory-os.v3_seed_edges_daily.v0",
                "natural_date": "2026-07-12",
                "created_at": "2026-07-13T00:00:00Z",
                "valid": True,
                "coverage_ratio": 0.99,
                "source_cursor_contiguous": True,
                "invalid_reasons": [],
                "trigger_class": "manual",
            },
            {
                "schema_version": "memory-os.v3_seed_edges_daily.v0",
                "natural_date": "2026-07-13",
                "created_at": "2026-07-14T00:00:00Z",
                "valid": False,
                "coverage_ratio": 0.5,
                "source_cursor_contiguous": False,
                "invalid_reasons": ["low_coverage"],
                "trigger_class": "manual",
            },
        ],
    )

    snapshot = module._v3_seed_evidence_snapshot(memory_root)

    # All latest_* fields must use empty-row defaults: no natural_cron rows exist
    assert snapshot["latest_valid"] is False, "latest_valid should default to False when no natural_cron rows"
    assert snapshot["latest_coverage_ratio"] == 0.0, "latest_coverage_ratio should default to 0.0 when no natural_cron rows"
    assert snapshot["latest_cursor_contiguous"] is False, "latest_cursor_contiguous should default to False when no natural_cron rows"
    assert snapshot["latest_invalid_reasons"] == [], "latest_invalid_reasons should default to [] when no natural_cron rows"
