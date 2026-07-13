from __future__ import annotations

from datetime import datetime, timedelta, timezone

from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.memory.memory_os.v3_body_packet import build_body_state_packet, write_body_packet_manifest
from plugins.memory.memory_os.v3_outlet import V3ProposalSink, evaluate_v3_outlet
from plugins.memory.memory_os.wandering_journal import ingest_thought_batch, read_journal


def _store(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="default"))
    store.initialize()
    return store


def _entry(store, *, requested="share", tier="association", roots=None):
    roots = roots or ["crystallized:cry_a", "crystallized:cry_b"]
    packet = build_body_state_packet(
        quiet_state=True,
        source_window={},
        source_cursors={},
        seed_candidates=[{"ref": ref, "kind": "stable_memory", "bounded_text": ref, "epistemic_status": "approved", "salience_reasons": []} for ref in roots],
        edges=[],
        sampler_seed=requested,
        max_text_chars=200,
    )
    write_body_packet_manifest(store, packet)
    return ingest_thought_batch(
        store,
        packet=packet,
        model_entries=[{"tier": tier, "content": "A bounded outward thought", "provenance_refs": roots, "concept_key": "outward", "requested_fate": requested}],
        ttl_days=3,
        max_entry_chars=300,
        max_lineage_hops=2,
    )[0]


class Delivery:
    def __init__(self):
        self.calls = 0

    def deliver(self, entry):
        self.calls += 1
        return {"entry_id": entry["entry_id"], "delivery_succeeded": True, "receipt_id": "sgd_1", "actual_send": True}


def _evaluate(store, *, mode, delivery=None, proposal_sink=None, prior=None, duplicate=False):
    return evaluate_v3_outlet(
        store,
        mode=mode,
        expression_enabled=mode == "active",
        max_share_per_window=2,
        share_window_seconds=3600,
        cooldown_seconds=60,
        min_lineage_diversity=2,
        semantic_duplicate=lambda _content: duplicate,
        delivery=delivery,
        proposal_sink=proposal_sink,
        prior_share_receipts=prior or [],
        now=datetime.now(timezone.utc),
    )


def test_would_share_shadow_has_no_delivery_or_journal_mutation(tmp_path):
    store = _store(tmp_path)
    entry = _entry(store)
    before = read_journal(store)
    delivery = Delivery()
    result = _evaluate(store, mode="shadow", delivery=delivery)
    assert result == {"status": "shadow", "would_share": 1, "would_propose": 0, "blocked": 0}
    assert delivery.calls == 0
    assert read_journal(store) == before
    assert next(item for item in before if item.get("entry_id") == entry["entry_id"])["fate"] == "pending"


def test_active_share_completes_only_after_verified_delivery_receipt(tmp_path):
    store = _store(tmp_path)
    entry = _entry(store)
    delivery = Delivery()
    result = _evaluate(store, mode="active", delivery=delivery)
    assert result["shared"] == 1
    updated = next(item for item in read_journal(store) if item.get("entry_id") == entry["entry_id"])
    assert updated["fate"] == "shared"
    assert updated["fate_ref"] == "sgd_1"


def test_cap_cooldown_semantic_and_lineage_gates_block_before_delivery(tmp_path):
    store = _store(tmp_path)
    _entry(store)
    delivery = Delivery()
    now = datetime.now(timezone.utc)
    result = _evaluate(store, mode="active", delivery=delivery, prior=[{"created_at": now.isoformat(), "actual_send": True}])
    assert result["blocked"] == 1
    assert delivery.calls == 0

    store2 = _store(tmp_path / "two")
    _entry(store2)
    delivery2 = Delivery()
    result = _evaluate(store2, mode="active", delivery=delivery2, duplicate=True)
    assert result["blocked"] == 1
    assert delivery2.calls == 0


def test_proposal_sink_queues_candidate_without_approval_and_closes_fate(tmp_path):
    store = _store(tmp_path)
    entry = _entry(store, requested="propose", tier="claim")
    result = _evaluate(store, mode="active", proposal_sink=V3ProposalSink(store))
    assert result["proposed"] == 1
    updated = next(item for item in read_journal(store) if item.get("entry_id") == entry["entry_id"])
    assert updated["fate"] == "proposed"
    candidates = (store.roots.crystallized_root / "candidates.jsonl").read_text(encoding="utf-8")
    assert entry["content"] in candidates
    assert '"approved_by"' not in candidates
