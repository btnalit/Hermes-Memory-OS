"""Entity Index public API — structural entity extraction and query-time joins.

Wraps the deterministic extractor in :mod:`entity_extractor` and the
index operations in :mod:`index` behind a stable facade.  All extraction
is rule-based (paths, URLs, UUIDs, capitalized phrases) — no LLM.

This is the L1 public base for export A (associative edges, query-time)
and export B (contradiction lane, owner-reviewed).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


def refresh_entity_index(
    db_path: Path,
    crystallized_root: Path,
    *,
    enabled: bool = True,
) -> dict[str, Any]:
    """Refresh the entity_index table from crystallized records.

    Idempotent — the table is cleared and repopulated each call so
    stale entities from renamed/deleted records are removed.
    Returns a summary dict with the count of entities indexed.

    When *enabled* is False the call is a no-op (knob-gated).
    """
    if not enabled or not db_path.exists():
        return {"status": "skipped", "entity_count": 0, "record_count": 0}

    from .entity_extractor import extract_entities
    from datetime import datetime, timezone

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("delete from entity_index")
        now = datetime.now(timezone.utc).isoformat()
        count = 0
        records_seen: set[str] = set()

        for md_path in sorted(crystallized_root.glob("*.md")):
            try:
                content = md_path.read_text(encoding="utf-8")
            except OSError:
                continue

            # Parse frontmatter for record_id
            record_id = ""
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    for line in parts[1].strip().split("\n"):
                        if line.startswith("id:"):
                            record_id = line.split(":", 1)[1].strip()
                            break
                    body_text = parts[2]
                else:
                    body_text = content
            else:
                body_text = content

            if not record_id or not body_text.strip():
                continue

            records_seen.add(record_id)
            entities = extract_entities(body_text, record_id=record_id)
            for ent in entities:
                conn.execute(
                    "insert or ignore into entity_index"
                    " (entity_id, entity_text, record_id, role, proposed_by, created_at)"
                    " values (?, ?, ?, ?, ?, ?)",
                    (ent["entity_id"], ent["entity_text"], ent["record_id"],
                     ent["role"], ent["proposed_by"], now),
                )
                count += 1

        conn.commit()
    finally:
        conn.close()

    return {
        "status": "ok",
        "entity_count": count,
        "record_count": len(records_seen),
    }


def query_related_records(
    db_path: Path,
    record_ids: list[str],
    *,
    max_results: int = 10,
) -> list[dict[str, Any]]:
    """Find records sharing entities with the given *record_ids*.

    This is the query-time associative edge — "what other records
    mention the same entities?"  Returns records with their shared
    entity and a ``related_reason``.
    """
    if not db_path.exists() or not record_ids:
        return []

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        placeholders = ",".join("?" for _ in record_ids)
        rows = conn.execute(
            f"""
            select ei2.record_id,
                   min(ei2.entity_text) as shared_entity,
                   count(*) as overlap_count
            from entity_index ei1
            join entity_index ei2
              on ei1.entity_id = ei2.entity_id
             and ei1.record_id != ei2.record_id
            where ei1.record_id in ({placeholders})
            group by ei2.record_id
            order by overlap_count desc
            limit ?
            """,
            (*record_ids, max_results),
        ).fetchall()
    except sqlite3.Error:
        conn.close()
        return []
    conn.close()

    return [
        {
            "related_record_id": row["record_id"],
            "shared_entity": row["shared_entity"],
            "overlap_count": int(row["overlap_count"]),
            "related_reason": f"shared_entity={row['shared_entity']}",
        }
        for row in rows
    ]


def entity_index_stats(db_path: Path) -> dict[str, Any]:
    """Return summary stats for the entity_index table."""
    if not db_path.exists():
        return {"entity_count": 0, "record_count": 0, "top_entities": []}

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        entity_count = conn.execute(
            "select count(*) from entity_index"
        ).fetchone()[0]
        record_count = conn.execute(
            "select count(distinct record_id) from entity_index"
        ).fetchone()[0]
        top = conn.execute(
            "select entity_text, count(*) as cnt"
            " from entity_index"
            " group by entity_id"
            " order by cnt desc limit 10"
        ).fetchall()
    except sqlite3.Error:
        conn.close()
        return {"entity_count": 0, "record_count": 0, "top_entities": []}
    conn.close()

    return {
        "entity_count": entity_count,
        "record_count": record_count,
        "top_entities": [
            {"entity_text": row["entity_text"], "record_count": row["cnt"]}
            for row in top
        ],
    }
