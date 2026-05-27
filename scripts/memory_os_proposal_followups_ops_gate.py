#!/usr/bin/env python3
"""Route approved proposal follow-ups through OpsGate report-only.

Hermes owns scheduling. This helper only invokes the Memory-OS structured
surface to move approved proposals to the report-only OpsGate follow-up state.
It never creates execution tickets and never executes external work.
"""

from __future__ import annotations

import json
import subprocess
import sys


def main() -> int:
    result = _run_json(
        [
            "hermes",
            "memory-os-agent-os",
            "review",
            "proposal-followups",
            "--ops-gate",
            "--all-pending",
            "--apply",
            "--owner",
            "owner",
            "--channel",
            "hermes_cron",
        ]
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if result.get("actual_execute") is True or result.get("execution_ticket_created") is True:
        return 2
    if result.get("status") not in {"ok", "warning"}:
        return 1
    return 0


def _run_json(command: list[str]) -> dict[str, object]:
    try:
        completed = subprocess.run(command, check=True, text=True, capture_output=True)
    except FileNotFoundError as exc:
        raise SystemExit("hermes command not found; cannot route proposal follow-ups") from exc
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(exc.stderr or exc.stdout or str(exc))
        raise SystemExit(exc.returncode) from exc
    try:
        parsed = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"proposal follow-up command did not return JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise SystemExit("proposal follow-up command returned non-object JSON")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
