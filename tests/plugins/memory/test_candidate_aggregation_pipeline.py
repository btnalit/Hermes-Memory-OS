"""Tests for candidate_aggregation pipeline — mutual exclusion via processed_ids.

Tests the pipeline stage logic directly. Uses a real MemoryOSStore with
a pre-created execution gate envelope so append_candidate_triage succeeds.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from plugins.memory.memory_os.crystallized import (
    CrystallizedCandidate,
    read_candidate_queue,
    append_candidate_queue,
    read_candidate_triage,
)
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore, StoreError
from plugins.modules.governance.candidate_aggregation import (
    _cluster_and_promote,
    _demote_aged,
    _tag_fleeting,
    _auto_demote_rejected,
    _REJECTION_THRESHOLD,
)

# Valid execution-gate envelope ID written to the store's gate envelope file
_VALID_ENVELOPE_ID = "xgate_test_candidate_aggregation_envelope"


def _store_with_gate(tmp_path) -> MemoryOSStore:
    """Create an initialized store with a pre-written valid execution-gate envelope."""
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    store = MemoryOSStore(roots)
    store.initialize()

    # Write a valid permit envelope so append_candidate_triage passes
    # the structural_write_gate check.
    now = datetime.now(timezone.utc)
    expires_at = now.replace(year=now.year + 1).isoformat().replace("+00:00", "Z")
    envelope = {
        "schema_version": "memory-os.execution_gate_envelope.v0",
        "stage": "permit",
        "execution_gate_envelope_id": _VALID_ENVELOPE_ID,
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": expires_at,
        "profile": "memoryos-test",
        "lane_id": "candidate_aggregation",
        "trigger_surface": "hermes_cron",
        "risk_class": "bounded_reversible_queue",
        "human_approval_required": False,
        "why_no_human_approval": "test",
        "scope": {"registry_key": "candidate_aggregation", "raw_script": "test"},
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
    gate_path = roots.hermes_home / "memory-os" / "system" / "execution_gate_envelopes.jsonl"
    gate_path.parent.mkdir(parents=True, exist_ok=True)
    with gate_path.open("a") as f:
        f.write(json.dumps(envelope, sort_keys=True) + "\n")

    return store


def _candidate(candidate_id="cand-test-001", kind="moment",
               body="记住：每次都要备份数据", rejection_count=0,
               bridge_state="", created_at=None):
    now = created_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return CrystallizedCandidate(
        candidate_id=candidate_id,
        kind=kind,
        body=body,
        source_event_ids=["evt-test-001"],
        sensitivity="private",
        tags=["test"],
        bridge_state=bridge_state,
        created_at=now,
        rejection_count=rejection_count,
    )


def test_processed_ids_prevent_duplicate_processing(tmp_path):
    """Once a candidate_id is in processed_ids, no stage should process it."""
    store = _store_with_gate(tmp_path)
    c = _candidate("cand-001", body="好的")
    processed: set[str] = {"cand-001"}

    rejected = _auto_demote_rejected([c], store, processed,
                                     envelope_id=_VALID_ENVELOPE_ID)
    promoted = _cluster_and_promote([c], store, processed,
                                    envelope_id=_VALID_ENVELOPE_ID)
    demoted = _demote_aged([c], store, processed,
                           envelope_id=_VALID_ENVELOPE_ID)
    fleeting = _tag_fleeting([c], store, processed,
                             envelope_id=_VALID_ENVELOPE_ID)

    assert rejected["rejected_demoted_count"] == 0
    assert promoted["promoted_count"] == 0
    assert demoted["demoted_count"] == 0
    assert fleeting["fleeting_count"] == 0


def test_processed_ids_accumulates_across_stages(tmp_path):
    """processed_ids from stage A prevents double-processing by stage B."""
    store = _store_with_gate(tmp_path)
    chat = _candidate("cand-chat", body="好的")
    signal = _candidate("cand-signal", body="记住：每次都必须备份用户数据，这是不可妥协的规则")

    processed: set[str] = set()

    # Stage 1: auto-demote rejected (none rejected → processed stays empty)
    r1 = _auto_demote_rejected([chat, signal], store, processed,
                               envelope_id=_VALID_ENVELOPE_ID)
    assert r1["rejected_demoted_count"] == 0
    assert len(processed) == 0

    # Stage 2: _tag_fleeting tags chat → chat added to processed
    r2 = _tag_fleeting([chat, signal], store, processed,
                       envelope_id=_VALID_ENVELOPE_ID)
    assert r2["fleeting_count"] == 1, f"Expected 1 fleeting, got {r2}"
    assert "cand-chat" in processed

    # Stage 3: _cluster_and_promote should skip chat (in processed),
    # only consider signal. Without a cluster partner (size < 2),
    # signal gets 0 promoted count but should not error.
    r3 = _cluster_and_promote([chat, signal], store, processed,
                              envelope_id=_VALID_ENVELOPE_ID)
    assert r3["promoted_count"] == 0
    # signal may or may not be added to processed — that's fine
    # The key contract: chat is NOT processed again
    assert "cand-chat" in processed
    assert "cand-signal" in r3.get("clusters", []) or "cand-signal" not in processed


def test_auto_demote_rejected_at_threshold(tmp_path):
    """_auto_demote_rejected demotes candidates with rejection_count >= threshold."""
    store = _store_with_gate(tmp_path)
    over = _candidate("cand-over", body="记住：规则1",
                      rejection_count=_REJECTION_THRESHOLD)
    under = _candidate("cand-under", body="记住：规则2",
                       rejection_count=_REJECTION_THRESHOLD - 1)
    zero = _candidate("cand-zero", body="记住：规则3", rejection_count=0)

    processed: set[str] = set()
    result = _auto_demote_rejected([over, under, zero], store, processed,
                                   envelope_id=_VALID_ENVELOPE_ID)

    assert result["rejected_demoted_count"] == 1
    assert "cand-over" in processed
    assert "cand-under" not in processed
    assert "cand-zero" not in processed


def test_auto_demote_rejected_skips_processed(tmp_path):
    """Already-processed candidates are skipped by _auto_demote_rejected."""
    store = _store_with_gate(tmp_path)
    over = _candidate("cand-over", body="记住：规则1",
                      rejection_count=_REJECTION_THRESHOLD)
    processed: set[str] = {"cand-over"}

    result = _auto_demote_rejected([over], store, processed,
                                   envelope_id=_VALID_ENVELOPE_ID)
    assert result["rejected_demoted_count"] == 0


def test_demote_aged_skips_processed(tmp_path):
    """_demote_aged skips candidates in processed_ids."""
    store = _store_with_gate(tmp_path)
    old = _candidate("cand-old", body="记住：规则1",
                     created_at="2026-05-20T00:00:00Z")
    processed: set[str] = {"cand-old"}

    result = _demote_aged([old], store, processed,
                          envelope_id=_VALID_ENVELOPE_ID)
    assert result["demoted_count"] == 0


def test_fleeting_skips_processed(tmp_path):
    """_tag_fleeting skips candidates in processed_ids."""
    store = _store_with_gate(tmp_path)
    chat = _candidate("cand-chat", body="好的")
    processed: set[str] = {"cand-chat"}

    result = _tag_fleeting([chat], store, processed,
                           envelope_id=_VALID_ENVELOPE_ID)
    assert result["fleeting_count"] == 0


def test_rejection_count_dataclass_field():
    """CrystallizedCandidate correctly carries rejection_count."""
    c = _candidate("cand-rc", body="记住：规则1", rejection_count=5)
    assert c.rejection_count == 5

    c_default = _candidate("cand-default", body="记住：规则1")
    assert c_default.rejection_count == 0
