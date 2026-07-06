"""FTS5-indexed recall retriever — SQLite full-text search."""

from __future__ import annotations

import sqlite3
from typing import Any, TYPE_CHECKING

from plugins.memory.memory_os.recall_types import RecallObject, RecallType

if TYPE_CHECKING:
    from plugins.memory.memory_os.store import MemoryOSStore


class IndexedFTSRetriever:
    """Full-text retrieval via the Memory-OS SQLite FTS5 index.

    Thin wrapper around ``MemoryOSIndex.search()`` — the index is a
    rebuildable cache, never the source of truth.  Fail-open: index
    missing or query error → empty list.
    """

    @property
    def recall_type(self) -> RecallType:
        return RecallType.INDEXED_FTS

    def retrieve(
        self,
        store: "MemoryOSStore",
        query: str,
        *,
        top_k: int = 10,
        scope: dict[str, Any] | None = None,
    ) -> list[RecallObject]:
        index_path = store.roots.index_path
        if not index_path.exists():
            return []

        try:
            conn = sqlite3.connect(str(index_path))
            conn.row_factory = sqlite3.Row
            # Use FTS5 with BM25 scoring
            rows = conn.execute(
                """
                SELECT m.record_id, m.content, m.kind, m.source_file,
                       rank
                FROM memory_fts(:query)
                JOIN memory_records m ON memory_fts.record_id = m.record_id
                ORDER BY rank
                LIMIT :limit
                """,
                {"query": _fts5_safe_query(query), "limit": top_k},
            ).fetchall()
            conn.close()
        except (sqlite3.Error, sqlite3.OperationalError):
            return []

        objects: list[RecallObject] = []
        for row in rows:
            content = (row["content"] or "")[:500]
            if not content.strip():
                continue
            objects.append(RecallObject(
                recall_type=RecallType.INDEXED_FTS.value,
                content=content,
                score=min(1.0, 1.0 / (1.0 + abs(float(row["rank"] or 0)))),
                source_ref=f"fts5:{row['record_id']}",
                metadata={
                    "kind": row["kind"] or "",
                    "source_file": row["source_file"] or "",
                    "record_id": row["record_id"],
                },
            ))
        return objects

    def format_context(
        self,
        objects: list[RecallObject],
        *,
        budget: int = 800,
    ) -> str:
        if not objects:
            return ""
        lines = ["### Indexed Recall (FTS5)"]
        for obj in objects:
            lines.append(f"- {obj.content[:200]}")
        return "\n".join(lines)


def _fts5_safe_query(query: str) -> str:
    """Sanitize user query for FTS5 — remove special chars, add prefix matching."""
    safe = "".join(c for c in query if c.isalnum() or c in " _.-")
    safe = safe.strip()
    if not safe:
        return '""'
    # Add prefix matching: append * to each term
    terms = safe.split()
    return " ".join(f"{t}*" if len(t) > 1 else t for t in terms)
