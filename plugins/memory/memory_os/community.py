"""
Community roster management for Hermes Community.

Defines the roster schema, validation, and CRUD operations for
partner agents in Sannai's community.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json

ROSTER_SCHEMA_VERSION = "memory-os.community.roster.v1"


@dataclass
class RosterEntry:
    """An entry in the community roster."""

    id: str
    name: str
    type: str = "agent"
    backend: str = ""
    channel: str = ""
    introduced_by: str = "owner"
    relationship: str = "acquaintance"
    known_since: str = ""
    tags: list[str] = field(default_factory=list)
    status: str = "active"
    charter: str = ""
    lifecycle: str = "open-ended"
    token_budget_weekly: int = 200000

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": ROSTER_SCHEMA_VERSION,
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "backend": self.backend,
            "channel": self.channel,
            "introduced_by": self.introduced_by,
            "relationship": self.relationship,
            "known_since": self.known_since,
            "tags": self.tags,
            "status": self.status,
            "charter": self.charter,
            "lifecycle": self.lifecycle,
            "token_budget_weekly": self.token_budget_weekly,
        }


def validate_roster(path: Path) -> list[str]:
    """Validate a roster JSONL file. Returns list of errors."""
    errors: list[str] = []
    if not path.exists():
        errors.append("roster file not found")
        return errors

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    seen_ids: set[str] = set()
    for i, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            import json
            entry = json.loads(line)
        except json.JSONDecodeError as e:
            errors.append(f"line {i}: invalid JSON: {e}")
            continue

        entry_id = entry.get("id", "")
        if not entry_id:
            errors.append(f"line {i}: missing id")
        elif entry_id in seen_ids:
            errors.append(f"line {i}: duplicate id: {entry_id}")
        else:
            seen_ids.add(entry_id)

        if not entry.get("name"):
            errors.append(f"line {i}: missing name")

        if entry.get("status") not in ("active", "dormant", "retired"):
            errors.append(f"line {i}: invalid status: {entry.get('status')}")

    return errors


def add_to_roster(path: Path, entry: RosterEntry) -> list[str]:
    """Add a new entry to the roster. Returns validation errors."""
    import json
    errors = validate_roster(path) if path.exists() else []

    # Check for duplicate id
    if path.exists():
        for line in path.read_text(encoding="utf-8").strip().splitlines():
            if not line.strip():
                continue
            try:
                existing = json.loads(line)
                if existing.get("id") == entry.id:
                    errors.append(f"duplicate id: {entry.id}")
                    return errors
            except json.JSONDecodeError:
                continue

    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")

    return errors


def get_active_roster(path: Path) -> list[RosterEntry]:
    """Get all active roster entries."""
    import json
    entries: list[RosterEntry] = []
    if not path.exists():
        return entries

    for line in path.read_text(encoding="utf-8").strip().splitlines():
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            if data.get("status") == "active":
                entries.append(RosterEntry(**{k: v for k, v in data.items() if k in RosterEntry.__dataclass_fields__}))
        except (json.JSONDecodeError, TypeError):
            continue

    return entries


def build_community_snapshot(roster_path: Path) -> dict[str, Any]:
    """Build a community snapshot for Sannai's DynamicStateOverlay."""
    active = get_active_roster(roster_path)
    return {
        "schema_version": ROSTER_SCHEMA_VERSION,
        "active_partners": [e.name for e in active],
        "partner_count": len(active),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }