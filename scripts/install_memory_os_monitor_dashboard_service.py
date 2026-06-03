#!/usr/bin/env python3
"""Install the Memory-OS monitor dashboard as a systemd service."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SERVICE_NAME = "hermes-memory-os-monitor-dashboard.service"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 3693
DEFAULT_PROFILE = "main"
DEFAULT_ENVIRONMENT = "prod"
DEFAULT_REFRESH_INTERVAL_SECONDS = 60

Runner = Callable[..., Any]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT, help="Hermes-Memory-OS checkout root.")
    parser.add_argument("--hermes-home", type=Path, default=Path.home() / ".hermes", help="Target HERMES_HOME.")
    parser.add_argument("--profile", default=DEFAULT_PROFILE, help=f"Dashboard profile. Default: {DEFAULT_PROFILE}.")
    parser.add_argument("--environment", default=DEFAULT_ENVIRONMENT, help=f"Dashboard environment label. Default: {DEFAULT_ENVIRONMENT}.")
    parser.add_argument(
        "--refresh-interval-seconds",
        type=int,
        default=DEFAULT_REFRESH_INTERVAL_SECONDS,
        help=f"Dashboard snapshot refresh interval. Default: {DEFAULT_REFRESH_INTERVAL_SECONDS}.",
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Bind host. Default: {DEFAULT_HOST}.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Bind port. Default: {DEFAULT_PORT}.")
    parser.add_argument("--python-bin", default=sys.executable or "python3", help="Python executable for systemd.")
    parser.add_argument(
        "--systemd-dir",
        type=Path,
        default=Path("/etc/systemd/system"),
        help="Systemd unit directory. Default: /etc/systemd/system.",
    )
    parser.add_argument("--service-name", default=DEFAULT_SERVICE_NAME, help=f"Default: {DEFAULT_SERVICE_NAME}.")
    parser.add_argument("--enable", action="store_true", help="Run systemctl daemon-reload and enable --now.")
    parser.add_argument("--dry-run", action="store_true", help="Print the report without writing or enabling.")
    return parser


def install_service(
    *,
    repo_root: Path,
    hermes_home: Path,
    profile: str,
    environment: str,
    refresh_interval_seconds: int,
    host: str,
    port: int,
    python_bin: str,
    systemd_dir: Path,
    service_name: str,
    enable: bool,
    dry_run: bool,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    repo_root = repo_root.expanduser().resolve()
    hermes_home = hermes_home.expanduser().resolve()
    systemd_dir = systemd_dir.expanduser().resolve()
    _validate_dashboard_inputs(repo_root)
    _validate_service_options(
        service_name=service_name,
        host=host,
        port=port,
        refresh_interval_seconds=refresh_interval_seconds,
    )
    python_bin = _resolve_python_bin(python_bin)

    unit_text = render_service_unit(
        repo_root=repo_root,
        hermes_home=hermes_home,
        profile=profile,
        environment=environment,
        refresh_interval_seconds=refresh_interval_seconds,
        host=host,
        port=port,
        python_bin=python_bin,
    )
    service_path = systemd_dir / service_name
    commands: list[list[str]] = []
    enabled = False
    if not dry_run:
        systemd_dir.mkdir(parents=True, exist_ok=True)
        service_path.write_text(unit_text, encoding="utf-8")
    if enable:
        commands = [
            ["systemctl", "daemon-reload"],
            ["systemctl", "enable", service_name],
            ["systemctl", "restart", service_name],
        ]
        if not dry_run:
            for command in commands:
                runner(command, check=True)
            enabled = True

    return {
        "schema_version": "memory-os.monitor_dashboard_service_install.v0",
        "service_name": service_name,
        "service_path": str(service_path),
        "repo_root": str(repo_root),
        "hermes_home": str(hermes_home),
        "profile": profile,
        "environment": environment,
        "refresh_interval_seconds": refresh_interval_seconds,
        "host": host,
        "port": port,
        "dashboard_dir": str(repo_root / "monitor_dashboard"),
        "snapshot_output": str(repo_root / "monitor_dashboard" / "snapshot.generated.js"),
        "enable_requested": enable,
        "enabled": enabled,
        "dry_run": dry_run,
        "commands": commands,
    }


def render_service_unit(
    *,
    repo_root: Path,
    hermes_home: Path,
    profile: str,
    environment: str,
    refresh_interval_seconds: int,
    host: str,
    port: int,
    python_bin: str,
) -> str:
    snapshot_script = repo_root / "scripts" / "memory_os_monitor_dashboard_snapshot.py"
    serve_script = repo_root / "scripts" / "serve_memory_os_monitor_dashboard.py"
    dashboard_dir = repo_root / "monitor_dashboard"
    snapshot_output = dashboard_dir / "snapshot.generated.js"
    return (
        "[Unit]\n"
        "Description=Hermes Memory-OS monitor dashboard\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n\n"
        "[Service]\n"
        "Type=simple\n"
        f"WorkingDirectory={_unit_arg(repo_root)}\n"
        f"Environment=HERMES_HOME={_unit_arg(hermes_home)}\n"
        f"Environment=HERMES_PROFILE={_unit_arg(profile)}\n"
        f"Environment=HERMES_ENV={_unit_arg(environment)}\n"
        f"Environment=MOS_DASHBOARD_REFRESH_INTERVAL_SECONDS={int(refresh_interval_seconds)}\n"
        "Environment=PYTHONUNBUFFERED=1\n"
        f"ExecStartPre={_unit_arg(python_bin)} {_unit_arg(snapshot_script)} --hermes-home {_unit_arg(hermes_home)} --profile {_unit_arg(profile)} --output {_unit_arg(snapshot_output)}\n"
        f"ExecStart={_unit_arg(python_bin)} {_unit_arg(serve_script)} --host {_unit_arg(host)} --port {int(port)} --directory {_unit_arg(dashboard_dir)} "
        f"--snapshot-hermes-home {_unit_arg(hermes_home)} --snapshot-profile {_unit_arg(profile)} --snapshot-output {_unit_arg(snapshot_output)} "
        f"--snapshot-interval-seconds {int(refresh_interval_seconds)}\n"
        "Restart=on-failure\n"
        "RestartSec=5s\n\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )


def _validate_dashboard_inputs(repo_root: Path) -> None:
    required = (
        repo_root / "monitor_dashboard" / "index.html",
        repo_root / "monitor_dashboard" / "assets" / "mos.css",
        repo_root / "monitor_dashboard" / "assets" / "dashboard.js",
        repo_root / "monitor_dashboard" / "assets" / "sample-data.js",
        repo_root / "scripts" / "memory_os_monitor_dashboard_snapshot.py",
        repo_root / "scripts" / "serve_memory_os_monitor_dashboard.py",
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise SystemExit("Dashboard service inputs missing: " + ", ".join(missing))


def _validate_service_options(*, service_name: str, host: str, port: int, refresh_interval_seconds: int) -> None:
    if not service_name.endswith(".service") or "/" in service_name or "\\" in service_name:
        raise SystemExit(f"Invalid systemd service name: {service_name}")
    if not str(host or "").strip():
        raise SystemExit("Dashboard service host must not be empty")
    if port < 1 or port > 65535:
        raise SystemExit(f"Dashboard service port out of range: {port}")
    if refresh_interval_seconds < 0:
        raise SystemExit(f"Dashboard refresh interval must be >= 0: {refresh_interval_seconds}")


def _resolve_python_bin(python_bin: str) -> str:
    if os.sep not in python_bin and (os.altsep is None or os.altsep not in python_bin):
        return shutil.which(python_bin) or python_bin
    return python_bin


def _unit_arg(value: str | Path) -> str:
    text = str(value)
    if not text:
        return '""'
    if all(ch not in text for ch in ' \t\n"\\'):
        return text
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = install_service(
        repo_root=args.repo_root,
        hermes_home=args.hermes_home,
        profile=args.profile,
        environment=args.environment,
        refresh_interval_seconds=args.refresh_interval_seconds,
        host=args.host,
        port=args.port,
        python_bin=args.python_bin,
        systemd_dir=args.systemd_dir,
        service_name=args.service_name,
        enable=args.enable,
        dry_run=args.dry_run,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
