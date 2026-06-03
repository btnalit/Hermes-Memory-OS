import pytest

from plugins.memory.memory_os.signal_source_registry import (
    SignalSourceSpec,
    evaluate_signal_source_requirements,
    signal_source_specs,
    validate_signal_source_specs,
)


def test_signal_source_registry_declares_read_only_sources():
    specs = signal_source_specs()

    assert specs
    assert {spec.source_key for spec in specs} >= {
        "execution_gate_envelopes",
        "session_mirror_apply",
        "owner_actions",
        "memory_sources_feedback",
        "hermes_cron_jobs",
        "hindsight_provider_stats",
        "mailbox_status",
        "wandering_mind_state",
        "skills_inventory",
        "mcp_server_health",
        "profile_config",
        "kanban_state",
        "tool_registry",
        "runtime_logs",
    }
    assert all(spec.writes_allowed is False for spec in specs)
    assert all(spec.allowed_payload_fields for spec in specs)
    assert all(spec.retention_class for spec in specs)
    by_source = {spec.source_key: spec for spec in specs}
    assert by_source["session_mirror_apply"].source_path_candidates == (
        "memory-os/system/session_mirror_applies.jsonl",
    )
    assert "external_failure_count" in by_source["hermes_cron_jobs"].allowed_payload_fields
    assert "operation_count" in by_source["hindsight_provider_stats"].allowed_payload_fields
    assert "would_send_count" in by_source["mailbox_status"].allowed_payload_fields
    assert "latest_output_at" in by_source["wandering_mind_state"].allowed_payload_fields
    assert "configured_server_count" in by_source["mcp_server_health"].allowed_payload_fields
    assert "error_log_exists" in by_source["runtime_logs"].allowed_payload_fields
    assert validate_signal_source_specs(specs)["status"] == "ok"


def test_signal_source_registry_rejects_write_capable_spec():
    bad = SignalSourceSpec(
        source_key="bad_writer",
        owner_system="memory-os",
        action_owner="memory-os",
        scope_type="host",
        host_capability_key="memory_os_core",
        activation_condition="always",
        requirement_policy="required",
        source_path_candidates=("memory-os/bad.jsonl",),
        payload_schema="memory-os.signal_payload.bad.v0",
        allowed_payload_fields=("status",),
        redaction_policy_id="metadata_only",
        retention_class="governance_evidence",
        allowed_outputs=("signal_observation",),
        writes_allowed=True,
        monitor_fields=("bad_writer_status",),
    )

    with pytest.raises(ValueError, match="writes_allowed"):
        validate_signal_source_specs((bad,))


def test_requirement_evaluation_derives_missing_and_optional_from_probe():
    specs = [
        SignalSourceSpec(
            source_key="required_present",
            owner_system="memory-os",
            action_owner="memory-os",
            scope_type="host",
            host_capability_key="memory_os_core",
            activation_condition="always",
            requirement_policy="required",
            source_path_candidates=("memory-os/system/example.jsonl",),
            payload_schema="memory-os.signal_payload.status.v0",
            allowed_payload_fields=("status",),
            redaction_policy_id="metadata_only",
            retention_class="governance_evidence",
            allowed_outputs=("signal_observation",),
            writes_allowed=False,
            monitor_fields=("required_present_status",),
        ),
        SignalSourceSpec(
            source_key="optional_missing",
            owner_system="hermes",
            action_owner="hermes",
            scope_type="host",
            host_capability_key="mailbox",
            activation_condition="if_present",
            requirement_policy="optional_if_present",
            source_path_candidates=("mailbox/status.json",),
            payload_schema="memory-os.signal_payload.status.v0",
            allowed_payload_fields=("status",),
            redaction_policy_id="metadata_only",
            retention_class="short_lived_status",
            allowed_outputs=("signal_observation",),
            writes_allowed=False,
            monitor_fields=("optional_missing_status",),
        ),
    ]
    probe = {
        "capabilities": {
            "memory_os_core": {"status": "present"},
            "mailbox": {"status": "missing"},
        }
    }

    report = evaluate_signal_source_requirements(specs, probe)
    by_source = {item["source_key"]: item for item in report["sources"]}

    assert report["required_missing_count"] == 0
    assert by_source["required_present"]["requirement_status"] == "required_present"
    assert by_source["optional_missing"]["requirement_status"] == "optional_missing"
