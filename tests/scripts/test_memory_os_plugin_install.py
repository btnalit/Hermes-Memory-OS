import importlib.util
import json
import argparse
import subprocess
import sys
from pathlib import Path

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


def test_installer_can_install_system_module_runtime_package(tmp_path):
    report = install_plugin(hermes_home=tmp_path / "home", install_system_modules=True)

    runtime_python = tmp_path / "home" / "memory-os" / "runtime" / "python"
    runtime_root = runtime_python / "plugins"
    assert report["system_modules_installed"] is True
    assert report["system_module_file_count"] > 0
    assert report["agent_runtime_file_count"] > 0
    assert runtime_root.joinpath("system", "lifecycle.py").is_file()
    assert runtime_root.joinpath("modules", "context", "digest_consolidation.py").is_file()
    assert runtime_root.joinpath("modules", "cognition", "deep_reflection.py").is_file()
    assert runtime_root.joinpath("modules", "cognition", "inner_drive.py").is_file()
    assert runtime_root.joinpath("modules", "expression", "speak_gate.py").is_file()
    assert runtime_root.joinpath("modules", "governance", "feedback_bridge.py").is_file()
    assert runtime_root.joinpath("memory", "memory_os", "store.py").is_file()
    assert runtime_root.joinpath("memory", "memory_os", "shadow_journal.py").is_file()
    assert runtime_python.joinpath("agent", "memory_provider.py").is_file()
    assert not any("__pycache__" in path for path in report["system_module_files"])
    assert not any("__pycache__" in path for path in report["agent_runtime_files"])


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
    assert "--yes" in text
    assert "--dry-run" in text
    assert "scripts/install_memory_os_plugin.py" in text
    assert "install_runtime" in text
    assert "enable_runtime" in text
    assert "install_cognitive_loop" in text
    assert "enable_cognitive_loop" in text
    assert "runtime artifacts are not being installed" in text
    assert "normalize_shell_enablement" in text
    assert "require_hermes_for_selected_actions" in text
    assert "The script does not restart hermes-gateway.service" in text
    assert "hermes memory-os-agent-os status" in text
    assert "hermes memory-os-agent-os doctor" in text
    assert "plugins.memory.memory_os cognitive-loop status" in text


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


def _enabled_plugins_from_config_text(config_text: str) -> list[str]:
    import yaml

    config = yaml.safe_load(config_text) or {}
    return list((config.get("plugins") or {}).get("enabled") or [])
