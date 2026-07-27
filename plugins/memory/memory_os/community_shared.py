"""
Shared memory area for Hermes Community.

Stores shared experiences between Sannai and her partners.
Append-only, Sannai writes summaries, partners can read.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json

SHARED_MEMORY_SCHEMA_VERSION = "memory-os.community.shared_memory.v1"


@dataclass
class SharedMemoryEntry:
    """A single entry in the shared memory area."""

    ts: str = ""
    summary: str = ""
    sannai_feeling: str = ""
    partner_feeling: str = ""
    thread: str = "open"
    partner_id: str = ""
    source: str = "conversation"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SHARED_MEMORY_SCHEMA_VERSION,
            "ts": self.ts or datetime.now(timezone.utc).isoformat(),
            "summary": self.summary,
            "sannai_feeling": self.sannai_feeling,
            "partner_feeling": self.partner_feeling,
            "thread": self.thread,
            "partner_id": self.partner_id,
            "source": self.source,
        }


def write_shared_memory(
    community_root: Path,
    partner_id: str,
    summary: str,
    *,
    sannai_feeling: str = "",
    partner_feeling: str = "",
    thread: str = "open",
    source: str = "conversation",
) -> SharedMemoryEntry:
    """Write a shared memory entry (Sannai writes, partners read)."""
    entry = SharedMemoryEntry(
        ts=datetime.now(timezone.utc).isoformat(),
        summary=summary,
        sannai_feeling=sannai_feeling,
        partner_feeling=partner_feeling,
        thread=thread,
        partner_id=partner_id,
        source=source,
    )

    shared_dir = community_root / "shared"
    shared_dir.mkdir(parents=True, exist_ok=True)
    shared_file = shared_dir / f"sannai__{partner_id}.jsonl"

    with open(shared_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")

    return entry


def read_shared_memory(
    community_root: Path,
    partner_id: str,
    *,
    limit: int = 10,
) -> list[SharedMemoryEntry]:
    """Read recent shared memory entries for a partner."""
    shared_file = community_root / "shared" / f"sannai__{partner_id}.jsonl"
    entries: list[SharedMemoryEntry] = []

    if not shared_file.exists():
        return entries

    lines = shared_file.read_text(encoding="utf-8").strip().splitlines()
    for line in lines[-limit:]:
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            # Filter to only dataclass fields
            valid_fields = {k: v for k, v in data.items() if k in SharedMemoryEntry.__dataclass_fields__}
            entries.append(SharedMemoryEntry(**valid_fields))
        except (json.JSONDecodeError, TypeError):
            continue

    return entries


def get_open_threads(
    community_root: Path,
    partner_id: str,
) -> list[SharedMemoryEntry]:
    """Get all open threads for a partner."""
    return [e for e in read_shared_memory(community_root, partner_id, limit=100) if e.thread == "open"]


def get_community_newspaper(
    community_root: Path,
    *,
    limit: int = 5,
) -> list[SharedMemoryEntry]:
    """Get the latest community newspaper entries."""
    shared_dir = community_root / "shared"
    all_entries: list[SharedMemoryEntry] = []

    if not shared_dir.exists():
        return all_entries

    for f in sorted(shared_dir.glob("*.jsonl")):
        entries = []
        for line in f.read_text(encoding="utf-8").strip().splitlines():
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                if data.get("source") == "newspaper":
                    valid_fields = {k: v for k, v in data.items() if k in SharedMemoryEntry.__dataclass_fields__}
                    entries.append(SharedMemoryEntry(**valid_fields))
            except (json.JSONDecodeError, TypeError):
                continue
        all_entries.extend(entries[-limit:])

    # Sort by timestamp, newest first
    all_entries.sort(key=lambda e: e.ts, reverse=True)
    return all_entries[:limit]


def write_newspaper_entry(
    community_root: Path,
    summary: str,
    *,
    source: str = "newspaper",
) -> SharedMemoryEntry:
    """Write a community newspaper entry (from info-collect or external source)."""
    entry = SharedMemoryEntry(
        ts=datetime.now(timezone.utc).isoformat(),
        summary=summary,
        source=source,
        thread="closed",
        partner_id="__newspaper__",
    )

    shared_dir = community_root / "shared"
    shared_dir.mkdir(parents=True, exist_ok=True)
    newspaper_file = shared_dir / "newspaper.jsonl"

    with open(newspaper_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")

    return entry