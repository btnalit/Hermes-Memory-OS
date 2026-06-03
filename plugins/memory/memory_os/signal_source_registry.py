"""Read-only Memory-OS signal source registry for left-brain projection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


SIGNAL_SOURCE_REGISTRY_SCHEMA_VERSION = "memory-os.signal_source_registry.v0"

REQUIREMENT_POLICIES = {"required", "required_if_configured", "optional_if_present", "smoke_only"}
RETENTION_CLASSES = {"governance_evidence", "short_lived_status", "operational_evidence", "prototype_evidence"}


@dataclass(frozen=True)
class SignalSourceSpec:
    source_key: str
    owner_system: str
    action_owner: str
    scope_type: str
    host_capability_key: str
    activation_condition: str
    requirement_policy: str
    source_path_candidates: tuple[str, ...]
    payload_schema: str
    allowed_payload_fields: tuple[str, ...]
    redaction_policy_id: str
    retention_class: str
    allowed_outputs: tuple[str, ...]
    writes_allowed: bool
    monitor_fields: tuple[str, ...]
    tier: int = 1
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_key": self.source_key,
            "owner_system": self.owner_system,
            "action_owner": self.action_owner,
            "scope_type": self.scope_type,
            "host_capability_key": self.host_capability_key,
            "activation_condition": self.activation_condition,
            "requirement_policy": self.requirement_policy,
            "source_path_candidates": list(self.source_path_candidates),
            "payload_schema": self.payload_schema,
            "allowed_payload_fields": list(self.allowed_payload_fields),
            "redaction_policy_id": self.redaction_policy_id,
            "retention_class": self.retention_class,
            "allowed_outputs": list(self.allowed_outputs),
            "writes_allowed": self.writes_allowed,
            "monitor_fields": list(self.monitor_fields),
            "tier": self.tier,
            "description": self.description,
        }


def signal_source_specs() -> tuple[SignalSourceSpec, ...]:
    """Return the single source of truth for 53 signal inputs.

    The registry intentionally includes broader Hermes surfaces than the first
    collectors use. Requirement evaluation decides which sources are required
    for a concrete host; the specs themselves remain read-only.
    """

    status_fields = (
        "status",
        "capability_status",
        "available",
        "freshness_seconds",
        "record_count",
        "latest_status",
        "boundary_true_count",
        "raw_body_included",
    )
    return (
        _spec(
            "execution_gate_envelopes",
            "memory-os",
            "execution_gate",
            "execution_gate",
            "required",
            ("memory-os/system/execution_gate_envelopes.jsonl",),
            status_fields,
            retention_class="operational_evidence",
            tier=0,
        ),
        _spec(
            "session_mirror_apply",
            "memory-os",
            "session_mirror",
            "session_mirror",
            "required_if_configured",
            ("memory-os/system/session_mirror_applies.jsonl",),
            status_fields + ("apply_count", "latest_apply_status"),
            retention_class="governance_evidence",
            tier=0,
        ),
        _spec(
            "owner_actions",
            "memory-os",
            "owner_actions",
            "owner_channel",
            "required_if_configured",
            ("memory-os/system/owner_actions.jsonl",),
            status_fields + ("owner_action_count", "action_required_count"),
            retention_class="governance_evidence",
            tier=0,
        ),
        _spec(
            "memory_sources_feedback",
            "memory-os",
            "memory_sources",
            "memory_sources",
            "required_if_configured",
            ("memory-os/system/memory_sources_feedback.jsonl",),
            status_fields + ("feedback_count",),
            retention_class="governance_evidence",
            tier=0,
        ),
        _spec(
            "hermes_cron_jobs",
            "hermes",
            "hermes_cron",
            "hermes_cron",
            "required_if_configured",
            ("cron/jobs.json", "memory-os/system/cron_registry_snapshot.json"),
            status_fields
            + (
                "wrapped_count",
                "expected_count",
                "job_count",
                "memory_os_job_count",
                "external_job_count",
                "latest_success_at",
                "latest_failure_at",
                "latest_failure_job",
                "latest_failure_reason",
                "latest_failure_deliver",
                "latest_failure_owner_system",
                "failure_count",
                "external_failure_count",
                "timeout_failure_count",
                "external_failure_jobs",
            ),
            retention_class="operational_evidence",
            tier=0,
        ),
        _spec(
            "cognitive_loop_status",
            "memory-os",
            "cognitive_loop",
            "memory_os_core",
            "required_if_configured",
            ("system-modules/cognitive_loop/reports.jsonl",),
            status_fields
            + (
                "report_count",
                "latest_cycle_id",
                "latest_finished_at",
                "step_count",
                "error_step_count",
                "warning_step_count",
                "required_step_missing_count",
                "boundary_true_count",
            ),
            retention_class="operational_evidence",
            tier=0,
        ),
        _spec(
            "gateway_runtime_status",
            "hermes",
            "gateway",
            "gateway",
            "required_if_configured",
            ("memory-os/runtime/heartbeat_state.json", "logs/gateway.log", "gateway.log"),
            status_fields
            + (
                "heartbeat_state_exists",
                "last_heartbeat_at",
                "heartbeat_age_seconds",
                "processed_event_count",
                "gateway_capability_status",
                "gateway_version_available",
                "gateway_log_exists",
                "gateway_log_age_seconds",
            ),
            retention_class="short_lived_status",
            tier=0,
        ),
        _spec(
            "proposal_queue_pressure",
            "memory-os",
            "proposal_queue",
            "memory_os_core",
            "required_if_configured",
            ("system-modules/proposal_queue/queue.json",),
            status_fields
            + (
                "proposal_count",
                "state_candidate_count",
                "approved_for_proposal_count",
                "awaiting_ops_gate_count",
                "ops_gate_reviewed_count",
                "execution_ticket_count",
                "actual_execute_count",
                "crystallized_approval_granted_count",
            ),
            retention_class="governance_evidence",
            tier=0,
        ),
        _spec(
            "candidate_queue_pressure",
            "memory-os",
            "candidate_review",
            "memory_os_core",
            "required_if_configured",
            ("memory-os/crystallized/candidates.jsonl",),
            status_fields
            + (
                "candidate_count",
                "private_candidate_count",
                "public_candidate_count",
                "latest_candidate_at",
                "kind_count",
                "source_event_ref_count",
                "bridge_state_count",
            ),
            retention_class="governance_evidence",
            tier=0,
        ),
        _spec(
            "owner_review_pressure",
            "memory-os",
            "owner_review",
            "memory_os_core",
            "required_if_configured",
            (
                "memory-os/system/owner_actions.jsonl",
                "system-modules/left_brain_advisor/reports.jsonl",
                "system-modules/proposal_queue/queue.json",
                "memory-os/crystallized/candidates.jsonl",
            ),
            status_fields
            + (
                "owner_action_count",
                "action_required_estimate_count",
                "review_suggested_estimate_count",
                "fyi_estimate_count",
                "advisor_finding_count",
                "owner_visible_finding_count",
                "pending_candidate_count",
                "pending_proposal_count",
                "overflow_estimate_count",
                "duplicate_action_count",
                "error_action_count",
            ),
            retention_class="governance_evidence",
            tier=0,
        ),
        _spec(
            "hindsight_provider_stats",
            "hindsight",
            "hindsight",
            "hindsight",
            "optional_if_present",
            ("hindsight/config.json", "memory-os/system/substrate_operations.jsonl"),
            status_fields
            + (
                "configured",
                "retain_enabled",
                "recall_mode",
                "reflect_enabled",
                "operation_count",
                "retain_count",
                "recall_count",
                "invalidate_count",
                "reflect_count",
                "raw_retained_count",
                "no_raw_retained",
                "projection_stale_count",
                "active_projection_count",
                "recall_llm_triggered",
                "reflect_hot_path_count",
                "latest_operation_at",
                "pollution_indicator_count",
            ),
            retention_class="governance_evidence",
            tier=1,
        ),
        _spec(
            "mailbox_status",
            "hermes",
            "mailbox",
            "mailbox",
            "optional_if_present",
            ("mailbox", "system/mailbox"),
            status_fields
            + (
                "mailbox_exists",
                "inbox_exists",
                "outbox_exists",
                "inbox_count",
                "outbox_count",
                "would_send_count",
                "latest_would_send_at",
                "backlog_count",
                "cooldown_active",
                "actual_send_count",
            ),
            retention_class="short_lived_status",
            tier=1,
        ),
        _spec(
            "wandering_mind_state",
            "hermes",
            "wandering_mind",
            "wandering_mind",
            "optional_if_present",
            ("system-modules/wandering_mind",),
            status_fields
            + (
                "state_exists",
                "output_count",
                "would_send_count",
                "generated_count",
                "skipped_count",
                "latest_status",
                "latest_reason",
                "latest_output_at",
                "latest_would_send_at",
                "actual_send_count",
                "household_digest_exists",
                "journal_count",
            ),
            retention_class="short_lived_status",
            tier=1,
        ),
        _spec(
            "skills_inventory",
            "hermes",
            "skills",
            "skills",
            "optional_if_present",
            ("skills", "plugins/skills"),
            status_fields
            + (
                "skill_count",
                "skill_directory_count",
                "skill_file_count",
                "skill_manifest_count",
                "skill_markdown_count",
                "latest_skill_age_seconds",
            ),
            retention_class="short_lived_status",
            tier=1,
        ),
        _spec(
            "mcp_server_health",
            "hermes",
            "mcp",
            "mcp",
            "optional_if_present",
            ("mcp", "mcp_servers.json", "config/mcp.json"),
            status_fields
            + (
                "config_file_count",
                "configured_server_count",
                "directory_server_count",
                "server_count",
                "healthy_count",
                "failed_server_count",
                "latest_config_age_seconds",
            ),
            retention_class="short_lived_status",
            tier=1,
        ),
        _spec(
            "profile_config",
            "hermes",
            "profile",
            "profile",
            "required_if_configured",
            ("profiles", "config.json"),
            status_fields
            + (
                "profile_id",
                "config_exists",
                "config_file_count",
                "profile_count",
                "active_profile_id",
                "memory_provider_configured",
                "hindsight_provider_configured",
                "channel_config_count",
                "model_config_present",
                "config_age_seconds",
            ),
            retention_class="operational_evidence",
            tier=1,
        ),
        _spec(
            "kanban_state",
            "hermes",
            "kanban",
            "kanban",
            "optional_if_present",
            ("kanban", "tasks", "system/kanban"),
            status_fields
            + (
                "card_count",
                "column_count",
                "open_card_count",
                "done_card_count",
                "latest_card_age_seconds",
            ),
            retention_class="short_lived_status",
            tier=2,
        ),
        _spec(
            "tool_registry",
            "hermes",
            "tools",
            "tools",
            "optional_if_present",
            ("tools", "plugins", "tool_registry.json"),
            status_fields
            + (
                "tool_count",
                "plugin_count",
                "mcp_tool_count",
                "tool_manifest_count",
                "tool_config_exists",
                "latest_tool_age_seconds",
            ),
            retention_class="short_lived_status",
            tier=2,
        ),
        _spec(
            "runtime_logs",
            "hermes",
            "logs",
            "logs",
            "optional_if_present",
            ("logs", "gateway.log", "system/logs"),
            status_fields
            + (
                "log_file_count",
                "latest_log_age_seconds",
                "latest_log_file",
                "latest_log_mtime",
                "error_log_exists",
                "error_log_size_bytes",
                "gateway_log_exists",
                "gateway_log_size_bytes",
                "rotated_log_count",
            ),
            retention_class="short_lived_status",
            tier=2,
        ),
    )


def validate_signal_source_specs(specs: Iterable[SignalSourceSpec] | None = None) -> dict[str, Any]:
    seen: set[str] = set()
    errors: list[dict[str, Any]] = []
    for spec in specs if specs is not None else signal_source_specs():
        if not spec.source_key:
            errors.append({"source_key": spec.source_key, "reason": "source_key_missing"})
        if spec.source_key in seen:
            errors.append({"source_key": spec.source_key, "reason": "source_key_duplicate"})
        seen.add(spec.source_key)
        if spec.writes_allowed:
            errors.append({"source_key": spec.source_key, "reason": "writes_allowed_true"})
        if spec.requirement_policy not in REQUIREMENT_POLICIES:
            errors.append({"source_key": spec.source_key, "reason": "requirement_policy_invalid"})
        if spec.retention_class not in RETENTION_CLASSES:
            errors.append({"source_key": spec.source_key, "reason": "retention_class_invalid"})
        if not spec.allowed_payload_fields:
            errors.append({"source_key": spec.source_key, "reason": "allowed_payload_fields_missing"})
        if not spec.payload_schema:
            errors.append({"source_key": spec.source_key, "reason": "payload_schema_missing"})
    if errors:
        raise ValueError(f"Invalid signal source registry: {errors}")
    return {
        "schema_version": SIGNAL_SOURCE_REGISTRY_SCHEMA_VERSION,
        "status": "ok",
        "source_count": len(seen),
        "writes_allowed_count": 0,
    }


def evaluate_signal_source_requirements(
    specs: Iterable[SignalSourceSpec] | None,
    host_capabilities: dict[str, Any],
) -> dict[str, Any]:
    resolved_specs = tuple(specs if specs is not None else signal_source_specs())
    capabilities = host_capabilities.get("capabilities") if isinstance(host_capabilities.get("capabilities"), dict) else {}
    sources = []
    for spec in resolved_specs:
        capability = capabilities.get(spec.host_capability_key) if isinstance(capabilities, dict) else {}
        status = _capability_status(capability)
        requirement_status = _requirement_status(spec, status)
        sources.append(
            {
                **spec.to_dict(),
                "capability_status": status,
                "requirement_status": requirement_status,
                "required_missing": requirement_status == "required_missing",
                "configured_missing": requirement_status == "configured_missing",
            }
        )
    required_missing = [item for item in sources if item["required_missing"]]
    return {
        "schema_version": "memory-os.signal_source_requirement_report.v0",
        "status": "error" if required_missing else "ok",
        "source_count": len(sources),
        "required_missing_count": len(required_missing),
        "optional_missing_count": sum(1 for item in sources if item["requirement_status"] == "optional_missing"),
        "sources": sources,
    }


def signal_source_spec_by_key(key: str) -> SignalSourceSpec | None:
    for spec in signal_source_specs():
        if spec.source_key == key:
            return spec
    return None


def _spec(
    source_key: str,
    owner_system: str,
    action_owner: str,
    host_capability_key: str,
    requirement_policy: str,
    source_path_candidates: tuple[str, ...],
    allowed_payload_fields: tuple[str, ...],
    *,
    retention_class: str,
    tier: int,
) -> SignalSourceSpec:
    return SignalSourceSpec(
        source_key=source_key,
        owner_system=owner_system,
        action_owner=action_owner,
        scope_type="host_profile",
        host_capability_key=host_capability_key,
        activation_condition="always" if requirement_policy == "required" else "if_configured_or_present",
        requirement_policy=requirement_policy,
        source_path_candidates=source_path_candidates,
        payload_schema="memory-os.signal_payload.status.v0",
        allowed_payload_fields=allowed_payload_fields,
        redaction_policy_id="metadata_only_no_raw_body",
        retention_class=retention_class,
        allowed_outputs=("signal_observation", "operational_signal"),
        writes_allowed=False,
        monitor_fields=(f"{source_key}_status",),
        tier=tier,
        description=f"Read-only signal source for {source_key}.",
    )


def _capability_status(capability: Any) -> str:
    if isinstance(capability, dict):
        return str(capability.get("status") or "missing")
    return "missing"


def _requirement_status(spec: SignalSourceSpec, capability_status: str) -> str:
    present = capability_status in {"available", "present", "configured", "running", "ok", "healthy"}
    if spec.requirement_policy == "required":
        return "required_present" if present else "required_missing"
    if spec.requirement_policy == "required_if_configured":
        if present:
            return "required_present"
        return "configured_missing" if capability_status == "configured_missing" else "not_configured"
    if spec.requirement_policy == "optional_if_present":
        return "optional_present" if present else "optional_missing"
    return "smoke_only"
