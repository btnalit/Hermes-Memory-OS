"""Rebuildable SQLite index for Memory-OS filesystem records."""

from __future__ import annotations

import json
import hashlib
import os
import re
import sqlite3
from typing import Any

from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .audit import append_audit, read_audit_records
from .crystallized import (
    is_active_crystallized_frontmatter,
    read_candidate_queue,
    read_candidate_triage,
    resolve_candidate_effective_state,
)
from .roots import MemoryOSRoots
from .store import MemoryOSStore


_CHECKPOINT_BUSY_FULL_THRESHOLD = 3
_WAL_TRUNCATE_THRESHOLD_BYTES = 100 * 1024 * 1024
_FTS_TEXT_PROJECTION_VERSION = "memory-os.fts_projection.v1"
_PRIVATE_PROJECTION_KEY_PARTS = {
    "api_key",
    "body",
    "content",
    "cookie",
    "key",
    "password",
    "private",
    "prompt",
    "raw",
    "secret",
    "token",
    "transcript",
}


class MemoryOSIndex:
    """SQLite index for status/search.

    The filesystem store remains the source of truth. This index can be
    deleted and rebuilt from the store at any time.
    """

    def __init__(self, roots: MemoryOSRoots) -> None:
        self.roots = roots
        self._embedder: object | None = None  # set by provider before rebuild

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
            _index_crystallized_candidates(conn, self.roots, store)
            _index_crystallized_records(conn, self.roots.crystallized_root)
            # Only repopulate embeddings when the embedder is available.
            # When unavailable, copy from the live index to preserve existing
            # embeddings across rebuilds (P0.2-class guard — prevents silent
            # embedding wipe when embedder is not installed or broken).
            _embedder_available = (
                self._embedder is not None
                and getattr(self._embedder, "is_available", lambda: False)()
            )
            if _embedder_available:
                _index_embeddings(conn, self.roots.crystallized_root, self._embedder)
            elif self.roots.index_path.exists():
                _copy_embeddings_from_live(conn, self.roots.index_path)
            _index_audit_entries(conn, self.roots.audit_path)
            _index_edges(conn, self.roots)
            if _entity_index_enabled(store):
                _index_entities(conn, self.roots.crystallized_root)
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
        _atomic_replace_index(staging_path, self.roots.index_path)
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
            before = self.counts()
            _clear_table(conn, "memory_fts")  # P0.1: prevent stale FTS5 entries from accumulating
            _index_events(conn, store)
            _update_event_source_state(conn, store)
            _clear_table(conn, "working_items")
            _index_working_items(conn, self.roots.working_root)
            _clear_table(conn, "crystallized_candidates")
            _index_crystallized_candidates(conn, self.roots, store)
            _clear_table(conn, "crystallized_records")
            _index_crystallized_records(conn, self.roots.crystallized_root)
            # Only clear+repopulate embeddings when the embedder is available.
            # An embedder-less sync (e.g. cron index-sync job) must not wipe
            # embeddings that were populated by a previous embedder-aware run.
            _embedder_available = (
                self._embedder is not None
                and getattr(self._embedder, "is_available", lambda: False)()
            )
            if _embedder_available:
                _clear_table(conn, "memory_embeddings")
                _index_embeddings(conn, self.roots.crystallized_root, self._embedder)
            # Clean up orphan embedding rows for records that have been
            # deleted from crystallized_records.  Safe regardless of
            # embedder availability — only removes dangling references.
            conn.execute(
                "delete from memory_embeddings "
                "where record_type = 'crystallized_record' "
                "and record_id not in (select id from crystallized_records)"
            )
            _clear_table(conn, "audit_entries")
            _index_audit_entries(conn, self.roots.audit_path)
            _clear_table(conn, "memory_edges")
            _index_edges(conn, self.roots)
            if _entity_index_enabled(store):
                _clear_table(conn, "entity_index")
                _index_entities(conn, self.roots.crystallized_root)
            conn.commit()
            _checkpoint_wal(conn)
            conn.commit()
            after = self.counts()
            append_audit(
                self.roots.audit_path,
                action="index_sync",
                status="ok",
                target=str(self.roots.index_path),
                details={
                    "events": f"{before.get('events',0)}->{after.get('events',0)}",
                    "working_items": f"{before.get('working_items',0)}->{after.get('working_items',0)}",
                    "crystallized_candidates": f"{before.get('crystallized_candidates',0)}->{after.get('crystallized_candidates',0)}",
                    "crystallized_records": f"{before.get('crystallized_records',0)}->{after.get('crystallized_records',0)}",
                    "audit_entries": f"{before.get('audit_entries',0)}->{after.get('audit_entries',0)}",
                    "memory_edges": f"{before.get('memory_edges',0)}->{after.get('memory_edges',0)}",
                    "memory_embeddings": f"{before.get('memory_embeddings',0)}->{after.get('memory_embeddings',0)}",
                    "entity_index": f"{before.get('entity_index',0)}->{after.get('entity_index',0)}",
                },
            )
            return after
        except sqlite3.Error as exc:
            append_audit(
                self.roots.audit_path,
                action="index_sync_failed",
                status="warning",
                target=str(self.roots.index_path),
                details={"error": str(exc)},
            )
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
                "memory_edges": 0,
                "memory_embeddings": 0,
                "entity_index": 0,
            }
        conn = sqlite3.connect(self.roots.index_path)
        try:
            return {
                table: conn.execute(f"select count(*) from {table}").fetchone()[0]
                for table in ("events", "working_items", "crystallized_candidates", "crystallized_records", "audit_entries", "memory_edges", "memory_embeddings", "entity_index")
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

    def query_edges(
        self,
        anchor_ids: list[str],
        *,
        depth: int = 1,
        relation_types: list[str] | None = None,
        state: str = "active",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """根据一组 anchor node id 查询关联边(第二跳遍历)。

        契约:
        - anchor_ids 为空 → 立即返回 [] (不做全表扫描,守 G2 性能边界)
        - depth=1: 直接 IN (anchors) 查询,不做递归
        - 异常 → 返回 [] (fail-open,守 G1)
        - limit 上限避免 budget 爆炸
        """
        if not anchor_ids:
            return []
        if not self.roots.index_path.exists():
            return []
        if depth < 1:
            depth = 1
        conn = sqlite3.connect(self.roots.index_path)
        conn.row_factory = sqlite3.Row
        try:
            _initialize_schema(conn)
            return _query_edges_sqlite(conn, anchor_ids, depth=depth, relation_types=relation_types, state=state, limit=limit)
        except Exception:
            return []
        finally:
            conn.close()

    def vector_search(
        self,
        query_vec: "np.ndarray",
        *,
        record_type: str = "crystallized_record",
        limit: int = 60,
        min_score: float = 0.30,
    ) -> list[str]:
        """Vector similarity search over memory_embeddings using cosine similarity.

        Pure numpy — no LLM, no network. Caller owns embedding (pass a
        pre-computed numpy array, not raw text). Skips rows whose embedding
        shape does not match the query embedding shape (shape mismatch is
        expected when different models produce different dimensions).

        Filters by record_type in the SQL query. Returns list of record_id
        strings sorted by cosine similarity descending, capped at limit,
        filtered to cosine similarity >= min_score (default 0.30, empirically
        calibrated from cross-lingual benchmark — removes clearly-unrelated
        matches (<0.30).  This is noise reduction, not a clean separator:
        residual noise in 0.30-0.45 overlaps with low-end GT (0.37), and is
        handled by RRF ranking + result budget + cross-lane dedup.
        Empty list on any failure (fail-open).
        """
        if not self.roots.index_path.exists():
            return []
        if query_vec is None:
            return []

        import numpy as np  # lazy import — numpy is only needed for vector search

        conn = sqlite3.connect(self.roots.index_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "select record_id, embedding from memory_embeddings "
                "where record_type = ?",
                (record_type,),
            ).fetchall()

            results: list[tuple[str, float]] = []
            q_norm = float(np.linalg.norm(query_vec))
            if q_norm == 0.0:
                return []

            for row in rows:
                try:
                    vec = np.frombuffer(row["embedding"], dtype=np.float32)
                except Exception:
                    continue
                if vec.shape != query_vec.shape:
                    continue
                dot = float(np.dot(query_vec, vec))
                v_norm = float(np.linalg.norm(vec))
                if v_norm == 0.0:
                    continue
                sim = dot / (q_norm * v_norm)
                if sim >= min_score:
                    results.append((str(row["record_id"]), sim))

            results.sort(key=lambda r: r[1], reverse=True)
            return [rid for rid, _score in results[:limit]]
        except Exception:
            return []
        finally:
            conn.close()

    def write_governed_edge(
        self,
        *,
        conn: sqlite3.Connection | None = None,
        from_record_type: str,
        from_record_id: str,
        to_record_type: str,
        to_record_id: str,
        relation_type: str,
        weight: float = 1.0,
        source_event_id: str | None = None,
        proposed_by: str = "structural",
        state: str = "candidate",
    ) -> dict[str, Any]:
        """Write a governed edge to the memory_edges table.

        Instance-level wrapper over the module-level write_governed_edge().
        Follows fail-open semantics. Writes to canonical store first
        (graph/edges.jsonl), then index DB.

        When *conn* is provided the caller's connection is reused; otherwise a
        new connection is opened per call. Callers that write many edges in a
        batch should supply a shared connection to avoid per-edge schema-init
        and connection overhead.

        Returns the edge dict on success, or {} on failure.
        """
        if conn is not None:
            # Use caller-provided connection — skip schema init and
            # connection lifecycle (caller is responsible for both).
            try:
                return write_governed_edge(
                    conn,
                    self.roots,
                    from_record_type=from_record_type,
                    from_record_id=from_record_id,
                    to_record_type=to_record_type,
                    to_record_id=to_record_id,
                    relation_type=relation_type,
                    weight=weight,
                    source_event_id=source_event_id,
                    proposed_by=proposed_by,
                    state=state,
                )
            except Exception:
                return {}
        if not self.roots.index_path.exists():
            return {}
        conn = sqlite3.connect(self.roots.index_path)
        conn.row_factory = sqlite3.Row
        try:
            _initialize_schema(conn)
            return write_governed_edge(
                conn,
                self.roots,
                from_record_type=from_record_type,
                from_record_id=from_record_id,
                to_record_type=to_record_type,
                to_record_id=to_record_id,
                relation_type=relation_type,
                weight=weight,
                source_event_id=source_event_id,
                proposed_by=proposed_by,
                state=state,
            )
        except Exception:
            return {}
        finally:
            conn.close()

    def transition_edge_state(
        self,
        edge_id: str,
        new_state: str,
        *,
        now: str | None = None,
    ) -> dict[str, Any]:
        """Transition an edge's governance state.

        Instance-level wrapper over the module-level transition_edge_state().
        Opens its own SQLite connection and follows fail-open semantics.

        Returns the updated edge dict on success, or {} on failure.
        """
        if not self.roots.index_path.exists():
            return {}
        conn = sqlite3.connect(self.roots.index_path)
        conn.row_factory = sqlite3.Row
        try:
            _initialize_schema(conn)
            return transition_edge_state(conn, edge_id, new_state, now=now)
        except Exception:
            return {}
        finally:
            conn.close()

    def get_edge(self, edge_id: str) -> dict[str, Any] | None:
        """Look up a single edge by its edge_id.

        Returns the edge dict on success, None if not found, or None on error
        (fail-open — the caller treats None as "not found").
        """
        if not self.roots.index_path.exists():
            return None
        conn = sqlite3.connect(self.roots.index_path)
        conn.row_factory = sqlite3.Row
        try:
            _initialize_schema(conn)
            row = conn.execute(
                "select * from memory_edges where edge_id = ?", (edge_id,)
            ).fetchone()
            if row is None:
                return None
            col_names = [str(c[1]) for c in conn.execute("pragma table_info(memory_edges)").fetchall()]
            return dict(zip(col_names, row))
        except sqlite3.Error:
            return None
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
            bridge_state text not null,
            provenance_json text not null default '{}'
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
            weight real not null default 1.0,
            created_at text not null,
            source_event_id text,
            state text not null default 'candidate',
            invalidated_at text,
            proposed_by text not null default 'structural'
        );
        create table if not exists entity_index (
            entity_id text not null,
            entity_text text not null,
            record_id text not null,
            role text not null,
            proposed_by text not null default 'structural',
            created_at text not null,
            primary key (entity_id, record_id, role)
        );
        """
    )
    _ensure_column(conn, "events", "record_hash", "text not null default ''")
    _ensure_column(conn, "memory_edges", "state", "text not null default 'candidate'")
    _ensure_column(conn, "memory_edges", "invalidated_at", "text")
    _ensure_column(conn, "memory_edges", "proposed_by", "text not null default 'structural'")
    _ensure_column(conn, "crystallized_candidates", "provenance_json", "text not null default '{}'")
    _ensure_fts(conn)
    _set_metadata(conn, "fts_text_projection_version", _FTS_TEXT_PROJECTION_VERSION)


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


def _atomic_replace_index(src: Path, dst: Path) -> None:
    """Replace dst with src. Uses copy+unlink fallback on Windows where
    os.replace fails when other connections hold the target file open
    (P3.2 — platform compat for test/dev environments)."""
    import platform
    import shutil

    try:
        os.replace(src, dst)
    except PermissionError:
        if platform.system() == "Windows":
            shutil.copy2(str(src), str(dst))
            src.unlink()
        else:
            raise


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
    for table in ("events", "working_items", "crystallized_candidates", "crystallized_records", "audit_entries", "memory_edges", "memory_embeddings", "memory_fts"):
        _clear_table(conn, table)


def _clear_table(conn: sqlite3.Connection, table: str) -> None:
    conn.execute(f"delete from {table}")


def _copy_embeddings_from_live(staging_conn: sqlite3.Connection, live_path: Path) -> None:
    """Copy memory_embeddings from the live index into a staging DB.

    Used by rebuild_from_store to preserve embeddings across a rebuild
    when the embedder is not available (P0.2-class guard — prevents
    silent embedding wipe).
    """
    try:
        staging_conn.execute(f"ATTACH DATABASE '{live_path}' AS live")
        staging_conn.execute(
            "INSERT INTO main.memory_embeddings "
            "SELECT * FROM live.memory_embeddings"
        )
        staging_conn.execute("DETACH live")
    except sqlite3.Error:
        pass  # fail-open: live index may not exist, be locked, or be corrupt


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
            text=_event_fts_text(event),
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
            if not is_active_crystallized_frontmatter(frontmatter):
                continue
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


def _index_embeddings(
    conn: sqlite3.Connection,
    crystallized_root: Path,
    embedder: object | None,
) -> int:
    """Populate memory_embeddings from active crystallized records.

    Reads all .md files under crystallized_root, embeds body text
    via the provided embedder, and INSERT OR REPLACE into memory_embeddings.

    embedder=None or embedder.is_available()=False -> returns 0 (table unchanged).
    Returns the number of records embedded.
    """
    if embedder is None or not getattr(embedder, "is_available", lambda: False)():
        return 0
    embedding_model = getattr(embedder, "model_name", "paraphrase-multilingual-MiniLM-L12-v2")
    now = datetime.now(timezone.utc).isoformat()
    count = 0
    for path in sorted(crystallized_root.glob("*.md")):
        for frontmatter, body in _markdown_records(path.read_text(encoding="utf-8")):
            if not is_active_crystallized_frontmatter(frontmatter):
                continue
            rid = str(frontmatter.get("id", ""))
            if not rid:
                continue
            blob = embedder.embed(body)
            if not blob:
                continue
            conn.execute(
                """
                insert or replace into memory_embeddings
                (record_type, record_id, embedding_model, embedding, created_at)
                values (?, ?, ?, ?, ?)
                """,
                ("crystallized_record", rid, embedding_model, blob, now),
            )
            count += 1
    return count


def _index_crystallized_candidates(
    conn: sqlite3.Connection, roots: MemoryOSRoots, store: MemoryOSStore | None = None
) -> None:
    triage: list[dict[str, Any]] = []
    if store is not None:
        triage = read_candidate_triage(store)
    for candidate in read_candidate_queue(roots):
        effective_state = (
            resolve_candidate_effective_state(candidate, triage) if triage
            else candidate.bridge_state
        )
        conn.execute(
            """
            insert or replace into crystallized_candidates
            (candidate_id, kind, body, source_event_ids_json, tags_json, sensitivity, bridge_state, provenance_json)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate.candidate_id,
                candidate.kind,
                candidate.body,
                json.dumps(candidate.source_event_ids, ensure_ascii=False, sort_keys=True),
                json.dumps(candidate.tags or [], ensure_ascii=False, sort_keys=True),
                candidate.sensitivity,
                effective_state,
                json.dumps(candidate.provenance or {}, ensure_ascii=False, sort_keys=True),
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
    records = read_audit_records(audit_path)
    for entry in records:
        if entry.get("action") == "malformed_audit_entry":
            continue
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


def _index_edges(conn: sqlite3.Connection, roots: MemoryOSRoots) -> int:
    """Project canonical edges into memory_edges table.

    Reads graph/edges.jsonl and inserts/replaces into memory_edges.
    Edge rows with state='invalidated' are included (守 G3 invalidate-not-delete).
    Returns edge count.
    """
    edges_path = roots.memory_os_root / "graph" / "edges.jsonl"
    if not edges_path.exists():
        return 0

    count = 0
    for line in edges_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            edge = json.loads(line)
            conn.execute(
                """
                insert or replace into memory_edges (
                    edge_id, from_record_type, from_record_id,
                    to_record_type, to_record_id, relation_type,
                    weight, created_at, source_event_id,
                    state, invalidated_at, proposed_by
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(edge.get("edge_id", "")),
                    str(edge.get("from_record_type", "")),
                    str(edge.get("from_record_id", "")),
                    str(edge.get("to_record_type", "")),
                    str(edge.get("to_record_id", "")),
                    str(edge.get("relation_type", "")),
                    float(edge.get("weight", 1.0)),
                    str(edge.get("created_at", "")),
                    str(edge.get("source_event_id", "")),
                    str(edge.get("state", "candidate")),
                    edge.get("invalidated_at"),
                    str(edge.get("proposed_by", "structural")),
                ),
            )
            count += 1
        except (json.JSONDecodeError, sqlite3.Error, Exception):
            continue
    conn.commit()
    return count


def _entity_index_enabled(store: MemoryOSStore) -> bool:
    """Check whether entity_index extraction is enabled via knob.

    Shared gate for rebuild, sync, and cognitive_loop — ensures entity_index
    is only populated when the operator has explicitly enabled the feature.
    """
    try:
        from .knob_overrides import resolve_knob
        return bool(resolve_knob("entity_index_enabled", default=False, roots=store.roots))
    except Exception as _exc:
        from .jsonl_io import build_error_record as _build_error_record
        _build_error_record(
            component="entity_index",
            operation="knob_resolution",
            error_code="ENTITY_INDEX_KNOB_FAILED",
            severity="warning",
            recoverable=True,
            details={"error": str(_exc)},
        )
        return False


def _index_entities(conn: sqlite3.Connection, crystallized_root: Path) -> int:
    """Index entities from crystallized records into entity_index table.

    Reads each .md file, parses frontmatter for the record id, then
    extracts entities from the body text using deterministic rules
    (paths, URLs, UUIDs, capitalized phrases).  The table is fully
    cleared and repopulated each call.
    """
    from .entity_extractor import extract_entities
    from datetime import datetime, timezone

    conn.execute("delete from entity_index")
    now = datetime.now(timezone.utc).isoformat()
    count = 0

    for path in sorted(crystallized_root.glob("*.md")):
        content = path.read_text(encoding="utf-8")
        # Parse frontmatter to extract record id
        record_id = ""
        body_start = 0
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                frontmatter_text = parts[1]
                body_text = parts[2]
                for line in frontmatter_text.strip().split("\n"):
                    if line.startswith("id:"):
                        record_id = line.split(":", 1)[1].strip()
                        break
            else:
                body_text = content
        else:
            body_text = content

        if not record_id:
            continue

        entities = extract_entities(body_text, record_id=record_id)
        for ent in entities:
            conn.execute(
                "insert or ignore into entity_index (entity_id, entity_text, record_id, role, proposed_by, created_at) "
                "values (?, ?, ?, ?, ?, ?)",
                (ent["entity_id"], ent["entity_text"], ent["record_id"], ent["role"], ent["proposed_by"], now),
            )
            count += 1

    return count


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


def _event_fts_text(event: Any) -> str:
    parts = [
        event.summary,
        event.source,
        event.kind,
        " ".join(str(tag) for tag in event.tags),
        _project_structured_text(event.safe_ref),
    ]
    return _normalize_projection_text(" ".join(part for part in parts if part))


def _project_structured_text(value: Any, *, path: tuple[str, ...] = ()) -> str:
    if isinstance(value, dict):
        fragments: list[str] = []
        for key, child in sorted(value.items(), key=lambda item: str(item[0])):
            clean_key = _clean_projection_token(str(key))
            if not clean_key or _is_private_projection_path(path + (clean_key,)):
                continue
            child_text = _project_structured_text(child, path=path + (clean_key,))
            if child_text:
                fragments.append(child_text)
        return " ".join(fragments)
    if isinstance(value, list):
        return " ".join(_project_structured_text(item, path=path) for item in value)
    if value is None or isinstance(value, bool):
        return ""
    rendered = _clean_projection_token(str(value))
    if not rendered:
        return ""
    return " ".join((*path[-2:], rendered))


def _is_private_projection_path(path: tuple[str, ...]) -> bool:
    joined = "_".join(path).lower()
    return any(part in joined for part in _PRIVATE_PROJECTION_KEY_PARTS)


def _clean_projection_token(value: str) -> str:
    cleaned = re.sub(r"[\{\}\[\]\"'`<>]", " ", value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:160]


def _normalize_projection_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


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


def _query_edges_sqlite(
    conn: sqlite3.Connection,
    anchor_ids: list[str],
    *,
    depth: int = 1,
    relation_types: list[str] | None = None,
    state: str = "active",
    limit: int = 10,
) -> list[dict[str, Any]]:
    """SQLite query helper for MemoryOSIndex.query_edges()."""
    if not anchor_ids or depth < 1:
        return []
    anchors = list(dict.fromkeys(anchor_ids))  # dedup preserve order
    if len(anchors) > 200:
        anchors = anchors[:200]
    placeholders = ",".join("?" * len(anchors))
    params: list[Any] = [state]
    params.extend(anchors)
    params.extend(anchors)  # second IN clause needs equal number of params
    where_relation = ""
    if relation_types:
        rt_placeholders = ",".join("?" * len(relation_types))
        where_relation = f" and relation_type in ({rt_placeholders})"
        params.extend(relation_types)
    params.append(limit + 1)
    sql = f"""
        select *
        from memory_edges
        where state = ?
          and (from_record_id in ({placeholders})
               or to_record_id in ({placeholders}))
          {where_relation}
        order by weight desc, created_at desc
        limit ?
    """
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.Error:
        return []
    results = [dict(row) for row in rows]
    if depth <= 1:
        return results[:limit]
    # depth >= 2: collect second-hop anchor ids from first-hop results
    second_ids = list(dict.fromkeys(
        r["to_record_id"] for r in results
        if r["to_record_id"] not in set(anchors)
    ))
    if not second_ids:
        return results[:limit]
    if len(second_ids) > 50:
        second_ids = second_ids[:50]
    s2_placeholders = ",".join("?" * len(second_ids))
    s2_params: list[Any] = [state]
    s2_params.extend(second_ids)
    s2_params.extend(second_ids)  # second IN clause
    s2_params.append(limit + 1)
    s2_sql = f"""
        select *
        from memory_edges
        where state = ?
          and (from_record_id in ({s2_placeholders})
               or to_record_id in ({s2_placeholders}))
        order by weight desc, created_at desc
        limit ?
    """
    try:
        s2_rows = conn.execute(s2_sql, s2_params).fetchall()
    except sqlite3.Error:
        return results[:limit]
    seen = {r["edge_id"] for r in results}
    combined = results + [dict(row) for row in s2_rows if row["edge_id"] not in seen]
    return combined[:limit]


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


# ── Edge governance helpers ───────────────────────────────────────────────


def _edge_id() -> str:
    """Generate a unique edge id."""
    return f"edge_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}_{hashlib.sha256(str(uuid4()).encode()).hexdigest()[:12]}"


def _write_edge_canonical(roots: MemoryOSRoots, edge: dict) -> bool:
    """Append one edge record to graph/edges.jsonl (canonical store).

    Uses append_jsonl (same pattern as events/working/candidates)
    so the edge has a durable canonical source outside the index DB.
    Writes an audit entry on success.

    Returns True on success, False on error.
    """
    from .jsonl_io import append_jsonl_locked
    from .audit import append_audit
    edges_path = roots.memory_os_root / "graph" / "edges.jsonl"
    try:
        edges_path.parent.mkdir(parents=True, exist_ok=True)
        append_jsonl_locked(edges_path, edge, ensure_parent=False, durable=True)
        append_audit(
            roots.audit_path,
            action="edge_canonical_written",
            status="ok",
            target=str(edges_path),
            details={"edge_id": edge.get("edge_id", ""), "relation_type": edge.get("relation_type", "")},
        )
        return True
    except (OSError, Exception):
        append_audit(
            roots.audit_path,
            action="edge_canonical_write_failed",
            status="warning",
            target=str(edges_path),
            details={"edge_id": edge.get("edge_id", "")},
        )
        return False


def write_governed_edge(
    conn: sqlite3.Connection,
    roots: MemoryOSRoots,
    *,
    from_record_type: str,
    from_record_id: str,
    to_record_type: str,
    to_record_id: str,
    relation_type: str,
    weight: float = 1.0,
    source_event_id: str | None = None,
    proposed_by: str = "structural",
    state: str = "candidate",
) -> dict[str, Any]:
    """Write an edge through the governance path into memory_edges.

    Governance path:
        1. Canonical write: graph/edges.jsonl (durable, survives rebuild)
        2. Index INSERT: memory_edges (queryable)
    If canonical write fails, the edge is NOT written to the index.
    Canonical write includes an audit entry (governance envelope).

    Args:
        conn: open SQLite connection (index DB).
        roots: MemoryOSRoots (needed for canonical path).
        from/to: node references (record_type + record_id).
        relation_type: one of the controlled vocabulary (refines, contradicts, etc.).
        weight: edge strength (default 1.0).
        source_event_id: optional provenance reference.
        proposed_by: source of the edge proposal (structural|vector|llm|owner).
        state: initial governance state (candidate|owner_eligible|active|invalidated).

    Returns the edge dict, or {} on failure.
    """
    now = datetime.now(timezone.utc).isoformat()
    edge = {
        "edge_id": _edge_id(),
        "from_record_type": from_record_type,
        "from_record_id": from_record_id,
        "to_record_type": to_record_type,
        "to_record_id": to_record_id,
        "relation_type": relation_type,
        "weight": float(weight),
        "created_at": now,
        "source_event_id": source_event_id or "",
        "state": state,
        "invalidated_at": None,
        "proposed_by": proposed_by,
    }
    try:
        # 1. Write canonical (governance path — if this fails, edge is not written)
        if not _write_edge_canonical(roots, edge):
            return {}

        # 2. Write to index DB
        conn.execute(
            """
            insert into memory_edges (
                edge_id, from_record_type, from_record_id,
                to_record_type, to_record_id, relation_type,
                weight, created_at, source_event_id,
                state, invalidated_at, proposed_by
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                edge["edge_id"],
                edge["from_record_type"],
                edge["from_record_id"],
                edge["to_record_type"],
                edge["to_record_id"],
                edge["relation_type"],
                edge["weight"],
                edge["created_at"],
                edge["source_event_id"],
                edge["state"],
                edge["invalidated_at"],
                edge["proposed_by"],
            ),
        )
        conn.commit()
        return edge
    except sqlite3.Error:
        return {}


def transition_edge_state(
    conn: sqlite3.Connection,
    edge_id: str,
    new_state: str,
    *,
    now: str | None = None,
) -> dict[str, Any]:
    """Transition an edge's governance state with validation.

    Allowed transitions:
        candidate → owner_eligible → active → invalidated
        candidate → active  (auto-approve for low-risk edges)
        candidate → invalidated  (rejection)

    Returns the updated edge dict, or {} on failure/illegal transition.
    """
    try:
        row = conn.execute(
            "select * from memory_edges where edge_id = ?", (edge_id,)
        ).fetchone()
    except sqlite3.Error:
        return {}
    if row is None:
        return {}
    col_names = [str(c[1]) for c in conn.execute("pragma table_info(memory_edges)").fetchall()]
    current = dict(zip(col_names, row))
    cur = str(current.get("state", ""))
    if cur == new_state:
        return current  # no-op
    _valid = {
        "candidate": {"owner_eligible", "active", "invalidated"},
        "owner_eligible": {"active", "invalidated"},
        "active": {"invalidated"},
        "invalidated": set(),
    }
    allowed = _valid.get(cur, set())
    if new_state not in allowed:
        return {}
    _now = now or datetime.now(timezone.utc).isoformat()
    updates: dict[str, Any] = {"state": new_state}
    if new_state == "invalidated":
        updates["invalidated_at"] = _now
    try:
        conn.execute(
            "update memory_edges set state = ?, invalidated_at = ? where edge_id = ?",
            (updates["state"], updates.get("invalidated_at"), edge_id),
        )
        conn.commit()
        current["state"] = updates["state"]
        current["invalidated_at"] = updates.get("invalidated_at")
        return current
    except sqlite3.Error:
        return {}
