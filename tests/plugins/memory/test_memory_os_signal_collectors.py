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
        "\n".join(
            [
                json.dumps(
                    {
                        "provider": "hindsight",
                        "operation": "retain",
                        "source_record_ref": "crystal-public-1",
                        "source_version": "v1",
                        "substrate_record_id": "hs_1",
                        "substrate_snapshot_id": "snap_1",
                    }
                ),
                json.dumps(
                    {
                        "provider": "hindsight",
                        "operation": "retain",
                        "source_record_ref": "crystal-public-1",
                        "source_version": "v1",
                        "substrate_record_id": "hs_1_duplicate",
                        "substrate_snapshot_id": "snap_2",
                    }
                ),
            ]
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
    (tmp_path / "skills" / "memory-helper").mkdir(parents=True)
    (tmp_path / "skills" / "memory-helper" / "SKILL.md").write_text("secret SHOULD_NOT_LEAK\n", encoding="utf-8")
    (tmp_path / "profiles" / "memoryos-test").mkdir(parents=True)
    (tmp_path / "profiles" / "memoryos-test" / "config.yaml").write_text(
        "\n".join(
            [
                "memory:",
                "  provider: hindsight",
                "llm:",
                "  model: SHOULD_NOT_LEAK",
                "channels:",
                "  telegram: SHOULD_NOT_LEAK",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "kanban" / "todo").mkdir(parents=True)
    (tmp_path / "kanban" / "done").mkdir()
    (tmp_path / "kanban" / "todo" / "open-card.md").write_text("SHOULD_NOT_LEAK\n", encoding="utf-8")
    (tmp_path / "kanban" / "done" / "done-card.md").write_text("SHOULD_NOT_LEAK\n", encoding="utf-8")
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "tool_registry.json").write_text(json.dumps({"secret": "SHOULD_NOT_LEAK"}), encoding="utf-8")
    (tmp_path / "tools" / "mcp-tool.json").write_text(json.dumps({"secret": "SHOULD_NOT_LEAK"}), encoding="utf-8")
    cognitive_root = tmp_path / "system-modules" / "cognitive_loop"
    cognitive_root.mkdir(parents=True)
    cognitive_steps = [
        {"step": "left_brain_pipeline_check", "status": "ok"},
        {"step": "host_capability_probe", "status": "ok"},
        {"step": "signal_collection", "status": "ok"},
        {"step": "memory_projection", "status": "ok"},
        {"step": "left_brain_advisor", "status": "ok"},
        {"step": "governance_feedback", "status": "ok"},
        {"step": "deep_reflection", "status": "warning"},
        {"step": "heartbeat_post", "status": "ok"},
        {"step": "doctor_boundary_report", "status": "ok"},
    ]
    (cognitive_root / "reports.jsonl").write_text(
        json.dumps(
            {
                "cycle_id": "cycle-test",
                "status": "warning",
                "finished_at": "2026-06-03T04:00:00Z",
                "step_count": len(cognitive_steps),
                "steps": cognitive_steps,
                "notes": "SHOULD_NOT_LEAK",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "memory-os" / "runtime").mkdir(parents=True)
    (tmp_path / "memory-os" / "runtime" / "heartbeat_state.json").write_text(
        json.dumps({"last_heartbeat_at": "2026-06-03T04:01:00Z", "processed_event_count": 7, "debug": "SHOULD_NOT_LEAK"}),
        encoding="utf-8",
    )
    proposal_root = tmp_path / "system-modules" / "proposal_queue"
    proposal_root.mkdir(parents=True)
    (proposal_root / "queue.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "proposal_id": "prop1",
                        "state": "candidate",
                        "followup_state": "awaiting_ops_gate",
                        "actual_execute": False,
                        "body": "SHOULD_NOT_LEAK",
                    },
                    {
                        "proposal_id": "prop2",
                        "state": "approved_for_proposal",
                        "followup_state": "ops_gate_reviewed",
                        "execution_ticket": "",
                        "crystallized_approved": False,
                        "body": "SHOULD_NOT_LEAK",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    candidate_root = tmp_path / "memory-os" / "crystallized"
    candidate_root.mkdir(parents=True)
    (candidate_root / "candidates.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "candidate_id": "cand1",
                        "created_at": "2026-06-03T04:02:00Z",
                        "kind": "public_fact",
                        "visibility": "public",
                        "source_event_ref": "evt1",
                        "body": "SHOULD_NOT_LEAK",
                    }
                ),
                json.dumps(
                    {
                        "candidate_id": "cand2",
                        "created_at": "2026-06-03T04:03:00Z",
                        "kind": "private_note",
                        "visibility": "private",
                        "bridge_state": "needs_review",
                        "body": "SHOULD_NOT_LEAK",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    advisor_root = tmp_path / "system-modules" / "left_brain_advisor"
    advisor_root.mkdir(parents=True)
    (advisor_root / "reports.jsonl").write_text(
        json.dumps(
            {
                "findings": [
                    {"finding_id": "f1", "owner_visible": True, "owner_burden_class": "review_suggested", "summary": "SHOULD_NOT_LEAK"},
                    {"finding_id": "f2", "owner_visible": True, "owner_burden_class": "fyi", "summary": "SHOULD_NOT_LEAK"},
                ]
            }
        )
        + "\n",
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
    assert by_source["hindsight_governance_signals"]["payload"]["available"] is True
    assert by_source["hindsight_governance_signals"]["payload"]["suggestion_count"] >= 1
    assert by_source["hindsight_governance_signals"]["payload"]["duplicate_indicator_count"] == 1
    assert by_source["hindsight_governance_signals"]["payload"]["authoritative_claim_count"] == 0
    assert by_source["hindsight_governance_signals"]["payload"]["raw_body_included"] is False
    assert by_source["mailbox_status"]["payload"]["inbox_count"] == 1
    assert by_source["mailbox_status"]["payload"]["would_send_count"] == 1
    assert by_source["wandering_mind_state"]["payload"]["output_count"] == 1
    assert by_source["wandering_mind_state"]["payload"]["would_send_count"] == 1
    assert by_source["mcp_server_health"]["payload"]["configured_server_count"] == 1
    assert by_source["mcp_server_health"]["payload"]["failed_server_count"] == 1
    assert by_source["skills_inventory"]["payload"]["skill_directory_count"] == 1
    assert by_source["skills_inventory"]["payload"]["skill_manifest_count"] == 1
    assert by_source["profile_config"]["payload"]["config_exists"] is True
    assert by_source["profile_config"]["payload"]["hindsight_provider_configured"] is True
    assert by_source["profile_config"]["payload"]["channel_config_count"] == 1
    assert by_source["kanban_state"]["payload"]["card_count"] == 2
    assert by_source["kanban_state"]["payload"]["column_count"] == 2
    assert by_source["kanban_state"]["payload"]["open_card_count"] == 1
    assert by_source["kanban_state"]["payload"]["done_card_count"] == 1
    assert by_source["tool_registry"]["payload"]["tool_manifest_count"] == 1
    assert by_source["tool_registry"]["payload"]["mcp_tool_count"] == 1
    assert by_source["cognitive_loop_status"]["payload"]["step_count"] == len(cognitive_steps)
    assert by_source["cognitive_loop_status"]["payload"]["warning_step_count"] == 1
    assert by_source["gateway_runtime_status"]["payload"]["heartbeat_state_exists"] is True
    assert by_source["gateway_runtime_status"]["payload"]["processed_event_count"] == 7
    assert by_source["proposal_queue_pressure"]["payload"]["proposal_count"] == 2
    assert by_source["proposal_queue_pressure"]["payload"]["awaiting_ops_gate_count"] == 1
    assert by_source["candidate_queue_pressure"]["payload"]["candidate_count"] == 2
    assert by_source["candidate_queue_pressure"]["payload"]["private_candidate_count"] == 1
    assert by_source["owner_review_pressure"]["payload"]["advisor_finding_count"] == 2
    assert by_source["owner_review_pressure"]["payload"]["pending_proposal_count"] == 2
    assert by_source["host_capability_contract"]["payload"]["capability_count"] >= 20
    assert by_source["host_capability_contract"]["payload"]["contract_status"] == "ok"
    assert by_source["host_capability_contract"]["payload"]["missing_required_capability_count"] == 0
    assert by_source["host_capability_contract"]["payload"]["memory_provider_name"] == ""
    assert by_source["host_capability_contract"]["payload"]["structural_write_gate_status"] in {
        "present",
        "available",
        "migration_needed",
    }


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
