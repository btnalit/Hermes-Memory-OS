#!/usr/bin/env python3
"""L3 probe cron helper — runs the governance path probe and reports results.

no_agent=True watchdog pattern:
  - Exit 0 + empty stdout → SILENT (nothing sent to user)
  - Exit 1 + error details → ALERT (delivered to origin channel)

Installed by deploy_l3_probe.py. Runs probe_l3_prefetch_behavior.py
from the repo to exercise the real governance write/read/revoke path.

Usage:
    python3 scripts/memory_os_l3_probe_helper.py [--smoke]
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path("/opt/Hermes-Memory-OS")
PROBE_SCRIPT = REPO_ROOT / "scripts" / "probe_l3_prefetch_behavior.py"
LAST_RUN_FILE = Path("/tmp/l3_probe_last_result.json")

SCHEMA_VERSION = "memory-os.l3_probe_result.v0"


def main(smoke: bool = False) -> int:
    if not PROBE_SCRIPT.exists():
        print(json.dumps({
            "schema_version": SCHEMA_VERSION,
            "status": "error",
            "error": f"probe script not found: {PROBE_SCRIPT}",
            "action": "Is the repo mounted at /opt/Hermes-Memory-OS?",
        }))
        return 1

    result = subprocess.run(
        [sys.executable, str(PROBE_SCRIPT)],
        capture_output=True, text=True, timeout=120,
        cwd=str(REPO_ROOT),
    )

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    details = _parse_probe_output(stdout)

    # Save last result for diagnostics
    LAST_RUN_FILE.parent.mkdir(parents=True, exist_ok=True)
    LAST_RUN_FILE.write_text(json.dumps({
        "returncode": result.returncode,
        "details": details,
        "stderr_truncated": stderr[-500:] if stderr else "",
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }, indent=2))

    # Smoke mode: always print result regardless of pass/fail
    if smoke:
        print(json.dumps({
            "schema_version": SCHEMA_VERSION,
            "status": "smoke_test",
            "returncode": result.returncode,
            "details": details,
        }, indent=2))
        return 0 if result.returncode == 0 and "GOVERNANCE PATH" in stdout else 1

    # Production mode: quiet on pass, loud on fail
    all_pass = (
        result.returncode == 0
        and "GOVERNANCE PATH" in stdout
        and "PARTIAL FAILURE" not in stdout
    )
    if all_pass:
        return 0  # silent — nothing delivered to user

    # Failure → alert
    report = {
        "schema_version": SCHEMA_VERSION,
        "status": "L3_PROBE_FAILURE",
        "returncode": result.returncode,
        "details": {k: v for k, v in details.items() if k != "verdict"},
    }
    if "NONCE NOT FOUND" in stdout:
        report["probable_cause"] = "L2 recall failure — nonce written but build_prefetch doesn't contain it"
        report["next_step"] = "Check prefetch budget starvation or _crystallized_lines health"
    elif "NEGATIVE NONCE FOUND" in stdout:
        report["probable_cause"] = "L2 negative check failed — unexpected nonce leak"
        report["next_step"] = "Check _crystallized_lines filter and is_active logic"
    elif result.returncode != 0:
        report["probable_cause"] = "Probe crashed (non-zero exit)"
        report["next_step"] = f"Manual run: python3 {PROBE_SCRIPT}"

    if stderr:
        report["stderr_truncated"] = stderr[-500:]

    print(json.dumps(report, indent=2))
    return 1


def _parse_probe_output(stdout: str) -> dict:
    """Extract key: value pairs from the probe's flat output format."""
    details = {}
    for line in stdout.splitlines():
        if ": " in line:
            key, _, value = line.partition(": ")
            details[key.strip()] = value.strip()
    return details


if __name__ == "__main__":
    smoke = "--smoke" in sys.argv
    raise SystemExit(main(smoke=smoke))
