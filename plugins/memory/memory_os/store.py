"""Filesystem canonical store for Memory-OS."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from typing import Any

from .audit import append_audit
from .jsonl_io import append_jsonl_locked
from .roots import MemoryOSRoots
from .schema import EventEnvelope


class StoreError(ValueError):
    """Raised when a store operation would break storage boundaries."""


def _reject_path_name(name: str, *, field_name: str) -> None:
    if not name or "/" in name or "\\" in name or ".." in Path(name).parts:
        raise StoreError(f"Invalid {field_name}: {name}")


def _event_path(events_root: Path, ts: str) -> Path:
    parsed = datetime.fromisoformat(ts)
    month = f"{parsed.year:04d}-{parsed.month:02d}"
    day = f"{parsed.year:04d}-{parsed.month:02d}-{parsed.day:02d}.jsonl"
    return events_root / month / day


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
    try:
        tmp_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def _format_frontmatter(frontmatter: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in frontmatter.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {item}")
        elif isinstance(value, dict):
            lines.append(f"{key}: {json.dumps(value, ensure_ascii=False, sort_keys=True)}")
        elif isinstance(value, bool):
            lines.append(f"{key}: {str(value).lower()}")
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines)


class MemoryOSStore:
    """Canonical filesystem store.

    SQLite and external adapters are intentionally outside this class. This
    store is the source of truth for Slice 0-3.
    """

    def __init__(self, roots: MemoryOSRoots) -> None:
        self.roots = roots

    def initialize(self) -> None:
        directories = (
            self.roots.memory_os_root,
            self.roots.events_root,
            self.roots.working_root,
            self.roots.crystallized_root,
            self.roots.identity_manifest_path.parent,
            self.roots.relationships_root,
            self.roots.index_path.parent,
            self.roots.audit_path.parent,
            self.roots.imports_root,
            self.roots.quarantine_root,
        )
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)

    def append_event(self, event: EventEnvelope) -> Path:
        path = _event_path(self.roots.events_root, event.ts)
        append_jsonl_locked(path, event.to_dict(), durable=True)
        append_audit(
            self.roots.audit_path,
            action="append_event",
            status="ok",
            target=str(path),
            details={"event_id": event.id},
        )
        return path

    def read_events(self) -> list[EventEnvelope]:
        events: list[EventEnvelope] = []
        for path in sorted(self.roots.events_root.glob("*/*.jsonl")):
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if not line.strip():
                    continue
                try:
                    events.append(EventEnvelope.from_dict(json.loads(line)))
                except Exception as exc:
                    self._quarantine_malformed_event(path, line_number, line, str(exc))
        return events

    def write_working_document(self, name: str, document: dict[str, Any], *, audit: bool = True) -> Path:
        _reject_path_name(name, field_name="working document name")
        path = self.roots.working_root / f"{name}.json"
        _atomic_write_json(path, document)
        if audit:
            append_audit(
                self.roots.audit_path,
                action="write_working_document",
                status="ok",
                target=str(path),
                details={"name": name},
            )
        return path

    def read_working_document(self, name: str) -> dict[str, Any]:
        _reject_path_name(name, field_name="working document name")
        path = self.roots.working_root / f"{name}.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def append_crystallized_record(self, file_name: str, frontmatter: dict[str, Any], body: str) -> Path:
        _reject_path_name(file_name, field_name="crystallized file name")
        if not file_name.endswith(".md"):
            raise StoreError(f"Crystallized file must be markdown: {file_name}")
        path = self.roots.crystallized_root / file_name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(_format_frontmatter(frontmatter))
            handle.write("\n\n")
            handle.write(body.rstrip())
            handle.write("\n\n")
        append_audit(
            self.roots.audit_path,
            action="append_crystallized_record",
            status="ok",
            target=str(path),
            details={"record_id": frontmatter.get("id", "")},
        )
        return path

    def _quarantine_malformed_event(self, source_path: Path, line_number: int, line: str, error: str) -> None:
        quarantine_path = self.roots.quarantine_root / "malformed_events.jsonl"
        quarantine_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "source_path": str(source_path),
            "line_number": line_number,
            "line": line,
            "error": error,
        }
        append_jsonl_locked(quarantine_path, record, durable=True)
        append_audit(
            self.roots.audit_path,
            action="quarantine_malformed_event",
            status="warning",
            target=str(source_path),
            details={"line_number": line_number, "error": error},
        )
