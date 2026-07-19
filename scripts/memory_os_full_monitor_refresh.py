#!/usr/bin/env python3
"""Refresh the canonical full-Monitor artifact without treating policy FAIL as a job failure.

The full monitor intentionally exits 2 when a governance observation gate is red.
That classification is valid evidence, not an execution failure. This wrapper runs the
monitor into a temporary path, validates the artifact, atomically publishes it, and
stays silent on success for Hermes no-agent cron use.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hermes-home", type=Path, default=Path.home() / ".hermes")
    parser.add_argument("--monitor-script", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--keep-artifacts", type=int, default=14)
    return parser


def _validated_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("snapshot root must be an object")
    classification = payload.get("classification")
    if not isinstance(classification, dict):
        raise ValueError("snapshot classification is missing")
    status = str(classification.get("status") or "")
    if status not in {"PASS", "WARN", "FAIL"}:
        raise ValueError(f"invalid monitor classification status: {status!r}")
    return payload


def _prune_old_artifacts(directory: Path, *, keep: int) -> None:
    artifacts = sorted(
        directory.glob("monitor_*.json"),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    for stale in artifacts[max(keep, 1) :]:
        stale.unlink(missing_ok=True)


def refresh(
    *,
    hermes_home: Path,
    monitor_script: Path,
    timeout_seconds: int,
    keep_artifacts: int,
) -> Path:
    artifact_dir = hermes_home / "memory-os" / "system" / "monitor_artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=".full-monitor-", suffix=".tmp", dir=artifact_dir,
    )
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        completed = subprocess.run(
            [
                sys.executable,
                str(monitor_script),
                "--hermes-home",
                str(hermes_home),
                "--snapshot-out",
                str(temp_path),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=max(int(timeout_seconds), 1),
        )
        if completed.returncode not in {0, 2}:
            detail = (completed.stderr or completed.stdout or "no monitor output").strip()[-500:]
            raise RuntimeError(f"monitor process exited {completed.returncode}: {detail}")
        _validated_payload(temp_path)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        destination = artifact_dir / f"monitor_{stamp}.json"
        os.replace(temp_path, destination)
        _prune_old_artifacts(artifact_dir, keep=keep_artifacts)
        return destination
    finally:
        temp_path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    script = args.monitor_script or Path(__file__).with_name("memory_os_3_200_monitor.py")
    try:
        refresh(
            hermes_home=args.hermes_home.expanduser().resolve(),
            monitor_script=script.expanduser().resolve(),
            timeout_seconds=args.timeout_seconds,
            keep_artifacts=args.keep_artifacts,
        )
    except Exception as exc:
        print(f"Full monitor refresh failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
