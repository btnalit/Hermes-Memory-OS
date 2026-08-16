"""LLM-class edge proposer — uses the Hermes runtime LLM for semantic analysis.

Phase 2.3 — calls the configured LLM (via low_clue_recall._call_hermes_runtime_model)
to determine relationships between crystallized record pairs.

R1 (owner 决策 2026-08-06): all relation types are auto-active — the graph
is a derived advisory projection that updates itself; wrong edges are
demoted by the weight-feedback loop, not by owner review (supersedes the
old §6/G4/T2.3.2 review-required contract).
Confidence is stored as provenance metadata.
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
# R1 (owner 决策 2026-08-06): 动态图谱全自动 — 全部关系类型 auto-active。
# 边是派生投影(advisory),不触碰 OwnerGate 永久边界;contradicts 的下游
# 消费(crystallization_gate)只产 owner 可见标记,自动生效不执行任何动作。
# 错误的边由权重反馈闭环(命中加权/无命中遗忘)动态淘汰。
_AUTO_ACTIVE_TYPES = frozenset(
    {"co_occurs", "evidence_for", "refines", "contradicts", "depends_on"}
)

# Relation types that stay candidate (needs owner review).
_REVIEW_REQUIRED_TYPES = frozenset()  # R1: no relation type requires owner review

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

    Returns a dict with keys: relation_type, confidence, reasoning, outcome.
    ``outcome`` is a closed-set typed failure value ("ok" on success) mirroring
    fact_judge.py's failure_reason typing — llm_call_exception / empty_llm_response
    / parse_failed / not_a_dict / invalid_confidence. Never raises: every failure
    path (including a non-numeric or null "confidence" field, which previously
    propagated a bare ValueError/TypeError out of this function) returns a typed
    failure dict with relation_type "none" and confidence 0.0 instead.
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
        return {
            "relation_type": "none", "confidence": 0.0,
            "reasoning": "llm_call_exception", "outcome": "llm_call_exception",
        }

    if not response or not response.strip():
        return {
            "relation_type": "none", "confidence": 0.0,
            "reasoning": "empty_llm_response", "outcome": "empty_llm_response",
        }

    # Parse JSON from response (handle wrapping markdown code fences)
    json_str = response.strip()
    if "```json" in json_str:
        json_str = json_str.split("```json")[1].split("```")[0].strip()
    elif "```" in json_str:
        json_str = json_str.split("```")[1].split("```")[0].strip()

    try:
        parsed = json.loads(json_str)
    except (json.JSONDecodeError, TypeError):
        return {
            "relation_type": "none", "confidence": 0.0,
            "reasoning": "parse_failed", "outcome": "parse_failed",
        }

    if not isinstance(parsed, dict):
        return {
            "relation_type": "none", "confidence": 0.0,
            "reasoning": "not_a_dict", "outcome": "not_a_dict",
        }

    rtype = str(parsed.get("relation_type", "none")).strip().lower()
    if rtype not in ("refines", "contradicts", "depends_on", "co_occurs", "none"):
        rtype = "none"

    # D1 fix: the model reply's "confidence" field is untrusted input — a
    # non-numeric string (e.g. "high") raises ValueError, null raises
    # TypeError. Both used to propagate out of this function (and out of
    # run_llm_proposer's pair loop) with no failure typing, ending the run
    # after partial writes. Type it the way fact_judge.py types LLM-reply
    # failures: a typed failure dict, never a raised exception.
    try:
        confidence = float(parsed.get("confidence", 0.0))
    except (TypeError, ValueError):
        return {
            "relation_type": "none", "confidence": 0.0,
            "reasoning": "invalid_confidence", "outcome": "invalid_confidence",
        }
    reasoning = str(parsed.get("reasoning", ""))

    return {
        "relation_type": rtype,
        "confidence": min(max(confidence, 0.0), 1.0),
        "reasoning": reasoning,
        "outcome": "ok",
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
) -> dict[str, Any]:
    """Run the LLM-class edge proposer across all crystallized record pairs.

    Calls the configured Hermes runtime LLM for each pair to determine
    relationships. Low-risk edges auto-promote to active.

    Args:
        index_path: Path to the index DB.
        index: MemoryOSIndex instance (needed for edge writing).
        audit_path: Optional audit path.

    Every eligible pair makes its own sequential LLM round-trip (up to
    _MAX_PAIRS=100, each bounded by _DEFAULT_LLM_CONFIG["timeout_ms"]).
    D2: this function used to accept a dead ``batch`` parameter, documented
    as "batches all pairs into a single LLM call (cheaper)" but never read
    anywhere in the body — no caller ever passed it (grepped repo-wide), so
    it was removed rather than wired up. There is no batched call path;
    real batching would be a behavior change beyond this fix.

    Returns a summary dict. ``status`` is "ok" unless at least one pair's
    LLM call failed this run, in which case it is "degraded" — see
    ``llm_call_failure_count`` / ``llm_call_failure_reasons`` for the typed
    breakdown and ``outcome`` for a closed-set characterization of what the
    run produced (no_eligible_pairs / llm_degraded / no_relationships_found
    / produced), so "the judge found nothing" is distinguishable from "the
    judge could not be reached" without re-running or reading source.
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

    # ── Guard: LLM not available ──────────────────────────────────────
    runtime = _resolve_runtime()
    if not runtime.get("ok"):
        return {
            "status": "skipped",
            "reason": "llm_runtime_unavailable",
            "code": runtime.get("code", "resolve_failed"),
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

    # 2. Collect existing edges to avoid wasted LLM calls.
    # W1/E2: this is an OPTIMIZATION only — the dedup AUTHORITY lives at the
    # write boundary (index.write_governed_edge).  The previous query_edges
    # pre-check was capped at limit=1000 and silently defeated once the
    # backlog crossed that cap; this scan has no limit.
    existing_edges: set[str] = set()
    try:
        conn3 = sqlite3.connect(index_path)
        try:
            rows3 = conn3.execute(
                "select from_record_id, to_record_id, relation_type"
                " from memory_edges where state != 'invalidated'"
            ).fetchall()
        finally:
            conn3.close()
        for _a, _b, _r in rows3:
            existing_edges.add(f"{_a}:{_b}:{_r}")
    except sqlite3.Error:
        pass

    # W1/E3 pair de-bias: records the llm proposer has not yet linked come
    # first, so the oldest records cannot consume the pair budget forever.
    from .structural_edge_proposer import _order_records_unedged_first
    records = _order_records_unedged_first(records, index_path, proposed_by="llm")

    # 3. Build pairs and call LLM
    pairs = 0
    proposed = 0
    auto_active = 0
    dedup_skipped = 0
    # D2b: per-run _call_llm outcome tally. "Completion Is Not Output" —
    # pair_count=100/proposed_count=0 was byte-identical whether the judge
    # legitimately found no relationships or every call failed; these
    # counters (surfaced in the summary below) make that distinguishable
    # from the summary alone, without re-running or reading source.
    llm_call_count = 0
    llm_ok_count = 0
    llm_failure_reasons: dict[str, int] = {}

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
            llm_call_count += 1
            call_outcome = str(llm_result.get("outcome", "ok"))
            if call_outcome == "ok":
                llm_ok_count += 1
            else:
                llm_failure_reasons[call_outcome] = llm_failure_reasons.get(call_outcome, 0) + 1
            rtype = llm_result.get("relation_type", "none")
            confidence = llm_result.get("confidence", 0.0)

            if rtype == "none":
                continue

            dedup_key = f"{records[i]['id']}:{records[j]['id']}:{rtype}"
            if dedup_key in existing_edges:
                dedup_skipped += 1
                continue
            existing_edges.add(dedup_key)

            # R1: all relation types are auto-active (owner 决策 2026-08-06,
            # 取代旧的 §6/G4/T2.3.2 需审契约 — 动态图谱不占审批带宽)。
            init_state = "active"

            # P3:出生权重 = 0.45 + 0.30 × confidence — confidence 本就被
            # _call_llm 采集,旧实现写入时硬编码 1.0 丢弃(出生即饱和,
            # 权重排序与命中强化双双失效)。
            if index and hasattr(index, "write_governed_edge"):
                from .edge_weights import llm_birth_weight

                edge = index.write_governed_edge(
                    from_record_type="crystallized_record",
                    from_record_id=records[i]["id"],
                    to_record_type="crystallized_record",
                    to_record_id=records[j]["id"],
                    relation_type=rtype,
                    weight=llm_birth_weight(confidence),
                    source_event_id=None,
                    proposed_by="llm",
                    state=init_state,
                )
                if edge.get("skipped_duplicate"):
                    dedup_skipped += 1
                elif edge:
                    proposed += 1
                    if init_state == "active":
                        auto_active += 1

    elapsed_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
    llm_failure_count = sum(llm_failure_reasons.values())

    # D2b closed outcome set — what this run actually produced, distinct
    # from "status" (whether calls degraded). See docstring above.
    if llm_call_count == 0:
        run_outcome = "no_eligible_pairs"
    elif llm_ok_count == 0:
        run_outcome = "llm_degraded"
    elif proposed:
        run_outcome = "produced"
    else:
        run_outcome = "no_relationships_found"

    # D2b: status must not lie "ok" through call failures — any typed
    # _call_llm failure this run marks the lane degraded, even if other
    # pairs succeeded and produced edges.
    run_status = "degraded" if llm_failure_count > 0 else "ok"

    summary = {
        "status": run_status,
        "outcome": run_outcome,
        "record_count": len(records),
        "pair_count": pairs,
        "proposed_count": proposed,
        "auto_active_count": auto_active,
        "dedup_skipped": dedup_skipped,
        "llm_call_count": llm_call_count,
        "llm_call_ok_count": llm_ok_count,
        "llm_call_failure_count": llm_failure_count,
        "llm_call_failure_reasons": llm_failure_reasons,
        "duration_ms": elapsed_ms,
        "begin_at": start_time.isoformat(),
        "llm_model": _resolve_runtime().get("model", "unknown"),
    }

    if audit_path:
        from pathlib import Path
        append_audit(
            Path(audit_path),
            action="llm_edge_proposer_run",
            status=run_status,
            target=str(index_path),
            details=summary,
        )

    return summary
