"""Deterministic structural edge proposer for crystallized↔crystallized relationships.

Runs as a cognitive-loop step. Reads active crystallized records from the
index, applies deterministic heuristics, and writes LIVE edges
(state=active, proposed_by=structural) — R1 (owner 决策 2026-08-06):动态
图谱全自动,边是派生投影,错误的边由权重反馈闭环动态淘汰,不占用
owner 审批带宽。

Relation vocabulary (W1/E2): structural similarity can prove that two
records are RELATED, never HOW they relate semantically — so this proposer
emits ``co_occurs`` (shared provenance, body similarity, temporal proximity)
plus ``depends_on`` only for an explicit record-id reference (a hard
structural fact, not a similarity guess).  ``refines`` and ``contradicts``
are reserved for the LLM proposer, which actually reads the content.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from .audit import append_audit
from .edge_weights import birth_weight
from .timeutil import ensure_utc_aware


# Dice coefficient threshold for body-text similarity — above this the pair
# is considered structurally related (co_occurs).
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
    """Parse an ISO timestamp string, best-effort.

    Naive (no-offset) timestamps parse without error but, if left naive,
    raise TypeError when subtracted from another parsed value of differing
    awareness in `_detect_relation`'s temporal-proximity check (two
    crystallized records whose `created_at` differ in naive/aware-ness).
    Normalize to UTC here, same as knob_overrides._is_expired, so every
    value this helper returns is safely comparable.
    """
    if not ts:
        return None
    try:
        parsed = datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None
    return ensure_utc_aware(parsed)


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

    # ── Shared source_event → co_occurs (shared provenance is
    # co-occurrence, not refinement — semantic labels are the LLM's job) ──
    shared_events = set(source_events_a) & set(source_events_b)
    if shared_events:
        shared_event = next(iter(shared_events)) if shared_events else ""
        edges.append({
            "from_record_type": "crystallized_record",
            "from_record_id": rid_a,
            "to_record_type": "crystallized_record",
            "to_record_id": rid_b,
            "relation_type": "co_occurs",
            "weight": birth_weight("structural", "shared_source_event"),
            "source_event_id": shared_event,
            "proposed_by": "structural",
            "state": "active",
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
            "weight": birth_weight("structural", "explicit_reference"),
            "source_event_id": None,
            "proposed_by": "structural",
            "state": "active",
        })

    # ── Body similarity → co_occurs (W1/E2: token overlap proves
    # relatedness, not refinement/contradiction — those need the LLM) ──
    dice = _dice_coefficient(body_a, body_b)
    if dice >= _DICE_THRESHOLD:
        rtype = "co_occurs"
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
                "weight": birth_weight("structural", "body_similarity"),
                "source_event_id": None,
                "proposed_by": "structural",
                "state": "active",
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
                "weight": birth_weight("structural", "temporal_proximity"),
                "source_event_id": None,
                "proposed_by": "structural",
                "state": "active",
            })

    return edges


def _order_records_unedged_first(
    records: list[dict[str, Any]],
    index_path: str,
    *,
    proposed_by: str = "structural",
) -> list[dict[str, Any]]:
    """Stable partition: records without a non-invalidated edge from this
    proposer class first.

    Coverage is judged per proposer (``proposed_by``) — an llm edge on a
    record must not push it behind the head records the structural reorder
    exists to starve out, and vice versa.  Fail-open: on any query error the
    input order is returned.
    """
    edged: set[str] = set()
    try:
        conn = sqlite3.connect(index_path)
        try:
            rows = conn.execute(
                "select from_record_id, to_record_id from memory_edges"
                " where state != 'invalidated' and proposed_by = ?",
                (proposed_by,),
            ).fetchall()
        finally:
            conn.close()
        for a, b in rows:
            edged.add(str(a))
            edged.add(str(b))
    except sqlite3.Error:
        return records
    unedged = [r for r in records if str(r.get("id", "")) not in edged]
    rest = [r for r in records if str(r.get("id", "")) in edged]
    return unedged + rest


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
    boundary_dedup_skipped = 0
    write_failed = 0
    dedup_keys: set[str] = set()

    # ── W1/E3 pair de-bias: unedged records first ──────────────────────
    # The old created_at-ascending order let the oldest ~20 records consume
    # the entire max_pairs budget every run (production: top-5 hubs were all
    # same-day records carrying 189–275 edges each) while newer records never
    # got a single structural edge.  Records without any non-invalidated
    # structural edge are examined first; within each group the created_at
    # order is preserved (stable).  Dedup itself now lives at the write
    # boundary (index.write_governed_edge) — the previous query_edges
    # pre-check here was capped at limit=1000 and silently defeated once the
    # backlog crossed that cap.
    records = _order_records_unedged_first(records, index_path)

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
                if dedup_key in dedup_keys:
                    continue
                dedup_keys.add(dedup_key)
                if index and hasattr(index, "write_governed_edge"):
                    result = index.write_governed_edge(**candidate)
                    if result.get("skipped_duplicate"):
                        boundary_dedup_skipped += 1
                    elif result:
                        proposed += 1
                    else:
                        write_failed += 1

    elapsed_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)

    summary = {
        "status": "ok",
        "record_count": len(records),
        "pair_count": pairs,
        "proposed_count": proposed,
        "dedup_skipped": boundary_dedup_skipped,
        "write_failed_count": write_failed,
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
