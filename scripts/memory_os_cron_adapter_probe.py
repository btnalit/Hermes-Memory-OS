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

# Location-agnostic path resolution.
#
# Priority order (highest first):
#   1. Repo self-root (the repository containing this script).
#   2. CLI --hermes-home runtime (preparsed before argparse).
#   3. Env HERMES_HOME runtime.
#   4. Self-location inference (when script is at <home>/scripts/…).
#
# Paths are collected into a list then applied in reverse order with
# insert(0) so that the first candidate ends up at sys.path[0].
# This ensures a repo checkout is never shadowed by an installed runtime
# even when HERMES_HOME is set globally.
_self = Path(__file__).absolute()
_repo_root = _self.parents[1]
_is_repo_checkout = (_repo_root / "plugins" / "memory" / "memory_os").exists()
_path_candidates: list[Path] = []

# 1) Repo self-root — must always be the highest-priority source
if _is_repo_checkout:
    _path_candidates.append(_repo_root)


def _preparse_hermes_home(argv: list[str]) -> str:
    """Extract --hermes-home from raw argv before argparse runs.

    This lets module-level imports use the CLI-specified home even when
    HERMES_HOME is not exported in the environment (systemd, cron, CI).
    """
    for i, arg in enumerate(argv):
        if arg == "--hermes-home" and i + 1 < len(argv):
            val = argv[i + 1]
            if val.startswith("--"):
                return ""
            return val
        if arg.startswith("--hermes-home="):
            return arg.split("=", 1)[1]
    return ""


# 2-3) CLI and env HERMES_HOME runtime paths.
#      ONLY injected when NOT running from a repo checkout — when a repo
#      checkout is active, importing from the repo is always correct and
#      the installed runtime must never shadow it.  Without this guard,
#      a globally-set HERMES_HOME (e.g. /root/.hermes in a Gateway agent
#      process) pollutes the repo test environment with installed-runtime
#      modules, causing import mismatches and spurious test failures.
if not _is_repo_checkout:
    _cli_home = _preparse_hermes_home(sys.argv[1:])
    _env_home = os.environ.get("HERMES_HOME", "")

    for _home_str in (_cli_home, _env_home):
        if not _home_str:
            continue
        _home = Path(_home_str)
        _runtime = _home / "memory-os" / "runtime" / "python"
        if _runtime.exists():
            _path_candidates.append(_runtime)
        _path_candidates.append(_home)

    # 4) Self-location inference: when script is copied to <home>/scripts/…
    #    and neither --hermes-home nor HERMES_HOME env is set.
    _inferred = _self.parents[1]
    _runtime_inferred = _inferred / "memory-os" / "runtime" / "python"
    if _runtime_inferred.exists():
        if _runtime_inferred not in _path_candidates:
            _path_candidates.append(_runtime_inferred)
        if _inferred not in _path_candidates:
            _path_candidates.append(_inferred)

# Apply: reversed + insert(0) so _path_candidates[0] ends up at sys.path[0].
# Reposition existing entries as well: inherited PYTHONPATH may already contain
# the runtime below HERMES_HOME, where a legacy ``plugins`` package shadows it.
for _base in reversed(_path_candidates):
    _base_str = str(_base)
    while _base_str in sys.path:
        sys.path.remove(_base_str)
    sys.path.insert(0, _base_str)

from plugins.memory.memory_os.cron_registry import specs_from_snapshot
from plugins.seam.hermes_memory_os.cron_adapter import HermesCronAdapter
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
    registry_error = ""
    try:
        specs = _load_installed_specs(hermes_home)
    except (FileNotFoundError, ValueError) as exc:
        specs = ()
        registry_error = str(exc)
    adapter = HermesCronAdapter(hermes_home=hermes_home, hermes_bin=hermes_bin)
    classification = adapter.classify_jobs(specs)
    capabilities = adapter.probe_capabilities()
    findings = list(capabilities.findings)
    status = "ok" if classification.get("status") == "ok" else "warning"
    if registry_error:
        findings.append({"code": registry_error})
        status = "error"
    if int(classification.get("enabled_retired_legacy_count") or 0) > 0:
        findings.append(
            {
                "code": "retired_legacy_cron_enabled",
                "count": int(classification.get("enabled_retired_legacy_count") or 0),
            }
        )
        status = "warning"
    if capabilities.status != "ok":
        findings.append({"code": "hermes_cron_capability_probe_not_ok", "status": capabilities.status})
        status = "warning"
    return {
        "schema_version": SCHEMA_VERSION,
        "adapter_owner": "hermes_memory_os_seam",
        "status": status,
        "hermes_home": str(hermes_home),
        "spec_source": "installed_snapshot" if not registry_error else registry_error,
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
    if not path.exists():
        raise FileNotFoundError("installed_cron_registry_missing")
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("installed_cron_registry_invalid") from exc
    specs = specs_from_snapshot(loaded) if isinstance(loaded, dict) else ()
    if not specs:
        raise ValueError("installed_cron_registry_empty_or_invalid")
    return specs


if __name__ == "__main__":
    raise SystemExit(main())
