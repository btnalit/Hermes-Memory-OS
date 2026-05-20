import importlib.util
import json
import argparse
import sys
from pathlib import Path

from scripts.install_memory_os_plugin import SOURCE_PLUGIN_DIR, install_plugin


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
    assert not (tmp_path / "home" / "plugins" / "memory_os").exists()


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
    assert "hermes memory_os heartbeat" in wrapper.read_text(encoding="utf-8")
    assert "OnUnitActiveSec=5min" in timer.read_text(encoding="utf-8")


def test_installer_can_install_system_module_runtime_package(tmp_path):
    report = install_plugin(hermes_home=tmp_path / "home", install_system_modules=True)

    runtime_root = tmp_path / "home" / "memory-os" / "runtime" / "python" / "plugins"
    assert report["system_modules_installed"] is True
    assert report["system_module_file_count"] > 0
    assert runtime_root.joinpath("system", "lifecycle.py").is_file()
    assert runtime_root.joinpath("modules", "cognition", "inner_drive.py").is_file()
    assert runtime_root.joinpath("modules", "expression", "speak_gate.py").is_file()
    assert runtime_root.joinpath("memory", "memory_os", "store.py").is_file()
    assert not any("__pycache__" in path for path in report["system_module_files"])


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
