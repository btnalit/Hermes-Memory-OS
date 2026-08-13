#!/usr/bin/env python3
"""Memory-OS execution gate runner.

ExecutionGate wrapper for Memory-OS-owned Hermes cron helpers.
Generates time-bounded permits for cron-lane subprocesses and
records completion evidence in the gate envelope journal.

Each permit carries:
  - envelope_id (xgate_<timestamp>_<hash>)
  - expires_at  (bounded by lane risk_class via _expiry_seconds)
  - lane_id and risk_class for structural_write_gate validation
  - scope hash for write-surface scope checking (where applicable)
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "memory-os.execution_gate_envelope.v0"
# Keys the core writer (execution_gate.start_execution_gate_envelope) emits on
# permit records that this runner deliberately omits: the runner's scope IS the
# registry row (nothing worth hashing) and it carries no evidence refs. The
# dual-writer guard test pins this gap exactly — growing either writer's permit
# schema must touch this constant consciously, or the shared-file contract
# drifts silently.
RUNNER_OMITTED_PERMIT_KEYS = frozenset({"scope_hash", "evidence_refs"})
HELPER_REPORT_SCHEMA_VERSION = "memory-os.helper_execution_report.v0"
SIDECAR_LOCK_TIMEOUT_SECONDS = 15.0
# Backstop for lanes whose registry entry carries no explicit timeout.
DEFAULT_HELPER_TIMEOUT_SECONDS = 300
# Retention for the O(1) sidecar index.  Entries are only consulted while an
# envelope is live (permit -> completion), so a few days of history is ample;
# a missed lookup falls back to the full-scan rebuild in execution_gate.py.
# Without a cap this file grew one entry per envelope forever while being
# fully rewritten on every permit and completion.
SIDECAR_INDEX_MAX_ENTRIES = 2000


class ExecutionGateInfrastructureError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a Memory-OS cron helper behind ExecutionGate.")
    parser.add_argument("--registry-key", required=True)
    parser.add_argument("--hermes-home", default=os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
    parser.add_argument("--smoke-mode", choices=("normal", "safe", "render-only", "natural"), default="normal")
    parser.add_argument(
        "--profile",
        default="",
        help="Profile attribution for permit/completion records. Falls back to HERMES_PROFILE, then a profiles/<name>-shaped --hermes-home, then 'default'.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run_registry_key(
        str(args.registry_key),
        hermes_home=Path(args.hermes_home).expanduser(),
        smoke_mode=str(args.smoke_mode),
        profile=str(args.profile),
    )


def _resolve_profile(hermes_home: Path, explicit: str = "") -> tuple[str, dict[str, str] | None]:
    """Resolve the profile attribution for gate records against hermes_home.

    Priority: explicit --profile > HERMES_PROFILE > profile-shaped
    hermes_home (``.../profiles/<name>``) > ``"default"``.

    Returns ``(profile, conflict)``.  ``conflict`` is None when the sources
    agree; when an explicitly requested profile contradicts a profile-shaped
    home it carries {"requested", "derived_from_home"} and the caller must
    fail closed — stamping records with the wrong profile is exactly the
    mis-attribution this resolver exists to prevent.

    NOTE: this runner is deliberately stdlib-only, so this is a local twin of
    plugins.memory.memory_os.roots.resolve_profile_name.  A guard test pins
    both implementations to the same behavior table.
    """
    home = Path(hermes_home).expanduser().resolve()
    derived = home.name if home.name and home.parent.name == "profiles" else ""
    requested = (explicit or "").strip() or str(os.environ.get("HERMES_PROFILE") or "").strip()
    if requested and derived and requested != derived:
        return derived, {"requested": requested, "derived_from_home": derived}
    if requested:
        return requested, None
    if derived:
        return derived, None
    return "default", None


def run_registry_key(
    registry_key: str, *, hermes_home: Path, smoke_mode: str = "normal", profile: str = ""
) -> int:
    """Run one lane behind an ExecutionGate permit. Returns its exit code."""
    return int(
        run_registry_key_detailed(
            registry_key,
            hermes_home=hermes_home,
            smoke_mode=smoke_mode,
            profile=profile,
        ).get("returncode")
        or 0
    )


def run_registry_key_detailed(
    registry_key: str,
    *,
    hermes_home: Path,
    smoke_mode: str = "normal",
    timeout_seconds: int | None = None,
    profile: str = "",
) -> dict[str, Any]:
    """Run one lane and report the outcome structurally.

    ``timeout_seconds`` bounds the helper subprocess.  Under the old 1:1
    job-per-lane layout a hung helper cost only its own lane; under group
    ticks it would block every later member of the tick, so a bound is
    required rather than optional.  ``None``/0 falls back to the lane's
    registered ``timeout_seconds``.
    """
    spec = _load_spec(hermes_home, registry_key)
    if not spec:
        sys.stderr.write(f"unknown Memory-OS cron registry key: {registry_key}\n")
        return {"status": "unknown_registry_key", "error_code": "unknown_registry_key", "returncode": 2}
    resolved_profile, profile_conflict = _resolve_profile(hermes_home, profile)
    effective_timeout = int(timeout_seconds or 0) or int(spec.get("timeout_seconds") or 0) or DEFAULT_HELPER_TIMEOUT_SECONDS
    scripts_dir = Path(__file__).resolve().parent
    helper = scripts_dir / spec["raw_script"]
    boundary = {
        "actual_send": False,
        "actual_execute": False,
        "actual_identity_write": False,
        "actual_unapproved_crystallized_approval": False,
    }
    try:
        permit = _append_permit(
            hermes_home=hermes_home,
            registry_key=registry_key,
            lane_id=spec["lane_id"],
            risk_class=spec["risk_class"],
            raw_script=spec["raw_script"],
            helper_present=helper.is_file(),
            smoke_mode=smoke_mode,
            boundary=boundary,
            profile=resolved_profile,
            profile_conflict=profile_conflict,
        )
    except ExecutionGateInfrastructureError as exc:
        sys.stderr.write(f"Memory-OS execution gate infrastructure error: {exc.code}\n")
        return {"status": "infrastructure_error", "error_code": exc.code, "returncode": 3}
    envelope_id = str(permit["execution_gate_envelope_id"])
    if permit["permit_decision"] != "allowed":
        return {
            "status": "permit_blocked",
            "error_code": str(permit.get("permit_reason") or "permit_blocked"),
            "execution_gate_envelope_id": envelope_id,
            "returncode": 2,
        }
    if not helper.is_file():
        try:
            _append_completion(
                hermes_home=hermes_home,
                envelope_id=envelope_id,
                lane_id=spec["lane_id"],
                execution_status="helper_missing",
                returncode=2,
                smoke_mode=smoke_mode,
                boundary=boundary,
                helper_report={},
                profile=resolved_profile,
                requires_boundary_report=spec.get("requires_boundary_report", True),
            )
        except ExecutionGateInfrastructureError as exc:
            sys.stderr.write(f"Memory-OS execution gate infrastructure error: {exc.code}\n")
            return {
                "status": "infrastructure_error",
                "error_code": exc.code,
                "execution_gate_envelope_id": envelope_id,
                "returncode": 3,
            }
        sys.stderr.write(f"Memory-OS cron helper missing: {helper.name}\n")
        return {
            "status": "helper_missing",
            "error_code": "helper_missing",
            "execution_gate_envelope_id": envelope_id,
            "returncode": 2,
        }
    report_path = _helper_report_path(hermes_home, envelope_id)
    env = {
        **os.environ,
        "HERMES_HOME": str(hermes_home),
        # Hand the helper the profile this run resolved to, so every lane
        # script stamps its own records with the same attribution as the
        # permit/completion envelope instead of re-deriving (and possibly
        # mis-deriving) it from an incomplete environment.
        "HERMES_PROFILE": resolved_profile,
        "MEMORY_OS_EXECUTION_GATE_ENVELOPE_ID": envelope_id,
        "MEMORY_OS_EXECUTION_REPORT_PATH": str(report_path),
        "MEMORY_OS_EXECUTION_SMOKE_MODE": smoke_mode,
    }
    timed_out = False
    try:
        completed = subprocess.run(
            [sys.executable, str(helper)],
            check=False,
            text=True,
            capture_output=True,
            env=env,
            timeout=effective_timeout,
        )
        stdout, stderr, returncode = completed.stdout, completed.stderr, completed.returncode
    except subprocess.TimeoutExpired as exc:
        # The helper is killed by subprocess.run before this is raised.  Code
        # 124 matches the timeout convention already used by the monitor's
        # bounded collection.
        timed_out = True
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        returncode = 124
        sys.stderr.write(
            f"Memory-OS cron helper timeout after {effective_timeout}s: {helper.name}\n"
        )
    helper_report = {} if timed_out else _read_helper_report(report_path, stdout)
    observed_boundary = helper_report.get("boundary") if isinstance(helper_report.get("boundary"), dict) else boundary
    execution_status = "timeout" if timed_out else ("ok" if returncode == 0 else "error")
    try:
        _append_completion(
            hermes_home=hermes_home,
            envelope_id=envelope_id,
            lane_id=spec["lane_id"],
            execution_status=execution_status,
            returncode=returncode,
            smoke_mode=smoke_mode,
            boundary=observed_boundary,
            helper_report=helper_report,
            profile=resolved_profile,
            # A timed-out helper never got to write its boundary report, so
            # requiring one would mislabel the timeout as a boundary gap.
            requires_boundary_report=False if timed_out else spec.get("requires_boundary_report", True),
        )
    except ExecutionGateInfrastructureError as exc:
        if stdout:
            sys.stdout.write(stdout)
        if stderr:
            sys.stderr.write(stderr)
        sys.stderr.write(f"Memory-OS execution gate infrastructure error: {exc.code}\n")
        return {
            "status": "infrastructure_error",
            "error_code": exc.code,
            "execution_gate_envelope_id": envelope_id,
            "returncode": 3,
        }
    if stdout:
        sys.stdout.write(stdout)
    if stderr:
        sys.stderr.write(stderr)
    result = {
        "status": execution_status,
        "execution_gate_envelope_id": envelope_id,
        "lane_id": spec["lane_id"],
        "returncode": returncode,
    }
    if timed_out:
        result["error_code"] = "helper_timeout"
        result["error_detail"] = f"timeout_after_{effective_timeout}s"
    return result


def _load_spec(hermes_home: Path, registry_key: str) -> dict[str, Any] | None:
    snapshot_path = hermes_home / "memory-os" / "system" / "memory_os_cron_registry.json"
    if snapshot_path.exists():
        try:
            loaded = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            loaded = {}
        for item in loaded.get("specs", []) if isinstance(loaded.get("specs"), list) else []:
            if isinstance(item, dict) and str(item.get("key") or "") == registry_key:
                return _runner_spec_from_registry_item(item)
    try:
        from plugins.memory.memory_os.cron_registry import memory_os_cron_spec_by_key

        spec = memory_os_cron_spec_by_key(registry_key)
        return _runner_spec_from_registry_item(spec.to_json()) if spec else None
    except Exception:
        return None


def _runner_spec_from_registry_item(item: dict[str, Any]) -> dict[str, Any]:
    try:
        timeout_seconds = int(item.get("timeout_seconds") or 0)
    except (TypeError, ValueError):
        timeout_seconds = 0
    return {
        "raw_script": str(item.get("raw_script") or ""),
        "lane_id": str(item.get("lane_id") or ""),
        "risk_class": str(item.get("helper_kind") or "local_helper"),
        "requires_boundary_report": bool(item.get("requires_boundary_report")),
        # 0 means "not declared" -- the caller falls back to
        # DEFAULT_HELPER_TIMEOUT_SECONDS rather than running unbounded.
        "timeout_seconds": max(timeout_seconds, 0),
    }


def _expiry_seconds(lane_id: str, risk_class: str) -> int:
    """Return permitted expiry window in seconds for a lane.

    Tight for short-lived subprocess lanes, generous but bounded
    so stale permits can't linger indefinitely.
    """
    if risk_class in ("owner_gate", "system_restart"):
        return 300  # 5 min — human-in-loop or restart tasks
    if risk_class == "render_report":
        return 600  # 10 min — LLM-rendered reports
    # local_helper / default: 1 hour
    return 3600


def _append_permit(
    *,
    hermes_home: Path,
    registry_key: str,
    lane_id: str,
    risk_class: str,
    raw_script: str,
    helper_present: bool,
    smoke_mode: str,
    boundary: dict[str, Any],
    profile: str,
    profile_conflict: dict[str, str] | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    material = f"{registry_key}|{lane_id}|{now.isoformat()}"
    envelope_id = f"xgate_{now.strftime('%Y%m%dT%H%M%S%fZ')}_{hashlib.sha256(material.encode('utf-8')).hexdigest()[:10]}"
    boundary_true = _any_boundary_true(boundary)
    if boundary_true:
        permit_decision, permit_reason = "blocked", "boundary_true"
    elif profile_conflict:
        # A profile explicitly requested via --profile/HERMES_PROFILE
        # contradicts the profiles/<name>-shaped hermes_home.  Running would
        # stamp this home's records with another profile's identity, so fail
        # closed — but leave this blocked permit as durable evidence rather
        # than exiting silently.
        permit_decision, permit_reason = "blocked", "profile_home_conflict"
    else:
        permit_decision, permit_reason = "allowed", "boundary_false"
    record = {
        "schema_version": SCHEMA_VERSION,
        "stage": "permit",
        "execution_gate_envelope_id": envelope_id,
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": (now + timedelta(seconds=_expiry_seconds(lane_id, risk_class))).isoformat().replace("+00:00", "Z"),
        "profile": profile,
        "lane_id": lane_id,
        "trigger_surface": "hermes_cron",
        "risk_class": risk_class,
        "human_approval_required": False,
        "why_no_human_approval": "Memory-OS-owned cron helper render/report lane; no external send is performed by the helper",
        "scope": {
            "registry_key": registry_key,
            "raw_script": raw_script,
            "helper_present": helper_present,
            "smoke_mode": smoke_mode,
        },
        "boundary": boundary,
        "boundary_true": boundary_true,
        "precheck": {"helper_present": helper_present},
        "permit_decision": permit_decision,
        "permit_reason": permit_reason,
    }
    if profile_conflict:
        record["profile_conflict"] = dict(profile_conflict)
    _append_jsonl(_records_path(hermes_home), record)
    _update_sidecar_index(hermes_home, envelope_id, "permit", record)
    return record


def _append_completion(
    *,
    hermes_home: Path,
    envelope_id: str,
    lane_id: str,
    execution_status: str,
    returncode: int,
    smoke_mode: str,
    boundary: dict[str, Any],
    helper_report: dict[str, Any],
    profile: str,
    requires_boundary_report: bool = True,
) -> None:
    now = datetime.now(timezone.utc)
    if not requires_boundary_report:
        # Helpers that declare requires_boundary_report=False are designed
        # to run without boundary evidence (no_agent local helpers with no
        # external-send surface).  Mark them as boundary-not-required so
        # the monitor can exempt them from boundary_unobserved counting.
        observed = True
        boundary_not_required = True
    else:
        observed = helper_report.get("schema_version") == HELPER_REPORT_SCHEMA_VERSION
        boundary_not_required = False
    record = {
        "schema_version": SCHEMA_VERSION,
        "stage": "completion",
        "execution_gate_envelope_id": envelope_id,
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "profile": profile,
        "lane_id": lane_id,
        "execution_status": execution_status,
        "postcheck": {
            "returncode": returncode,
            "boundary": boundary,
            "postcheck_boundary_observed": observed,
            "postcheck_boundary_not_required": boundary_not_required,
            "helper_report_schema_version": str(helper_report.get("schema_version") or ""),
            "smoke_mode": smoke_mode,
        },
        "postcheck_boundary_true": _any_boundary_true(boundary),
        "result_summary": {
            "returncode": returncode,
            **(
                helper_report.get("result_summary")
                if isinstance(helper_report.get("result_summary"), dict)
                else {}
            ),
        },
    }
    _append_jsonl(_records_path(hermes_home), record)
    _update_sidecar_index(hermes_home, envelope_id, "completion", record)


def _records_path(hermes_home: Path) -> Path:
    return hermes_home / "memory-os" / "system" / "execution_gate_envelopes.jsonl"


def _helper_report_path(hermes_home: Path, envelope_id: str) -> Path:
    return hermes_home / "memory-os" / "system" / "execution_gate" / "helper_reports" / f"{envelope_id}.json"


def _read_helper_report(path: Path, stdout: str) -> dict[str, Any]:
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            loaded = {}
        if isinstance(loaded, dict) and loaded.get("schema_version") == HELPER_REPORT_SCHEMA_VERSION:
            return loaded
    stripped = (stdout or "").strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            loaded = json.loads(stripped)
        except json.JSONDecodeError:
            loaded = {}
        if isinstance(loaded, dict) and loaded.get("schema_version") == HELPER_REPORT_SCHEMA_VERSION:
            return loaded
    return {}


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    try:
        with _exclusive_file_lock(lock_path, timeout_seconds=SIDECAR_LOCK_TIMEOUT_SECONDS):
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
    except ExecutionGateInfrastructureError:
        raise
    except OSError as exc:
        raise ExecutionGateInfrastructureError("journal_append_failed") from exc


def _update_sidecar_index(hermes_home: Path, envelope_id: str, stage: str, record: dict[str, Any]) -> None:
    """Keep the ExecutionGate O(1) sidecar index in sync for cron-wrapper permits."""
    index_path = hermes_home / "memory-os" / "system" / "execution_gate_index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = index_path.with_name(f".{index_path.name}.lock")
    try:
        with _exclusive_file_lock(lock_path, timeout_seconds=SIDECAR_LOCK_TIMEOUT_SECONDS):
            try:
                loaded = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
            except json.JSONDecodeError:
                loaded = {}
            if not isinstance(loaded, dict):
                loaded = {}
            entry = loaded.get(envelope_id, {})
            if not isinstance(entry, dict):
                entry = {}
            entry["envelope_id"] = envelope_id
            if stage == "permit":
                entry.update(
                    {
                        "permit_decision": record.get("permit_decision"),
                        "lane_id": record.get("lane_id"),
                        "risk_class": record.get("risk_class"),
                        "scope_hash": record.get("scope_hash"),
                        "permit_created_at": record.get("created_at"),
                        "permit_expires_at": record.get("expires_at"),
                        "boundary_true": record.get("boundary_true", False),
                    }
                )
            elif stage == "completion":
                entry["completion_count"] = int(entry.get("completion_count") or 0) + 1
                entry["completion_status"] = record.get("execution_status") or record.get("completion_status")
                entry["completed_at"] = record.get("created_at")
            loaded[envelope_id] = entry
            _atomic_write_json(index_path, prune_sidecar_index(loaded, envelope_id))
    except ExecutionGateInfrastructureError:
        raise
    except OSError as exc:
        raise ExecutionGateInfrastructureError("sidecar_update_failed") from exc


def prune_sidecar_index(
    index: dict[str, Any],
    keep_envelope_id: str = "",
    *,
    max_entries: int = SIDECAR_INDEX_MAX_ENTRIES,
) -> dict[str, Any]:
    """Bound the sidecar index to the newest ``max_entries`` envelopes.

    The index is rewritten in full on every permit and completion, so
    unbounded growth turns each cron firing into an O(N) read+write+fsync.
    Dropping an old entry is safe: ``execution_gate.py`` rebuilds missing
    entries from the JSONL journal on lookup miss, and entries are only
    consulted while an envelope is live.

    ``keep_envelope_id`` is never evicted -- the envelope being written must
    survive its own prune regardless of clock skew in the sort key.
    """
    if max_entries <= 0 or len(index) <= max_entries:
        return index

    def sort_key(item: tuple[str, Any]) -> tuple[str, str]:
        envelope_id, entry = item
        if not isinstance(entry, dict):
            return ("", envelope_id)
        stamp = str(entry.get("permit_created_at") or entry.get("completed_at") or "")
        # envelope_id is prefixed with a UTC timestamp, so it is a sound
        # tiebreaker when an entry carries no usable timestamp.
        return (stamp, envelope_id)

    ordered = sorted(index.items(), key=sort_key)
    keep_count = max_entries
    kept = dict(ordered[-keep_count:])
    if keep_envelope_id and keep_envelope_id not in kept and keep_envelope_id in index:
        kept[keep_envelope_id] = index[keep_envelope_id]
    return kept


@contextlib.contextmanager
def _exclusive_file_lock(path: Path, *, timeout_seconds: float):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    deadline = time.monotonic() + max(0.1, float(timeout_seconds))
    locked = False
    try:
        while not locked:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except (BlockingIOError, OSError):
                if time.monotonic() >= deadline:
                    raise ExecutionGateInfrastructureError("sidecar_lock_timeout")
                time.sleep(0.01)
        yield
    finally:
        if locked:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        _fsync_directory(path.parent)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def _fsync_directory(path: Path) -> None:
    try:
        directory_fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(directory_fd)
    except OSError:
        pass
    finally:
        os.close(directory_fd)


def _any_boundary_true(value: Any) -> bool:
    if isinstance(value, bool):
        return value is True
    if isinstance(value, dict):
        return any(_any_boundary_true(item) for item in value.values())
    if isinstance(value, list):
        return any(_any_boundary_true(item) for item in value)
    return False


if __name__ == "__main__":
    raise SystemExit(main())
