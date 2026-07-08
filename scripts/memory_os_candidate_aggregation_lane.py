#!/usr/bin/env python3
"""Memory-OS candidate aggregation lane helper (no_agent).

Reads the candidate queue, runs triage (cluster+promote, age-out demote,
tag fleeting), appends triage actions, optionally compacts. Outputs a JSON
summary for the cron scheduler to deliver.

TASK ANCHOR: queue-state only, never crystallizes, never auto-approves.
All writes are append-only via candidate_triage.jsonl.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Point to Memory-OS runtime root for plugin imports
# Script lives in ~/.hermes/scripts/; runtime is at ~/.hermes/memory-os/runtime/python/
_HERMES_HOME = os.environ.get("HERMES_HOME") or str(Path.home() / ".hermes")
REPO_ROOT = Path(_HERMES_HOME) / "memory-os" / "runtime" / "python"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.modules.governance.candidate_aggregation import run_candidate_aggregation_lane


def main() -> int:
    hermes_home = os.environ.get("HERMES_HOME", "")
    profile = os.environ.get("HERMES_PROFILE", "default")
    envelope_id = os.environ.get("MEMORY_OS_EXECUTION_GATE_ENVELOPE_ID", "")

    if not hermes_home:
        hermes_home = str(Path.home() / ".hermes")

    roots = MemoryOSRoots.from_hermes_home(hermes_home, profile=profile)
    store = MemoryOSStore(roots)
    store.initialize()

    now = datetime.now(timezone.utc)

    result = run_candidate_aggregation_lane(
        store,
        now=now,
        execution_gate_envelope_id=envelope_id,
    )

    # Write execution helper report
    _write_execution_report(result)

    # Persist lane outcome for the owner review digest (Fix 3).
    try:
        from plugins.memory.memory_os.crystallized import write_candidate_aggregation_status
        write_candidate_aggregation_status(
            store,
            summary=result,
            execution_gate_envelope_id=envelope_id,
            now=now,
        )
    except Exception as exc:  # pragma: no cover - best-effort persistence
        sys.stderr.write(f"[candidate_aggregation] status persistence skipped: {exc}\n")

    # Output JSON summary for cron delivery
    summary = {
        "tick": now.isoformat().replace("+00:00", "Z"),
        "candidates_read": result["candidates_read"],
        "pending": result["pending"],
        "already_triaged": result["already_triaged"],
        "promoted_count": result["promoted_count"],
        "promoted_clusters": result["promoted_clusters"],
        "demoted_count": result["demoted_count"],
        "fleeting_count": result["fleeting_count"],
        "compacted_count": result["compacted_count"],
        "actual_crystallized_approval": result["actual_crystallized_approval"],
        "status": "ok" if not result.get("error") else "error",
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _write_execution_report(result: dict[str, Any]) -> None:
    try:
        from memory_os_execution_report import write_helper_execution_report
    except ModuleNotFoundError:
        try:
            from scripts.memory_os_execution_report import write_helper_execution_report
        except ModuleNotFoundError:
            return
    write_helper_execution_report(
        boundary={
            "actual_crystallized_approval": result.get("actual_crystallized_approval", False),
            "actual_send": result.get("actual_send", False),
            "actual_execute": result.get("actual_execute", False),
            "actual_identity_write": result.get("actual_identity_write", False),
        },
        result_summary={
            "lane_id": "candidate_aggregation",
            "helper": "candidate_aggregation",
            "returncode": 0,
            **result,
        },
    )


if __name__ == "__main__":
    raise SystemExit(main())
