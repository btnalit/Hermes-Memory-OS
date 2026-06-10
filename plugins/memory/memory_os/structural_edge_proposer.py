"""Deterministic structural edge proposer for crystallized↔crystallized relationships.

Runs as a cognitive-loop step. Reads active crystallized records from the
index, applies heuristics to detect refines / contradicts / depends_on edges,
and writes candidate edges (state=candidate, proposed_by=structural) to the
memory_edges table for subsequent owner review and promotion.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from .audit import append_audit
from .index import write_governed_edge


# Dice coefficient threshold for body-text similarity — above this is
# considered a positive match (refines or contradicts, resolved by stance).
_DICE_THRESHOLD = 0.30

# Temporal proximity for co_occurs / loose refines (seconds).
_TEMPORAL_WINDOW_SECONDS = 3600

# Max crystallized pairs to examine per cycle (guard out-degree explosion).
_MAX_PAIRS = 200


# ── Body-text helpers ──────────────────────────────────────────────────────


def _dice_coefficient(a: str, b: str) -> float:
    """Dice coefficient for two strings based on bigram overlap."""
    bigrams_a = {a[i:i+2] for i in range(len(a) - 1)}
    bigrams_b = {b[i:i+2] for i in range(len(b) - 1)}
    if not bigrams_a or not bigrams_b:
        return 0.0
    intersection = bigrams_a & bigrams_b
    return 2.0 * len(intersection) / (len(bigrams_a) + len(bigrams_b))


def _contains_record_ref(body: str, record_id: str) -> bool:
    """Check if body text contains a reference to the given record_id."""
    return record_id in body


def _parse_iso(ts: str) -> datetime | None:
    """Parse an ISO timestamp string, best-effort."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def _detect_relation(
    record_a: dict[str, Any],
    record_b: dict[str, Any],
) -> list[dict[str, Any]]:
    """Apply deterministic heuristics to a pair of crystallized records.

    Returns a list of candidate edge dicts (may be empty).
    Each edge dict has the keys expected by write_governed_edge().
    """
    edges: list[dict[str, Any]] = []

    rid_a = str(record_a.get("id", ""))
    rid_b = str(record_b.get("id", ""))
    if not rid_a or not rid_b:
        return []
    if rid_a == rid_b:
        return []

    body_a = str(record_a.get("body", "") or record_a.get("summary", ""))
    body_b = str(record_b.get("body", "") or record_b.get("summary", ""))
    kind_a = str(record_a.get("kind", ""))
    kind_b = str(record_b.get("kind", ""))
    tags_a = record_a.get("tags_json", []) or []
    tags_b = record_b.get("tags_json", []) or []
    if isinstance(tags_a, str):
        try:
            tags_a = json.loads(tags_a)
        except (json.JSONDecodeError, TypeError):
            tags_a = [tags_a] if tags_a else []
    if isinstance(tags_b, str):
        try:
            tags_b = json.loads(tags_b)
        except (json.JSONDecodeError, TypeError):
            tags_b = [tags_b] if tags_b else []
    tags_a = list(tags_a)
    tags_b = list(tags_b)

    source_events_a = record_a.get("source_event_ids_json", []) or []
    source_events_b = record_b.get("source_event_ids_json", []) or []
    if isinstance(source_events_a, str):
        try:
            source_events_a = json.loads(source_events_a)
        except (json.JSONDecodeError, TypeError):
            source_events_a = [source_events_a] if source_events_a else []
    if isinstance(source_events_b, str):
        try:
            source_events_b = json.loads(source_events_b)
        except (json.JSONDecodeError, TypeError):
            source_events_b = [source_events_b] if source_events_b else []
    source_events_a = list(source_events_a)
    source_events_b = list(source_events_b)

    # ── Shared source_event → refines or co_occurs ──
    shared_events = set(source_events_a) & set(source_events_b)
    if shared_events:
        shared_event = next(iter(shared_events)) if shared_events else ""
        edges.append({
            "from_record_type": "crystallized_record",
            "from_record_id": rid_a,
            "to_record_type": "crystallized_record",
            "to_record_id": rid_b,
            "relation_type": "refines",
            "weight": 1.0,
            "source_event_id": shared_event,
            "proposed_by": "structural",
            "state": "candidate",
        })

    # ── depends_on: one body explicitly references the other's ID ──
    if _contains_record_ref(body_a, rid_b) or _contains_record_ref(body_b, rid_a):
        from_id = rid_a if _contains_record_ref(body_a, rid_b) else rid_b
        to_id = rid_b if _contains_record_ref(body_a, rid_b) else rid_a
        edges.append({
            "from_record_type": "crystallized_record",
            "from_record_id": from_id,
            "to_record_type": "crystallized_record",
            "to_record_id": to_id,
            "relation_type": "depends_on",
            "weight": 1.0,
            "source_event_id": None,
            "proposed_by": "structural",
            "state": "candidate",
        })

    # ── Body similarity → refines or contradicts ──
    dice = _dice_coefficient(body_a, body_b)
    if dice >= _DICE_THRESHOLD:
        if kind_a != kind_b:
            rtype = "contradicts"
        else:
            rtype = "refines"
        # Only write if we haven't already via source_event or depends_on
        has_same = any(
            e["relation_type"] == rtype
            and e["from_record_id"] == rid_a
            and e["to_record_id"] == rid_b
            for e in edges
        )
        if not has_same:
            edges.append({
                "from_record_type": "crystallized_record",
                "from_record_id": rid_a,
                "to_record_type": "crystallized_record",
                "to_record_id": rid_b,
                "relation_type": rtype,
                "weight": 1.0,
                "source_event_id": None,
                "proposed_by": "structural",
                "state": "candidate",
            })

    # ── Temporal proximity → co_occurs ──
    ts_a = _parse_iso(str(record_a.get("created_at", "")))
    ts_b = _parse_iso(str(record_b.get("created_at", "")))
    if ts_a and ts_b:
        delta = abs((ts_a - ts_b).total_seconds())
        if 0 < delta < _TEMPORAL_WINDOW_SECONDS and not edges:
            edges.append({
                "from_record_type": "crystallized_record",
                "from_record_id": rid_a,
                "to_record_type": "crystallized_record",
                "to_record_id": rid_b,
                "relation_type": "co_occurs",
                "weight": 1.0,
                "source_event_id": None,
                "proposed_by": "structural",
                "state": "candidate",
            })

    return edges


# ── Proposer runner ────────────────────────────────────────────────────────


def run_structural_proposer(
    index_path: str,
    *,
    index: object | None = None,
    audit_path: str | None = None,
    max_pairs: int = _MAX_PAIRS,
) -> dict[str, Any]:
    """Read crystallized records and propose edges between them.

    Args:
        index_path: Path to the index DB.
        index: Optional MemoryOSIndex instance (for writing edges).
               If None, creates a fresh one (needs roots).
        audit_path: Optional audit path.

    Returns a summary dict with counts of proposed edges.
    """
    start_time = datetime.now(timezone.utc)

    # Read active crystallized records from the index.
    conn = sqlite3.connect(index_path)
    conn.row_factory = sqlite3.Row
    try:
        records_raw = conn.execute(
            "select * from crystallized_records order by created_at"
        ).fetchall()
    except sqlite3.Error:
        return {"status": "error", "error": "cannot_read_crystallized_records"}
    finally:
        conn.close()

    records: list[dict[str, Any]] = [dict(r) for r in records_raw]
    if len(records) < 2:
        return {
            "status": "skipped",
            "reason": f"need ≥2 crystallized records, got {len(records)}",
            "proposed_count": 0,
            "pair_count": 0,
        }

    # Enrich records with body text from FTS5 index (crystallized_records
    # table has no body column — it comes from the FTS projection).
    conn2 = sqlite3.connect(index_path)
    conn2.row_factory = sqlite3.Row
    try:
        for rec in records:
            rid = str(rec.get("id", ""))
            if not rid:
                continue
            row = conn2.execute(
                "select text from memory_fts where record_type = 'crystallized_record' and record_id = ?",
                (rid,),
            ).fetchone()
            if row:
                rec["body"] = str(row["text"])
    except sqlite3.Error:
        pass  # fail-open — body enrichment is best-effort
    finally:
        conn2.close()

    # Build all unordered pairs.
    pairs = 0
    proposed = 0
    dedup_keys: set[str] = set()

    # Check existing edges to avoid duplicates.
    existing_edges: set[str] = set()
    if index:
        try:
            all_records = [r["id"] for r in records if r.get("id")]
            if all_records:
                # Check both candidate and active edges for dedup
                for dedup_state in ("candidate", "active"):
                    raw = index.query_edges(
                        all_records, depth=1, state=dedup_state, limit=1000
                    )
                    if isinstance(raw, list):
                        for e in raw:
                            key = f"{e.get('from_record_id','')}:{e.get('to_record_id','')}:{e.get('relation_type','')}"
                            existing_edges.add(key)
        except Exception:
            pass  # fail-open

    for i in range(len(records)):
        if pairs >= max_pairs:
            break
        for j in range(i + 1, len(records)):
            if pairs >= max_pairs:
                break
            pairs += 1
            candidates = _detect_relation(records[i], records[j])
            for candidate in candidates:
                dedup_key = (
                    f"{candidate['from_record_id']}:"
                    f"{candidate['to_record_id']}:"
                    f"{candidate['relation_type']}"
                )
                if dedup_key in dedup_keys or dedup_key in existing_edges:
                    continue
                dedup_keys.add(dedup_key)
                if index:
                    result = index.write_governed_edge(**candidate)
                    if result:
                        proposed += 1

    elapsed_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)

    summary = {
        "status": "ok",
        "record_count": len(records),
        "pair_count": pairs,
        "proposed_count": proposed,
        "dedup_skipped": len(dedup_keys) - proposed,
        "duration_ms": elapsed_ms,
        "begin_at": start_time.isoformat(),
    }

    if audit_path:
        from pathlib import Path
        append_audit(
            Path(audit_path),
            action="structural_edge_proposer_run",
            status="ok",
            target=str(index_path),
            details=summary,
        )

    return summary
