"""Entity Graph retriever — query-time associative edges via shared entities.

Reads the entity_index table to find records that share entities with
records matching the query.  This is the L1 controlled-injection path:
related records are surfaced as a recall lane, NOT auto-injected into
memory_edges.  Owner-governed crystallization remains the only path to
persistent graph edges.

Implements export A from the Graph V2 architecture:
  entity_index → query-time SQL join → related records with reason.

Phase 2: entity_class soft-weighting applied at retrieval layer.
Low-weight entities (path=0.4, url=0.5) are de-prioritized in scoring
but never hard-excluded (constraint 2: safe defaults).
"""

from __future__ import annotations

import json
from typing import Any, TYPE_CHECKING

from plugins.memory.memory_os.recall_types import RecallObject, RecallType
from plugins.memory.memory_os.entity_extractor import classify_entity

if TYPE_CHECKING:
    from plugins.memory.memory_os.store import MemoryOSStore


class EntityGraphRetriever:
    """Query-time entity graph recall.

    Finds primary matching records via FTS5 (or crystallized markdown
    scan), then joins through the entity_index to surface related
    records with a ``related_reason`` annotation.

    Phase 2: applies entity_class soft-weighting — path/url entities
    receive lower weight (0.4-0.5) while proper_nouns receive higher
    weight (0.9).  All entities remain recallable; only ranking changes.
    """

    @property
    def recall_type(self) -> RecallType:
        return RecallType.ENTITY_GRAPH

    def retrieve(
        self,
        store: "MemoryOSStore",
        query: str,
        *,
        top_k: int = 10,
        scope: dict[str, Any] | None = None,
    ) -> list[RecallObject]:
        from plugins.memory.memory_os.entity_index import query_related_records

        roots = store.roots
        db_path = roots.index_path

        if not db_path.exists():
            return []

        # 1) Find primary records matching the query via crystallized scan
        primary_ids = _find_primary_record_ids(roots.crystallized_root, query)
        if not primary_ids:
            return []

        # 2) Query-time join: what records share entities with primary hits?
        #    min_weight=0.3 excludes only truly empty entities
        related = query_related_records(
            db_path, primary_ids, max_results=top_k, min_weight=0.3,
        )

        # 3) Read related record bodies from crystallized
        objects: list[RecallObject] = []
        for rel in related:
            rid = rel["related_record_id"]
            body = _read_record_body(roots.crystallized_root, rid)
            if not body:
                continue
            entity_class = rel.get("entity_class", "unknown")
            weight = rel.get("weight", 0.7)
            # Score: overlap density × entity weight (Phase 2 soft-weighting)
            base = min(1.0, rel["overlap_count"] / 5.0)
            score = round(base * weight, 3)
            shared_entity = rel["shared_entity"]
            related_reason = (
                f"shared_entity={shared_entity}"
                + (f" ({entity_class}, w={weight})" if entity_class != "unknown" else "")
            )
            objects.append(RecallObject(
                recall_type=RecallType.ENTITY_GRAPH.value,
                content=body[:300],
                score=score,
                source_ref=f"entity_graph:{rid}",
                metadata={
                    "related_record_id": rid,
                    "shared_entity": shared_entity,
                    "related_reason": related_reason,
                    "overlap_count": rel["overlap_count"],
                    "entity_class": entity_class,
                    "weight": weight,
                    "primary_ids": primary_ids[:3],
                },
            ))

        objects.sort(key=lambda o: o.score, reverse=True)
        return objects[:top_k]

    def format_context(
        self,
        objects: list[RecallObject],
        *,
        budget: int = 800,
    ) -> str:
        if not objects:
            return ""
        lines = ["### Related Memory (entity graph)"]
        for obj in objects:
            reason = obj.metadata.get("related_reason", "")
            shared = obj.metadata.get("shared_entity", "")
            entity_class = obj.metadata.get("entity_class", "")
            # Include entity_class for path-noise visibility
            tag_parts = []
            if shared:
                tag_parts.append(shared)
            if entity_class and entity_class != "unknown":
                tag_parts.append(entity_class)
            tag = f" [{' | '.join(tag_parts)}]" if tag_parts else ""
            lines.append(f"-{tag} {obj.content[:200]}")
        return "\n".join(lines)


def _find_primary_record_ids(crystallized_root: Any, query: str) -> list[str]:
    """Find crystallized records matching the query via simple text scan.

    Returns up to 5 record IDs.  Falls back to empty when no records match.
    """
    q_lower = query.lower()
    q_words = [w for w in q_lower.split() if len(w) > 1]
    if not q_words:
        return []

    scored: list[tuple[int, str]] = []
    for md_path in sorted(crystallized_root.glob("*.md")):
        try:
            text = md_path.read_text(encoding="utf-8")
        except OSError:
            continue
        body_lower = text.lower()
        hits = sum(1 for w in q_words if w in body_lower)
        if hits > 0:
            # Extract record_id from frontmatter
            rid = ""
            if text.startswith("---"):
                parts = text.split("---", 2)
                if len(parts) >= 3:
                    for line in parts[1].strip().split("\n"):
                        if line.startswith("id:"):
                            rid = line.split(":", 1)[1].strip()
                            break
            if not rid:
                rid = md_path.stem
            scored.append((hits, rid))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [rid for _, rid in scored[:5]]


def _read_record_body(crystallized_root: Any, record_id: str) -> str:
    """Read the body of a crystallized record by record_id.

    Scans *.md files for frontmatter id matching *record_id*.
    """
    for md_path in sorted(crystallized_root.glob("*.md")):
        try:
            text = md_path.read_text(encoding="utf-8")
        except OSError:
            continue
        if f"id: {record_id}" not in text and f'id: "{record_id}"' not in text:
            continue
        parts = text.split("---", 2)
        body = parts[-1].strip() if len(parts) >= 3 else text.strip()
        first_para = body.split("\n\n")[0].strip() if body else ""
        return first_para
    return ""
