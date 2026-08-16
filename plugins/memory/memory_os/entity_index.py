"""Entity Index public API — structural entity extraction and query-time joins.

Wraps the deterministic extractor in :mod:`entity_extractor` and the
index operations in :mod:`index` behind a stable facade.  All extraction
is rule-based (paths, URLs, UUIDs, capitalized phrases) — no LLM.

This is the L1 public base for export A (associative edges, query-time)
and export B (contradiction lane, owner-reviewed).
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


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
    if not enabled:
        return {"status": "skipped", "entity_count": 0, "record_count": 0}

    # Ensure the parent directory exists (db may not exist yet on first run)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    from .entity_extractor import extract_entities
    from datetime import datetime, timezone

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("""
            create table if not exists entity_index (
                entity_id text not null,
                entity_text text not null,
                record_id text not null,
                role text not null,
                proposed_by text not null default 'structural',
                created_at text not null,
                primary key (entity_id, record_id, role)
            );
        """)
        # Migration-safe: add entity_class and weight columns (Phase 2)
        for col, col_type in [("entity_class", "text not null default 'unknown'"),
                               ("weight", "real not null default 0.7")]:
            try:
                conn.execute(f"alter table entity_index add column {col} {col_type}")
            except sqlite3.OperationalError:
                pass  # column already exists
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
                    " (entity_id, entity_text, record_id, role, proposed_by, created_at,"
                    "  entity_class, weight)"
                    " values (?, ?, ?, ?, ?, ?, ?, ?)",
                    (ent["entity_id"], ent["entity_text"], ent["record_id"],
                     ent["role"], ent["proposed_by"], now,
                     ent.get("entity_class", "unknown"),
                     ent.get("weight", 0.7)),
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
    min_weight: float = 0.0,
) -> list[dict[str, Any]]:
    """Find records sharing entities with the given *record_ids*.

    This is the query-time associative edge — "what other records
    mention the same entities?"  Returns records with their shared
    entity and a ``related_reason``.

    When *min_weight* > 0, entities below the weight threshold are
    excluded from the join (Phase 2 soft-weighting, constraint 2).
    """
    if not db_path.exists() or not record_ids:
        return []

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        placeholders = ",".join("?" for _ in record_ids)
        rows = conn.execute(
            f"""
            with matches as (
                select ei2.record_id as record_id,
                       ei2.entity_text as entity_text,
                       ei2.entity_class as entity_class,
                       ei2.weight as weight
                from entity_index ei1
                join entity_index ei2
                  on ei1.entity_id = ei2.entity_id
                 and ei1.record_id != ei2.record_id
                where ei1.record_id in ({placeholders})
                  and ei2.weight >= ?
            ),
            ranked as (
                select record_id, entity_text, entity_class, weight,
                       row_number() over (
                           partition by record_id
                           order by weight desc, entity_text asc
                       ) as rn,
                       count(*) over (partition by record_id) as overlap_count
                from matches
            )
            select record_id,
                   entity_text as shared_entity,
                   entity_class,
                   weight,
                   overlap_count
            from ranked
            where rn = 1
            order by overlap_count desc
            limit ?
            """,
            (*record_ids, min_weight, max_results),
        ).fetchall()
    except sqlite3.Error as exc:
        # Fail-open by contract (recall must never crash the caller), but a
        # schema-level failure must not be indistinguishable from "no related
        # records" — that silence hid the missing weight column for months.
        logger.warning(
            "entity_index related-records query failed (%s: %s); returning empty set",
            type(exc).__name__, exc,
        )
        conn.close()
        return []
    conn.close()

    results: list[dict[str, Any]] = []
    for row in rows:
        shared_entity = row["shared_entity"]
        # entity_class and weight are read from the SAME winning row (highest
        # weight, entity_text tie-break) — never re-derived from independent
        # aggregates, which could mix one entity's text with another's class.
        entity_class = row["entity_class"]
        weight = float(row["weight"])
        results.append({
            "related_record_id": row["record_id"],
            "shared_entity": shared_entity,
            "overlap_count": int(row["overlap_count"]),
            "related_reason": f"shared_entity={shared_entity}",
            "entity_class": entity_class,
            "weight": weight,
        })

    return results


def entity_index_stats(db_path: Path) -> dict[str, Any]:
    """Return summary stats for the entity_index table."""
    if not db_path.exists():
        return {"entity_count": 0, "record_count": 0, "top_entities": [], "class_distribution": {}}

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
            "select entity_text, entity_class, weight, count(*) as cnt"
            " from entity_index"
            " group by entity_id"
            " order by cnt desc limit 10"
        ).fetchall()
        # Class distribution (Phase 2)
        try:
            class_rows = conn.execute(
                "select entity_class, count(*) as cnt from entity_index"
                " group by entity_class order by cnt desc"
            ).fetchall()
            class_distribution = {row["entity_class"]: row["cnt"] for row in class_rows}
        except sqlite3.OperationalError:
            class_distribution = {}
    except sqlite3.Error:
        conn.close()
        return {"entity_count": 0, "record_count": 0, "top_entities": [], "class_distribution": {}}
    conn.close()

    return {
        "entity_count": entity_count,
        "record_count": record_count,
        "top_entities": [
            {
                "entity_text": row["entity_text"],
                "record_count": row["cnt"],
                "entity_class": row["entity_class"] if "entity_class" in row.keys() else "unknown",
                "weight": row["weight"] if "weight" in row.keys() else 0.7,
            }
            for row in top
        ],
        "class_distribution": class_distribution,
    }
