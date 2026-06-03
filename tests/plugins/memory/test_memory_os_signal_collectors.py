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
    (tmp_path / "memory-os" / "system" / "substrate_operations.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"provider": "hindsight", "operation": "retain", "source_class": "crystallized", "created_at": "2026-06-03T01:00:00Z"}),
                json.dumps({"provider": "hindsight", "operation": "recall", "recall_llm_triggered": False, "created_at": "2026-06-03T01:01:00Z"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "memory-os" / "system" / "projection_ledger.jsonl").write_text(
        json.dumps(
            {
                "provider": "hindsight",
                "operation": "retain",
                "source_record_ref": "crystal-public-1",
                "source_version": "v1",
                "substrate_record_id": "hs_1",
                "substrate_snapshot_id": "snap_1",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "gateway.log").write_text("secret token SHOULD_NOT_LEAK\n", encoding="utf-8")
    (tmp_path / "logs" / "errors.log").write_text("api_key=SHOULD_NOT_LEAK\n", encoding="utf-8")
    (tmp_path / "mailbox" / "inbox").mkdir(parents=True)
    (tmp_path / "mailbox" / "outbox").mkdir()
    (tmp_path / "mailbox" / "inbox" / "msg.json").write_text('{"body":"SHOULD_NOT_LEAK"}\n', encoding="utf-8")
    (tmp_path / "system-modules" / "mailbox").mkdir(parents=True)
    (tmp_path / "system-modules" / "mailbox" / "would_send.jsonl").write_text(
        json.dumps({"created_at": "2026-06-03T02:00:00Z", "actual_send": False, "body": "SHOULD_NOT_LEAK"}) + "\n",
        encoding="utf-8",
    )
    wandering_root = tmp_path / "system-modules" / "wandering_mind"
    wandering_root.mkdir(parents=True)
    (wandering_root / "state.json").write_text(
        json.dumps({"generated_count": 2, "skipped_count": 1, "latest_status": "generated", "latest_reason": "cadence_ok"}),
        encoding="utf-8",
    )
    (wandering_root / "outputs.jsonl").write_text(
        json.dumps({"created_at": "2026-06-03T03:00:00Z", "status": "generated", "content": "SHOULD_NOT_LEAK"}) + "\n",
        encoding="utf-8",
    )
    (wandering_root / "would_send.jsonl").write_text(
        json.dumps({"created_at": "2026-06-03T03:01:00Z", "actual_send": False, "body": "SHOULD_NOT_LEAK"}) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "mcp_servers.json").write_text(
        json.dumps({"mcpServers": {"voicebox": {"status": "failed", "command": "SHOULD_NOT_LEAK"}}}),
        encoding="utf-8",
    )
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
    assert by_source["runtime_logs"]["payload"]["log_file_count"] == 2
    assert by_source["runtime_logs"]["payload"]["error_log_exists"] is True
    assert by_source["hindsight_provider_stats"]["payload"]["operation_count"] == 2
    assert by_source["hindsight_provider_stats"]["payload"]["retain_count"] == 1
    assert by_source["mailbox_status"]["payload"]["inbox_count"] == 1
    assert by_source["mailbox_status"]["payload"]["would_send_count"] == 1
    assert by_source["wandering_mind_state"]["payload"]["output_count"] == 1
    assert by_source["wandering_mind_state"]["payload"]["would_send_count"] == 1
    assert by_source["mcp_server_health"]["payload"]["configured_server_count"] == 1
    assert by_source["mcp_server_health"]["payload"]["failed_server_count"] == 1


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
