#!/usr/bin/env python3
"""Memory-OS event_stats cache refresh helper (no_agent).

Rebuilds event_stats.json from canonical events so status/monitor reads
stay O(1).  Zero side effects — no heartbeat, no candidates, no working
memory decay, no audit writes.

Intended as a lightweight cron subprocess behind ExecutionGate
(via memory_os_cron_event_stats_refresh_gate.py).

Invocation:
  - Cron (via execution_gate_runner): env HERMES_HOME is set by the runner.
  - Direct/manual:  python scripts/memory_os_event_stats_refresh.py
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
                return ""  # next token is another flag, not a value
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
    # Fallback: installed runtime layout (<home>/memory-os/runtime/python/)
    _runtime_root = Path(_HERMES_HOME) / "memory-os" / "runtime" / "python"
    if _runtime_root.exists() and str(_runtime_root) not in sys.path:
        sys.path.insert(0, str(_runtime_root))

from plugins.memory.memory_os.event_stats import build_event_stats, write_event_stats
from plugins.memory.memory_os.lane_last_run import record_lane_last_run
from plugins.memory.memory_os.roots import MemoryOSRoots, resolve_profile_name
from plugins.memory.memory_os.store import MemoryOSStore


def main() -> int:
    hermes_home = (
        _preparse_cli_arg(sys.argv, "--hermes-home")
        or os.environ.get("HERMES_HOME", "")
        or str(Path.home() / ".hermes")
    )
    profile = resolve_profile_name(hermes_home, _preparse_cli_arg(sys.argv, "--profile"))

    roots = MemoryOSRoots.from_hermes_home(hermes_home, profile=profile)
    store = MemoryOSStore(roots)
    store.initialize()

    now = datetime.now(timezone.utc)
    events = store.read_events()
    event_dicts = [e.to_dict() for e in events]
    stats = build_event_stats(event_dicts)
    stats.events_root = str(roots.events_root)
    write_event_stats(roots, stats)

    summary = {
        "tick": now.isoformat().replace("+00:00", "Z"),
        "status": "ok",
        "total_event_count": stats.total_event_count,
        "recent_event_summaries_count": len(stats.recent_event_summaries),
        "has_continuity_selector": bool(stats.continuity_selector),
        "updated_at": stats.updated_at,
    }
    record_lane_last_run(
        hermes_home,
        "event_stats_refresh",
        status="ok",
        reason="stats_refreshed" if event_dicts else "no_events",
        counters={
            "total_event_count": int(stats.total_event_count or 0),
            "recent_event_summaries_count": len(stats.recent_event_summaries),
        },
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    # Helper report for ExecutionGate postcheck (INV-5: no LLM / no network).
    report_path = os.environ.get("MEMORY_OS_EXECUTION_REPORT_PATH", "")
    if report_path:
        Path(report_path).parent.mkdir(parents=True, exist_ok=True)
        Path(report_path).write_text(
            json.dumps(
                {
                    "schema_version": "memory-os.helper_execution_report.v0",
                    "boundary": {
                        "actual_send": False,
                        "actual_execute": False,
                        "actual_identity_write": False,
                        "actual_unapproved_crystallized_approval": False,
                    },
                    "result_summary": {
                        "total_event_count": stats.total_event_count,
                        "recent_event_summaries_count": len(stats.recent_event_summaries),
                        "updated_at": stats.updated_at,
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
