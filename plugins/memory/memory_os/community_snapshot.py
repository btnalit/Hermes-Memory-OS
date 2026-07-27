"""Portable community projection for Memory State Overlay."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .community import get_active_roster
from .jsonl_io import read_jsonl

SNAPSHOT_SCHEMA_VERSION = "memory-os.community.snapshot.v1"


def build_community_snapshot(
    community_root: Path,
    *,
    inbox_dir: Path | None = None,
    max_active: int = 5,
) -> dict[str, Any]:
    """Build a read-only, profile-portable community projection."""

    root = Path(community_root)
    roster_path = root / "roster.jsonl"
    if not roster_path.exists():
        return _empty_snapshot("no_roster")
    active = get_active_roster(roster_path)
    active_ids = {entry.id for entry in active}
    active_names = {entry.id: entry.name for entry in active}

    interactions: list[tuple[str, str]] = []
    shared_dir = root / "shared"
    if shared_dir.exists():
        for path in sorted(shared_dir.glob("sannai__*.jsonl")):
            for row in read_jsonl(path)[-3:]:
                partner_id = str(row.get("partner_id") or "")
                if partner_id not in active_ids:
                    continue
                timestamp = str(row.get("ts") or "")
                summary = str(row.get("summary") or "").strip()
                if summary:
                    interactions.append(
                        (timestamp, f"{active_names[partner_id]} — {summary[:120]}")
                    )
    interactions.sort(key=lambda item: item[0])

    pending_greetings = [
        entry.name
        for entry in active
        if not (shared_dir / f"greeting_{entry.id}.flag").exists()
    ]

    unread_count = 0
    if inbox_dir is not None and Path(inbox_dir).exists():
        for path in Path(inbox_dir).glob("*.json"):
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if not isinstance(row, dict):
                continue
            sender = str(row.get("from") or "")
            delivery_state = str(row.get("delivery_state") or "delivered")
            if sender in active_ids and delivery_state in {"unread", "delivered", "processed"} and not bool(row.get("read")):
                unread_count += 1

    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "status": "ok",
        "active_partners": [entry.name for entry in active[:max_active]],
        "partner_count": len(active),
        "recent_interactions": [text for _timestamp, text in interactions[-5:]],
        "unread_messages": unread_count,
        "new_partners_pending_greeting": pending_greetings,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _empty_snapshot(reason: str) -> dict[str, Any]:
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "status": f"empty: {reason}",
        "active_partners": [],
        "partner_count": 0,
        "recent_interactions": [],
        "unread_messages": 0,
        "new_partners_pending_greeting": [],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
