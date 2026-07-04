"""Shared JSONL and small JSON state IO helpers for Memory-OS."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, Iterable

import logging
import threading
from contextlib import contextmanager
from uuid import uuid4

try:
    import fcntl
    _FLOCK_AVAILABLE = True
except ImportError:
    fcntl = None  # type: ignore
    _FLOCK_AVAILABLE = False

_flock_warned = False
logger = logging.getLogger(__name__)


ERROR_RECORD_SCHEMA_VERSION = "memory-os.error_record.v0"


@dataclass(frozen=True)
class JsonlReadResult:
    records: list[dict[str, Any]]
    error_records: list[dict[str, Any]]

    @property
    def suppressed_error_count(self) -> int:
        return len(self.error_records)

    @property
    def recent_error_codes(self) -> list[str]:
        return [str(record.get("error_code") or "") for record in self.error_records if record.get("error_code")]


@dataclass(frozen=True)
class JsonStateReadResult:
    data: dict[str, Any]
    error_records: list[dict[str, Any]]

    @property
    def suppressed_error_count(self) -> int:
        return len(self.error_records)

    @property
    def recent_error_codes(self) -> list[str]:
        return [str(record.get("error_code") or "") for record in self.error_records if record.get("error_code")]


def build_error_record(
    *,
    component: str,
    operation: str,
    error_code: str,
    severity: str = "warning",
    recoverable: bool = True,
    path: str | Path | None = None,
    line_number: int | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "schema_version": ERROR_RECORD_SCHEMA_VERSION,
        "component": str(component),
        "operation": str(operation),
        "error_code": str(error_code),
        "severity": str(severity),
        "recoverable": bool(recoverable),
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    if path is not None:
        record["path"] = str(path)
    if line_number is not None:
        record["line_number"] = int(line_number)
    if details:
        record["details"] = dict(details)
    return record


def read_jsonl(path: str | Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    return read_jsonl_result(path, limit=limit).records


def read_jsonl_result(
    path: str | Path,
    *,
    limit: int | None = None,
    component: str = "memory_os.jsonl_io",
    operation: str = "read_jsonl",
) -> JsonlReadResult:
    target = Path(path)
    if not target.exists():
        return JsonlReadResult(records=[], error_records=[])
    records: list[dict[str, Any]] = []
    error_records: list[dict[str, Any]] = []
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return JsonlReadResult(
            records=[],
            error_records=[
                build_error_record(
                    component=component,
                    operation=operation,
                    error_code="jsonl_read_error",
                    severity="error",
                    recoverable=True,
                    path=target,
                    details={"error_type": type(exc).__name__},
                )
            ],
        )
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            error_records.append(
                build_error_record(
                    component=component,
                    operation=operation,
                    error_code="jsonl_malformed_line",
                    severity="warning",
                    recoverable=True,
                    path=target,
                    line_number=line_number,
                )
            )
            continue
        if not isinstance(parsed, dict):
            error_records.append(
                build_error_record(
                    component=component,
                    operation=operation,
                    error_code="jsonl_non_object_line",
                    severity="warning",
                    recoverable=True,
                    path=target,
                    line_number=line_number,
                )
            )
            continue
        records.append(parsed)
        if limit is not None and len(records) >= limit:
            break
    return JsonlReadResult(records=records, error_records=error_records)


def latest_jsonl_record(path: str | Path) -> dict[str, Any] | None:
    records = read_jsonl(path)
    return records[-1] if records else None


def read_json_state_result(
    path: str | Path,
    *,
    component: str = "memory_os.jsonl_io",
    operation: str = "read_json_state",
) -> JsonStateReadResult:
    target = Path(path)
    if not target.exists():
        return JsonStateReadResult(data={}, error_records=[])
    try:
        parsed = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return JsonStateReadResult(
            data={},
            error_records=[
                build_error_record(
                    component=component,
                    operation=operation,
                    error_code="json_state_malformed",
                    severity="warning",
                    recoverable=True,
                    path=target,
                )
            ],
        )
    except OSError as exc:
        return JsonStateReadResult(
            data={},
            error_records=[
                build_error_record(
                    component=component,
                    operation=operation,
                    error_code="json_state_read_error",
                    severity="error",
                    recoverable=True,
                    path=target,
                    details={"error_type": type(exc).__name__},
                )
            ],
        )
    if not isinstance(parsed, dict):
        return JsonStateReadResult(
            data={},
            error_records=[
                build_error_record(
                    component=component,
                    operation=operation,
                    error_code="json_state_non_object",
                    severity="warning",
                    recoverable=True,
                    path=target,
                )
            ],
        )
    return JsonStateReadResult(data=parsed, error_records=[])


def append_jsonl(path: str | Path, record: dict[str, Any], *, ensure_parent: bool = True) -> None:
    target = Path(path)
    if ensure_parent:
        target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def write_jsonl(path: str | Path, records: Iterable[dict[str, Any]], *, ensure_parent: bool = True) -> None:
    target = Path(path)
    if ensure_parent:
        target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )


def jsonl_compact(
    path: str | Path,
    keep_predicate: "Callable[[dict[str, Any]], bool]",
    *,
    max_lines: int | None = None,
    dry_run: bool = True,
    backup: bool = True,
) -> dict[str, Any]:
    """Compact a JSONL file: keep only records matching *keep_predicate*.

    When *max_lines* is set, additionally caps the output to the most recent
    N kept records (preserving tail — JSONL append order).  Malformed lines
    are silently dropped (fail-open: compaction is not a correctness-critical
    operation and must not lose data from a parse error).

    dry_run=True → report what would happen without writing.
    backup=True + dry_run=False → atomically replace after backing up the
    original to ``<path>.compact.bak``.

    Returns a structured result dict with ``status``, ``lines_before``,
    ``lines_after``, ``kept``, ``dropped``, ``malformed``, ``dry_run``,
    ``backup_path``, and any ``error``.
    """
    from datetime import datetime, timezone

    target = Path(path)
    result: dict[str, Any] = {
        "status": "ok",
        "path": str(target),
        "dry_run": dry_run,
        "lines_before": 0,
        "lines_after": 0,
        "kept": 0,
        "dropped": 0,
        "malformed": 0,
        "backup_path": None,
    }

    if not target.exists():
        result["status"] = "no_file"
        return result

    # ── Read ────────────────────────────────────────────────────────
    kept: list[dict[str, Any]] = []
    for raw_line in target.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        result["lines_before"] += 1
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            result["malformed"] += 1
            continue
        if keep_predicate(record):
            kept.append(record)

    result["kept"] = len(kept)
    result["dropped"] = result["lines_before"] - result["kept"] - result["malformed"]

    # ── Apply max_lines cap (most recent) ───────────────────────────
    if max_lines is not None and len(kept) > max_lines:
        kept = kept[-max_lines:]
        result["max_lines_applied"] = True
    else:
        result["max_lines_applied"] = False

    result["lines_after"] = len(kept)

    # ── No-op when nothing changes ──────────────────────────────────
    if result["lines_before"] == result["lines_after"] and result["malformed"] == 0:
        result["status"] = "no_change"
        return result

    if dry_run:
        return result

    # ── Backup ──────────────────────────────────────────────────────
    backup_path: Path | None = None
    if backup:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = target.with_name(f"{target.name}.compact.{ts}.bak")
        try:
            backup_path.write_bytes(target.read_bytes())
            result["backup_path"] = str(backup_path)
        except OSError as exc:
            result["status"] = "backup_failed"
            result["error"] = str(exc)
            return result

    # ── Atomic replace ──────────────────────────────────────────────
    tmp_path = target.with_name(f".{target.name}.compact.tmp")
    try:
        write_jsonl(tmp_path, kept, ensure_parent=False)
        os.replace(tmp_path, target)
    except OSError as exc:
        result["status"] = "write_failed"
        result["error"] = str(exc)
        if tmp_path.exists():
            tmp_path.unlink()
        return result

    return result


def write_json_atomic(path: str | Path, data: Any, *, ensure_parent: bool = True) -> None:
    target = Path(path)
    if ensure_parent:
        target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_name(f".{target.name}.tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp_path, target)


# ── Locked JSONL IO primitives (data-plane safety) ─────────────────

_held = threading.local()
_fallback_locks: dict[str, threading.Lock] = {}
_fallback_locks_lock = threading.Lock()


def _get_fallback_lock(key: str) -> threading.Lock:
    """Return (or create) a per-path threading.Lock for non-fcntl platforms."""
    with _fallback_locks_lock:
        if key not in _fallback_locks:
            _fallback_locks[key] = threading.Lock()
        return _fallback_locks[key]


def _assert_not_reentrant(target: Path) -> None:
    """Raise RuntimeError if *target* is already held by this process."""
    s = getattr(_held, "paths", None) or set()
    key = str(target.resolve())
    if key in s:
        raise RuntimeError(f"reentrant locked_jsonl_file on {key}")
    s.add(key)
    _held.paths = s


def _release_reentrant(target: Path) -> None:
    """Release the reentrant guard for *target*."""
    s = getattr(_held, "paths", None) or set()
    s.discard(str(target.resolve()))
    _held.paths = s


@contextmanager
def locked_jsonl_file(path: Path) -> Generator[Path, None, None]:
    """Acquire exclusive sidecar lock on *path*, yield the path.

    Uses a .{name}.lock sidecar file with fcntl.flock (not the data file).
    On platforms without fcntl, degrades to unlocked with a one-time warning.
    Guards against same-process reentrant acquisition via thread-local held-set.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not _FLOCK_AVAILABLE:
        global _flock_warned
        if not _flock_warned:
            logger.warning("fcntl unavailable; JSONL writes proceed without inter-process lock")
            _flock_warned = True
        # Fallback: threading.Lock for same-process safety + reentrant guard
        _assert_not_reentrant(target)
        fallback_lock = _get_fallback_lock(str(target.resolve()))
        fallback_lock.acquire()
        try:
            yield target
        finally:
            fallback_lock.release()
            _release_reentrant(target)
        return
    lock_path = target.with_name(f".{target.name}.lock")
    with lock_path.open("a+", encoding="utf-8") as lh:
        fcntl.flock(lh.fileno(), fcntl.LOCK_EX)
        _assert_not_reentrant(target)
        try:
            yield target
        finally:
            _release_reentrant(target)
            fcntl.flock(lh.fileno(), fcntl.LOCK_UN)


def append_jsonl_locked(
    path: Path,
    record: dict[str, Any],
    *,
    ensure_parent: bool = True,
    durable: bool = True,
) -> None:
    """Append one JSONL record under sidecar lock.

    Contract: the serialized record is written in a single handle.write() call.
    """
    line = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
    with locked_jsonl_file(path) as target:
        with target.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            if durable:
                os.fsync(handle.fileno())


def append_jsonl_lines_locked(
    path: Path,
    records: list[dict[str, Any]],
    *,
    ensure_parent: bool = True,
    durable: bool = True,
) -> None:
    """Append multiple JSONL records under one lock acquisition.

    All records are joined and written in a single handle.write() call.
    """
    if not records:
        return
    blob = "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in records) + "\n"
    with locked_jsonl_file(path) as target:
        with target.open("a", encoding="utf-8") as handle:
            handle.write(blob)
            handle.flush()
            if durable:
                os.fsync(handle.fileno())


def write_jsonl_atomic_locked(
    path: Path,
    records: list[dict[str, Any]],
    *,
    ensure_parent: bool = True,
) -> None:
    """Atomically replace a JSONL file under sidecar lock.

    Writes to a temp file in the same directory, then os.replace() under lock.
    """
    target = Path(path)
    if ensure_parent:
        target.parent.mkdir(parents=True, exist_ok=True)
    blob = "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in records) + "\n"
    with locked_jsonl_file(target) as _lock_target:
        tmp_path = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        tmp_path.write_text(blob, encoding="utf-8")
        os.replace(tmp_path, target)
