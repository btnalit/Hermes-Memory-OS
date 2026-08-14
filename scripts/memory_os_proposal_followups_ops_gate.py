#!/usr/bin/env python3
"""Auto-route safe proposal follow-ups through OpsGate report-only.

Hermes owns scheduling. This helper only invokes the Memory-OS structured
surface to move safe proposal_queue_only items to the report-only OpsGate
follow-up state. It never creates execution tickets and never executes external
work.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

try:
    from memory_os_execution_report import write_helper_execution_report
except ModuleNotFoundError:
    from scripts.memory_os_execution_report import write_helper_execution_report

_HERMES_HOME_DEFAULT = str(Path.home() / ".hermes")
_repo_root = Path(__file__).absolute().parents[1]
if (_repo_root / "plugins" / "memory" / "memory_os").exists():
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
else:
    _runtime_root = Path(os.environ.get("HERMES_HOME", "") or _HERMES_HOME_DEFAULT) / "memory-os" / "runtime" / "python"
    if _runtime_root.exists() and str(_runtime_root) not in sys.path:
        sys.path.insert(0, str(_runtime_root))

try:
    from plugins.memory.memory_os.lane_last_run import record_lane_last_run
except ModuleNotFoundError:  # pragma: no cover - plugin tree unavailable
    def record_lane_last_run(*_args, **_kwargs) -> bool:  # type: ignore[misc]
        sys.stderr.write("lane_last_run unavailable: plugin tree not importable\n")
        return False

_LANE_ID = "proposal_followups_opsgate"


def _record_last_run(status: str, reason: str, counters: dict[str, int] | None = None) -> None:
    hermes_home = os.environ.get("HERMES_HOME", "") or _HERMES_HOME_DEFAULT
    record_lane_last_run(hermes_home, _LANE_ID, status=status, reason=reason, counters=counters)


def main() -> int:
    try:
        result = _run_json(
            [
                "hermes",
                "memory-os-agent-os",
                "review",
                "proposal-followups",
                "--auto-route",
                "--apply",
                "--limit",
                "1",
                "--owner",
                "memory_os_auto",
                "--channel",
                "hermes_cron",
            ]
        )
    except SystemExit:
        _record_last_run("error", "hermes_cli_failed")
        raise
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    boundary = {
        "actual_execute": result.get("actual_execute") is True or result.get("execution_ticket_created") is True,
        "actual_send": result.get("actual_send") is True,
        "actual_identity_write": result.get("actual_identity_write") is True,
        "actual_unapproved_crystallized_approval": result.get("actual_unapproved_crystallized_approval") is True,
    }
    write_helper_execution_report(
        boundary=boundary,
        result_summary={
            "status": result.get("status"),
            "routed_count": result.get("auto_followup_routed_count"),
            "eligible_count": result.get("eligible_count"),
            "lane_mode": result.get("lane_mode"),
            "effective_limit": result.get("effective_limit"),
            "wilson_95_lower_bound": result.get("wilson_95_lower_bound"),
        },
    )
    # "0 routed" used to be indistinguishable between an empty queue, a
    # boundary rejection, and a failed surface — persist the closed outcome.
    routed = int(result.get("auto_followup_routed_count") or 0)
    eligible = int(result.get("eligible_count") or 0)
    counters = {"routed_count": routed, "eligible_count": eligible}
    if result.get("actual_execute") is True or result.get("execution_ticket_created") is True:
        _record_last_run("error", "boundary_violation", counters)
        return 2
    if result.get("status") not in {"ok", "warning"}:
        _record_last_run("error", "surface_not_ok", counters)
        return 1
    if eligible == 0:
        _record_last_run("ok", "no_eligible_proposals", counters)
    elif routed == 0:
        _record_last_run("ok", "nothing_routed", counters)
    else:
        _record_last_run("ok", "routed", counters)
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
