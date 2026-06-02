"""Memory-OS-owned Hermes cron registry."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryOSCronSpec:
    key: str
    name: str
    raw_script: str
    wrapper_script: str
    lane_id: str
    helper_kind: str


MEMORY_OS_CRON_SPECS: tuple[MemoryOSCronSpec, ...] = (
    MemoryOSCronSpec(
        key="owner_review_digest",
        name="memory-os-owner-review-digest",
        raw_script="memory_os_owner_review_digest.py",
        wrapper_script="memory_os_cron_owner_review_digest_gate.py",
        lane_id="owner_review_digest_render",
        helper_kind="owner_channel_render",
    ),
    MemoryOSCronSpec(
        key="right_brain_expression",
        name="memory-os-right-brain-expression",
        raw_script="memory_os_right_brain_expression.py",
        wrapper_script="memory_os_cron_right_brain_expression_gate.py",
        lane_id="right_brain_expression_render",
        helper_kind="owner_channel_render",
    ),
    MemoryOSCronSpec(
        key="module_cadence_report",
        name="memory-os-module-cadence-report",
        raw_script="memory_os_module_cadence_report_cron.py",
        wrapper_script="memory_os_cron_module_cadence_report_gate.py",
        lane_id="module_cadence_report",
        helper_kind="local_helper",
    ),
    MemoryOSCronSpec(
        key="right_brain_expression_outcome",
        name="memory-os-right-brain-expression-outcome",
        raw_script="memory_os_right_brain_expression_outcome_cron.py",
        wrapper_script="memory_os_cron_right_brain_expression_outcome_gate.py",
        lane_id="right_brain_expression_outcome",
        helper_kind="local_helper",
    ),
    MemoryOSCronSpec(
        key="proposal_followups_opsgate",
        name="memory-os-proposal-followups-opsgate",
        raw_script="memory_os_proposal_followups_ops_gate.py",
        wrapper_script="memory_os_cron_proposal_followups_opsgate_gate.py",
        lane_id="proposal_followups_opsgate",
        helper_kind="local_helper",
    ),
    MemoryOSCronSpec(
        key="expression_feedback_request",
        name="memory-os-expression-feedback-request",
        raw_script="memory_os_expression_feedback_prompt.py",
        wrapper_script="memory_os_cron_expression_feedback_request_gate.py",
        lane_id="expression_feedback_request",
        helper_kind="owner_channel_render",
    ),
    MemoryOSCronSpec(
        key="memory_sources_feedback_request",
        name="memory-os-memory-sources-feedback-request",
        raw_script="memory_os_memory_sources_feedback_prompt.py",
        wrapper_script="memory_os_cron_memory_sources_feedback_request_gate.py",
        lane_id="memory_sources_feedback_request",
        helper_kind="owner_channel_render",
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
