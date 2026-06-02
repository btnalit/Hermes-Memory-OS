import json

from plugins.memory.memory_os.host_capability_probe import probe_host_capabilities
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.signal_collectors import collect_signal_sources


def test_collect_signal_sources_outputs_typed_metadata_only_payloads(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    (tmp_path / "memory-os" / "system").mkdir(parents=True)
    (tmp_path / "memory-os" / "system" / "execution_gate_envelopes.jsonl").write_text(
        json.dumps({"stage": "permit", "execution_gate_envelope_id": "xgate_fixture"}) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "gateway.log").write_text("secret token SHOULD_NOT_LEAK\n", encoding="utf-8")
    capabilities = probe_host_capabilities(roots, hermes_bin="definitely-missing-hermes-bin")

    report = collect_signal_sources(
        roots,
        host_capabilities=capabilities,
        trigger_type="manual_cli",
        manual_run_ref="manual:test",
    )
    encoded = json.dumps(report, ensure_ascii=False)

    assert report["schema_version"] == "memory-os.signal_collection.v0"
    assert report["raw_body_included"] is False
    assert report["record_count"] > 0
    assert report["payload_schema_violation_count"] == 0
    assert "SHOULD_NOT_LEAK" not in encoded
    assert "secret token" not in encoded
    by_source = {item["source_key"]: item for item in report["records"]}
    assert by_source["execution_gate_envelopes"]["payload"]["record_count"] == 1
    assert by_source["runtime_logs"]["payload"]["log_file_count"] == 1


def test_collect_signal_sources_blocks_payload_fields_outside_registry(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    capabilities = probe_host_capabilities(roots, hermes_bin="definitely-missing-hermes-bin")
    report = collect_signal_sources(
        roots,
        host_capabilities=capabilities,
        trigger_type="manual_cli",
        manual_run_ref="manual:test",
        collector_overrides={"execution_gate_envelopes": {"status": "ok", "private_body": "nope"}},
    )
    record = next(item for item in report["records"] if item["source_key"] == "execution_gate_envelopes")

    assert record["status"] == "blocked"
    assert record["payload_schema_violation"] is True
    assert report["payload_schema_violation_count"] == 1
