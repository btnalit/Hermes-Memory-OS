"""
Community snapshot builder for Sannai's DynamicStateOverlay.

Injects community context into Sannai's state overlay so she
naturally knows who's around, who's been talking, and what's new.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json

SNAPSHOT_SCHEMA_VERSION = "memory-os.community.snapshot.v1"


def build_community_snapshot(
    community_root: Path,
    *,
    max_active: int = 5,
) -> dict[str, Any]:
    """Build a community status snapshot for Sannai's overlay.

    Returns a dict that can be injected into Sannai's DynamicStateOverlay
    as the 'community_snapshot' section.
    """
    roster_path = community_root / "roster.jsonl"
    if not roster_path.exists():
        return _empty_snapshot("no_roster")

    active_partners: list[dict[str, Any]] = []
    try:
        for line in roster_path.read_text(encoding="utf-8").strip().splitlines():
            if not line.strip():
                continue
            data = json.loads(line)
            if data.get("status") == "active":
                active_partners.append({
                    "id": data.get("id", ""),
                    "name": data.get("name", ""),
                    "relationship": data.get("relationship", "acquaintance"),
                    "tags": data.get("tags", []),
                })
    except (json.JSONDecodeError, OSError):
        return _empty_snapshot("roster_error")

    # Build recent interactions from shared memory
    recent_interactions: list[str] = []
    shared_dir = community_root / "shared"
    if shared_dir.exists():
        for f in sorted(shared_dir.glob("*.jsonl")):
            try:
                lines = f.read_text(encoding="utf-8").strip().splitlines()
                for line in lines[-3:]:  # Last 3 entries per file
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    if data.get("summary"):
                        partner_name = ""
                        pid = data.get("partner_id", "")
                        for p in active_partners:
                            if p["id"] == pid:
                                partner_name = p["name"]
                                break
                        prefix = f"{partner_name} — " if partner_name else ""
                        recent_interactions.append(f"{prefix}{data['summary'][:60]}")
            except (json.JSONDecodeError, OSError):
                continue

    # Check for new partners (not yet greeted)
    new_partners: list[str] = []
    for p in active_partners:
        greeting_file = community_root / "shared" / f"greeting_{p['id']}.flag"
        if not greeting_file.exists():
            new_partners.append(p["name"])

    # Check for unread messages
    unread_count = 0
    inbox_dir = Path("/vol1/.hermes/messages/agents/sannai/inbox")
    if inbox_dir.exists():
        try:
            for f in inbox_dir.iterdir():
                if f.suffix == ".json":
                    try:
                        data = json.loads(f.read_text())
                        if not data.get("read", False):
                            unread_count += 1
                    except (json.JSONDecodeError, OSError):
                        continue
        except OSError:
            pass

    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "active_partners": [p["name"] for p in active_partners[:max_active]],
        "partner_count": len(active_partners),
        "recent_interactions": recent_interactions[-5:],
        "unread_messages": unread_count,
        "new_partners_pending_greeting": new_partners,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _empty_snapshot(reason: str) -> dict[str, Any]:
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "active_partners": [],
        "partner_count": 0,
        "recent_interactions": [],
        "unread_messages": 0,
        "new_partners_pending_greeting": [],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": f"empty: {reason}",
    }