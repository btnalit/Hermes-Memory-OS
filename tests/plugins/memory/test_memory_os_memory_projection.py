import json

from plugins.memory.memory_os.execution_gate import read_execution_gate_records, start_execution_gate_envelope
from plugins.memory.memory_os.host_capability_probe import probe_host_capabilities
from plugins.memory.memory_os.memory_projection import (
    compact_memory_projection_records,
    collect_and_project_signals,
    memory_projection_records_path,
    memory_projection_retention_status,
    memory_projection_status,
)
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
    assert status["registered_source_count"] == 14
    assert status["unique_source_count"] == 14
    assert status["registered_source_missing_count"] == 0
    assert set(status["projected_source_keys"]) >= {"execution_gate_envelopes", "hermes_cron_jobs", "runtime_logs"}
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


def test_memory_projection_compaction_archives_short_lived_status_records(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test"))
    store.initialize()
    path = memory_projection_records_path(store.roots)
    path.parent.mkdir(parents=True, exist_ok=True)
    records = [
        _projection_record("old-a", "gateway_status", "hash-old-a", retention_class="short_lived_status"),
        _projection_record("old-b", "gateway_status", "hash-old-b", retention_class="short_lived_status"),
        _projection_record("new", "gateway_status", "hash-new", retention_class="short_lived_status"),
        _projection_record("gov", "owner_actions", "hash-gov", retention_class="governance_evidence"),
    ]
    path.write_text("\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n", encoding="utf-8")

    report = compact_memory_projection_records(store.roots, keep_latest_status_per_source=1, apply=True)
    remaining = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    retention = memory_projection_retention_status(store.roots)

    assert report["status"] == "ok"
    assert report["input_count"] == 4
    assert report["output_count"] == 2
    assert report["archived_count"] == 2
    assert {record["projection_id"] for record in remaining} == {"new", "gov"}
    assert report["archive_path"]
    assert (store.roots.memory_os_root / report["archive_path"]).is_file()
    assert retention["latest_archived_count"] == 2
    assert retention["latest_boundary_true_archived_count"] == 0


def test_memory_projection_compaction_preserves_boundary_and_safety_records(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test"))
    store.initialize()
    path = memory_projection_records_path(store.roots)
    path.parent.mkdir(parents=True, exist_ok=True)
    records = [
        _projection_record("old", "gateway_status", "hash-old", retention_class="short_lived_status"),
        _projection_record("new", "gateway_status", "hash-new", retention_class="short_lived_status"),
        _projection_record(
            "boundary",
            "gateway_status",
            "hash-boundary",
            retention_class="short_lived_status",
            boundary={"actual_send": True},
        ),
        _projection_record("raw", "gateway_status", "hash-raw", retention_class="short_lived_status", raw_body_included=True),
    ]
    path.write_text("\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n", encoding="utf-8")

    report = compact_memory_projection_records(store.roots, keep_latest_status_per_source=1, apply=True)
    remaining = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert report["archived_count"] == 1
    assert report["boundary_true_preserved_count"] == 1
    assert report["raw_body_included_preserved_count"] == 1
    assert {record["projection_id"] for record in remaining} == {"new", "boundary", "raw"}


def _projection_record(
    projection_id: str,
    source_key: str,
    source_hash: str,
    *,
    retention_class: str,
    boundary: dict | None = None,
    raw_body_included: bool = False,
) -> dict:
    return {
        "schema_version": "memory-os.memory_projection_record.v0",
        "projection_id": projection_id,
        "dedup_key": f"dedup-{projection_id}",
        "created_at": f"2026-06-03T00:0{len(projection_id) % 9}:00Z",
        "host_id": "test-host",
        "hermes_home_ref": "test-home",
        "profile_id": "memoryos-test",
        "source_scope_ref": "scope-test",
        "source_key": source_key,
        "source_hash": source_hash,
        "projection_type": "operational_signal",
        "retention_class": retention_class,
        "payload": {"status": "ok"},
        "raw_body_included": raw_body_included,
        "boundary": boundary or {"actual_send": False},
    }
