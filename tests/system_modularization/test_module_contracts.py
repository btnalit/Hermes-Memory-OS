from datetime import datetime, timedelta, timezone

import pytest

from plugins.system.bus import ModuleBus
from plugins.system.contracts import ModuleManifest, ManifestValidationError
from plugins.system.scheduler import ScheduleCoordinator


def _manifest_dict():
    return {
        "name": "wandering_mind",
        "kind": "cognition",
        "version": "0.1.0",
        "layer": "L2",
        "dependencies": {
            "required": ["memory_os >=0.1.0", "scheduler"],
            "optional": ["household_digest"],
        },
        "provides": {
            "commands": ["status", "doctor", "run-once"],
            "schedules": ["weekly_wandering"],
            "reads": ["memory_os.events.summary"],
            "writes": ["memory_os.events", "memory_os.crystallized_candidates"],
        },
        "defaults": {
            "enabled": False,
            "delivery_mode": "no-send",
            "profile_scope": "per-profile",
        },
        "memory_os_compat": {
            "min_version": "0.1.0",
            "max_version": "0.2.x",
            "schema_versions": {
                "event": ["memory-os.event.v0", "memory-os.event.v1"],
                "working": ["memory-os.working.v0"],
                "crystallized": ["memory-os.crystallized.v0"],
            },
        },
    }


def test_module_manifest_parses_lifecycle_and_memory_os_compatibility():
    manifest = ModuleManifest.from_dict(_manifest_dict())

    assert manifest.name == "wandering_mind"
    assert manifest.required_dependencies == ("memory_os >=0.1.0", "scheduler")
    assert manifest.default_delivery_mode == "no-send"
    assert manifest.can_read_schema("event", "memory-os.event.v1") is True
    assert manifest.can_read_schema("event", "memory-os.event.v2") is False

    report = manifest.compatibility_report(
        memory_os_version="0.1.5",
        schema_versions={
            "event": "memory-os.event.v1",
            "working": "memory-os.working.v0",
            "crystallized": "memory-os.crystallized.v0",
        },
    )

    assert report.status == "compatible"
    assert report.reasons == ()


def test_module_manifest_rejects_missing_required_sections():
    raw = _manifest_dict()
    raw.pop("memory_os_compat")

    with pytest.raises(ManifestValidationError, match="memory_os_compat"):
        ModuleManifest.from_dict(raw)


def test_module_manifest_reports_incompatible_memory_os_version():
    manifest = ModuleManifest.from_dict(_manifest_dict())

    report = manifest.compatibility_report(
        memory_os_version="0.3.0",
        schema_versions={"event": "memory-os.event.v1"},
    )

    assert report.status == "incompatible"
    assert "memory_os_version" in report.reasons[0]


def test_module_manifest_reports_read_only_for_unknown_schema_versions():
    manifest = ModuleManifest.from_dict(_manifest_dict())

    report = manifest.compatibility_report(
        memory_os_version="0.1.5",
        schema_versions={
            "event": "memory-os.event.v2",
            "working": "memory-os.working.v0",
        },
    )

    assert report.status == "read_only_unknown_schema"
    assert report.read_only_schema_kinds == ("event",)


def test_module_bus_persists_profile_local_events_without_private_bodies(tmp_path):
    bus = ModuleBus(tmp_path / "state" / "module_bus.jsonl")

    event = bus.publish(
        "module.health_changed",
        profile="main",
        module="inner_drive",
        payload={"state": "degraded", "reason": "lock_contention"},
    )

    entries = bus.read_events(profile="main")
    assert entries == [event]
    assert event.schema_version == "hermes.module_bus.v0"
    assert event.payload == {"state": "degraded", "reason": "lock_contention"}
    assert "private_body" not in event.to_dict()


def test_schedule_coordinator_uses_ttl_locks_and_reports_contention(tmp_path):
    now = datetime(2026, 5, 20, 12, 0, tzinfo=timezone.utc)
    coordinator = ScheduleCoordinator(tmp_path / "runtime" / "locks")

    first = coordinator.acquire_lock(
        "memory_os.heartbeat",
        owner="inner_drive",
        ttl_seconds=60,
        now=now,
    )
    second = coordinator.acquire_lock(
        "memory_os.heartbeat",
        owner="wandering_mind",
        ttl_seconds=60,
        now=now + timedelta(seconds=10),
    )
    third = coordinator.acquire_lock(
        "memory_os.heartbeat",
        owner="wandering_mind",
        ttl_seconds=60,
        now=now + timedelta(seconds=61),
    )

    assert first.acquired is True
    assert second.acquired is False
    assert second.status == "held"
    assert second.lock_contention_count == 1
    assert third.acquired is True
    assert third.status == "expired_replaced"
