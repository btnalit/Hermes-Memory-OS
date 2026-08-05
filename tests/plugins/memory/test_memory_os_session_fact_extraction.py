"""Tests for session_fact_extraction — offline lane closing the 140-char
turn-summary truncation gap by extracting durable facts from raw session
transcripts too long to have survived `_turn_summary`'s per-side clip.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from plugins.memory.memory_os.crystallized import read_candidate_queue
from plugins.memory.memory_os.jsonl_io import read_jsonl
from plugins.memory.memory_os.knob_overrides import register_override
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.modules.cognition.session_fact_extraction import (
    MAX_EXTRACTION_ATTEMPTS,
    MESSAGE_ELIGIBILITY_THRESHOLD_CHARS,
    SKIPPED_REASON_CODES,
    _session_fingerprint,
    extract_fact_from_message,
    read_processed_session_fingerprints,
    read_session_fact_extraction_runs,
    run_session_fact_extraction_lane,
    session_fact_extraction_manifest,
)


# ── Helpers ──────────────────────────────────────────────────────────────


def _add_gate_envelope(store: MemoryOSStore, envelope_id: str) -> None:
    """Append one valid ExecutionGate permit record for this lane."""
    now = datetime.now(timezone.utc)
    expires_at = now.replace(year=now.year + 1).isoformat().replace("+00:00", "Z")
    envelope = {
        "schema_version": "memory-os.execution_gate_envelope.v0",
        "stage": "permit",
        "execution_gate_envelope_id": envelope_id,
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": expires_at,
        "profile": store.roots.profile,
        "lane_id": "session_fact_extraction",
        "trigger_surface": "hermes_cron",
        "risk_class": "local_helper",
        "human_approval_required": False,
        "why_no_human_approval": "test",
        "scope": {"registry_key": "session_fact_extraction", "raw_script": "test"},
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
        },
        "boundary_true": False,
        "precheck": {"helper_present": True},
        "permit_decision": "allowed",
        "permit_reason": "boundary_false",
    }
    gate_path = store.roots.hermes_home / "memory-os" / "system" / "execution_gate_envelopes.jsonl"
    gate_path.parent.mkdir(parents=True, exist_ok=True)
    with gate_path.open("a") as f:
        f.write(json.dumps(envelope, sort_keys=True) + "\n")


def _store_with_gate(tmp_path, envelope_id: str, *, profile: str = "main") -> MemoryOSStore:
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile=profile)
    store = MemoryOSStore(roots)
    store.initialize()
    _add_gate_envelope(store, envelope_id)
    return store


def _write_session_file(
    hermes_home: Path,
    name: str,
    *,
    messages: list[dict],
    session_id: str | None = None,
    platform: str = "test_platform",
    mtime: float | None = None,
) -> Path:
    sessions_dir = hermes_home / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    path = sessions_dir / name
    payload = {
        "id": session_id or name.replace(".json", ""),
        "platform": platform,
        "messages": messages,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def _fake_llm_always_durable(prompt: str, config: dict) -> str:
    return json.dumps({"has_durable_fact": True, "fact": "extracted durable fact text", "reason": "test"})


def _fake_llm_no_fact(prompt: str, config: dict) -> str:
    return json.dumps({"has_durable_fact": False, "fact": "", "reason": "no durable content"})


def _fake_llm_empty(prompt: str, config: dict) -> str:
    return ""


_LONG_MARKER_TEXT = "prefer " + ("y" * (MESSAGE_ELIGIBILITY_THRESHOLD_CHARS + 20))
_LONG_NO_MARKER_TEXT = "z" * (MESSAGE_ELIGIBILITY_THRESHOLD_CHARS + 20)
_SHORT_TEXT = "ok thanks"


# ── Counterfactual 1: >140-char message produces a fact; <=140-char does not ──


def test_long_message_over_threshold_is_extracted_short_message_is_not(tmp_path, monkeypatch):
    """The whole premise of the lane: only messages beyond _turn_summary's
    140-char clip are worth re-extracting.

    Counterfactual: without the MESSAGE_ELIGIBILITY_THRESHOLD_CHARS filter,
    every message (including the short one) would reach the LLM, so
    llm_calls would be 2 and messages_eligible_over_threshold would be 2.
    """
    envelope_id = "xgate_test_sfe_threshold"
    store = _store_with_gate(tmp_path, envelope_id)
    assert len(_LONG_NO_MARKER_TEXT) > MESSAGE_ELIGIBILITY_THRESHOLD_CHARS
    assert len(_SHORT_TEXT) <= MESSAGE_ELIGIBILITY_THRESHOLD_CHARS

    _write_session_file(
        store.roots.hermes_home,
        "session_threshold.json",
        messages=[
            {"role": "user", "content": _SHORT_TEXT},
            {"role": "user", "content": _LONG_NO_MARKER_TEXT},
        ],
    )
    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model",
        _fake_llm_always_durable,
    )

    report = run_session_fact_extraction_lane(store, execution_gate_envelope_id=envelope_id)

    assert report["skipped"] is False
    assert report["messages_considered"] == 2
    assert report["messages_eligible_over_threshold"] == 1
    assert report["llm_calls"] == 1
    assert report["facts_extracted"] == 1
    assert report["candidates_written"] == 1

    candidates = read_candidate_queue(store)
    assert len(candidates) == 1
    assert "extracted durable fact text" in candidates[0].body
    assert candidates[0].bridge_state == "inner_drive_candidate"


def test_session_with_only_short_messages_yields_no_facts(tmp_path, monkeypatch):
    envelope_id = "xgate_test_sfe_all_short"
    store = _store_with_gate(tmp_path, envelope_id)
    _write_session_file(
        store.roots.hermes_home,
        "session_allshort.json",
        messages=[{"role": "user", "content": _SHORT_TEXT}, {"role": "assistant", "content": "好的"}],
    )
    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model",
        _fake_llm_always_durable,
    )

    report = run_session_fact_extraction_lane(store, execution_gate_envelope_id=envelope_id)

    assert report["sessions_processed"] == 1
    assert report["messages_eligible_over_threshold"] == 0
    assert report["llm_calls"] == 0
    assert report["facts_extracted"] == 0
    assert report["candidates_written"] == 0


# ── Counterfactual 2: llm_empty_content is counted, never conflated with "no input" ──


def test_llm_empty_content_is_typed_failure_not_silent_success(tmp_path, monkeypatch):
    """_call_hermes_runtime_model returning "" must be counted as
    llm_empty_content, and the run must not report as if there were no
    eligible input (that would hide a real model outage behind a lookalike
    of case (a) "no eligible input existed").
    """
    envelope_id = "xgate_test_sfe_empty"
    store = _store_with_gate(tmp_path, envelope_id)
    _write_session_file(
        store.roots.hermes_home,
        "session_empty_llm.json",
        messages=[{"role": "user", "content": _LONG_MARKER_TEXT}],
    )
    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model",
        _fake_llm_empty,
    )

    report = run_session_fact_extraction_lane(store, execution_gate_envelope_id=envelope_id)

    assert report["skipped"] is False
    assert report["skipped_reason"] == ""
    assert report["sessions_processed"] == 1
    assert report["messages_eligible_over_threshold"] == 1
    assert report["llm_calls"] == 1
    assert report["llm_failures_by_reason"].get("llm_empty_content") == 1
    assert report["fallback_used_count"] == 1
    # No fact is manufactured on model failure -- a marker-matched raw clip is
    # not a recovered fact, it is the same truncation this lane undoes. The
    # message is deferred for a later tick instead of being lost or faked.
    assert report["facts_extracted"] == 0
    assert report["candidates_written"] == 0
    assert report["sessions_deferred_llm_failure"] == 1


def test_llm_empty_content_with_no_marker_produces_no_fact_but_is_still_counted(tmp_path, monkeypatch):
    """The heuristic fallback is fail-closed (mirrors fact_judge): no marker
    match means no fact, even on total LLM failure. The failure is still
    recorded so it is never conflated with 'nothing to extract'.
    """
    envelope_id = "xgate_test_sfe_empty_no_marker"
    store = _store_with_gate(tmp_path, envelope_id)
    _write_session_file(
        store.roots.hermes_home,
        "session_empty_llm_no_marker.json",
        messages=[{"role": "user", "content": _LONG_NO_MARKER_TEXT}],
    )
    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model",
        _fake_llm_empty,
    )

    report = run_session_fact_extraction_lane(store, execution_gate_envelope_id=envelope_id)

    assert report["llm_failures_by_reason"].get("llm_empty_content") == 1
    assert report["fallback_used_count"] == 1
    assert report["facts_extracted"] == 0
    assert report["candidates_written"] == 0
    assert report["skipped"] is False  # input existed; model just failed


# ── Counterfactual 3: fingerprint ledger prevents reprocessing ──────────


def test_fingerprint_ledger_prevents_reprocessing_next_run(tmp_path, monkeypatch):
    """Counterfactual: without a persisted, checked fingerprint, the second
    run would find the same session file eligible again (sessions_eligible
    would be 1, not 0) and would re-extract/re-write for it.
    """
    envelope_1 = "xgate_test_sfe_ledger_run1"
    envelope_2 = "xgate_test_sfe_ledger_run2"
    store = _store_with_gate(tmp_path, envelope_1)
    _add_gate_envelope(store, envelope_2)

    _write_session_file(
        store.roots.hermes_home,
        "session_ledger.json",
        messages=[{"role": "user", "content": _LONG_MARKER_TEXT}],
    )
    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model",
        _fake_llm_always_durable,
    )

    report1 = run_session_fact_extraction_lane(store, execution_gate_envelope_id=envelope_1)
    assert report1["sessions_scanned"] == 1
    assert report1["sessions_eligible"] == 1
    assert report1["sessions_processed"] == 1
    assert report1["candidates_written"] == 1

    report2 = run_session_fact_extraction_lane(store, execution_gate_envelope_id=envelope_2)
    assert report2["sessions_scanned"] == 1
    assert report2["sessions_eligible"] == 0
    assert report2["sessions_processed"] == 0
    assert report2["sessions_skipped_already_processed"] == 1
    assert report2["skipped"] is True
    assert report2["skipped_reason"] == "no_unprocessed_sessions"
    assert report2["candidates_written"] == 0


def test_appending_to_a_processed_session_makes_it_eligible_again(tmp_path, monkeypatch):
    """The fingerprint combines size+mtime, not just the filename, so an
    appended-to session is reconsidered rather than permanently skipped."""
    envelope_1 = "xgate_test_sfe_append_run1"
    envelope_2 = "xgate_test_sfe_append_run2"
    store = _store_with_gate(tmp_path, envelope_1)
    _add_gate_envelope(store, envelope_2)

    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model",
        _fake_llm_always_durable,
    )

    path = _write_session_file(
        store.roots.hermes_home,
        "session_grows.json",
        messages=[{"role": "user", "content": _LONG_MARKER_TEXT}],
    )
    report1 = run_session_fact_extraction_lane(store, execution_gate_envelope_id=envelope_1)
    assert report1["sessions_processed"] == 1

    # Append a second message -> different size/mtime -> different fingerprint.
    time.sleep(0.01)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["messages"].append({"role": "assistant", "content": _LONG_MARKER_TEXT + " more"})
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.utime(path, None)

    report2 = run_session_fact_extraction_lane(store, execution_gate_envelope_id=envelope_2)
    assert report2["sessions_eligible"] == 1
    assert report2["sessions_processed"] == 1


# ── Counterfactual 4: newest-unprocessed-first selection, not head-of-queue ──


def test_selection_is_newest_first_not_lexicographic_head_of_queue(tmp_path, monkeypatch):
    """session_aaa.json sorts first lexicographically but is OLDER;
    session_zzz.json sorts last lexicographically but is NEWER. A
    head-of-queue selector (like SessionMirror.scan's documented bias) would
    pick aaa first; this lane must pick zzz first.

    Counterfactual: with plain `sorted(glob(...))` (lexicographic) instead of
    an mtime-descending sort, the first processed fingerprint would be aaa's,
    not zzz's -- the assertions below would flip.
    """
    envelope_id = "xgate_test_sfe_order"
    store = _store_with_gate(tmp_path, envelope_id)
    register_override(
        "session_fact_extraction_max_sessions_per_tick",
        1,
        prior=2,
        proposed_by="test",
        approved_via="test",
        expires_at="",
        roots=store.roots,
    )

    now = time.time()
    aaa_path = _write_session_file(
        store.roots.hermes_home,
        "session_aaa.json",
        messages=[{"role": "user", "content": _LONG_MARKER_TEXT}],
        mtime=now - 100000,
    )
    zzz_path = _write_session_file(
        store.roots.hermes_home,
        "session_zzz.json",
        messages=[{"role": "user", "content": _LONG_MARKER_TEXT}],
        mtime=now,
    )
    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model",
        _fake_llm_always_durable,
    )

    aaa_stat = aaa_path.stat()
    zzz_stat = zzz_path.stat()
    aaa_fp = _session_fingerprint(session_ref=aaa_path.name, size=aaa_stat.st_size, mtime=aaa_stat.st_mtime)
    zzz_fp = _session_fingerprint(session_ref=zzz_path.name, size=zzz_stat.st_size, mtime=zzz_stat.st_mtime)

    report = run_session_fact_extraction_lane(store, execution_gate_envelope_id=envelope_id)
    assert report["sessions_scanned"] == 2
    assert report["sessions_processed"] == 1  # capped to 1 by the override above

    processed = read_processed_session_fingerprints(store)
    assert zzz_fp in processed
    assert aaa_fp not in processed


def test_max_sessions_per_tick_bounds_work(tmp_path, monkeypatch):
    envelope_id = "xgate_test_sfe_cap"
    store = _store_with_gate(tmp_path, envelope_id)
    now = time.time()
    for i in range(4):
        _write_session_file(
            store.roots.hermes_home,
            f"session_cap_{i}.json",
            messages=[{"role": "user", "content": _LONG_MARKER_TEXT}],
            mtime=now - i,
        )
    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model",
        _fake_llm_always_durable,
    )

    report = run_session_fact_extraction_lane(store, execution_gate_envelope_id=envelope_id)

    assert report["sessions_scanned"] == 4
    assert report["sessions_eligible"] == 4
    # DEFAULT_CONFIG["max_sessions_per_tick"] == 2
    assert report["sessions_processed"] == 2


# ── Output-contract distinguishability: (a) vs (b) vs (c) ────────────────


def test_sessions_dir_absent_is_explicit_not_silent(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="main")
    store = MemoryOSStore(roots)
    store.initialize()
    assert not (store.roots.hermes_home / "sessions").exists()

    report = run_session_fact_extraction_lane(store, execution_gate_envelope_id="")

    assert report["skipped"] is True
    assert report["skipped_reason"] == "sessions_dir_absent"
    assert report["skipped_reason"] in SKIPPED_REASON_CODES
    assert report["sessions_scanned"] == 0
    assert report["candidates_written"] == 0


def test_sessions_dir_present_but_empty_is_distinct_reason(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="main")
    store = MemoryOSStore(roots)
    store.initialize()
    (store.roots.hermes_home / "sessions").mkdir(parents=True, exist_ok=True)

    report = run_session_fact_extraction_lane(store, execution_gate_envelope_id="")

    assert report["skipped"] is True
    assert report["skipped_reason"] == "no_session_files_found"
    assert report["skipped_reason"] != "sessions_dir_absent"


def test_run_report_and_fingerprints_are_persisted_artifacts(tmp_path, monkeypatch):
    envelope_id = "xgate_test_sfe_persist"
    store = _store_with_gate(tmp_path, envelope_id)
    _write_session_file(
        store.roots.hermes_home,
        "session_persist.json",
        messages=[{"role": "user", "content": _LONG_MARKER_TEXT}],
    )
    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model",
        _fake_llm_always_durable,
    )

    report = run_session_fact_extraction_lane(store, execution_gate_envelope_id=envelope_id)
    assert report["candidates_written"] == 1

    runs = read_session_fact_extraction_runs(store)
    assert len(runs) == 1
    assert runs[0]["candidates_written"] == 1
    assert runs[0]["schema_version"] == "memory-os.session_fact_extraction_run.v0"

    fingerprints = read_processed_session_fingerprints(store)
    assert len(fingerprints) == 1


# ── extract_fact_from_message unit coverage ──────────────────────────────


def test_extract_fact_from_message_defers_without_marker(monkeypatch):
    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model",
        _fake_llm_empty,
    )
    result = extract_fact_from_message(_LONG_NO_MARKER_TEXT)
    assert result["has_durable_fact"] is False
    assert result["failure_reason"] == "llm_empty_content"


def test_extract_fact_from_message_defers_rather_than_manufacturing_on_marker(monkeypatch):
    """A durable-marker match must NOT synthesize a fact out of raw transcript.

    fact_judge's marker heuristic answers a boolean about existing content;
    this lane has to generate a summary, and no heuristic summarizes. A
    marker-matched raw clip would re-introduce the very truncation the lane
    exists to undo -- and `fact_judge._DURABLE_MARKERS` contains "用", which
    occurs in nearly any long Chinese message, so such a gate would fire almost
    always. Candidates are resolver-eligible for provisional crystallized, so
    manufacturing here is a governance problem, not just noise.
    """
    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model",
        _fake_llm_empty,
    )
    result = extract_fact_from_message(_LONG_MARKER_TEXT)
    assert result["has_durable_fact"] is False, "must not manufacture a fact from raw text"
    assert result["fact"] == ""
    assert result["failure_reason"] == "llm_empty_content"
    assert result["reason"] == "llm_unavailable_extraction_deferred"


def test_extract_fact_from_message_llm_missing_key_retries_then_defers(monkeypatch):
    calls = {"count": 0}

    def _malformed(prompt, config):
        calls["count"] += 1
        return json.dumps({"fact": "no boolean key here"})

    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model",
        _malformed,
    )
    result = extract_fact_from_message(_LONG_MARKER_TEXT)
    assert result["failure_reason"] == "llm_missing_key"
    assert calls["count"] == 3  # 1 initial + MAX_EXTRACT_RETRIES(2)
    assert result["has_durable_fact"] is False  # deferred, never manufactured


def test_extract_fact_from_message_clean_success_has_no_failure_reason(monkeypatch):
    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model",
        _fake_llm_always_durable,
    )
    result = extract_fact_from_message(_LONG_NO_MARKER_TEXT)
    assert result["failure_reason"] is None
    assert result["has_durable_fact"] is True
    assert result["fact"] == "extracted durable fact text"


def test_extract_fact_from_message_empty_input_is_not_a_model_failure(monkeypatch):
    """An empty message is a content fact, not an outage: no LLM call, and no
    failure_reason (which would otherwise defer the whole session forever).
    """
    def _should_not_be_called(prompt, config):
        raise AssertionError("LLM must not be called for empty input")

    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model",
        _should_not_be_called,
    )
    result = extract_fact_from_message("   ")
    assert result["has_durable_fact"] is False
    assert result["failure_reason"] is None
    assert result["reason"] == "empty_message"


def test_manifest_shape():
    manifest = session_fact_extraction_manifest()
    assert manifest["name"] == "session_fact_extraction"
    assert "run_session_fact_extraction_lane" in manifest["provides"]["commands"]


# ── Counterfactual 5: candidate_id is stable across session appends ──────


def test_appended_session_does_not_duplicate_earlier_facts(tmp_path, monkeypatch):
    """A live session that grows must not re-mint candidates for facts already
    extracted from its unchanged earlier messages.

    The fingerprint intentionally carries mtime so an appended-to session is
    reconsidered. That means message 0 IS re-extracted on the next run. The
    only thing standing between that and a flooded owner-review queue is
    append_candidate_queue's de-duplication by candidate_id
    (crystallized.py:1116) -- which only works if the id is stable.

    Counterfactual: with the session fingerprint folded into the candidate_id
    material, the re-extracted message 0 yields a DIFFERENT id on run 2, the
    dedup guard is bypassed, and the queue holds 3 rows instead of 2.
    """
    envelope_id = "xgate_test_sfe_append_stable"
    store = _store_with_gate(tmp_path, envelope_id)
    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model",
        _fake_llm_always_durable,
    )

    # Run 1: one long message.
    _write_session_file(
        store.roots.hermes_home,
        "session_growing.json",
        messages=[{"role": "user", "content": _LONG_NO_MARKER_TEXT}],
        session_id="sess_growing",
        mtime=1_700_000_000.0,
    )
    first = run_session_fact_extraction_lane(store, execution_gate_envelope_id=envelope_id)
    assert first["candidates_written"] == 1
    after_first = read_candidate_queue(store)
    assert len(after_first) == 1
    first_id = after_first[0].candidate_id

    # Run 2: same session, appended second long message -> new size AND mtime,
    # so the fingerprint changes and the session is reconsidered.
    _write_session_file(
        store.roots.hermes_home,
        "session_growing.json",
        messages=[
            {"role": "user", "content": _LONG_NO_MARKER_TEXT},
            {"role": "user", "content": _LONG_NO_MARKER_TEXT + " second"},
        ],
        session_id="sess_growing",
        mtime=1_700_000_100.0,
    )
    _add_gate_envelope(store, envelope_id + "_2")
    second = run_session_fact_extraction_lane(
        store, execution_gate_envelope_id=envelope_id + "_2"
    )
    assert second["sessions_processed"] == 1, "appended session must be reconsidered"
    assert second["messages_eligible_over_threshold"] == 2

    queue = read_candidate_queue(store)
    ids = [c.candidate_id for c in queue]
    # message 0's candidate is byte-identical to run 1's, so dedup elided it;
    # only message 1 is genuinely new.
    assert first_id in ids, "message 0 must keep its original candidate_id"
    assert len(queue) == 2, f"expected 2 candidates (one per message), got {len(queue)}: {ids}"
    assert len(set(ids)) == len(ids), "no duplicate candidate_ids"


# ── Counterfactual 6: already-processed count is not corrupted by a stat failure ──


def test_skipped_already_processed_count_survives_a_stat_failure(tmp_path, monkeypatch):
    """These counters are the lane's contract for telling "nothing to do"
    apart from "something broke", so their arithmetic has to hold even when
    one file is unreadable.

    sessions_scanned counts only files that stat() succeeded on, so
    already-processed sessions must be derived as scanned - eligible.

    Counterfactual: subtracting the stat-failure count a second time reports
    0 already-processed sessions here instead of 1, understating drain
    progress (and the max(...,0) clamp hides the resulting negative).
    """
    envelope_id = "xgate_test_sfe_stat_fail"
    store = _store_with_gate(tmp_path, envelope_id)
    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model",
        _fake_llm_no_fact,
    )

    # Three sessions: one will be pre-marked processed, one will fail stat(),
    # one is genuinely fresh.
    already = _write_session_file(
        store.roots.hermes_home,
        "session_already.json",
        messages=[{"role": "user", "content": _LONG_NO_MARKER_TEXT}],
        mtime=1_700_000_300.0,
    )
    _write_session_file(
        store.roots.hermes_home,
        "session_broken.json",
        messages=[{"role": "user", "content": _LONG_NO_MARKER_TEXT}],
        mtime=1_700_000_200.0,
    )
    _write_session_file(
        store.roots.hermes_home,
        "session_fresh.json",
        messages=[{"role": "user", "content": _LONG_NO_MARKER_TEXT}],
        mtime=1_700_000_100.0,
    )

    # Pre-record the fingerprint of session_already so it is skipped.
    already_stat = already.stat()
    run_session_fact_extraction_lane  # (import-time reference guard, no-op)
    from plugins.modules.cognition.session_fact_extraction import _append_processed_fingerprint

    _append_processed_fingerprint(
        store,
        fingerprint=_session_fingerprint(
            session_ref=already.name, size=already_stat.st_size, mtime=already_stat.st_mtime
        ),
        execution_gate_envelope_id=envelope_id,
        now=datetime.now(timezone.utc),
        error_records=[],
    )

    # Make exactly one file's stat() fail, leaving all other Path.stat calls intact.
    real_stat = Path.stat

    def _flaky_stat(self, *args, **kwargs):
        if self.name == "session_broken.json":
            raise OSError("simulated stat failure")
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", _flaky_stat)

    _add_gate_envelope(store, envelope_id + "_run")
    report = run_session_fact_extraction_lane(
        store, execution_gate_envelope_id=envelope_id + "_run"
    )

    # session_broken never entered the totals; session_already was skipped as
    # already-processed; session_fresh was eligible.
    assert report["sessions_scanned"] == 2
    assert report["sessions_eligible"] == 1
    assert report["sessions_skipped_already_processed"] == 1
    assert any(
        record.get("error_code") == "session_file_stat_failed"
        for record in report["error_records"]
    ), "the stat failure must still be recorded as a bounded error_record"


# ── Redaction parity: local copy must not drift from the canonical set ───


def test_local_secret_patterns_match_canonical_turn_summary_patterns():
    """This lane reads RAW transcript bodies, not the already-redacted
    140-char event summary that inner_drive candidates come from, so its
    redaction must be at least as strong as the capture path's.

    _SECRET_PATTERNS is a deliberate local copy (avoiding a cross-module
    import for a four-line helper). This test is what keeps the copy honest:
    if the canonical set in __init__.py gains a pattern, this fails instead
    of silently leaking that class of secret into candidates.
    """
    from plugins.memory.memory_os import _TASK_SECRET_PATTERNS
    from plugins.modules.cognition.session_fact_extraction import _SECRET_PATTERNS

    canonical = [pattern.pattern for pattern in _TASK_SECRET_PATTERNS]
    local = [pattern.pattern for pattern in _SECRET_PATTERNS]
    assert local == canonical, (
        "session_fact_extraction._SECRET_PATTERNS drifted from "
        "memory_os._TASK_SECRET_PATTERNS; this lane reads raw transcripts, so "
        "its redaction must not be weaker than the capture path's"
    )


# ── Counterfactual 7: LLM failure must DEFER, not permanently consume the session ──


def test_llm_failure_leaves_session_retryable_and_next_tick_recovers_the_fact(tmp_path, monkeypatch):
    """The lane exists to stop losing facts, so it must not lose them in its
    own most likely failure mode.

    Measured llm_empty_content rate on production fact_judge is 27.5%. If a
    session were fingerprinted as processed on a failed tick, every fact in it
    would be lost for good -- never revisited unless the file itself changes.

    Counterfactual: with the fingerprint appended unconditionally, run 2 sees
    the session as already-processed (sessions_eligible == 0, skipped_reason
    "no_unprocessed_sessions") and the fact is never extracted even though the
    model came back.
    """
    envelope_id = "xgate_test_sfe_defer"
    store = _store_with_gate(tmp_path, envelope_id)
    _write_session_file(
        store.roots.hermes_home,
        "session_defer.json",
        messages=[{"role": "user", "content": _LONG_NO_MARKER_TEXT}],
        session_id="sess_defer",
        mtime=1_700_001_000.0,
    )

    # Tick 1: model is down.
    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model",
        _fake_llm_empty,
    )
    first = run_session_fact_extraction_lane(store, execution_gate_envelope_id=envelope_id)
    assert first["sessions_processed"] == 1
    assert first["llm_failures_by_reason"].get("llm_empty_content") == 1
    assert first["facts_extracted"] == 0
    assert first["sessions_deferred_llm_failure"] == 1, "failure must be recorded as a deferral"
    assert first["candidates_written"] == 0

    # The session must NOT be suppressed from future ticks.
    assert read_processed_session_fingerprints(store) == set(), (
        "a deferred session must not appear as terminally processed"
    )

    # Tick 2: model recovers, same unchanged file.
    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model",
        _fake_llm_always_durable,
    )
    _add_gate_envelope(store, envelope_id + "_2")
    second = run_session_fact_extraction_lane(
        store, execution_gate_envelope_id=envelope_id + "_2"
    )
    assert second["skipped"] is False
    assert second["sessions_eligible"] == 1, "deferred session must be retried"
    assert second["facts_extracted"] == 1
    assert second["candidates_written"] == 1
    assert second["sessions_deferred_llm_failure"] == 0
    # Now it is terminal.
    assert len(read_processed_session_fingerprints(store)) == 1


def test_deferral_is_bounded_and_abandonment_is_recorded(tmp_path, monkeypatch):
    """Deferral cannot be unbounded: a message that always fails would
    otherwise re-consume the per-tick budget forever and starve every other
    session. After MAX_EXTRACTION_ATTEMPTS the session is recorded as
    abandoned -- terminal, but distinguishable in the ledger from a clean
    processed row, so giving up stays visible instead of looking like success.
    """
    envelope_id = "xgate_test_sfe_abandon"
    store = _store_with_gate(tmp_path, envelope_id)
    _write_session_file(
        store.roots.hermes_home,
        "session_abandon.json",
        messages=[{"role": "user", "content": _LONG_NO_MARKER_TEXT}],
        session_id="sess_abandon",
        mtime=1_700_002_000.0,
    )
    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model",
        _fake_llm_empty,
    )

    deferred_ticks = 0
    abandoned = False
    for tick in range(MAX_EXTRACTION_ATTEMPTS + 2):
        gate = f"{envelope_id}_{tick}"
        _add_gate_envelope(store, gate)
        report = run_session_fact_extraction_lane(store, execution_gate_envelope_id=gate)
        deferred_ticks += report["sessions_deferred_llm_failure"]
        if report["sessions_abandoned_after_max_attempts"]:
            abandoned = True
            break

    assert abandoned, "must stop retrying after the attempt budget"
    assert deferred_ticks == MAX_EXTRACTION_ATTEMPTS - 1
    # Terminal now, so later ticks stop spending budget on it.
    assert len(read_processed_session_fingerprints(store)) == 1
    statuses = [
        str(r.get("status") or "")
        for r in read_jsonl(
            store.roots.memory_os_root / "system-modules" / "session_fact_extraction"
            / "processed_sessions.jsonl"
        )
    ]
    assert statuses.count("deferred") == MAX_EXTRACTION_ATTEMPTS - 1
    assert statuses.count("abandoned") == 1
    assert "processed" not in statuses, "a never-extracted session must not read as processed"

    _add_gate_envelope(store, envelope_id + "_after")
    after = run_session_fact_extraction_lane(
        store, execution_gate_envelope_id=envelope_id + "_after"
    )
    assert after["skipped"] is True
    assert after["skipped_reason"] == "no_unprocessed_sessions"


# ── Counterfactual 9: both new ledgers can actually age out ──────────────


def test_new_ledgers_are_retention_registered_and_timestamp_readable(tmp_path, monkeypatch):
    """Backlog item 9 records two sibling ledgers that can never age out
    because they timestamp records with a field _record_created_at() does not
    read. These two must not repeat it.

    Both halves are required, and are checked through the REAL producer rather
    than a hand-written row: an unregistered ledger is invisible to retention
    planning and grows forever, while a registered one whose timestamp is
    unreadable is judged to have no timestamp and is retained forever anyway.

    Counterfactual: renaming the producer field back to processed_at, or
    dropping either _ledger_plan registration, fails this test.
    """
    from plugins.memory.memory_os.metadata_retention import (
        _record_created_at,
        metadata_retention_plan,
    )

    envelope_id = "xgate_test_sfe_retention"
    store = _store_with_gate(tmp_path, envelope_id)
    _write_session_file(
        store.roots.hermes_home,
        "session_retention.json",
        messages=[{"role": "user", "content": _LONG_NO_MARKER_TEXT}],
    )
    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model",
        _fake_llm_always_durable,
    )
    run_session_fact_extraction_lane(store, execution_gate_envelope_id=envelope_id)

    module_root = (
        store.roots.memory_os_root / "system-modules" / "session_fact_extraction"
    )
    for name in ("processed_sessions.jsonl", "runs.jsonl"):
        rows = read_jsonl(module_root / name)
        assert rows, f"{name} should have been written by the real lane run"
        for row in rows:
            assert _record_created_at(row) is not None, (
                f"{name} rows carry a timestamp metadata_retention cannot read, "
                "so they could never age out (backlog item 9's defect)"
            )

    plan = metadata_retention_plan(store.roots)
    planned = {str(entry.get("ledger") or "") for entry in plan["ledgers"]}
    for ledger in (
        "session_fact_extraction_processed_sessions",
        "session_fact_extraction_runs",
    ):
        assert ledger in planned, f"{ledger} is not registered for retention"
    for entry in plan["ledgers"]:
        if str(entry["ledger"]).startswith("session_fact_extraction"):
            assert entry["exists"] is True
            assert entry["retention_days"] is not None
            assert entry["total_records"] > 0, (
                "registered but zero records counted -- the planned path does not "
                "match where the lane actually writes"
            )


def test_candidates_cite_a_real_provenance_event(tmp_path, monkeypatch):
    """CE.2: the crystallized write gate requires non-empty source_event_ids on
    EVERY approval path (owner included), so a candidate born without event
    provenance can never be crystallized. The lane's first five production
    candidates shipped with source_event_ids=[] and crashed every
    candidate_aggregation tick from 12:12Z on.

    Counterfactual: without the fix, candidates[0].source_event_ids == [] and
    no session_fact_extracted event exists.
    """
    envelope_id = "xgate_test_sfe_provenance"
    store = _store_with_gate(tmp_path, envelope_id)
    _write_session_file(
        store.roots.hermes_home,
        "session_prov.json",
        messages=[
            {"role": "user", "content": _LONG_MARKER_TEXT},
            {"role": "user", "content": _LONG_NO_MARKER_TEXT},
        ],
    )
    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model",
        _fake_llm_always_durable,
    )

    report = run_session_fact_extraction_lane(store, execution_gate_envelope_id=envelope_id)

    assert report["candidates_written"] == 2
    candidates = read_candidate_queue(store)
    assert len(candidates) == 2

    events = {event.id: event for event in store.read_events()}
    provenance_events = [
        event for event in events.values() if event.kind == "session_fact_extracted"
    ]
    # One provenance event per session per tick, shared by both facts.
    assert len(provenance_events) == 1
    provenance = provenance_events[0]
    for candidate in candidates:
        assert candidate.source_event_ids == [provenance.id], (
            "every fact candidate must cite the session provenance event"
        )
    # The anchor must not itself spawn a second candidate generation pass.
    assert provenance.safe_ref.get("candidate_allowed") is False
    assert provenance.source == "session_fact_extraction"
