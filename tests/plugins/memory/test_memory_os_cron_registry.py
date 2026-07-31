import json

from plugins.memory.memory_os.cron_registry import (
    LEGACY_PER_LANE_CRON_JOB_NAMES,
    cron_registry_snapshot,
    groups_from_snapshot,
    memory_os_cron_groups,
    memory_os_cron_spec_by_key,
    memory_os_cron_specs,
    specs_from_snapshot,
    write_cron_registry_snapshot,
)


def test_hindsight_health_probe_keeps_read_only_lane_identity_inside_tick_group():
    """The lane's governance identity survives cron-group consolidation.

    Its Hermes job is now the shared evidence tick, but the ExecutionGate
    identity (lane_id, risk class, boundary contract) must be untouched --
    that is the whole premise of merging only the scheduling surface.
    """
    spec = memory_os_cron_spec_by_key("hindsight_health_probe")

    assert spec is not None
    assert spec.raw_script == "memory_os_hindsight_health_probe.py"
    assert spec.lane_id == "hindsight_health_probe"
    assert spec.helper_kind == "read_only_probe"
    assert spec.requires_boundary_report is False
    # Scheduling surface is the group's.
    assert spec.group_key == "tick_evidence"
    assert spec.name == "memory-os-tick-evidence"
    assert spec.wrapper_script == "memory_os_cron_tick_evidence.py"
    assert spec.schedule_arg == "tick_evidence_schedule"
    assert spec.deliver_role == "local"
    assert spec.no_agent is True
    # Its original hourly cadence is preserved by due gating, not by cron.
    assert spec.due_interval_minutes == 60


def test_full_monitor_refresh_is_registered_as_read_only_self_wrapper():
    spec = memory_os_cron_spec_by_key("full_monitor_refresh")

    assert spec is not None
    assert spec.name == "memory-os-full-monitor-refresh"
    assert spec.raw_script == "memory_os_full_monitor_refresh.py"
    assert spec.wrapper_script == spec.raw_script
    assert spec.lane_id == "full_monitor_refresh"
    assert spec.schedule_arg == "full_monitor_refresh_schedule"
    assert spec.deliver_role == "owner"
    assert spec.no_agent is True
    assert spec.requires_boundary_report is False


def test_cron_registry_snapshot_round_trips_all_specs(tmp_path):
    snapshot_path = tmp_path / "memory-os" / "system" / "memory_os_cron_registry.json"

    written = write_cron_registry_snapshot(snapshot_path, source_commit="abc123")
    loaded = json.loads(snapshot_path.read_text(encoding="utf-8"))
    restored = specs_from_snapshot(loaded)

    assert written == cron_registry_snapshot(source_commit="abc123")
    assert loaded["schema_version"] == "memory-os.cron_registry.v1"
    assert loaded["source_commit"] == "abc123"
    assert [spec.key for spec in restored] == [spec.key for spec in memory_os_cron_specs()]
    assert all(
        spec.wrapper_script.startswith("memory_os_cron_")
        or spec.wrapper_script == spec.raw_script  # self-wrapping no_agent scripts
        for spec in restored
    )
    assert all(spec.schedule_arg for spec in restored)
    assert all(spec.prompt_ref for spec in restored)
    # Due metadata must survive the round trip: the monitor derives its
    # completion-freshness window from due_interval_minutes, and a lost/zeroed
    # value would mark every lane permanently stale.
    assert all(spec.due_interval_minutes > 0 for spec in restored)
    assert all(spec.timeout_seconds > 0 for spec in restored)
    assert {spec.key: spec.due_interval_minutes for spec in restored} == {
        spec.key: spec.due_interval_minutes for spec in memory_os_cron_specs()
    }


def test_snapshot_records_groups_covering_every_installed_lane(tmp_path):
    snapshot_path = tmp_path / "memory-os" / "system" / "memory_os_cron_registry.json"

    write_cron_registry_snapshot(snapshot_path)
    loaded = json.loads(snapshot_path.read_text(encoding="utf-8"))
    groups = groups_from_snapshot(loaded)

    assert groups, "snapshot must carry the group table the tick runner reads"
    grouped_members = {key for group in groups for key in group.member_keys}
    assert grouped_members == {spec.key for spec in memory_os_cron_specs()}
    # Every lane's job name must be its group's name.
    names = {group.name for group in groups}
    assert {spec.name for spec in memory_os_cron_specs()} == names


def test_specs_from_v0_snapshot_backfills_due_metadata(tmp_path):
    """A pre-consolidation snapshot has no due metadata.

    Without the compiled-in fallback these lanes would restore with a
    0-minute interval, which makes them permanently 'due' in the tick runner
    and permanently 'stale' in the monitor.
    """
    legacy = {
        "schema_version": "memory-os.cron_registry.v0",
        "source_commit": "old",
        "specs": [
            {
                "key": "working_cleanup",
                "name": "memory-os-working-cleanup",
                "raw_script": "cleanup_expired_working.py",
                "wrapper_script": "memory_os_cron_working_cleanup_gate.py",
                "lane_id": "working_cleanup",
                "helper_kind": "local_helper",
                "schedule_arg": "working_cleanup_schedule",
                "deliver_role": "local",
                "prompt_ref": "empty",
                "no_agent": True,
                "requires_boundary_report": False,
            }
        ],
    }

    restored = specs_from_snapshot(legacy)

    assert len(restored) == 1
    assert restored[0].due_interval_minutes == 10080
    assert restored[0].timeout_seconds > 0
    assert restored[0].group_key == "tick_daily"


def test_cron_registry_snapshot_can_write_active_subset(tmp_path):
    snapshot_path = tmp_path / "memory-os" / "system" / "memory_os_cron_registry.json"
    subset = tuple(spec for spec in memory_os_cron_specs() if spec.key in {"owner_review_digest", "proposal_followups_opsgate"})

    written = write_cron_registry_snapshot(snapshot_path, specs=subset)
    loaded = json.loads(snapshot_path.read_text(encoding="utf-8"))
    restored = specs_from_snapshot(loaded)

    assert written == cron_registry_snapshot(specs=subset)
    # Order follows the registry's lane table, which is incidental here; the
    # contract is the SET of installed lanes.
    assert sorted(spec.key for spec in restored) == ["owner_review_digest", "proposal_followups_opsgate"]
    assert [spec.key for spec in memory_os_cron_specs()] != [spec.key for spec in restored]


def test_subset_snapshot_narrows_group_membership_to_installed_lanes(tmp_path):
    """A profile-excluded lane must not appear in its group's member list.

    The tick runner drives execution off the snapshot's member_keys, so a
    deferred lane left in that list would start running on the next tick --
    exactly the silent activation clearance_cycle is being held back from.
    """
    snapshot_path = tmp_path / "memory-os" / "system" / "memory_os_cron_registry.json"
    subset = tuple(spec for spec in memory_os_cron_specs() if spec.key == "proposal_followups_opsgate")

    write_cron_registry_snapshot(snapshot_path, specs=subset)
    groups = groups_from_snapshot(json.loads(snapshot_path.read_text(encoding="utf-8")))

    governance = [group for group in groups if group.key == "tick_governance"]
    assert len(governance) == 1
    assert governance[0].member_keys == ("proposal_followups_opsgate",)
    assert "clearance_cycle" not in governance[0].member_keys


def test_active_closure_profile_installs_eight_hermes_cron_jobs():
    """The point of the consolidation: 19 lanes -> 8 Hermes jobs.

    Asserted on the DERIVED job count rather than a hand-typed job list, so a
    newly registered lane joins an existing tick instead of silently adding a
    cron job.
    """
    excluded = {"module_cadence_report", "clearance_cycle"}
    active = [spec for spec in memory_os_cron_specs() if spec.key not in excluded]

    assert len(active) == 19
    assert len({spec.name for spec in active}) == 8


def test_every_lane_resolves_to_a_group_that_lists_it():
    groups = {group.key: group for group in memory_os_cron_groups()}

    for spec in memory_os_cron_specs():
        assert spec.group_key in groups, f"{spec.key} has no group"
        assert spec.key in groups[spec.group_key].member_keys
        assert spec.name == groups[spec.group_key].name
        assert spec.wrapper_script == groups[spec.group_key].wrapper_script


def test_legacy_per_lane_job_names_never_collide_with_active_group_jobs():
    """A legacy name that is also a live group name would get paused as
    superseded during onboarding, disabling a job that is still in use."""
    active_names = {spec.name for spec in memory_os_cron_specs()}

    assert not (LEGACY_PER_LANE_CRON_JOB_NAMES & active_names)


def test_date_partitioned_lane_uses_calendar_due_policy():
    """v3_seed_evidence emits one record per natural_date and reports
    consecutive_valid_day_count; elapsed gating could drift it across a UTC
    day boundary and skip or double-count a day."""
    spec = memory_os_cron_spec_by_key("v3_seed_evidence")

    assert spec is not None
    assert spec.due_policy == "calendar"
    assert spec.calendar_anchor == "00:00"


def test_owner_facing_lanes_keep_dedicated_jobs():
    """Owner messages must not be fused into a shared tick.

    Each renders a distinct message through its own agent prompt and deliver
    channel, so a shared tick would merge separate owner messages.
    """
    groups = {group.key: group for group in memory_os_cron_groups()}

    for key in (
        "owner_review_digest",
        "memory_sources_feedback_request",
        "expression_feedback_request",
        "full_monitor_refresh",
    ):
        spec = memory_os_cron_spec_by_key(key)
        assert spec is not None, key
        assert groups[spec.group_key].member_keys == (key,), key
