#!/usr/bin/env python3
"""Run the V2-A exposure rollup as a local no-agent helper."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _preparse_cli_arg(argv: list[str], flag: str) -> str:
    for index, arg in enumerate(argv):
        if arg == flag and index + 1 < len(argv) and not argv[index + 1].startswith("--"):
            return argv[index + 1]
        if arg.startswith(f"{flag}="):
            return arg.split("=", 1)[1]
    return ""


_HERMES_HOME = _preparse_cli_arg(sys.argv, "--hermes-home") or os.environ.get("HERMES_HOME", "") or str(Path.home() / ".hermes")
_self = Path(__file__).absolute()
_repo_root = _self.parents[1]
if (_repo_root / "plugins" / "memory" / "memory_os").exists():
    sys.path.insert(0, str(_repo_root))
else:
    runtime_root = Path(_HERMES_HOME) / "memory-os" / "runtime" / "python"
    if runtime_root.exists():
        sys.path.insert(0, str(runtime_root))

from plugins.memory.memory_os.exposure_rollup import run_exposure_rollup_cycle
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hermes-home", default=_HERMES_HOME)
    parser.add_argument("--profile", default=os.environ.get("HERMES_PROFILE", "default"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    roots = MemoryOSRoots.from_hermes_home(args.hermes_home, profile=args.profile)
    store = MemoryOSStore(roots)
    store.initialize()
    result = run_exposure_rollup_cycle(
        store,
        execution_gate_envelope_id=os.environ.get("MEMORY_OS_EXECUTION_GATE_ENVELOPE_ID", ""),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))

    report_path = os.environ.get("MEMORY_OS_EXECUTION_REPORT_PATH", "")
    if report_path:
        report = {
            "schema_version": "memory-os.helper_execution_report.v0",
            "boundary": {
                "actual_send": False,
                "actual_execute": False,
                "actual_identity_write": False,
                "actual_unapproved_crystallized_approval": False,
            },
            "result_summary": {
                key: result.get(key)
                for key in (
                    "status", "skipped", "records_processed", "records_classified",
                    "eligible", "selected", "dropped_by_budget", "dropped_by_rank",
                    "conservation_passes",
                )
            },
        }
        target = Path(report_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if result.get("status") == "ok" and (result.get("skipped") or result.get("conservation_passes")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
