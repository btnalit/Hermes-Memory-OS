#!/usr/bin/env python3
"""Refresh the canonical full-Monitor artifact without treating policy FAIL as a job failure.

The full monitor intentionally exits 2 when a governance observation gate is red.
That classification is valid evidence, not an execution failure. This wrapper runs the
monitor into a temporary path, validates the artifact, atomically publishes it, and
stays silent on success for Hermes no-agent cron use.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_SELF = Path(__file__).absolute()
_REPO_ROOT = _SELF.parents[1]
_IMPORT_ROOT = (
    _REPO_ROOT
    if (_REPO_ROOT / "plugins" / "memory" / "memory_os").exists()
    else _REPO_ROOT / "memory-os" / "runtime" / "python"
)
if _IMPORT_ROOT.exists() and str(_IMPORT_ROOT) not in sys.path:
    sys.path.insert(0, str(_IMPORT_ROOT))

from plugins.memory.memory_os.lane_last_run import record_lane_last_run
from plugins.memory.memory_os.operational_truth import build_full_monitor_envelope


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hermes-home", type=Path, default=Path.home() / ".hermes")
    parser.add_argument("--monitor-script", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--keep-artifacts", type=int, default=14)
    parser.add_argument("--source-head", default="")
    parser.add_argument("--runtime-digest", default="")
    parser.add_argument("--monitor-profile", choices=["live", "clean-host"], default="")
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
    now: datetime,
    source_head: str,
    runtime_digest: str,
    monitor_profile: str = "",
) -> Path:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("refresh now must be timezone-aware")
    artifact_dir = hermes_home / "memory-os" / "system" / "monitor_artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=".full-monitor-", suffix=".tmp", dir=artifact_dir,
    )
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        monitor_command = [
                sys.executable,
                str(monitor_script),
                "--hermes-home",
                str(hermes_home),
                "--python-bin",
                sys.executable,
                "--snapshot-out",
                str(temp_path),
                "--output",
                "json",
                # Declare this wrapper's envelope so the monitor can grant its
                # probe subprocess the real budget instead of the 300s floor
                # (the nightly probe_script_timeout FAILs were the probe being
                # killed at the floor while this wrapper still had 300s left).
                "--caller-timeout-seconds",
                str(max(int(timeout_seconds), 1)),
            ]
        if monitor_profile:
            monitor_command.extend(["--monitor-profile", monitor_profile])
        with tempfile.TemporaryDirectory(prefix=".monitor-cwd-", dir=artifact_dir) as monitor_cwd:
            completed = subprocess.run(
                monitor_command,
                cwd=monitor_cwd,
                env=_monitor_environment(hermes_home, monitor_script),
                capture_output=True,
                text=True,
                check=False,
                timeout=max(int(timeout_seconds), 1),
            )
        if completed.returncode not in {0, 2}:
            detail = (completed.stderr or completed.stdout or "no monitor output").strip()[-500:]
            raise RuntimeError(f"monitor process exited {completed.returncode}: {detail}")
        payload = _validated_payload(temp_path)
        monitor_version = str(payload.get("schema_version") or "")
        if not monitor_version or monitor_version.lower() == "unknown":
            raise ValueError("monitor payload must declare a non-unknown schema_version")
        generated_at = now.astimezone(timezone.utc)
        receipt_seed = ":".join(
            (
                generated_at.isoformat(),
                source_head,
                runtime_digest,
                monitor_version,
                str(completed.returncode),
            )
        )
        producer_receipt = {
            "schema_version": "memory-os.full_monitor_producer_receipt.v1",
            "receipt_id": "fmpr_" + hashlib.sha256(receipt_seed.encode("utf-8")).hexdigest()[:20],
            "producer": "memory_os_full_monitor_refresh",
            "monitor_exit_code": completed.returncode,
            "completed_at": generated_at.isoformat().replace("+00:00", "Z"),
            "publication": "validated_atomic_replace",
            "monitor_script_digest": _file_digest(monitor_script),
        }
        envelope = build_full_monitor_envelope(
            payload,
            generated_at=generated_at,
            source_head=source_head,
            runtime_digest=runtime_digest,
            monitor_version=monitor_version,
            producer_receipt=producer_receipt,
        )
        temp_path.write_text(
            json.dumps(envelope, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        stamp = generated_at.strftime("%Y%m%dT%H%M%S%fZ")
        destination = artifact_dir / f"monitor_{stamp}.json"
        os.replace(temp_path, destination)
        _prune_old_artifacts(artifact_dir, keep=keep_artifacts)
        return destination
    finally:
        temp_path.unlink(missing_ok=True)


def _deployment_source_head(hermes_home: Path) -> str:
    manifest_path = hermes_home.expanduser().resolve() / "memory-os" / "system" / "deployment_runtime_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "unknown"
    if not isinstance(manifest, dict):
        return "unknown"
    return str(manifest.get("deployed_head") or manifest.get("source_repo_head") or "unknown")


def _monitor_environment(hermes_home: Path, monitor_script: Path) -> dict[str, str]:
    """Give nested monitor probes an explicit import root without relying on cwd."""
    resolved_script = monitor_script.expanduser().resolve()
    scripts_root = resolved_script.parent
    source_root = scripts_root.parent
    runtime_root = hermes_home.expanduser().resolve() / "memory-os" / "runtime" / "python"
    import_root = source_root if (source_root / "plugins" / "memory" / "memory_os").exists() else runtime_root
    env = dict(os.environ)
    paths = [str(scripts_root), str(import_root)]
    paths.extend(part for part in env.get("PYTHONPATH", "").split(os.pathsep) if part)
    env["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(paths))
    return env


def _file_digest(path: Path) -> str:
    try:
        content = path.expanduser().resolve().read_bytes()
    except OSError:
        return "unknown"
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _runtime_tree_digest(hermes_home: Path) -> str:
    runtime_root = (
        hermes_home.expanduser().resolve()
        / "memory-os" / "runtime" / "python" / "plugins" / "memory" / "memory_os"
    )
    files = sorted(
        path for path in runtime_root.rglob("*.py")
        if path.is_file() and "__pycache__" not in path.parts
    )
    if not files:
        return "unknown"
    digest = hashlib.sha256()
    try:
        for path in files:
            digest.update(path.relative_to(runtime_root).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    except OSError:
        return "unknown"
    return "sha256:" + digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    script = args.monitor_script or Path(__file__).with_name("memory_os_3_200_monitor.py")
    hermes_home = args.hermes_home.expanduser().resolve()
    script = script.expanduser().resolve()
    try:
        refresh(
            hermes_home=hermes_home,
            monitor_script=script,
            timeout_seconds=args.timeout_seconds,
            keep_artifacts=args.keep_artifacts,
            now=datetime.now(timezone.utc),
            source_head=args.source_head or _deployment_source_head(hermes_home),
            runtime_digest=args.runtime_digest or _runtime_tree_digest(hermes_home),
            monitor_profile=args.monitor_profile,
        )
    except Exception as exc:
        # The finally-block deletes the temp artifact on failure, so without
        # this record a crashed refresh leaves the previous snapshot silently
        # going stale with no on-disk explanation.
        record_lane_last_run(
            hermes_home,
            "full_monitor_refresh",
            status="error",
            reason="refresh_failed",
            error=str(exc),
        )
        print(f"Full monitor refresh failed: {exc}", file=sys.stderr)
        return 2
    record_lane_last_run(
        hermes_home,
        "full_monitor_refresh",
        status="ok",
        reason="artifact_published",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
