import importlib.util
import json
import argparse
import os
import subprocess
import sys
from pathlib import Path

import yaml

from scripts.install_memory_os_plugin import SOURCE_AGENT_OS_SHELL_DIR, SOURCE_PLUGIN_DIR, install_plugin


def test_installer_copies_memory_provider_shape_without_cache_files(tmp_path):
    source = tmp_path / "source"
    target_home = tmp_path / "home"
    shutil_copy_source(SOURCE_PLUGIN_DIR, source)
    (source / "__pycache__").mkdir(exist_ok=True)
    (source / "__pycache__" / "ignored.pyc").write_bytes(b"cache")

    report = install_plugin(hermes_home=target_home, source=source)

    target = target_home / "plugins" / "memory_os"
    assert report["provider"] == "memory_os"
    assert target.joinpath("__init__.py").is_file()
    assert target.joinpath("plugin.yaml").is_file()
    assert target.joinpath("cli.py").is_file()
    assert not target.joinpath("__pycache__", "ignored.pyc").exists()


def test_installer_copies_agent_os_shell_by_default_without_cache_files(tmp_path):
    shell_source = tmp_path / "shell-source"
    target_home = tmp_path / "home"
    shutil_copy_source(SOURCE_AGENT_OS_SHELL_DIR, shell_source)
    (shell_source / "__pycache__").mkdir(exist_ok=True)
    (shell_source / "__pycache__" / "ignored.pyc").write_bytes(b"cache")

    report = install_plugin(hermes_home=target_home, shell_source=shell_source)

    target = target_home / "plugins" / "memory-os-agent-os"
    assert report["agent_os_shell_install_requested"] is True
    assert report["agent_os_shell_installed"] is True
    assert report["agent_os_shell_target"] == str(target)
    assert target.joinpath("__init__.py").is_file()
    assert target.joinpath("plugin.yaml").is_file()
    assert not target.joinpath("__pycache__", "ignored.pyc").exists()


def test_plugin_yaml_name_matches_hermes_provider_config_name():
    text = (SOURCE_PLUGIN_DIR / "plugin.yaml").read_text(encoding="utf-8")

    assert "name: memory_os" in text


def test_user_memory_cli_imports_before_provider_package_is_loaded(tmp_path):
    target_home = tmp_path / "home"
    install_plugin(hermes_home=target_home)
    cli_file = target_home / "plugins" / "memory_os" / "cli.py"
    module_name = "_hermes_user_memory.memory_os.cli"
    for name in list(sys.modules):
        if name.startswith("_hermes_user_memory"):
            sys.modules.pop(name)

    spec = importlib.util.spec_from_file_location(module_name, cli_file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)

    assert callable(module.register_cli)
    assert callable(module.memory_os_command)


def test_installer_dry_run_does_not_create_target(tmp_path):
    report = install_plugin(hermes_home=tmp_path / "home", dry_run=True)

    assert report["dry_run"] is True
    assert report["copied_file_count"] > 0
    assert report["agent_os_shell_file_count"] > 0
    assert not (tmp_path / "home" / "plugins" / "memory_os").exists()
    assert not (tmp_path / "home" / "plugins" / "memory-os-agent-os").exists()


def test_installer_cli_prints_json(tmp_path, capsys):
    from scripts.install_memory_os_plugin import main

    old_argv = sys.argv
    try:
        sys.argv = [
            "install_memory_os_plugin.py",
            "--hermes-home",
            str(tmp_path / "home"),
            "--dry-run",
        ]
        assert main() == 0
    finally:
        sys.argv = old_argv
    output = json.loads(capsys.readouterr().out)
    assert output["schema_version"] == "memory-os.install.v0"
    assert output["provider"] == "memory_os"


def test_installer_hindsight_off_leaves_substrate_disabled(tmp_path):
    from plugins.memory.memory_os.config import load_config

    home = tmp_path / "home"
    report = install_plugin(hermes_home=home, hindsight_mode="off")

    assert report["hindsight_mode"] == "off"
    assert report["hindsight_adoption"]["status"] == "disabled"
    hindsight = load_config(home)["substrate_providers"]["hindsight"]
    assert hindsight["enabled"] is False


def test_installer_cli_hindsight_config_imports_when_run_by_absolute_path(tmp_path):
    script = Path(__file__).resolve().parents[2] / "scripts" / "install_memory_os_plugin.py"
    home = tmp_path / "home"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--hermes-home",
            str(home),
            "--hindsight",
            "off",
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=True,
    )

    report = json.loads(result.stdout)

    assert report["schema_version"] == "memory-os.install.v0"
    assert report["hindsight_adoption"]["status"] == "disabled"
    assert (home / "memory-os" / "config.json").is_file()


def test_installer_hindsight_auto_adopts_existing_legacy_config_without_printing_secret(tmp_path):
    from plugins.memory.memory_os.config import load_config

    home = tmp_path / "home"
    legacy = home / "hindsight"
    legacy.mkdir(parents=True)
    (legacy / "config.json").write_text(
        '{"api_url":"http://127.0.0.1:8888","bank_id":"hermes02","apiKey":"SECRET","auto_retain":false}',
        encoding="utf-8",
    )

    report = install_plugin(hermes_home=home, hindsight_mode="auto")

    serialized = json.dumps(report, ensure_ascii=False)
    assert "SECRET" not in serialized
    assert report["hindsight_mode"] == "auto"
    assert report["hindsight_adoption"]["status"] == "adopted_shadow"
    hindsight = load_config(home)["substrate_providers"]["hindsight"]
    assert hindsight["enabled"] is True
    assert hindsight["bank_id"] == "hermes02"
    assert hindsight["recall_mode"] == "shadow"
    assert hindsight["retain_enabled"] is False
    assert hindsight["reflect_enabled"] is False
    assert hindsight["api_key"] == ""
    assert hindsight["provider_bank_id"] == "hermes02"
    assert hindsight["bank_selection_reason"] == "top_level_provider_bank_id"


def test_installer_hindsight_active_adopts_existing_provider_with_live_flags(tmp_path):
    from plugins.memory.memory_os.config import load_config

    home = tmp_path / "home"
    legacy = home / "hindsight"
    legacy.mkdir(parents=True)
    (legacy / "config.json").write_text(
        '{"api_url":"http://127.0.0.1:8888","bank_id":"hermes02","apiKey":"SECRET","auto_retain":false}',
        encoding="utf-8",
    )

    report = install_plugin(hermes_home=home, hindsight_mode="active")

    assert "SECRET" not in json.dumps(report, ensure_ascii=False)
    assert report["hindsight_mode"] == "active"
    assert report["hindsight_adoption"]["status"] == "adopted_active"
    hindsight = load_config(home)["substrate_providers"]["hindsight"]
    assert hindsight["enabled"] is True
    assert hindsight["bank_id"] == "hermes02"
    assert hindsight["recall_mode"] == "active"
    assert hindsight["retain_enabled"] is True
    assert hindsight["reflect_enabled"] is True
    assert hindsight["provider_bank_id"] == "hermes02"


def test_installer_hindsight_auto_preserves_existing_active_adoption(tmp_path):
    from plugins.memory.memory_os.config import load_config, save_config

    home = tmp_path / "home"
    legacy = home / "hindsight"
    legacy.mkdir(parents=True)
    (legacy / "config.json").write_text(
        '{"api_url":"http://127.0.0.1:8888","bank_id":"hermes02","apiKey":"SECRET","auto_retain":false}',
        encoding="utf-8",
    )
    save_config(
        {
            "substrate_providers": {
                "hindsight": {
                    "enabled": True,
                    "adoption_source": "hermes_hindsight_config",
                    "api_url": "http://127.0.0.1:8888",
                    "bank_id": "hermes02",
                    "provider_bank_id": "hermes02",
                    "retain_enabled": True,
                    "recall_mode": "active",
                    "reflect_enabled": True,
                }
            }
        },
        home,
    )

    report = install_plugin(hermes_home=home, hindsight_mode="auto")

    assert report["hindsight_mode"] == "auto"
    assert report["hindsight_adoption"]["status"] == "preserved_active"
    hindsight = load_config(home)["substrate_providers"]["hindsight"]
    assert hindsight["enabled"] is True
    assert hindsight["bank_id"] == "hermes02"
    assert hindsight["recall_mode"] == "active"
    assert hindsight["retain_enabled"] is True
    assert hindsight["reflect_enabled"] is True


def test_installer_hindsight_auto_uses_provider_bank_not_other_configured_banks(tmp_path):
    from plugins.memory.memory_os.config import load_config

    home = tmp_path / "home"
    legacy = home / "hindsight"
    legacy.mkdir(parents=True)
    (legacy / "config.json").write_text(
        json.dumps(
            {
                "api_url": "http://127.0.0.1:8888",
                "bank_id": "hermes02",
                "apiKey": "SECRET",
                "auto_retain": False,
                "banks": {
                    "opsevo-info": {"bankId": "opsevo-info", "enabled": True},
                    "hermes02": {"bankId": "hermes02", "enabled": True},
                },
            }
        ),
        encoding="utf-8",
    )

    report = install_plugin(hermes_home=home, hindsight_mode="auto")

    assert report["hindsight_adoption"]["status"] == "adopted_shadow"
    detected = report["hindsight_adoption"]["detected"]
    assert detected["provider_bank_id"] == "hermes02"
    assert detected["bank_selection_reason"] == "top_level_provider_bank_id"
    assert detected["non_provider_configured_bank_count"] == 1
    assert "SECRET" not in json.dumps(report, ensure_ascii=False)
    hindsight = load_config(home)["substrate_providers"]["hindsight"]
    assert hindsight["bank_id"] == "hermes02"
    assert hindsight["provider_bank_id"] == "hermes02"
    assert hindsight["configured_provider_bank_ids"] == ["opsevo-info", "hermes02"]
    assert hindsight["non_provider_configured_bank_count"] == 1


def test_installer_hindsight_auto_refuses_ambiguous_provider_bank(tmp_path):
    from plugins.memory.memory_os.config import load_config

    home = tmp_path / "home"
    legacy = home / "hindsight"
    legacy.mkdir(parents=True)
    (legacy / "config.json").write_text(
        json.dumps(
            {
                "api_url": "http://127.0.0.1:8888",
                "banks": {
                    "opsevo-info": {"bankId": "opsevo-info", "enabled": True},
                    "hermes02": {"bankId": "hermes02", "enabled": True},
                },
            }
        ),
        encoding="utf-8",
    )

    report = install_plugin(hermes_home=home, hindsight_mode="auto")

    assert report["hindsight_adoption"]["status"] == "ambiguous_provider_bank"
    assert load_config(home)["substrate_providers"]["hindsight"]["enabled"] is False


def test_installer_hindsight_auto_without_config_stays_disabled(tmp_path):
    from plugins.memory.memory_os.config import load_config

    home = tmp_path / "home"
    report = install_plugin(hermes_home=home, hindsight_mode="auto")

    assert report["hindsight_mode"] == "auto"
    assert report["hindsight_adoption"]["status"] == "not_configured"
    assert load_config(home)["substrate_providers"]["hindsight"]["enabled"] is False


def test_installer_can_write_runtime_heartbeat_artifacts(tmp_path):
    report = install_plugin(hermes_home=tmp_path / "home", install_runtime=True)

    home = tmp_path / "home"
    assert report["runtime_artifacts_installed"] is True
    wrapper = home / "memory-os" / "bin" / "memory_os_heartbeat.sh"
    service = home / "memory-os" / "systemd" / "hermes-memory-os-heartbeat.service"
    timer = home / "memory-os" / "systemd" / "hermes-memory-os-heartbeat.timer"
    assert wrapper.is_file()
    assert service.is_file()
    assert timer.is_file()
    assert "python3 -m plugins.memory.memory_os heartbeat" in wrapper.read_text(encoding="utf-8")
    assert "OnUnitActiveSec=5min" in timer.read_text(encoding="utf-8")


def test_installer_can_write_cognitive_loop_artifacts(tmp_path):
    report = install_plugin(
        hermes_home=tmp_path / "home",
        install_cognitive_loop=True,
        cognitive_loop_interval="6h",
    )

    home = tmp_path / "home"
    assert report["cognitive_loop_artifacts_installed"] is True
    wrapper = home / "memory-os" / "bin" / "memory_os_cognitive_loop.sh"
    service = home / "memory-os" / "systemd" / "hermes-memory-os-cognitive-loop.service"
    timer = home / "memory-os" / "systemd" / "hermes-memory-os-cognitive-loop.timer"
    assert wrapper.is_file()
    assert service.is_file()
    assert timer.is_file()
    assert "python3 -m plugins.memory.memory_os cognitive-loop run-once --test-host --apply" in wrapper.read_text(
        encoding="utf-8"
    )
    assert "OnUnitActiveSec=6h" in timer.read_text(encoding="utf-8")


def test_installer_does_not_write_cognitive_loop_artifacts_by_default(tmp_path):
    report = install_plugin(hermes_home=tmp_path / "home")

    assert report["cognitive_loop_artifacts_installed"] is False
    assert not (tmp_path / "home" / "memory-os" / "bin" / "memory_os_cognitive_loop.sh").exists()


def test_installer_can_copy_owner_review_cron_helper_without_enabling_cron(tmp_path):
    report = install_plugin(hermes_home=tmp_path / "home", install_owner_review_cron_helper=True)

    helper = tmp_path / "home" / "scripts" / "memory_os_owner_review_digest.py"
    gate = tmp_path / "home" / "scripts" / "memory_os_owner_review_cron_gate.py"
    assert report["owner_review_cron_helper_install_requested"] is True
    assert report["owner_review_cron_helper_installed"] is True
    assert report["owner_review_cron_helper_path"] == str(helper)
    assert report["owner_review_cron_gate_path"] == str(gate)
    assert helper.is_file()
    assert gate.is_file()
    assert "Hermes cron owns scheduling" in helper.read_text(encoding="utf-8")
    assert "Explicit opt-in gate" in gate.read_text(encoding="utf-8")


def test_installer_can_copy_right_brain_expression_cron_helper_without_enabling_cron(tmp_path):
    report = install_plugin(hermes_home=tmp_path / "home", install_right_brain_expression_cron_helper=True)

    helper = tmp_path / "home" / "scripts" / "memory_os_right_brain_expression.py"
    gate = tmp_path / "home" / "scripts" / "memory_os_right_brain_expression_cron_gate.py"
    outcome = tmp_path / "home" / "scripts" / "memory_os_right_brain_expression_outcome.py"
    assert report["right_brain_expression_cron_helper_install_requested"] is True
    assert report["right_brain_expression_cron_helper_installed"] is True
    assert report["right_brain_expression_cron_helper_path"] == str(helper)
    assert report["right_brain_expression_cron_gate_path"] == str(gate)
    assert report["right_brain_expression_outcome_path"] == str(outcome)
    assert helper.is_file()
    assert gate.is_file()
    assert outcome.is_file()
    assert "Hermes agent owns the final expression" in helper.read_text(encoding="utf-8")
    assert "Right-brain expression Hermes cron" in gate.read_text(encoding="utf-8")
    assert "Hermes owns the agent turn" in outcome.read_text(encoding="utf-8")


def test_installer_can_copy_owner_cron_onboarding_without_enabling_cron(tmp_path):
    report = install_plugin(hermes_home=tmp_path / "home", install_owner_cron_onboarding=True)

    onboarding = tmp_path / "home" / "scripts" / "memory_os_owner_cron_onboarding.py"
    assert report["owner_cron_onboarding_install_requested"] is True
    assert report["owner_cron_onboarding_installed"] is True
    assert report["owner_cron_onboarding_path"] == str(onboarding)
    assert report["owner_cron_onboarding_run_status"] == ""
    assert onboarding.is_file()
    assert "detect" not in onboarding.read_text(encoding="utf-8").lower() or "channel" in onboarding.read_text(encoding="utf-8").lower()
    assert not (tmp_path / "home" / "cron" / "jobs.json").exists()


def test_installer_can_run_owner_cron_onboarding_with_auto_channel(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    home.joinpath("channel_directory.json").write_text(
        json.dumps(
            {
                "platforms": {
                    "telegram": [],
                    "discord": [{"id": "room-1", "type": "dm", "name": "owner"}],
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = install_plugin(
        hermes_home=home,
        install_system_modules=True,
        install_owner_cron_onboarding=True,
        run_owner_cron_onboarding=True,
        owner_cron_owner_approved=True,
        hermes_bin=_fake_hermes(tmp_path),
        owner_review_deliver="auto",
        right_brain_deliver="origin",
    )

    assert report["owner_cron_onboarding_run_status"] == "applied"
    assert report["owner_cron_onboarding_report"]["selected_owner_review_deliver"] == "discord"
    assert report["owner_cron_onboarding_report"]["selected_owner_review_channel"] == "discord"
    assert report["owner_cron_onboarding_report"]["selected_right_brain_deliver"] == "origin"
    assert report["owner_cron_profile"] == "active-closure"
    assert report["owner_cron_onboarding_report"]["cron_profile"] == "active-closure"
    assert len(report["owner_cron_onboarding_report"]["operational_cron_jobs"]) == 2
    jobs = json.loads(home.joinpath("cron", "jobs.json").read_text(encoding="utf-8"))["jobs"]
    by_name = {job["name"]: job for job in jobs}
    assert set(by_name) == {
        "memory-os-owner-review-digest",
        "memory-os-proposal-followups-opsgate",
    }
    assert by_name["memory-os-owner-review-digest"]["deliver"] == "discord"
    assert by_name["memory-os-proposal-followups-opsgate"]["deliver"] == "local"


def test_installer_can_run_full_owner_cron_profile_when_requested(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    home.joinpath("channel_directory.json").write_text(
        json.dumps({"platforms": {"telegram": [{"id": "chat-1", "type": "dm", "name": "owner"}]}}),
        encoding="utf-8",
    )

    report = install_plugin(
        hermes_home=home,
        install_system_modules=True,
        install_owner_cron_onboarding=True,
        run_owner_cron_onboarding=True,
        owner_cron_owner_approved=True,
        owner_cron_profile="full",
        hermes_bin=_fake_hermes(tmp_path),
        owner_review_deliver="auto",
        right_brain_deliver="origin",
    )

    assert report["owner_cron_profile"] == "full"
    assert report["owner_cron_onboarding_report"]["cron_profile"] == "full"
    assert len(report["owner_cron_onboarding_report"]["operational_cron_jobs"]) == 7

    jobs = json.loads(home.joinpath("cron", "jobs.json").read_text(encoding="utf-8"))["jobs"]
    assert {job["name"] for job in jobs} == {
        "memory-os-owner-review-digest",
        "memory-os-right-brain-expression",
        "memory-os-module-cadence-report",
        "memory-os-right-brain-expression-outcome",
        "memory-os-proposal-followups-opsgate",
        "memory-os-expression-feedback-request",
        "memory-os-memory-sources-feedback-request",
    }


def test_installer_runs_owner_cron_onboarding_after_shell_enable(tmp_path, monkeypatch):
    import scripts.install_memory_os_plugin as installer

    home = tmp_path / "home"
    config_path = home / "config.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "plugins:\n"
        "  disabled:\n"
        "    - memory-os-agent-os\n",
        encoding="utf-8",
    )
    order: list[str] = []
    original_shell_enable = installer._enable_agent_os_shell

    def fake_memory_provider(hermes_home, command):
        order.append("provider")

    def wrapped_shell_enable(hermes_home):
        order.append("shell")
        original_shell_enable(hermes_home)

    def fake_onboarding(**kwargs):
        order.append("onboarding")
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        assert config["plugins"]["enabled"] == ["memory-os-agent-os"]
        assert "memory-os-agent-os" not in config["plugins"].get("disabled", [])
        return {"status": "applied"}

    monkeypatch.setattr(installer, "_enable_memory_provider", fake_memory_provider)
    monkeypatch.setattr(installer, "_enable_agent_os_shell", wrapped_shell_enable)
    monkeypatch.setattr(installer, "_run_owner_cron_onboarding", fake_onboarding)

    report = install_plugin(
        hermes_home=home,
        enable=True,
        enable_shell=True,
        install_owner_cron_onboarding=True,
        run_owner_cron_onboarding=True,
        owner_cron_owner_approved=True,
    )

    assert order == ["provider", "shell", "onboarding"]
    assert report["owner_cron_onboarding_run_status"] == "applied"


def test_installer_can_install_system_module_runtime_package(tmp_path):
    report = install_plugin(hermes_home=tmp_path / "home", install_system_modules=True)

    runtime_python = tmp_path / "home" / "memory-os" / "runtime" / "python"
    runtime_root = runtime_python / "plugins"
    cadence_report = tmp_path / "home" / "scripts" / "memory_os_module_cadence_report.py"
    cadence_report_cron = tmp_path / "home" / "scripts" / "memory_os_module_cadence_report_cron.py"
    right_brain_outcome_cron = tmp_path / "home" / "scripts" / "memory_os_right_brain_expression_outcome_cron.py"
    expression_feedback_prompt = tmp_path / "home" / "scripts" / "memory_os_expression_feedback_prompt.py"
    memory_sources_feedback_prompt = tmp_path / "home" / "scripts" / "memory_os_memory_sources_feedback_prompt.py"
    proposal_followups_ops_gate = tmp_path / "home" / "scripts" / "memory_os_proposal_followups_ops_gate.py"
    assert report["system_modules_installed"] is True
    assert report["system_module_file_count"] > 0
    assert report["agent_runtime_file_count"] > 0
    assert report["eval_runtime_file_count"] > 0
    assert report["module_cadence_report_path"] == str(cadence_report)
    assert report["module_cadence_report_cron_path"] == str(cadence_report_cron)
    assert report["right_brain_expression_outcome_cron_path"] == str(right_brain_outcome_cron)
    assert report["expression_feedback_prompt_path"] == str(expression_feedback_prompt)
    assert report["memory_sources_feedback_prompt_path"] == str(memory_sources_feedback_prompt)
    assert report["proposal_followups_ops_gate_path"] == str(proposal_followups_ops_gate)
    assert cadence_report.is_file()
    assert cadence_report_cron.is_file()
    assert right_brain_outcome_cron.is_file()
    assert expression_feedback_prompt.is_file()
    assert memory_sources_feedback_prompt.is_file()
    assert proposal_followups_ops_gate.is_file()
    assert "Hermes owns cron" in cadence_report.read_text(encoding="utf-8")
    assert "--apply" in cadence_report_cron.read_text(encoding="utf-8")
    assert "--apply" in right_brain_outcome_cron.read_text(encoding="utf-8")
    assert "Hermes agent owns the owner interaction" in expression_feedback_prompt.read_text(encoding="utf-8")
    assert "Hermes agent owns the owner interaction" in memory_sources_feedback_prompt.read_text(encoding="utf-8")
    assert "OpsGate report-only" in proposal_followups_ops_gate.read_text(encoding="utf-8")
    assert runtime_root.joinpath("system", "lifecycle.py").is_file()
    assert runtime_root.joinpath("modules", "context", "digest_consolidation.py").is_file()
    assert runtime_root.joinpath("modules", "cognition", "deep_reflection.py").is_file()
    assert runtime_root.joinpath("modules", "cognition", "inner_drive.py").is_file()
    assert runtime_root.joinpath("modules", "expression", "speak_gate.py").is_file()
    assert runtime_root.joinpath("modules", "governance", "feedback_bridge.py").is_file()
    assert runtime_root.joinpath("memory", "memory_os", "store.py").is_file()
    assert runtime_root.joinpath("memory", "memory_os", "shadow_journal.py").is_file()
    assert runtime_python.joinpath("agent", "memory_provider.py").is_file()
    assert runtime_python.joinpath("eval", "memory_os", "runner", "run.py").is_file()
    assert runtime_python.joinpath("eval", "memory_os", "adapters", "grep.py").is_file()
    assert runtime_python.joinpath("eval", "memory_os", "adapters", "retrieval_shadow.py").is_file()
    assert runtime_python.joinpath("eval", "memory_os", "data", "retrieval_shadow_cases.jsonl").is_file()
    assert not any("__pycache__" in path for path in report["system_module_files"])
    assert not any("__pycache__" in path for path in report["agent_runtime_files"])
    assert not any("__pycache__" in path for path in report["eval_runtime_files"])


def test_installer_does_not_write_deep_reflection_config_by_default(tmp_path):
    report = install_plugin(hermes_home=tmp_path / "home", install_system_modules=True)

    assert report["deep_reflection_preset"] is None
    assert report["deep_reflection_config_written"] is False
    assert not (tmp_path / "home" / "system-modules" / "deep_reflection" / "config.json").exists()


def test_installer_can_write_deep_reflection_test_host_preset(tmp_path):
    report = install_plugin(
        hermes_home=tmp_path / "home",
        install_system_modules=True,
        deep_reflection_preset="test-host",
    )

    config_path = tmp_path / "home" / "system-modules" / "deep_reflection" / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert report["deep_reflection_preset"] == "test-host"
    assert report["deep_reflection_config_written"] is True
    assert config["preset"] == "test-host"
    assert config["enabled"] is True
    assert config["injection_mode"] == "auto_bounded"
    assert config["self_evolution_proposals_enabled"] is True
    assert config["wandering_seed_enabled"] is True
    assert config["working_updates_enabled"] is False
    assert config["llm_enabled"] is False


def test_installer_does_not_write_memory_sources_config_by_default(tmp_path):
    report = install_plugin(hermes_home=tmp_path / "home")

    assert report["memory_sources_preset"] is None
    assert report["memory_sources_config_written"] is False
    assert not (tmp_path / "home" / "memory-os" / "config.json").exists()


def test_installer_can_write_memory_sources_test_host_preset(tmp_path):
    config_path = tmp_path / "home" / "memory-os" / "config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps({"context_router": {"enabled": True}}, ensure_ascii=False),
        encoding="utf-8",
    )

    report = install_plugin(
        hermes_home=tmp_path / "home",
        memory_sources_preset="test-host",
    )

    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert report["memory_sources_preset"] == "test-host"
    assert report["memory_sources_config_written"] is True
    assert report["memory_sources_config_path"] == str(config_path)
    assert config["context_router"]["enabled"] is True
    assert config["memory_sources"]["enabled"] is True
    assert config["memory_sources"]["mode"] == "metadata_only"
    assert config["memory_sources"]["retention_days"] == 30
    assert config["memory_sources"]["record_live_prefetch"] is True
    assert config["memory_sources"]["record_dry_run"] is False
    assert report["session_mirror_preset"] == "test-host"
    assert report["session_mirror_config_written"] is True
    assert config["session_mirror"]["test_host_apply_allowed"] is True
    assert config["session_mirror"]["test_host_marker"] == "install_preset:test-host"
    assert config["session_mirror"]["production_apply_owner_ref_required"] is True


def test_installer_memory_sources_production_safe_preset_is_explicitly_off(tmp_path):
    report = install_plugin(
        hermes_home=tmp_path / "home",
        memory_sources_preset="production-safe",
    )

    config = json.loads((tmp_path / "home" / "memory-os" / "config.json").read_text(encoding="utf-8"))
    assert report["memory_sources_config_written"] is True
    assert config["memory_sources"]["enabled"] is False
    assert config["memory_sources"]["record_live_prefetch"] is True
    assert report["session_mirror_preset"] == "production-safe"
    assert report["session_mirror_config_written"] is True
    assert config["session_mirror"]["test_host_apply_allowed"] is False
    assert config["session_mirror"]["test_host_marker"] == ""
    assert config["session_mirror"]["production_apply_owner_ref_required"] is True


def test_installer_can_enable_shell_without_enabling_memory_os_as_general_plugin(tmp_path):
    config_path = tmp_path / "home" / "config.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "plugins:\n"
        "  enabled:\n"
        "    - existing-plugin\n",
        encoding="utf-8",
    )

    report = install_plugin(hermes_home=tmp_path / "home", enable_shell=True)

    assert report["agent_os_shell_enable_requested"] is True
    assert report["agent_os_shell_enabled"] is True
    assert report["agent_os_shell_enable_action"] == "config_yaml"
    config_text = config_path.read_text(encoding="utf-8")
    assert "memory-os-agent-os" in config_text
    assert "existing-plugin" in config_text
    assert "memory_os" not in _enabled_plugins_from_config_text(config_text)


def test_installer_shell_enable_is_idempotent(tmp_path):
    config_path = tmp_path / "home" / "config.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "plugins:\n"
        "  enabled:\n"
        "    - memory-os-agent-os\n",
        encoding="utf-8",
    )

    install_plugin(hermes_home=tmp_path / "home", enable_shell=True)

    enabled = _enabled_plugins_from_config_text(config_path.read_text(encoding="utf-8"))
    assert enabled.count("memory-os-agent-os") == 1
    assert "memory_os" not in enabled


def test_installer_shell_enable_removes_stale_disabled_marker(tmp_path):
    config_path = tmp_path / "home" / "config.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "plugins:\n"
        "  enabled:\n"
        "    - existing-plugin\n"
        "  disabled:\n"
        "    - memory-os-agent-os\n"
        "    - other-plugin\n",
        encoding="utf-8",
    )

    install_plugin(hermes_home=tmp_path / "home", enable_shell=True)

    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert config["plugins"]["enabled"] == ["existing-plugin", "memory-os-agent-os"]
    assert config["plugins"]["disabled"] == ["other-plugin"]


def test_installer_rejects_shell_enable_when_shell_was_not_installed_or_present(tmp_path):
    try:
        install_plugin(hermes_home=tmp_path / "home", install_shell=False, enable_shell=True)
    except SystemExit as exc:
        assert "Cannot enable memory-os-agent-os" in str(exc)
    else:
        raise AssertionError("expected shell enable to fail when shell plugin is absent")

    config_path = tmp_path / "home" / "config.yaml"
    assert not (tmp_path / "home" / "plugins" / "memory-os-agent-os").exists()
    if config_path.exists():
        assert "memory-os-agent-os" not in config_path.read_text(encoding="utf-8")


def test_installer_can_enable_existing_shell_without_reinstalling_it(tmp_path):
    shell_target = tmp_path / "home" / "plugins" / "memory-os-agent-os"
    shell_target.mkdir(parents=True)
    (shell_target / "__init__.py").write_text("", encoding="utf-8")
    (shell_target / "plugin.yaml").write_text("name: memory-os-agent-os\n", encoding="utf-8")

    report = install_plugin(hermes_home=tmp_path / "home", install_shell=False, enable_shell=True)

    assert report["agent_os_shell_install_requested"] is False
    assert report["agent_os_shell_file_count"] == 0
    assert report["agent_os_shell_enable_requested"] is True
    assert report["agent_os_shell_enabled"] is True
    enabled = _enabled_plugins_from_config_text(
        (tmp_path / "home" / "config.yaml").read_text(encoding="utf-8")
    )
    assert enabled == ["memory-os-agent-os"]


def test_installer_does_not_enable_shell_when_provider_enable_fails(tmp_path, monkeypatch):
    def fail_provider_enable(*args, **kwargs):
        raise RuntimeError("provider enable failed")

    monkeypatch.setattr("scripts.install_memory_os_plugin._enable_memory_provider", fail_provider_enable)

    try:
        install_plugin(hermes_home=tmp_path / "home", enable=True, enable_shell=True)
    except RuntimeError as exc:
        assert "provider enable failed" in str(exc)
    else:
        raise AssertionError("expected provider enable failure")

    config_path = tmp_path / "home" / "config.yaml"
    if config_path.exists():
        assert "memory-os-agent-os" not in config_path.read_text(encoding="utf-8")


def test_installer_preserves_provider_when_shell_enable_fails(tmp_path, monkeypatch):
    config_path = tmp_path / "home" / "config.yaml"

    def fake_provider_enable(hermes_home, command):
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text("memory:\n  provider: memory_os\n", encoding="utf-8")

    def fail_shell_enable(*args, **kwargs):
        raise RuntimeError("shell enable failed")

    monkeypatch.setattr("scripts.install_memory_os_plugin._enable_memory_provider", fake_provider_enable)
    monkeypatch.setattr("scripts.install_memory_os_plugin._enable_agent_os_shell", fail_shell_enable)

    try:
        install_plugin(hermes_home=tmp_path / "home", enable=True, enable_shell=True)
    except RuntimeError as exc:
        assert "shell enable failed" in str(exc)
    else:
        raise AssertionError("expected shell enable failure")

    config_text = config_path.read_text(encoding="utf-8")
    assert "provider: memory_os" in config_text
    assert "memory-os-agent-os" not in config_text


def test_provider_enable_subprocess_stdout_is_suppressed(tmp_path, monkeypatch):
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args[0], 0)

    monkeypatch.setattr("scripts.install_memory_os_plugin.subprocess.run", fake_run)

    report = install_plugin(hermes_home=tmp_path / "home", enable=True)

    assert report["enabled"] is True
    assert calls
    assert calls[0][1]["stdout"] is subprocess.DEVNULL


def test_provider_enable_missing_hermes_command_reports_actionable_error(tmp_path, monkeypatch):
    def fake_run(*args, **kwargs):
        raise FileNotFoundError("hermes")

    monkeypatch.setattr("scripts.install_memory_os_plugin.subprocess.run", fake_run)

    try:
        install_plugin(hermes_home=tmp_path / "home", enable=True)
    except SystemExit as exc:
        message = str(exc)
    else:
        raise AssertionError("expected missing hermes command error")

    assert "hermes" in message
    assert "scripts/install_memory_os.sh" in message
    assert "--enable" in message


def test_installer_rejects_shell_backups_inside_plugin_scan_tree(tmp_path):
    source = tmp_path / "source"
    shutil_copy_source(SOURCE_PLUGIN_DIR, source)
    bad_backup = tmp_path / "home" / "plugins" / "memory-os-agent-os.backup" / "nested"
    bad_backup.mkdir(parents=True)
    (bad_backup / "plugin.yaml").write_text("name: memory-os-agent-os\n", encoding="utf-8")

    try:
        install_plugin(hermes_home=tmp_path / "home", source=source)
    except SystemExit as exc:
        assert "plugin backup manifest inside plugin scan tree" in str(exc)
    else:
        raise AssertionError("expected backup manifest guard to fail")


def test_installer_deep_reflection_production_safe_preset_is_explicitly_off(tmp_path):
    report = install_plugin(
        hermes_home=tmp_path / "home",
        deep_reflection_preset="production-safe",
    )

    config = json.loads(
        (tmp_path / "home" / "system-modules" / "deep_reflection" / "config.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["deep_reflection_config_written"] is True
    assert config["enabled"] is False
    assert config["injection_mode"] == "disabled"
    assert config["self_evolution_proposals_enabled"] is False
    assert config["wandering_seed_enabled"] is False


def test_installer_writes_low_clue_recall_llm_judge_report_only_config(tmp_path):
    report = install_plugin(
        hermes_home=tmp_path / "home",
        llm_judge_preset="report-only",
    )

    config = json.loads((tmp_path / "home" / "memory-os" / "config.json").read_text(encoding="utf-8"))
    assert report["low_clue_recall_config_written"] is True
    assert report["llm_judge_preset"] == "report-only"
    assert config["low_clue_recall"]["enabled"] is True
    assert config["low_clue_recall"]["llm_judge"]["enabled"] is True
    assert config["low_clue_recall"]["llm_judge"]["mode"] == "report_only"
    assert config["low_clue_recall"]["llm_judge"]["provider"] == "hermes_default"
    assert config["low_clue_recall"]["llm_judge"]["model"] is None
    assert config["low_clue_recall"]["llm_judge"]["max_tokens"] == 1024


def test_installer_writes_low_clue_recall_llm_judge_active_config(tmp_path):
    report = install_plugin(
        hermes_home=tmp_path / "home",
        llm_judge_preset="active",
    )

    config = json.loads((tmp_path / "home" / "memory-os" / "config.json").read_text(encoding="utf-8"))
    assert report["low_clue_recall_config_written"] is True
    assert report["llm_judge_preset"] == "active"
    assert config["low_clue_recall"]["enabled"] is True
    assert config["low_clue_recall"]["preset"] == "active"
    assert config["low_clue_recall"]["llm_judge"]["enabled"] is True
    assert config["low_clue_recall"]["llm_judge"]["mode"] == "bounded_vote"
    assert config["low_clue_recall"]["llm_judge"]["provider"] == "hermes_default"


def test_test_host_install_shell_wraps_full_agent_os_install():
    script = Path("scripts/install_memory_os_test_host.sh")
    text = script.read_text(encoding="utf-8")

    assert 'exec "${SCRIPT_DIR}/install_memory_os.sh" --yes --test-host "$@"' in text


def test_interactive_install_shell_exposes_safe_operator_flow():
    script = Path("scripts/install_memory_os.sh")
    text = script.read_text(encoding="utf-8")

    assert "select_hermes_home" in text
    assert "inspect_current_state" in text
    assert "ask_yes_no" in text
    assert "--test-host" in text
    assert "--production-safe" in text
    assert "--memory-sources-preset" in text
    assert "--llm-judge-preset" in text
    assert "--hindsight" in text
    assert "default active reuses Hermes" in text
    assert "active enables retain/recall/reflect" in text
    assert "report-only" in text
    assert "--yes" in text
    assert "--dry-run" in text
    assert "scripts/install_memory_os_plugin.py" in text
    assert "--install-owner-cron-onboarding" in text
    assert "--run-owner-cron-onboarding" in text
    assert "--owner-cron-owner-approved" in text
    assert "channel_directory.json" in text
    assert "install_runtime" in text
    assert "enable_runtime" in text
    assert "install_cognitive_loop" in text
    assert "enable_cognitive_loop" in text
    assert "runtime artifacts are not being installed" in text
    assert "normalize_shell_enablement" in text
    assert "require_hermes_for_selected_actions" in text
    assert 'args+=("--hindsight" "${HINDSIGHT_MODE}")' in text
    assert "The script does not restart hermes-gateway.service" in text
    assert "hermes memory-os-agent-os status" in text
    assert "hermes memory-os-agent-os doctor" in text
    assert "plugins.memory.memory_os cognitive-loop status" in text


def test_install_shell_exposes_one_command_operational_product_install():
    text = Path("scripts/install_memory_os.sh").read_text(encoding="utf-8")

    assert "--operational" in text
    assert "MODE=\"operational\"" in text
    assert "DEEP_REFLECTION_PRESET=\"${DEEP_REFLECTION_PRESET:-operational}\"" in text
    assert "MEMORY_SOURCES_PRESET=\"${MEMORY_SOURCES_PRESET:-operational}\"" in text
    assert "default_enable_cognitive_loop=\"yes\"" in text
    assert "default_enable_owner_cron_onboarding=\"yes\"" in text
    assert "active-closure Hermes cron onboarding" in text
    assert "--owner-cron-profile" in text
    assert "seven-node Hermes cron onboarding" not in text
    assert "--enable-owner-cron-onboarding" in text
    assert "--run-owner-cron-onboarding" in text


def test_test_host_wrapper_delegates_to_interactive_installer_defaults():
    text = Path("scripts/install_memory_os_test_host.sh").read_text(encoding="utf-8")

    assert "install_memory_os.sh" in text
    assert "--yes" in text
    assert "--test-host" in text


def test_memory_os_status_command_uses_current_hermes_home(tmp_path, monkeypatch, capsys):
    from plugins.memory.memory_os.cli import memory_os_command
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    roots = MemoryOSRoots.from_hermes_home(tmp_path)
    MemoryOSStore(roots).initialize()
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    result = memory_os_command(argparse.Namespace(memory_os_command="status"))

    assert result == 0
    output = json.loads(capsys.readouterr().out)
    assert output["root"] == str(tmp_path / "memory-os")


def shutil_copy_source(source: Path, target: Path) -> None:
    import shutil

    shutil.copytree(source, target)


def _fake_hermes(tmp_path: Path) -> str:
    script = tmp_path / "fake_hermes_for_install.py"
    script.write_text(
        """
import json
import os
import pathlib
import sys

args = sys.argv[1:]
home = pathlib.Path(os.environ.get("HERMES_HOME", "."))

if args[:3] == ["cron", "create", "--help"]:
    print("usage: hermes cron create [--name NAME] [--deliver DELIVER] [--script SCRIPT] [--no-agent] schedule prompt")
    raise SystemExit(0)

if args[:3] == ["memory-os-agent-os", "review", "render-digest"]:
    print("Memory-OS owner review digest")
    raise SystemExit(0)

if args[:2] == ["cron", "create"]:
    def value(flag):
        return args[args.index(flag) + 1] if flag in args else ""
    jobs_path = home / "cron" / "jobs.json"
    jobs_path.parent.mkdir(parents=True, exist_ok=True)
    loaded = json.loads(jobs_path.read_text(encoding="utf-8")) if jobs_path.exists() else {"jobs": []}
    jobs = loaded.get("jobs", [])
    name = value("--name")
    jobs.append(
        {
            "id": "job_" + name.replace("-", "_"),
            "name": name,
            "enabled": True,
            "deliver": value("--deliver"),
            "script": value("--script"),
            "no_agent": "--no-agent" in args,
            "prompt": args[-1],
        }
    )
    jobs_path.write_text(json.dumps({"jobs": jobs}), encoding="utf-8")
    raise SystemExit(0)

print("unexpected command", args, file=sys.stderr)
raise SystemExit(2)
""".lstrip(),
        encoding="utf-8",
    )
    if os.name == "nt":
        launcher = tmp_path / "hermes.cmd"
        launcher.write_text(f'@"{sys.executable}" "{script}" %*\n', encoding="utf-8")
    else:
        launcher = tmp_path / "hermes"
        launcher.write_text(f'#! /bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        launcher.chmod(0o755)
    return str(launcher)


def _enabled_plugins_from_config_text(config_text: str) -> list[str]:
    import yaml

    config = yaml.safe_load(config_text) or {}
    return list((config.get("plugins") or {}).get("enabled") or [])
