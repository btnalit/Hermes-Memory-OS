#!/usr/bin/env python3
"""Read-only Hermes cron adapter probe for Memory-OS-owned jobs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from plugins.memory.memory_os.cron_registry import memory_os_cron_specs, specs_from_snapshot
from plugins.memory.memory_os.hermes_cron_adapter import HermesCronAdapter


SCHEMA_VERSION = "memory-os.hermes_cron_adapter_probe.v0"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Probe Hermes cron jobs through the Memory-OS cron adapter.")
    parser.add_argument("--hermes-home", default="/root/.hermes")
    parser.add_argument("--hermes-bin", default="hermes")
    parser.add_argument("--output", choices=("json",), default="json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = probe_hermes_cron_adapter(
        hermes_home=Path(args.hermes_home).expanduser(),
        hermes_bin=str(args.hermes_bin),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.get("status") in {"ok", "warning"} else 1


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
