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
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# ── Memory-OS identity markers ──────────────────────────────────────────
# A valid repo root must contain ALL of these files.  We check for
# specific paths (not just pyproject.toml alone) so we don't confuse a
# random Python project with a Memory-OS clone.
_MEMORY_OS_IDENTITY_MARKERS = [
    "pyproject.toml",
    "plugins/memory/memory_os/__init__.py",
]


def _resolve_repo_root() -> Path:
    """Resolve the Memory-OS repository root for probe discovery.

    1. MEMORY_OS_REPO_ROOT env var
    2. Config file next to this script (l3_probe_repo_root.txt)
    3. Auto-detection — walk up from script / cwd / common clone paths
       looking for pyproject.toml + plugins/memory/memory_os/__init__.py

    Every candidate is identity-verified before acceptance — a directory
    that exists but lacks the marker files is rejected with a diagnostic
    (fail-loud), not silently accepted.
    """
    # 1. Env var
    env_val = os.environ.get("MEMORY_OS_REPO_ROOT", "").strip()
    if env_val:
        candidate = Path(env_val)
        if _is_memory_os_repo(candidate):
            return candidate

    # 2. Config file
    config_file = Path(__file__).with_name("l3_probe_repo_root.txt")
    if config_file.is_file():
        candidate = Path(config_file.read_text(encoding="utf-8").strip())
        if _is_memory_os_repo(candidate):
            return candidate

    # 3. Auto-detection
    candidate = _auto_detect_repo_root()
    if candidate is not None:
        return candidate

    raise SystemExit(
        "Cannot resolve Memory-OS repo root. "
        "Set MEMORY_OS_REPO_ROOT env var or ensure l3_probe_repo_root.txt exists "
        f"next to this script ({config_file}). "
        "Auto-detection also failed — no directory with pyproject.toml + "
        "plugins/memory/memory_os/__init__.py found from script location, "
        "cwd, or common clone paths."
    )


def _is_memory_os_repo(candidate: Path) -> bool:
    """Verify *candidate* is a Memory-OS repository root.

    Returns True if the directory exists and contains ALL identity markers.
    Fails loud (SystemExit) when the directory exists but doesn't look like
    a Memory-OS repo — this prevents silent acceptance of wrong/old clones.
    """
    if not candidate.is_dir():
        return False

    missing = [m for m in _MEMORY_OS_IDENTITY_MARKERS if not (candidate / m).is_file()]
    if missing:
        raise SystemExit(
            f"Repo root candidate {candidate} does not appear to be a Memory-OS "
            f"repository. Missing marker files: {', '.join(missing)}. "
            "Check that MEMORY_OS_REPO_ROOT or l3_probe_repo_root.txt "
            "points to the correct clone."
        )
    return True


def _auto_detect_repo_root() -> Path | None:
    """Walk up from known starting points looking for Memory-OS identity markers.

    Tries, in order:
      - Walk up from this script's directory
      - Walk up from the current working directory
      - Common clone locations (/opt/Hermes-Memory-OS, ~/Hermes-Memory-OS)
    """
    starts = [
        Path(__file__).resolve().parent,
        Path.cwd(),
    ]
    for start in starts:
        found = _walk_up_for_markers(start, _MEMORY_OS_IDENTITY_MARKERS)
        if found is not None:
            return found

    common = [
        Path("/opt/Hermes-Memory-OS"),
        Path.home() / "Hermes-Memory-OS",
    ]
    for path in common:
        if _has_all_markers(path, _MEMORY_OS_IDENTITY_MARKERS):
            return path

    return None


def _walk_up_for_markers(start: Path, markers: list[str]) -> Path | None:
    """Walk up from *start* until we find a directory containing all *markers*."""
    current = start.resolve()
    for _ in range(10):  # safety cap: don't walk past filesystem root
        if _has_all_markers(current, markers):
            return current
        parent = current.parent
        if parent == current:  # reached filesystem root
            break
        current = parent
    return None


def _has_all_markers(path: Path, markers: list[str]) -> bool:
    """Check if *path* contains all relative *markers*."""
    return all((path / m).is_file() for m in markers)


REPO_ROOT = _resolve_repo_root()
PROBE_SCRIPT = REPO_ROOT / "scripts" / "probe_l3_prefetch_behavior.py"
LAST_RUN_FILE = Path(tempfile.gettempdir()) / "l3_probe_last_result.json"

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
