import json

from plugins.memory.memory_os.cron_registry import (
    cron_registry_snapshot,
    memory_os_cron_spec_by_key,
    memory_os_cron_specs,
    specs_from_snapshot,
    write_cron_registry_snapshot,
)


def test_hindsight_health_probe_is_registered_as_read_only_self_wrapper():
    spec = memory_os_cron_spec_by_key("hindsight_health_probe")

    assert spec is not None
    assert spec.name == "memory-os-hindsight-health-probe"
    assert spec.raw_script == "memory_os_hindsight_health_probe.py"
    assert spec.wrapper_script == spec.raw_script
    assert spec.lane_id == "hindsight_health_probe"
    assert spec.schedule_arg == "hindsight_health_probe_schedule"
    assert spec.deliver_role == "local"
    assert spec.no_agent is True
    assert spec.requires_boundary_report is False


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
    assert loaded["schema_version"] == "memory-os.cron_registry.v0"
    assert loaded["source_commit"] == "abc123"
    assert [spec.key for spec in restored] == [spec.key for spec in memory_os_cron_specs()]
    assert all(
        spec.wrapper_script.startswith("memory_os_cron_")
        or spec.wrapper_script == spec.raw_script  # self-wrapping no_agent scripts
        for spec in restored
    )
    assert all(spec.schedule_arg for spec in restored)
    assert all(spec.prompt_ref for spec in restored)


def test_cron_registry_snapshot_can_write_active_subset(tmp_path):
    snapshot_path = tmp_path / "memory-os" / "system" / "memory_os_cron_registry.json"
    subset = tuple(spec for spec in memory_os_cron_specs() if spec.key in {"owner_review_digest", "proposal_followups_opsgate"})

    written = write_cron_registry_snapshot(snapshot_path, specs=subset)
    loaded = json.loads(snapshot_path.read_text(encoding="utf-8"))
    restored = specs_from_snapshot(loaded)

    assert written == cron_registry_snapshot(specs=subset)
    assert [spec.key for spec in restored] == ["owner_review_digest", "proposal_followups_opsgate"]
    assert [spec.key for spec in memory_os_cron_specs()] != [spec.key for spec in restored]
