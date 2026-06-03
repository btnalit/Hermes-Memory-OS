import json

import pytest

from plugins.memory.memory_os.execution_gate import execution_gate_scope_hash, start_execution_gate_envelope
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.memory.memory_os.structural_write_gate import append_governed_jsonl


def _read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_append_governed_jsonl_rejects_automatic_write_without_valid_execution_gate(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test"))
    store.initialize()
    path = store.roots.memory_os_root / "system" / "governed.jsonl"

    with pytest.raises(ValueError, match="execution_gate_envelope_id_invalid"):
        append_governed_jsonl(
            store,
            path,
            {"value": "blocked"},
            write_owner="automatic",
            lane_id="memory_projection_collect",
            risk_class="governance_projection",
            execution_gate_envelope_id="manual_cli_explicit",
            scope_hash=execution_gate_scope_hash({"source_count": 1}),
        )

    assert not path.exists()


def test_append_governed_jsonl_writes_governance_metadata_for_valid_automatic_write(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test"))
    store.initialize()
    scope = {"source_count": 1, "profile": "memoryos-test"}
    permit = start_execution_gate_envelope(
        store,
        lane_id="memory_projection_collect",
        trigger_surface="cognitive_loop",
        risk_class="governance_projection",
        human_approval_required=False,
        why_no_human_approval="read-only projection",
        scope=scope,
        boundary={"actual_send": False, "actual_execute": False},
    )
    path = store.roots.memory_os_root / "system" / "governed.jsonl"

    written_path = append_governed_jsonl(
        store,
        path,
        {"value": "ok"},
        write_owner="automatic",
        lane_id="memory_projection_collect",
        risk_class="governance_projection",
        execution_gate_envelope_id=permit["execution_gate_envelope_id"],
        scope_hash=execution_gate_scope_hash(scope),
    )

    records = _read_jsonl(path)
    governance = records[0]["structural_write_governance"]

    assert written_path == path
    assert records[0]["value"] == "ok"
    assert governance["write_owner"] == "automatic"
    assert governance["lane_id"] == "memory_projection_collect"
    assert governance["risk_class"] == "governance_projection"
    assert governance["execution_gate_envelope_id"] == permit["execution_gate_envelope_id"]
    assert governance["permit_status"] == "valid"
    assert governance["scope_hash"] == execution_gate_scope_hash(scope)
    assert governance["boundary_true"] is False
