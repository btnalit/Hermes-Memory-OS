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

def _preparse_cli_arg(argv: list[str], flag: str) -> str:
    """Extract a --flag value from raw argv before argparse runs.

    Needed at module level because sys.path setup depends on --hermes-home.
    """
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

# Point to Memory-OS runtime root for plugin imports
# Script lives in ~/.hermes/scripts/; runtime is at ~/.hermes/memory-os/runtime/python/
REPO_ROOT = Path(_HERMES_HOME) / "memory-os" / "runtime" / "python"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.modules.governance.candidate_aggregation import run_candidate_aggregation_lane


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
    envelope_id = (
        _preparse_cli_arg(sys.argv, "--envelope-id")
        or os.environ.get("MEMORY_OS_EXECUTION_GATE_ENVELOPE_ID", "")
    )

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
        try:
            from plugins.memory.memory_os.jsonl_io import build_error_record, append_jsonl_locked  # fmt: skip
            append_jsonl_locked(
                store.roots.memory_os_root / "system" / "error_records.jsonl",
                build_error_record(
                    component="candidate_aggregation_lane",
                    operation="write_candidate_aggregation_status",
                    error_code="candidate_aggregation_status_write_failed",
                    severity="warning",
                    recoverable=True,
                    details={"error_type": type(exc).__name__, "message": str(exc)[:200]},
                ),
                durable=True,
            )
        except Exception:
            pass

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
            # P1-1: hard-zero/False only — never pass through the truthful
            # compat bool `actual_crystallized_approval` here. A bounded,
            # reversible provisional crystallized write is legitimate and
            # bare-True in a boundary dict is indistinguishable from a real
            # violation to any_boundary_true()/the boundary runtime probe.
            # This lane never grants PERMANENT crystallization on its own
            # (that stays owner-gated), so actual_permanent_crystallized_
            # approval is always False. The truthful provisional evidence
            # (crystallized_write, provisional_crystallized_write_count,
            # actual_crystallized_approval) is still available, unsanitized,
            # in result_summary below.
            "actual_permanent_crystallized_approval": False,
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
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
