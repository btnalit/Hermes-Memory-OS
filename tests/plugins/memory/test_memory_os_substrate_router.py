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


class RaisingHealthProvider:
    """A substrate provider whose health() raises -- e.g. a live probe that
    throws instead of reporting degraded status. Used to prove DEFECT 2's
    fix: this must never abort the whole SubstrateRouter.recall() call."""

    def __init__(self, name="broken"):
        self.name = name

    def health(self):
        raise RuntimeError("health check exploded")

    def recall(self, query, *, consumer):
        raise AssertionError("recall() must not be called when health() raises")


class RaisingRecallProvider:
    """A substrate provider whose health() reports healthy but recall()
    itself raises -- e.g. a provider whose backend connection drops between
    the health check and the recall call. This swallow predates the
    health()-placement fix; it must be counted the same way."""

    def __init__(self, name="flaky"):
        self.name = name

    def health(self):
        return ProviderHealth(provider=self.name, status="ok", capabilities=["recall"])

    def recall(self, query, *, consumer):
        raise ValueError("recall backend exploded")


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
    """Counterfactual: an external provider (not local_artifact) that
    self-reports authority_class="local_canonical" must not merely be
    FLAGGED -- it must be structurally excluded from the ranked/selectable
    output. Before the fix, `_rank_fact` granted this fact tier-1 priority
    based solely on its own claimed authority_class (no provider-identity
    check), so with no genuine local_artifact fact in this call it became
    `facts[0]` and `selected_provider == "hindsight"` -- i.e. the spoofed
    claim WON despite the detection fields correctly flipping. Reverting
    the router.py fix makes the two new assertions below fail while the
    three original detection assertions keep passing -- proving the old
    test never actually caught the vulnerability it targeted.
    """
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
    # The spoofed fact must never reach selectable/returned content.
    assert result["facts"] == []
    assert result["selected_provider"] != "hindsight"
    assert result["selected_provider"] == "deterministic_fallback"


def test_spoofed_local_authority_claim_excluded_even_alongside_genuine_local_fact():
    """A second counterfactual with a genuine local_artifact fact ALSO
    present: the spoofed external claim must still be dropped from
    `facts` (not merely outranked), while the real local fact still wins
    selection. This guards against a fix that only reorders tiers instead
    of structurally excluding the spoofed entry."""
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
    bad_external_fact = GroundingFact(
        provider="hindsight",
        capability="recall",
        body_summary="bad authority claim",
        confidence=0.99,
        provenance="hindsight_recall",
        source_event_refs=["h1"],
        substrate_snapshot_id="hindsight:bank:v1",
        advisory_only=False,
        authority_class="owner_approved",
    )
    router = SubstrateRouter(
        providers=[
            FakeProvider("hindsight", facts=[bad_external_fact]),
            FakeProvider("local_artifact", facts=[local_fact]),
        ],
        mode="active",
    )

    result = router.recall("memory", consumer="grounded_expression")

    assert len(result["facts"]) == 1
    assert result["facts"][0]["provider"] == "local_artifact"
    assert result["selected_provider"] == "local_artifact"
    assert result["external_authoritative_count"] == 1
    assert result["local_first_authority_preserved"] is False


def test_provider_health_raise_before_local_artifact_does_not_abort_recall():
    """Counterfactual: DEFECT 2. Before the fix, provider.health() was
    called OUTSIDE any try/except in the per-provider loop. A raising
    health() therefore propagated straight out of SubstrateRouter.recall(),
    aborting the whole call before LocalArtifactProvider -- the
    architecture's always-primary authority -- ever got its turn.
    RaisingHealthProvider is listed FIRST here to reproduce that exact
    failure shape. Reverting the router.py fix makes this test raise
    RuntimeError instead of returning a result.
    """
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
    router = SubstrateRouter(
        providers=[RaisingHealthProvider(), FakeProvider("local_artifact", facts=[local_fact])],
        mode="active",
    )

    result = router.recall("memory", consumer="grounded_expression")

    assert result["facts"][0]["provider"] == "local_artifact"
    assert result["selected_provider"] == "local_artifact"
    assert result["fallback_triggered"] is False


def test_provider_health_raise_is_counted_as_a_provider_error():
    """Counterfactual: a provider whose health() raises must not be
    silently dropped -- it must be distinguishable in the report from a
    provider that legitimately reports status != "ok". Before this fix,
    moving health() inside the per-provider try/except (to stop it aborting
    the whole loop) widened the existing swallow: the raise vanished with
    no error record anywhere. Recall must still return LocalArtifact's
    facts, AND the report must carry provider_error_count == 1 with
    stage == "health" and the raising provider's name.
    """
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
    router = SubstrateRouter(
        providers=[RaisingHealthProvider(name="broken"), FakeProvider("local_artifact", facts=[local_fact])],
        mode="active",
    )

    result = router.recall("memory", consumer="grounded_expression")

    assert result["facts"][0]["provider"] == "local_artifact"
    assert result["provider_error_count"] == 1
    assert len(result["provider_errors"]) == 1
    error = result["provider_errors"][0]
    assert error["provider"] == "broken"
    assert error["stage"] == "health"
    assert error["error_type"] == "RuntimeError"


def test_provider_recall_raise_is_counted_as_a_provider_error():
    """Same defect shape as the health() swallow, but for recall() itself --
    this swallow predates the health()-placement branch entirely. A
    provider that reports healthy but whose recall() raises must be
    counted with stage == "recall", not silently dropped.
    """
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
    router = SubstrateRouter(
        providers=[RaisingRecallProvider(name="flaky"), FakeProvider("local_artifact", facts=[local_fact])],
        mode="active",
    )

    result = router.recall("memory", consumer="grounded_expression")

    assert result["facts"][0]["provider"] == "local_artifact"
    assert result["provider_error_count"] == 1
    assert len(result["provider_errors"]) == 1
    error = result["provider_errors"][0]
    assert error["provider"] == "flaky"
    assert error["stage"] == "recall"
    assert error["error_type"] == "ValueError"


def test_disabled_provider_status_is_not_counted_as_a_provider_error():
    """The entire point of provider_error_count: a provider that legitimately
    reports status="disabled" (no exception, a clean health report) must
    remain distinguishable from one whose health()/recall() raised. This is
    the test that proves the two cases no longer collapse into the same
    silent-skip shape.
    """
    router = SubstrateRouter(providers=[FakeProvider("hindsight", status="disabled")])

    result = router.recall("memory", consumer="grounded_expression")

    assert result["fallback_triggered"] is True
    assert result["provider_error_count"] == 0
    assert result["provider_errors"] == []


def test_provider_health_raise_after_facts_collected_does_not_discard_them():
    """A second ordering: the raising provider comes AFTER a provider that
    already contributed facts. Before the fix, the uncaught raise happened
    mid-loop, so the function never reached its `return` -- facts already
    appended into raw_facts from earlier providers were lost along with it,
    not merely left out of this iteration.
    """
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
    router = SubstrateRouter(
        providers=[FakeProvider("local_artifact", facts=[local_fact]), RaisingHealthProvider()],
        mode="active",
    )

    result = router.recall("memory", consumer="grounded_expression")

    assert result["facts"][0]["provider"] == "local_artifact"
    assert result["selected_provider"] == "local_artifact"
    assert result["fallback_triggered"] is False
