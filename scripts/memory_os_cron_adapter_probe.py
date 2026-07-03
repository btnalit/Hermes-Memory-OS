#!/usr/bin/env python3
"""Read-only Hermes cron adapter probe for Memory-OS-owned jobs."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

# Location-agnostic path resolution: when HERMES_HOME is set the probe runs
# from the installed location (HERMES_HOME/scripts/); otherwise it runs from
# a repo checkout and derives the root from its own file path.
_HERMES_HOME = os.environ.get("HERMES_HOME", "")
if _HERMES_HOME:
    _base = Path(_HERMES_HOME)
else:
    _base = Path(__file__).resolve().parents[1]
if str(_base) not in sys.path:
    sys.path.insert(0, str(_base))

from plugins.memory.memory_os.cron_registry import memory_os_cron_specs, specs_from_snapshot
from plugins.memory.memory_os.hermes_cron_adapter import HermesCronAdapter
from scripts.memory_os_host_profile import resolve_host_runtime_profile


SCHEMA_VERSION = "memory-os.hermes_cron_adapter_probe.v0"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Probe Hermes cron jobs through the Memory-OS cron adapter.")
    parser.add_argument("--host", default="", help="SSH host alias for running this probe on a deployed target.")
    parser.add_argument("--remote-repo-root", default="")
    parser.add_argument("--python-bin", default="python3")
    parser.add_argument("--hermes-home", default="/root/.hermes")
    parser.add_argument("--hermes-bin", default="hermes")
    parser.add_argument("--output", choices=("json",), default="json")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        host_profile = resolve_host_runtime_profile(
            host=str(args.host),
            remote_repo_root=str(args.remote_repo_root),
            hermes_home=str(args.hermes_home),
            python_bin=str(args.python_bin),
        )
    except ValueError as exc:
        parser.error(str(exc))
    if args.host:
        return run_remote_probe(
            remote_probe_command(
                host=str(args.host),
                remote_repo_root=host_profile.remote_repo_root,
                hermes_home=host_profile.hermes_home,
                hermes_bin=str(args.hermes_bin),
                python_bin=host_profile.python_bin,
            )
        )
    report = probe_hermes_cron_adapter(
        hermes_home=Path(args.hermes_home).expanduser(),
        hermes_bin=str(args.hermes_bin),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.get("status") in {"ok", "warning"} else 1


def remote_probe_command(
    *,
    host: str,
    remote_repo_root: str,
    hermes_home: str,
    hermes_bin: str,
    python_bin: str,
) -> list[str]:
    script = Path(remote_repo_root) / "scripts" / "memory_os_cron_adapter_probe.py"
    remote_argv = [
        python_bin,
        str(script).replace("\\", "/"),
        "--hermes-home",
        hermes_home,
        "--hermes-bin",
        hermes_bin,
        "--output",
        "json",
    ]
    return ["ssh", host, shlex.join(remote_argv)]


def run_remote_probe(command: list[str]) -> int:
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, file=sys.stderr, end="")
    return completed.returncode


def probe_hermes_cron_adapter(*, hermes_home: Path, hermes_bin: str = "hermes") -> dict[str, Any]:
    specs = _load_installed_specs(hermes_home)
    adapter = HermesCronAdapter(hermes_home=hermes_home, hermes_bin=hermes_bin)
    classification = adapter.classify_jobs(specs)
    capabilities = adapter.probe_capabilities()
    findings = list(capabilities.findings)
    status = "ok" if classification.get("status") == "ok" else "warning"
    if capabilities.status != "ok":
        findings.append({"code": "hermes_cron_capability_probe_not_ok", "status": capabilities.status})
        status = "warning"
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "hermes_home": str(hermes_home),
        "spec_source": "installed_snapshot" if _snapshot_path(hermes_home).exists() else "package_registry",
        "capabilities": {
            "supports_script": capabilities.supports_script,
            "supports_no_agent": capabilities.supports_no_agent,
            "supports_edit": capabilities.supports_edit,
            "jobs_schema": capabilities.jobs_schema,
            "status": capabilities.status,
        },
        "classification": classification,
        "findings": findings,
    }


def _snapshot_path(hermes_home: Path) -> Path:
    return hermes_home / "memory-os" / "system" / "memory_os_cron_registry.json"


def _load_installed_specs(hermes_home: Path):
    path = _snapshot_path(hermes_home)
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            loaded = {}
        specs = specs_from_snapshot(loaded) if isinstance(loaded, dict) else ()
        if specs:
            return specs
    return memory_os_cron_specs()


if __name__ == "__main__":
    raise SystemExit(main())
