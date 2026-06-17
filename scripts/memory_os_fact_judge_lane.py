#!/usr/bin/env python3
"""Memory-OS fact judge lane helper (no_agent).

Reads the candidate queue, judges each inner_drive_candidate for
durable_fact, and writes verdicts to the sidecar JSONL file.
Does NOT mutate candidates. Outputs a JSON summary for the cron
scheduler to deliver.

Offline only — never on the hot path (INV-5).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Point to Memory-OS runtime root for plugin imports
_HERMES_HOME = os.environ.get("HERMES_HOME") or str(Path.home() / ".hermes")
REPO_ROOT = Path(_HERMES_HOME) / "memory-os" / "runtime" / "python"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.modules.governance.fact_judge import run_fact_judge_lane


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

    result = run_fact_judge_lane(
        store,
        now=now,
        execution_gate_envelope_id=envelope_id,
    )

    # Write execution helper report
    _write_execution_report(result)

    # Output JSON summary for cron delivery
    summary = {
        "tick": now.isoformat().replace("+00:00", "Z"),
        "candidates_read": result["candidates_read"],
        "judged_count": result["judged_count"],
        "durable_count": result["durable_count"],
        "moment_count": result["moment_count"],
        "skipped_count": result["skipped_count"],
        "error_count": result["error_count"],
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
            "lane_id": "fact_judge",
            "helper": "fact_judge",
            "returncode": 0,
            **result,
        },
    )


if __name__ == "__main__":
    raise SystemExit(main())
