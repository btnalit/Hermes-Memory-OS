"""Rebuildable SQLite index for Memory-OS filesystem records."""

from __future__ import annotations

import json
import hashlib
import os
import sqlite3
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .audit import append_audit
from .crystallized import read_candidate_queue
from .roots import MemoryOSRoots
from .store import MemoryOSStore


_CHECKPOINT_BUSY_FULL_THRESHOLD = 3
_WAL_TRUNCATE_THRESHOLD_BYTES = 100 * 1024 * 1024


class MemoryOSIndex:
    """SQLite index for status/search.

    The filesystem store remains the source of truth. This index can be
    deleted and rebuilt from the store at any time.
    """

    def __init__(self, roots: MemoryOSRoots) -> None:
        self.roots = roots

    def rebuild_from_store(self, store: MemoryOSStore) -> None:
        self.roots.index_path.parent.mkdir(parents=True, exist_ok=True)
        staging_path = self.roots.index_path.with_name(f"{self.roots.index_path.name}.rebuild.db")
        _remove_index_file(staging_path)
        success = False
        conn = sqlite3.connect(staging_path)
        try:
            _initialize_schema(conn)
            _clear(conn)
            _index_events(conn, store)
            _update_event_source_state(conn, store)
            _index_working_items(conn, self.roots.working_root)
            _index_crystallized_candidates(conn, self.roots)
            _index_crystallized_records(conn, self.roots.crystallized_root)
            _index_audit_entries(conn, self.roots.audit_path)
            conn.commit()
            _checkpoint_wal(conn)
            conn.commit()
            success = True
        finally:
            conn.close()
            if not success:
                _remove_index_file(staging_path)
        _checkpoint_live_index(self.roots.index_path)
        _remove_sqlite_sidecars(self.roots.index_path)
        os.replace(staging_path, self.roots.index_path)
        _remove_sqlite_sidecars(staging_path)
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

    def sync_from_store(self, store: MemoryOSStore) -> dict[str, int]:
        """Idempotently catch the derived index up to canonical store records."""
        self.roots.index_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.roots.index_path)
        try:
            _initialize_schema(conn)
            _index_events(conn, store)
            _update_event_source_state(conn, store)
            _clear_table(conn, "working_items")
            _index_working_items(conn, self.roots.working_root)
            _clear_table(conn, "crystallized_candidates")
            _index_crystallized_candidates(conn, self.roots)
            _clear_table(conn, "crystallized_records")
            _index_crystallized_records(conn, self.roots.crystallized_root)
            _clear_table(conn, "audit_entries")
            _index_audit_entries(conn, self.roots.audit_path)
            conn.commit()
            _checkpoint_wal(conn)
            conn.commit()
            return self.counts()
        finally:
            conn.close()

    def counts(self) -> dict[str, int]:
        if not self.roots.index_path.exists():
            return {
                "events": 0,
                "working_items": 0,
                "crystallized_candidates": 0,
                "crystallized_records": 0,
                "audit_entries": 0,
            }
        conn = sqlite3.connect(self.roots.index_path)
        try:
            return {
                table: conn.execute(f"select count(*) from {table}").fetchone()[0]
                for table in ("events", "working_items", "crystallized_candidates", "crystallized_records", "audit_entries")
            }
        finally:
            conn.close()

    def search(self, query: str, *, limit: int = 5) -> dict[str, Any]:
        if not self.roots.index_path.exists():
            return {"mode": "missing", "tokenizer": "", "hits": []}
        conn = sqlite3.connect(self.roots.index_path)
        conn.row_factory = sqlite3.Row
        try:
            _initialize_schema(conn)
            tokenizer = _metadata_value(conn, "fts_tokenizer") or "unknown"
            hits = _fts_hits(conn, query, limit=limit)
            if not hits:
                hits = _like_hits(conn, query, limit=limit)
            return {"mode": "indexed", "tokenizer": tokenizer, "hits": hits}
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
        create table if not exists index_metadata (
            key text primary key,
            value text not null
        );
        create table if not exists index_source_state (
            source_path text primary key,
            source_kind text not null,
            source_size integer not null,
            source_mtime_ns integer not null,
            indexed_line_count integer not null,
            first_record_id text not null,
            last_record_id text not null,
            last_indexed_at text not null
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
        create table if not exists crystallized_candidates (
            candidate_id text primary key,
            kind text not null,
            body text not null,
            source_event_ids_json text not null,
            tags_json text not null,
            sensitivity text not null,
            bridge_state text not null
        );
        create table if not exists audit_entries (
            id text primary key,
            ts text not null,
            action text not null,
            status text not null,
            target text not null,
            details_json text not null
        );
        create table if not exists memory_embeddings (
            record_type text not null,
            record_id text not null,
            embedding_model text not null,
            embedding blob not null,
            created_at text not null,
            primary key (record_type, record_id, embedding_model)
        );
        create table if not exists memory_edges (
            edge_id text primary key,
            from_record_type text not null,
            from_record_id text not null,
            to_record_type text not null,
            to_record_id text not null,
            relation_type text not null,
            weight real not null,
            created_at text not null,
            source_event_id text
        );
        """
    )
    _ensure_column(conn, "events", "record_hash", "text not null default ''")
    _ensure_fts(conn)


def _ensure_fts(conn: sqlite3.Connection) -> None:
    existing = _metadata_value(conn, "fts_tokenizer")
    if existing:
        return
    try:
        conn.execute(
            """
            create virtual table if not exists memory_fts
            using fts5(record_type unindexed, record_id unindexed, title, text, tokenize='trigram')
            """
        )
        tokenizer = "trigram"
    except sqlite3.Error:
        conn.execute(
            """
            create virtual table if not exists memory_fts
            using fts5(record_type unindexed, record_id unindexed, title, text, tokenize='unicode61')
            """
        )
        tokenizer = "unicode61"
    conn.execute(
        "insert or replace into index_metadata (key, value) values (?, ?)",
        ("fts_tokenizer", tokenizer),
    )


def _metadata_value(conn: sqlite3.Connection, key: str) -> str:
    try:
        row = conn.execute("select value from index_metadata where key = ?", (key,)).fetchone()
    except sqlite3.Error:
        return ""
    return "" if row is None else str(row[0])


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {str(row[1]) for row in conn.execute(f"pragma table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"alter table {table} add column {column} {definition}")


def _set_metadata(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "insert or replace into index_metadata (key, value) values (?, ?)",
        (key, value),
    )


def _checkpoint_wal(conn: sqlite3.Connection) -> None:
    try:
        mode = "PASSIVE"
        busy = _run_checkpoint(conn, "PASSIVE")
        busy_count = int(_metadata_value(conn, "checkpoint_busy_count") or "0")
        if busy:
            busy_count += 1
        else:
            busy_count = 0
        if busy_count >= _CHECKPOINT_BUSY_FULL_THRESHOLD:
            _run_checkpoint(conn, "FULL")
            mode = "FULL"
            busy_count = 0
        db_path = _database_path(conn)
        if _wal_file_size_bytes(db_path) > _WAL_TRUNCATE_THRESHOLD_BYTES:
            _run_checkpoint(conn, "TRUNCATE")
            mode = "TRUNCATE"
            busy_count = 0
        _set_metadata(conn, "checkpoint_busy_count", str(busy_count))
        _set_metadata(conn, "last_checkpoint_mode", mode)
    except sqlite3.Error as exc:
        _set_metadata(conn, "last_checkpoint_mode", "FAILED")
        _set_metadata(conn, "last_checkpoint_error", str(exc))


def _run_checkpoint(conn: sqlite3.Connection, mode: str) -> bool:
    row = conn.execute(f"pragma wal_checkpoint({mode})").fetchone()
    return bool(row and int(row[0]) > 0)


def _database_path(conn: sqlite3.Connection) -> Path:
    for _, name, path in conn.execute("pragma database_list").fetchall():
        if name == "main":
            return Path(path)
    return Path("")


def _wal_file_size_bytes(path: Path) -> int:
    wal_path = Path(f"{path}-wal")
    if not wal_path.exists():
        return 0
    return wal_path.stat().st_size


def _checkpoint_live_index(path: Path) -> None:
    if not path.exists():
        return
    conn = sqlite3.connect(path)
    try:
        try:
            conn.execute("pragma wal_checkpoint(TRUNCATE)").fetchone()
        except sqlite3.Error:
            pass
    finally:
        conn.close()


def _remove_index_file(path: Path) -> None:
    if path.exists():
        path.unlink()
    _remove_sqlite_sidecars(path)


def _remove_sqlite_sidecars(path: Path) -> None:
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{path}{suffix}")
        if sidecar.exists():
            sidecar.unlink()


def _clear(conn: sqlite3.Connection) -> None:
    for table in ("events", "working_items", "crystallized_candidates", "crystallized_records", "audit_entries"):
        _clear_table(conn, table)


def _clear_table(conn: sqlite3.Connection, table: str) -> None:
    conn.execute(f"delete from {table}")


def _index_events(conn: sqlite3.Connection, store: MemoryOSStore) -> None:
    for event in store.read_events():
        conn.execute(
            """
            insert or replace into events
            (id, ts, profile, source, kind, summary, promotion_state, sensitivity, record_hash)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                _event_hash(event),
            ),
        )
        _replace_fts_record(
            conn,
            record_type="event",
            record_id=event.id,
            title=f"{event.kind} {event.source}",
            text=event.summary,
        )


def _update_event_source_state(conn: sqlite3.Connection, store: MemoryOSStore) -> None:
    now = datetime.now(timezone.utc).isoformat()
    for path in sorted(store.roots.events_root.glob("*/*.jsonl")):
        ids: list[str] = []
        line_count = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            line_count += 1
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            if raw.get("id"):
                ids.append(str(raw["id"]))
        stat = path.stat()
        conn.execute(
            """
            insert or replace into index_source_state
            (source_path, source_kind, source_size, source_mtime_ns, indexed_line_count,
             first_record_id, last_record_id, last_indexed_at)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(path),
                "events_jsonl",
                stat.st_size,
                stat.st_mtime_ns,
                line_count,
                ids[0] if ids else "",
                ids[-1] if ids else "",
                now,
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
        for frontmatter, body in _markdown_records(path.read_text(encoding="utf-8")):
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
            _replace_fts_record(
                conn,
                record_type="crystallized_record",
                record_id=str(frontmatter["id"]),
                title=f"{frontmatter.get('kind', '')} {path.name} {' '.join(frontmatter.get('tags', []))}",
                text=body,
            )


def _index_crystallized_candidates(conn: sqlite3.Connection, roots: MemoryOSRoots) -> None:
    for candidate in read_candidate_queue(roots):
        conn.execute(
            """
            insert or replace into crystallized_candidates
            (candidate_id, kind, body, source_event_ids_json, tags_json, sensitivity, bridge_state)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate.candidate_id,
                candidate.kind,
                candidate.body,
                json.dumps(candidate.source_event_ids, ensure_ascii=False, sort_keys=True),
                json.dumps(candidate.tags or [], ensure_ascii=False, sort_keys=True),
                candidate.sensitivity,
                candidate.bridge_state,
            ),
        )
        _replace_fts_record(
            conn,
            record_type="crystallized_candidate",
            record_id=candidate.candidate_id,
            title=f"{candidate.kind} {' '.join(candidate.tags or [])}",
            text=candidate.body,
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


def _replace_fts_record(
    conn: sqlite3.Connection,
    *,
    record_type: str,
    record_id: str,
    title: str,
    text: str,
) -> None:
    conn.execute(
        "delete from memory_fts where record_type = ? and record_id = ?",
        (record_type, record_id),
    )
    conn.execute(
        "insert into memory_fts (record_type, record_id, title, text) values (?, ?, ?, ?)",
        (record_type, record_id, title, text),
    )


def _fts_hits(conn: sqlite3.Connection, query: str, *, limit: int) -> list[dict[str, str]]:
    if not query.strip():
        return []
    try:
        rows = conn.execute(
            """
            select record_type, record_id, title, text
            from memory_fts
            where memory_fts match ?
            limit ?
            """,
            (query, limit),
        ).fetchall()
    except sqlite3.Error:
        return []
    return [_row_to_hit(row) for row in rows]


def _like_hits(conn: sqlite3.Connection, query: str, *, limit: int) -> list[dict[str, str]]:
    if not query.strip():
        return []
    rows = conn.execute(
        """
        select record_type, record_id, title, text
        from memory_fts
        where title like ? or text like ?
        limit ?
        """,
        (f"%{query}%", f"%{query}%", limit),
    ).fetchall()
    return [_row_to_hit(row) for row in rows]


def _row_to_hit(row: sqlite3.Row) -> dict[str, str]:
    text = str(row["text"])
    return {
        "record_type": str(row["record_type"]),
        "record_id": str(row["record_id"]),
        "title": str(row["title"]),
        "snippet": text[:240],
    }


def _event_hash(event: Any) -> str:
    payload = json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _markdown_records(content: str) -> Iterable[tuple[dict[str, Any], str]]:
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
        if index >= len(lines):
            break
        index += 1
        body_lines: list[str] = []
        while index < len(lines) and lines[index].strip() != "---":
            body_lines.append(lines[index])
            index += 1
        if block:
            yield _parse_frontmatter(block), "\n".join(body_lines).strip()


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
