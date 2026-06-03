import json

from plugins.memory.memory_os.execution_gate import read_execution_gate_records, start_execution_gate_envelope
from plugins.memory.memory_os.host_capability_probe import probe_host_capabilities
from plugins.memory.memory_os.memory_projection import collect_and_project_signals, memory_projection_status
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore


def test_memory_projection_requires_execution_gate_for_automatic_write(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test"))
    store.initialize()
    capabilities = probe_host_capabilities(store.roots, hermes_bin="definitely-missing-hermes-bin")

    report = collect_and_project_signals(
        store,
        host_capabilities=capabilities,
        trigger_type="cognitive_loop",
        execution_envelope_id="manual_cli_explicit",
    )

    assert report["status"] == "blocked"
    assert report["reason"] == "execution_gate_envelope_id_invalid"
    assert memory_projection_status(store.roots)["projection_count"] == 0


def test_memory_projection_appends_records_with_valid_execution_gate(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test"))
    store.initialize()
    capabilities = probe_host_capabilities(store.roots, hermes_bin="definitely-missing-hermes-bin")
    permit = start_execution_gate_envelope(
        store,
        lane_id="memory_projection_collect",
        trigger_surface="cognitive_loop",
        risk_class="governance_projection",
        human_approval_required=False,
        why_no_human_approval="read-only signal projection",
        scope={"source_count": 14, "profile": "memoryos-test"},
        boundary={"actual_send": False, "actual_execute": False, "actual_crystallized_approval": False},
    )

    report = collect_and_project_signals(
        store,
        host_capabilities=capabilities,
        trigger_type="cognitive_loop",
        execution_envelope_id=permit["execution_gate_envelope_id"],
        expected_scope={"source_count": 14, "profile": "memoryos-test"},
    )
    status = memory_projection_status(store.roots)
    execution_records = read_execution_gate_records(store.roots)
    completions = [item for item in execution_records if item.get("stage") == "completion"]
    projection_records = [
        json.loads(line)
        for line in (store.roots.memory_os_root / "system" / "memory_projections.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    encoded = json.dumps(report, ensure_ascii=False)

    assert report["status"] in {"ok", "warning"}
    assert report["written_count"] > 0
    assert status["projection_count"] == report["written_count"]
    assert status["boundary_true_count"] == 0
    assert status["source_scope_missing_count"] == 0
    assert status["duplicate_source_hash_count"] == 0
    assert completions[-1]["execution_status"] == "ok"
    assert completions[-1]["postcheck_boundary_true"] is False
    assert '"raw_body":' not in encoded
    assert "private_body" not in encoded
    assert report["execution_gate_resolution"]["status"] == "valid"
    assert projection_records[0]["structural_write_governance"]["permit_status"] == "valid"
    assert projection_records[0]["structural_write_governance"]["lane_id"] == "memory_projection_collect"


def test_memory_projection_deduplicates_stable_source_hashes(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test"))
    store.initialize()
    capabilities = probe_host_capabilities(store.roots, hermes_bin="definitely-missing-hermes-bin")
    scope = {"source_count": 14, "profile": "memoryos-test"}

    first_permit = start_execution_gate_envelope(
        store,
        lane_id="memory_projection_collect",
        trigger_surface="cognitive_loop",
        risk_class="governance_projection",
        human_approval_required=False,
        why_no_human_approval="read-only signal projection",
        scope=scope,
        boundary={"actual_send": False, "actual_execute": False, "actual_crystallized_approval": False},
    )
    first = collect_and_project_signals(
        store,
        host_capabilities=capabilities,
        trigger_type="cognitive_loop",
        execution_envelope_id=first_permit["execution_gate_envelope_id"],
        expected_scope=scope,
    )
    second_permit = start_execution_gate_envelope(
        store,
        lane_id="memory_projection_collect",
        trigger_surface="cognitive_loop",
        risk_class="governance_projection",
        human_approval_required=False,
        why_no_human_approval="read-only signal projection",
        scope=scope,
        boundary={"actual_send": False, "actual_execute": False, "actual_crystallized_approval": False},
    )
    second = collect_and_project_signals(
        store,
        host_capabilities=capabilities,
        trigger_type="cognitive_loop",
        execution_envelope_id=second_permit["execution_gate_envelope_id"],
        expected_scope=scope,
    )
    status = memory_projection_status(store.roots)

    assert first["written_count"] > 0
    assert second["duplicate_skipped_count"] > 0
    assert status["duplicate_source_hash_count"] == 0
