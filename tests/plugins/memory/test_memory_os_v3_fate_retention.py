from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from plugins.memory.memory_os.store import MemoryOSStore
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.v3_body_packet import build_body_state_packet, resolve_body_manifest, write_body_packet_manifest
from plugins.memory.memory_os.v3_fate import claim_outlet, close_outlet, complete_proposal, complete_share
from plugins.memory.memory_os.v3_retention import sweep_pending_expired
from plugins.memory.memory_os.wandering_journal import ingest_thought_batch, query_journal, read_journal


def _setup(tmp_path, *, tier="association", requested_fate="share", ttl_days=3):
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
                "bounded_text": "A",
                "epistemic_status": "approved",
                "salience_reasons": [],
            }
        ],
        edges=[],
        sampler_seed="s",
    )
    write_body_packet_manifest(store, packet)
    entries = ingest_thought_batch(
        store,
        packet=packet,
        model_entries=[
            {
                "tier": tier,
                "content": "A private thought",
                "provenance_refs": ["crystallized:cry_a"],
                "concept_key": "private-thought",
                "requested_fate": requested_fate,
            }
        ],
        ttl_days=ttl_days,
        max_entry_chars=200,
        max_lineage_hops=2,
    )
    return store, packet, entries[0]


def test_share_fate_requires_cas_claim_and_verified_delivery_receipt(tmp_path):
    store, _packet, entry = _setup(tmp_path)
    claimed = claim_outlet(store, entry["entry_id"], expected_requested_fate="share")
    assert claimed["outlet_status"] == "claimed"
    with pytest.raises(ValueError, match="not_queued"):
        claim_outlet(store, entry["entry_id"], expected_requested_fate="share")
    with pytest.raises(ValueError, match="delivery_receipt"):
        complete_share(store, entry["entry_id"], {"delivery_succeeded": False})

    completed = complete_share(
        store,
        entry["entry_id"],
        {
            "entry_id": entry["entry_id"],
            "delivery_succeeded": True,
            "receipt_id": "delivery_1",
        },
    )
    assert completed["fate"] == "shared"
    assert completed["fate_ref"] == "delivery_1"
    assert completed["outlet_status"] == "completed"


def test_claim_proposal_requires_body_and_provenance_bound_candidate_receipt(tmp_path):
    store, _packet, entry = _setup(tmp_path, tier="claim", requested_fate="propose")
    claim_outlet(store, entry["entry_id"], expected_requested_fate="propose")
    with pytest.raises(ValueError, match="candidate_receipt"):
        complete_proposal(
            store,
            entry["entry_id"],
            {"candidate_id": "cand_1", "body_hash": "wrong", "provenance_refs": []},
        )
    completed = complete_proposal(
        store,
        entry["entry_id"],
        {
            "candidate_id": "cand_1",
            "body_hash": entry["content_hash"],
            "provenance_refs": entry["provenance_refs"],
        },
    )
    assert completed["fate"] == "proposed"
    assert completed["fate_ref"] == "cand_1"


def test_closed_outlet_stays_pending_and_cannot_reopen(tmp_path):
    store, _packet, entry = _setup(tmp_path)
    claim_outlet(store, entry["entry_id"], expected_requested_fate="share")
    closed = close_outlet(store, entry["entry_id"], reason_code="silent")
    assert closed["outlet_status"] == "closed"
    assert closed["fate"] == "pending"
    with pytest.raises(ValueError, match="not_queued"):
        claim_outlet(store, entry["entry_id"], expected_requested_fate="share")


def test_ttl_physically_deletes_only_pending_and_orphan_manifest(tmp_path):
    store, packet, entry = _setup(tmp_path)
    query_journal(store, scope_class="all")
    journal_path = store.roots.memory_os_root / "system" / "wandering_journal.jsonl"
    rows = read_journal(store)
    rows[0]["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    from plugins.memory.memory_os.jsonl_io import write_jsonl_atomic_locked

    write_jsonl_atomic_locked(journal_path, rows)
    report = sweep_pending_expired(store, now=datetime.now(timezone.utc))
    assert report == {"cycle_status": "ok"}
    assert entry["entry_id"] not in journal_path.read_text(encoding="utf-8")
    assert any(item.get("record_type") == "query_trace" for item in read_journal(store))
    with pytest.raises(ValueError, match="manifest_not_found"):
        resolve_body_manifest(store, packet["snapshot_id"])
    status_path = store.roots.memory_os_root / "system" / "v3_journal_sweep_status.json"
    assert status_path.read_text(encoding="utf-8").strip() == '{"cycle_status":"ok"}'
