"""Rebuildable SQLite index for Memory-OS filesystem records."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .audit import append_audit
from .roots import MemoryOSRoots
from .store import MemoryOSStore


class MemoryOSIndex:
    """SQLite index for status/search.

    The filesystem store remains the source of truth. This index can be
    deleted and rebuilt from the store at any time.
    """

    def __init__(self, roots: MemoryOSRoots) -> None:
        self.roots = roots

    def rebuild_from_store(self, store: MemoryOSStore) -> None:
        self.roots.index_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.roots.index_path)
        try:
            _initialize_schema(conn)
            _clear(conn)
            _index_events(conn, store)
            _index_working_items(conn, self.roots.working_root)
            _index_crystallized_records(conn, self.roots.crystallized_root)
            _index_audit_entries(conn, self.roots.audit_path)
            conn.commit()
        finally:
            conn.close()
        append_audit(
            self.roots.audit_path,
            action="index_rebuild",
            status="ok",
            target=str(self.roots.index_path),
            details={},
        )

    def try_rebuild_from_store(self, store: MemoryOSStore) -> bool:
        try:
            self.rebuild_from_store(store)
        except sqlite3.Error as exc:
            append_audit(
                self.roots.audit_path,
                action="index_rebuild_failed",
                status="warning",
                target=str(self.roots.index_path),
                details={"error": str(exc)},
            )
            return False
        return True

    def counts(self) -> dict[str, int]:
        if not self.roots.index_path.exists():
            return {
                "events": 0,
                "working_items": 0,
                "crystallized_records": 0,
                "audit_entries": 0,
            }
        conn = sqlite3.connect(self.roots.index_path)
        try:
            return {
                table: conn.execute(f"select count(*) from {table}").fetchone()[0]
                for table in ("events", "working_items", "crystallized_records", "audit_entries")
            }
        finally:
            conn.close()


def _initialize_schema(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("pragma journal_mode=WAL")
    except sqlite3.DatabaseError:
        conn.execute("pragma journal_mode=DELETE")
    conn.executescript(
        """
        create table if not exists events (
            id text primary key,
            ts text not null,
            profile text not null,
            source text not null,
            kind text not null,
            summary text not null,
            promotion_state text not null,
            sensitivity text not null
        );
        create table if not exists working_items (
            id text primary key,
            kind text not null,
            status text not null,
            created_at text not null,
            updated_at text not null,
            text text not null,
            source_event_id text,
            document_name text not null,
            weight real not null,
            tags_json text not null
        );
        create table if not exists crystallized_records (
            id text primary key,
            kind text not null,
            created_at text,
            approved_by text,
            approved_at text,
            source_event_ids_json text not null,
            tags_json text not null,
            sensitivity text,
            hindsight_indexed integer not null,
            file_name text not null
        );
        create table if not exists audit_entries (
            id text primary key,
            ts text not null,
            action text not null,
            status text not null,
            target text not null,
            details_json text not null
        );
        """
    )


def _clear(conn: sqlite3.Connection) -> None:
    for table in ("events", "working_items", "crystallized_records", "audit_entries"):
        conn.execute(f"delete from {table}")


def _index_events(conn: sqlite3.Connection, store: MemoryOSStore) -> None:
    for event in store.read_events():
        conn.execute(
            """
            insert or replace into events
            (id, ts, profile, source, kind, summary, promotion_state, sensitivity)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.id,
                event.ts,
                event.profile,
                event.source,
                event.kind,
                event.summary,
                event.promotion_state,
                event.sensitivity,
            ),
        )


def _index_working_items(conn: sqlite3.Connection, working_root: Path) -> None:
    for path in sorted(working_root.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        for item in document.get("items", []):
            conn.execute(
                """
                insert or replace into working_items
                (id, kind, status, created_at, updated_at, text, source_event_id, document_name, weight, tags_json)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(item["id"]),
                    str(item["kind"]),
                    str(item["status"]),
                    str(item["created_at"]),
                    str(item["updated_at"]),
                    str(item["text"]),
                    str(item.get("source_event_id", "")),
                    path.stem,
                    float(item.get("weight", 0.0)),
                    json.dumps(item.get("tags", []), ensure_ascii=False, sort_keys=True),
                ),
            )


def _index_crystallized_records(conn: sqlite3.Connection, crystallized_root: Path) -> None:
    for path in sorted(crystallized_root.glob("*.md")):
        for frontmatter in _frontmatter_blocks(path.read_text(encoding="utf-8")):
            conn.execute(
                """
                insert or replace into crystallized_records
                (id, kind, created_at, approved_by, approved_at, source_event_ids_json, tags_json,
                 sensitivity, hindsight_indexed, file_name)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(frontmatter["id"]),
                    str(frontmatter["kind"]),
                    _optional_str(frontmatter.get("created_at")),
                    _optional_str(frontmatter.get("approved_by")),
                    _optional_str(frontmatter.get("approved_at")),
                    json.dumps(frontmatter.get("source_event_ids", []), ensure_ascii=False, sort_keys=True),
                    json.dumps(frontmatter.get("tags", []), ensure_ascii=False, sort_keys=True),
                    _optional_str(frontmatter.get("sensitivity")),
                    1 if frontmatter.get("hindsight_indexed") is True else 0,
                    path.name,
                ),
            )


def _index_audit_entries(conn: sqlite3.Connection, audit_path: Path) -> None:
    if not audit_path.exists():
        return
    for line in audit_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        conn.execute(
            """
            insert or replace into audit_entries
            (id, ts, action, status, target, details_json)
            values (?, ?, ?, ?, ?, ?)
            """,
            (
                str(entry["id"]),
                str(entry["ts"]),
                str(entry["action"]),
                str(entry["status"]),
                str(entry["target"]),
                json.dumps(entry.get("details", {}), ensure_ascii=False, sort_keys=True),
            ),
        )


def _frontmatter_blocks(content: str) -> Iterable[dict[str, Any]]:
    lines = content.splitlines()
    index = 0
    while index < len(lines):
        if lines[index].strip() != "---":
            index += 1
            continue
        index += 1
        block: list[str] = []
        while index < len(lines) and lines[index].strip() != "---":
            block.append(lines[index])
            index += 1
        if index < len(lines):
            index += 1
        if block:
            yield _parse_frontmatter(block)


def _parse_frontmatter(lines: list[str]) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    current_list_key = ""
    for line in lines:
        if line.startswith("  - ") and current_list_key:
            parsed[current_list_key].append(line[4:])
            continue
        current_list_key = ""
        if line.endswith(":"):
            key = line[:-1]
            parsed[key] = []
            current_list_key = key
            continue
        key, _, raw_value = line.partition(": ")
        if not key:
            continue
        if raw_value == "true":
            parsed[key] = True
        elif raw_value == "false":
            parsed[key] = False
        else:
            parsed[key] = raw_value
    return parsed


def _optional_str(value: object) -> str:
    return "" if value is None else str(value)
