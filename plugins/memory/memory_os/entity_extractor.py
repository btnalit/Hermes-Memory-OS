"""Deterministic entity extraction for the V2 entity index.

Rule-based only — no LLM, INV-5 compliant. Extracts:
- Named entities: capitalized phrases, proper nouns
- Paths: file paths, URLs
- Identifiers: IDs, UUIDs, reference strings

All extraction is deterministic and cheap — suitable for cognitive_loop
low-frequency execution.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any


# ── Regex patterns ─────────────────────────────────────────────────────

_PATH_PATTERN = re.compile(
    r"(?:/[a-zA-Z0-9._\-\[\]]+)+/?",
)

_URL_PATTERN = re.compile(
    r"https?://[^\s<>\"{}|\\^`\[\]]+",
)

_UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b",
)

_CAPITALIZED_PHRASE_PATTERN = re.compile(
    r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b",
)

_ID_PATTERN = re.compile(
    r"\b[A-Za-z_][A-Za-z0-9_]*[A-Z0-9]\b",
)


def _normalize_entity_id(entity_text: str) -> str:
    """Generate a stable, deterministic entity_id from entity text."""
    normalized = entity_text.strip().lower()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return f"ent_{digest}"


def extract_entities(body: str, *, record_id: str = "") -> list[dict[str, Any]]:
    """Extract entities from a crystallized record body.

    Returns a list of entity dicts with keys:
        entity_id, entity_text, record_id, role, proposed_by

    role is always "mention" in P1 (subject/object distinction requires
    LLM, which is P4). P1 captures: paths, URLs, UUIDs, capitalized
    phrases.
    """
    if not body or not body.strip():
        return []

    entities: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(text: str, role: str = "mention") -> None:
        text = text.strip()
        if not text or len(text) < 2:
            return
        eid = _normalize_entity_id(text)
        if eid in seen:
            return
        seen.add(eid)
        entities.append({
            "entity_id": eid,
            "entity_text": text,
            "record_id": record_id,
            "role": role,
            "proposed_by": "structural",
        })

    # Paths
    for m in _PATH_PATTERN.finditer(body):
        _add(m.group(0), role="mention")

    # URLs
    for m in _URL_PATTERN.finditer(body):
        _add(m.group(0), role="mention")

    # UUIDs
    for m in _UUID_PATTERN.finditer(body):
        _add(m.group(0), role="mention")

    # Capitalized phrases (proper nouns, names)
    for m in _CAPITALIZED_PHRASE_PATTERN.finditer(body):
        _add(m.group(0), role="mention")

    return entities


def entity_inverted_index(
    conn: "sqlite3.Connection",
    entity_id: str,
) -> list[str]:
    """Return all record_ids sharing the given entity_id.

    This is the inverted index lookup — "what records mention entity X?"
    Used by both export A (query-time associative edge derivation) and
    export B (contradiction lane candidate discovery).
    """
    import sqlite3

    rows = conn.execute(
        "select distinct record_id from entity_index where entity_id = ? order by record_id",
        (entity_id,),
    ).fetchall()
    return [str(r[0]) for r in rows]


def shared_entity_pairs(
    conn: "sqlite3.Connection",
    *,
    min_shared_entities: int = 1,
    max_pairs: int = 200,
) -> list[dict[str, Any]]:
    """Find record pairs that share entities.

    Returns pairs of record_ids that share at least min_shared_entities
    entities. Each pair is {"record_a": str, "record_b": str, "shared_entities": int}.
    """
    rows = conn.execute(
        """
        select a.record_id as record_a, b.record_id as record_b,
               count(distinct a.entity_id) as shared_entities
        from entity_index a
        join entity_index b
          on a.entity_id = b.entity_id
         and a.record_id < b.record_id
        group by a.record_id, b.record_id
        having shared_entities >= ?
        order by shared_entities desc
        limit ?
        """,
        (min_shared_entities, max_pairs),
    ).fetchall()
    return [
        {"record_a": str(r[0]), "record_b": str(r[1]), "shared_entities": int(r[2])}
        for r in rows
    ]
