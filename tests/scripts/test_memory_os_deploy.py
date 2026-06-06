import json
import subprocess
import sys
from pathlib import Path

from scripts.deploy_memory_os import (
    _classify_boundary_runtime_probe,
    _classify_cron_adapter_probe,
    _classify_llm_judge_probe,
    classify_deploy_report,
    deploy_memory_os,
    render_deploy_plan,
)


def test_deploy_script_plan_bootstraps_repo_import_path(tmp_path):
    script = Path(__file__).resolve().parents[2] / "scripts" / "deploy_memory_os.py"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--repo-root",
            str(tmp_path),
            "--hermes-home",
            "/root/.hermes",
            "--phase",
            "plan",
            "--output",
            "json",
        ],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0
    assert json.loads(result.stdout)["schema_version"] == "memory-os.deploy.v0"


def _llm_judge_probe_result():
    return {
        "exit_code": 0,
        "stdout": json.dumps(
            {
                "schema_version": "memory-os.low_clue_recall.v0",
                "candidate_count": 1,
                "llm_judge": {
                    "status": "ok",
                    "mode": "bounded_vote",
                    "provider": "hermes_default",
                    "resolved_model": "deepseek-v4-flash",
                    "api_mode": "chat_completions",
                },
                "boundaries": {
                    "actual_send": False,
                    "actual_execute": False,
                    "actual_canonical_write": False,
                },
            }
        ),
        "stderr": "",
    }


def _cron_adapter_probe_result():
    return {
        "exit_code": 0,
        "stdout": json.dumps(
            {
                "schema_version": "memory-os.hermes_cron_adapter_probe.v0",
                "status": "ok",
                "capabilities": {"status": "ok"},
                "classification": {
                    "memory_os_owned_naked_count": 0,
                    "memory_os_like_unregistered_count": 0,
                    "unclassified_count": 0,
                },
            }
        ),
        "stderr": "",
    }


def _boundary_runtime_probe_result():
    return {
        "exit_code": 0,
        "stdout": json.dumps(
            {
                "schema_version": "memory-os.boundary_runtime_probe.v0",
                "status": "ok",
                "findings": [],
                "permanent_boundary_counters": {
                    "unapproved_or_automatic_crystallized_write_count": 0,
                    "actual_hindsight_write_count": 0,
                    "actual_hindsight_delete_count": 0,
                    "actual_hindsight_demote_count": 0,
                    "actual_route_score_write_count": 0,
                    "actual_identity_relationship_write_count": 0,
                    "actual_external_send_count": 0,
                    "unbounded_autonomous_action_count": 0,
                    "execution_gate_permit_boundary_true_count": 0,
                    "execution_gate_completion_boundary_true_count": 0,
                },
                "execution_gate": {
                    "permit_count": 1,
                    "completion_count": 1,
                    "permit_boundary_true_count": 0,
                    "completion_postcheck_boundary_true_count": 0,
                },
                "structural_write_gate": {
                    "status": "available",
                    "append_governed_jsonl_available": True,
                },
            }
        ),
        "stderr": "",
    }


def _deployment_manifest_result():
    return {
        "exit_code": 0,
        "stdout": json.dumps(
            {
                "schema_version": "memory-os.deployment_runtime_manifest.v0",
                "status": "present",
                "deployed_head": "abc123",
                "deployed_at": "2026-06-03T01:00:00Z",
            }
        ),
        "stderr": "",
    }


def _probe_json(*, status="ok", boundaries=None):
    return {
        "json": {
            "schema_version": "memory-os.low_clue_recall.v0",
            "candidate_count": 0,
            "llm_judge": {
                "status": status,
                "mode": "report_only",
                "provider": "hermes_default",
            },
            "boundaries": boundaries
            if boundaries is not None
            else {
                "actual_send": False,
                "actual_execute": False,
                "actual_canonical_write": False,
            },
        }
    }


def test_llm_judge_probe_classifies_insufficient_context_as_pass_when_boundaries_false():
    classified = _classify_llm_judge_probe(_probe_json(status="insufficient_context"))

    assert classified["status"] == "pass"


def test_llm_judge_probe_fails_when_boundary_true_even_if_judge_status_is_valid():
    classified = _classify_llm_judge_probe(
        _probe_json(
            status="success",
            boundaries={
                "actual_send": False,
                "actual_execute": False,
                "actual_canonical_write": True,
            },
        )
    )

    assert classified["status"] == "fail"
    assert classified["reason"] == "llm_judge_probe_boundary_true"
    assert classified["boundary_true_paths"] == ["actual_canonical_write"]


def test_llm_judge_probe_fails_on_any_true_boundary_key_from_report_schema():
    classified = _classify_llm_judge_probe(
        _probe_json(
            status="success",
            boundaries={
                "actual_send": False,
                "actual_execute": False,
                "actual_crystallized_approval": True,
                "actual_relationship_write": False,
                "hindsight_exported": False,
            },
        )
    )

    assert classified["status"] == "fail"
    assert classified["reason"] == "llm_judge_probe_boundary_true"
    assert classified["boundary_true_paths"] == ["actual_crystallized_approval"]


def test_cron_adapter_probe_fails_on_naked_memory_os_jobs():
    classified = _classify_cron_adapter_probe(
        {
            "json": {
                "schema_version": "memory-os.hermes_cron_adapter_probe.v0",
                "status": "ok",
                "capabilities": {"status": "ok"},
                "classification": {
                    "memory_os_owned_naked_count": 1,
                    "memory_os_like_unregistered_count": 0,
                    "unclassified_count": 0,
                },
            }
        }
    )

    assert classified["status"] == "fail"
    assert "cron_adapter_memory_os_naked_jobs" in classified["reason"]


def test_cron_adapter_probe_passes_on_wrapped_jobs():
    classified = _classify_cron_adapter_probe(
        {
            "json": {
                "schema_version": "memory-os.hermes_cron_adapter_probe.v0",
                "status": "ok",
                "capabilities": {"status": "ok"},
                "classification": {
                    "memory_os_owned_naked_count": 0,
                    "memory_os_like_unregistered_count": 0,
                    "unclassified_count": 0,
                },
            }
        }
    )

    assert classified["status"] == "pass"


def test_boundary_runtime_probe_fails_on_high_risk_counter():
    result = _boundary_runtime_probe_result()
    data = json.loads(result["stdout"])
    data["permanent_boundary_counters"]["actual_hindsight_write_count"] = 1
    classified = _classify_boundary_runtime_probe({"json": data})

    assert classified["status"] == "fail"
    assert "actual_hindsight_write_count" in classified["reason"]


def test_boundary_runtime_probe_passes_when_boundaries_and_write_gate_are_clean():
    result = _boundary_runtime_probe_result()
    classified = _classify_boundary_runtime_probe({"json": json.loads(result["stdout"])})

    assert classified["status"] == "pass"


def test_plan_phase_includes_hindsight_and_no_restart_by_default(tmp_path):
    report = deploy_memory_os(
        repo_root=tmp_path,
        hermes_home="/root/.hermes",
        mode="production-safe",
        hindsight_mode="auto",
        phase="plan",
        profile="fresh",
    )

    rendered = render_deploy_plan(report)

    assert report["schema_version"] == "memory-os.deploy.v0"
    assert report["phase"] == "plan"
    assert report["profile"] == "fresh"
    assert report["restart_requested"] is False
    assert "--hindsight auto" in rendered
    assert "--llm-judge-preset active" in rendered
    assert "--production-safe" in rendered
    assert "SECRET" not in json.dumps(report, ensure_ascii=False)


def test_plan_phase_allows_hindsight_active_cutover(tmp_path):
    report = deploy_memory_os(
        repo_root=tmp_path,
        hermes_home="/root/.hermes",
        mode="operational",
        hindsight_mode="active",
        phase="plan",
        profile="upgrade",
    )

    rendered = render_deploy_plan(report)

    assert report["hindsight_mode"] == "active"
    assert "--hindsight active" in rendered


def test_plan_phase_includes_deployment_runtime_manifest_commands(tmp_path):
    report = deploy_memory_os(
        repo_root=tmp_path,
        hermes_home="/root/.hermes",
        mode="production-safe",
        hindsight_mode="auto",
        phase="plan",
        profile="upgrade",
    )
    commands = report["commands"]

    assert "deployment_manifest_write" in commands
    assert "deployment_manifest_status" in commands
    assert "deployment-manifest write" in " ".join(commands["deployment_manifest_write"])
    assert "--install-profile upgrade" in " ".join(commands["deployment_manifest_write"])


def test_apply_phase_writes_and_verifies_deployment_runtime_manifest(tmp_path):
    calls: list[str] = []

    def fake_runner(argv, *, host=None, timeout=30):
        command = " ".join(argv)
        calls.append(command)
        if "memory_os_upgrade_compat_check.py" in command:
            return {
                "exit_code": 0,
                "stdout": json.dumps(
                    {
                        "schema_version": "memory-os.hermes_upgrade_compat.v0",
                        "classification": {"pass": [{"code": "memory_provider_active"}], "warn": [], "fail": []},
                    }
                ),
                "stderr": "",
            }
        if "install_memory_os.sh" in command:
            return {
                "exit_code": 0,
                "stdout": json.dumps({"schema_version": "memory-os.install.v0", "dry_run": "--dry-run" in command}),
                "stderr": "",
            }
        if "deployment-manifest write" in command or "deployment-manifest status" in command:
            return {
                "exit_code": 0,
                "stdout": json.dumps(
                    {
                        "schema_version": "memory-os.deployment_runtime_manifest.v0",
                        "status": "present",
                        "deployed_head": "abc123",
                        "deployed_at": "2026-06-03T01:00:00Z",
                    }
                ),
                "stderr": "",
            }
        if "memory_os_cron_adapter_probe.py" in command:
            return _cron_adapter_probe_result()
        if "memory_os_boundary_runtime_probe.py" in command:
            return _boundary_runtime_probe_result()
        if "low-clue-recall" in command:
            return _llm_judge_probe_result()
        if "deployment-manifest" in command:
            return _deployment_manifest_result()
        raise AssertionError(f"unexpected command: {command}")

    report = deploy_memory_os(
        repo_root=tmp_path,
        hermes_home="/root/.hermes",
        mode="production-safe",
        hindsight_mode="auto",
        phase="apply",
        profile="upgrade",
        run_command=fake_runner,
    )

    assert report["deployment_manifest_write"]["status"] == "pass"
    assert report["deployment_manifest_status"]["status"] == "pass"
    assert any("deployment-manifest write" in call for call in calls)


def test_upgrade_profile_blocks_apply_when_preflight_compat_fails(tmp_path):
    def fake_runner(argv, *, host=None, timeout=30):
        command = " ".join(argv)
        if "memory_os_upgrade_compat_check.py" in command:
            return {
                "exit_code": 1,
                "stdout": json.dumps(
                    {
                        "schema_version": "memory-os.hermes_upgrade_compat.v0",
                        "classification": {
                            "pass": [],
                            "warn": [],
                            "fail": [{"code": "memory_provider_not_memory_os"}],
                        },
                    }
                ),
                "stderr": "",
            }
        if "memory_os_cron_adapter_probe.py" in command:
            return _cron_adapter_probe_result()
        if "memory_os_boundary_runtime_probe.py" in command:
            return _boundary_runtime_probe_result()
        if "low-clue-recall" in command:
            return _llm_judge_probe_result()
        if "deployment-manifest" in command:
            return _deployment_manifest_result()
        raise AssertionError(f"unexpected command: {command}")

    report = deploy_memory_os(
        repo_root=tmp_path,
        hermes_home="/root/.hermes",
        mode="operational",
        hindsight_mode="auto",
        phase="apply",
        profile="upgrade",
        run_command=fake_runner,
    )

    classification = classify_deploy_report(report)

    assert report["preflight"]["status"] == "fail"
    assert report["apply"]["status"] == "blocked"
    assert {"code": "preflight_compat_failed"} in classification["fail"]


def test_fresh_profile_allows_preinstall_provider_mismatch_but_requires_postcheck(tmp_path):
    calls = []

    def fake_runner(argv, *, host=None, timeout=30):
        calls.append(tuple(argv))
        command = " ".join(argv)
        if "memory_os_upgrade_compat_check.py" in command and len(calls) == 1:
            return {
                "exit_code": 1,
                "stdout": json.dumps(
                    {
                        "schema_version": "memory-os.hermes_upgrade_compat.v0",
                        "classification": {
                            "pass": [],
                            "warn": [],
                            "fail": [{"code": "memory_provider_not_memory_os"}],
                        },
                    }
                ),
                "stderr": "",
            }
        if "install_memory_os.sh" in command:
            is_dry_run = "--dry-run" in command
            return {
                "exit_code": 0,
                "stdout": (
                    "Memory-OS install preflight\n"
                    + json.dumps(
                        {
                            "schema_version": "memory-os.install.v0",
                            "dry_run": is_dry_run,
                            "hindsight_adoption": {
                                "planned_config": {"enabled": True, "recall_mode": "shadow"}
                            },
                        }
                    )
                    + "\nMemory-OS install complete.\n"
                    + json.dumps({"schema_version": "memory-os.owner_cron_onboarding.v0", "status": "ok"})
                ),
                "stderr": "",
            }
        if "memory_os_upgrade_compat_check.py" in command:
            return {
                "exit_code": 0,
                "stdout": json.dumps(
                    {
                        "schema_version": "memory-os.hermes_upgrade_compat.v0",
                        "classification": {
                            "pass": [{"code": "memory_provider_active"}],
                            "warn": [],
                            "fail": [],
                        },
                    }
                ),
                "stderr": "",
            }
        if "memory_os_cron_adapter_probe.py" in command:
            return _cron_adapter_probe_result()
        if "memory_os_boundary_runtime_probe.py" in command:
            return _boundary_runtime_probe_result()
        if "low-clue-recall" in command:
            return _llm_judge_probe_result()
        if "deployment-manifest" in command:
            return _deployment_manifest_result()
        raise AssertionError(f"unexpected command: {command}")

    report = deploy_memory_os(
        repo_root=tmp_path,
        hermes_home="/root/.hermes",
        mode="production-safe",
        hindsight_mode="off",
        phase="apply",
        profile="fresh",
        run_command=fake_runner,
    )

    classification = classify_deploy_report(report)

    assert report["preflight"]["status"] == "warn_expected_for_fresh"
    assert report["apply"]["status"] == "applied"
    assert report["postcheck"]["status"] == "pass"
    assert classification["fail"] == []


def test_fresh_profile_allows_missing_memory_os_shell_before_install(tmp_path):
    calls = []

    def fake_runner(argv, *, host=None, timeout=30):
        calls.append(tuple(argv))
        command = " ".join(argv)
        if "memory_os_upgrade_compat_check.py" in command and len(calls) == 1:
            return {
                "exit_code": 1,
                "stdout": json.dumps(
                    {
                        "schema_version": "memory-os.hermes_upgrade_compat.v0",
                        "classification": {
                            "pass": [{"code": "hermes_version_command_ok"}, {"code": "memory_provider_command_ok"}],
                            "warn": [],
                            "fail": [
                                {"code": "shell_status_command_failed", "exit_code": 2},
                                {"code": "shell_doctor_command_failed", "exit_code": 2},
                                {"code": "hindsight_status_command_failed", "exit_code": 2},
                                {"code": "modules_status_command_failed", "exit_code": 2},
                                {"code": "modules_doctor_command_failed", "exit_code": 2},
                                {"code": "modules_run_once_cron_mirror_dry_run_command_failed", "exit_code": 2},
                                {"code": "modules_validate_no_send_command_failed", "exit_code": 2},
                                {"code": "low_clue_recall_command_failed", "exit_code": 2},
                                {"code": "memory_sources_stats_command_failed", "exit_code": 2},
                                {"code": "memory_provider_not_memory_os"},
                                {"code": "shell_status_schema_mismatch", "expected": "memory-os.status.v0"},
                                {"code": "shell_doctor_missing_json"},
                                {"code": "hindsight_status_missing_json"},
                                {"code": "modules_status_schema_mismatch", "expected": "memory-os.modules_status.v0"},
                                {"code": "modules_doctor_missing_json"},
                                {
                                    "code": "modules_run_once_cron_mirror_dry_run_schema_mismatch",
                                    "expected": "memory-os.cron_mirror_report.v0",
                                },
                                {"code": "modules_run_once_not_dry_run", "value": None},
                                {
                                    "code": "modules_validate_no_send_schema_mismatch",
                                    "expected": "memory-os.modules_no_send_validation.v0",
                                },
                                {"code": "low_clue_recall_schema_mismatch", "expected": "memory-os.low_clue_recall.v0"},
                                {
                                    "code": "memory_sources_stats_schema_mismatch",
                                    "expected": "memory-os.memory_sources_stats.v0",
                                },
                                {"code": "memory_sources_boundary_true", "value": None},
                            ],
                        },
                    }
                ),
                "stderr": "",
            }
        if "install_memory_os.sh" in command:
            is_dry_run = "--dry-run" in command
            return {
                "exit_code": 0,
                "stdout": json.dumps({"schema_version": "memory-os.install.v0", "dry_run": is_dry_run}),
                "stderr": "",
            }
        if "memory_os_upgrade_compat_check.py" in command:
            return {
                "exit_code": 0,
                "stdout": json.dumps(
                    {
                        "schema_version": "memory-os.hermes_upgrade_compat.v0",
                        "classification": {"pass": [{"code": "memory_provider_active"}], "warn": [], "fail": []},
                    }
                ),
                "stderr": "",
            }
        if "memory_os_cron_adapter_probe.py" in command:
            return _cron_adapter_probe_result()
        if "memory_os_boundary_runtime_probe.py" in command:
            return _boundary_runtime_probe_result()
        if "low-clue-recall" in command:
            return _llm_judge_probe_result()
        if "deployment-manifest" in command:
            return _deployment_manifest_result()
        raise AssertionError(f"unexpected command: {command}")

    report = deploy_memory_os(
        repo_root=tmp_path,
        hermes_home="/root/.hermes",
        mode="operational",
        hindsight_mode="auto",
        phase="apply",
        profile="fresh",
        run_command=fake_runner,
    )

    classification = classify_deploy_report(report)

    assert report["preflight"]["status"] == "warn_expected_for_fresh"
    assert report["apply"]["status"] == "applied"
    assert report["postcheck"]["status"] == "pass"
    assert classification["fail"] == []
    assert {"code": "fresh_preflight_memory_os_preinstall_expected"} in classification["warn"]


def test_upgrade_profile_allows_preinstall_hindsight_status_gap_but_requires_postcheck(tmp_path):
    calls = []

    def fake_runner(argv, *, host=None, timeout=30):
        calls.append(tuple(argv))
        command = " ".join(argv)
        if "memory_os_upgrade_compat_check.py" in command and len(calls) == 1:
            return {
                "exit_code": 1,
                "stdout": json.dumps(
                    {
                        "schema_version": "memory-os.hermes_upgrade_compat.v0",
                        "classification": {
                            "pass": [{"code": "memory_provider_active"}],
                            "warn": [],
                            "fail": [
                                {"code": "hindsight_status_command_failed", "exit_code": 2},
                                {"code": "hindsight_status_missing_json"},
                            ],
                        },
                    }
                ),
                "stderr": "",
            }
        if "install_memory_os.sh" in command:
            is_dry_run = "--dry-run" in command
            return {
                "exit_code": 0,
                "stdout": json.dumps({"schema_version": "memory-os.install.v0", "dry_run": is_dry_run}),
                "stderr": "",
            }
        if "memory_os_upgrade_compat_check.py" in command:
            return {
                "exit_code": 0,
                "stdout": json.dumps(
                    {
                        "schema_version": "memory-os.hermes_upgrade_compat.v0",
                        "classification": {"pass": [{"code": "hindsight_optional_off_ok"}], "warn": [], "fail": []},
                    }
                ),
                "stderr": "",
            }
        if "memory_os_cron_adapter_probe.py" in command:
            return _cron_adapter_probe_result()
        if "memory_os_boundary_runtime_probe.py" in command:
            return _boundary_runtime_probe_result()
        if "low-clue-recall" in command:
            return _llm_judge_probe_result()
        if "deployment-manifest" in command:
            return _deployment_manifest_result()
        raise AssertionError(f"unexpected command: {command}")

    report = deploy_memory_os(
        repo_root=tmp_path,
        hermes_home="/root/.hermes",
        mode="operational",
        hindsight_mode="auto",
        phase="apply",
        profile="upgrade",
        run_command=fake_runner,
    )

    classification = classify_deploy_report(report)

    assert report["preflight"]["status"] == "warn_expected_for_upgrade_preinstall"
    assert report["apply"]["status"] == "applied"
    assert report["postcheck"]["status"] == "pass"
    assert {"code": "upgrade_preflight_hindsight_status_pending_install"} in classification["warn"]
    assert classification["fail"] == []


def test_upgrade_profile_allows_preinstall_fixable_shell_doctor_index_mismatch(tmp_path):
    calls = []

    def fake_runner(argv, *, host=None, timeout=30):
        calls.append(tuple(argv))
        command = " ".join(argv)
        if "memory_os_upgrade_compat_check.py" in command and len(calls) == 1:
            return {
                "exit_code": 1,
                "stdout": json.dumps(
                    {
                        "schema_version": "memory-os.hermes_upgrade_compat.v0",
                        "classification": {
                            "pass": [{"code": "memory_provider_active"}],
                            "warn": [],
                            "fail": [
                                {"code": "shell_doctor_command_failed", "exit_code": 1},
                                {"code": "shell_doctor_missing_json"},
                            ],
                        },
                        "commands": {
                            "shell_doctor": {
                                "exit_code": 1,
                                "json": {
                                    "schema_version": "memory-os.doctor.v0",
                                    "status": "fail",
                                    "findings": [
                                        {
                                            "code": "index_count_mismatch",
                                            "severity": "error",
                                            "details": {"count_key": "crystallized_records"},
                                        }
                                    ],
                                },
                            }
                        },
                    }
                ),
                "stderr": "",
            }
        if "install_memory_os.sh" in command:
            is_dry_run = "--dry-run" in command
            return {
                "exit_code": 0,
                "stdout": json.dumps({"schema_version": "memory-os.install.v0", "dry_run": is_dry_run}),
                "stderr": "",
            }
        if "memory_os_upgrade_compat_check.py" in command:
            return {
                "exit_code": 0,
                "stdout": json.dumps(
                    {
                        "schema_version": "memory-os.hermes_upgrade_compat.v0",
                        "classification": {"pass": [{"code": "shell_doctor_ok"}], "warn": [], "fail": []},
                    }
                ),
                "stderr": "",
            }
        if "memory_os_cron_adapter_probe.py" in command:
            return _cron_adapter_probe_result()
        if "memory_os_boundary_runtime_probe.py" in command:
            return _boundary_runtime_probe_result()
        if "low-clue-recall" in command:
            return _llm_judge_probe_result()
        if "deployment-manifest" in command:
            return _deployment_manifest_result()
        raise AssertionError(f"unexpected command: {command}")

    report = deploy_memory_os(
        repo_root=tmp_path,
        hermes_home="/root/.hermes",
        mode="operational",
        hindsight_mode="auto",
        phase="apply",
        profile="upgrade",
        run_command=fake_runner,
    )

    classification = classify_deploy_report(report)

    assert report["preflight"]["status"] == "warn_expected_for_upgrade_preinstall"
    assert report["apply"]["status"] == "applied"
    assert report["postcheck"]["status"] == "pass"
    assert {"code": "upgrade_preflight_shell_doctor_preinstall_fixable"} in classification["warn"]
    assert classification["fail"] == []


def test_upgrade_profile_allows_preinstall_shell_doctor_gap_when_postcheck_repairs(tmp_path):
    calls = []

    def fake_runner(argv, *, host=None, timeout=30):
        calls.append(tuple(argv))
        command = " ".join(argv)
        if "memory_os_upgrade_compat_check.py" in command and len(calls) == 1:
            return {
                "exit_code": 1,
                "stdout": json.dumps(
                    {
                        "schema_version": "memory-os.hermes_upgrade_compat.v0",
                        "classification": {
                            "pass": [{"code": "memory_provider_active"}, {"code": "hindsight_configured_ok"}],
                            "warn": [],
                            "fail": [
                                {"code": "shell_doctor_command_failed", "exit_code": 1},
                                {"code": "shell_doctor_missing_json"},
                            ],
                        },
                    }
                ),
                "stderr": "",
            }
        if "install_memory_os.sh" in command:
            is_dry_run = "--dry-run" in command
            return {
                "exit_code": 0,
                "stdout": json.dumps({"schema_version": "memory-os.install.v0", "dry_run": is_dry_run}),
                "stderr": "",
            }
        if "memory_os_upgrade_compat_check.py" in command:
            return {
                "exit_code": 0,
                "stdout": json.dumps(
                    {
                        "schema_version": "memory-os.hermes_upgrade_compat.v0",
                        "classification": {"pass": [{"code": "shell_doctor_ok"}], "warn": [], "fail": []},
                    }
                ),
                "stderr": "",
            }
        if "memory_os_cron_adapter_probe.py" in command:
            return _cron_adapter_probe_result()
        if "memory_os_boundary_runtime_probe.py" in command:
            return _boundary_runtime_probe_result()
        if "low-clue-recall" in command:
            return _llm_judge_probe_result()
        if "deployment-manifest" in command:
            return _deployment_manifest_result()
        raise AssertionError(f"unexpected command: {command}")

    report = deploy_memory_os(
        repo_root=tmp_path,
        hermes_home="/root/.hermes",
        mode="operational",
        hindsight_mode="auto",
        phase="apply",
        profile="upgrade",
        run_command=fake_runner,
    )

    assert report["preflight"]["status"] == "warn_expected_for_upgrade_preinstall"
    assert report["apply"]["status"] == "applied"
    assert report["postcheck"]["status"] == "pass"


def test_upgrade_profile_allows_preinstall_provider_bank_evidence_gap_but_requires_postcheck(tmp_path):
    calls = []

    def fake_runner(argv, *, host=None, timeout=30):
        calls.append(tuple(argv))
        command = " ".join(argv)
        if "memory_os_upgrade_compat_check.py" in command and len(calls) == 1:
            return {
                "exit_code": 1,
                "stdout": json.dumps(
                    {
                        "schema_version": "memory-os.hermes_upgrade_compat.v0",
                        "classification": {
                            "pass": [{"code": "memory_provider_active"}],
                            "warn": [],
                            "fail": [{"code": "hindsight_provider_bank_evidence_missing"}],
                        },
                    }
                ),
                "stderr": "",
            }
        if "install_memory_os.sh" in command:
            is_dry_run = "--dry-run" in command
            return {
                "exit_code": 0,
                "stdout": json.dumps(
                    {
                        "schema_version": "memory-os.install.v0",
                        "dry_run": is_dry_run,
                        "hindsight_adoption": {
                            "status": "adopted_shadow",
                            "planned_config": {
                                "enabled": True,
                                "bank_id": "hermes02",
                                "provider_bank_id": "hermes02",
                            },
                        },
                    }
                ),
                "stderr": "",
            }
        if "memory_os_upgrade_compat_check.py" in command:
            return {
                "exit_code": 0,
                "stdout": json.dumps(
                    {
                        "schema_version": "memory-os.hermes_upgrade_compat.v0",
                        "classification": {
                            "pass": [{"code": "hindsight_provider_bank_selected"}],
                            "warn": [],
                            "fail": [],
                        },
                    }
                ),
                "stderr": "",
            }
        if "memory_os_cron_adapter_probe.py" in command:
            return _cron_adapter_probe_result()
        if "memory_os_boundary_runtime_probe.py" in command:
            return _boundary_runtime_probe_result()
        if "low-clue-recall" in command:
            return _llm_judge_probe_result()
        if "deployment-manifest" in command:
            return _deployment_manifest_result()
        raise AssertionError(f"unexpected command: {command}")

    report = deploy_memory_os(
        repo_root=tmp_path,
        hermes_home="/root/.hermes",
        mode="operational",
        hindsight_mode="auto",
        phase="apply",
        profile="upgrade",
        run_command=fake_runner,
    )

    assert report["preflight"]["status"] == "warn_expected_for_upgrade_preinstall"
    assert report["apply"]["status"] == "applied"
    assert report["postcheck"]["status"] == "pass"


def test_remote_plan_uses_ssh_without_printing_secret(tmp_path):
    report = deploy_memory_os(
        repo_root=tmp_path,
        remote_repo_root="/opt/Hermes-Memory-OS",
        host="hermes-media",
        hermes_home="/root/.hermes",
        mode="operational",
        hindsight_mode="adopt",
        phase="plan",
        profile="upgrade",
    )

    rendered = render_deploy_plan(report)

    assert report["host"] == "hermes-media"
    assert report["commands"]["install_apply"][0] == "ssh"
    assert "python3 /opt/Hermes-Memory-OS/scripts/memory_os_upgrade_compat_check.py" in rendered
    assert "--hindsight adopt" in rendered
    assert "/opt/Hermes-Memory-OS/scripts/install_memory_os.sh" in rendered


def test_remote_plan_resolves_known_host_repo_root_when_missing(tmp_path):
    local_repo_root = tmp_path / "local checkout"
    local_repo_root.mkdir()

    report = deploy_memory_os(
        repo_root=local_repo_root,
        host="hermes-media",
        hermes_home="/root/.hermes",
        mode="operational",
        hindsight_mode="auto",
        phase="plan",
        profile="upgrade",
    )

    rendered = render_deploy_plan(report)

    assert "/opt/Hermes-Memory-OS/scripts/memory_os_upgrade_compat_check.py" in rendered
    assert str(local_repo_root) not in rendered
    assert report["host_runtime_profile"]["profile_source"] == "known_host"


def test_remote_plan_unknown_host_without_remote_repo_root_fails_fast(tmp_path):
    try:
        deploy_memory_os(
            repo_root=tmp_path,
            host="unknown-host",
            hermes_home="/root/.hermes",
            mode="operational",
            hindsight_mode="auto",
            phase="plan",
            profile="upgrade",
        )
    except ValueError as exc:
        assert "--remote-repo-root is required" in str(exc)
    else:
        raise AssertionError("unknown --host without --remote-repo-root should fail fast")


def test_python_bin_can_be_overridden_for_remote_targets(tmp_path):
    report = deploy_memory_os(
        repo_root=tmp_path,
        remote_repo_root="/opt/Hermes-Memory-OS",
        host="hermes-media",
        hermes_home="/root/.hermes",
        mode="operational",
        hindsight_mode="auto",
        phase="plan",
        profile="upgrade",
        python_bin="/custom/python",
    )

    assert "/custom/python /opt/Hermes-Memory-OS/scripts/memory_os_upgrade_compat_check.py" in render_deploy_plan(report)


def test_postcheck_summary_renders_status_and_classification(tmp_path):
    def fake_runner(argv, *, host=None, timeout=30):
        command = " ".join(argv)
        if "memory_os_upgrade_compat_check.py" in command:
            return {
                "exit_code": 0,
                "stdout": json.dumps(
                    {
                        "schema_version": "memory-os.hermes_upgrade_compat.v0",
                        "classification": {
                            "pass": [{"code": "memory_provider_active"}],
                            "warn": [],
                            "fail": [],
                        },
                    }
                ),
                "stderr": "",
            }
        if "memory_os_cron_adapter_probe.py" in command:
            return _cron_adapter_probe_result()
        if "memory_os_boundary_runtime_probe.py" in command:
            return _boundary_runtime_probe_result()
        if "low-clue-recall" in command:
            return _llm_judge_probe_result()
        if "deployment-manifest" in command:
            return _deployment_manifest_result()
        raise AssertionError(f"unexpected command: {command}")

    report = deploy_memory_os(
        repo_root=tmp_path,
        hermes_home="/root/.hermes",
        mode="operational",
        hindsight_mode="auto",
        phase="postcheck",
        profile="upgrade",
        run_command=fake_runner,
    )

    rendered = render_deploy_plan(report)

    assert report["postcheck"]["status"] == "pass"
    assert (
        "classification: "
        "pass=postcheck_pass,deployment_manifest_status_pass,llm_judge_probe_pass,"
        "cron_adapter_probe_pass,boundary_runtime_probe_pass "
        "warn=[] fail=[]"
    ) in rendered
    assert "evidence_labels=fast_probe_pass,live_monitor_not_run,clean_host_not_run" in rendered
    assert "postcheck_status=pass" in rendered
    assert "llm_judge_probe_status=pass" in rendered
    assert "boundary_runtime_probe_status=pass" in rendered


def test_postcheck_exposes_full_monitor_timeout_policy(tmp_path):
    def fake_runner(argv, *, host=None, timeout=30):
        command = " ".join(argv)
        if "memory_os_upgrade_compat_check.py" in command:
            return {
                "exit_code": 0,
                "stdout": json.dumps(
                    {
                        "schema_version": "memory-os.hermes_upgrade_compat.v0",
                        "classification": {"pass": [{"code": "memory_provider_active"}], "warn": [], "fail": []},
                    }
                ),
                "stderr": "",
            }
        if "memory_os_cron_adapter_probe.py" in command:
            return _cron_adapter_probe_result()
        if "memory_os_boundary_runtime_probe.py" in command:
            return _boundary_runtime_probe_result()
        if "low-clue-recall" in command:
            return _llm_judge_probe_result()
        if "deployment-manifest" in command:
            return _deployment_manifest_result()
        raise AssertionError(f"unexpected command: {command}")

    report = deploy_memory_os(
        repo_root=tmp_path,
        hermes_home="/root/.hermes",
        mode="operational",
        hindsight_mode="auto",
        phase="postcheck",
        profile="upgrade",
        timeout=120,
        run_command=fake_runner,
    )
    rendered = render_deploy_plan(report)

    assert report["monitor_timeout_policy"]["schema_version"] == "memory-os.monitor_timeout_policy.v0"
    assert report["monitor_timeout_policy"]["caller_timeout_seconds"] == 120
    assert report["monitor_timeout_policy"]["full_monitor_not_run"] is True
    assert report["monitor_timeout_policy"]["caller_timeout_under_full_monitor_minimum"] is True
    assert "monitor_timeout_policy=fast_probe_timeout=120,full_monitor_min_timeout=300,full_monitor_not_run=true" in rendered


def test_postcheck_fails_and_renders_cognitive_loop_timer_failure(tmp_path):
    def fake_runner(argv, *, host=None, timeout=30):
        command = " ".join(argv)
        if "memory_os_upgrade_compat_check.py" in command:
            return {
                "exit_code": 1,
                "stdout": json.dumps(
                    {
                        "schema_version": "memory-os.hermes_upgrade_compat.v0",
                        "commands": {
                            "cognitive_loop_timer": {
                                "exit_code": 0,
                                "stdout_preview": "ActiveState=inactive\nUnitFileState=disabled\n",
                            }
                        },
                        "classification": {
                            "pass": [],
                            "warn": [],
                            "fail": [
                                {
                                    "code": "cognitive_loop_timer_inactive",
                                    "active_state": "inactive",
                                    "unit_file_state": "disabled",
                                }
                            ],
                        },
                    }
                ),
                "stderr": "",
            }
        if "memory_os_cron_adapter_probe.py" in command:
            return _cron_adapter_probe_result()
        if "memory_os_boundary_runtime_probe.py" in command:
            return _boundary_runtime_probe_result()
        if "low-clue-recall" in command:
            return _llm_judge_probe_result()
        if "deployment-manifest" in command:
            return _deployment_manifest_result()
        raise AssertionError(f"unexpected command: {command}")

    report = deploy_memory_os(
        repo_root=tmp_path,
        hermes_home="/root/.hermes",
        mode="operational",
        hindsight_mode="auto",
        phase="postcheck",
        profile="upgrade",
        run_command=fake_runner,
    )

    rendered = render_deploy_plan(report)

    assert report["postcheck"]["status"] == "fail"
    assert {"code": "postcheck_failed"} in classify_deploy_report(report)["fail"]
    assert "postcheck_fail_codes=cognitive_loop_timer_inactive" in rendered
    assert "postcheck_cognitive_loop_timer=inactive/disabled" in rendered
