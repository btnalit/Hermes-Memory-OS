from __future__ import annotations

from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.memory.memory_os.v3_body_packet import build_body_state_packet, write_body_packet_manifest
from plugins.memory.memory_os.v3_synthesis import run_v3_synthesis_cycle
from plugins.memory.memory_os.wandering_journal import ingest_thought_batch, read_journal


def _store(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="default"))
    store.initialize()
    return store


def _source(store, concept, root):
    packet = build_body_state_packet(
        quiet_state=True,
        source_window={},
        source_cursors={},
        seed_candidates=[{"ref": root, "kind": "stable_memory", "bounded_text": concept, "epistemic_status": "approved", "salience_reasons": []}],
        edges=[],
        sampler_seed=concept,
        max_text_chars=200,
    )
    write_body_packet_manifest(store, packet)
    return ingest_thought_batch(
        store,
        packet=packet,
        model_entries=[{"tier": "association", "content": concept, "provenance_refs": [root], "concept_key": concept, "requested_fate": "hold"}],
        ttl_days=3,
        max_entry_chars=300,
        max_lineage_hops=2,
    )[0]


class Adapter:
    capability = True

    def __init__(self, entries):
        self.entries = entries
        self.called = 0

    def infer(self, *, packet, prompt_contract, route_snapshot):
        self.called += 1
        return {
            "status": "ok",
            "structured_output": {"entries": self.entries},
            "requested_provider": route_snapshot["provider"],
            "requested_model": route_snapshot["model"],
            "actual_provider": route_snapshot["provider"],
            "actual_model": route_snapshot["model"],
            "fallback_used": False,
            "model_input_transmitted": True,
            "owner_delivery_attempted": False,
            "external_action_executed": False,
            "tools_enabled": False,
        }


def _route():
    return {"provider": "test", "model": "test", "allowed_routes": [{"provider": "test", "model": "test"}]}


def test_synthesis_abstention_is_success_without_new_thought(tmp_path):
    store = _store(tmp_path)
    _source(store, "alpha", "crystallized:cry_a")
    _source(store, "beta", "crystallized:cry_b")
    before = len(read_journal(store))
    result = run_v3_synthesis_cycle(
        store,
        adapter=Adapter([]),
        route_snapshot=_route(),
        min_inputs=2,
        min_provenance_diversity=2,
        min_semantic_distance=0.4,
        semantic_distance=lambda _content, _roots: 1.0,
        ttl_days=3,
        max_entry_chars=300,
        max_lineage_hops=2,
    )
    assert result["status"] == "ok_empty"
    assert len(read_journal(store)) == before


def test_synthesis_resolves_journal_refs_to_canonical_roots_and_one_hop(tmp_path):
    store = _store(tmp_path)
    a = _source(store, "alpha", "crystallized:cry_a")
    b = _source(store, "beta", "crystallized:cry_b")
    refs = ["journal:" + a["entry_id"], "journal:" + b["entry_id"]]
    adapter = Adapter([
        {
            "tier": "claim",
            "content": "A reusable synthesis",
            "provenance_refs": refs,
            "concept_key": "reusable-synthesis",
            "requested_fate": "propose",
            "reusable_insight": True,
        }
    ])
    result = run_v3_synthesis_cycle(
        store,
        adapter=adapter,
        route_snapshot=_route(),
        min_inputs=2,
        min_provenance_diversity=2,
        min_semantic_distance=0.4,
        semantic_distance=lambda _content, roots: 0.8 if len(roots) == 2 else 0.0,
        ttl_days=3,
        max_entry_chars=300,
        max_lineage_hops=2,
    )
    assert result["status"] == "ingested"
    thought = next(item for item in read_journal(store) if item.get("concept_key") == "reusable-synthesis")
    assert thought["lineage_hop"] == 1
    assert thought["lineage_root_refs"] == ["crystallized:cry_a", "crystallized:cry_b"]
    assert thought["requested_fate"] == "propose"


def test_admission_and_semantic_gates_fail_closed(tmp_path):
    store = _store(tmp_path)
    a = _source(store, "alpha", "crystallized:cry_a")
    adapter = Adapter([])
    result = run_v3_synthesis_cycle(
        store,
        adapter=adapter,
        route_snapshot=_route(),
        min_inputs=2,
        min_provenance_diversity=2,
        min_semantic_distance=0.4,
        semantic_distance=lambda _content, _roots: 0.0,
        ttl_days=3,
        max_entry_chars=300,
        max_lineage_hops=2,
    )
    assert result["status"] == "admission_rejected"
    assert adapter.called == 0

    second = _source(store, "beta", "crystallized:cry_b")
    refs = ["journal:" + a["entry_id"], "journal:" + second["entry_id"]]
    adapter = Adapter([{"tier": "claim", "content": "Too close", "provenance_refs": refs, "concept_key": "close", "requested_fate": "propose", "reusable_insight": True}])
    result = run_v3_synthesis_cycle(
        store,
        adapter=adapter,
        route_snapshot=_route(),
        min_inputs=2,
        min_provenance_diversity=2,
        min_semantic_distance=0.4,
        semantic_distance=lambda _content, _roots: 0.1,
        ttl_days=3,
        max_entry_chars=300,
        max_lineage_hops=2,
    )
    assert result["status"] == "semantic_gate_rejected"
    assert not any(item.get("concept_key") == "close" for item in read_journal(store))
