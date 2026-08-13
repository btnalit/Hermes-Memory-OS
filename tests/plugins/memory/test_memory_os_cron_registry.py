import json

from plugins.memory.memory_os.cron_registry import (
    LANE_DISABLE_STATE_SCHEMA_VERSION,
    LEGACY_PER_LANE_CRON_JOB_NAMES,
    build_lane_disable_state,
    cron_registry_snapshot,
    groups_from_snapshot,
    memory_os_cron_groups,
    memory_os_cron_spec_by_key,
    memory_os_cron_specs,
    read_disabled_lane_keys,
    read_lane_disable_records,
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
    """The point of the consolidation: 22 lanes -> 8 Hermes jobs.

    Asserted on the DERIVED job count rather than a hand-typed job list, so a
    newly registered lane joins an existing tick instead of silently adding a
    cron job. History: 20 lanes at consolidation; +clearance_cycle activated
    and +state_source_mirror registered on 2026-08-06 (both ride existing
    ticks — the 8-job invariant is the one that must never move silently).
    """
    from plugins.memory.memory_os.cron_registry import ACTIVE_CLOSURE_EXCLUDED_CRON_KEYS

    active = [
        spec for spec in memory_os_cron_specs()
        if spec.key not in ACTIVE_CLOSURE_EXCLUDED_CRON_KEYS
    ]

    assert len(active) == 22
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


def _cron_minutes(field, lo, hi):
    if field == "*":
        return set(range(lo, hi + 1))
    out = set()
    for part in field.split(","):
        if part.startswith("*/"):
            out |= set(range(lo, hi + 1, int(part[2:])))
        else:
            out.add(int(part))
    return out


def test_no_two_group_jobs_start_in_the_same_minute():
    """The consolidation exists to remove same-minute contention on
    execution_gate_index.json. Aligned cron expressions (*/15, */30,
    0 * * * *) all fire at :00 and put three group runners in the same
    minute again -- which is exactly what happened on the first production
    deployment, where three ticks fired at 20:00:56. Minutes are staggered;
    this pins that.
    """
    from collections import Counter

    fires = Counter()
    for group in memory_os_cron_groups():
        minute, hour, day_of_month, month, day_of_week = group.default_schedule.split()
        if day_of_week != "*" or day_of_month != "*" or month != "*":
            continue  # weekly/monthly jobs are counted separately below
        for h in _cron_minutes(hour, 0, 23):
            for m in _cron_minutes(minute, 0, 59):
                fires[(h, m)] += 1

    collisions = {slot: count for slot, count in fires.items() if count > 1}
    assert not collisions, f"group jobs share a start minute: {sorted(collisions)}"


def test_every_tick_fires_at_least_as_often_as_its_fastest_installed_lane():
    """Staggering moves minutes, never rates.

    Compared against the lanes active-closure actually INSTALLS, not every
    registered lane: clearance_cycle wants 10min but its activation is
    deferred, so tick-governance running every 30min is correct today. If
    clearance_cycle is ever switched on without speeding that tick up, this
    fails -- which is the intended tripwire.
    """
    excluded = {"module_cadence_report", "clearance_cycle"}
    for group in memory_os_cron_groups():
        minute, hour, _, _, day_of_week = group.default_schedule.split()
        if day_of_week != "*" or hour != "*":
            continue  # daily/weekly ticks are gated per lane, not per minute
        members = [
            spec
            for spec in memory_os_cron_specs()
            if spec.group_key == group.key and spec.key not in excluded
        ]
        if not members:
            continue
        slots = sorted(_cron_minutes(minute, 0, 59))
        assert slots, group.name
        tick_interval = 60 // len(slots)
        fastest = min(spec.due_interval_minutes for spec in members)
        assert tick_interval <= fastest, (
            f"{group.name} fires every {tick_interval}min but its fastest "
            f"installed member needs every {fastest}min"
        )


# ── per-lane disable: audit trail ─────────────────────────────────────


def _write_disable_file(home, payload):
    path = home / "memory-os" / "system" / "cron_lane_disabled.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) if not isinstance(payload, str) else payload, encoding="utf-8")
    return path


def test_lane_disable_reads_all_three_on_disk_shapes(tmp_path):
    """Adding audit fields must not orphan hosts already carrying the older
    shapes -- both pre-audit forms keep disabling their lanes, they simply
    report no reason."""
    bare = tmp_path / "bare"
    _write_disable_file(bare, ["alpha"])
    wrapper = tmp_path / "wrapper"
    _write_disable_file(wrapper, {"disabled_lane_keys": ["alpha"]})
    audited = tmp_path / "audited"
    _write_disable_file(
        audited,
        {
            "schema_version": LANE_DISABLE_STATE_SCHEMA_VERSION,
            "lanes": {"alpha": {"reason": "retired", "actor": "owner", "disabled_at": "2026-08-02T00:00:00Z"}},
        },
    )

    assert read_disabled_lane_keys(bare) == frozenset({"alpha"})
    assert read_disabled_lane_keys(wrapper) == frozenset({"alpha"})
    assert read_disabled_lane_keys(audited) == frozenset({"alpha"})

    assert read_lane_disable_records(bare)["alpha"]["reason"] == ""
    assert read_lane_disable_records(wrapper)["alpha"]["reason"] == ""
    audited_record = read_lane_disable_records(audited)["alpha"]
    assert audited_record["reason"] == "retired"
    assert audited_record["actor"] == "owner"
    assert audited_record["disabled_at"] == "2026-08-02T00:00:00Z"


def test_corrupt_disable_file_disables_nothing(tmp_path):
    """Load-bearing failure direction: a corrupt file must never silently stop
    governed lanes."""
    home = tmp_path / "home"
    _write_disable_file(home, "{ not json at all")

    assert read_disabled_lane_keys(home) == frozenset()
    assert read_lane_disable_records(home) == {}


def test_missing_disable_file_disables_nothing(tmp_path):
    assert read_disabled_lane_keys(tmp_path / "absent") == frozenset()
    assert read_lane_disable_records(tmp_path / "absent") == {}


def test_build_lane_disable_state_round_trips(tmp_path):
    """An operator writing this file by hand should produce exactly what the
    runtime and monitor already parse."""
    home = tmp_path / "home"
    document = build_lane_disable_state(
        {"expression_feedback_request": {"reason": "retired with右脑表达 lanes", "actor": "owner", "disabled_at": "2026-08-02T00:00:00Z"}}
    )
    _write_disable_file(home, document)

    assert document["schema_version"] == LANE_DISABLE_STATE_SCHEMA_VERSION
    records = read_lane_disable_records(home)
    assert records["expression_feedback_request"]["reason"] == "retired with右脑表达 lanes"
    assert read_disabled_lane_keys(home) == frozenset({"expression_feedback_request"})


# ── Lane last-run evidence census ("Completion Is Not Output") ──────────────
#
# Both directions are pinned, like the exposure vocabulary guard: every
# registered lane must be triaged, and no census entry may name a lane that
# does not exist.  A new lane therefore cannot ship without declaring how a
# reader distinguishes "no eligible input" from "processing failed".


def test_every_cron_lane_declares_last_run_evidence():
    from plugins.memory.memory_os.cron_registry import (
        LANE_LAST_RUN_EVIDENCE,
        LANE_LAST_RUN_EVIDENCE_KINDS,
        MEMORY_OS_CRON_LANES,
    )

    lane_ids = {lane.lane_id for lane in MEMORY_OS_CRON_LANES}

    missing = sorted(lane_ids - set(LANE_LAST_RUN_EVIDENCE))
    assert not missing, f"lanes registered without last-run evidence triage: {missing}"

    orphaned = sorted(set(LANE_LAST_RUN_EVIDENCE) - lane_ids)
    assert not orphaned, f"census names lanes that are not registered: {orphaned}"

    unknown_kinds = {
        lane_id: kind
        for lane_id, kind in LANE_LAST_RUN_EVIDENCE.items()
        if kind not in LANE_LAST_RUN_EVIDENCE_KINDS
    }
    assert not unknown_kinds, f"census uses undefined evidence kinds: {unknown_kinds}"


def test_lane_last_run_declarations_are_actually_wired():
    """Source-scan guard: a lane declared 'lane_last_run' must really call
    record_lane_last_run with its own lane_id — a census that nothing
    satisfies would be green-by-vocabulary, the exact drift this table
    exists to prevent."""
    from pathlib import Path

    from plugins.memory.memory_os.cron_registry import (
        LANE_LAST_RUN_EVIDENCE,
        MEMORY_OS_CRON_LANES,
    )

    scripts_dir = Path(__file__).resolve().parents[3] / "scripts"
    unwired: list[str] = []
    for lane in MEMORY_OS_CRON_LANES:
        if LANE_LAST_RUN_EVIDENCE.get(lane.lane_id) != "lane_last_run":
            continue
        source = (scripts_dir / lane.raw_script).read_text(encoding="utf-8")
        if "record_lane_last_run" not in source or f'"{lane.lane_id}"' not in source:
            unwired.append(lane.lane_id)
    assert not unwired, f"lanes declared lane_last_run but not wired: {unwired}"
