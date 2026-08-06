"""Memory-OS-owned Hermes cron registry.

Two tables, deliberately kept separate (see
``docs/resolver/hermes-memory-os-cron-consolidation-plan.md``):

``MemoryOSCronLaneDef`` / ``MemoryOSCronSpec``
    The *governance identity* of a lane: ``lane_id``, ``raw_script``,
    ``helper_kind`` (risk class) and boundary-report requirement.  One entry
    per ExecutionGate lane.  This granularity is what the monitor, the
    envelope journal and StructuralWriteGate scope checks all key off, so it
    never collapses.

``MemoryOSCronGroupSpec``
    The *Hermes scheduling surface*: the job that actually gets created via
    ``hermes cron create``.  Several lanes share one group job, which is fired
    by a tick wrapper that runs each due member behind its own ExecutionGate
    permit.

``MEMORY_OS_CRON_SPECS`` is the join of the two: every lane still exposes a
``name``/``wrapper_script``/``schedule_arg``, but those values are *derived
from its group* rather than owned per lane.  Existing consumers therefore keep
working unchanged; the only visible difference is that several specs now share
one ``name``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


RETIRED_MEMORY_OS_CRON_SCRIPTS = {
    "memory-os-right-brain-expression": "memory_os_cron_right_brain_expression_gate.py",
    "memory-os-right-brain-expression-outcome": "memory_os_cron_right_brain_expression_outcome_gate.py",
}
RETIRED_MEMORY_OS_CRON_SCRIPT_NAMES = frozenset(
    {
        *RETIRED_MEMORY_OS_CRON_SCRIPTS.values(),
        "memory_os_right_brain_expression.py",
        "memory_os_right_brain_expression_outcome_cron.py",
        # Commit 47bbc13 extracted the "sannai community" feature (see
        # docs/resolver/hermes-memory-os-optimization-roadmap.md section 11)
        # out of the repo, but these self-contained community cron scripts
        # (no ExecutionGate wrapper ever existed for them) can still be
        # running on already-deployed hosts. Neither their job "name" nor
        # "script" starts with "memory-os-"/"memory_os_", so without a raw
        # script-name entry here they fall through to external_unmanaged
        # (invisible drift) in classify_hermes_cron_jobs instead of the
        # retired_legacy bucket.
        "community_monitor.py",
        "community_partner_reply.py",
    }
)

# ── Legacy per-lane cron jobs (superseded by group ticks) ─────────────
#
# Before the group consolidation every lane owned its own Hermes cron job
# named ``memory-os-<lane>`` running a 5-line shim
# ``memory_os_cron_<lane>_gate.py``.  Those jobs still exist (paused) on
# already-onboarded hosts.
#
# They MUST be listed here.  ``classify_hermes_cron_jobs`` resolves a job by
# spec name / wrapper script / raw script; after consolidation none of those
# lookups match a legacy per-lane job any more, so without this table the job
# falls through to the ``name.startswith("memory-os-")`` branch and lands in
# ``unregistered_like`` -- which the 3.200 monitor reports as a FAIL
# (``execution_gate_memory_os_cron_unregistered_like_job``) on every upgraded
# host.  This is the identical trap the retired sannai community scripts hit
# above; the fix is the same: name them explicitly.
LEGACY_PER_LANE_CRON_JOBS = {
    "memory-os-index-sync": "memory_os_cron_index_sync_gate.py",
    "memory-os-event-stats-refresh": "memory_os_cron_event_stats_refresh_gate.py",
    "memory-os-state-overlay-refresh": "memory_os_cron_state_overlay_refresh_gate.py",
    "memory-os-entity-index-refresh": "memory_os_cron_entity_index_refresh_gate.py",
    "memory-os-proposal-followups-opsgate": "memory_os_cron_proposal_followups_opsgate_gate.py",
    "memory-os-clearance-cycle": "memory_os_cron_clearance_cycle_gate.py",
    "memory-os-hindsight-health-probe": "memory_os_hindsight_health_probe.py",
    "memory-os-fact-judge": "memory_os_cron_fact_judge_gate.py",
    "memory-os-candidate-aggregation": "memory_os_cron_candidate_aggregation_gate.py",
    "memory-os-l3-probe-verification": "memory_os_cron_l3_probe_verification_gate.py",
    "memory-os-v3-wandering": "memory_os_cron_v3_wandering_gate.py",
    "memory-os-exposure-rollup": "memory_os_cron_exposure_rollup_gate.py",
    "memory-os-v3-seed-evidence": "memory_os_cron_v3_seed_evidence_gate.py",
    "memory-os-v3-journal-sweep": "memory_os_cron_v3_journal_sweep_gate.py",
    "memory-os-working-cleanup": "memory_os_cron_working_cleanup_gate.py",
    "memory-os-hindsight-advisory-digest": "memory_os_cron_hindsight_advisory_digest_gate.py",
}
LEGACY_PER_LANE_CRON_JOB_NAMES = frozenset(LEGACY_PER_LANE_CRON_JOBS)
LEGACY_PER_LANE_CRON_SCRIPT_NAMES = frozenset(LEGACY_PER_LANE_CRON_JOBS.values())

# Registry keys deliberately withheld from the active-closure cron profile.
# Owned here (not in the onboarding script) so every consumer that can import
# the registry — onboarding, the monitor's host-side snapshot-parity probe,
# dashboards — reads ONE intent record: a compiled member absent from the
# deployed snapshot is silent drift ONLY when it is not documented here.
# A key belongs here ONLY for a documented, deliberate reason — never merely
# because the spec happens to be new.
#
#   - module_cadence_report: the cadence report artifact is already produced
#     on demand by build_cadence_report() from both the monitor dashboard
#     snapshot and the 3.200 full monitor, so a dedicated periodic cron job
#     is redundant; it remains available under the "full" cron profile.
#   - clearance_cycle: DEFERRED ACTIVATION, not a permanent exclusion. The
#     helper/gate scripts are deployed and the M3 watermark fix removed the
#     technical blocker, but switching the lane on is an owner decision that
#     must not ride in as a side effect of an unrelated change. To enable:
#     delete this one line (and regenerate the deployed snapshot).
ACTIVE_CLOSURE_EXCLUDED_CRON_KEYS = frozenset({
    "module_cadence_report",
    "clearance_cycle",
})

DUE_POLICY_INTERVAL = "interval"
DUE_POLICY_CALENDAR = "calendar"


@dataclass(frozen=True)
class MemoryOSCronGroupSpec:
    """One Hermes cron job. Fires a tick that runs its due members."""

    key: str
    name: str
    wrapper_script: str
    schedule_arg: str
    default_schedule: str
    deliver_role: str
    prompt_ref: str
    no_agent: bool
    member_keys: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "wrapper_script": self.wrapper_script,
            "schedule_arg": self.schedule_arg,
            "default_schedule": self.default_schedule,
            "deliver_role": self.deliver_role,
            "prompt_ref": self.prompt_ref,
            "no_agent": self.no_agent,
            "member_keys": list(self.member_keys),
        }


@dataclass(frozen=True)
class MemoryOSCronLaneDef:
    """Governance identity of a lane, independent of how it is scheduled."""

    key: str
    raw_script: str
    lane_id: str
    helper_kind: str
    group_key: str
    due_interval_minutes: int
    due_policy: str = DUE_POLICY_INTERVAL
    calendar_anchor: str = ""
    timeout_seconds: int = 300
    requires_boundary_report: bool = False


@dataclass(frozen=True)
class MemoryOSCronSpec:
    """Lane joined with its group.

    ``name``/``wrapper_script``/``schedule_arg``/``deliver_role``/
    ``prompt_ref``/``no_agent`` are the *group's* values -- several specs
    legitimately share them.
    """

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
    group_key: str = ""
    due_policy: str = DUE_POLICY_INTERVAL
    due_interval_minutes: int = 1440
    calendar_anchor: str = ""
    timeout_seconds: int = 300

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
            "group_key": self.group_key,
            "due_policy": self.due_policy,
            "due_interval_minutes": self.due_interval_minutes,
            "calendar_anchor": self.calendar_anchor,
            "timeout_seconds": self.timeout_seconds,
        }


# ── Group table: what actually becomes a Hermes cron job ──────────────
#
# Tick minutes are deliberately STAGGERED (:02/:17/:32/:47, :07/:37, :12,
# 00:05) rather than sharing :00. Aligned expressions (*/15, */30, 0 * * * *)
# all fire at the top of the hour, which put three group runners in the same
# minute contending on execution_gate_index.json -- the very concurrency this
# consolidation set out to remove. Staggering changes no lane's cadence:
# a lane's rate comes from due_interval_minutes, not from which minute its
# tick lands on.
#
# Four multi-member tick groups collapse 16 local lanes into 4 jobs.  The
# owner-facing lanes keep a dedicated single-member group each: they render a
# distinct owner message through their own agent prompt and deliver channel,
# so merging them would fuse separate owner messages and cross-contaminate
# prompts.  full_monitor_refresh stays alone because it is the heavyweight
# (<=180s) full monitor and would block co-tenants of any tick.
MEMORY_OS_CRON_GROUPS: tuple[MemoryOSCronGroupSpec, ...] = (
    MemoryOSCronGroupSpec(
        key="tick_derived",
        name="memory-os-tick-derived",
        wrapper_script="memory_os_cron_tick_derived.py",
        schedule_arg="tick_derived_schedule",
        default_schedule="2,17,32,47 * * * *",
        deliver_role="local",
        prompt_ref="empty",
        no_agent=True,
        member_keys=("event_stats_refresh", "index_sync", "state_overlay_refresh", "entity_index_refresh"),
    ),
    MemoryOSCronGroupSpec(
        key="tick_governance",
        name="memory-os-tick-governance",
        wrapper_script="memory_os_cron_tick_governance.py",
        schedule_arg="tick_governance_schedule",
        default_schedule="7,37 * * * *",
        deliver_role="local",
        prompt_ref="empty",
        no_agent=True,
        member_keys=("proposal_followups_opsgate", "clearance_cycle"),
    ),
    MemoryOSCronGroupSpec(
        key="tick_evidence",
        name="memory-os-tick-evidence",
        wrapper_script="memory_os_cron_tick_evidence.py",
        schedule_arg="tick_evidence_schedule",
        default_schedule="12 * * * *",
        deliver_role="local",
        prompt_ref="empty",
        no_agent=True,
        member_keys=(
            "hindsight_health_probe",
            "fact_judge",
            "candidate_aggregation",
            "l3_probe_verification",
            "v3_wandering",
            "session_fact_extraction",
        ),
    ),
    MemoryOSCronGroupSpec(
        key="tick_daily",
        name="memory-os-tick-daily",
        wrapper_script="memory_os_cron_tick_daily.py",
        schedule_arg="tick_daily_schedule",
        default_schedule="5 0 * * *",
        deliver_role="local",
        prompt_ref="empty",
        no_agent=True,
        member_keys=(
            "exposure_rollup",
            "v3_seed_evidence",
            "v3_journal_sweep",
            "working_cleanup",
            "hindsight_advisory_digest",
        ),
    ),
    # ── Single-member groups: unchanged Hermes jobs ───────────────────
    MemoryOSCronGroupSpec(
        key="owner_review_digest",
        name="memory-os-owner-review-digest",
        wrapper_script="memory_os_cron_owner_review_digest_gate.py",
        schedule_arg="owner_review_schedule",
        default_schedule="0 9 * * *",
        deliver_role="owner",
        prompt_ref="owner_review_agent_prompt",
        no_agent=False,
        member_keys=("owner_review_digest",),
    ),
    MemoryOSCronGroupSpec(
        key="memory_sources_feedback_request",
        name="memory-os-memory-sources-feedback-request",
        wrapper_script="memory_os_cron_memory_sources_feedback_request_gate.py",
        schedule_arg="memory_sources_feedback_schedule",
        default_schedule="30 10 * * *",
        deliver_role="owner",
        prompt_ref="memory_sources_feedback_agent_prompt",
        no_agent=False,
        member_keys=("memory_sources_feedback_request",),
    ),
    MemoryOSCronGroupSpec(
        key="expression_feedback_request",
        name="memory-os-expression-feedback-request",
        wrapper_script="memory_os_cron_expression_feedback_request_gate.py",
        schedule_arg="expression_feedback_schedule",
        default_schedule="0 5 * * 0",
        deliver_role="owner",
        prompt_ref="expression_feedback_agent_prompt",
        no_agent=False,
        member_keys=("expression_feedback_request",),
    ),
    MemoryOSCronGroupSpec(
        key="full_monitor_refresh",
        name="memory-os-full-monitor-refresh",
        wrapper_script="memory_os_full_monitor_refresh.py",
        schedule_arg="full_monitor_refresh_schedule",
        default_schedule="30 2 * * *",
        deliver_role="owner",
        prompt_ref="empty",
        no_agent=True,
        member_keys=("full_monitor_refresh",),
    ),
    MemoryOSCronGroupSpec(
        key="module_cadence_report",
        name="memory-os-module-cadence-report",
        wrapper_script="memory_os_cron_module_cadence_report_gate.py",
        schedule_arg="module_cadence_schedule",
        default_schedule="15 */6 * * *",
        deliver_role="local",
        prompt_ref="empty",
        no_agent=True,
        member_keys=("module_cadence_report",),
    ),
)


# ── Lane table: governance identity, one entry per ExecutionGate lane ──
#
# ``due_interval_minutes`` is the lane's effective cadence.  It is the ONLY
# source the monitor may use for completion-freshness windows -- deriving the
# window from the group's cron expression instead would collapse a weekly
# lane sharing a daily tick down to a 54h window and report it permanently
# stale.
MEMORY_OS_CRON_LANES: tuple[MemoryOSCronLaneDef, ...] = (
    # G1 derived views -- rebuildable projections, no governance risk
    MemoryOSCronLaneDef(
        key="event_stats_refresh",
        raw_script="memory_os_event_stats_refresh.py",
        lane_id="event_stats_refresh",
        helper_kind="local_helper",
        group_key="tick_derived",
        due_interval_minutes=15,
    ),
    MemoryOSCronLaneDef(
        key="index_sync",
        raw_script="memory_os_index_sync.py",
        lane_id="index_sync",
        helper_kind="local_helper",
        group_key="tick_derived",
        due_interval_minutes=30,
        timeout_seconds=600,
    ),
    MemoryOSCronLaneDef(
        key="state_overlay_refresh",
        raw_script="memory_os_state_overlay_refresh.py",
        lane_id="state_overlay_refresh",
        helper_kind="local_helper",
        group_key="tick_derived",
        due_interval_minutes=30,
    ),
    MemoryOSCronLaneDef(
        key="entity_index_refresh",
        raw_script="memory_os_entity_index_refresh.py",
        lane_id="entity_index_refresh",
        helper_kind="local_helper",
        group_key="tick_derived",
        due_interval_minutes=30,
    ),
    # G2 governance queues
    MemoryOSCronLaneDef(
        key="proposal_followups_opsgate",
        raw_script="memory_os_proposal_followups_ops_gate.py",
        lane_id="proposal_followups_opsgate",
        helper_kind="local_helper",
        group_key="tick_governance",
        due_interval_minutes=30,
    ),
    MemoryOSCronLaneDef(
        key="clearance_cycle",
        raw_script="memory_os_clearance_cycle_helper.py",
        lane_id="clearance_cycle",
        helper_kind="local_helper",
        group_key="tick_governance",
        due_interval_minutes=10,
    ),
    # G3 judgement + probe lanes
    MemoryOSCronLaneDef(
        key="hindsight_health_probe",
        raw_script="memory_os_hindsight_health_probe.py",
        lane_id="hindsight_health_probe",
        helper_kind="read_only_probe",
        group_key="tick_evidence",
        due_interval_minutes=60,
    ),
    MemoryOSCronLaneDef(
        key="fact_judge",
        raw_script="memory_os_fact_judge_lane.py",
        lane_id="fact_judge",
        helper_kind="local_helper",
        group_key="tick_evidence",
        due_interval_minutes=240,
        timeout_seconds=600,
    ),
    MemoryOSCronLaneDef(
        key="candidate_aggregation",
        raw_script="memory_os_candidate_aggregation_lane.py",
        lane_id="candidate_aggregation",
        helper_kind="bounded_reversible_queue",
        group_key="tick_evidence",
        due_interval_minutes=360,
        timeout_seconds=600,
        requires_boundary_report=True,
    ),
    MemoryOSCronLaneDef(
        key="l3_probe_verification",
        raw_script="memory_os_l3_probe_helper.py",
        lane_id="l3_probe_verification",
        helper_kind="local_helper",
        group_key="tick_evidence",
        due_interval_minutes=360,
    ),
    MemoryOSCronLaneDef(
        key="v3_wandering",
        raw_script="memory_os_v3_wandering.py",
        lane_id="v3_wandering",
        helper_kind="local_helper",
        group_key="tick_evidence",
        due_interval_minutes=360,
    ),
    # Offline lane closing the 140-char turn-summary truncation gap: reads
    # raw session transcripts (never events) and extracts durable facts from
    # messages too long to have survived _turn_summary's clip. See
    # plugins/modules/cognition/session_fact_extraction.py for the full
    # design/governance rationale.
    MemoryOSCronLaneDef(
        key="session_fact_extraction",
        raw_script="memory_os_session_fact_extraction_lane.py",
        lane_id="session_fact_extraction",
        helper_kind="local_helper",
        group_key="tick_evidence",
        due_interval_minutes=360,
        timeout_seconds=600,
    ),
    # G4 day-boundary + maintenance
    MemoryOSCronLaneDef(
        key="exposure_rollup",
        raw_script="memory_os_exposure_rollup.py",
        lane_id="exposure_rollup",
        helper_kind="local_helper",
        group_key="tick_daily",
        due_interval_minutes=1440,
    ),
    # Date-partitioned: emits a per-``natural_date`` daily record and exposes
    # consecutive_valid_day_count.  Elapsed-interval gating could drift it
    # across a UTC day boundary and double-count or skip a day, so it is
    # anchored to the calendar day instead.
    MemoryOSCronLaneDef(
        key="v3_seed_evidence",
        raw_script="memory_os_v3_seed_evidence.py",
        lane_id="v3_seed_evidence",
        helper_kind="local_helper",
        group_key="tick_daily",
        due_interval_minutes=1440,
        due_policy=DUE_POLICY_CALENDAR,
        calendar_anchor="00:00",
    ),
    MemoryOSCronLaneDef(
        key="v3_journal_sweep",
        raw_script="memory_os_v3_journal_sweep.py",
        lane_id="v3_journal_sweep",
        helper_kind="local_helper",
        group_key="tick_daily",
        due_interval_minutes=1440,
    ),
    MemoryOSCronLaneDef(
        key="working_cleanup",
        raw_script="cleanup_expired_working.py",
        lane_id="working_cleanup",
        helper_kind="local_helper",
        group_key="tick_daily",
        due_interval_minutes=10080,
    ),
    MemoryOSCronLaneDef(
        key="hindsight_advisory_digest",
        raw_script="memory_os_hindsight_advisory_digest.py",
        lane_id="hindsight_advisory_digest",
        helper_kind="local_helper",
        group_key="tick_daily",
        due_interval_minutes=10080,
    ),
    # Single-member groups
    MemoryOSCronLaneDef(
        key="owner_review_digest",
        raw_script="memory_os_owner_review_digest.py",
        lane_id="owner_review_digest_render",
        helper_kind="owner_channel_render",
        group_key="owner_review_digest",
        due_interval_minutes=1440,
        timeout_seconds=600,
    ),
    MemoryOSCronLaneDef(
        key="memory_sources_feedback_request",
        raw_script="memory_os_memory_sources_feedback_prompt.py",
        lane_id="memory_sources_feedback_request",
        helper_kind="owner_channel_render",
        group_key="memory_sources_feedback_request",
        due_interval_minutes=1440,
        timeout_seconds=600,
    ),
    MemoryOSCronLaneDef(
        key="expression_feedback_request",
        raw_script="memory_os_expression_feedback_prompt.py",
        lane_id="expression_feedback_request",
        helper_kind="owner_channel_render",
        group_key="expression_feedback_request",
        due_interval_minutes=10080,
        timeout_seconds=600,
    ),
    MemoryOSCronLaneDef(
        key="full_monitor_refresh",
        raw_script="memory_os_full_monitor_refresh.py",
        lane_id="full_monitor_refresh",
        helper_kind="read_only_probe",
        group_key="full_monitor_refresh",
        due_interval_minutes=1440,
        timeout_seconds=900,
    ),
    MemoryOSCronLaneDef(
        key="module_cadence_report",
        raw_script="memory_os_module_cadence_report_cron.py",
        lane_id="module_cadence_report",
        helper_kind="local_helper",
        group_key="module_cadence_report",
        due_interval_minutes=360,
    ),
)


def _build_specs() -> tuple[MemoryOSCronSpec, ...]:
    groups = {group.key: group for group in MEMORY_OS_CRON_GROUPS}
    missing = sorted({lane.group_key for lane in MEMORY_OS_CRON_LANES} - set(groups))
    if missing:
        raise ValueError(f"cron lanes reference unknown group keys: {missing}")
    lanes_by_key = {lane.key: lane for lane in MEMORY_OS_CRON_LANES}
    for group in MEMORY_OS_CRON_GROUPS:
        unknown = sorted(set(group.member_keys) - set(lanes_by_key))
        if unknown:
            raise ValueError(f"cron group {group.key} lists unknown member keys: {unknown}")
        for member in group.member_keys:
            if lanes_by_key[member].group_key != group.key:
                raise ValueError(
                    f"cron lane {member} claims group {lanes_by_key[member].group_key} "
                    f"but is listed under {group.key}"
                )
    specs: list[MemoryOSCronSpec] = []
    for lane in MEMORY_OS_CRON_LANES:
        group = groups[lane.group_key]
        if lane.key not in group.member_keys:
            raise ValueError(f"cron lane {lane.key} is not listed in group {group.key} member_keys")
        specs.append(
            MemoryOSCronSpec(
                key=lane.key,
                name=group.name,
                raw_script=lane.raw_script,
                wrapper_script=group.wrapper_script,
                lane_id=lane.lane_id,
                helper_kind=lane.helper_kind,
                schedule_arg=group.schedule_arg,
                deliver_role=group.deliver_role,
                prompt_ref=group.prompt_ref,
                no_agent=group.no_agent,
                requires_boundary_report=lane.requires_boundary_report,
                group_key=group.key,
                due_policy=lane.due_policy,
                due_interval_minutes=lane.due_interval_minutes,
                calendar_anchor=lane.calendar_anchor,
                timeout_seconds=lane.timeout_seconds,
            )
        )
    return tuple(specs)


MEMORY_OS_CRON_SPECS: tuple[MemoryOSCronSpec, ...] = _build_specs()


def memory_os_cron_specs() -> tuple[MemoryOSCronSpec, ...]:
    return MEMORY_OS_CRON_SPECS


def memory_os_cron_groups() -> tuple[MemoryOSCronGroupSpec, ...]:
    return MEMORY_OS_CRON_GROUPS


def memory_os_cron_group_by_key(key: str) -> MemoryOSCronGroupSpec | None:
    for group in MEMORY_OS_CRON_GROUPS:
        if group.key == key:
            return group
    return None


def memory_os_cron_group_by_name(name: str) -> MemoryOSCronGroupSpec | None:
    for group in MEMORY_OS_CRON_GROUPS:
        if group.name == name:
            return group
    return None


def memory_os_cron_spec_by_key(key: str) -> MemoryOSCronSpec | None:
    for spec in MEMORY_OS_CRON_SPECS:
        if spec.key == key:
            return spec
    return None


def memory_os_cron_specs_by_name(name: str) -> tuple[MemoryOSCronSpec, ...]:
    """All lanes scheduled by the Hermes job called ``name``."""
    return tuple(spec for spec in MEMORY_OS_CRON_SPECS if spec.name == name)


def memory_os_cron_spec_by_name(name: str) -> MemoryOSCronSpec | None:
    """First lane scheduled by ``name``.

    Kept for callers that only need a representative spec (wrapper script,
    deliver role, schedule arg -- all group-level values shared by every
    member).  Use :func:`memory_os_cron_specs_by_name` when the full member
    list matters.
    """
    matches = memory_os_cron_specs_by_name(name)
    return matches[0] if matches else None


def cron_registry_snapshot(
    *,
    source_commit: str = "",
    specs: tuple[MemoryOSCronSpec, ...] | None = None,
    groups: tuple[MemoryOSCronGroupSpec, ...] | None = None,
) -> dict[str, Any]:
    selected_specs = specs if specs is not None else MEMORY_OS_CRON_SPECS
    if groups is not None:
        selected_groups = groups
    else:
        selected_groups = groups_for_specs(selected_specs)
    return {
        "schema_version": "memory-os.cron_registry.v1",
        "source_commit": str(source_commit or ""),
        "specs": [spec.to_json() for spec in selected_specs],
        "groups": [group.to_json() for group in selected_groups],
    }


def write_cron_registry_snapshot(
    path: Path,
    *,
    source_commit: str = "",
    specs: tuple[MemoryOSCronSpec, ...] | None = None,
    groups: tuple[MemoryOSCronGroupSpec, ...] | None = None,
) -> dict[str, Any]:
    snapshot = cron_registry_snapshot(source_commit=source_commit, specs=specs, groups=groups)
    # Atomic replace: group resolution prefers this snapshot over the
    # compiled-in registry, so a torn write here would silently break
    # member resolution on the deployed host.
    from .jsonl_io import write_json_atomic

    write_json_atomic(path, snapshot)
    return snapshot


def specs_from_snapshot(value: dict[str, Any]) -> tuple[MemoryOSCronSpec, ...]:
    specs = []
    for item in value.get("specs", []) if isinstance(value.get("specs"), list) else []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "")
        # v0 snapshots predate the lane/group split and carry no due metadata.
        # Fall back to the compiled-in lane definition so an old snapshot can
        # never silently yield a 0-minute interval -- which would make every
        # lane permanently "due" in the tick runner and permanently stale in
        # the monitor.
        fallback = memory_os_cron_spec_by_key(key)
        try:
            due_interval = int(item.get("due_interval_minutes") or 0)
        except (TypeError, ValueError):
            due_interval = 0
        if due_interval <= 0:
            due_interval = fallback.due_interval_minutes if fallback else 1440
        try:
            timeout_seconds = int(item.get("timeout_seconds") or 0)
        except (TypeError, ValueError):
            timeout_seconds = 0
        if timeout_seconds <= 0:
            timeout_seconds = fallback.timeout_seconds if fallback else 300
        due_policy = str(item.get("due_policy") or "") or (fallback.due_policy if fallback else DUE_POLICY_INTERVAL)
        calendar_anchor = str(item.get("calendar_anchor") or "") or (fallback.calendar_anchor if fallback else "")
        specs.append(
            MemoryOSCronSpec(
                key=key,
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
                group_key=str(item.get("group_key") or "") or (fallback.group_key if fallback else ""),
                due_policy=due_policy,
                due_interval_minutes=due_interval,
                calendar_anchor=calendar_anchor,
                timeout_seconds=timeout_seconds,
            )
        )
    return tuple(spec for spec in specs if spec.key and spec.name and spec.raw_script and spec.wrapper_script)


def groups_from_snapshot(value: dict[str, Any]) -> tuple[MemoryOSCronGroupSpec, ...]:
    """Group specs recorded in an installed snapshot.

    A v0 snapshot has no ``groups`` array; callers fall back to
    :func:`groups_for_specs` over its ``specs``.
    """
    groups = []
    for item in value.get("groups", []) if isinstance(value.get("groups"), list) else []:
        if not isinstance(item, dict):
            continue
        members = item.get("member_keys")
        groups.append(
            MemoryOSCronGroupSpec(
                key=str(item.get("key") or ""),
                name=str(item.get("name") or ""),
                wrapper_script=str(item.get("wrapper_script") or ""),
                schedule_arg=str(item.get("schedule_arg") or ""),
                default_schedule=str(item.get("default_schedule") or ""),
                deliver_role=str(item.get("deliver_role") or "local"),
                prompt_ref=str(item.get("prompt_ref") or "empty"),
                no_agent=bool(item.get("no_agent")),
                member_keys=tuple(str(member) for member in members if str(member)) if isinstance(members, list) else (),
            )
        )
    return tuple(group for group in groups if group.key and group.name and group.wrapper_script)


def lane_disable_state_path(hermes_home: Path | str) -> Path:
    """Owner-controlled per-lane disable list.

    Before consolidation an owner stopped a single lane by disabling its
    dedicated Hermes cron job, and the monitor read ``enabled is False`` off
    that job.  Group ticks make the Hermes job granularity coarser than the
    lane, so that control is restored here instead: the tick runner skips a
    listed lane, and the monitor classifies it ``disabled`` rather than
    reporting missing completion evidence.
    """
    return Path(hermes_home) / "memory-os" / "system" / "cron_lane_disabled.json"


LANE_DISABLE_STATE_SCHEMA_VERSION = "memory-os.cron_lane_disabled.v1"
LANE_DISABLE_AUDIT_FIELDS = ("reason", "actor", "disabled_at")


def read_lane_disable_records(hermes_home: Path | str) -> dict[str, dict[str, str]]:
    """Disabled lane keys mapped to whatever audit detail the owner recorded.

    Three on-disk shapes are accepted, oldest first::

        ["lane_key", ...]                                   # pre-audit bare list
        {"disabled_lane_keys": ["lane_key", ...]}           # pre-audit wrapper
        {"lanes": {"lane_key": {"reason": ..., "actor": ..., "disabled_at": ...}}}

    The first two carry no reason at all, so their records come back with empty
    audit fields; that is what lets the monitor separate "the owner disabled
    this lane, and here is why" from an undocumented stop.  A corrupt or
    unreadable file disables nothing -- that failure direction keeps governed
    lanes running rather than silently starving them.
    """
    path = lane_disable_state_path(hermes_home)
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    entries: Any
    if isinstance(loaded, dict):
        lanes = loaded.get("lanes")
        if isinstance(lanes, dict):
            records: dict[str, dict[str, str]] = {}
            for key, value in lanes.items():
                lane_key = str(key)
                if not lane_key:
                    continue
                detail = value if isinstance(value, dict) else {}
                records[lane_key] = {
                    field: str(detail.get(field) or "") for field in LANE_DISABLE_AUDIT_FIELDS
                }
            return records
        entries = loaded.get("disabled_lane_keys")
    else:
        entries = loaded
    if not isinstance(entries, list):
        return {}
    return {
        str(entry): {field: "" for field in LANE_DISABLE_AUDIT_FIELDS}
        for entry in entries
        if str(entry)
    }


def build_lane_disable_state(records: dict[str, dict[str, str]]) -> dict[str, Any]:
    """The v1 document shape, so an operator writing this file by hand produces
    something the runtime and the monitor both already parse."""
    return {
        "schema_version": LANE_DISABLE_STATE_SCHEMA_VERSION,
        "lanes": {
            str(key): {field: str((detail or {}).get(field) or "") for field in LANE_DISABLE_AUDIT_FIELDS}
            for key, detail in records.items()
            if str(key)
        },
    }


def read_disabled_lane_keys(hermes_home: Path | str) -> frozenset[str]:
    """Lane keys the owner has disabled. Unreadable/malformed state disables
    nothing -- a corrupt file must never silently stop governed lanes."""
    return frozenset(read_lane_disable_records(hermes_home))


def groups_for_specs(specs: tuple[MemoryOSCronSpec, ...]) -> tuple[MemoryOSCronGroupSpec, ...]:
    """Group specs covering ``specs``, with member lists narrowed to them.

    Used by onboarding so a profile that installs a subset of lanes creates a
    group job whose member list matches what is actually installed (the
    excluded members must not be run by the tick).
    """
    members_by_name: dict[str, set[str]] = {}
    for spec in specs:
        members_by_name.setdefault(spec.name, set()).add(spec.key)
    built: list[MemoryOSCronGroupSpec] = []
    for group in MEMORY_OS_CRON_GROUPS:
        members = members_by_name.get(group.name)
        if not members:
            continue
        ordered = tuple(key for key in group.member_keys if key in members)
        built.append(
            MemoryOSCronGroupSpec(
                key=group.key,
                name=group.name,
                wrapper_script=group.wrapper_script,
                schedule_arg=group.schedule_arg,
                default_schedule=group.default_schedule,
                deliver_role=group.deliver_role,
                prompt_ref=group.prompt_ref,
                no_agent=group.no_agent,
                member_keys=ordered,
            )
        )
    return tuple(built)
