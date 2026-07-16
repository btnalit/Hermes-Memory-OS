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
    assert set(trace) == {"queried_at", "scope"}

    from plugins.memory.memory_os import wandering_journal

    monkeypatch.setattr(wandering_journal, "_rewrite_records_under_lock", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError, match="disk"):
        query_journal(store, scope_class="all")


def test_journal_lineage_expands_to_roots_and_enforces_max_hops(tmp_path):
    store, packet = _store_and_packet(tmp_path)
    first = ingest_thought_batch(
        store,
        packet=packet,
        model_entries=[_entry()],
        ttl_days=3,
        max_entry_chars=200,
        max_lineage_hops=2,
    )[0]

    def derive(source, concept):
        source_ref = "journal:" + source["entry_id"]
        child_packet = build_body_state_packet(
            quiet_state=True,
            source_window={},
            source_cursors={},
            seed_candidates=[{"ref": source_ref, "kind": "private_thought", "bounded_text": source["content"], "epistemic_status": "private_uncommitted", "salience_reasons": []}],
            edges=[],
            sampler_seed=concept,
            max_text_chars=200,
        )
        write_body_packet_manifest(store, child_packet)
        return child_packet, [{"tier": "interpretation", "content": concept, "provenance_refs": [source_ref], "concept_key": concept, "requested_fate": "hold"}]

    packet1, entries1 = derive(first, "hop-one")
    hop_one = ingest_thought_batch(store, packet=packet1, model_entries=entries1, ttl_days=3, max_entry_chars=200, max_lineage_hops=2)[0]
    assert hop_one["lineage_hop"] == 1
    assert hop_one["lineage_root_refs"] == ["crystallized:cry_a"]
    packet2, entries2 = derive(hop_one, "hop-two")
    hop_two = ingest_thought_batch(store, packet=packet2, model_entries=entries2, ttl_days=3, max_entry_chars=200, max_lineage_hops=2)[0]
    assert hop_two["lineage_hop"] == 2
    packet3, entries3 = derive(hop_two, "hop-three")
    with pytest.raises(ValueError, match="lineage_hop"):
        ingest_thought_batch(store, packet=packet3, model_entries=entries3, ttl_days=3, max_entry_chars=200, max_lineage_hops=2)


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
