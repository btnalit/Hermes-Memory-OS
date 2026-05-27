from plugins.memory.memory_os.fixtures import build_event, build_sannai_multi_root_fixture
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.schema import EventEnvelope
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.modules.context.household_digest import HouseholdDigestModule, household_digest_manifest
from plugins.system.lifecycle import ModuleLifecycle


def _store(tmp_path, *, profile="main"):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile=profile)
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def test_household_digest_manifest_installs_through_lifecycle(tmp_path):
    lifecycle = ModuleLifecycle(
        tmp_path,
        profile="main",
        available_dependencies=("memory_os", "scheduler"),
    )

    status = lifecycle.install(household_digest_manifest())
    enabled = lifecycle.enable("household_digest")

    assert status.installed is True
    assert enabled.enabled is True
    assert enabled.delivery_mode == "no-send"
    assert lifecycle.doctor("household_digest").status == "ok"


def test_household_digest_builds_summary_from_memory_os_events(tmp_path):
    store = _store(tmp_path)
    first = EventEnvelope.from_dict(
        {**build_event(seed=1, profile="main"), "summary": "Owner discussed mailbox module."}
    )
    second = EventEnvelope.from_dict(
        {**build_event(seed=2, profile="main"), "summary": "Memory-OS generated a context digest."}
    )
    store.append_event(first)
    store.append_event(second)
    module = HouseholdDigestModule(tmp_path, profile="main")

    result = module.build_digest(store=store, limit=10)

    assert result["event_count"] == 2
    assert result["degraded"] is False
    assert result["artifact_ref"].endswith("household_digest.md")
    digest = (tmp_path / "system-modules" / "household_digest" / "household_digest.md").read_text(
        encoding="utf-8"
    )
    assert "Owner discussed mailbox module." in digest
    assert "Memory-OS generated a context digest." in digest
    assert "body" not in digest.lower()


def test_household_digest_skips_when_input_fingerprint_is_unchanged(tmp_path):
    store = _store(tmp_path)
    store.append_event(
        EventEnvelope.from_dict(
            {**build_event(seed=11, profile="main"), "summary": "Stable household digest source."}
        )
    )
    module = HouseholdDigestModule(tmp_path, profile="main")

    first = module.build_digest(store=store, limit=10)
    before = module.digest_path.read_text(encoding="utf-8")
    second = module.build_digest(store=store, limit=10)
    status = module.status()

    assert first["status"] == "ok"
    assert second["status"] == "skipped"
    assert second["skipped"] is True
    assert second["cadence_skipped"] is True
    assert second["reason"] == "unchanged_input_fingerprint"
    assert module.digest_path.read_text(encoding="utf-8") == before
    assert status["generated_count"] == 1
    assert status["skipped_count"] == 1


def test_household_digest_degrades_gracefully_with_few_events(tmp_path):
    store = _store(tmp_path)
    store.append_event(EventEnvelope.from_dict(build_event(seed=3, profile="main")))
    module = HouseholdDigestModule(tmp_path, profile="main")

    result = module.build_digest(store=store, min_events=50)

    assert result["event_count"] == 1
    assert result["degraded"] is True
    assert result["reason"] == "insufficient_events"
    assert module.doctor(store=store)["status"] == "warning"


def test_household_digest_doctor_warns_when_events_are_missing(tmp_path):
    store = _store(tmp_path)
    module = HouseholdDigestModule(tmp_path, profile="main")

    report = module.doctor(store=store)

    assert report["status"] == "warning"
    assert report["findings"][0]["code"] == "no_memory_os_events"


def test_household_digest_does_not_touch_sannai_shape_fixture(tmp_path):
    fixture = build_sannai_multi_root_fixture(tmp_path / "fixture")
    soul = fixture.hermes_home / "SOUL.md"
    before = soul.stat().st_mtime_ns
    store = _store(tmp_path / "main", profile="main")
    store.append_event(EventEnvelope.from_dict(build_event(seed=4, profile="main")))
    module = HouseholdDigestModule(tmp_path / "main", profile="main")

    module.build_digest(store=store)

    assert soul.stat().st_mtime_ns == before
    assert not (fixture.hermes_home / "system-modules").exists()
