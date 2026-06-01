from plugins.memory.memory_os.substrates.local_artifact import LocalArtifactProvider


class FakeStore:
    def __init__(self):
        self.records = [
            {
                "record_id": "cmem_1",
                "summary": "Apollo budget is owner approved",
                "source_event_refs": ["evt_1"],
                "state": "crystallized",
                "owner_approved": True,
                "version": "4",
            }
        ]

    def iter_crystallized_records(self):
        return iter(self.records)


def test_local_artifact_provider_returns_canonical_fact():
    provider = LocalArtifactProvider(FakeStore())

    facts = provider.recall("Apollo budget", consumer="grounded_expression")

    assert facts[0].provider == "local_artifact"
    assert facts[0].authority_class == "local_canonical"
    assert facts[0].advisory_only is False
    assert facts[0].confidence == 1.0
