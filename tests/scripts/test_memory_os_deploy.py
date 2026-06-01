import json

from scripts.deploy_memory_os import (
    classify_deploy_report,
    deploy_memory_os,
    render_deploy_plan,
)


def _llm_judge_probe_result():
    return {
        "exit_code": 0,
        "stdout": json.dumps(
            {
                "schema_version": "memory-os.low_clue_recall.v0",
                "candidate_count": 1,
                "llm_judge": {
                    "status": "ok",
                    "mode": "report_only",
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
    assert "--llm-judge-preset report-only" in rendered
    assert "--production-safe" in rendered
    assert "SECRET" not in json.dumps(report, ensure_ascii=False)


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
        if "low-clue-recall" in command:
            return _llm_judge_probe_result()
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
        if "low-clue-recall" in command:
            return _llm_judge_probe_result()
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
        if "low-clue-recall" in command:
            return _llm_judge_probe_result()
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
        if "low-clue-recall" in command:
            return _llm_judge_probe_result()
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
        if "low-clue-recall" in command:
            return _llm_judge_probe_result()
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
        if "low-clue-recall" in command:
            return _llm_judge_probe_result()
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
    assert "classification: pass=postcheck_pass,llm_judge_probe_pass warn=[] fail=[]" in rendered
    assert "postcheck_status=pass" in rendered
    assert "llm_judge_probe_status=pass" in rendered
