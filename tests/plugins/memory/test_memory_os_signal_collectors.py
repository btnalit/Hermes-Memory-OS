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


def test_collect_signal_sources_projects_external_hermes_cron_failures_metadata_only(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    cron_root = tmp_path / "cron"
    output_root = cron_root / "output" / "job-ext"
    output_root.mkdir(parents=True)
    (cron_root / "jobs.json").write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "id": "job-memory-os",
                        "name": "memory-os-owner-review-digest",
                        "script": "memory_os_cron_owner_review_digest.py",
                        "deliver": True,
                    },
                    {
                        "id": "job-ext",
                        "name": "info-reflect-ai",
                        "script": "/root/.hermes/scripts/info-reflect-ai.sh",
                        "deliver": True,
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (output_root / "2026-06-03_11-02-35.md").write_text(
        "\n".join(
            [
                "# Cron Job: info-reflect-ai",
                "**Job ID:** job-ext",
                "**Run Time:** 2026-06-03 11:02:35",
                "**Status:** script failed",
                "",
                "Script timed out after 120s: /root/.hermes/scripts/info-reflect-ai.sh",
                "secret token SHOULD_NOT_LEAK",
            ]
        ),
        encoding="utf-8",
    )
    capabilities = probe_host_capabilities(roots, hermes_bin="definitely-missing-hermes-bin")

    report = collect_signal_sources(
        roots,
        host_capabilities=capabilities,
        trigger_type="manual_cli",
        manual_run_ref="manual:test",
    )
    by_source = {item["source_key"]: item for item in report["records"]}
    payload = by_source["hermes_cron_jobs"]["payload"]
    encoded = json.dumps(payload, ensure_ascii=False)

    assert by_source["hermes_cron_jobs"]["payload_schema_violation"] is False
    assert payload["status"] == "warning"
    assert payload["external_failure_count"] == 1
    assert payload["timeout_failure_count"] == 1
    assert payload["latest_failure_job"] == "info-reflect-ai"
    assert "120s" in payload["latest_failure_reason"]
    assert payload["latest_failure_deliver"] is True
    assert "SHOULD_NOT_LEAK" not in encoded
    assert "secret token" not in encoded
