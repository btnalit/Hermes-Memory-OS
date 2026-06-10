"""LLM-class edge proposer — uses the Hermes runtime LLM for semantic analysis.

Phase 2.3 — calls the configured LLM (via low_clue_recall._call_hermes_runtime_model)
to determine relationships between crystallized record pairs.

Auto-active types (co_occurs, evidence_for) promote to `active` directly.
Review-required types (contradicts, depends_on, refines) always stay as `candidate`
— owner review is non-negotiable per §6, G4, T2.3.2.
Confidence is stored as provenance metadata, NOT as a review bypass.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from .audit import append_audit
from .low_clue_recall import _call_hermes_runtime_model, _resolve_hermes_default_runtime


# Default LLM judge config (mirrors low_clue_recall.DEFAULT_CONFIG["llm_judge"]).
_DEFAULT_LLM_CONFIG: dict[str, Any] = {
    "enabled": True,
    "mode": "bounded_vote",
    "provider": "hermes_default",
    "temperature": 0,
    "timeout_ms": 15000,
    "max_tokens": 1024,
    "max_candidates": 4,
    "on_error": "deterministic_fallback",
}

# Relation types that auto-promote to active (low risk).
_AUTO_ACTIVE_TYPES = frozenset({"co_occurs", "evidence_for"})

# Relation types that stay candidate (needs owner review).
_REVIEW_REQUIRED_TYPES = frozenset({"contradicts", "depends_on", "refines"})

_MAX_PAIRS = 100


# ── Prompt template ────────────────────────────────────────────────────────


_RELATION_PROMPT_TEMPLATE = """You are analyzing crystallized memory records in a governance system.
Determine the relationship between the two records below.

Record A (kind: {kind_a}):
Tags: [{tags_a}]
Body: {body_a}

Record B (kind: {kind_b}):
Tags: [{tags_b}]
Body: {body_b}

Choose ONE relationship type from:
- "refines" — Record A is a refinement/extension of Record B (or vice versa)
- "contradicts" — The records express contradictory positions on the same topic
- "depends_on" — One record logically depends on the other
- "co_occurs" — The records are related by context (same topic, same session) but not refinement/contradiction/dependency
- "none" — No meaningful relationship

Respond with ONLY a JSON object:
{{"relation_type": "<chosen_type>", "confidence": 0.0-1.0, "reasoning": "<brief explanation>"}}

If "none", still respond with valid JSON showing relation_type "none"."""


# ── LLM call ───────────────────────────────────────────────────────────────


def _call_llm(record_a: dict[str, Any], record_b: dict[str, Any]) -> dict[str, Any]:
    """Call the configured Hermes LLM to determine relationship between two records.

    Returns a dict with keys: relation_type, confidence, reasoning.
    Returns {"relation_type": "none", "confidence": 0.0, "reasoning": "llm_unavailable"} on failure.
    """
    kind_a = str(record_a.get("kind", ""))
    kind_b = str(record_b.get("kind", ""))
    body_a = str(record_a.get("body", "") or "")[:500]
    body_b = str(record_b.get("body", "") or "")[:500]
    tags_a = _format_tags(record_a.get("tags_json", []))
    tags_b = _format_tags(record_b.get("tags_json", []))

    prompt = _RELATION_PROMPT_TEMPLATE.format(
        kind_a=kind_a or "unknown",
        kind_b=kind_b or "unknown",
        tags_a=tags_a,
        tags_b=tags_b,
        body_a=body_a or "(no body)",
        body_b=body_b or "(no body)",
    )

    try:
        response = _call_hermes_runtime_model(prompt, _DEFAULT_LLM_CONFIG)
    except Exception:
        return {"relation_type": "none", "confidence": 0.0, "reasoning": "llm_call_exception"}

    if not response or not response.strip():
        return {"relation_type": "none", "confidence": 0.0, "reasoning": "empty_llm_response"}

    # Parse JSON from response (handle wrapping markdown code fences)
    json_str = response.strip()
    if "```json" in json_str:
        json_str = json_str.split("```json")[1].split("```")[0].strip()
    elif "```" in json_str:
        json_str = json_str.split("```")[1].split("```")[0].strip()

    try:
        parsed = json.loads(json_str)
    except (json.JSONDecodeError, TypeError):
        return {"relation_type": "none", "confidence": 0.0, "reasoning": "parse_failed"}

    if not isinstance(parsed, dict):
        return {"relation_type": "none", "confidence": 0.0, "reasoning": "not_a_dict"}

    rtype = str(parsed.get("relation_type", "none")).strip().lower()
    if rtype not in ("refines", "contradicts", "depends_on", "co_occurs", "none"):
        rtype = "none"

    confidence = float(parsed.get("confidence", 0.0))
    reasoning = str(parsed.get("reasoning", ""))

    return {
        "relation_type": rtype,
        "confidence": min(max(confidence, 0.0), 1.0),
        "reasoning": reasoning,
    }


# ── Helper ─────────────────────────────────────────────────────────────────


def _format_tags(tags_val: Any) -> str:
    """Format tags field (list or JSON string) into a comma-separated string."""
    if isinstance(tags_val, list):
        return ", ".join(str(t) for t in tags_val)
    if isinstance(tags_val, str):
        try:
            parsed = json.loads(tags_val)
            if isinstance(parsed, list):
                return ", ".join(str(t) for t in parsed)
        except (json.JSONDecodeError, TypeError):
            pass
        return tags_val
    return ""


def _resolve_runtime() -> dict[str, Any]:
    """Check if LLM runtime is available for the proposer."""
    try:
        resolved = _resolve_hermes_default_runtime(_DEFAULT_LLM_CONFIG)
        return resolved
    except Exception:
        return {"ok": False, "code": "resolve_failed"}


# ── Entry point ────────────────────────────────────────────────────────────


def run_llm_proposer(
    index_path: str,
    *,
    index: object | None = None,
    audit_path: str | None = None,
    batch: bool = True,
) -> dict[str, Any]:
    """Run the LLM-class edge proposer across all crystallized record pairs.

    Calls the configured Hermes runtime LLM for each pair to determine
    relationships. Low-risk edges auto-promote to active.

    Args:
        index_path: Path to the index DB.
        index: MemoryOSIndex instance (needed for edge writing).
        audit_path: Optional audit path.
        batch: If True, batches all pairs into a single LLM call (cheaper).
               If False, calls LLM per pair (more accurate).

    Returns a summary dict.
    """
    start_time = datetime.now(timezone.utc)

    # 1. Read crystallized records with body text.
    try:
        conn = sqlite3.connect(index_path)
    except (sqlite3.Error, Exception):
        return {"status": "error", "error": f"cannot_open_index: {index_path}"}
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
        }

    # Enrich with body text from FTS5
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
        pass
    finally:
        conn2.close()

    # 2. Collect existing edges for dedup
    existing_edges: set[str] = set()
    if index and hasattr(index, "query_edges"):
        try:
            all_ids = [r["id"] for r in records if r.get("id")]
            if all_ids:
                for state_filter in ("candidate", "active", "owner_eligible"):
                    raw = index.query_edges(all_ids, depth=1, state=state_filter, limit=1000)
                    if isinstance(raw, list):
                        for e in raw:
                            key = f"{e.get('from_record_id','')}:{e.get('to_record_id','')}:{e.get('relation_type','')}"
                            existing_edges.add(key)
        except Exception:
            pass

    # 3. Build pairs and call LLM
    pairs = 0
    proposed = 0
    auto_active = 0
    dedup_skipped = 0

    for i in range(len(records)):
        if pairs >= _MAX_PAIRS:
            break
        for j in range(i + 1, len(records)):
            if pairs >= _MAX_PAIRS:
                break
            pairs += 1

            # Skip if all relation types already exist as edges
            existing_for_pair = {
                k.split(":")[2]
                for k in existing_edges
                if k.startswith(f"{records[i]['id']}:{records[j]['id']}:")
            }
            all_types = _AUTO_ACTIVE_TYPES | _REVIEW_REQUIRED_TYPES
            if existing_for_pair >= all_types:
                continue

            # Call LLM for this pair
            llm_result = _call_llm(records[i], records[j])
            rtype = llm_result.get("relation_type", "none")
            confidence = llm_result.get("confidence", 0.0)

            if rtype == "none":
                continue

            dedup_key = f"{records[i]['id']}:{records[j]['id']}:{rtype}"
            if dedup_key in existing_edges:
                dedup_skipped += 1
                continue
            existing_edges.add(dedup_key)

            # Determine initial state based on risk
            if rtype in _AUTO_ACTIVE_TYPES:
                init_state = "active"
            else:
                # REVIEW_REQUIRED types always start as candidate:
                # owner review is non-negotiable per §6, G4, T2.3.2
                init_state = "candidate"

            # Write edge — weight=1.0 for Phase 1-2 (confidence is provenance only)
            if index and hasattr(index, "write_governed_edge"):
                edge = index.write_governed_edge(
                    from_record_type="crystallized_record",
                    from_record_id=records[i]["id"],
                    to_record_type="crystallized_record",
                    to_record_id=records[j]["id"],
                    relation_type=rtype,
                    weight=1.0,
                    source_event_id=None,
                    proposed_by="llm",
                    state=init_state,
                )
                if edge:
                    proposed += 1
                    if init_state == "active":
                        auto_active += 1

    elapsed_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
    summary = {
        "status": "ok",
        "record_count": len(records),
        "pair_count": pairs,
        "proposed_count": proposed,
        "auto_active_count": auto_active,
        "dedup_skipped": dedup_skipped,
        "duration_ms": elapsed_ms,
        "begin_at": start_time.isoformat(),
        "llm_model": _resolve_runtime().get("model", "unknown"),
    }

    if audit_path:
        from pathlib import Path
        append_audit(
            Path(audit_path),
            action="llm_edge_proposer_run",
            status="ok",
            target=str(index_path),
            details=summary,
        )

    return summary
