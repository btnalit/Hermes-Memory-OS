#!/usr/bin/env python3
"""Memory-OS clearance cycle helper (no_agent).

Calls run_clearance_cycle to invalidate affected receipts, enqueue
never-judged provisionals, and judge each candidate via LLM contradiction
detection against the permanent corpus.

Invocation:
  - Cron (via execution_gate_runner): env HERMES_HOME is set by the runner.
  - Direct/manual:  python scripts/memory_os_clearance_cycle_helper.py
      --hermes-home /path/to/copy  --profile default
    CLI args take priority over env vars.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _preparse_cli_arg(argv: list[str], flag: str) -> str:
    """Extract a --flag value from raw argv before argparse runs."""
    for i, arg in enumerate(argv):
        if arg == flag and i + 1 < len(argv):
            val = argv[i + 1]
            if val.startswith("--"):
                return ""
            return val
        if arg.startswith(f"{flag}="):
            return arg.split("=", 1)[1]
    return ""


# Resolve HERMES_HOME at module level — CLI > env > default.
_CLI_HOME = _preparse_cli_arg(sys.argv, "--hermes-home")
_ENV_HOME = os.environ.get("HERMES_HOME", "")
_HERMES_HOME = _CLI_HOME or _ENV_HOME or str(Path.home() / ".hermes")

# Location-agnostic import resolution: repo checkout > runtime layout.
_self = Path(__file__).absolute()
_repo_root = _self.parents[1]  # scripts/ → repo root
if (_repo_root / "plugins" / "memory" / "memory_os").exists():
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
else:
    _runtime_root = Path(_HERMES_HOME) / "memory-os" / "runtime" / "python"
    if _runtime_root.exists() and str(_runtime_root) not in sys.path:
        sys.path.insert(0, str(_runtime_root))

from plugins.memory.memory_os.clearance_cycle import run_clearance_cycle
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore


def main() -> int:
    hermes_home = (
        _preparse_cli_arg(sys.argv, "--hermes-home")
        or os.environ.get("HERMES_HOME", "")
        or str(Path.home() / ".hermes")
    )
    profile = (
        _preparse_cli_arg(sys.argv, "--profile")
        or os.environ.get("HERMES_PROFILE", "default")
    )

    roots = MemoryOSRoots.from_hermes_home(hermes_home, profile=profile)
    store = MemoryOSStore(roots)
    store.initialize()

    report = run_clearance_cycle(store, v2e_enabled=True)

    # Print structured helper report for execution gate runner consumption
    helper_report = {
        "schema_version": "memory-os.helper_execution_report.v0",
        "status": report.get("status", "error"),
        "result_summary": {
            "judged": report.get("judged", 0),
            "invalidated": report.get("invalidated", 0),
            "queue_depth": report.get("queue_depth", 0),
            "budget_used": report.get("budget_used", 0),
            "verdict_distribution": report.get("verdict_distribution", {}),
            "initial_never_judged_queued": report.get("initial_never_judged_queued", 0),
        },
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
        },
    }
    print(json.dumps(helper_report, ensure_ascii=False, indent=2))
    return 0 if report.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
