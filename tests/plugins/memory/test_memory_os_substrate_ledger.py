from plugins.memory.memory_os.substrates.ledger import (
    SubstrateOperationLedger,
    derive_substrate_monitor_fields,
)


def test_monitor_fields_are_derived_from_operation_records(tmp_path):
    ledger = SubstrateOperationLedger(tmp_path / "substrate_operations.jsonl")
    ledger.append(
        {
            "provider": "hindsight",
            "operation": "retain",
            "source_class": "crystallized",
            "raw_body_included": False,
            "substrate_snapshot_id": "hindsight:bank:v1",
        }
    )
    ledger.append(
        {
            "provider": "hindsight",
            "operation": "recall",
            "recall_llm_triggered": False,
            "substrate_snapshot_id": "hindsight:bank:v1",
        }
    )
    ledger.append(
        {
            "provider": "hindsight",
            "operation": "reflect",
            "phase": "async",
            "substrate_snapshot_id": "hindsight:bank:v1",
        }
    )

    fields = derive_substrate_monitor_fields(ledger.read_all(), provider="hindsight")

    assert fields["retain_count"] == 1
    assert fields["raw_retained_count"] == 0
    assert fields["no_raw_retained"] is True
    assert fields["recall_llm_triggered"] is False
    assert fields["reflect_hot_path_count"] == 0
    assert fields["reflect_off_hot_path"] is True


def test_monitor_fields_fail_closed_when_raw_retain_is_recorded(tmp_path):
    ledger = SubstrateOperationLedger(tmp_path / "substrate_operations.jsonl")
    ledger.append(
        {
            "provider": "hindsight",
            "operation": "retain",
            "source_class": "raw_turn",
            "raw_body_included": True,
            "substrate_snapshot_id": "hindsight:bank:v2",
        }
    )

    fields = derive_substrate_monitor_fields(ledger.read_all(), provider="hindsight")

    assert fields["raw_retained_count"] == 1
    assert fields["no_raw_retained"] is False
