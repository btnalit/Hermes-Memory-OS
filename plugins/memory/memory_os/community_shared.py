"""Governed shared-experience projection for Hermes Community."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .community import validate_partner_id
from .jsonl_io import append_jsonl_locked, read_jsonl

SHARED_MEMORY_SCHEMA_VERSION = "memory-os.community.shared_memory.v1"


@dataclass
class SharedMemoryEntry:
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
    actor: str = "",
    sannai_feeling: str = "",
    partner_feeling: str = "",
    thread: str = "open",
    source: str = "conversation",
) -> SharedMemoryEntry:
    """Append Sannai's bounded shared-experience summary.

    This projection is not mature memory and cannot be written by partners.
    """

    if actor != "sannai":
        raise PermissionError("only sannai may write shared memory")
    validate_partner_id(partner_id)
    if not str(summary or "").strip():
        raise ValueError("summary is required")
    if thread not in {"open", "closed"}:
        raise ValueError("invalid thread state")
    entry = SharedMemoryEntry(
        ts=datetime.now(timezone.utc).isoformat(),
        summary=str(summary).strip()[:1000],
        sannai_feeling=str(sannai_feeling).strip()[:120],
        partner_feeling=str(partner_feeling).strip()[:120],
        thread=thread,
        partner_id=partner_id,
        source=str(source or "conversation")[:64],
    )
    target = Path(community_root) / "shared" / f"sannai__{partner_id}.jsonl"
    append_jsonl_locked(target, entry.to_dict(), durable=True)
    return entry


def _entries(path: Path, *, limit: int | None = None) -> list[SharedMemoryEntry]:
    rows = read_jsonl(path)
    if limit is not None:
        rows = rows[-max(0, limit):]
    entries: list[SharedMemoryEntry] = []
    for row in rows:
        try:
            entries.append(
                SharedMemoryEntry(**{
                    key: value
                    for key, value in row.items()
                    if key in SharedMemoryEntry.__dataclass_fields__
                })
            )
        except (TypeError, ValueError):
            continue
    return entries


def read_shared_memory(
    community_root: Path,
    partner_id: str,
    *,
    limit: int = 10,
) -> list[SharedMemoryEntry]:
    validate_partner_id(partner_id)
    target = Path(community_root) / "shared" / f"sannai__{partner_id}.jsonl"
    return _entries(target, limit=limit)


def get_open_threads(community_root: Path, partner_id: str) -> list[SharedMemoryEntry]:
    return [entry for entry in read_shared_memory(community_root, partner_id, limit=100) if entry.thread == "open"]


def get_community_newspaper(
    community_root: Path,
    *,
    limit: int = 5,
) -> list[SharedMemoryEntry]:
    target = Path(community_root) / "shared" / "newspaper.jsonl"
    entries = [entry for entry in _entries(target) if entry.source == "newspaper"]
    entries.sort(key=lambda entry: entry.ts, reverse=True)
    return entries[:limit]


def write_newspaper_entry(
    community_root: Path,
    summary: str,
    *,
    actor: str = "",
) -> SharedMemoryEntry:
    if actor not in {"info_collect", "hermes_owner_delegate"}:
        raise PermissionError("actor is not authorized to write newspaper")
    if not str(summary or "").strip():
        raise ValueError("summary is required")
    entry = SharedMemoryEntry(
        ts=datetime.now(timezone.utc).isoformat(),
        summary=str(summary).strip()[:1000],
        source="newspaper",
        thread="closed",
        partner_id="__newspaper__",
    )
    target = Path(community_root) / "shared" / "newspaper.jsonl"
    append_jsonl_locked(target, entry.to_dict(), durable=True)
    return entry
