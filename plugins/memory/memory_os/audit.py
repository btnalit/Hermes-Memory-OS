"""Append-only audit helpers for Memory-OS."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .ids import new_audit_id


def append_audit(
    audit_path: Path,
    *,
    action: str,
    status: str,
    target: str,
    details: dict[str, Any] | None = None,
) -> None:
    audit_path.parent.mkdir(parents=True, exist_ok=True)
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
    with audit_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
        handle.write("\n")


def read_audit_entries(audit_path: Path) -> list[dict[str, Any]]:
    if not audit_path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in audit_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            entries.append(
                {
                    "schema_version": "memory-os.audit.v0",
                    "id": "",
                    "ts": "",
                    "action": "malformed_audit_entry",
                    "status": "warning",
                    "target": str(audit_path),
                    "details": {"line": line},
                }
            )
            continue
        if isinstance(parsed, dict):
            entries.append(parsed)
    return entries


def last_audit_age_seconds(audit_path: Path, *, now: datetime | None = None) -> float | None:
    entries = [entry for entry in read_audit_entries(audit_path) if entry.get("ts")]
    if not entries:
        return None
    latest = max(datetime.fromisoformat(str(entry["ts"])) for entry in entries)
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return max(0.0, (current - latest.astimezone(timezone.utc)).total_seconds())
