#!/usr/bin/env python3
"""Memory-OS session fact-extraction lane helper (no_agent).

Reads session transcripts, extracts durable facts from messages too long to
have survived the live 140-char-per-side turn summary, and writes them as
unapproved candidates on the existing governed candidate-queue path. Never
mutates or deletes session files. Outputs a JSON summary for the cron
scheduler to deliver.

Offline only -- never on the hot path (INV-5).

Invocation:
  - Cron (via execution_gate_runner): env HERMES_HOME is set by the runner.
  - Direct/manual:  python scripts/memory_os_session_fact_extraction_lane.py
      --hermes-home /path/to/copy  --profile default
      --envelope-id xgate_...
    CLI args take priority over env vars, so a copied store can be tested
    without risk of writing to the ambient HERMES_HOME.
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

REPO_ROOT = Path(_HERMES_HOME) / "memory-os" / "runtime" / "python"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.modules.cognition.session_fact_extraction import run_session_fact_extraction_lane


def _resolve_config() -> tuple[str, str, str]:
    """Resolve (hermes_home, profile, envelope_id) with CLI > env priority."""
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
    return hermes_home, profile, envelope_id


def main() -> int:
    hermes_home, profile, envelope_id = _resolve_config()

    roots = MemoryOSRoots.from_hermes_home(hermes_home, profile=profile)
    store = MemoryOSStore(roots)
    store.initialize()

    now = datetime.now(timezone.utc)

    result = run_session_fact_extraction_lane(
        store,
        now=now,
        execution_gate_envelope_id=envelope_id,
    )

    # Write execution helper report
    _write_execution_report(result)

    # Output JSON summary for cron delivery
    summary = {
        "tick": now.isoformat().replace("+00:00", "Z"),
        "sessions_scanned": result["sessions_scanned"],
        "sessions_eligible": result["sessions_eligible"],
        "sessions_processed": result["sessions_processed"],
        "sessions_skipped_already_processed": result["sessions_skipped_already_processed"],
        "messages_considered": result["messages_considered"],
        "messages_eligible_over_threshold": result["messages_eligible_over_threshold"],
        "facts_extracted": result["facts_extracted"],
        "candidates_written": result["candidates_written"],
        "llm_calls": result["llm_calls"],
        "llm_failures_by_reason": result["llm_failures_by_reason"],
        "fallback_used_count": result["fallback_used_count"],
        "skipped": result["skipped"],
        "skipped_reason": result["skipped_reason"],
        "error_record_count": len(result.get("error_records") or []),
        "status": result.get("status", "ok"),
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
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_crystallized_approval": False,
        },
        result_summary={
            "lane_id": "session_fact_extraction",
            "helper": "session_fact_extraction",
            "returncode": 0,
            **result,
        },
    )


if __name__ == "__main__":
    raise SystemExit(main())
