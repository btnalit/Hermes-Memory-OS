from scripts.memory_os_upgrade_compat_check import classify_report, render_summary, run_upgrade_compat_check


def test_upgrade_compat_check_passes_healthy_report():
    report = run_upgrade_compat_check(run_command=_fake_runner(_healthy_outputs()))

    assert report["schema_version"] == "memory-os.hermes_upgrade_compat.v0"
    assert report["classification"]["fail"] == []
    assert any(item["code"] == "memory_provider_active" for item in report["classification"]["pass"])
    assert "memory-os.modules_status.v0" in render_summary(report)


def test_upgrade_compat_check_warns_when_version_probe_unavailable():
    outputs = _healthy_outputs()
    outputs["hermes_version"] = {"exit_code": 2, "stdout": "", "stderr": "unknown option"}

    report = run_upgrade_compat_check(run_command=_fake_runner(outputs))

    assert report["classification"]["fail"] == []
    assert any(item["code"] == "hermes_version_unavailable" for item in report["classification"]["warn"])


def test_upgrade_compat_check_fails_when_provider_is_not_memory_os():
    outputs = _healthy_outputs()
    outputs["memory_provider"] = {"exit_code": 0, "stdout": "Provider: built-in", "stderr": ""}

    report = run_upgrade_compat_check(run_command=_fake_runner(outputs))

    assert any(item["code"] == "memory_provider_not_memory_os" for item in report["classification"]["fail"])


def test_upgrade_compat_check_fails_when_modules_alias_breaks():
    outputs = _healthy_outputs()
    outputs["modules_status"] = {"exit_code": 2, "stdout": "", "stderr": "invalid choice: modules"}

    report = run_upgrade_compat_check(run_command=_fake_runner(outputs))

    fail_codes = {item["code"] for item in report["classification"]["fail"]}
    assert "modules_status_command_failed" in fail_codes
    assert "modules_status_schema_mismatch" in fail_codes


def test_upgrade_compat_check_fails_on_boundary_true():
    outputs = _healthy_outputs()
    outputs["modules_validate_no_send"]["stdout"] = (
        '{"schema_version":"memory-os.modules_no_send_validation.v0",'
        '"status":"ok","boundaries":{"actual_send":true}}'
    )

    report = run_upgrade_compat_check(run_command=_fake_runner(outputs))

    assert any(item["code"] == "modules_validate_no_send_boundary_true" for item in report["classification"]["fail"])


def test_classify_report_fails_on_memory_sources_forbidden_fields():
    outputs = _healthy_outputs()
    outputs["memory_sources_stats"]["stdout"] = (
        '{"schema_version":"memory-os.memory_sources_stats.v0",'
        '"boundary_true_count":0,"forbidden_field_findings":["raw_body"]}'
    )
    command_results = {
        name: {
            "exit_code": raw["exit_code"],
            "stdout_preview": raw["stdout"],
            "stderr_preview": raw["stderr"],
            "json": __import__("json").loads(raw["stdout"]) if raw["stdout"].startswith("{") else None,
        }
        for name, raw in outputs.items()
    }

    classification = classify_report(command_results)

    assert any(item["code"] == "memory_sources_stats_forbidden_fields" for item in classification["fail"])


def test_upgrade_check_accepts_optional_hindsight_off():
    results = _healthy_command_results()
    results["hindsight_status"] = {
        "exit_code": 0,
        "json": {
            "schema_version": "memory-os.hindsight_substrate_status.v0",
            "enabled": False,
            "status": "optional_not_configured",
        },
    }

    classification = classify_report(results)

    assert {"code": "hindsight_optional_off_ok"} in classification["pass"]
    assert not [item for item in classification["fail"] if item["code"].startswith("hindsight")]


def test_upgrade_check_fails_when_substrate_monitor_reports_raw_retain():
    results = _healthy_command_results()
    results["hindsight_status"] = {
        "exit_code": 0,
        "json": {
            "schema_version": "memory-os.hindsight_substrate_status.v0",
            "enabled": True,
            "status": "configured",
            "recall_mode": "shadow",
            "substrate_monitor": {
                "raw_retained_count": 1,
                "no_raw_retained": False,
                "projection_stale_count": 0,
                "local_first_authority_preserved": True,
            },
        },
    }

    classification = classify_report(results)

    assert {"code": "hindsight_raw_retain_detected"} in classification["fail"]


def test_upgrade_check_requires_governed_hindsight_to_match_provider_bank():
    results = _healthy_command_results()
    results["hindsight_status"] = {
        "exit_code": 0,
        "json": {
            "schema_version": "memory-os.hindsight_substrate_status.v0",
            "enabled": True,
            "status": "configured",
            "adoption_source": "hermes_hindsight_config",
            "bank_id": "opsevo-info",
            "provider_bank_id": "hermes02",
            "bank_selection_reason": "top_level_provider_bank_id",
            "recall_mode": "shadow",
            "substrate_monitor": {
                "raw_retained_count": 0,
                "projection_stale_count": 0,
                "local_first_authority_preserved": True,
            },
        },
    }

    classification = classify_report(results)

    assert {"code": "hindsight_provider_bank_mismatch", "bank_id": "opsevo-info", "provider_bank_id": "hermes02"} in classification["fail"]


def test_upgrade_check_passes_when_governed_hindsight_uses_provider_bank():
    results = _healthy_command_results()
    results["hindsight_status"] = {
        "exit_code": 0,
        "json": {
            "schema_version": "memory-os.hindsight_substrate_status.v0",
            "enabled": True,
            "status": "configured",
            "adoption_source": "hermes_hindsight_config",
            "bank_id": "hermes02",
            "provider_bank_id": "hermes02",
            "bank_selection_reason": "top_level_provider_bank_id",
            "non_provider_configured_bank_count": 1,
            "recall_mode": "shadow",
            "substrate_monitor": {
                "raw_retained_count": 0,
                "projection_stale_count": 0,
                "local_first_authority_preserved": True,
            },
        },
    }

    classification = classify_report(results)

    assert classification["fail"] == []
    assert any(item["code"] == "hindsight_provider_bank_selected" for item in classification["pass"])


def test_upgrade_check_fails_when_projection_stale_count_is_positive():
    results = _healthy_command_results()
    results["hindsight_status"] = {
        "exit_code": 0,
        "json": {
            "schema_version": "memory-os.hindsight_substrate_status.v0",
            "enabled": True,
            "status": "configured",
            "recall_mode": "shadow",
            "substrate_monitor": {
                "raw_retained_count": 0,
                "projection_stale_count": 1,
                "local_first_authority_preserved": True,
            },
        },
    }

    classification = classify_report(results)

    assert {"code": "hindsight_projection_stale"} in classification["fail"]


def test_upgrade_check_fails_when_external_provider_claims_authority():
    results = _healthy_command_results()
    results["hindsight_status"] = {
        "exit_code": 0,
        "json": {
            "schema_version": "memory-os.hindsight_substrate_status.v0",
            "enabled": True,
            "status": "configured",
            "recall_mode": "active",
            "substrate_monitor": {
                "raw_retained_count": 0,
                "projection_stale_count": 0,
                "local_first_authority_preserved": False,
                "external_authoritative_count": 1,
            },
        },
    }

    classification = classify_report(results)

    assert {"code": "hindsight_overrode_local_authority"} in classification["fail"]


def _fake_runner(outputs):
    def run_command(argv, host, hermes_home, timeout):
        command_name = _name_for_argv(tuple(argv))
        result = outputs[command_name]
        return dict(result)

    return run_command


def _name_for_argv(argv: tuple[str, ...]) -> str:
    if argv == ("hermes", "--version"):
        return "hermes_version"
    if argv == ("hermes", "memory"):
        return "memory_provider"
    if argv == ("hermes", "memory-os-agent-os", "status"):
        return "shell_status"
    if argv == ("hermes", "memory-os-agent-os", "doctor"):
        return "shell_doctor"
    if argv == ("hermes", "memory-os-agent-os", "hindsight", "status"):
        return "hindsight_status"
    if argv == ("hermes", "memory-os-agent-os", "modules", "status"):
        return "modules_status"
    if argv == ("hermes", "memory-os-agent-os", "modules", "doctor"):
        return "modules_doctor"
    if argv == (
        "hermes",
        "memory-os-agent-os",
        "modules",
        "run-once",
        "--module",
        "cron_mirror",
        "--dry-run",
    ):
        return "modules_run_once_cron_mirror_dry_run"
    if argv == ("hermes", "memory-os-agent-os", "modules", "validate-no-send"):
        return "modules_validate_no_send"
    if argv[:3] == ("hermes", "memory-os-agent-os", "low-clue-recall"):
        return "low_clue_recall"
    if argv[:3] == ("hermes", "memory-os-agent-os", "memory-sources"):
        return "memory_sources_stats"
    raise AssertionError(f"unexpected command: {argv}")


def _healthy_outputs():
    return {
        "hermes_version": {
            "exit_code": 0,
            "stdout": "Hermes Agent v0.14.0 (2026.5.16)",
            "stderr": "",
        },
        "memory_provider": {
            "exit_code": 0,
            "stdout": "Provider: memory_os\nPlugin: installed\nStatus: available\nmemory_os (local) active",
            "stderr": "",
        },
        "shell_status": {
            "exit_code": 0,
            "stdout": '{"schema_version":"memory-os.status.v0"}',
            "stderr": "",
        },
        "shell_doctor": {
            "exit_code": 0,
            "stdout": '{"schema_version":"memory-os.doctor.v0","status":"ok","findings":[]}',
            "stderr": "",
        },
        "hindsight_status": {
            "exit_code": 0,
            "stdout": (
                '{"schema_version":"memory-os.hindsight_substrate_status.v0",'
                '"enabled":false,"status":"optional_not_configured"}'
            ),
            "stderr": "",
        },
        "modules_status": {
            "exit_code": 0,
            "stdout": '{"schema_version":"memory-os.modules_status.v0","modules":[]}',
            "stderr": "",
        },
        "modules_doctor": {
            "exit_code": 0,
            "stdout": '{"schema_version":"memory-os.modules_doctor.v0","status":"warning","findings":[]}',
            "stderr": "",
        },
        "modules_run_once_cron_mirror_dry_run": {
            "exit_code": 0,
            "stdout": '{"schema_version":"memory-os.cron_mirror_report.v0","dry_run":true}',
            "stderr": "",
        },
        "modules_validate_no_send": {
            "exit_code": 0,
            "stdout": (
                '{"schema_version":"memory-os.modules_no_send_validation.v0",'
                '"status":"ok","boundaries":{"actual_send":false,'
                '"actual_execute":false,"actual_identity_write":false,'
                '"actual_relationship_write":false,'
                '"actual_crystallized_approval":false,"hindsight_exported":false}}'
            ),
            "stderr": "",
        },
        "low_clue_recall": {
            "exit_code": 0,
            "stdout": (
                '{"schema_version":"memory-os.low_clue_recall.v0",'
                '"boundaries":{"actual_send":false,"actual_execute":false,'
                '"actual_identity_write":false,"actual_relationship_write":false,'
                '"actual_crystallized_approval":false,"hindsight_exported":false}}'
            ),
            "stderr": "",
        },
        "memory_sources_stats": {
            "exit_code": 0,
            "stdout": (
                '{"schema_version":"memory-os.memory_sources_stats.v0",'
                '"boundary_true_count":0,"forbidden_field_findings":[]}'
            ),
            "stderr": "",
        },
    }


def _healthy_command_results():
    return {
        name: {
            "exit_code": raw["exit_code"],
            "stdout_preview": raw["stdout"],
            "stderr_preview": raw["stderr"],
            "json": __import__("json").loads(raw["stdout"]) if raw["stdout"].startswith("{") else None,
        }
        for name, raw in _healthy_outputs().items()
    }
