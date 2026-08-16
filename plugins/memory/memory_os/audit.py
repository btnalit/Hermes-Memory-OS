"""Append-only audit helpers for Memory-OS."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .ids import new_audit_id
from .jsonl_io import append_jsonl_locked
from .timeutil import ensure_utc_aware


def _audit_monthly_path(base_audit_path: Path) -> Path:
    """Return the monthly-sharded audit path for the current UTC month.

    Legacy write_audit.jsonl stays read-only; new records go to
    write_audit.{YYYYMM}.jsonl so the file does not grow unbounded.
    """
    month = datetime.now(timezone.utc).strftime("%Y%m")
    return base_audit_path.parent / f"{base_audit_path.stem}.{month}.jsonl"


def append_audit(
    audit_path: Path,
    *,
    action: str,
    status: str,
    target: str,
    details: dict[str, Any] | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    record = {
        "schema_version": "memory-os.audit.v0",
        "id": new_audit_id(now),
        "ts": now.isoformat(),
        "action": action,
        "status": status,
        "target": target,
        "details": details or {},
    }
    append_jsonl_locked(_audit_monthly_path(audit_path), record, durable=True)


def read_audit_records(audit_path: Path) -> list[dict[str, Any]]:
    """Read all audit records from legacy + monthly shards.

    Always globs for {stem}*.jsonl so that records written to monthly shards
    (e.g. write_audit.202607.jsonl) are visible alongside the legacy
    monolithic file (write_audit.jsonl).

    Records are returned in chronological order (sorted by ``ts``).
    Consumers that use positional access (``[-N:]``) therefore receive
    the *N* most recent records rather than an arbitrary file-order tail.
    """
    audit_dir = audit_path.parent
    if not audit_dir.exists():
        return []
    stem = audit_path.stem
    records: list[dict[str, Any]] = []
    for path in sorted(audit_dir.glob(f"{stem}*.jsonl")):
        if path.stat().st_size == 0:
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                records.append({
                    "schema_version": "memory-os.audit.v0",
                    "id": "",
                    "ts": "",
                    "action": "malformed_audit_entry",
                    "status": "warning",
                    "target": str(path),
                    "details": {"line": line},
                })
                continue
            if isinstance(parsed, dict):
                records.append(parsed)
    records.sort(key=lambda r: str(r.get("ts") or ""))
    return records


def read_audit_entries(audit_path: Path) -> list[dict[str, Any]]:
    """Read audit entries (backward-compatible wrapper)."""
    return read_audit_records(audit_path)


def last_audit_age_seconds(audit_path: Path, *, now: datetime | None = None) -> float | None:
    entries = [entry for entry in read_audit_records(audit_path) if entry.get("ts")]
    if not entries:
        return None
    # A malformed `ts` string raises ValueError, and a mix of naive and
    # aware `ts` values across entries raises TypeError inside max() (the
    # bare comparison between two datetimes of differing awareness). Parse
    # each entry individually, normalizing a naive value to UTC same as
    # knob_overrides._is_expired, and skip entries that fail to parse at
    # all rather than letting one malformed record crash the CLI status
    # report for every entry.
    parsed_ts: list[datetime] = []
    for entry in entries:
        try:
            ts = datetime.fromisoformat(str(entry["ts"]))
        except (ValueError, TypeError):
            continue
        ts = ensure_utc_aware(ts)
        parsed_ts.append(ts)
    if not parsed_ts:
        return None
    latest = max(parsed_ts)
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return max(0.0, (current - latest.astimezone(timezone.utc)).total_seconds())
