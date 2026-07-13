from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from plugins.memory.memory_os.store import MemoryOSStore
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.v3_body_packet import (
    build_body_state_packet,
    resolve_body_manifest,
    write_body_packet_manifest,
)
from plugins.memory.memory_os.wandering_journal import (
    ingest_thought_batch,
    query_journal,
    read_journal,
)


def _store_and_packet(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="default"))
    store.initialize()
    packet = build_body_state_packet(
        quiet_state=True,
        source_window={},
        source_cursors={},
        seed_candidates=[
            {
                "ref": "crystallized:cry_a",
                "kind": "stable_memory",
                "bounded_text": "A stable memory",
                "epistemic_status": "approved",
                "salience_reasons": ["co_selected"],
            }
        ],
        edges=[],
        sampler_seed="seed",
    )
    write_body_packet_manifest(store, packet)
    return store, packet


def _entry(**overrides):
    value = {
        "tier": "association",
        "content": "Something briefly came to mind.",
        "felt_tone": None,
        "concern": None,
        "motive_fragment": None,
        "self_narrative_fragment": None,
        "provenance_refs": ["crystallized:cry_a"],
        "concept_key": "brief-thought",
        "requested_fate": "share",
    }
    value.update(overrides)
    return value


def test_ingest_is_all_or_nothing_and_model_cannot_set_terminal_fate(tmp_path):
    store, packet = _store_and_packet(tmp_path)
    entries = ingest_thought_batch(
        store,
        packet=packet,
        model_entries=[_entry(fate="shared")],
        ttl_days=3,
        max_entry_chars=200,
        max_lineage_hops=2,
    )
    assert len(entries) == 1
    row = entries[0]
    assert row["fate"] == "pending"
    assert row["fate_at"] is None
    assert row["fate_ref"] is None
    assert row["outlet_status"] == "queued"
    assert row["epistemic_status"] == "private_uncommitted"

    before = read_journal(store)
    with pytest.raises(ValueError, match="batch_schema_invalid"):
        ingest_thought_batch(
            store,
            packet=packet,
            model_entries=[_entry(), _entry(tier="fact")],
            ttl_days=3,
            max_entry_chars=200,
            max_lineage_hops=2,
        )
    assert read_journal(store) == before


def test_ingest_requires_packet_allowlist_and_non_journal_root(tmp_path):
    store, packet = _store_and_packet(tmp_path)
    with pytest.raises(ValueError, match="provenance_not_in_packet"):
        ingest_thought_batch(
            store,
            packet=packet,
            model_entries=[_entry(provenance_refs=["event:evt_unknown"])],
            ttl_days=3,
            max_entry_chars=200,
            max_lineage_hops=2,
        )


def test_query_trace_is_written_before_results_and_contains_no_query_body(tmp_path, monkeypatch):
    store, packet = _store_and_packet(tmp_path)
    ingest_thought_batch(
        store,
        packet=packet,
        model_entries=[_entry()],
        ttl_days=3,
        max_entry_chars=200,
        max_lineage_hops=2,
    )
    results = query_journal(store, scope_class="tier", tier="association")
    assert len(results) == 1
    rows = read_journal(store)
    trace = rows[-1]
    assert trace["record_type"] == "query_trace"
    assert set(trace) == {
        "record_type",
        "trace_id",
        "queried_at",
        "scope_class",
        "result_count_bucket",
    }

    from plugins.memory.memory_os import wandering_journal

    monkeypatch.setattr(wandering_journal, "_rewrite_records_under_lock", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError, match="disk"):
        query_journal(store, scope_class="all")


def test_empty_model_output_removes_per_run_manifest(tmp_path):
    store, packet = _store_and_packet(tmp_path)
    assert ingest_thought_batch(
        store,
        packet=packet,
        model_entries=[],
        ttl_days=3,
        max_entry_chars=200,
        max_lineage_hops=2,
    ) == []
    with pytest.raises(ValueError, match="manifest_not_found"):
        resolve_body_manifest(store, packet["snapshot_id"])


def test_ingest_rejects_expired_or_nonpositive_ttl(tmp_path):
    store, packet = _store_and_packet(tmp_path)
    with pytest.raises(ValueError, match="ttl_days"):
        ingest_thought_batch(
            store,
            packet=packet,
            model_entries=[_entry()],
            ttl_days=0,
            max_entry_chars=200,
            max_lineage_hops=2,
        )
