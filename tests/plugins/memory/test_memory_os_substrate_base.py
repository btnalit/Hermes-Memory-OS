from plugins.memory.memory_os.substrates.base import (
    GroundingFact,
    ProviderHealth,
    SubstrateSnapshot,
)


def test_grounding_fact_defaults_to_advisory_and_snapshot_bound():
    fact = GroundingFact(
        provider="hindsight",
        capability="recall",
        body_summary="approved fact",
        confidence=0.6,
        provenance="hindsight_recall",
        source_event_refs=["cmem_1"],
        substrate_snapshot_id="hindsight:bank:v7",
    )

    assert fact.advisory_only is True
    assert fact.authority_class == "derived_projection"
    assert fact.recall_llm_triggered is False
    assert fact.to_monitor_dict()["substrate_snapshot_id"] == "hindsight:bank:v7"


def test_local_fact_can_be_canonical_authority():
    fact = GroundingFact(
        provider="local_artifact",
        capability="recall",
        body_summary="owner approved local fact",
        confidence=0.95,
        provenance="crystallized",
        source_event_refs=["cmem_2"],
        substrate_snapshot_id="local:canonical:v12",
        advisory_only=False,
        authority_class="local_canonical",
    )

    assert fact.authority_class == "local_canonical"
    assert fact.advisory_only is False


def test_provider_health_reports_kill_switch_disabled():
    health = ProviderHealth(
        provider="hindsight",
        status="disabled",
        capabilities=[],
        reason="kill_switch_enabled",
        kill_switch_forced_disabled=True,
    )

    assert health.to_monitor_dict()["kill_switch_forced_disabled"] is True


def test_snapshot_id_is_stable_for_same_inputs():
    left = SubstrateSnapshot(provider="hindsight", source_ref="bank", version="7")
    right = SubstrateSnapshot(provider="hindsight", source_ref="bank", version="7")

    assert left.snapshot_id == right.snapshot_id
    assert left.snapshot_id.startswith("hindsight:")
