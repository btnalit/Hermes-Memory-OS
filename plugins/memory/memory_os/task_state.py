"""Shared read-only projections for append-only foreground task anchors."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .roots import MemoryOSRoots


def active_task_anchor_path(roots: MemoryOSRoots):
    """Return the canonical append-only task-anchor journal path."""

    return roots.memory_os_root / "system" / "active_task_anchor.jsonl"


def read_effective_current_task(
    roots: MemoryOSRoots,
    *,
    profile: str = "",
    max_age_hours: int = 0,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Project the latest effective foreground task without mutating state.

    The journal is append-only. After profile filtering, the latest valid JSON
    object is authoritative: only ``status=active`` projects a task. Terminal
    and unknown statuses fail closed so an older active row cannot become a
    zombie after a lifecycle tombstone.
    """

    path = active_task_anchor_path(roots)
    if not path.exists():
        return None
    target_profile = str(profile or roots.profile or "default").strip() or "default"
    latest: tuple[int, dict[str, Any]] | None = None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for revision, raw in enumerate(lines, start=1):
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        record_profile = str(record.get("profile") or roots.profile or "default").strip() or "default"
        if record_profile != target_profile:
            continue
        latest = (revision, record)
    if latest is None:
        return None
    revision, record = latest
    if str(record.get("status") or "").strip().lower() != "active":
        return None
    anchor = str(record.get("anchor") or "").strip()
    if not anchor:
        return None

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    source_at = str(record.get("updated_at") or record.get("created_at") or "").strip()
    if max_age_hours > 0:
        source_time = _parse_timestamp(source_at)
        if source_time is None:
            return None
        if (current - source_time).total_seconds() > max_age_hours * 3600:
            return None

    projected = dict(record)
    projected["revision"] = revision
    projected["source_at"] = source_at
    projected["observed_at"] = current.isoformat().replace("+00:00", "Z")
    return projected


def _parse_timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
