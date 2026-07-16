"""FTS5-indexed recall retriever — SQLite full-text search."""

from __future__ import annotations

import math
import sqlite3
from typing import Any, TYPE_CHECKING

from plugins.memory.memory_os.crystallized import (
    _parse_markdown_records,
    is_active_crystallized_frontmatter,
)
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
        limit = max(0, int(top_k))
        if not index_path.exists() or limit == 0:
            return []

        active_crystallized_bodies = _active_crystallized_record_bodies(store.roots.crystallized_root)
        objects: list[RecallObject] = []
        batch_size = max(50, limit * 4)
        offset = 0
        conn = sqlite3.connect(str(index_path))
        try:
            conn.row_factory = sqlite3.Row
            while len(objects) < limit:
                rows = conn.execute(
                    """
                    SELECT record_type,
                           record_id,
                           title,
                           text,
                           bm25(memory_fts) AS rank
                    FROM memory_fts
                    WHERE memory_fts MATCH ?
                    ORDER BY rank
                    LIMIT ? OFFSET ?
                    """,
                    (_fts5_safe_query(query), batch_size, offset),
                ).fetchall()
                if not rows:
                    break
                offset += len(rows)
                for row in rows:
                    if row["record_type"] == "crystallized_record":
                        record_id = str(row["record_id"] or "")
                        source_body = active_crystallized_bodies.get(record_id)
                        if source_body is None or source_body.strip() != str(row["text"] or "").strip():
                            continue
                    content = (row["text"] or "")[:500]
                    if not content.strip():
                        continue
                    rank = max(-60.0, min(60.0, float(row["rank"] or 0.0)))
                    objects.append(RecallObject(
                        recall_type=RecallType.INDEXED_FTS.value,
                        content=content,
                        score=1.0 / (1.0 + math.exp(rank)),
                        source_ref=f"fts5:{row['record_id']}",
                        authority_class="indexed_derived",
                        metadata={
                            "kind": row["record_type"] or "",
                            "title": row["title"] or "",
                            "record_id": row["record_id"],
                        },
                    ))
                    if len(objects) >= limit:
                        break
                if len(rows) < batch_size:
                    break
        except sqlite3.Error:
            return []
        finally:
            conn.close()
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
            lines.append(f"- {obj.content}")
        return "\n".join(lines)


def _active_crystallized_record_bodies(crystallized_root: Any) -> dict[str, str]:
    active_bodies: dict[str, str] = {}
    for path in sorted(crystallized_root.glob("*.md")):
        try:
            records = _parse_markdown_records(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        for frontmatter, body in records:
            record_id = str(frontmatter.get("id") or "")
            if record_id and is_active_crystallized_frontmatter(frontmatter):
                active_bodies[record_id] = body
    return active_bodies


def _fts5_safe_query(query: str) -> str:
    """Sanitize user query for FTS5 — remove special chars, add prefix matching."""
    safe = "".join(c for c in query if c.isalnum() or c in " _.-")
    safe = safe.strip()
    if not safe:
        return '""'
    # Add prefix matching: append * to each term
    terms = safe.split()
    return " ".join(f"{t}*" if len(t) > 1 else t for t in terms)
