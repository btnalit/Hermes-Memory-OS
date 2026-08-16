"""llm_edge_proposer.py — two verified defect fixes.

D1: ``_call_llm``'s confidence parsing (``float(parsed.get("confidence", 0.0))``)
had no guard. A model reply with a non-numeric confidence (``"high"``) raised
ValueError; ``null`` raised TypeError. Either propagated out of ``_call_llm``
and out of ``run_llm_proposer``'s pair loop *after* some edges from earlier
pairs in the same run had already been written via ``write_governed_edge`` —
ending the run with no summary, no audit entry, and a partially-processed
pair set (the next run re-pays the LLM cost for pairs it never reached).
Fixed by typing the failure the way fact_judge.py (the project's reference
governed-LLM-lane implementation) types LLM-reply failures: a typed failure
dict, never a raised exception.

D2: ``run_llm_proposer``'s ``batch: bool = True`` parameter was documented as
"batches all pairs into a single LLM call (cheaper)" but never read anywhere
in the function body — every run made sequential per-pair calls regardless.
No caller ever passed it (grepped repo-wide: only cognitive_loop.py calls
run_llm_proposer, without ``batch=``), so it was removed rather than wired
up. Additionally, the summary hardcoded ``"status": "ok"`` and never counted
``_call_llm``'s four failure outcomes, so ``pair_count=100, proposed_count=0``
was byte-identical whether the judge legitimately found no relationships or
every call returned garbage. Fixed by tallying every ``_call_llm`` outcome
into the summary (``llm_call_count`` / ``llm_call_ok_count`` /
``llm_call_failure_count`` / ``llm_call_failure_reasons``), a closed-set
``outcome`` value (no_eligible_pairs / llm_degraded / no_relationships_found
/ produced), and a ``status`` that turns "degraded" once any call failed.

All fixtures drive the real producer: ``_call_llm`` / ``run_llm_proposer``
are exercised through a monkeypatched ``_call_hermes_runtime_model`` that
returns real-shaped response strings (JSON text, empty string) — never by
constructing hand-written result dicts, per the project's counterfactual
rule that hand fixtures let counterfactuals pass vacuously.
"""
from __future__ import annotations

import inspect
import json
from typing import Any

import pytest

from plugins.memory.memory_os import llm_edge_proposer
from plugins.memory.memory_os.audit import read_audit_records
from plugins.memory.memory_os.index import MemoryOSIndex
from plugins.memory.memory_os.llm_edge_proposer import _call_llm, run_llm_proposer
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore


# ── Helpers ──────────────────────────────────────────────────────────────


def _store(tmp_path) -> tuple[MemoryOSStore, MemoryOSIndex]:
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="llm-edge-proposer-test")
    store = MemoryOSStore(roots)
    store.initialize()
    index = MemoryOSIndex(roots)
    index.rebuild_from_store(store)
    return store, index


def _seed_canonical_crystallized(store: MemoryOSStore, records: list[dict[str, Any]]) -> None:
    """Write canonical crystallized record files directly so index rebuild
    picks them up (mirrors test_memory_os_graph_layer.py's producer-backed
    seed helper — ``store.append_crystallized_record`` is the direct
    file-append primitive and does not require canonical-write authority,
    unlike ``CrystallizedMemoryService.write_approved_record``)."""
    for rec in records:
        frontmatter = {
            "schema_version": "memory-os.crystallized.v0",
            "id": rec["id"],
            "kind": rec.get("kind", "test"),
            "created_at": rec.get("created_at", "2026-06-01T00:00:00Z"),
            "approved_by": "owner",
            "approved_at": rec.get("created_at", "2026-06-01T00:00:00Z"),
            "approval_purpose": "test",
            "approval_note": "test seed",
            "source_event_ids": rec.get("source_event_ids", []),
            "tags": rec.get("tags", []),
            "sensitivity": "private",
            "hindsight_indexed": False,
            "bridge_state": "active",
        }
        body = rec.get("body", "test crystallized record body")
        store.append_crystallized_record("test_llm_edge_proposer.md", frontmatter, body)


def _ok_runtime(config: dict[str, Any]) -> dict[str, Any]:
    """Stand-in for ``_resolve_hermes_default_runtime`` reporting the LLM
    runtime as available, so run_llm_proposer proceeds past its availability
    guard instead of hitting the (already-tested, unrelated) skip branch."""
    return {"ok": True, "model": "test-model", "runtime": {"api_mode": "chat_completions"}}


def _queued_responses(monkeypatch: pytest.MonkeyPatch, responses: list[str]) -> list[str]:
    """Monkeypatch _call_hermes_runtime_model (the real producer surface
    _call_llm consumes) to return *responses* in call order. Records prompts
    seen, for assertions that don't care about exact per-pair mapping."""
    queue = list(responses)
    prompts_seen: list[str] = []

    def _fake(prompt: str, config: dict[str, Any]) -> str:
        prompts_seen.append(prompt)
        return queue.pop(0) if queue else ""

    monkeypatch.setattr(llm_edge_proposer, "_call_hermes_runtime_model", _fake)
    return prompts_seen


_VALID_REFINES_JSON = json.dumps(
    {"relation_type": "refines", "confidence": 0.8, "reasoning": "B extends A"}
)
_VALID_NONE_JSON = json.dumps(
    {"relation_type": "none", "confidence": 0.0, "reasoning": "unrelated"}
)


# ═══════════════════════════════════════════════════════════════════════════
# D1 — _call_llm confidence guard (unit level)
# ═══════════════════════════════════════════════════════════════════════════


def test_call_llm_non_numeric_confidence_returns_typed_failure(monkeypatch):
    """D1 counterfactual: {"confidence": "high"} used to raise ValueError out
    of the unguarded float() call. Must now return a typed failure dict."""
    monkeypatch.setattr(
        llm_edge_proposer, "_call_hermes_runtime_model",
        lambda prompt, config: json.dumps(
            {"relation_type": "refines", "confidence": "high", "reasoning": "x"}
        ),
    )
    result = _call_llm({"kind": "note", "body": "a"}, {"kind": "note", "body": "b"})
    assert result["outcome"] == "invalid_confidence"
    assert result["relation_type"] == "none"
    assert result["confidence"] == 0.0


def test_call_llm_null_confidence_returns_typed_failure(monkeypatch):
    """D1 counterfactual: {"confidence": null} used to raise TypeError out of
    the unguarded float(None) call. Must now return a typed failure dict."""
    monkeypatch.setattr(
        llm_edge_proposer, "_call_hermes_runtime_model",
        lambda prompt, config: '{"relation_type": "refines", "confidence": null, "reasoning": "x"}',
    )
    result = _call_llm({"kind": "note", "body": "a"}, {"kind": "note", "body": "b"})
    assert result["outcome"] == "invalid_confidence"
    assert result["relation_type"] == "none"
    assert result["confidence"] == 0.0


def test_call_llm_valid_confidence_still_succeeds(monkeypatch):
    """Regression guard: the D1 try/except must not swallow legitimate
    numeric (including numeric-string) confidence values."""
    monkeypatch.setattr(
        llm_edge_proposer, "_call_hermes_runtime_model",
        lambda prompt, config: json.dumps(
            {"relation_type": "refines", "confidence": "0.7", "reasoning": "ok"}
        ),
    )
    result = _call_llm({"kind": "note", "body": "a"}, {"kind": "note", "body": "b"})
    assert result["outcome"] == "ok"
    assert result["relation_type"] == "refines"
    assert result["confidence"] == pytest.approx(0.7)


# ═══════════════════════════════════════════════════════════════════════════
# D1 — run_llm_proposer survives a bad-confidence pair (run level)
# ═══════════════════════════════════════════════════════════════════════════


def test_run_llm_proposer_survives_invalid_confidence_and_writes_audit(tmp_path, monkeypatch):
    """D1 counterfactual at the run level: before the fix, a single
    bad-confidence pair raised out of the pair loop entirely — no summary,
    no audit entry, next run re-pays the LLM cost for unreached pairs. Must
    now finish cleanly with a summary and a written audit entry."""
    store, index = _store(tmp_path)
    _seed_canonical_crystallized(store, [
        {"id": "cry_conf_a", "created_at": "2026-06-01T10:00:00Z", "body": "Record A body."},
        {"id": "cry_conf_b", "created_at": "2026-06-01T11:00:00Z", "body": "Record B body."},
    ])
    index.rebuild_from_store(store)

    monkeypatch.setattr(llm_edge_proposer, "_resolve_hermes_default_runtime", _ok_runtime)
    _queued_responses(monkeypatch, [
        json.dumps({"relation_type": "refines", "confidence": "high", "reasoning": "x"}),
    ])

    audit_path = store.roots.audit_path
    result = run_llm_proposer(str(index.roots.index_path), index=index, audit_path=str(audit_path))

    assert result["pair_count"] == 1
    assert result["proposed_count"] == 0
    assert result["llm_call_count"] == 1
    assert result["llm_call_failure_count"] == 1
    assert result["llm_call_failure_reasons"] == {"invalid_confidence": 1}
    assert result["status"] == "degraded"

    audit_actions = [rec.get("action") for rec in read_audit_records(audit_path)]
    assert "llm_edge_proposer_run" in audit_actions, (
        f"run must still write its audit entry after an in-pair failure: {audit_actions}"
    )


def test_run_llm_proposer_continues_past_failure_to_later_pairs(tmp_path, monkeypatch):
    """D1 counterfactual: a failure on one pair must not stop the loop from
    reaching and correctly processing the remaining pairs in the same run."""
    store, index = _store(tmp_path)
    _seed_canonical_crystallized(store, [
        {"id": "cry_multi_a", "created_at": "2026-06-01T10:00:00Z", "body": "Record A body."},
        {"id": "cry_multi_b", "created_at": "2026-06-01T11:00:00Z", "body": "Record B body."},
        {"id": "cry_multi_c", "created_at": "2026-06-01T12:00:00Z", "body": "Record C body."},
    ])
    index.rebuild_from_store(store)

    monkeypatch.setattr(llm_edge_proposer, "_resolve_hermes_default_runtime", _ok_runtime)
    # 3 records -> 3 pairs. One bad-confidence failure, one legitimate
    # "none", one real relationship that must still get written.
    _queued_responses(monkeypatch, [
        json.dumps({"relation_type": "refines", "confidence": "high", "reasoning": "x"}),
        _VALID_NONE_JSON,
        _VALID_REFINES_JSON,
    ])

    result = run_llm_proposer(str(index.roots.index_path), index=index)

    assert result["pair_count"] == 3
    assert result["llm_call_count"] == 3
    assert result["llm_call_ok_count"] == 2
    assert result["llm_call_failure_count"] == 1
    assert result["proposed_count"] == 1, (
        "the failure on one pair must not prevent a real edge from a later pair"
    )
    assert result["status"] == "degraded"
    assert result["outcome"] == "produced"


# ═══════════════════════════════════════════════════════════════════════════
# D2a — dead `batch` parameter removed
# ═══════════════════════════════════════════════════════════════════════════


def test_run_llm_proposer_batch_param_removed():
    """D2a counterfactual: `batch` was documented ("batches all pairs into a
    single LLM call (cheaper)") but never read in the function body, and no
    caller passed it (grepped repo-wide: only cognitive_loop.py calls
    run_llm_proposer, never with batch=). Removed rather than wired up.
    Passing it must now raise TypeError, proving the parameter is actually
    gone rather than merely undocumented."""
    sig = inspect.signature(run_llm_proposer)
    assert "batch" not in sig.parameters

    with pytest.raises(TypeError):
        run_llm_proposer("/nonexistent/index.db", index=None, batch=True)  # type: ignore[call-arg]


# ═══════════════════════════════════════════════════════════════════════════
# D2b — per-run _call_llm outcome accounting distinguishes garbage from
# legitimate "no relationships found"
# ═══════════════════════════════════════════════════════════════════════════


def test_garbage_run_distinguishable_from_legitimate_none_run(tmp_path, monkeypatch):
    """D2b counterfactual (the acceptance criterion, verbatim): a run where
    every LLM call returns garbage must be distinguishable from a run where
    the judge genuinely found no relationships, using the returned summary
    alone. Before the fix pair_count/proposed_count were byte-identical in
    both cases and status was an unconditional "ok" — this test proves the
    two runs now diverge on status/outcome/llm_call_failure_count while
    pair_count/proposed_count stay identical (that's precisely why those two
    counters could never carry this distinction on their own)."""
    monkeypatch.setattr(llm_edge_proposer, "_resolve_hermes_default_runtime", _ok_runtime)

    # Run A: every call returns garbage (empty response -> empty_llm_response).
    store_a, index_a = _store(tmp_path / "a")
    _seed_canonical_crystallized(store_a, [
        {"id": "cry_garbage_a", "created_at": "2026-06-01T10:00:00Z", "body": "A"},
        {"id": "cry_garbage_b", "created_at": "2026-06-01T11:00:00Z", "body": "B"},
    ])
    index_a.rebuild_from_store(store_a)
    _queued_responses(monkeypatch, [""])
    result_garbage = run_llm_proposer(str(index_a.roots.index_path), index=index_a)

    # Run B: LLM legitimately parses and reports no relationship.
    store_b, index_b = _store(tmp_path / "b")
    _seed_canonical_crystallized(store_b, [
        {"id": "cry_legit_a", "created_at": "2026-06-01T10:00:00Z", "body": "A"},
        {"id": "cry_legit_b", "created_at": "2026-06-01T11:00:00Z", "body": "B"},
    ])
    index_b.rebuild_from_store(store_b)
    _queued_responses(monkeypatch, [_VALID_NONE_JSON])
    result_legit = run_llm_proposer(str(index_b.roots.index_path), index=index_b)

    # The two counters the pre-fix summary relied on are identical...
    assert result_garbage["pair_count"] == result_legit["pair_count"] == 1
    assert result_garbage["proposed_count"] == result_legit["proposed_count"] == 0

    # ...but the summary as a whole is not: status/outcome/failure counters
    # diverge, so a reader can tell the two runs apart without re-running
    # anything or reading source.
    assert result_garbage["status"] == "degraded"
    assert result_garbage["outcome"] == "llm_degraded"
    assert result_garbage["llm_call_failure_count"] == 1
    assert result_garbage["llm_call_failure_reasons"] == {"empty_llm_response": 1}

    assert result_legit["status"] == "ok"
    assert result_legit["outcome"] == "no_relationships_found"
    assert result_legit["llm_call_failure_count"] == 0
    assert result_legit["llm_call_failure_reasons"] == {}


def test_run_llm_proposer_all_failure_reason_kinds_counted(tmp_path, monkeypatch):
    """D2b: each of _call_llm's four pre-existing failure outcomes plus D1's
    new invalid_confidence outcome must be tallied by type, not just totaled."""
    store, index = _store(tmp_path)
    _seed_canonical_crystallized(store, [
        {"id": f"cry_reason_{n}", "created_at": f"2026-06-01T{10 + n:02d}:00:00Z", "body": f"body {n}"}
        for n in range(4)
    ])
    index.rebuild_from_store(store)

    monkeypatch.setattr(llm_edge_proposer, "_resolve_hermes_default_runtime", _ok_runtime)
    # 4 records -> 6 pairs. Feed 6 distinct outcomes: 4 typed failures +
    # 1 legitimate "none" + 1 real relationship.
    _queued_responses(monkeypatch, [
        "",                                    # empty_llm_response
        "not json at all {{{",                 # parse_failed
        "[1, 2, 3]",                            # not_a_dict
        json.dumps({"relation_type": "refines", "confidence": "bad", "reasoning": "x"}),  # invalid_confidence
        _VALID_NONE_JSON,
        _VALID_REFINES_JSON,
    ])

    result = run_llm_proposer(str(index.roots.index_path), index=index)

    assert result["pair_count"] == 6
    assert result["llm_call_count"] == 6
    assert result["llm_call_ok_count"] == 2
    assert result["llm_call_failure_count"] == 4
    assert result["llm_call_failure_reasons"] == {
        "empty_llm_response": 1,
        "parse_failed": 1,
        "not_a_dict": 1,
        "invalid_confidence": 1,
    }
    assert result["status"] == "degraded"
    assert result["proposed_count"] == 1


def test_run_llm_proposer_status_ok_when_no_failures(tmp_path, monkeypatch):
    """Regression guard: a fully healthy run must not be marked degraded."""
    store, index = _store(tmp_path)
    _seed_canonical_crystallized(store, [
        {"id": "cry_healthy_a", "created_at": "2026-06-01T10:00:00Z", "body": "A"},
        {"id": "cry_healthy_b", "created_at": "2026-06-01T11:00:00Z", "body": "B"},
    ])
    index.rebuild_from_store(store)

    monkeypatch.setattr(llm_edge_proposer, "_resolve_hermes_default_runtime", _ok_runtime)
    _queued_responses(monkeypatch, [_VALID_REFINES_JSON])

    result = run_llm_proposer(str(index.roots.index_path), index=index)

    assert result["status"] == "ok"
    assert result["outcome"] == "produced"
    assert result["llm_call_failure_count"] == 0
    assert result["llm_call_failure_reasons"] == {}
    assert result["proposed_count"] == 1
