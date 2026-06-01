from plugins.memory.memory_os.substrates.base import GroundingFact, ProviderHealth
from plugins.memory.memory_os.substrates.router import SubstrateRouter


class FakeProvider:
    def __init__(self, name, facts=None, status="ok"):
        self.name = name
        self.facts = facts or []
        self.status = status

    def health(self):
        return ProviderHealth(provider=self.name, status=self.status, capabilities=["recall"])

    def recall(self, query, *, consumer):
        return list(self.facts)


def test_router_returns_fallback_when_provider_disabled():
    router = SubstrateRouter(providers=[FakeProvider("hindsight", status="disabled")])

    result = router.recall("memory", consumer="grounded_expression")

    assert result["facts"] == []
    assert result["fallback_triggered"] is True
    assert result["selected_provider"] == "deterministic_fallback"


def test_router_records_shadow_hindsight_without_making_it_authoritative():
    router = SubstrateRouter(
        providers=[
            FakeProvider(
                "hindsight",
                facts=[
                    GroundingFact(
                        provider="hindsight",
                        capability="recall",
                        body_summary="shadow",
                        confidence=0.6,
                        provenance="hindsight_recall",
                        source_event_refs=["h1"],
                        substrate_snapshot_id="hindsight:bank:v1",
                        advisory_only=True,
                        authority_class="derived_projection",
                    )
                ],
            )
        ],
        mode="shadow",
    )

    result = router.recall("memory", consumer="low_clue_recall")

    assert result["facts"][0]["provider"] == "hindsight"
    assert result["facts"][0]["body_summary"] == "shadow"
    assert result["authoritative"] is False
    assert result["recall_llm_triggered"] is False
    assert result["local_first_authority_preserved"] is True


def test_active_hindsight_does_not_outrank_local_canonical_fact():
    local_fact = GroundingFact(
        provider="local_artifact",
        capability="recall",
        body_summary="local canonical",
        confidence=1.0,
        provenance="crystallized",
        source_event_refs=["cmem_1"],
        substrate_snapshot_id="local:canonical:v4",
        advisory_only=False,
        authority_class="local_canonical",
    )
    hindsight_fact = GroundingFact(
        provider="hindsight",
        capability="recall",
        body_summary="external candidate",
        confidence=0.99,
        provenance="hindsight_recall",
        source_event_refs=["h1"],
        substrate_snapshot_id="hindsight:bank:v1",
        advisory_only=True,
        authority_class="derived_projection",
    )
    router = SubstrateRouter(
        providers=[
            FakeProvider("hindsight", facts=[hindsight_fact]),
            FakeProvider("local_artifact", facts=[local_fact]),
        ],
        mode="active",
    )

    result = router.recall("memory", consumer="grounded_expression")

    assert result["facts"][0]["provider"] == "local_artifact"
    assert result["facts"][0]["authority_class"] == "local_canonical"
    assert result["facts"][1]["provider"] == "hindsight"
    assert result["facts"][1]["advisory_only"] is True
    assert result["authoritative"] is True
    assert result["external_authoritative_count"] == 0


def test_external_provider_claiming_local_authority_is_a_guard_violation():
    bad_external_fact = GroundingFact(
        provider="hindsight",
        capability="recall",
        body_summary="bad authority claim",
        confidence=0.99,
        provenance="hindsight_recall",
        source_event_refs=["h1"],
        substrate_snapshot_id="hindsight:bank:v1",
        advisory_only=False,
        authority_class="local_canonical",
    )
    router = SubstrateRouter(providers=[FakeProvider("hindsight", facts=[bad_external_fact])], mode="active")

    result = router.recall("memory", consumer="grounded_expression")

    assert result["authoritative"] is False
    assert result["external_authoritative_count"] == 1
    assert result["local_first_authority_preserved"] is False
