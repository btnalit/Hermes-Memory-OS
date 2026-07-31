#!/usr/bin/env python3
"""Memory-OS cron group tick runner.

One Hermes cron job per *group*; this runner fires the group's due member
lanes, each behind its own ExecutionGate permit via
``memory_os_execution_gate_runner.run_registry_key_detailed``.

Governance granularity is unchanged: every member still opens and closes its
own permit/completion envelope with its own ``lane_id`` and ``risk_class``.
Only the Hermes scheduling surface is consolidated.

Design points that are load-bearing (see
``docs/resolver/hermes-memory-os-cron-consolidation-plan.md``):

* **Due gating.** The group's cron cadence is the *finest* member cadence.
  Each member declares ``due_interval_minutes`` and is skipped on ticks where
  it is not yet due, which reproduces its original effective cadence.  An
  ``interval`` member also self-heals after downtime (the next tick sees it
  overdue and runs it), which the old fixed-time cron could not do.
* **Calendar members.** ``v3_seed_evidence`` is date-partitioned, so elapsed
  gating could drift it across a UTC day boundary and skip or double-count a
  day.  ``due_policy="calendar"`` runs it at most once per UTC calendar day,
  on the first tick at/after its anchor.
* **Overlap.** A non-blocking group lock means a long tick can never be
  double-run by the next one.  Losing the lock is reported as an explicit
  ``skipped_overlap`` status, never a silent pass.
* **Isolation.** One member failing, timing out, or crashing must not stop the
  rest of the tick.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from memory_os_execution_gate_runner import (  # noqa: E402
    ExecutionGateInfrastructureError,
    run_registry_key_detailed,
)

SCHEMA_VERSION = "memory-os.cron_group_tick_report.v1"
LANE_STATE_SCHEMA_VERSION = "memory-os.cron_lane_state.v1"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the due members of a Memory-OS cron group.")
    parser.add_argument("--group-key", required=True)
    parser.add_argument("--hermes-home", default=os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
    parser.add_argument("--smoke-mode", choices=("normal", "safe", "render-only", "natural"), default="normal")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run every enabled member regardless of due state (manual/diagnostic use).",
    )
    parser.add_argument("--now", default="", help="Override current UTC time (ISO-8601). Testing only.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    now = _parse_iso(str(args.now)) if str(args.now) else datetime.now(timezone.utc)
    if now is None:
        sys.stderr.write(f"invalid --now value: {args.now}\n")
        return 2
    report = run_group(
        str(args.group_key),
        hermes_home=Path(args.hermes_home).expanduser(),
        smoke_mode=str(args.smoke_mode),
        force=bool(args.force),
        now=now,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return int(report.get("returncode") or 0)


def run_group(
    group_key: str,
    *,
    hermes_home: Path,
    smoke_mode: str = "normal",
    force: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    group, members = _load_group(hermes_home, group_key)
    if not group:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "error",
            "group_key": group_key,
            "error_code": "unknown_cron_group",
            "returncode": 2,
            "members": [],
        }

    lock_path = _group_lock_path(hermes_home, group_key)
    try:
        lock = _try_exclusive_lock(lock_path)
    except OSError as exc:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "error",
            "group_key": group_key,
            "error_code": "group_lock_unavailable",
            "error_detail": str(exc)[:200],
            "returncode": 3,
            "members": [],
        }
    if lock is None:
        # A previous tick of this same group is still running.  Reported
        # explicitly so the monitor can see a tick that is overrunning its
        # cadence; skipping silently would hide a real capacity problem.
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "skipped_overlap",
            "group_key": group_key,
            "group_name": group.get("name", ""),
            "returncode": 0,
            "skipped_overlap_count": 1,
            "members": [],
        }

    try:
        disabled = _read_disabled_lane_keys(hermes_home)
        state = _read_lane_state(hermes_home)
        lanes = state.setdefault("lanes", {})
        results: list[dict[str, Any]] = []
        worst_returncode = 0
        for spec in members:
            key = str(spec.get("key") or "")
            entry = lanes.get(key) if isinstance(lanes.get(key), dict) else {}
            if key in disabled:
                results.append({"key": key, "lane_id": spec.get("lane_id", ""), "status": "skipped_disabled"})
                continue
            due, reason = _is_due(spec, entry, now=now, force=force)
            if not due:
                results.append(
                    {
                        "key": key,
                        "lane_id": spec.get("lane_id", ""),
                        "status": "skipped_not_due",
                        "reason": reason,
                    }
                )
                continue
            started_at = now.isoformat().replace("+00:00", "Z")
            try:
                outcome = run_registry_key_detailed(
                    key,
                    hermes_home=hermes_home,
                    smoke_mode=smoke_mode,
                    timeout_seconds=int(spec.get("timeout_seconds") or 0) or None,
                )
            except ExecutionGateInfrastructureError as exc:
                # Journal/sidecar failure for this member.  Record it and keep
                # going: the remaining members are independent lanes and must
                # not be silently dropped because one lane's bookkeeping broke.
                outcome = {
                    "status": "infrastructure_error",
                    "error_code": exc.code,
                    "returncode": 3,
                }
            except Exception as exc:  # noqa: BLE001 - member isolation boundary
                outcome = {
                    "status": "error",
                    "error_code": "member_unhandled_exception",
                    "error_detail": f"{type(exc).__name__}: {exc}"[:200],
                    "returncode": 3,
                }
            returncode = int(outcome.get("returncode") or 0)
            worst_returncode = max(worst_returncode, returncode)
            # Record the attempt (not just successes) so a persistently
            # failing lane retries at its normal cadence instead of on every
            # tick.  Failures stay visible through the ExecutionGate journal.
            lanes[key] = {
                "last_started_at": started_at,
                "last_status": str(outcome.get("status") or ""),
                "last_returncode": returncode,
                "last_envelope_id": str(outcome.get("execution_gate_envelope_id") or ""),
            }
            member_result = {
                "key": key,
                "lane_id": spec.get("lane_id", ""),
                "status": str(outcome.get("status") or ""),
                "returncode": returncode,
            }
            if outcome.get("error_code"):
                member_result["error_code"] = str(outcome.get("error_code"))
            if outcome.get("error_detail"):
                member_result["error_detail"] = str(outcome.get("error_detail"))
            results.append(member_result)
        state["schema_version"] = LANE_STATE_SCHEMA_VERSION
        state["updated_at"] = now.isoformat().replace("+00:00", "Z")
        state_error = ""
        try:
            _write_lane_state(hermes_home, state)
        except OSError as exc:
            # Losing the state write means the next tick re-runs members that
            # already ran.  Surface it rather than passing silently.
            state_error = str(exc)[:200]
            worst_returncode = max(worst_returncode, 3)
        report = {
            "schema_version": SCHEMA_VERSION,
            "status": "ok" if worst_returncode == 0 else "error",
            "group_key": group_key,
            "group_name": group.get("name", ""),
            "ran_at": now.isoformat().replace("+00:00", "Z"),
            "member_total": len(members),
            "member_ran_count": sum(1 for item in results if item.get("status") not in _SKIPPED_STATUSES),
            "member_skipped_not_due_count": sum(1 for item in results if item.get("status") == "skipped_not_due"),
            "member_skipped_disabled_count": sum(1 for item in results if item.get("status") == "skipped_disabled"),
            "member_error_count": sum(1 for item in results if int(item.get("returncode") or 0) != 0),
            "returncode": worst_returncode,
            "members": results,
        }
        if state_error:
            report["error_code"] = "lane_state_write_failed"
            report["error_detail"] = state_error
        return report
    finally:
        _release_lock(lock)


_SKIPPED_STATUSES = frozenset({"skipped_not_due", "skipped_disabled"})


# ── due evaluation ────────────────────────────────────────────────────


def _is_due(spec: dict[str, Any], entry: dict[str, Any], *, now: datetime, force: bool) -> tuple[bool, str]:
    if force:
        return True, "forced"
    last_started = _parse_iso(str(entry.get("last_started_at") or ""))
    if last_started is None:
        return True, "no_previous_run"
    policy = str(spec.get("due_policy") or "interval")
    if policy == "calendar":
        anchor_minutes = _anchor_minutes(str(spec.get("calendar_anchor") or "00:00"))
        if last_started.astimezone(timezone.utc).date() >= now.astimezone(timezone.utc).date():
            return False, "already_ran_today"
        if (now.hour * 60 + now.minute) < anchor_minutes:
            return False, "before_calendar_anchor"
        return True, "calendar_day_due"
    try:
        interval_minutes = int(spec.get("due_interval_minutes") or 0)
    except (TypeError, ValueError):
        interval_minutes = 0
    if interval_minutes <= 0:
        # A zero/garbage interval must not mean "run every tick".  Treat it as
        # daily, matching the registry's own fallback.
        interval_minutes = 1440
    # Tolerance: cron ticks jitter by seconds, so a lane whose interval is an
    # exact multiple of the tick would otherwise alternate run/skip.
    tolerance = timedelta(seconds=30)
    if now - last_started + tolerance >= timedelta(minutes=interval_minutes):
        return True, "interval_elapsed"
    return False, "interval_not_elapsed"


def _anchor_minutes(anchor: str) -> int:
    parts = str(anchor or "").split(":")
    if len(parts) != 2:
        return 0
    try:
        hours, minutes = int(parts[0]), int(parts[1])
    except ValueError:
        return 0
    if not (0 <= hours <= 23 and 0 <= minutes <= 59):
        return 0
    return hours * 60 + minutes


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


# ── registry loading ──────────────────────────────────────────────────


def _load_group(hermes_home: Path, group_key: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Resolve a group and its member specs.

    Prefers the installed snapshot (which reflects what onboarding actually
    installed on this host, including profile exclusions) and falls back to
    the compiled-in registry.
    """
    snapshot_path = hermes_home / "memory-os" / "system" / "memory_os_cron_registry.json"
    loaded: dict[str, Any] = {}
    if snapshot_path.exists():
        try:
            parsed = json.loads(snapshot_path.read_text(encoding="utf-8"))
            loaded = parsed if isinstance(parsed, dict) else {}
        except (OSError, json.JSONDecodeError):
            loaded = {}
    groups = loaded.get("groups") if isinstance(loaded.get("groups"), list) else []
    specs = loaded.get("specs") if isinstance(loaded.get("specs"), list) else []
    group = next(
        (item for item in groups if isinstance(item, dict) and str(item.get("key") or "") == group_key),
        {},
    )
    if group and specs:
        by_key = {str(item.get("key") or ""): item for item in specs if isinstance(item, dict)}
        members = [by_key[key] for key in group.get("member_keys", []) if key in by_key]
        if members:
            return group, members
    return _load_group_from_registry(group_key)


def _load_group_from_registry(group_key: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        from plugins.memory.memory_os.cron_registry import (
            memory_os_cron_group_by_key,
            memory_os_cron_spec_by_key,
        )
    except Exception:  # noqa: BLE001 - registry unavailable in installed layout
        return {}, []
    group = memory_os_cron_group_by_key(group_key)
    if not group:
        return {}, []
    members = []
    for key in group.member_keys:
        spec = memory_os_cron_spec_by_key(key)
        if spec:
            members.append(spec.to_json())
    return group.to_json(), members


def _read_disabled_lane_keys(hermes_home: Path) -> frozenset[str]:
    path = hermes_home / "memory-os" / "system" / "cron_lane_disabled.json"
    if not path.exists():
        return frozenset()
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # A corrupt disable list must never silently stop governed lanes.
        return frozenset()
    entries = loaded.get("disabled_lane_keys") if isinstance(loaded, dict) else loaded
    if not isinstance(entries, list):
        return frozenset()
    return frozenset(str(entry) for entry in entries if str(entry))


# ── lane state ────────────────────────────────────────────────────────


def _lane_state_path(hermes_home: Path) -> Path:
    return hermes_home / "memory-os" / "system" / "cron_lane_state.json"


def _read_lane_state(hermes_home: Path) -> dict[str, Any]:
    path = _lane_state_path(hermes_home)
    if not path.exists():
        return {"schema_version": LANE_STATE_SCHEMA_VERSION, "lanes": {}}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # Unreadable state means "nothing has run"; every member becomes due.
        # That is the safe direction -- it re-runs idempotent lanes rather
        # than silently starving them forever.
        return {"schema_version": LANE_STATE_SCHEMA_VERSION, "lanes": {}}
    if not isinstance(loaded, dict):
        return {"schema_version": LANE_STATE_SCHEMA_VERSION, "lanes": {}}
    if not isinstance(loaded.get("lanes"), dict):
        loaded["lanes"] = {}
    return loaded


def _write_lane_state(hermes_home: Path, state: dict[str, Any]) -> None:
    path = _lane_state_path(hermes_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


# ── group lock ────────────────────────────────────────────────────────


def _group_lock_path(hermes_home: Path, group_key: str) -> Path:
    return hermes_home / "memory-os" / "system" / "execution_gate" / f".cron_group_{group_key}.lock"


def _try_exclusive_lock(path: Path):
    """Non-blocking exclusive lock. Returns a handle, or None if already held."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    try:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        handle.close()
        return None
    return handle


def _release_lock(handle) -> None:
    if handle is None:
        return
    try:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    finally:
        handle.close()


if __name__ == "__main__":
    raise SystemExit(main())
