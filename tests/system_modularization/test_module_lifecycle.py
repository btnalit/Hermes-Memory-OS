import json

import pytest

from plugins.system.lifecycle import LifecycleError, ModuleLifecycle


def _manifest(name: str = "mailbox"):
    return {
        "name": name,
        "kind": "messaging",
        "version": "0.1.0",
        "layer": "L4",
        "dependencies": {
            "required": ["memory_os >=0.1.0", "scheduler"],
            "optional": ["delivery_sink"],
        },
        "provides": {
            "commands": ["status", "doctor", "run-once"],
            "schedules": [],
            "reads": ["memory_os.events.summary"],
            "writes": ["memory_os.events"],
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
                "event": ["memory-os.event.v0"],
                "working": ["memory-os.working.v0"],
                "crystallized": ["memory-os.crystallized.v0"],
            },
        },
    }


def test_lifecycle_installs_manifest_and_reports_disabled_status(tmp_path):
    lifecycle = ModuleLifecycle(
        tmp_path,
        profile="main",
        available_dependencies=("memory_os", "scheduler"),
    )

    status = lifecycle.install(_manifest())

    assert status.installed is True
    assert status.enabled is False
    assert status.delivery_mode == "no-send"
    assert (tmp_path / "system-modules" / "installed" / "mailbox.json").exists()
    assert lifecycle.status("mailbox").to_dict()["name"] == "mailbox"
    assert [event.event_type for event in lifecycle.bus.read_events(profile="main")] == [
        "module.discovered"
    ]


def test_lifecycle_enable_and_disable_are_profile_local(tmp_path):
    sannai_home = tmp_path / "profiles" / "sannai-shape"
    sannai_home.mkdir(parents=True)
    soul = sannai_home / "SOUL.md"
    soul.write_text("private identity fixture\n", encoding="utf-8")
    before = soul.stat().st_mtime_ns
    lifecycle = ModuleLifecycle(
        tmp_path / "profiles" / "main",
        profile="main",
        available_dependencies=("memory_os", "scheduler"),
    )
    lifecycle.install(_manifest("inner_drive"))

    enabled = lifecycle.enable("inner_drive")
    disabled = lifecycle.disable("inner_drive")

    assert enabled.enabled is True
    assert disabled.enabled is False
    assert soul.stat().st_mtime_ns == before
    profile_state = json.loads(
        (tmp_path / "profiles" / "main" / "system-modules" / "profiles" / "main" / "inner_drive.json").read_text(
            encoding="utf-8"
        )
    )
    assert profile_state["enabled"] is False


def test_lifecycle_refuses_enable_when_required_dependency_is_missing(tmp_path):
    lifecycle = ModuleLifecycle(
        tmp_path,
        profile="main",
        available_dependencies=("memory_os",),
    )
    lifecycle.install(_manifest())

    with pytest.raises(LifecycleError, match="scheduler"):
        lifecycle.enable("mailbox")

    doctor = lifecycle.doctor("mailbox")
    assert doctor.status == "error"
    assert doctor.findings[0]["code"] == "missing_required_dependency"


def test_lifecycle_refuses_send_delivery_without_explicit_override(tmp_path):
    lifecycle = ModuleLifecycle(
        tmp_path,
        profile="main",
        available_dependencies=("memory_os", "scheduler"),
    )
    lifecycle.install(_manifest())

    with pytest.raises(LifecycleError, match="delivery"):
        lifecycle.enable("mailbox", delivery_mode="send")


def test_lifecycle_doctor_reports_schema_incompatibility(tmp_path):
    lifecycle = ModuleLifecycle(
        tmp_path,
        profile="main",
        available_dependencies=("memory_os", "scheduler"),
        memory_os_version="0.3.0",
    )
    lifecycle.install(_manifest())

    doctor = lifecycle.doctor("mailbox")

    assert doctor.status == "error"
    assert doctor.findings[0]["code"] == "memory_os_incompatible"
