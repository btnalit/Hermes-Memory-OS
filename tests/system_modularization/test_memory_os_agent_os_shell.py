from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
SHELL_DIR = REPO_ROOT / "plugins" / "memory-os-agent-os"


class FakePluginContext:
    def __init__(self) -> None:
        self.cli_commands: list[dict[str, Any]] = []
        self.hooks: list[str] = []
        self.slash_commands: list[str] = []

    def register_cli_command(self, **kwargs: Any) -> None:
        self.cli_commands.append(kwargs)

    def register_hook(self, name: str, callback: Any) -> None:
        self.hooks.append(name)

    def register_command(self, name: str, handler: Any, **kwargs: Any) -> None:
        self.slash_commands.append(name)


def load_shell_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("memory_os_agent_os_shell", SHELL_DIR / "__init__.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_shell_module_from(path: Path, name: str = "memory_os_agent_os_shell_installed") -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_shell_manifest_is_official_user_plugin_shape():
    manifest = (SHELL_DIR / "plugin.yaml").read_text(encoding="utf-8")

    assert "name: memory-os-agent-os" in manifest
    assert "version: 0.1.0" in manifest
    assert "kind: standalone" in manifest
    assert "on_session_start" in manifest
    assert "on_session_reset" in manifest
    assert "on_session_finalize" in manifest


def test_shell_registers_cli_alias_and_session_marker_hooks_without_slash_commands():
    module = load_shell_module()
    ctx = FakePluginContext()

    module.register(ctx)

    assert [command["name"] for command in ctx.cli_commands] == ["memory-os-agent-os"]
    command = ctx.cli_commands[0]
    assert command["handler_fn"] is module.memory_os_agent_os_command
    assert callable(command["setup_fn"])
    assert ctx.hooks == ["on_session_start", "on_session_reset", "on_session_finalize"]
    assert ctx.slash_commands == []


def test_shell_cli_exposes_status_and_doctor_aliases():
    module = load_shell_module()
    parser = argparse.ArgumentParser()

    module.register_cli(parser)

    assert parser.parse_args(["status"]).agent_os_command == "status"
    assert parser.parse_args(["doctor"]).agent_os_command == "doctor"
    low_clue_args = parser.parse_args(["low-clue-recall", "dry-run", "--query", "继续昨天那个"])
    assert low_clue_args.agent_os_command == "low-clue-recall"
    assert low_clue_args.low_clue_recall_command == "dry-run"
    assert low_clue_args.query == "继续昨天那个"
    last_args = parser.parse_args(["memory-sources", "last"])
    assert last_args.agent_os_command == "memory-sources"
    assert last_args.memory_sources_command == "last"
    history_args = parser.parse_args(["memory-sources", "history", "--limit", "5"])
    assert history_args.memory_sources_command == "history"
    assert history_args.limit == 5
    stats_args = parser.parse_args(["memory-sources", "stats", "--hours", "24"])
    assert stats_args.memory_sources_command == "stats"
    assert stats_args.hours == 24
    feedback_args = parser.parse_args(["memory-sources", "feedback", "last", "--rating", "useful"])
    assert feedback_args.memory_sources_command == "feedback"
    assert feedback_args.memory_sources_feedback_command == "last"
    assert feedback_args.rating == "useful"
    feedback_history_args = parser.parse_args(["memory-sources", "feedback", "history", "--limit", "3"])
    assert feedback_history_args.memory_sources_feedback_command == "history"
    assert feedback_history_args.limit == 3
    modules_status_args = parser.parse_args(["modules", "status"])
    assert modules_status_args.agent_os_command == "modules"
    assert modules_status_args.modules_command == "status"
    modules_doctor_args = parser.parse_args(["modules", "doctor"])
    assert modules_doctor_args.modules_command == "doctor"
    modules_run_once_args = parser.parse_args(["modules", "run-once", "--module", "cron_mirror", "--dry-run"])
    assert modules_run_once_args.modules_command == "run-once"
    assert modules_run_once_args.module == "cron_mirror"
    assert modules_run_once_args.dry_run is True
    modules_validate_args = parser.parse_args(["modules", "validate-no-send"])
    assert modules_validate_args.modules_command == "validate-no-send"
    dr_history_args = parser.parse_args(["modules", "deep_reflection", "history", "--days", "3"])
    assert dr_history_args.modules_command == "deep_reflection"
    assert dr_history_args.deep_reflection_command == "history"
    assert dr_history_args.days == 3


def test_shell_status_alias_delegates_to_existing_memory_os_cli(monkeypatch, capsys):
    module = load_shell_module()
    calls: list[argparse.Namespace] = []

    def fake_delegate(args: argparse.Namespace) -> int:
        calls.append(args)
        print(json.dumps({"delegated": args.memory_os_command}, sort_keys=True))
        return 0

    monkeypatch.setattr(module, "_delegate_to_memory_os_cli", fake_delegate)
    args = argparse.Namespace(agent_os_command="status", passthrough="kept")

    assert module.memory_os_agent_os_command(args) == 0

    assert calls[0].memory_os_command == "status"
    assert calls[0].passthrough == "kept"
    assert json.loads(capsys.readouterr().out) == {"delegated": "status"}


def test_shell_memory_sources_alias_delegates_to_existing_memory_os_cli(monkeypatch, capsys):
    module = load_shell_module()
    calls: list[argparse.Namespace] = []

    def fake_delegate(args: argparse.Namespace) -> int:
        calls.append(args)
        print(json.dumps({"delegated": args.memory_os_command, "subcommand": args.memory_sources_command}))
        return 0

    monkeypatch.setattr(module, "_delegate_to_memory_os_cli", fake_delegate)
    args = argparse.Namespace(agent_os_command="memory-sources", memory_sources_command="stats", hours=24)

    assert module.memory_os_agent_os_command(args) == 0

    assert calls[0].memory_os_command == "memory-sources"
    assert calls[0].memory_sources_command == "stats"
    assert json.loads(capsys.readouterr().out) == {
        "delegated": "memory-sources",
        "subcommand": "stats",
    }


def test_shell_low_clue_recall_alias_delegates_to_existing_memory_os_cli(monkeypatch, capsys):
    module = load_shell_module()
    calls: list[argparse.Namespace] = []

    def fake_delegate(args: argparse.Namespace) -> int:
        calls.append(args)
        print(json.dumps({"delegated": args.memory_os_command, "subcommand": args.low_clue_recall_command}))
        return 0

    monkeypatch.setattr(module, "_delegate_to_memory_os_cli", fake_delegate)
    args = argparse.Namespace(
        agent_os_command="low-clue-recall",
        low_clue_recall_command="dry-run",
        query="继续昨天那个",
    )

    assert module.memory_os_agent_os_command(args) == 0

    assert calls[0].memory_os_command == "low-clue-recall"
    assert calls[0].low_clue_recall_command == "dry-run"
    assert json.loads(capsys.readouterr().out) == {
        "delegated": "low-clue-recall",
        "subcommand": "dry-run",
    }


def test_shell_modules_alias_delegates_to_existing_memory_os_cli(monkeypatch, capsys):
    module = load_shell_module()
    calls: list[argparse.Namespace] = []

    def fake_delegate(args: argparse.Namespace) -> int:
        calls.append(args)
        print(json.dumps({"delegated": args.memory_os_command, "subcommand": args.modules_command}))
        return 0

    monkeypatch.setattr(module, "_delegate_to_memory_os_cli", fake_delegate)
    args = argparse.Namespace(
        agent_os_command="modules",
        modules_command="run-once",
        module="cron_mirror",
        dry_run=True,
        apply=False,
    )

    assert module.memory_os_agent_os_command(args) == 0

    assert calls[0].memory_os_command == "modules"
    assert calls[0].modules_command == "run-once"
    assert calls[0].module == "cron_mirror"
    assert json.loads(capsys.readouterr().out) == {
        "delegated": "modules",
        "subcommand": "run-once",
    }


def test_shell_unknown_alias_fails_closed():
    module = load_shell_module()

    result = module.memory_os_agent_os_command(argparse.Namespace(agent_os_command="heartbeat"))

    assert result == 2


def test_shell_fails_closed_when_memory_os_runtime_is_missing(monkeypatch, capsys):
    module = load_shell_module()

    def missing_runtime():
        raise ModuleNotFoundError("No module named 'plugins.memory.memory_os'")

    monkeypatch.setattr(module, "_load_memory_os_command", missing_runtime)

    result = module.memory_os_agent_os_command(argparse.Namespace(agent_os_command="status"))

    assert result == 1
    report = json.loads(capsys.readouterr().out)
    assert report["schema_version"] == "memory-os.agent_os_shell.v0"
    assert report["status"] == "error"
    assert report["code"] == "memory_os_provider_missing"


def test_shell_runtime_path_extends_existing_plugins_namespace(monkeypatch, tmp_path):
    module = load_shell_module()
    hermes_home = tmp_path / "home"
    runtime_root = hermes_home / "memory-os" / "runtime" / "python"
    runtime_plugins = runtime_root / "plugins"
    runtime_memory = runtime_plugins / "memory"
    runtime_plugins.mkdir(parents=True)
    runtime_memory.mkdir()
    existing_plugins = ModuleType("plugins")
    existing_plugins.__path__ = ["bundled/plugins"]  # type: ignore[attr-defined]
    existing_memory = ModuleType("plugins.memory")
    existing_memory.__path__ = ["bundled/plugins/memory"]  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "plugins", existing_plugins)
    monkeypatch.setitem(sys.modules, "plugins.memory", existing_memory)
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    module._ensure_memory_os_runtime_path()

    assert str(runtime_root) in sys.path
    assert str(runtime_plugins) in existing_plugins.__path__  # type: ignore[attr-defined]
    assert str(runtime_memory) in existing_memory.__path__  # type: ignore[attr-defined]


def test_shell_runtime_path_adds_flat_provider_parent(monkeypatch, tmp_path):
    module = load_shell_module()
    hermes_home = tmp_path / "home"
    flat_provider = hermes_home / "plugins" / "memory_os"
    flat_provider.mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    module._ensure_memory_os_runtime_path()

    assert str(hermes_home / "plugins") in sys.path


def test_shell_runtime_path_infers_hermes_home_from_installed_plugin_without_env(monkeypatch, tmp_path):
    original_sys_path = list(sys.path)
    hermes_home = tmp_path / "home"
    installed_shell = hermes_home / "plugins" / "memory-os-agent-os"
    installed_shell.mkdir(parents=True)
    shell_init = installed_shell / "__init__.py"
    shell_init.write_text((SHELL_DIR / "__init__.py").read_text(encoding="utf-8"), encoding="utf-8")
    runtime_root = hermes_home / "memory-os" / "runtime" / "python"
    runtime_root.mkdir(parents=True)
    flat_provider = hermes_home / "plugins" / "memory_os"
    flat_provider.mkdir(parents=True)
    monkeypatch.delenv("HERMES_HOME", raising=False)

    try:
        module = load_shell_module_from(shell_init)
        module._ensure_memory_os_runtime_path()

        assert str(runtime_root) in sys.path
        assert str(hermes_home / "plugins") in sys.path
    finally:
        sys.path[:] = original_sys_path
        _clear_imported_memory_os_modules()


def test_shell_alias_imports_provider_from_inferred_runtime_without_env(monkeypatch, tmp_path, capsys):
    original_sys_path = list(sys.path)
    hermes_home = tmp_path / "home"
    installed_shell = hermes_home / "plugins" / "memory-os-agent-os"
    installed_shell.mkdir(parents=True)
    shell_init = installed_shell / "__init__.py"
    shell_init.write_text((SHELL_DIR / "__init__.py").read_text(encoding="utf-8"), encoding="utf-8")
    runtime_pkg = hermes_home / "memory-os" / "runtime" / "python" / "plugins" / "memory" / "memory_os"
    runtime_pkg.mkdir(parents=True)
    for package in [
        runtime_pkg.parents[2],
        runtime_pkg.parents[1],
        runtime_pkg.parent,
        runtime_pkg,
    ]:
        package.joinpath("__init__.py").write_text("", encoding="utf-8")
    runtime_pkg.joinpath("cli.py").write_text(
        "def memory_os_command(args):\n"
        "    print('{\"status\":\"ok\",\"delegated\":\"%s\"}' % args.memory_os_command)\n"
        "    return 0\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("HERMES_HOME", raising=False)
    for name in [
        "plugins",
        "plugins.memory",
        "plugins.memory.memory_os",
        "plugins.memory.memory_os.cli",
    ]:
        sys.modules.pop(name, None)

    try:
        module = load_shell_module_from(shell_init, name="memory_os_agent_os_shell_installed_runtime")

        result = module.memory_os_agent_os_command(argparse.Namespace(agent_os_command="status"))

        assert result == 0
        assert json.loads(capsys.readouterr().out) == {"delegated": "status", "status": "ok"}
    finally:
        sys.path[:] = original_sys_path
        _clear_imported_memory_os_modules()


def test_shell_session_start_hook_writes_bounded_audit_marker(monkeypatch, tmp_path):
    module = load_shell_module()
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    module._on_session_start(session_id="sess-1", platform="telegram", model="test-model")

    entries = _audit_entries(tmp_path)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["action"] == "agent_os_shell_session_started"
    assert entry["status"] == "ok"
    assert entry["target"] == "memory-os-agent-os"
    assert entry["details"] == {
        "hook": "on_session_start",
        "model": "test-model",
        "platform": "telegram",
        "session_id": "sess-1",
    }


def test_shell_session_reset_and_finalize_hooks_write_audit_markers(monkeypatch, tmp_path):
    module = load_shell_module()
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    module._on_session_reset(session_id="new-session", platform="telegram")
    module._on_session_finalize(session_id="old-session", platform="telegram")

    actions = [entry["action"] for entry in _audit_entries(tmp_path)]
    assert actions == [
        "agent_os_shell_session_reset",
        "agent_os_shell_session_finalized",
    ]


def test_shell_session_hooks_skip_without_hermes_home(monkeypatch, tmp_path):
    module = load_shell_module()
    monkeypatch.delenv("HERMES_HOME", raising=False)

    module._on_session_start(session_id="sess-1", platform="telegram", model="test-model")

    assert not (tmp_path / "memory-os" / "audit" / "write_audit.jsonl").exists()


def _audit_entries(hermes_home: Path) -> list[dict[str, Any]]:
    audit_path = hermes_home / "memory-os" / "audit" / "write_audit.jsonl"
    return [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]


def _clear_imported_memory_os_modules() -> None:
    for name in [
        "plugins",
        "plugins.memory",
        "plugins.memory.memory_os",
        "plugins.memory.memory_os.cli",
        "memory_os",
        "memory_os.cli",
    ]:
        sys.modules.pop(name, None)
