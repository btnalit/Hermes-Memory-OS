#!/usr/bin/env python3
"""Memory-OS clearance receipt snapshot rebuild helper (no_agent).

Rebuilds the derived clearance receipt snapshot
(``system/clearance_receipt_snapshot.json``) from the authoritative
append-only ``clearance_receipts.jsonl`` ledger, then verifies freshness.

Fail-visible (NOT fail-open, unlike ``memory_os_state_overlay_refresh.py``):
this script exits 1 on any rebuild error, or if ``clearance_snapshot_freshness``
still reports non-fresh immediately after the rebuild. A clearance snapshot
that silently stays stale is exactly the P2 defect this script exists to
close — so unlike the overlay refresh helper, errors here are surfaced via
exit code rather than swallowed.

Invocation:
  - Cron (via execution_gate_runner): env HERMES_HOME is set by the runner.
  - Direct/manual: python scripts/memory_os_clearance_snapshot_rebuild.py
      --hermes-home /path/to/copy --profile default
    CLI args take priority over env vars.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Location-agnostic import resolution (same pattern as
# memory_os_state_overlay_refresh.py / memory_os_clearance_cycle_helper.py).
_self = Path(__file__).absolute()
_repo_root = _self.parents[1]  # scripts/ → repo root


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

if (_repo_root / "plugins" / "memory" / "memory_os").exists():
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
else:
    _runtime_root = Path(_HERMES_HOME) / "memory-os" / "runtime" / "python"
    if _runtime_root.exists() and str(_runtime_root) not in sys.path:
        sys.path.insert(0, str(_runtime_root))

from plugins.memory.memory_os.clearance_receipts import (
    clearance_snapshot_freshness,
    rebuild_clearance_receipt_snapshot,
)
from plugins.memory.memory_os.roots import MemoryOSRoots, resolve_profile_name
from plugins.memory.memory_os.store import MemoryOSStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rebuild the Memory-OS clearance receipt snapshot (fail-visible).",
    )
    parser.add_argument(
        "--hermes-home",
        default=_HERMES_HOME,
        help="Path to HERMES_HOME (default: $HERMES_HOME or ~/.hermes)",
    )
    parser.add_argument(
        "--profile",
        default="",
        help="Memory-OS profile name",
    )
    parser.add_argument(
        "--output",
        choices=("json",),
        default="json",
    )
    args = parser.parse_args(argv)
    profile = resolve_profile_name(args.hermes_home, args.profile)

    t0 = time.monotonic()
    run_status = "ok"
    error_msg = ""
    freshness: dict = {}

    try:
        roots = MemoryOSRoots.from_hermes_home(args.hermes_home, profile=profile)
        store = MemoryOSStore(roots)
        store.initialize()

        rebuild_clearance_receipt_snapshot(roots)
        freshness = clearance_snapshot_freshness(roots, for_activation=False)
        if str(freshness.get("status") or "") != "fresh":
            run_status = "error"
            error_msg = f"snapshot_not_fresh_after_rebuild:{freshness.get('reason', '')}"
    except Exception as exc:
        run_status = "error"
        error_msg = f"{type(exc).__name__}: {exc}"

    duration_ms = int((time.monotonic() - t0) * 1000)

    if args.output == "json":
        print(json.dumps({
            "status": run_status,
            "error": error_msg,
            "freshness": freshness,
            "duration_ms": duration_ms,
            "profile": profile,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }, ensure_ascii=False))

    # Fail-visible: exit 1 on any error or non-fresh outcome — a clearance
    # snapshot that silently stays stale is the defect this script exists
    # to close, so (unlike memory_os_state_overlay_refresh.py) this never
    # unconditionally returns 0.
    return 0 if run_status == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
