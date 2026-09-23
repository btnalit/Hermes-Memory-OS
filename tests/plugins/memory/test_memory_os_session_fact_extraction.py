"""Tests for session_fact_extraction -- offline lane closing the 140-char
turn-summary truncation gap by extracting durable facts from raw session
transcripts too long to have survived `_turn_summary`'s per-side clip.

SFE (2026-09-23): the lane's input moved from the dead
`sessions/session_*.json` files to Hermes' `state.db` (SQLite), filtered
through `principal.resolve_principal`. Fixtures below build a REAL SQLite
file with the schema verified read-only against production (hermes-media
main + sannai), not hand-written dicts -- see the module docstring for the
verified column set.
"""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from plugins.memory.memory_os.config import save_config
from plugins.memory.memory_os.crystallized import read_candidate_queue
from plugins.memory.memory_os.jsonl_io import read_jsonl
from plugins.memory.memory_os.knob_overrides import register_override
from plugins.memory.memory_os.low_clue_recall import LlmCallResult
from plugins.memory.memory_os.roots import MemoryOSRoots, state_db_path
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


# ── state.db fixture builder (real SQLite file, verified schema) ────────
# Columns/types match `PRAGMA table_info` read read-only against hermes-media
# main (2026-09-23): sessions(id TEXT, source TEXT, user_id TEXT,
# started_at REAL, last_activity_at REAL, message_count INTEGER,
# chat_type TEXT, session_key TEXT); messages(id INTEGER, session_id TEXT,
# role TEXT NOT NULL, content TEXT, timestamp REAL).


def _create_state_db(hermes_home: Path) -> Path:
    db_path = state_db_path(MemoryOSRoots.from_hermes_home(hermes_home))
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            user_id TEXT,
            started_at REAL NOT NULL,
            last_activity_at REAL,
            message_count INTEGER DEFAULT 0,
            chat_type TEXT,
            session_key TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT,
            timestamp REAL NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()
    return db_path


def _write_session(
    db_path: Path,
    *,
    session_id: str,
    source: str,
    user_id: str | None = None,
    started_at: float,
    last_activity_at: float | None = None,
    message_count: int | None = None,
    chat_type: str | None = None,
    session_key: str | None = None,
    messages: list[dict] | None = None,
) -> None:
    """Insert (or replace) one session row plus its messages.

    Re-callable with the same ``session_id`` to simulate a growing session:
    replaces the session row (new message_count/last_activity_at) and
    replaces its message rows.
    """
    messages = messages or []
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT OR REPLACE INTO sessions "
        "(id, source, user_id, started_at, last_activity_at, message_count, chat_type, session_key) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            session_id,
            source,
            user_id,
            started_at,
            last_activity_at if last_activity_at is not None else started_at,
            message_count if message_count is not None else len(messages),
            chat_type,
            session_key,
        ),
    )
    conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    for i, msg in enumerate(messages):
        conn.execute(
            "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (session_id, msg["role"], msg["content"], msg.get("timestamp", started_at + i)),
        )
    conn.commit()
    conn.close()


def _configure_owner_identity(hermes_home: Path, platform: str, user_id: str) -> None:
    save_config(
        {"principal": {"owner_identities": {platform: [user_id]}, "binding_sources": {}}},
        hermes_home,
    )


def _fake_llm_always_durable(prompt: str, config: dict) -> LlmCallResult:
    return LlmCallResult(
        text=json.dumps({"has_durable_fact": True, "fact": "extracted durable fact text", "reason": "test"})
    )


def _fake_llm_no_fact(prompt: str, config: dict) -> LlmCallResult:
    return LlmCallResult(
        text=json.dumps({"has_durable_fact": False, "fact": "", "reason": "no durable content"})
    )


def _fake_llm_empty(prompt: str, config: dict) -> LlmCallResult:
    return LlmCallResult(text="", failure_reason="llm_empty_content")


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

    now = time.time()
    db_path = _create_state_db(store.roots.hermes_home)
    _configure_owner_identity(store.roots.hermes_home, "telegram", "owner_uid")
    _write_session(
        db_path,
        session_id="sess_threshold",
        source="telegram",
        user_id="owner_uid",
        started_at=now - 10,
        messages=[
            {"role": "user", "content": _SHORT_TEXT},
            {"role": "user", "content": _LONG_NO_MARKER_TEXT},
        ],
    )
    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model_result",
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
    assert candidates[0].provenance["principal"] == "owner"


def test_session_with_only_short_messages_yields_no_facts(tmp_path, monkeypatch):
    envelope_id = "xgate_test_sfe_all_short"
    store = _store_with_gate(tmp_path, envelope_id)
    now = time.time()
    db_path = _create_state_db(store.roots.hermes_home)
    _configure_owner_identity(store.roots.hermes_home, "telegram", "owner_uid")
    _write_session(
        db_path,
        session_id="sess_allshort",
        source="telegram",
        user_id="owner_uid",
        started_at=now - 10,
        messages=[{"role": "user", "content": _SHORT_TEXT}, {"role": "assistant", "content": "好的"}],
    )
    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model_result",
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
    now = time.time()
    db_path = _create_state_db(store.roots.hermes_home)
    _configure_owner_identity(store.roots.hermes_home, "telegram", "owner_uid")
    _write_session(
        db_path,
        session_id="sess_empty_llm",
        source="telegram",
        user_id="owner_uid",
        started_at=now - 10,
        messages=[{"role": "user", "content": _LONG_MARKER_TEXT}],
    )
    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model_result",
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
    now = time.time()
    db_path = _create_state_db(store.roots.hermes_home)
    _configure_owner_identity(store.roots.hermes_home, "telegram", "owner_uid")
    _write_session(
        db_path,
        session_id="sess_empty_llm_no_marker",
        source="telegram",
        user_id="owner_uid",
        started_at=now - 10,
        messages=[{"role": "user", "content": _LONG_NO_MARKER_TEXT}],
    )
    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model_result",
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
    run would find the same session eligible again (sessions_eligible would
    be 1, not 0) and would re-extract/re-write for it.
    """
    envelope_1 = "xgate_test_sfe_ledger_run1"
    envelope_2 = "xgate_test_sfe_ledger_run2"
    store = _store_with_gate(tmp_path, envelope_1)
    _add_gate_envelope(store, envelope_2)

    now = time.time()
    db_path = _create_state_db(store.roots.hermes_home)
    _configure_owner_identity(store.roots.hermes_home, "telegram", "owner_uid")
    _write_session(
        db_path,
        session_id="sess_ledger",
        source="telegram",
        user_id="owner_uid",
        started_at=now - 10,
        messages=[{"role": "user", "content": _LONG_MARKER_TEXT}],
    )
    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model_result",
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
    assert report2["skipped_reason"] == "no_actionable_sessions"
    assert report2["candidates_written"] == 0


def test_appending_to_a_processed_session_makes_it_eligible_again(tmp_path, monkeypatch):
    """The fingerprint combines message_count+last_activity_at, not just the
    session id, so a session that grew new messages is reconsidered."""
    envelope_1 = "xgate_test_sfe_append_run1"
    envelope_2 = "xgate_test_sfe_append_run2"
    store = _store_with_gate(tmp_path, envelope_1)
    _add_gate_envelope(store, envelope_2)

    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model_result",
        _fake_llm_always_durable,
    )

    now = time.time()
    db_path = _create_state_db(store.roots.hermes_home)
    _configure_owner_identity(store.roots.hermes_home, "telegram", "owner_uid")
    _write_session(
        db_path,
        session_id="sess_grows",
        source="telegram",
        user_id="owner_uid",
        started_at=now - 20,
        last_activity_at=now - 20,
        messages=[{"role": "user", "content": _LONG_MARKER_TEXT}],
    )
    report1 = run_session_fact_extraction_lane(store, execution_gate_envelope_id=envelope_1)
    assert report1["sessions_processed"] == 1

    # Append a second message -> new message_count AND last_activity_at ->
    # different fingerprint.
    _write_session(
        db_path,
        session_id="sess_grows",
        source="telegram",
        user_id="owner_uid",
        started_at=now - 20,
        last_activity_at=now - 5,
        messages=[
            {"role": "user", "content": _LONG_MARKER_TEXT},
            {"role": "assistant", "content": _LONG_MARKER_TEXT + " more"},
        ],
    )

    report2 = run_session_fact_extraction_lane(store, execution_gate_envelope_id=envelope_2)
    assert report2["sessions_eligible"] == 1
    assert report2["sessions_processed"] == 1


# ── Counterfactual 4: newest-first selection ─────────────────────────────


def test_selection_is_newest_first(tmp_path, monkeypatch):
    """A head-of-queue (insertion-order) selector would pick the OLDER
    session first; this lane must pick the NEWER one first (matches the
    original file-based lane's documented newest-mtime-first bias).
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
    db_path = _create_state_db(store.roots.hermes_home)
    _configure_owner_identity(store.roots.hermes_home, "telegram", "owner_uid")
    _write_session(
        db_path,
        session_id="sess_old",
        source="telegram",
        user_id="owner_uid",
        started_at=now - 100000,
        messages=[{"role": "user", "content": _LONG_MARKER_TEXT}],
    )
    _write_session(
        db_path,
        session_id="sess_new",
        source="telegram",
        user_id="owner_uid",
        started_at=now,
        messages=[{"role": "user", "content": _LONG_MARKER_TEXT}],
    )
    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model_result",
        _fake_llm_always_durable,
    )

    report = run_session_fact_extraction_lane(store, execution_gate_envelope_id=envelope_id)
    assert report["sessions_scanned"] == 2
    assert report["sessions_processed"] == 1  # capped to 1 by the override above

    old_fp = _session_fingerprint(session_ref="sess_old", size=1, mtime=now - 100000)
    new_fp = _session_fingerprint(session_ref="sess_new", size=1, mtime=now)

    processed = read_processed_session_fingerprints(store)
    assert new_fp in processed
    assert old_fp not in processed


def test_max_sessions_per_tick_bounds_work(tmp_path, monkeypatch):
    envelope_id = "xgate_test_sfe_cap"
    store = _store_with_gate(tmp_path, envelope_id)
    now = time.time()
    db_path = _create_state_db(store.roots.hermes_home)
    _configure_owner_identity(store.roots.hermes_home, "telegram", "owner_uid")
    for i in range(4):
        _write_session(
            db_path,
            session_id=f"sess_cap_{i}",
            source="telegram",
            user_id="owner_uid",
            started_at=now - i,
            messages=[{"role": "user", "content": _LONG_MARKER_TEXT}],
        )
    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model_result",
        _fake_llm_always_durable,
    )

    report = run_session_fact_extraction_lane(store, execution_gate_envelope_id=envelope_id)

    assert report["sessions_scanned"] == 4
    assert report["sessions_eligible"] == 4
    # DEFAULT_CONFIG["max_sessions_per_tick"] == 2
    assert report["sessions_processed"] == 2


# ── Output-contract distinguishability ────────────────────────────────────


def test_state_db_absent_is_explicit_not_silent(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="main")
    store = MemoryOSStore(roots)
    store.initialize()
    assert not state_db_path(store.roots).exists()

    report = run_session_fact_extraction_lane(store, execution_gate_envelope_id="")

    assert report["skipped"] is True
    assert report["skipped_reason"] == "state_db_absent"
    assert report["skipped_reason"] in SKIPPED_REASON_CODES
    assert report["sessions_scanned"] == 0
    assert report["candidates_written"] == 0


def test_state_db_that_will_not_open_is_not_reported_absent(tmp_path):
    """A state.db that exists but cannot be opened is "input existed but
    could not be read", never "no input": the closed reasons must keep the
    two apart without re-running anything."""
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="main")
    store = MemoryOSStore(roots)
    store.initialize()
    state_db_path(store.roots).mkdir(parents=True)  # exists, cannot open as a database

    report = run_session_fact_extraction_lane(store, execution_gate_envelope_id="")

    assert report["skipped"] is True
    assert report["skipped_reason"] == "state_db_open_failed"


def _candidate_provenance(candidate):
    return candidate.provenance if hasattr(candidate, "provenance") else candidate["provenance"]


def test_candidates_from_a_sender_ambiguous_session_carry_the_marker(tmp_path, monkeypatch):
    """An unsplit group session's single user_id may not be the sender of
    every message in it; an owner reviewing one candidate must see that on
    the candidate itself, not only in the lane's aggregate counter."""
    envelope_id = "xgate_test_sfe_shared_marker"
    store = _store_with_gate(tmp_path, envelope_id)
    now = time.time()
    db_path = _create_state_db(store.roots.hermes_home)
    _configure_owner_identity(store.roots.hermes_home, "telegram", "owner_uid")
    _write_session(
        db_path, session_id="sess_group_unsplit", source="telegram", user_id="owner_uid",
        started_at=now - 20, chat_type="group", session_key="agent:main:telegram:group:-100",
        messages=[{"role": "user", "content": _LONG_MARKER_TEXT}],
    )
    _write_session(
        db_path, session_id="sess_dm", source="telegram", user_id="owner_uid",
        started_at=now - 10, chat_type="dm", session_key="agent:main:telegram:dm:owner_uid",
        messages=[{"role": "user", "content": _LONG_MARKER_TEXT + " dm"}],
    )
    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model_result",
        _fake_llm_always_durable,
    )

    run_session_fact_extraction_lane(store, execution_gate_envelope_id=envelope_id)

    markers = {
        _candidate_provenance(c)["session_id"]: _candidate_provenance(c)["shared_session_unsplit"]
        for c in read_candidate_queue(store)
    }
    assert markers == {"sess_group_unsplit": True, "sess_dm": False}


def test_sessions_table_missing_is_distinct_reason(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="main")
    store = MemoryOSStore(roots)
    store.initialize()
    # state.db exists but has neither a sessions nor a messages table.
    db_path = state_db_path(store.roots)
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE unrelated (x INTEGER)")
    conn.commit()
    conn.close()

    report = run_session_fact_extraction_lane(store, execution_gate_envelope_id="")

    assert report["skipped"] is True
    assert report["skipped_reason"] == "sessions_table_missing"
    assert report["skipped_reason"] != "state_db_absent"


def test_no_sessions_in_window_is_distinct_reason(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="main")
    store = MemoryOSStore(roots)
    store.initialize()
    db_path = _create_state_db(store.roots.hermes_home)
    # A session that exists but is far outside the default 180-day window.
    ancient = time.time() - (400 * 86400)
    _write_session(
        db_path,
        session_id="sess_ancient",
        source="telegram",
        user_id="owner_uid",
        started_at=ancient,
        messages=[{"role": "user", "content": _LONG_MARKER_TEXT}],
    )

    report = run_session_fact_extraction_lane(store, execution_gate_envelope_id="")

    assert report["skipped"] is True
    assert report["skipped_reason"] == "no_sessions_in_window"
    assert report["sessions_scanned"] == 0


def test_run_report_and_fingerprints_are_persisted_artifacts(tmp_path, monkeypatch):
    envelope_id = "xgate_test_sfe_persist"
    store = _store_with_gate(tmp_path, envelope_id)
    now = time.time()
    db_path = _create_state_db(store.roots.hermes_home)
    _configure_owner_identity(store.roots.hermes_home, "telegram", "owner_uid")
    _write_session(
        db_path,
        session_id="sess_persist",
        source="telegram",
        user_id="owner_uid",
        started_at=now - 10,
        messages=[{"role": "user", "content": _LONG_MARKER_TEXT}],
    )
    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model_result",
        _fake_llm_always_durable,
    )

    report = run_session_fact_extraction_lane(store, execution_gate_envelope_id=envelope_id)
    assert report["candidates_written"] == 1

    runs = read_session_fact_extraction_runs(store)
    assert len(runs) == 1
    assert runs[0]["candidates_written"] == 1
    assert runs[0]["schema_version"] == "memory-os.session_fact_extraction_run.v1"
    assert runs[0]["input_source"] == "state_db"

    fingerprints = read_processed_session_fingerprints(store)
    assert len(fingerprints) == 1


# ── extract_fact_from_message unit coverage (unchanged: pure LLM-call logic) ──


def test_extract_fact_from_message_defers_without_marker(monkeypatch):
    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model_result",
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
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model_result",
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
        return LlmCallResult(text=json.dumps({"fact": "no boolean key here"}))

    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model_result",
        _malformed,
    )
    result = extract_fact_from_message(_LONG_MARKER_TEXT)
    assert result["failure_reason"] == "llm_missing_key"
    assert calls["count"] == 3  # 1 initial + MAX_EXTRACT_RETRIES(2)
    assert result["has_durable_fact"] is False  # deferred, never manufactured


def test_extract_fact_from_message_clean_success_has_no_failure_reason(monkeypatch):
    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model_result",
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
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model_result",
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

    The fingerprint intentionally carries last_activity_at so an appended-to
    session is reconsidered. That means message 0 IS re-extracted on the next
    run. The only thing standing between that and a flooded owner-review
    queue is append_candidate_queue's de-duplication by candidate_id
    (crystallized.py:1116) -- which only works if the id is stable.

    Counterfactual: with the session fingerprint folded into the candidate_id
    material, the re-extracted message 0 yields a DIFFERENT id on run 2, the
    dedup guard is bypassed, and the queue holds 3 rows instead of 2.
    """
    envelope_id = "xgate_test_sfe_append_stable"
    store = _store_with_gate(tmp_path, envelope_id)
    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model_result",
        _fake_llm_always_durable,
    )

    now = time.time()
    db_path = _create_state_db(store.roots.hermes_home)
    _configure_owner_identity(store.roots.hermes_home, "telegram", "owner_uid")

    # Run 1: one long message.
    _write_session(
        db_path,
        session_id="sess_growing",
        source="telegram",
        user_id="owner_uid",
        started_at=now - 100,
        last_activity_at=now - 100,
        messages=[{"role": "user", "content": _LONG_NO_MARKER_TEXT}],
    )
    first = run_session_fact_extraction_lane(store, execution_gate_envelope_id=envelope_id)
    assert first["candidates_written"] == 1
    after_first = read_candidate_queue(store)
    assert len(after_first) == 1
    first_id = after_first[0].candidate_id

    # Run 2: same session, appended second long message -> new message_count
    # AND last_activity_at, so the fingerprint changes and the session is
    # reconsidered.
    _write_session(
        db_path,
        session_id="sess_growing",
        source="telegram",
        user_id="owner_uid",
        started_at=now - 100,
        last_activity_at=now - 10,
        messages=[
            {"role": "user", "content": _LONG_NO_MARKER_TEXT},
            {"role": "user", "content": _LONG_NO_MARKER_TEXT + " second"},
        ],
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


# ── Counterfactual 6: LLM failure must DEFER, not permanently consume the session ──


def test_llm_failure_leaves_session_retryable_and_next_tick_recovers_the_fact(tmp_path, monkeypatch):
    """The lane exists to stop losing facts, so it must not lose them in its
    own most likely failure mode.

    Measured llm_empty_content rate on production fact_judge is 27.5%. If a
    session were fingerprinted as processed on a failed tick, every fact in it
    would be lost for good -- never revisited unless the row itself changes.

    Counterfactual: with the fingerprint appended unconditionally, run 2 sees
    the session as already-processed (sessions_eligible == 0, skipped_reason
    "no_actionable_sessions") and the fact is never extracted even though the
    model came back.
    """
    envelope_id = "xgate_test_sfe_defer"
    store = _store_with_gate(tmp_path, envelope_id)
    now = time.time()
    db_path = _create_state_db(store.roots.hermes_home)
    _configure_owner_identity(store.roots.hermes_home, "telegram", "owner_uid")
    _write_session(
        db_path,
        session_id="sess_defer",
        source="telegram",
        user_id="owner_uid",
        started_at=now - 1000,
        messages=[{"role": "user", "content": _LONG_NO_MARKER_TEXT}],
    )

    # Tick 1: model is down.
    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model_result",
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

    # Tick 2: model recovers, same unchanged row.
    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model_result",
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
    now = time.time()
    db_path = _create_state_db(store.roots.hermes_home)
    _configure_owner_identity(store.roots.hermes_home, "telegram", "owner_uid")
    _write_session(
        db_path,
        session_id="sess_abandon",
        source="telegram",
        user_id="owner_uid",
        started_at=now - 2000,
        messages=[{"role": "user", "content": _LONG_NO_MARKER_TEXT}],
    )
    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model_result",
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
    assert after["skipped_reason"] == "no_actionable_sessions"


# ── Counterfactual 7: both new ledgers can actually age out ──────────────


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
    now = time.time()
    db_path = _create_state_db(store.roots.hermes_home)
    _configure_owner_identity(store.roots.hermes_home, "telegram", "owner_uid")
    _write_session(
        db_path,
        session_id="sess_retention",
        source="telegram",
        user_id="owner_uid",
        started_at=now - 10,
        messages=[{"role": "user", "content": _LONG_NO_MARKER_TEXT}],
    )
    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model_result",
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
    now = time.time()
    db_path = _create_state_db(store.roots.hermes_home)
    _configure_owner_identity(store.roots.hermes_home, "telegram", "owner_uid")
    _write_session(
        db_path,
        session_id="sess_prov",
        source="telegram",
        user_id="owner_uid",
        started_at=now - 10,
        messages=[
            {"role": "user", "content": _LONG_MARKER_TEXT},
            {"role": "user", "content": _LONG_NO_MARKER_TEXT},
        ],
    )
    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model_result",
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
    assert provenance.safe_ref.get("principal") == "owner"


# ── Principal filter (P0-lite integration, 2026-09-23) ───────────────────


def test_owner_telegram_session_produces_candidate(tmp_path, monkeypatch):
    envelope_id = "xgate_test_sfe_principal_owner"
    store = _store_with_gate(tmp_path, envelope_id)
    now = time.time()
    db_path = _create_state_db(store.roots.hermes_home)
    _configure_owner_identity(store.roots.hermes_home, "telegram", "owner_uid")
    _write_session(
        db_path,
        session_id="sess_owner",
        source="telegram",
        user_id="owner_uid",
        started_at=now - 10,
        messages=[{"role": "user", "content": _LONG_MARKER_TEXT}],
    )
    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model_result",
        _fake_llm_always_durable,
    )

    report = run_session_fact_extraction_lane(store, execution_gate_envelope_id=envelope_id)

    assert report["candidates_written"] == 1
    assert report["sessions_skipped_by_principal"] == {}
    candidates = read_candidate_queue(store)
    assert candidates[0].provenance["principal"] == "owner"


def test_other_human_telegram_session_is_skipped_and_counted(tmp_path, monkeypatch):
    """A telegram session from a DIFFERENT user_id than the configured owner
    identity must resolve to other_human and never reach the LLM."""
    envelope_id = "xgate_test_sfe_principal_other_human"
    store = _store_with_gate(tmp_path, envelope_id)
    now = time.time()
    db_path = _create_state_db(store.roots.hermes_home)
    _configure_owner_identity(store.roots.hermes_home, "telegram", "owner_uid")
    _write_session(
        db_path,
        session_id="sess_stranger",
        source="telegram",
        user_id="stranger_uid",
        started_at=now - 10,
        messages=[{"role": "user", "content": _LONG_MARKER_TEXT}],
    )

    def _should_not_be_called(prompt, config):
        raise AssertionError("LLM must not be called for a non-owner session")

    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model_result",
        _should_not_be_called,
    )

    report = run_session_fact_extraction_lane(store, execution_gate_envelope_id=envelope_id)

    assert report["skipped"] is True
    assert report["skipped_reason"] == "no_actionable_sessions"
    assert report["sessions_scanned"] == 1
    assert report["sessions_skipped_by_principal"] == {"other_human": 1}
    assert report["llm_calls"] == 0
    assert report["candidates_written"] == 0

    # Durably fingerprinted: a second run must not re-derive/re-count it.
    report2 = run_session_fact_extraction_lane(store, execution_gate_envelope_id=envelope_id + "_2")
    assert report2["sessions_skipped_already_processed"] == 1
    assert report2["sessions_skipped_by_principal"] == {}


def test_mailbox_session_is_skipped_as_peer_agent(tmp_path, monkeypatch):
    """mailbox is Hermes' agent-to-agent channel (owner ruling 2026-09-23):
    never owner-authenticated, regardless of any configured identity."""
    envelope_id = "xgate_test_sfe_principal_mailbox"
    store = _store_with_gate(tmp_path, envelope_id)
    now = time.time()
    db_path = _create_state_db(store.roots.hermes_home)
    _write_session(
        db_path,
        session_id="sess_mailbox",
        source="mailbox",
        user_id="peer_uid",
        started_at=now - 10,
        messages=[{"role": "user", "content": _LONG_MARKER_TEXT}],
    )

    def _should_not_be_called(prompt, config):
        raise AssertionError("LLM must not be called for a mailbox (peer_agent) session")

    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model_result",
        _should_not_be_called,
    )

    report = run_session_fact_extraction_lane(store, execution_gate_envelope_id=envelope_id)

    assert report["skipped"] is True
    assert report["skipped_reason"] == "no_actionable_sessions"
    assert report["sessions_skipped_by_principal"] == {"peer_agent": 1}
    assert report["candidates_written"] == 0


def test_cron_and_subagent_sessions_are_skipped_as_system(tmp_path, monkeypatch):
    """Machine sessions never reach extraction, and (unlike peer_agent/
    other_human) are never durably fingerprinted -- see the module docstring
    on why persisting a terminal row for ~95% of production session volume
    would be an unbounded ledger for zero benefit.
    """
    envelope_id = "xgate_test_sfe_principal_machine"
    store = _store_with_gate(tmp_path, envelope_id)
    now = time.time()
    db_path = _create_state_db(store.roots.hermes_home)
    _write_session(
        db_path,
        session_id="sess_cron_1",
        source="cron",
        user_id=None,
        started_at=now - 10,
        messages=[{"role": "user", "content": _LONG_MARKER_TEXT}],
    )
    _write_session(
        db_path,
        session_id="sess_subagent_1",
        source="subagent",
        user_id=None,
        started_at=now - 9,
        messages=[{"role": "user", "content": _LONG_MARKER_TEXT}],
    )

    def _should_not_be_called(prompt, config):
        raise AssertionError("LLM must not be called for a machine session")

    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model_result",
        _should_not_be_called,
    )

    report = run_session_fact_extraction_lane(store, execution_gate_envelope_id=envelope_id)

    assert report["skipped"] is True
    assert report["skipped_reason"] == "no_actionable_sessions"
    # Machine sessions are excluded in SQL (they would otherwise fill the
    # scan window) and counted separately, so nothing is "scanned".
    assert report["sessions_scanned"] == 0
    assert report["sessions_skipped_by_principal"] == {"system": 2}

    # Never durably fingerprinted -- a second run re-derives the same result
    # (not "already processed"), proving no ledger row was written for them.
    report2 = run_session_fact_extraction_lane(store, execution_gate_envelope_id=envelope_id + "_2")
    assert report2["sessions_skipped_by_principal"] == {"system": 2}
    assert report2["sessions_skipped_already_processed"] == 0
    assert read_processed_session_fingerprints(store) == set()


def test_unconfigured_platform_session_is_processed_as_unknown_compat(tmp_path, monkeypatch):
    """principal.py: an unconfigured platform resolves to `unknown`, the
    pre-2026-09 compatibility state -- NOT a rejection. It must still be
    extracted, matching "only owner and unknown may produce owner facts".
    """
    envelope_id = "xgate_test_sfe_principal_unknown_compat"
    store = _store_with_gate(tmp_path, envelope_id)
    now = time.time()
    db_path = _create_state_db(store.roots.hermes_home)
    # No principal.owner_identities configured for "weixin" at all.
    _write_session(
        db_path,
        session_id="sess_weixin",
        source="weixin",
        user_id="some_uid",
        started_at=now - 10,
        messages=[{"role": "user", "content": _LONG_MARKER_TEXT}],
    )
    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model_result",
        _fake_llm_always_durable,
    )

    report = run_session_fact_extraction_lane(store, execution_gate_envelope_id=envelope_id)

    assert report["skipped"] is False
    assert report["sessions_eligible"] == 1
    assert report["sessions_skipped_by_principal"] == {}
    assert report["candidates_written"] == 1
    candidates = read_candidate_queue(store)
    assert candidates[0].provenance["principal"] == "unknown"


# ── Counterfactual 8: numeric epoch windowing, never an ISO string ───────


def test_epoch_iso_windowing_counterfactual(tmp_path, monkeypatch):
    """`sessions.started_at` is an epoch-seconds REAL column. Comparing it to
    an ISO-formatted string does not raise -- SQLite's type affinity makes a
    REAL-vs-TEXT comparison always false -- so a real in-window owner session
    would silently vanish from every query if the cutoff were ever built as a
    string instead of a float.

    Counterfactual: sabotage `_lookback_cutoff_epoch` to return an ISO string;
    the real session must then be invisible (no_sessions_in_window) despite
    genuinely existing. Restoring the real cutoff must find it again.
    """
    import plugins.modules.cognition.session_fact_extraction as sfe_module

    envelope_id = "xgate_test_sfe_epoch_iso"
    store = _store_with_gate(tmp_path, envelope_id)
    now = time.time()
    db_path = _create_state_db(store.roots.hermes_home)
    _configure_owner_identity(store.roots.hermes_home, "telegram", "owner_uid")
    _write_session(
        db_path,
        session_id="sess_epoch_check",
        source="telegram",
        user_id="owner_uid",
        started_at=now - 10,
        messages=[{"role": "user", "content": _LONG_MARKER_TEXT}],
    )
    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model_result",
        _fake_llm_always_durable,
    )

    def _sabotaged_cutoff(now_dt, lookback_days):
        return now_dt.isoformat()  # BUG: string, not epoch-seconds float

    monkeypatch.setattr(sfe_module, "_lookback_cutoff_epoch", _sabotaged_cutoff)
    broken = run_session_fact_extraction_lane(store, execution_gate_envelope_id=envelope_id)
    assert broken["skipped"] is True
    assert broken["skipped_reason"] == "no_sessions_in_window"
    assert broken["sessions_scanned"] == 0

    monkeypatch.undo()
    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model_result",
        _fake_llm_always_durable,
    )
    fixed = run_session_fact_extraction_lane(store, execution_gate_envelope_id=envelope_id + "_fixed")
    assert fixed["skipped"] is False
    assert fixed["sessions_scanned"] == 1
    assert fixed["candidates_written"] == 1


# ── Counterfactual 9: oversize message content is clipped at the SQL layer ──


def test_oversize_message_content_is_clipped_at_the_sql_layer(tmp_path):
    """A production message has been measured at 975,665 characters. The
    fetch helper must clip via `substr()` so an oversized body never leaves
    SQLite as an unbounded Python string.

    Counterfactual: reading the bare `content` column (no substr bound)
    would return the full length instead of the clipped one.
    """
    from plugins.modules.cognition.session_fact_extraction import _fetch_eligible_role_messages

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="main")
    store = MemoryOSStore(roots)
    store.initialize()
    now = time.time()
    db_path = _create_state_db(store.roots.hermes_home)
    huge_content = "x" * 50_000
    _write_session(
        db_path,
        session_id="sess_huge",
        source="telegram",
        user_id="owner_uid",
        started_at=now - 10,
        messages=[{"role": "user", "content": huge_content}],
    )

    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = _fetch_eligible_role_messages(conn, session_id="sess_huge", max_message_chars=4000)
    finally:
        conn.close()

    assert len(rows) == 1
    assert len(rows[0]["content"]) == 4000, "content must be clipped to max_message_chars at the SQL layer"


def test_fetch_eligible_role_messages_excludes_tool_and_session_meta_roles(tmp_path):
    from plugins.modules.cognition.session_fact_extraction import _fetch_eligible_role_messages

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="main")
    store = MemoryOSStore(roots)
    store.initialize()
    now = time.time()
    db_path = _create_state_db(store.roots.hermes_home)
    _write_session(
        db_path,
        session_id="sess_roles",
        source="telegram",
        user_id="owner_uid",
        started_at=now - 10,
        messages=[
            {"role": "session_meta", "content": "meta"},
            {"role": "user", "content": _LONG_MARKER_TEXT},
            {"role": "tool", "content": "tool output"},
            {"role": "assistant", "content": _LONG_MARKER_TEXT},
        ],
    )

    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = _fetch_eligible_role_messages(conn, session_id="sess_roles", max_message_chars=4000)
    finally:
        conn.close()

    roles = [row["role"] for row in rows]
    assert roles == ["user", "assistant"]


# ── Counterfactual 10: backlog drains across runs ────────────────────────


def test_machine_sessions_cannot_starve_an_older_owner_session_out_of_the_scan_window(tmp_path, monkeypatch):
    """Counterfactual: machine sessions are ~95% of production volume and are
    never fingerprinted. If they count against the newest-first scan LIMIT,
    they fill it every tick and an owner session older than the window is
    never scanned -- the backlog can never drain."""
    envelope_id = "xgate_test_sfe_machine_starvation"
    store = _store_with_gate(tmp_path, envelope_id)
    register_override(
        "session_fact_extraction_max_sessions_scanned_per_tick",
        10,
        prior=500,
        proposed_by="test",
        approved_via="test",
        expires_at="",
        roots=store.roots,
    )
    now = time.time()
    db_path = _create_state_db(store.roots.hermes_home)
    _configure_owner_identity(store.roots.hermes_home, "telegram", "owner_uid")
    _write_session(
        db_path,
        session_id="sess_owner_old",
        source="telegram",
        user_id="owner_uid",
        started_at=now - 3600,
        messages=[{"role": "user", "content": _LONG_MARKER_TEXT}],
    )
    for i in range(12):
        _write_session(
            db_path,
            session_id=f"sess_cron_{i}",
            source="cron" if i % 2 else "subagent",
            user_id=None,
            started_at=now - 60 + i,
            messages=[{"role": "user", "content": _LONG_MARKER_TEXT}],
        )
    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model_result",
        _fake_llm_always_durable,
    )

    report = run_session_fact_extraction_lane(store, execution_gate_envelope_id=envelope_id)

    assert report["sessions_processed"] == 1
    assert report["sessions_skipped_by_principal"] == {"system": 12}


def test_backlog_drains_across_runs(tmp_path, monkeypatch):
    """With max_sessions_per_tick=1 and 3 owner-eligible sessions, three runs
    must each process a DIFFERENT session and the backlog must fully drain --
    never re-picking an already-processed one (head-of-queue starvation) and
    never leaving a session permanently stuck.
    """
    envelope_id = "xgate_test_sfe_backlog"
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
    db_path = _create_state_db(store.roots.hermes_home)
    _configure_owner_identity(store.roots.hermes_home, "telegram", "owner_uid")
    session_ids = ["sess_bl_0", "sess_bl_1", "sess_bl_2"]
    for i, sid in enumerate(session_ids):
        _write_session(
            db_path,
            session_id=sid,
            source="telegram",
            user_id="owner_uid",
            started_at=now - (10 - i),
            messages=[{"role": "user", "content": _LONG_MARKER_TEXT}],
        )
    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model_result",
        _fake_llm_always_durable,
    )

    seen_candidate_counts = []
    for i in range(3):
        gate = f"{envelope_id}_{i}"
        _add_gate_envelope(store, gate)
        report = run_session_fact_extraction_lane(store, execution_gate_envelope_id=gate)
        assert report["sessions_processed"] == 1
        seen_candidate_counts.append(report["candidates_written"])

    assert seen_candidate_counts == [1, 1, 1]
    assert len(read_candidate_queue(store)) == 3
    assert len(read_processed_session_fingerprints(store)) == 3

    # Backlog is fully drained: a fourth run finds nothing left to do.
    _add_gate_envelope(store, envelope_id + "_drained")
    drained = run_session_fact_extraction_lane(store, execution_gate_envelope_id=envelope_id + "_drained")
    assert drained["skipped"] is True
    assert drained["skipped_reason"] == "no_actionable_sessions"
    assert drained["sessions_skipped_already_processed"] == 3


# ── Group-chat tripwire (INFO, not a gate) ───────────────────────────────


def test_group_session_tripwire_counts_missing_user_suffix(tmp_path, monkeypatch):
    envelope_id = "xgate_test_sfe_group_tripwire"
    store = _store_with_gate(tmp_path, envelope_id)
    now = time.time()
    db_path = _create_state_db(store.roots.hermes_home)
    _configure_owner_identity(store.roots.hermes_home, "telegram", "owner_uid")
    # A properly per-sender-split group session: session_key carries the
    # sender's user_id.
    _write_session(
        db_path,
        session_id="sess_group_ok",
        source="telegram",
        user_id="owner_uid",
        started_at=now - 10,
        chat_type="group",
        session_key="agent:main:group123:owner_uid",
        messages=[{"role": "user", "content": _LONG_MARKER_TEXT}],
    )
    # A group session whose key does NOT carry the sender's user_id (the
    # per-sender split is not happening for this chat).
    _write_session(
        db_path,
        session_id="sess_group_bad",
        source="telegram",
        user_id="owner_uid",
        started_at=now - 9,
        chat_type="group",
        session_key="agent:main:group123",
        messages=[{"role": "user", "content": _LONG_MARKER_TEXT}],
    )
    monkeypatch.setattr(
        "plugins.modules.cognition.session_fact_extraction._call_hermes_runtime_model_result",
        _fake_llm_always_durable,
    )

    report = run_session_fact_extraction_lane(store, execution_gate_envelope_id=envelope_id)

    assert report["group_sessions_scanned"] == 2
    assert report["group_sessions_without_user_suffix"] == 1
