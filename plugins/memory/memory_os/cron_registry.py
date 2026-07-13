"""Memory-OS-owned Hermes cron registry."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MemoryOSCronSpec:
    key: str
    name: str
    raw_script: str
    wrapper_script: str
    lane_id: str
    helper_kind: str
    schedule_arg: str
    deliver_role: str
    prompt_ref: str
    no_agent: bool
    requires_boundary_report: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "raw_script": self.raw_script,
            "wrapper_script": self.wrapper_script,
            "lane_id": self.lane_id,
            "helper_kind": self.helper_kind,
            "schedule_arg": self.schedule_arg,
            "deliver_role": self.deliver_role,
            "prompt_ref": self.prompt_ref,
            "no_agent": self.no_agent,
            "requires_boundary_report": self.requires_boundary_report,
        }


MEMORY_OS_CRON_SPECS: tuple[MemoryOSCronSpec, ...] = (
    MemoryOSCronSpec(
        key="owner_review_digest",
        name="memory-os-owner-review-digest",
        raw_script="memory_os_owner_review_digest.py",
        wrapper_script="memory_os_cron_owner_review_digest_gate.py",
        lane_id="owner_review_digest_render",
        helper_kind="owner_channel_render",
        schedule_arg="owner_review_schedule",
        deliver_role="owner",
        prompt_ref="owner_review_agent_prompt",
        no_agent=False,
    ),
    MemoryOSCronSpec(
        key="right_brain_expression",
        name="memory-os-right-brain-expression",
        raw_script="memory_os_right_brain_expression.py",
        wrapper_script="memory_os_cron_right_brain_expression_gate.py",
        lane_id="right_brain_expression_render",
        helper_kind="owner_channel_render",
        schedule_arg="right_brain_schedule",
        deliver_role="right_brain",
        prompt_ref="right_brain_agent_prompt",
        no_agent=False,
    ),
    MemoryOSCronSpec(
        key="module_cadence_report",
        name="memory-os-module-cadence-report",
        raw_script="memory_os_module_cadence_report_cron.py",
        wrapper_script="memory_os_cron_module_cadence_report_gate.py",
        lane_id="module_cadence_report",
        helper_kind="local_helper",
        schedule_arg="module_cadence_schedule",
        deliver_role="local",
        prompt_ref="empty",
        no_agent=True,
    ),
    MemoryOSCronSpec(
        key="right_brain_expression_outcome",
        name="memory-os-right-brain-expression-outcome",
        raw_script="memory_os_right_brain_expression_outcome_cron.py",
        wrapper_script="memory_os_cron_right_brain_expression_outcome_gate.py",
        lane_id="right_brain_expression_outcome",
        helper_kind="local_helper",
        schedule_arg="right_brain_outcome_schedule",
        deliver_role="local",
        prompt_ref="empty",
        no_agent=True,
    ),
    MemoryOSCronSpec(
        key="proposal_followups_opsgate",
        name="memory-os-proposal-followups-opsgate",
        raw_script="memory_os_proposal_followups_ops_gate.py",
        wrapper_script="memory_os_cron_proposal_followups_opsgate_gate.py",
        lane_id="proposal_followups_opsgate",
        helper_kind="local_helper",
        schedule_arg="proposal_followups_schedule",
        deliver_role="local",
        prompt_ref="empty",
        no_agent=True,
    ),
    MemoryOSCronSpec(
        key="expression_feedback_request",
        name="memory-os-expression-feedback-request",
        raw_script="memory_os_expression_feedback_prompt.py",
        wrapper_script="memory_os_cron_expression_feedback_request_gate.py",
        lane_id="expression_feedback_request",
        helper_kind="owner_channel_render",
        schedule_arg="expression_feedback_schedule",
        deliver_role="owner",
        prompt_ref="expression_feedback_agent_prompt",
        no_agent=False,
    ),
    MemoryOSCronSpec(
        key="memory_sources_feedback_request",
        name="memory-os-memory-sources-feedback-request",
        raw_script="memory_os_memory_sources_feedback_prompt.py",
        wrapper_script="memory_os_cron_memory_sources_feedback_request_gate.py",
        lane_id="memory_sources_feedback_request",
        helper_kind="owner_channel_render",
        schedule_arg="memory_sources_feedback_schedule",
        deliver_role="owner",
        prompt_ref="memory_sources_feedback_agent_prompt",
        no_agent=False,
    ),
    MemoryOSCronSpec(
        key="candidate_aggregation",
        name="memory-os-candidate-aggregation",
        raw_script="memory_os_candidate_aggregation_lane.py",
        wrapper_script="memory_os_cron_candidate_aggregation_gate.py",
        lane_id="candidate_aggregation",
        helper_kind="bounded_reversible_queue",
        schedule_arg="candidate_aggregation_schedule",
        deliver_role="local",
        prompt_ref="empty",
        no_agent=True,
        requires_boundary_report=True,
    ),
    MemoryOSCronSpec(
        key="fact_judge",
        name="memory-os-fact-judge",
        raw_script="memory_os_fact_judge_lane.py",
        wrapper_script="memory_os_cron_fact_judge_gate.py",
        lane_id="fact_judge",
        helper_kind="local_helper",
        schedule_arg="fact_judge_schedule",
        deliver_role="local",
        prompt_ref="empty",
        no_agent=True,
        requires_boundary_report=False,
    ),
    MemoryOSCronSpec(
        key="index_sync",
        name="memory-os-index-sync",
        raw_script="memory_os_index_sync.py",
        wrapper_script="memory_os_cron_index_sync_gate.py",
        lane_id="index_sync",
        helper_kind="local_helper",
        schedule_arg="index_sync_schedule",
        deliver_role="local",
        prompt_ref="empty",
        no_agent=True,
        requires_boundary_report=False,
    ),
    MemoryOSCronSpec(
        key="event_stats_refresh",
        name="memory-os-event-stats-refresh",
        raw_script="memory_os_event_stats_refresh.py",
        wrapper_script="memory_os_cron_event_stats_refresh_gate.py",
        lane_id="event_stats_refresh",
        helper_kind="local_helper",
        schedule_arg="event_stats_refresh_schedule",
        deliver_role="local",
        prompt_ref="empty",
        no_agent=True,
        requires_boundary_report=False,
    ),
    MemoryOSCronSpec(
        key="exposure_rollup",
        name="memory-os-exposure-rollup",
        raw_script="memory_os_exposure_rollup.py",
        wrapper_script="memory_os_cron_exposure_rollup_gate.py",
        lane_id="exposure_rollup",
        helper_kind="local_helper",
        schedule_arg="exposure_rollup_schedule",
        deliver_role="local",
        prompt_ref="empty",
        no_agent=True,
        requires_boundary_report=False,
    ),
    MemoryOSCronSpec(
        key="working_cleanup",
        name="memory-os-working-cleanup",
        raw_script="cleanup_expired_working.py",
        wrapper_script="memory_os_cron_working_cleanup_gate.py",
        lane_id="working_cleanup",
        helper_kind="local_helper",
        schedule_arg="working_cleanup_schedule",
        deliver_role="local",
        prompt_ref="empty",
        no_agent=True,
        requires_boundary_report=False,
    ),
    MemoryOSCronSpec(
        key="l3_probe_verification",
        name="memory-os-l3-probe-verification",
        raw_script="memory_os_l3_probe_helper.py",
        wrapper_script="memory_os_cron_l3_probe_verification_gate.py",
        lane_id="l3_probe_verification",
        helper_kind="local_helper",
        schedule_arg="l3_probe_schedule",
        deliver_role="local",
        prompt_ref="empty",
        no_agent=True,
        requires_boundary_report=False,
    ),
    MemoryOSCronSpec(
        key="state_overlay_refresh",
        name="memory-os-state-overlay-refresh",
        raw_script="memory_os_state_overlay_refresh.py",
        wrapper_script="memory_os_cron_state_overlay_refresh_gate.py",
        lane_id="state_overlay_refresh",
        helper_kind="local_helper",
        schedule_arg="state_overlay_refresh_schedule",
        deliver_role="local",
        prompt_ref="empty",
        no_agent=True,
        requires_boundary_report=False,
    ),
    MemoryOSCronSpec(
        key="entity_index_refresh",
        name="memory-os-entity-index-refresh",
        raw_script="memory_os_entity_index_refresh.py",
        wrapper_script="memory_os_cron_entity_index_refresh_gate.py",
        lane_id="entity_index_refresh",
        helper_kind="local_helper",
        schedule_arg="entity_index_refresh_schedule",
        deliver_role="local",
        prompt_ref="empty",
        no_agent=True,
        requires_boundary_report=False,
    ),
    MemoryOSCronSpec(
        key="hindsight_advisory_digest",
        name="memory-os-hindsight-advisory-digest",
        raw_script="memory_os_hindsight_advisory_digest.py",
        wrapper_script="memory_os_cron_hindsight_advisory_digest_gate.py",
        lane_id="hindsight_advisory_digest",
        helper_kind="local_helper",
        schedule_arg="hindsight_advisory_digest_schedule",
        deliver_role="local",
        prompt_ref="empty",
        no_agent=True,
        requires_boundary_report=False,
    ),
    MemoryOSCronSpec(
        key="hindsight_health_probe",
        name="memory-os-hindsight-health-probe",
        raw_script="memory_os_hindsight_health_probe.py",
        wrapper_script="memory_os_hindsight_health_probe.py",
        lane_id="hindsight_health_probe",
        helper_kind="read_only_probe",
        schedule_arg="hindsight_health_probe_schedule",
        deliver_role="local",
        prompt_ref="empty",
        no_agent=True,
        requires_boundary_report=False,
    ),
    MemoryOSCronSpec(
        key="clearance_cycle",
        name="memory-os-clearance-cycle",
        raw_script="memory_os_clearance_cycle_helper.py",
        wrapper_script="memory_os_cron_clearance_cycle_gate.py",
        lane_id="clearance_cycle",
        helper_kind="local_helper",
        schedule_arg="clearance_cycle_schedule",
        deliver_role="local",
        prompt_ref="empty",
        no_agent=True,
        requires_boundary_report=False,
    ),
)


def memory_os_cron_specs() -> tuple[MemoryOSCronSpec, ...]:
    return MEMORY_OS_CRON_SPECS


def memory_os_cron_spec_by_key(key: str) -> MemoryOSCronSpec | None:
    for spec in MEMORY_OS_CRON_SPECS:
        if spec.key == key:
            return spec
    return None


def memory_os_cron_spec_by_name(name: str) -> MemoryOSCronSpec | None:
    for spec in MEMORY_OS_CRON_SPECS:
        if spec.name == name:
            return spec
    return None


def cron_registry_snapshot(*, source_commit: str = "", specs: tuple[MemoryOSCronSpec, ...] | None = None) -> dict[str, Any]:
    selected_specs = specs if specs is not None else MEMORY_OS_CRON_SPECS
    return {
        "schema_version": "memory-os.cron_registry.v0",
        "source_commit": str(source_commit or ""),
        "specs": [spec.to_json() for spec in selected_specs],
    }


def write_cron_registry_snapshot(
    path: Path,
    *,
    source_commit: str = "",
    specs: tuple[MemoryOSCronSpec, ...] | None = None,
) -> dict[str, Any]:
    snapshot = cron_registry_snapshot(source_commit=source_commit, specs=specs)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return snapshot


def specs_from_snapshot(value: dict[str, Any]) -> tuple[MemoryOSCronSpec, ...]:
    specs = []
    for item in value.get("specs", []) if isinstance(value.get("specs"), list) else []:
        if not isinstance(item, dict):
            continue
        specs.append(
            MemoryOSCronSpec(
                key=str(item.get("key") or ""),
                name=str(item.get("name") or ""),
                raw_script=str(item.get("raw_script") or ""),
                wrapper_script=str(item.get("wrapper_script") or ""),
                lane_id=str(item.get("lane_id") or ""),
                helper_kind=str(item.get("helper_kind") or "local_helper"),
                schedule_arg=str(item.get("schedule_arg") or ""),
                deliver_role=str(item.get("deliver_role") or "local"),
                prompt_ref=str(item.get("prompt_ref") or "empty"),
                no_agent=bool(item.get("no_agent")),
                requires_boundary_report=bool(item.get("requires_boundary_report")),
            )
        )
    return tuple(spec for spec in specs if spec.key and spec.name and spec.raw_script and spec.wrapper_script)
