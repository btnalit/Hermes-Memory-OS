#!/usr/bin/env python3
"""Install Memory-OS as a Hermes user memory provider plugin."""

from __future__ import annotations

import argparse
import json
import os
import stat
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PLUGIN_DIR = REPO_ROOT / "plugins" / "memory" / "memory_os"
SOURCE_AGENT_OS_SHELL_DIR = REPO_ROOT / "plugins" / "memory-os-agent-os"
SOURCE_PACKAGE_DIR = REPO_ROOT / "plugins"
SOURCE_AGENT_DIR = REPO_ROOT / "agent"
AGENT_OS_SHELL_PLUGIN_NAME = "memory-os-agent-os"
MEMORY_PROVIDER_PLUGIN_NAME = "memory_os"


DEEP_REFLECTION_PRESETS: dict[str, dict[str, object]] = {
    "production-safe": {
        "enabled": False,
        "injection_mode": "disabled",
        "working_updates_enabled": False,
        "self_evolution_proposals_enabled": False,
        "wandering_seed_enabled": False,
    },
    "observe": {
        "enabled": True,
        "injection_mode": "dry_run",
        "working_updates_enabled": False,
        "self_evolution_proposals_enabled": False,
        "wandering_seed_enabled": False,
    },
    "auto-bounded": {
        "enabled": True,
        "injection_mode": "auto_bounded",
        "working_updates_enabled": False,
        "self_evolution_proposals_enabled": False,
        "wandering_seed_enabled": False,
    },
    "test-host": {
        "enabled": True,
        "injection_mode": "auto_bounded",
        "working_updates_enabled": False,
        "self_evolution_proposals_enabled": True,
        "wandering_seed_enabled": True,
        "max_optional_outputs": 2,
        "max_self_evolution_proposals": 1,
        "max_wandering_seeds": 1,
    },
}


DEEP_REFLECTION_CONFIG_DEFAULTS: dict[str, object] = {
    "enabled": False,
    "injection_mode": "disabled",
    "max_cards": 2,
    "max_chars_total": 600,
    "max_chars_per_card": 260,
    "ttl_hours": 24,
    "analysis_mode": "deterministic",
    "llm_enabled": False,
    "working_updates_enabled": False,
    "self_evolution_proposals_enabled": False,
    "wandering_seed_enabled": False,
}


def install_plugin(
    *,
    hermes_home: Path,
    source: Path = SOURCE_PLUGIN_DIR,
    shell_source: Path = SOURCE_AGENT_OS_SHELL_DIR,
    install_shell: bool = True,
    enable: bool = False,
    enable_shell: bool = False,
    install_runtime: bool = False,
    install_system_modules: bool = False,
    enable_runtime: bool = False,
    runtime_interval: str = "5min",
    install_cognitive_loop: bool = False,
    enable_cognitive_loop: bool = False,
    cognitive_loop_interval: str = "6h",
    deep_reflection_preset: str | None = None,
    systemd_dir: Path | None = None,
    dry_run: bool = False,
) -> dict[str, object]:
    source = source.expanduser().resolve()
    shell_source = shell_source.expanduser().resolve()
    hermes_home = hermes_home.expanduser().resolve()
    target = hermes_home / "plugins" / "memory_os"
    shell_target = hermes_home / "plugins" / AGENT_OS_SHELL_PLUGIN_NAME
    _guard_plugin_scan_tree_backups(hermes_home)
    _validate_source(source)
    if install_shell:
        _validate_agent_os_shell_source(shell_source)
    if enable_shell and not install_shell and not (shell_target / "plugin.yaml").is_file():
        raise SystemExit(
            f"Cannot enable {AGENT_OS_SHELL_PLUGIN_NAME}: shell plugin is not installed at {shell_target}"
        )

    copied_files = _copy_tree(source, target, dry_run=dry_run)
    shell_files: list[Path] = []
    if install_shell:
        shell_files = _copy_tree(shell_source, shell_target, dry_run=dry_run)
    system_module_files: list[Path] = []
    system_module_root = hermes_home / "memory-os" / "runtime" / "python"
    system_module_target = system_module_root / "plugins"
    agent_runtime_target = system_module_root / "agent"
    agent_runtime_files: list[Path] = []
    if install_system_modules:
        _validate_system_module_source(SOURCE_PACKAGE_DIR)
        system_module_files = _copy_tree(SOURCE_PACKAGE_DIR, system_module_target, dry_run=dry_run)
        _validate_agent_source(SOURCE_AGENT_DIR)
        agent_runtime_files = _copy_tree(SOURCE_AGENT_DIR, agent_runtime_target, dry_run=dry_run)
    deep_reflection_config: dict[str, object] | None = None
    deep_reflection_config_path: Path | None = None
    if deep_reflection_preset is not None:
        deep_reflection_config_path, deep_reflection_config = _write_deep_reflection_config(
            hermes_home,
            preset=deep_reflection_preset,
            dry_run=dry_run,
        )
    runtime_artifacts: list[Path] = []
    if install_runtime or enable_runtime:
        runtime_artifacts = _write_runtime_artifacts(
            hermes_home,
            interval=runtime_interval,
            dry_run=dry_run,
        )
    cognitive_loop_artifacts: list[Path] = []
    if install_cognitive_loop or enable_cognitive_loop:
        cognitive_loop_artifacts = _write_cognitive_loop_artifacts(
            hermes_home,
            interval=cognitive_loop_interval,
            dry_run=dry_run,
        )
    enabled = False
    enable_command: list[str] = []
    if enable:
        enable_command = ["hermes", "config", "set", "memory.provider", "memory_os"]
        if not dry_run:
            _enable_memory_provider(hermes_home, enable_command)
            enabled = True

    shell_enabled = False
    shell_enable_action = ""
    if enable_shell:
        shell_enable_action = "config_yaml"
        if not dry_run:
            _enable_agent_os_shell(hermes_home)
            shell_enabled = True

    runtime_enabled = False
    runtime_enable_command: list[str] = []
    if enable_runtime:
        if not install_runtime:
            runtime_artifacts = _write_runtime_artifacts(
                hermes_home,
                interval=runtime_interval,
                dry_run=dry_run,
            )
        unit_dir = (systemd_dir or (Path.home() / ".config" / "systemd" / "user")).expanduser().resolve()
        service_src = hermes_home / "memory-os" / "systemd" / "hermes-memory-os-heartbeat.service"
        timer_src = hermes_home / "memory-os" / "systemd" / "hermes-memory-os-heartbeat.timer"
        runtime_enable_command = [
            "systemctl",
            "--user",
            "enable",
            "--now",
            "hermes-memory-os-heartbeat.timer",
        ]
        if not dry_run:
            unit_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(service_src, unit_dir / service_src.name)
            shutil.copy2(timer_src, unit_dir / timer_src.name)
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
            subprocess.run(runtime_enable_command, check=True)
            runtime_enabled = True

    cognitive_loop_enabled = False
    cognitive_loop_enable_command: list[str] = []
    if enable_cognitive_loop:
        if not install_cognitive_loop:
            cognitive_loop_artifacts = _write_cognitive_loop_artifacts(
                hermes_home,
                interval=cognitive_loop_interval,
                dry_run=dry_run,
            )
        unit_dir = (systemd_dir or (Path.home() / ".config" / "systemd" / "user")).expanduser().resolve()
        service_src = hermes_home / "memory-os" / "systemd" / "hermes-memory-os-cognitive-loop.service"
        timer_src = hermes_home / "memory-os" / "systemd" / "hermes-memory-os-cognitive-loop.timer"
        cognitive_loop_enable_command = [
            "systemctl",
            "--user",
            "enable",
            "--now",
            "hermes-memory-os-cognitive-loop.timer",
        ]
        if not dry_run:
            unit_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(service_src, unit_dir / service_src.name)
            shutil.copy2(timer_src, unit_dir / timer_src.name)
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
            subprocess.run(cognitive_loop_enable_command, check=True)
            cognitive_loop_enabled = True

    return {
        "schema_version": "memory-os.install.v0",
        "provider": "memory_os",
        "source": str(source),
        "target": str(target),
        "copied_file_count": len(copied_files),
        "copied_files": [str(path.relative_to(target)) for path in copied_files],
        "agent_os_shell": AGENT_OS_SHELL_PLUGIN_NAME,
        "agent_os_shell_install_requested": install_shell,
        "agent_os_shell_installed": bool(shell_files) and not dry_run,
        "agent_os_shell_source": str(shell_source),
        "agent_os_shell_target": str(shell_target),
        "agent_os_shell_file_count": len(shell_files),
        "agent_os_shell_files": [str(path.relative_to(shell_target)) for path in shell_files],
        "agent_os_shell_enable_requested": enable_shell,
        "agent_os_shell_enabled": shell_enabled,
        "agent_os_shell_enable_action": shell_enable_action,
        "system_modules_install_requested": install_system_modules,
        "system_modules_installed": bool(system_module_files) and not dry_run,
        "system_module_target": str(system_module_target),
        "system_module_file_count": len(system_module_files),
        "system_module_files": [str(path.relative_to(system_module_target)) for path in system_module_files],
        "agent_runtime_target": str(agent_runtime_target),
        "agent_runtime_file_count": len(agent_runtime_files),
        "agent_runtime_files": [str(path.relative_to(agent_runtime_target)) for path in agent_runtime_files],
        "enable_requested": enable,
        "enabled": enabled,
        "enable_command": enable_command,
        "runtime_artifacts_installed": bool(runtime_artifacts) and not dry_run,
        "runtime_artifacts": [str(path) for path in runtime_artifacts],
        "runtime_interval": runtime_interval,
        "runtime_enable_requested": enable_runtime,
        "runtime_enabled": runtime_enabled,
        "runtime_enable_command": runtime_enable_command,
        "cognitive_loop_artifacts_installed": bool(cognitive_loop_artifacts) and not dry_run,
        "cognitive_loop_artifacts": [str(path) for path in cognitive_loop_artifacts],
        "cognitive_loop_interval": cognitive_loop_interval,
        "cognitive_loop_enable_requested": enable_cognitive_loop,
        "cognitive_loop_enabled": cognitive_loop_enabled,
        "cognitive_loop_enable_command": cognitive_loop_enable_command,
        "deep_reflection_preset": deep_reflection_preset,
        "deep_reflection_config_written": bool(deep_reflection_config_path) and not dry_run,
        "deep_reflection_config_path": str(deep_reflection_config_path) if deep_reflection_config_path else "",
        "deep_reflection_config": deep_reflection_config or {},
        "dry_run": dry_run,
    }


def _validate_source(source: Path) -> None:
    required = ("__init__.py", "plugin.yaml", "cli.py")
    missing = [name for name in required if not (source / name).is_file()]
    if missing:
        raise SystemExit(f"Memory-OS plugin source is missing: {', '.join(missing)}")


def _validate_agent_os_shell_source(source: Path) -> None:
    required = ("__init__.py", "plugin.yaml")
    missing = [name for name in required if not (source / name).is_file()]
    if missing:
        raise SystemExit(f"Memory-OS Agent OS shell source is missing: {', '.join(missing)}")
    text = (source / "plugin.yaml").read_text(encoding="utf-8")
    if f"name: {AGENT_OS_SHELL_PLUGIN_NAME}" not in text:
        raise SystemExit("Memory-OS Agent OS shell plugin.yaml has the wrong plugin name")


def _validate_system_module_source(source: Path) -> None:
    required = (
        "system/lifecycle.py",
        "system/scheduler.py",
        "modules/context/digest_consolidation.py",
        "modules/cognition/deep_reflection.py",
        "modules/cognition/inner_drive.py",
        "modules/expression/speak_gate.py",
        "modules/governance/feedback_bridge.py",
        "memory/memory_os/store.py",
    )
    missing = [name for name in required if not (source / name).is_file()]
    if missing:
        raise SystemExit(f"Memory-OS system module source is missing: {', '.join(missing)}")


def _validate_agent_source(source: Path) -> None:
    required = ("__init__.py", "memory_provider.py")
    missing = [name for name in required if not (source / name).is_file()]
    if missing:
        raise SystemExit(f"Memory-OS agent compatibility source is missing: {', '.join(missing)}")


def _copy_tree(source: Path, target: Path, *, dry_run: bool) -> list[Path]:
    files = [
        path for path in sorted(source.rglob("*"))
        if path.is_file() and not _is_excluded(path)
    ]
    copied: list[Path] = []
    for src in files:
        rel = src.relative_to(source)
        dst = target / rel
        copied.append(dst)
        if dry_run:
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    return copied


def _is_excluded(path: Path) -> bool:
    return "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}


def _guard_plugin_scan_tree_backups(hermes_home: Path) -> None:
    plugins_root = hermes_home / "plugins"
    if not plugins_root.exists():
        return
    for manifest in sorted(plugins_root.rglob("plugin.yaml")):
        rel = manifest.relative_to(plugins_root)
        top_level = rel.parts[0] if rel.parts else ""
        if top_level in {MEMORY_PROVIDER_PLUGIN_NAME, AGENT_OS_SHELL_PLUGIN_NAME}:
            continue
        if not _looks_like_memory_os_backup_path(rel):
            continue
        raise SystemExit(
            "plugin backup manifest inside plugin scan tree: "
            f"{rel}. Move backups to {hermes_home / 'plugin-backups'}."
        )


def _looks_like_memory_os_backup_path(rel: Path) -> bool:
    text = str(rel).lower()
    backup_markers = (".bak", ".backup", ".bad", "backup", "old")
    memory_os_names = (MEMORY_PROVIDER_PLUGIN_NAME.lower(), AGENT_OS_SHELL_PLUGIN_NAME.lower())
    return any(name in text for name in memory_os_names) and any(marker in text for marker in backup_markers)


def _enable_memory_provider(hermes_home: Path, enable_command: list[str]) -> None:
    subprocess.run(
        enable_command,
        check=True,
        env={**dict(os.environ), "HERMES_HOME": str(hermes_home)},
        stdout=subprocess.DEVNULL,
    )


def _enable_agent_os_shell(hermes_home: Path) -> None:
    config_path = hermes_home / "config.yaml"
    config = _read_yaml_config(config_path)
    plugins_config = config.get("plugins")
    if not isinstance(plugins_config, dict):
        plugins_config = {}
    enabled = plugins_config.get("enabled")
    if not isinstance(enabled, list):
        enabled = []
    normalized: list[str] = []
    for item in enabled:
        value = str(item)
        if value == MEMORY_PROVIDER_PLUGIN_NAME:
            continue
        if value not in normalized:
            normalized.append(value)
    if AGENT_OS_SHELL_PLUGIN_NAME not in normalized:
        normalized.append(AGENT_OS_SHELL_PLUGIN_NAME)
    plugins_config["enabled"] = normalized
    config["plugins"] = plugins_config
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _read_yaml_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        return {}
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        return {}
    return dict(loaded)


def _write_runtime_artifacts(hermes_home: Path, *, interval: str, dry_run: bool) -> list[Path]:
    runtime_root = hermes_home / "memory-os"
    wrapper = runtime_root / "bin" / "memory_os_heartbeat.sh"
    service = runtime_root / "systemd" / "hermes-memory-os-heartbeat.service"
    timer = runtime_root / "systemd" / "hermes-memory-os-heartbeat.timer"
    artifacts = [wrapper, service, timer]
    if dry_run:
        return artifacts
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    service.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"export HERMES_HOME={_shell_quote(str(hermes_home))}\n"
        "export PYTHONPATH=\"${HERMES_HOME}/memory-os/runtime/python:${HERMES_HOME}/plugins:${PYTHONPATH:-}\"\n"
        "exec python3 -m plugins.memory.memory_os heartbeat --max-events 100\n",
        encoding="utf-8",
    )
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)
    service.write_text(
        "[Unit]\n"
        "Description=Hermes Memory-OS heartbeat\n\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"ExecStart={wrapper}\n",
        encoding="utf-8",
    )
    timer.write_text(
        "[Unit]\n"
        "Description=Run Hermes Memory-OS heartbeat periodically\n\n"
        "[Timer]\n"
        f"OnBootSec={interval}\n"
        f"OnUnitActiveSec={interval}\n"
        "AccuracySec=30s\n\n"
        "[Install]\n"
        "WantedBy=timers.target\n",
        encoding="utf-8",
    )
    return artifacts


def _write_cognitive_loop_artifacts(hermes_home: Path, *, interval: str, dry_run: bool) -> list[Path]:
    runtime_root = hermes_home / "memory-os"
    wrapper = runtime_root / "bin" / "memory_os_cognitive_loop.sh"
    service = runtime_root / "systemd" / "hermes-memory-os-cognitive-loop.service"
    timer = runtime_root / "systemd" / "hermes-memory-os-cognitive-loop.timer"
    artifacts = [wrapper, service, timer]
    if dry_run:
        return artifacts
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    service.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"export HERMES_HOME={_shell_quote(str(hermes_home))}\n"
        "export PYTHONPATH=\"${HERMES_HOME}/memory-os/runtime/python:${HERMES_HOME}/plugins:${PYTHONPATH:-}\"\n"
        "exec python3 -m plugins.memory.memory_os cognitive-loop run-once --test-host --apply\n",
        encoding="utf-8",
    )
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)
    service.write_text(
        "[Unit]\n"
        "Description=Hermes Memory-OS test-host cognitive loop\n\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"ExecStart={wrapper}\n",
        encoding="utf-8",
    )
    timer.write_text(
        "[Unit]\n"
        "Description=Run Hermes Memory-OS test-host cognitive loop periodically\n\n"
        "[Timer]\n"
        f"OnBootSec={interval}\n"
        f"OnUnitActiveSec={interval}\n"
        "AccuracySec=30s\n"
        "Persistent=true\n\n"
        "[Install]\n"
        "WantedBy=timers.target\n",
        encoding="utf-8",
    )
    return artifacts


def _write_deep_reflection_config(
    hermes_home: Path,
    *,
    preset: str,
    dry_run: bool,
) -> tuple[Path, dict[str, object]]:
    if preset not in DEEP_REFLECTION_PRESETS:
        choices = ", ".join(sorted(DEEP_REFLECTION_PRESETS))
        raise SystemExit(f"Unsupported DeepReflection preset: {preset}. Choices: {choices}")
    config = {
        **DEEP_REFLECTION_CONFIG_DEFAULTS,
        **DEEP_REFLECTION_PRESETS[preset],
        "preset": preset,
    }
    config_path = hermes_home / "system-modules" / "deep_reflection" / "config.json"
    if not dry_run:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return config_path, config


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hermes-home", required=True, help="Target HERMES_HOME")
    parser.add_argument("--source", default=str(SOURCE_PLUGIN_DIR), help="Plugin source directory")
    parser.add_argument("--shell-source", default=str(SOURCE_AGENT_OS_SHELL_DIR), help="Agent OS shell plugin source directory")
    parser.add_argument("--no-install-shell", action="store_true", help="Do not copy the memory-os-agent-os shell plugin")
    parser.add_argument("--enable", action="store_true", help="Set memory.provider=memory_os after install")
    parser.add_argument("--enable-shell", action="store_true", help="Add memory-os-agent-os to plugins.enabled")
    parser.add_argument("--install-runtime", action="store_true", help="Write heartbeat wrapper and systemd timer artifacts")
    parser.add_argument("--install-system-modules", action="store_true", help="Install portable L2-L4 module runtime package")
    parser.add_argument("--enable-runtime", action="store_true", help="Install and enable the user systemd heartbeat timer")
    parser.add_argument("--runtime-interval", default="5min", help="Heartbeat timer interval, default: 5min")
    parser.add_argument("--install-cognitive-loop", action="store_true", help="Write test-host cognitive loop wrapper and systemd timer artifacts")
    parser.add_argument("--enable-cognitive-loop", action="store_true", help="Install and enable the user systemd cognitive-loop timer")
    parser.add_argument("--cognitive-loop-interval", default="6h", help="Cognitive-loop timer interval, default: 6h")
    parser.add_argument(
        "--deep-reflection-preset",
        choices=sorted(DEEP_REFLECTION_PRESETS),
        help=(
            "Write a DeepReflection config preset. Default is no config write; "
            "use production-safe for explicit off, observe for dry-run, "
            "auto-bounded for injection only, or test-host for no-send test observation."
        ),
    )
    parser.add_argument("--dry-run", action="store_true", help="Report actions without copying or enabling")
    args = parser.parse_args()

    report = install_plugin(
        hermes_home=Path(args.hermes_home),
        source=Path(args.source),
        shell_source=Path(args.shell_source),
        install_shell=not args.no_install_shell,
        enable=args.enable,
        enable_shell=args.enable_shell,
        install_runtime=args.install_runtime,
        install_system_modules=args.install_system_modules,
        enable_runtime=args.enable_runtime,
        runtime_interval=args.runtime_interval,
        install_cognitive_loop=args.install_cognitive_loop,
        enable_cognitive_loop=args.enable_cognitive_loop,
        cognitive_loop_interval=args.cognitive_loop_interval,
        deep_reflection_preset=args.deep_reflection_preset,
        dry_run=args.dry_run,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
