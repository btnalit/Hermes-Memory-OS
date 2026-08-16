import json

from plugins.memory.memory_os.cli import _hindsight_substrate_monitor
from plugins.memory.memory_os.prefetch import _record_substrate_shadow_recall
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.memory.memory_os.substrates.ledger import (
    SubstrateOperationLedger,
    derive_substrate_monitor_fields,
)


def _store(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    store = MemoryOSStore(roots)
    store.initialize()
    return store


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


def test_provider_errors_reach_shadow_ledger_and_hindsight_substrate_monitor(tmp_path):
    """End-to-end wiring: SubstrateRouter.recall's provider_error_count /
    provider_errors must reach a durable shadow-ledger row (prefetch.py
    ``_record_substrate_shadow_recall``) AND be surfaced by
    ``hermes memory-os status`` (cli.py ``_hindsight_substrate_monitor``).
    Before this test, an all-providers-failed turn left no evidence anywhere
    in this chain.
    """
    store = _store(tmp_path)

    _record_substrate_shadow_recall(
        store=store,
        query="ALL_PROVIDERS_FAILED_QUERY",
        report={
            "schema_version": "memory-os.substrate_recall.v0",
            "query_class": "shadow",
            "selected_provider": "deterministic_fallback",
            "facts": [],
            "authoritative": False,
            "external_authoritative_count": 0,
            "local_first_authority_preserved": True,
            "recall_llm_triggered": False,
            "fallback_triggered": True,
            "provider_error_count": 2,
            "provider_errors": [
                {"provider": "hindsight", "stage": "health", "error_type": "RuntimeError"},
                {"provider": "hindsight", "stage": "recall", "error_type": "TimeoutError"},
            ],
        },
    )

    shadow_path = store.roots.memory_os_root / "system" / "substrate_recall_shadow.jsonl"
    assert shadow_path.exists(), "an all-providers-failed turn must leave evidence even with zero facts"
    shadow_record = json.loads(shadow_path.read_text(encoding="utf-8").splitlines()[-1])
    assert shadow_record["provider_error_count"] == 2
    assert shadow_record["provider_errors"] == [
        {"provider": "hindsight", "stage": "health", "error_type": "RuntimeError"},
        {"provider": "hindsight", "stage": "recall", "error_type": "TimeoutError"},
    ]

    monitor = _hindsight_substrate_monitor(store)

    assert monitor["provider_error_count"] == 2
    assert monitor["provider_errors"] == [
        {"provider": "hindsight", "stage": "health", "error_type": "RuntimeError"},
        {"provider": "hindsight", "stage": "recall", "error_type": "TimeoutError"},
    ]
