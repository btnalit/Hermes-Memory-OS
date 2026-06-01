import pytest

from plugins.memory.memory_os.adapters.hindsight import HindsightExportRefused
from plugins.memory.memory_os.substrates.hindsight import (
    GovernedHindsightConfig,
    GovernedHindsightSubstrate,
)
from plugins.modules.governance.live_guard import LiveGuardRegistry


class FakeClient:
    def __init__(self):
        self.retained = []
        self.recalled = []
        self.reflected = []
        self.invalidated = []

    def retain(self, payload):
        self.retained.append(payload)
        return {"ok": True, "id": "h1"}

    def recall(self, *, bank_id, query, budget, max_tokens):
        self.recalled.append(
            {"bank_id": bank_id, "query": query, "budget": budget, "max_tokens": max_tokens}
        )
        return {"items": [{"text": "grounded memory", "score": 0.7, "source": "hindsight"}]}

    def reflect(self, *, bank_id, query, budget):
        self.reflected.append({"bank_id": bank_id, "query": query, "budget": budget})
        return {"summary": "synthesized belief", "grounding": ["h1"]}

    def invalidate(self, payload):
        self.invalidated.append(payload)
        return {"ok": True}


class FakeLiveGuard:
    def __init__(self, enabled):
        self.enabled = enabled

    def kill_switch_enabled(self, name):
        return self.enabled


def test_disabled_substrate_is_unavailable():
    substrate = GovernedHindsightSubstrate(
        GovernedHindsightConfig(enabled=False),
        client=FakeClient(),
    )

    assert substrate.health().status == "disabled"
    assert substrate.recall("memory", consumer="test") == []


def test_global_kill_switch_forces_hindsight_disabled():
    substrate = GovernedHindsightSubstrate(
        GovernedHindsightConfig(enabled=True, bank_id="bank", recall_mode="shadow"),
        client=FakeClient(),
        live_guard=FakeLiveGuard(True),
    )

    health = substrate.health()

    assert health.status == "disabled"
    assert health.reason == "kill_switch_enabled"
    assert health.kill_switch_forced_disabled is True
    assert substrate.recall("memory", consumer="test") == []


def test_live_guard_registry_without_config_does_not_false_positive():
    substrate = GovernedHindsightSubstrate(
        GovernedHindsightConfig(enabled=True, bank_id="bank", recall_mode="shadow"),
        client=FakeClient(),
        live_guard=LiveGuardRegistry(),
    )

    health = substrate.health()

    assert health.status == "ok"
    assert health.kill_switch_forced_disabled is False


def test_config_dict_kill_switch_forces_hindsight_disabled():
    substrate = GovernedHindsightSubstrate(
        GovernedHindsightConfig(enabled=True, bank_id="bank", recall_mode="shadow"),
        client=FakeClient(),
        live_guard={"l4": {"kill_switch_enabled": True}},
    )

    health = substrate.health()

    assert health.status == "disabled"
    assert health.reason == "kill_switch_enabled"


def test_retain_rejects_raw_source_class():
    substrate = GovernedHindsightSubstrate(
        GovernedHindsightConfig(enabled=True, bank_id="bank", retain_enabled=True),
        client=FakeClient(),
    )

    with pytest.raises(HindsightExportRefused, match="raw"):
        substrate.retain_payload(
            {
                "schema_version": "memory-os.hindsight_export.v0",
                "record_id": "evt_1",
                "text": "raw turn",
                "source_event_ids": ["evt_1"],
                "metadata": {"source_class": "raw_turn"},
            }
        )


def test_retain_accepts_approved_summary_payload():
    client = FakeClient()
    substrate = GovernedHindsightSubstrate(
        GovernedHindsightConfig(enabled=True, bank_id="bank", retain_enabled=True),
        client=client,
    )

    result = substrate.retain_payload(
        {
            "schema_version": "memory-os.hindsight_export.v0",
            "record_id": "cmem_1",
            "text": "approved summary",
            "source_event_ids": ["evt_1"],
            "metadata": {"source_class": "crystallized"},
        }
    )

    assert result["ok"] is True
    assert client.retained[0]["metadata"]["source_class"] == "crystallized"
    assert client.retained[0]["metadata"]["substrate_snapshot_id"].startswith("hindsight:bank:")


def test_recall_shadow_returns_grounding_facts_without_hot_path_llm():
    substrate = GovernedHindsightSubstrate(
        GovernedHindsightConfig(enabled=True, bank_id="bank", recall_mode="shadow"),
        client=FakeClient(),
    )

    facts = substrate.recall("continue yesterday", consumer="low_clue_recall")

    assert facts[0].provider == "hindsight"
    assert facts[0].body_summary == "grounded memory"
    assert facts[0].confidence == 0.7
    assert facts[0].authority_class == "derived_projection"
    assert facts[0].advisory_only is True
    assert facts[0].recall_llm_triggered is False
    assert facts[0].substrate_snapshot_id.startswith("hindsight:bank:")


def test_reflect_is_disabled_until_explicitly_enabled():
    client = FakeClient()
    substrate = GovernedHindsightSubstrate(
        GovernedHindsightConfig(enabled=True, bank_id="bank", reflect_enabled=False),
        client=client,
    )

    assert substrate.reflect("what do I believe?", consumer="owner")["status"] == "disabled"
    assert client.reflected == []


def test_invalidate_projection_is_invalidate_not_delete():
    client = FakeClient()
    substrate = GovernedHindsightSubstrate(
        GovernedHindsightConfig(enabled=True, bank_id="bank"),
        client=client,
    )

    result = substrate.invalidate_projection(
        source_record_ref="cmem_1",
        source_version="4",
        reason="owner_revoked",
    )

    assert result["ok"] is True
    assert client.invalidated[0]["delete_policy"] == "invalidate_not_delete"
    assert client.invalidated[0]["source_record_ref"] == "cmem_1"
