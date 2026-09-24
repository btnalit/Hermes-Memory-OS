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
import sqlite3
from typing import Any
from unittest.mock import patch

import pytest

from plugins.memory.memory_os import llm_edge_proposer
from plugins.memory.memory_os.audit import read_audit_records
from plugins.memory.memory_os.index import MemoryOSIndex
from plugins.memory.memory_os.llm_edge_proposer import _call_llm, run_llm_proposer
from plugins.memory.memory_os.low_clue_recall import LlmCallResult
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


def _as_call_result(text: str) -> LlmCallResult:
    """Wrap a plain response string as the transport now returns it."""
    if not text:
        return LlmCallResult(text="", failure_reason="llm_empty_content")
    return LlmCallResult(text=text)


def _queued_responses(monkeypatch: pytest.MonkeyPatch, responses: list[str]) -> list[str]:
    """Monkeypatch _call_hermes_runtime_model_result (the real producer
    surface _call_llm consumes) to return *responses* in call order. Records
    prompts seen, for assertions that don't care about exact per-pair mapping."""
    queue = list(responses)
    prompts_seen: list[str] = []

    def _fake(prompt: str, config: dict[str, Any]) -> LlmCallResult:
        prompts_seen.append(prompt)
        return _as_call_result(queue.pop(0) if queue else "")

    monkeypatch.setattr(llm_edge_proposer, "_call_hermes_runtime_model_result", _fake)
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
        llm_edge_proposer, "_call_hermes_runtime_model_result",
        lambda prompt, config: LlmCallResult(text=json.dumps(
            {"relation_type": "refines", "confidence": "high", "reasoning": "x"}
        )),
    )
    result = _call_llm({"kind": "note", "body": "a"}, {"kind": "note", "body": "b"})
    assert result["outcome"] == "invalid_confidence"
    assert result["relation_type"] == "none"
    assert result["confidence"] == 0.0


def test_call_llm_null_confidence_returns_typed_failure(monkeypatch):
    """D1 counterfactual: {"confidence": null} used to raise TypeError out of
    the unguarded float(None) call. Must now return a typed failure dict."""
    monkeypatch.setattr(
        llm_edge_proposer, "_call_hermes_runtime_model_result",
        lambda prompt, config: LlmCallResult(
            text='{"relation_type": "refines", "confidence": null, "reasoning": "x"}'
        ),
    )
    result = _call_llm({"kind": "note", "body": "a"}, {"kind": "note", "body": "b"})
    assert result["outcome"] == "invalid_confidence"
    assert result["relation_type"] == "none"
    assert result["confidence"] == 0.0


def test_call_llm_valid_confidence_still_succeeds(monkeypatch):
    """Regression guard: the D1 try/except must not swallow legitimate
    numeric (including numeric-string) confidence values."""
    monkeypatch.setattr(
        llm_edge_proposer, "_call_hermes_runtime_model_result",
        lambda prompt, config: LlmCallResult(text=json.dumps(
            {"relation_type": "refines", "confidence": "0.7", "reasoning": "ok"}
        )),
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


# ═══════════════════════════════════════════════════════════════════════════
# J2: optional Jev native-choice judge backend (owner ruling 2026-09-23,
# next-phase plan row J2). Default OFF -- mirrors fact_judge.py's J1 test
# shape (tests/plugins/memory/test_memory_os_fact_judge.py's TestJ1*
# classes): byte-identical default-off, correct routing/fallback when the
# knob is set, and native-primitive confidence mapping through the shared
# edge_weights.llm_birth_weight formula (0.45 + 0.30 x confidence).
# ═══════════════════════════════════════════════════════════════════════════


def _write_knob_override(store: MemoryOSStore, knob_name: str, value: Any) -> None:
    """Write a knob override directly to the knob-override store for testing
    (mirrors test_memory_os_fact_judge.py's helper of the same name)."""
    from datetime import datetime as _dt, timezone as _tz

    path = store.roots.memory_os_root / "system" / "knob_overrides.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    now = _dt.now(_tz.utc)
    record = {
        "schema_version": "memory-os.knob_override.v0",
        "id": f"ko_test_{knob_name}",
        "knob": knob_name,
        "override_value": value,
        "prior_value": None,
        "provisional": False,
        "expires_at": "",
        "proposed_by": "test",
        "approved_via": "test",
        "state": "active",
        "ts": now.isoformat(),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


class TestJ2JudgeBackendKnobRegistered:
    def test_judge_backend_knob_registered(self):
        from plugins.memory.memory_os.knob_overrides import OVERRIDABLE_KNOBS
        assert "llm_edge_proposer_judge_backend" in OVERRIDABLE_KNOBS
        knob = OVERRIDABLE_KNOBS["llm_edge_proposer_judge_backend"]
        assert knob["module"] == "llm_edge_proposer"
        assert knob["default"] == "hermes_default"
        assert knob["kind"] == "lane_switch"
        assert knob["allowed"] == ["hermes_default", "typesafe_jev"]
        assert knob["meta"] is False

    def test_judge_backend_knob_round_trips_through_register_and_resolve(self, tmp_path):
        from plugins.memory.memory_os.knob_overrides import register_override, resolve_knob

        store_root = tmp_path / "system"
        store_root.mkdir(parents=True, exist_ok=True)

        assert resolve_knob(
            "llm_edge_proposer_judge_backend", default="hermes_default", _store_root=store_root,
        ) == "hermes_default"

        register_override(
            "llm_edge_proposer_judge_backend", "typesafe_jev",
            prior="hermes_default", proposed_by="test", approved_via="test",
            expires_at="", _store_root=store_root,
        )
        assert resolve_knob(
            "llm_edge_proposer_judge_backend", default="hermes_default", _store_root=store_root,
        ) == "typesafe_jev"

    def test_judge_backend_knob_rejects_unregistered_value(self):
        from plugins.memory.memory_os.knob_overrides import register_override
        with pytest.raises(ValueError, match="not in allowed"):
            register_override(
                "llm_edge_proposer_judge_backend", "openai_direct",
                prior="hermes_default", proposed_by="test", approved_via="test",
                expires_at="",
            )

    def test_judge_backend_lane_switch_never_auto_approvable(self):
        """lane_switch kind is always owner-gated -- same rule as
        fact_judge_judge_backend / llm_transport."""
        from plugins.memory.memory_os.knob_overrides import knob_override_auto_approvable
        assert knob_override_auto_approvable("llm_edge_proposer_judge_backend", "typesafe_jev") is False


class TestJ2DefaultOffByteIdentical:
    """Default-off (no knob override registered) must be byte-identical to
    pre-J2 run_llm_proposer behaviour -- Section W counterfactual."""

    def test_default_off_never_calls_jev_backend(self, tmp_path, monkeypatch):
        """Counterfactual: remove the `judge_backend ==
        jev_backend.JEV_BACKEND_NAME` guard in the pair loop and this call
        would happen even with the knob unset."""
        store, index = _store(tmp_path)
        _seed_canonical_crystallized(store, [
            {"id": "cry_j2_off_a", "created_at": "2026-06-01T10:00:00Z", "body": "Record A body."},
            {"id": "cry_j2_off_b", "created_at": "2026-06-01T11:00:00Z", "body": "Record B body."},
        ])
        index.rebuild_from_store(store)

        monkeypatch.setattr(llm_edge_proposer, "_resolve_hermes_default_runtime", _ok_runtime)
        _queued_responses(monkeypatch, [_VALID_REFINES_JSON])

        with patch.object(llm_edge_proposer.jev_backend, "judge_choice") as mock_jev:
            result = run_llm_proposer(str(index.roots.index_path), index=index, roots=store.roots)

        assert not mock_jev.called, "default-off must never call the Jev backend"
        assert result["judge_backend"] == "hermes_default"
        assert result["judge_backend_fallback_count"] == 0
        assert result["judge_backend_fallback_reasons"] == {}
        assert result["judge_backend_fallback_detail_sample"] == ""
        assert result["proposed_count"] == 1

    def test_default_off_identical_whether_or_not_roots_is_passed(self, tmp_path, monkeypatch):
        """``roots`` is documented to fall back to ``index.roots`` when
        omitted (same fallback shape as ``run_vector_proposer``) -- so with
        no override registered, omitting ``roots`` entirely (every pre-J2
        call site's shape) must resolve the SAME "hermes_default" backend
        and produce an identical core summary to passing it explicitly."""
        store, index = _store(tmp_path)
        _seed_canonical_crystallized(store, [
            {"id": "cry_j2_shape_a", "created_at": "2026-06-01T10:00:00Z", "body": "A"},
            {"id": "cry_j2_shape_b", "created_at": "2026-06-01T11:00:00Z", "body": "B"},
        ])
        index.rebuild_from_store(store)

        monkeypatch.setattr(llm_edge_proposer, "_resolve_hermes_default_runtime", _ok_runtime)
        _queued_responses(monkeypatch, [_VALID_NONE_JSON])
        result_without_roots = run_llm_proposer(str(index.roots.index_path), index=index)

        store2, index2 = _store(tmp_path / "shape2")
        _seed_canonical_crystallized(store2, [
            {"id": "cry_j2_shape_a2", "created_at": "2026-06-01T10:00:00Z", "body": "A"},
            {"id": "cry_j2_shape_b2", "created_at": "2026-06-01T11:00:00Z", "body": "B"},
        ])
        index2.rebuild_from_store(store2)
        _queued_responses(monkeypatch, [_VALID_NONE_JSON])
        result_with_roots = run_llm_proposer(str(index2.roots.index_path), index=index2, roots=store2.roots)

        _volatile_keys = {"duration_ms", "begin_at", "end_at", "started_at", "finished_at"}
        stable_keys = set(result_without_roots) - _volatile_keys
        assert set(result_with_roots) - _volatile_keys == stable_keys
        for key in stable_keys:
            assert result_with_roots[key] == result_without_roots[key], (
                f"J2 default-off must resolve identically regardless of key {key!r}"
            )
        assert result_without_roots["judge_backend"] == "hermes_default"
        assert result_with_roots["judge_backend"] == "hermes_default"

    def test_run_llm_proposer_default_parameter_is_none(self):
        """Every pre-J2 call site of run_llm_proposer omits `roots` -- this
        locks the default so those call sites stay byte-identical."""
        sig = inspect.signature(run_llm_proposer)
        assert sig.parameters["roots"].default is None


class TestJ2JevBackendRouting:
    """Knob override routes to the Jev backend; success skips _call_llm
    entirely for that pair."""

    def test_knob_override_routes_to_jev_and_skips_call_llm(self, tmp_path, monkeypatch):
        store, index = _store(tmp_path)
        _seed_canonical_crystallized(store, [
            {"id": "cry_j2_route_a", "created_at": "2026-06-01T10:00:00Z", "body": "Record A body."},
            {"id": "cry_j2_route_b", "created_at": "2026-06-01T11:00:00Z", "body": "Record B body."},
        ])
        index.rebuild_from_store(store)
        _write_knob_override(store, "llm_edge_proposer_judge_backend", "typesafe_jev")

        from plugins.memory.memory_os.jev_backend import JevChoiceResult

        monkeypatch.setattr(llm_edge_proposer, "_resolve_hermes_default_runtime", _ok_runtime)
        with patch.object(
            llm_edge_proposer.jev_backend, "judge_choice",
            return_value=JevChoiceResult(
                choice="refines", confidence=0.9, probabilities={"refines": 0.9}, failure_reason="",
            ),
        ) as mock_jev, patch.object(llm_edge_proposer, "_call_hermes_runtime_model_result") as mock_hermes:
            result = run_llm_proposer(str(index.roots.index_path), index=index, roots=store.roots)

        assert mock_jev.called
        assert not mock_hermes.called, "Jev success must not fall through to _call_llm"
        assert result["judge_backend"] == "typesafe_jev"
        assert result["judge_backend_fallback_count"] == 0
        assert result["proposed_count"] == 1

    def test_jev_none_choice_is_not_a_relationship(self, tmp_path, monkeypatch):
        """A legitimate Jev "none" answer must behave exactly like
        _call_llm's own "none" -- no edge written, not counted as failure."""
        store, index = _store(tmp_path)
        _seed_canonical_crystallized(store, [
            {"id": "cry_j2_none_a", "created_at": "2026-06-01T10:00:00Z", "body": "A"},
            {"id": "cry_j2_none_b", "created_at": "2026-06-01T11:00:00Z", "body": "B"},
        ])
        index.rebuild_from_store(store)
        _write_knob_override(store, "llm_edge_proposer_judge_backend", "typesafe_jev")

        from plugins.memory.memory_os.jev_backend import JevChoiceResult

        monkeypatch.setattr(llm_edge_proposer, "_resolve_hermes_default_runtime", _ok_runtime)
        with patch.object(
            llm_edge_proposer.jev_backend, "judge_choice",
            return_value=JevChoiceResult(choice="none", confidence=0.7, failure_reason=""),
        ):
            result = run_llm_proposer(str(index.roots.index_path), index=index, roots=store.roots)

        assert result["judge_backend_fallback_count"] == 0
        assert result["proposed_count"] == 0


class TestJ2JevFallback:
    """Any Jev failure must fall back to the _call_llm path and be counted --
    Completion Is Not Output."""

    def test_jev_failure_falls_back_to_call_llm_and_counts(self, tmp_path, monkeypatch):
        store, index = _store(tmp_path)
        _seed_canonical_crystallized(store, [
            {"id": "cry_j2_fb_a", "created_at": "2026-06-01T10:00:00Z", "body": "Record A body."},
            {"id": "cry_j2_fb_b", "created_at": "2026-06-01T11:00:00Z", "body": "Record B body."},
        ])
        index.rebuild_from_store(store)
        _write_knob_override(store, "llm_edge_proposer_judge_backend", "typesafe_jev")

        from plugins.memory.memory_os.jev_backend import JevChoiceResult

        monkeypatch.setattr(llm_edge_proposer, "_resolve_hermes_default_runtime", _ok_runtime)
        _queued_responses(monkeypatch, [_VALID_REFINES_JSON])
        with patch.object(
            llm_edge_proposer.jev_backend, "judge_choice",
            return_value=JevChoiceResult(failure_reason="llm_timeout", detail="socket_timeout"),
        ) as mock_jev:
            result = run_llm_proposer(str(index.roots.index_path), index=index, roots=store.roots)

        assert mock_jev.called
        assert result["judge_backend"] == "typesafe_jev"
        assert result["judge_backend_fallback_count"] == 1
        assert result["judge_backend_fallback_reasons"] == {"llm_timeout": 1}
        assert result["judge_backend_fallback_detail_sample"] == "socket_timeout"
        assert result["proposed_count"] == 1, "the fallback call_llm result must still produce the edge"

    def test_missing_key_never_calls_network_and_still_falls_back(self, tmp_path, monkeypatch, hermes_env_root):
        """Counterfactual for jev_backend._resolve_api_key, exercised through
        the real (unmocked) jev_backend.judge_choice with no TYPESAFE_API_KEY
        in os.environ nor in (fake) Hermes' .env."""
        store, index = _store(tmp_path)
        _seed_canonical_crystallized(store, [
            {"id": "cry_j2_key_a", "created_at": "2026-06-01T10:00:00Z", "body": "A"},
            {"id": "cry_j2_key_b", "created_at": "2026-06-01T11:00:00Z", "body": "B"},
        ])
        index.rebuild_from_store(store)
        _write_knob_override(store, "llm_edge_proposer_judge_backend", "typesafe_jev")
        hermes_env_root("OTHER_KEY=unrelated\n")

        import os
        old_key = os.environ.pop("TYPESAFE_API_KEY", None)
        monkeypatch.setattr(llm_edge_proposer, "_resolve_hermes_default_runtime", _ok_runtime)
        _queued_responses(monkeypatch, [_VALID_NONE_JSON])
        try:
            with patch("urllib.request.urlopen") as mock_urlopen:
                result = run_llm_proposer(str(index.roots.index_path), index=index, roots=store.roots)
        finally:
            if old_key is not None:
                os.environ["TYPESAFE_API_KEY"] = old_key

        assert not mock_urlopen.called, "missing key must never reach the network"
        assert result["judge_backend_fallback_count"] == 1
        assert result["judge_backend_fallback_reasons"] == {"llm_missing_key": 1}
        assert result["judge_backend_fallback_detail_sample"] == "not_in_environ_or_hermes_env"

    def test_key_only_in_hermes_dotenv_reaches_jev_without_fallback(self, tmp_path, monkeypatch, hermes_env_root):
        """Counterfactual for the J2 production gap: the cognitive-loop
        launcher does not load Hermes' .env into os.environ, so every pair fell
        back with llm_missing_key. With the key only in .env, Jev must answer
        and _call_llm must not run."""
        store, index = _store(tmp_path)
        _seed_canonical_crystallized(store, [
            {"id": "cry_j2_env_a", "created_at": "2026-06-01T10:00:00Z", "body": "Record A body."},
            {"id": "cry_j2_env_b", "created_at": "2026-06-01T11:00:00Z", "body": "Record B body."},
        ])
        index.rebuild_from_store(store)
        _write_knob_override(store, "llm_edge_proposer_judge_backend", "typesafe_jev")
        monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
        hermes_env_root("TYPESAFE_API_KEY=fake-dotenv-key-not-real\n")

        answer = {"type": "choice", "choice": "refines", "confidence": 0.9, "probabilities": {"refines": 0.9}}
        response_body = json.dumps({"model": "jev-1.13.0", "answers": {"relation_type": answer}}).encode()

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, *exc_info):
                return False

            def read(self):
                return response_body

        monkeypatch.setattr(llm_edge_proposer, "_resolve_hermes_default_runtime", _ok_runtime)
        with patch("urllib.request.urlopen", return_value=_Response()) as mock_urlopen, patch.object(
            llm_edge_proposer, "_call_hermes_runtime_model_result",
        ) as mock_hermes:
            result = run_llm_proposer(str(index.roots.index_path), index=index, roots=store.roots)

        assert mock_urlopen.called
        assert mock_urlopen.call_args[0][0].get_header("Authorization") == "Bearer fake-dotenv-key-not-real"
        assert not mock_hermes.called, "Jev success must not fall through to _call_llm"
        assert result["judge_backend"] == "typesafe_jev"
        assert result["judge_backend_fallback_count"] == 0
        assert result["proposed_count"] == 1

    def test_fallback_counts_aggregate_across_pairs(self, tmp_path, monkeypatch):
        store, index = _store(tmp_path)
        _seed_canonical_crystallized(store, [
            {"id": "cry_j2_agg_a", "created_at": "2026-06-01T10:00:00Z", "body": "A"},
            {"id": "cry_j2_agg_b", "created_at": "2026-06-01T11:00:00Z", "body": "B"},
            {"id": "cry_j2_agg_c", "created_at": "2026-06-01T12:00:00Z", "body": "C"},
        ])
        index.rebuild_from_store(store)
        _write_knob_override(store, "llm_edge_proposer_judge_backend", "typesafe_jev")

        from plugins.memory.memory_os.jev_backend import JevChoiceResult

        monkeypatch.setattr(llm_edge_proposer, "_resolve_hermes_default_runtime", _ok_runtime)
        # 3 records -> 3 pairs, every Jev call fails the same way.
        _queued_responses(monkeypatch, [_VALID_NONE_JSON, _VALID_NONE_JSON, _VALID_NONE_JSON])
        with patch.object(
            llm_edge_proposer.jev_backend, "judge_choice",
            return_value=JevChoiceResult(failure_reason="llm_exception", detail="boom"),
        ):
            result = run_llm_proposer(str(index.roots.index_path), index=index, roots=store.roots)

        assert result["judge_backend_fallback_count"] == 3
        assert result["judge_backend_fallback_reasons"] == {"llm_exception": 3}

    def test_caller_side_closed_set_defence_rejects_choice_outside_criteria(self, tmp_path, monkeypatch):
        """Defense in depth: even if jev_backend's own wire-contract guard
        were bypassed (simulated here via a direct mock returning a choice
        outside _JEV_RELATION_CHOICE_CRITERIA), _call_jev's own closed-set
        check must still catch it and fall back rather than writing an edge
        with an unrecognised relation_type."""
        store, index = _store(tmp_path)
        _seed_canonical_crystallized(store, [
            {"id": "cry_j2_closed_a", "created_at": "2026-06-01T10:00:00Z", "body": "A"},
            {"id": "cry_j2_closed_b", "created_at": "2026-06-01T11:00:00Z", "body": "B"},
        ])
        index.rebuild_from_store(store)
        _write_knob_override(store, "llm_edge_proposer_judge_backend", "typesafe_jev")

        from plugins.memory.memory_os.jev_backend import JevChoiceResult

        monkeypatch.setattr(llm_edge_proposer, "_resolve_hermes_default_runtime", _ok_runtime)
        _queued_responses(monkeypatch, [_VALID_NONE_JSON])
        with patch.object(
            llm_edge_proposer.jev_backend, "judge_choice",
            return_value=JevChoiceResult(choice="not_a_real_relation", confidence=0.9, failure_reason=""),
        ):
            result = run_llm_proposer(str(index.roots.index_path), index=index, roots=store.roots)

        assert result["judge_backend_fallback_count"] == 1
        assert result["judge_backend_fallback_reasons"] == {"llm_parse_failed": 1}


class TestJ2NativeChoiceConfidenceMapping:
    """The native choice confidence must feed the same
    edge_weights.llm_birth_weight formula (0.45 + 0.30 x confidence) as
    _call_llm's confidence -- no separate weight formula for the Jev path."""

    def test_jev_confidence_maps_into_shared_birth_weight_formula(self, tmp_path, monkeypatch):
        from plugins.memory.memory_os.edge_weights import llm_birth_weight
        from plugins.memory.memory_os.jev_backend import JevChoiceResult

        store, index = _store(tmp_path)
        _seed_canonical_crystallized(store, [
            {"id": "cry_j2_weight_a", "created_at": "2026-06-01T10:00:00Z", "body": "A"},
            {"id": "cry_j2_weight_b", "created_at": "2026-06-01T11:00:00Z", "body": "B"},
        ])
        index.rebuild_from_store(store)
        _write_knob_override(store, "llm_edge_proposer_judge_backend", "typesafe_jev")

        monkeypatch.setattr(llm_edge_proposer, "_resolve_hermes_default_runtime", _ok_runtime)
        with patch.object(
            llm_edge_proposer.jev_backend, "judge_choice",
            return_value=JevChoiceResult(choice="refines", confidence=0.8, failure_reason=""),
        ):
            result = run_llm_proposer(str(index.roots.index_path), index=index, roots=store.roots)

        assert result["proposed_count"] == 1
        conn = sqlite3.connect(str(index.roots.index_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "select weight from memory_edges where proposed_by = 'llm' and relation_type = 'refines'"
        ).fetchall()
        conn.close()
        assert len(rows) == 1
        assert float(rows[0]["weight"]) == pytest.approx(llm_birth_weight(0.8))
        assert float(rows[0]["weight"]) == pytest.approx(0.45 + 0.30 * 0.8)

    def test_jev_none_confidence_falls_back_to_zero_bound(self, tmp_path, monkeypatch):
        """llm_birth_weight's own None-safety (bounded to 0) must be exercised
        through the Jev path exactly as it is through _call_llm's."""
        from plugins.memory.memory_os.edge_weights import llm_birth_weight
        from plugins.memory.memory_os.jev_backend import JevChoiceResult

        store, index = _store(tmp_path)
        _seed_canonical_crystallized(store, [
            {"id": "cry_j2_noconf_a", "created_at": "2026-06-01T10:00:00Z", "body": "A"},
            {"id": "cry_j2_noconf_b", "created_at": "2026-06-01T11:00:00Z", "body": "B"},
        ])
        index.rebuild_from_store(store)
        _write_knob_override(store, "llm_edge_proposer_judge_backend", "typesafe_jev")

        monkeypatch.setattr(llm_edge_proposer, "_resolve_hermes_default_runtime", _ok_runtime)
        with patch.object(
            llm_edge_proposer.jev_backend, "judge_choice",
            return_value=JevChoiceResult(choice="co_occurs", confidence=None, failure_reason=""),
        ):
            result = run_llm_proposer(str(index.roots.index_path), index=index, roots=store.roots)

        assert result["proposed_count"] == 1
        conn = sqlite3.connect(str(index.roots.index_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "select weight from memory_edges where proposed_by = 'llm' and relation_type = 'co_occurs'"
        ).fetchall()
        conn.close()
        assert len(rows) == 1
        assert float(rows[0]["weight"]) == pytest.approx(llm_birth_weight(0.0))
        assert float(rows[0]["weight"]) == pytest.approx(0.45)


# ═══════════════════════════════════════════════════════════════════════════
# J2: _call_jev unit tests (state building, criteria, reasoning parity)
# ═══════════════════════════════════════════════════════════════════════════


class TestJ2CallJevUnit:
    def test_call_jev_success_shape_matches_call_llm(self):
        """_call_jev's success dict must carry the same relation_type/
        confidence/outcome keys _call_llm's pair-loop consumer reads."""
        from plugins.memory.memory_os.jev_backend import JevChoiceResult

        with patch.object(
            llm_edge_proposer.jev_backend, "judge_choice",
            return_value=JevChoiceResult(
                choice="contradicts", confidence=0.55, probabilities={"contradicts": 0.55}, failure_reason="",
            ),
        ):
            result = llm_edge_proposer._call_jev(
                {"kind": "note", "tags_json": [], "body": "a"},
                {"kind": "note", "tags_json": [], "body": "b"},
            )

        assert result["outcome"] == "ok"
        assert result["relation_type"] == "contradicts"
        assert result["confidence"] == 0.55
        assert result["judge_backend"] == llm_edge_proposer.jev_backend.JEV_BACKEND_NAME

    def test_call_jev_failure_never_returns_ok_outcome(self):
        from plugins.memory.memory_os.jev_backend import JevChoiceResult

        with patch.object(
            llm_edge_proposer.jev_backend, "judge_choice",
            return_value=JevChoiceResult(failure_reason="llm_http_4xx", detail="HTTP 400: bad"),
        ):
            result = llm_edge_proposer._call_jev(
                {"kind": "note", "tags_json": [], "body": "a"},
                {"kind": "note", "tags_json": [], "body": "b"},
            )

        assert result["outcome"] == "jev_failed"
        assert result["jev_failure_reason"] == "llm_http_4xx"
        assert result["jev_failure_detail"] == "HTTP 400: bad"
        assert result["relation_type"] == "none"

    def test_build_jev_choice_state_clips_body_to_500_chars(self):
        long_body = "x" * 800
        state = llm_edge_proposer._build_jev_choice_state(
            {"kind": "note", "tags_json": [], "body": long_body},
            {"kind": "note", "tags_json": [], "body": "short"},
        )
        assert len(state["record_a"]["body"]) == 500
        assert state["record_b"]["body"] == "short"

    def test_relation_choice_criteria_is_closed_five_way_set(self):
        assert set(llm_edge_proposer._JEV_RELATION_CHOICE_CRITERIA.keys()) == {
            "refines", "contradicts", "depends_on", "co_occurs", "none",
        }


# ═══════════════════════════════════════════════════════════════════════════
# W4-A / plan row L1 — route visibility (llm_route_unexpected_count)
# ═══════════════════════════════════════════════════════════════════════════


def test_run_llm_proposer_counts_route_unexpected_when_answering_model_differs(tmp_path, monkeypatch):
    """W4-A: run_llm_proposer's summary must count calls whose answering
    model diverged from the pinned one -- LlmCallResult.__post_init__
    derives route_unexpected from expected_model vs model (see
    low_clue_recall.py's docstring). Diagnostics-forwarding only: does not
    touch _call_llm's judgment logic/prompt."""
    store, index = _store(tmp_path)
    _seed_canonical_crystallized(store, [
        {"id": "cry_route_a", "created_at": "2026-06-01T10:00:00Z", "body": "A"},
        {"id": "cry_route_b", "created_at": "2026-06-01T11:00:00Z", "body": "B"},
    ])
    index.rebuild_from_store(store)

    monkeypatch.setattr(llm_edge_proposer, "_resolve_hermes_default_runtime", _ok_runtime)
    monkeypatch.setattr(
        llm_edge_proposer, "_call_hermes_runtime_model_result",
        lambda prompt, config: LlmCallResult(
            text=_VALID_REFINES_JSON, provider="openai-codex", model="answering-model",
            expected_model="pinned-model", expected_provider="openai-codex", routed_provider="fallback-provider",
        ),
    )

    result = run_llm_proposer(str(index.roots.index_path), index=index)

    assert result["llm_route_unexpected_count"] == 1
    assert result["llm_route_unknown_count"] == 0
    assert result["llm_route_unexpected_expected_model"] == "pinned-model"
    assert result["llm_route_unexpected_actual_model"] == "answering-model"


def test_run_llm_proposer_counts_route_unknown_when_actual_model_cannot_be_determined(tmp_path, monkeypatch):
    """Counterfactual companion: an empty-content reply never resolves an
    actual model -- must count as unknown, NEVER as unexpected (mutually
    exclusive by construction)."""
    store, index = _store(tmp_path)
    _seed_canonical_crystallized(store, [
        {"id": "cry_unk_a", "created_at": "2026-06-01T10:00:00Z", "body": "A"},
        {"id": "cry_unk_b", "created_at": "2026-06-01T11:00:00Z", "body": "B"},
    ])
    index.rebuild_from_store(store)

    monkeypatch.setattr(llm_edge_proposer, "_resolve_hermes_default_runtime", _ok_runtime)
    _queued_responses(monkeypatch, [""])

    result = run_llm_proposer(str(index.roots.index_path), index=index)

    assert result["llm_route_unknown_count"] == 1
    assert result["llm_route_unexpected_count"] == 0
