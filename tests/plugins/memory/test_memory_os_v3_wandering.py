from __future__ import annotations

from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.memory.memory_os.v3_wandering import run_v3_wandering_cycle
from plugins.memory.memory_os.wandering_journal import read_journal


def _store(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="default"))
    store.initialize()
    return store


def _seed():
    return {
        "ref": "crystallized:cry_a",
        "kind": "stable_memory",
        "bounded_text": "A stable memory",
        "epistemic_status": "approved",
        "salience_reasons": ["co_selected"],
    }


class FakeAdapter:
    capability = True

    def __init__(self, payload):
        self.payload = payload
        self.called = 0

    def infer(self, *, packet, prompt_contract, route_snapshot):
        self.called += 1
        return {
            "status": "ok",
            "structured_output": self.payload,
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


def _run(store, adapter, **overrides):
    values = {
        "adapter": adapter,
        "route_snapshot": {"provider": "openai-codex", "model": "gpt-test"},
        "seed_candidates": [_seed()],
        "edges": [],
        "quiet_gate": {"quiet": True, "reason": "off_peak"},
        "ttl_days": 3,
        "max_entry_chars": 300,
        "max_lineage_hops": 2,
        "model_input_char_budget": 2000,
    }
    values.update(overrides)
    return run_v3_wandering_cycle(store, **values)


def test_missing_ephemeral_capability_fails_closed_before_manifest(tmp_path):
    store = _store(tmp_path)

    class MissingAdapter:
        capability = False

    result = _run(store, MissingAdapter())
    assert result["status"] == "capability_unavailable"
    assert read_journal(store) == []
    assert not (store.roots.memory_os_root / "system" / "v3_body_packet_manifests.jsonl").exists()


def test_empty_entries_is_success_and_removes_manifest(tmp_path):
    store = _store(tmp_path)
    adapter = FakeAdapter({"entries": []})
    result = _run(store, adapter)
    assert result["status"] == "healthy_no_sample"
    assert result["reason"] == "empty_entries"
    assert adapter.called == 1
    assert read_journal(store) == []
    manifest = store.roots.memory_os_root / "system" / "v3_body_packet_manifests.jsonl"
    assert not manifest.exists() or not manifest.read_text(encoding="utf-8").strip()


def test_private_wandering_ingests_valid_entry_without_delivery_or_tools(tmp_path):
    store = _store(tmp_path)
    adapter = FakeAdapter(
        {
            "entries": [
                {
                    "tier": "association",
                    "content": "A quiet association.",
                    "provenance_refs": ["crystallized:cry_a"],
                    "concept_key": "quiet-association",
                    "requested_fate": "hold",
                }
            ]
        }
    )
    result = _run(store, adapter)
    assert result["status"] == "ingested"
    assert result["entry_count"] == 1
    assert result["owner_delivery_attempted"] is False
    assert result["external_action_executed"] is False
    assert len([item for item in read_journal(store) if item.get("record_type") == "thought"]) == 1


def test_schema_or_route_poison_rejects_whole_batch(tmp_path):
    store = _store(tmp_path)
    malformed = FakeAdapter({"entries": [{"tier": "fact"}]})
    result = _run(store, malformed)
    assert result["status"] == "schema_rejected"
    assert read_journal(store) == []

    class DriftAdapter(FakeAdapter):
        def infer(self, *, packet, prompt_contract, route_snapshot):
            result = super().infer(packet=packet, prompt_contract=prompt_contract, route_snapshot=route_snapshot)
            result["actual_model"] = "unexpected"
            return result

    result = _run(store, DriftAdapter({"entries": []}))
    assert result["status"] == "route_drift"
    assert read_journal(store) == []


def test_quiet_gate_skip_never_calls_adapter_or_catches_up(tmp_path):
    store = _store(tmp_path)
    adapter = FakeAdapter({"entries": []})
    result = _run(store, adapter, quiet_gate={"quiet": False, "reason": "foreground_task"})
    assert result == {"status": "skipped", "reason": "foreground_task"}
    assert adapter.called == 0
