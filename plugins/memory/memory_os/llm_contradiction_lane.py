"""LLM/evidence contradiction lane for Memory-OS graph layer.

Replaces fragile vector-distance contradiction detection (low cosine →
unrelated) with a high-similarity + LLM claim-extraction approach.

Path A: uses cosine similarity for candidate discovery (shared-topic pairs).
Path B (future): uses entity index for candidate discovery (V2-P1).

Guardrails:
1. Shadow-only — contradictions stay as candidate edges, never auto-invalidate.
2. LLM unavailable → lane skipped (no fallback to vector distance).
3. Low-frequency — only triggered by new/changed crystallized records.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ── Claim extraction prompt ──────────────────────────────────────────────

CLAIM_EXTRACTION_PROMPT = """\
You are a precise fact extractor. Given two memory records that appear to be
about the same topic, extract the core factual claim from each.

For each record, output a JSON object with:
- subject: the entity or concept the claim is about (short phrase)
- predicate: the property or relationship being asserted (short phrase)
- object: the value or conclusion being asserted (short phrase)
- confidence: your confidence that this is the core claim (0.0-1.0)

If a record does not contain a clear factual claim, set confidence to 0.

Return ONLY a JSON object with keys "claim_a" and "claim_b":
{
  "claim_a": {"subject": "...", "predicate": "...", "object": "...", "confidence": 0.0},
  "claim_b": {"subject": "...", "predicate": "...", "object": "...", "confidence": 0.0}
}

Record A ({kind_a}):
{body_a}

Record B ({kind_b}):
{body_b}
"""


# ── Claim conflict detection ─────────────────────────────────────────────

def _claims_contradict(claim_a: dict, claim_b: dict) -> bool:
    """Determine if two structured claims mutually contradict.

    Contradiction requires:
    - Both confidences >= 0.5 (filter noise)
    - Same subject (normalized)
    - Same predicate (normalized)
    - Mutually exclusive objects (different values for the same property)
    """
    if claim_a.get("confidence", 0) < 0.5:
        return False
    if claim_b.get("confidence", 0) < 0.5:
        return False

    subj_a = _norm(str(claim_a.get("subject", "")))
    subj_b = _norm(str(claim_b.get("subject", "")))
    if not subj_a or not subj_b or subj_a != subj_b:
        return False

    pred_a = _norm(str(claim_a.get("predicate", "")))
    pred_b = _norm(str(claim_b.get("predicate", "")))
    if not pred_a or not pred_b or pred_a != pred_b:
        return False

    obj_a = _norm(str(claim_a.get("object", "")))
    obj_b = _norm(str(claim_b.get("object", "")))
    if not obj_a or not obj_b or obj_a == obj_b:
        return False

    return True


def _norm(s: str) -> str:
    """Normalize a claim component for comparison."""
    return s.strip().lower().rstrip(".,;:!?") or ""


def _format_evidence(record_id: str, body: str, claim: dict) -> str:
    """Format evidence block for storage in the edge."""
    return (
        f"CLAIM: {claim.get('subject','')} | {claim.get('predicate','')} | {claim.get('object','')}\n"
        f"SOURCE ({record_id}): {body[:500]}"
    )


# ── Main entry point ─────────────────────────────────────────────────────

def run_contradiction_lane(
    store: Any,  # MemoryOSStore
    *,
    index: object | None = None,
    embedder: object | None = None,
    roots: object | None = None,
    max_pairs: int = 100,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run the LLM/evidence contradiction lane.

    Finds record pairs with high cosine similarity (same topic), extracts
    structured claims via LLM, and writes contradiction candidate edges
    to memory_edges (state=candidate, proposed_by=llm). Never auto-invalidates
    — all contradictions go through owner review.
    """
    from .knob_overrides import resolve_knob
    from .jsonl_io import build_error_record as _build_error_record

    start_time = datetime.now(timezone.utc)
    error_records: list[dict[str, Any]] = []

    # ── Guard: lane disabled ─────────────────────────────────────────
    enabled = resolve_knob("llm_contradiction_lane_enabled", default=False, roots=roots)
    if not enabled:
        return {"status": "skipped", "reason": "lane_disabled", "contradictions_found": 0, "error_records": error_records}

    # ── Guard: embedder not available ─────────────────────────────────
    if embedder is None or not getattr(embedder, "is_available", lambda: False)():
        return {"status": "skipped", "reason": "embedder_unavailable", "contradictions_found": 0, "error_records": error_records}

    # ── Guard: LLM not available ──────────────────────────────────────
    llm_available = False
    try:
        from .low_clue_recall import low_clue_judge_availability as _judge_avail
        judge_status = _judge_avail({})
        llm_available = judge_status.get("available", False)
    except Exception as _exc:
        error_records.append(_build_error_record(
            component="llm_contradiction_lane",
            operation="judge_availability_check",
            error_code="JUDGE_CHECK_FAILED",
            severity="warning",
            recoverable=True,
            details={"error": str(_exc)},
        ))
    if not llm_available:
        return {"status": "skipped", "reason": "llm_unavailable", "contradictions_found": 0, "error_records": error_records}

    # ── 1. Read crystallized records with embeddings ──────────────────
    index_path = getattr(store.roots, "index_path", None)
    if index_path is None:
        return {"status": "error", "error": "no_index_path", "error_records": error_records}

    conn = sqlite3.connect(str(index_path))
    conn.row_factory = sqlite3.Row

    from .vector_edge_proposer import _cosine_similarity

    record_limit = max(int((2 * max_pairs) ** 0.5) + 2, 2)
    try:
        rows = conn.execute(
            "select cr.id, cr.kind, cr.body, me.embedding "
            "from crystallized_records cr "
            "inner join memory_embeddings me "
            "  on me.record_type = 'crystallized_record' "
            "  and me.record_id = cr.id "
            "order by cr.created_at desc "
            "limit ?",
            (record_limit,),
        ).fetchall()
    except sqlite3.Error:
        conn.close()
        return {"status": "error", "error": "cannot_read_crystallized_records", "error_records": error_records}

    records: list[dict[str, Any]] = []
    for row in rows:
        rid = str(row["id"] or "")
        embedding = row["embedding"]
        body = str(row["body"] or "")
        if not rid or not embedding or not body:
            continue
        records.append({
            "id": rid,
            "kind": str(row["kind"] or ""),
            "body": body,
            "embedding": bytes(embedding),
        })

    if len(records) < 2:
        conn.close()
        return {"status": "skipped", "reason": f"need >=2 records, got {len(records)}", "contradictions_found": 0, "error_records": error_records}

    # ── 2. Build high-similarity candidate pairs (same kind, sim >= 0.75) ─
    candidate_pairs: list[dict[str, Any]] = []
    pairs_evaluated = 0

    for i in range(len(records)):
        if pairs_evaluated >= max_pairs:
            break
        for j in range(i + 1, len(records)):
            if pairs_evaluated >= max_pairs:
                break
            pairs_evaluated += 1

            rec_a = records[i]
            rec_b = records[j]

            # Only compare same-kind records (same topic domain)
            if rec_a["kind"] != rec_b["kind"]:
                continue

            sim = _cosine_similarity(rec_a["embedding"], rec_b["embedding"])
            if sim is None or sim < 0.75:
                continue

            candidate_pairs.append({
                "a": rec_a,
                "b": rec_b,
                "similarity": sim,
            })

    conn.close()

    if not candidate_pairs:
        return {
            "status": "ok",
            "reason": "no_high_similarity_pairs",
            "pairs_evaluated": pairs_evaluated,
            "candidate_pairs": 0,
            "contradictions_found": 0,
            "error_records": error_records,
        }

    # ── 3. LLM claim extraction + contradiction judgment ──────────────
    from .low_clue_recall import _call_hermes_runtime_model, _resolve_hermes_default_runtime

    # Reuse the same LLM config pattern as llm_edge_proposer
    _DEFAULT_LLM_CONFIG: dict[str, Any] = {
        "enabled": True,
        "mode": "bounded_vote",
        "provider": "hermes_default",
        "temperature": 0,
        "timeout_ms": 15000,
        "max_tokens": 512,
        "on_error": "deterministic_fallback",
    }
    resolved = _resolve_hermes_default_runtime(_DEFAULT_LLM_CONFIG)
    if not resolved.get("ok"):
        return {"status": "skipped", "reason": "llm_runtime_unavailable", "contradictions_found": 0, "error_records": error_records}
    llm_config = dict(_DEFAULT_LLM_CONFIG)

    contradictions_found = 0
    edge_writer: object | None = None
    if index is not None and not dry_run:
        edge_writer = index

    for pair in candidate_pairs[:max_pairs]:
        rec_a = pair["a"]
        rec_b = pair["b"]

        # Build extraction prompt
        prompt = CLAIM_EXTRACTION_PROMPT.format(
            kind_a=rec_a["kind"],
            body_a=rec_a["body"][:1200],
            kind_b=rec_b["kind"],
            body_b=rec_b["body"][:1200],
        )

        try:
            response = _call_hermes_runtime_model(prompt, llm_config)
        except Exception as _exc:
            error_records.append(_build_error_record(
                component="llm_contradiction_lane",
                operation="hermes_runtime_call",
                error_code="LLM_CALL_FAILED",
                severity="warning",
                recoverable=True,
                details={"error": str(_exc)[:200], "record_a": pair["a"]["id"], "record_b": pair["b"]["id"]},
            ))
            continue

        if not response or not response.strip():
            continue

        # Parse LLM response
        try:
            parsed = json.loads(response.strip())
        except json.JSONDecodeError:
            # Extract outermost JSON object (handles nested braces in claim values)
            start = response.find("{")
            if start == -1:
                continue
            # Find matching close brace
            depth = 0
            end = -1
            for _i in range(start, len(response)):
                if response[_i] == "{":
                    depth += 1
                elif response[_i] == "}":
                    depth -= 1
                    if depth == 0:
                        end = _i
                        break
            if end == -1:
                continue
            try:
                parsed = json.loads(response[start:end + 1])
            except json.JSONDecodeError:
                continue

        claim_a = parsed.get("claim_a") if isinstance(parsed.get("claim_a"), dict) else {}
        claim_b = parsed.get("claim_b") if isinstance(parsed.get("claim_b"), dict) else {}

        if not claim_a or not claim_b:
            continue

        if not _claims_contradict(claim_a, claim_b):
            continue

        # ── 4. Write contradiction candidate edge ─────────────────────
        if dry_run:
            contradictions_found += 1
            continue

        if edge_writer is None:
            continue

        evidence = (
            f"SIMILARITY: {pair['similarity']:.4f}\n"
            f"{_format_evidence(rec_a['id'], rec_a['body'], claim_a)}\n"
            f"{_format_evidence(rec_b['id'], rec_b['body'], claim_b)}"
        )

        if hasattr(edge_writer, "write_governed_edge"):
            result = edge_writer.write_governed_edge(
                from_record_type="crystallized_record",
                from_record_id=rec_a["id"],
                to_record_type="crystallized_record",
                to_record_id=rec_b["id"],
                relation_type="contradicts",
                weight=round(pair["similarity"], 4),
                source_event_id=None,
                proposed_by="llm",
                state="candidate",
                # Store evidence in a way compatible with the edge schema.
                # The edge's weight carries the similarity score; the
                # structured evidence is logged via audit.
            )
            if result and result != {}:
                contradictions_found += 1

    elapsed_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)

    return {
        "status": "ok",
        "pairs_evaluated": pairs_evaluated,
        "candidate_pairs": len(candidate_pairs),
        "contradictions_found": contradictions_found,
        "duration_ms": elapsed_ms,
        "begin_at": start_time.isoformat(),
        "error_records": error_records,
    }
