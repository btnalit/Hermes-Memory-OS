"""LLM-class edge proposer — uses the Hermes runtime LLM for semantic analysis.

Phase 2.3 — calls the configured LLM (via low_clue_recall._call_hermes_runtime_model_result)
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

from . import jev_backend
from .audit import append_audit
from .low_clue_recall import LlmCallResult, _call_hermes_runtime_model_result, _resolve_hermes_default_runtime


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


def _call_diagnostics(call_result: LlmCallResult | None) -> dict[str, Any]:
    """Typed transport diagnostics to fold onto a ``_call_llm`` result (W2).

    ``llm_transport_failure_reason`` is the RAW closed-set reason from
    :class:`LlmCallResult` -- distinct from this module's own ``outcome``
    vocabulary (llm_call_exception/empty_llm_response/parse_failed/
    not_a_dict/invalid_confidence), which additionally covers post-transport
    parsing/schema failures the transport layer knows nothing about.
    """
    if call_result is None:
        return {}
    diagnostics: dict[str, Any] = {
        "llm_transport_failure_reason": call_result.failure_reason,
        "llm_provider": call_result.provider,
        "llm_model": call_result.model,
        "llm_transport": call_result.transport,
    }
    if call_result.usage:
        diagnostics["llm_usage_prompt_tokens"] = call_result.usage.get("prompt_tokens")
        diagnostics["llm_usage_completion_tokens"] = call_result.usage.get("completion_tokens")
    return diagnostics


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
        call_result = _call_hermes_runtime_model_result(prompt, _DEFAULT_LLM_CONFIG)
    except Exception:
        # Defensive only: _call_hermes_runtime_model_result is designed to
        # never raise (every failure is a typed LlmCallResult).
        return {
            "relation_type": "none", "confidence": 0.0,
            "reasoning": "llm_call_exception", "outcome": "llm_call_exception",
        }

    if call_result.failure_reason == "llm_empty_content" or not call_result.text.strip():
        return {
            "relation_type": "none", "confidence": 0.0,
            "reasoning": "empty_llm_response", "outcome": "empty_llm_response",
            **_call_diagnostics(call_result),
        }
    if call_result.failure_reason:
        # Any other typed transport failure -- collapse to this module's
        # pre-existing "llm_call_exception" bucket (matching the pre-W2
        # behavior where every non-empty-response failure was a bare "").
        return {
            "relation_type": "none", "confidence": 0.0,
            "reasoning": "llm_call_exception", "outcome": "llm_call_exception",
            **_call_diagnostics(call_result),
        }

    response = call_result.text

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
            **_call_diagnostics(call_result),
        }

    if not isinstance(parsed, dict):
        return {
            "relation_type": "none", "confidence": 0.0,
            "reasoning": "not_a_dict", "outcome": "not_a_dict",
            **_call_diagnostics(call_result),
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
            **_call_diagnostics(call_result),
        }
    reasoning = str(parsed.get("reasoning", ""))

    return {
        "relation_type": rtype,
        "confidence": min(max(confidence, 0.0), 1.0),
        "reasoning": reasoning,
        "outcome": "ok",
        **_call_diagnostics(call_result),
    }


# ── J2: Jev native-choice mapping (owner ruling 2026-09-23) ─────────────
# TypeSafe's own selection guidance: "Choice should be used when the answer
# is one of a known set of options with no order between them... If two
# types both seem to fit, prefer the one whose answer your code can act on
# directly." (https://docs.typesafe.ai/primitives.md) -- this lane's
# pick-one-of-five relation type is exactly that shape, and each answer
# maps straight onto write_governed_edge's relation_type argument below.
#
# Options and their one-line descriptions are lifted VERBATIM from
# _RELATION_PROMPT_TEMPLATE's bullet list above, kept as an independent
# mapping rather than re-templating the free-text prompt from shared data
# -- the same deliberate separation fact_judge.py's _JEV_NOUL_* constants
# keep from _JUDGE_SYSTEM_PROMPT (owner explicitly rejected wrapping the
# free-text prompt as a single low-fidelity question). If the prompt's
# relation descriptions change, update this dict to match.
_JEV_RELATION_CHOICE_INSTRUCTIONS = (
    "You are analyzing crystallized memory records in a governance system. "
    "Determine the relationship between Record A and Record B described in "
    "the state below, choosing exactly one option."
)
_JEV_RELATION_CHOICE_CRITERIA: dict[str, str] = {
    "refines": "Record A is a refinement/extension of Record B (or vice versa)",
    "contradicts": "The records express contradictory positions on the same topic",
    "depends_on": "One record logically depends on the other",
    "co_occurs": "The records are related by context (same topic, same session) but not refinement/contradiction/dependency",
    "none": "No meaningful relationship",
}


def _build_jev_choice_state(record_a: dict[str, Any], record_b: dict[str, Any]) -> dict[str, Any]:
    """Structured record_a/record_b state for the Jev choice call -- same
    clip bound (500 chars) _call_llm's free-text prompt uses for body text,
    independent of jev_backend's own defensive _clip_state floor."""
    return {
        "record_a": {
            "kind": str(record_a.get("kind", "")),
            "tags": _format_tags(record_a.get("tags_json", [])),
            "body": str(record_a.get("body", "") or "")[:500],
        },
        "record_b": {
            "kind": str(record_b.get("kind", "")),
            "tags": _format_tags(record_b.get("tags_json", [])),
            "body": str(record_b.get("body", "") or "")[:500],
        },
    }


def _format_jev_reasoning(choice: str, confidence: float | None, probabilities: dict[str, float] | None) -> str:
    """Synthesize a reasoning string for parity with _call_llm's return
    shape. See the "reasoning" field note on _call_jev below -- no consumer
    reads this value beyond this module's own pair loop, so its exact
    content is not load-bearing."""
    prob = probabilities.get(choice) if isinstance(probabilities, dict) else None
    prob_text = f"{prob:.2f}" if isinstance(prob, (int, float)) else "?"
    conf_text = f"{confidence:.2f}" if isinstance(confidence, (int, float)) else "?"
    return f"jev_choice={choice}_probability={prob_text}_confidence={conf_text}"[:200]


def _call_jev(
    record_a: dict[str, Any],
    record_b: dict[str, Any],
    *,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ask Jev's native choice primitive for the relationship between two
    records. Returns a dict shaped like _call_llm's return value
    (relation_type, confidence, reasoning, outcome) on success, so
    run_llm_proposer's pair loop can treat a Jev success identically to a
    hermes_default success.

    On ANY failure -- transport, wire-contract (non-"choice" answer type or
    a choice outside the offered options, both rejected inside
    jev_backend.judge_choice), or a caller-side closed-set mismatch -- this
    returns ``outcome: "jev_failed"`` plus ``jev_failure_reason``/
    ``jev_failure_detail`` so the caller can fall back to _call_llm and
    count the fallback. Never raises, and never returns "none" as a
    disguised failure -- "none" is only ever a legitimate Jev *answer*.

    ``reasoning``: grepped project-wide (see module docstring at top of
    this file for the search) -- _call_llm's own "reasoning" field has
    exactly one consumer, this module's pair loop, which never reads it
    either (only relation_type/confidence feed write_governed_edge). No
    field a consumer reads is being dropped; the synthesized string below
    exists only for shape parity with _call_llm's return value.
    """
    state = _build_jev_choice_state(record_a, record_b)
    result = jev_backend.judge_choice(
        question_id="relation_type",
        instructions=_JEV_RELATION_CHOICE_INSTRUCTIONS,
        criteria=_JEV_RELATION_CHOICE_CRITERIA,
        state=state,
        config=config if config is not None else _DEFAULT_LLM_CONFIG,
    )
    if result.failure_reason:
        return {
            "relation_type": "none", "confidence": 0.0, "reasoning": "",
            "outcome": "jev_failed",
            "jev_failure_reason": result.failure_reason,
            "jev_failure_detail": result.detail,
        }

    # Defense in depth: jev_backend.judge_choice already rejects any choice
    # outside the criteria keys it was sent (a generic wire-contract check),
    # so this can only fire if that guard is ever loosened -- but the
    # domain-level closed-set requirement belongs at this layer too (see
    # CLAUDE.md's "a gate whose vocabulary drifts from its producer's
    # checks nothing, silently").
    rtype = result.choice
    if rtype not in _JEV_RELATION_CHOICE_CRITERIA:
        return {
            "relation_type": "none", "confidence": 0.0, "reasoning": "",
            "outcome": "jev_failed",
            "jev_failure_reason": "llm_parse_failed",
            "jev_failure_detail": _clip_detail(f"choice_outside_closed_set:{rtype}"),
        }

    return {
        "relation_type": rtype,
        "confidence": result.confidence if result.confidence is not None else 0.0,
        "reasoning": _format_jev_reasoning(rtype, result.confidence, result.probabilities),
        "outcome": "ok",
        "judge_backend": jev_backend.JEV_BACKEND_NAME,
        "jev_model": result.model,
        "jev_latency_ms": result.latency_ms,
    }


def _clip_detail(text: str, limit: int = 160) -> str:
    return text[:limit]


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
    roots: Any | None = None,
) -> dict[str, Any]:
    """Run the LLM-class edge proposer across all crystallized record pairs.

    Calls the configured Hermes runtime LLM for each pair to determine
    relationships. Low-risk edges auto-promote to active.

    Args:
        index_path: Path to the index DB.
        index: MemoryOSIndex instance (needed for edge writing).
        audit_path: Optional audit path.
        roots: MemoryOSRoots for knob resolution (``llm_edge_proposer_judge_backend``);
            falls back to ``index.roots`` when omitted, and to the
            "hermes_default" knob default when neither is available (same
            fallback shape as ``run_vector_proposer``).

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

    J2 (owner ruling 2026-09-23): when the ``llm_edge_proposer_judge_backend``
    knob selects ``"typesafe_jev"`` (default stays ``"hermes_default"``,
    resolved once per run below), each pair first asks Jev's native choice
    primitive for the relation type; ANY Jev failure (transport or wire-
    contract) falls back to the unchanged ``_call_llm`` path for that same
    pair -- never straight to "none" -- and the fallback is typed and
    counted (``judge_backend_fallback_count``/``_reasons``/
    ``_detail_sample`` in the summary below), mirroring fact_judge.py's J1
    contract. When the knob stays at its default, this changes nothing
    below -- default-off is byte-identical.
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

    # J2: judge_backend knob resolved ONCE per run (same precedence/timing
    # as fact_judge.run_fact_judge_lane resolving it once per tick, not per
    # candidate) -- a cheap single-file read, not per-pair. Default
    # "hermes_default" is untouched by this resolution when no override is
    # registered, so the rest of the run behaves exactly as before J2.
    from .knob_overrides import resolve_knob as _resolve_knob

    _effective_roots = roots if roots is not None else getattr(index, "roots", None)
    judge_backend = str(
        _resolve_knob(
            "llm_edge_proposer_judge_backend",
            default="hermes_default",
            roots=_effective_roots,
        )
        or "hermes_default"
    )
    if judge_backend not in ("hermes_default", jev_backend.JEV_BACKEND_NAME):
        judge_backend = "hermes_default"

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
    # W2: typed LLM transport diagnostics, aggregated across this run's calls.
    llm_transport_failures_by_reason: dict[str, int] = {}
    llm_transport_provider = ""
    llm_transport_model = ""
    llm_transport_name = ""
    llm_usage_prompt_tokens = 0
    llm_usage_completion_tokens = 0
    # J2: optional Jev backend diagnostics, aggregated across this run.
    judge_backend_fallback_count = 0
    judge_backend_fallback_reasons: dict[str, int] = {}
    judge_backend_fallback_detail_sample = ""

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

            # Call LLM for this pair. J2: when selected, try Jev's native
            # choice primitive first; ANY Jev failure falls back to the
            # unchanged _call_llm path below for this same pair (never
            # straight to "none"), typed and counted. When judge_backend
            # stays "hermes_default" (the default), this is exactly the
            # pre-J2 single call -- default-off is byte-identical.
            if judge_backend == jev_backend.JEV_BACKEND_NAME:
                jev_result = _call_jev(records[i], records[j])
                if jev_result.get("outcome") == "ok":
                    llm_result = jev_result
                else:
                    judge_backend_fallback_count += 1
                    jev_reason = str(jev_result.get("jev_failure_reason") or "")
                    judge_backend_fallback_reasons[jev_reason] = (
                        judge_backend_fallback_reasons.get(jev_reason, 0) + 1
                    )
                    judge_backend_fallback_detail_sample = _clip_detail(
                        str(jev_result.get("jev_failure_detail") or "")
                    )
                    llm_result = _call_llm(records[i], records[j])
            else:
                llm_result = _call_llm(records[i], records[j])
            llm_call_count += 1
            call_outcome = str(llm_result.get("outcome", "ok"))
            if call_outcome == "ok":
                llm_ok_count += 1
            else:
                llm_failure_reasons[call_outcome] = llm_failure_reasons.get(call_outcome, 0) + 1
            # ── W2 transport diagnostics ─────────────────────────────────
            transport_reason = str(llm_result.get("llm_transport_failure_reason") or "")
            if transport_reason:
                llm_transport_failures_by_reason[transport_reason] = (
                    llm_transport_failures_by_reason.get(transport_reason, 0) + 1
                )
            if llm_result.get("llm_provider"):
                llm_transport_provider = str(llm_result["llm_provider"])
            if llm_result.get("llm_model"):
                llm_transport_model = str(llm_result["llm_model"])
            if llm_result.get("llm_transport"):
                llm_transport_name = str(llm_result["llm_transport"])
            llm_usage_prompt_tokens += int(llm_result.get("llm_usage_prompt_tokens") or 0)
            llm_usage_completion_tokens += int(llm_result.get("llm_usage_completion_tokens") or 0)
            # ─────────────────────────────────────────────────────────────
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
        # W2: typed LLM transport diagnostics (ADD-only; llm_call_failure_reasons
        # above keeps its pre-W2 "outcome" vocabulary/meaning unchanged).
        "llm_transport_failures_by_reason": llm_transport_failures_by_reason,
        "llm_transport_provider": llm_transport_provider,
        "llm_transport_model": llm_transport_model,
        "llm_transport": llm_transport_name,
        "llm_usage_prompt_tokens": llm_usage_prompt_tokens,
        "llm_usage_completion_tokens": llm_usage_completion_tokens,
        # J2: optional Jev judge-backend diagnostics (ADD-only). judge_backend
        # is the resolved backend for this run ("hermes_default" unless the
        # llm_edge_proposer_judge_backend knob selects "typesafe_jev").
        # judge_backend_fallback_count/reasons count pairs where Jev was
        # selected but failed and this pair fell back to _call_llm --
        # Completion Is Not Output: a clean envelope alone cannot distinguish
        # "Jev worked" from "Jev failed and fell back silently" without this
        # (same contract as fact_judge.py's J1 fields).
        "judge_backend": judge_backend,
        "judge_backend_fallback_count": judge_backend_fallback_count,
        "judge_backend_fallback_reasons": judge_backend_fallback_reasons,
        "judge_backend_fallback_detail_sample": judge_backend_fallback_detail_sample,
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
