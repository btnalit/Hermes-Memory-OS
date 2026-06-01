from plugins.memory.memory_os.substrates.projection import (
    ProjectionLedger,
    derive_projection_coherence,
)


def test_projection_retract_marks_derived_fact_invalid(tmp_path):
    ledger = ProjectionLedger(tmp_path / "projection_ledger.jsonl")
    ledger.record_retain(
        provider="hindsight",
        source_record_ref="cmem_1",
        source_version="4",
        substrate_record_id="h1",
        substrate_snapshot_id="hindsight:bank:v4",
    )

    ledger.record_invalidate(
        provider="hindsight",
        source_record_ref="cmem_1",
        source_version="4",
        reason="crystallized_demoted",
        substrate_snapshot_id="hindsight:bank:v5",
    )

    coherence = derive_projection_coherence(ledger.read_all(), provider="hindsight")

    assert coherence["active_projection_count"] == 0
    assert coherence["retract_count"] == 1
    assert coherence["projection_stale_count"] == 0


def test_missing_retract_is_reported_as_stale_projection(tmp_path):
    ledger = ProjectionLedger(tmp_path / "projection_ledger.jsonl")
    ledger.record_retain(
        provider="hindsight",
        source_record_ref="cmem_2",
        source_version="1",
        substrate_record_id="h2",
        substrate_snapshot_id="hindsight:bank:v1",
    )

    coherence = derive_projection_coherence(
        ledger.read_all(),
        provider="hindsight",
        demoted_source_refs={"cmem_2"},
    )

    assert coherence["projection_stale_count"] == 1
    assert coherence["stale_source_refs"] == ["cmem_2"]


def test_owner_revoke_path_records_projection_invalidation(tmp_path):
    from plugins.modules.governance.crystallized_revalidator import (
        invalidate_hindsight_projection_for_canonical_change,
    )

    invalidate_hindsight_projection_for_canonical_change(
        projection_ledger_path=tmp_path / "projection_ledger.jsonl",
        record_id="cmem_3",
        record_version="2",
        reason="owner_revoked",
        substrate_snapshot_id="hindsight:bank:v3",
    )

    records = ProjectionLedger(tmp_path / "projection_ledger.jsonl").read_all()

    assert records[-1]["operation"] == "invalidate"
    assert records[-1]["reason"] == "owner_revoked"
    assert records[-1]["source_record_ref"] == "cmem_3"
