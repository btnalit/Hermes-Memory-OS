from plugins.memory.memory_os.fixtures import build_event, build_sannai_multi_root_fixture
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.schema import EventEnvelope
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.modules.cognition import DeepReflectionModule, deep_reflection_manifest
from plugins.system.lifecycle import ModuleLifecycle


def _store(tmp_path, *, profile="main"):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile=profile)
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def test_deep_reflection_manifest_installs_through_lifecycle(tmp_path):
    lifecycle = ModuleLifecycle(
        tmp_path,
        profile="main",
        available_dependencies=("memory_os", "scheduler", "continuity_selector", "inner_drive"),
    )

    status = lifecycle.install(deep_reflection_manifest())
    enabled = lifecycle.enable("deep_reflection")

    assert status.installed is True
    assert status.enabled is False
    assert enabled.enabled is True
    assert enabled.delivery_mode == "no-send"
    assert lifecycle.doctor("deep_reflection").status == "ok"


def test_deep_reflection_status_defaults_to_no_injection(tmp_path):
    module = DeepReflectionModule(tmp_path, profile="main")

    status = module.status()

    assert status["schema_version"] == "hermes.deep_reflection_status.v0"
    assert status["module"] == "deep_reflection"
    assert status["profile"] == "main"
    assert status["enabled"] is False
    assert status["injection_mode"] == "disabled"
    assert status["actual_send"] is False
    assert status["actual_execute"] is False
    assert status["actual_identity_write"] is False
    assert status["actual_crystallized_approval"] is False


def test_deep_reflection_dry_run_writes_local_report_without_memory_events(tmp_path):
    store = _store(tmp_path)
    store.append_event(EventEnvelope.from_dict(build_event(seed=1, profile="main")))
    before_event_count = len(store.read_events())
    module = DeepReflectionModule(tmp_path, profile="main")

    result = module.run_once(store=store, dry_run=True)

    assert result["status"] == "ok"
    assert result["dry_run"] is True
    assert result["injection_mode"] == "disabled"
    assert result["analysis_artifact_created"] is True
    assert result["actual_send"] is False
    assert result["actual_execute"] is False
    assert len(store.read_events()) == before_event_count
    assert module.current_injection_path.exists() is False
    assert module.reports_path.exists()


def test_deep_reflection_doctor_reports_safe_default_state(tmp_path):
    store = _store(tmp_path)
    module = DeepReflectionModule(tmp_path, profile="main")

    report = module.doctor(store=store)

    assert report["schema_version"] == "hermes.deep_reflection_doctor.v0"
    assert report["module"] == "deep_reflection"
    assert report["status"] == "ok"
    assert report["findings"] == []


def test_deep_reflection_preview_injection_is_empty_by_default(tmp_path):
    module = DeepReflectionModule(tmp_path, profile="main")

    preview = module.preview_injection()

    assert preview["schema_version"] == "hermes.deep_reflection_preview.v0"
    assert preview["module"] == "deep_reflection"
    assert preview["profile"] == "main"
    assert preview["injection_mode"] == "disabled"
    assert preview["selected_cards"] == []
    assert preview["actual_send"] is False


def test_deep_reflection_doctor_warns_on_cross_profile_store(tmp_path):
    store = _store(tmp_path, profile="other")
    store.append_event(EventEnvelope.from_dict(build_event(seed=3, profile="other")))
    module = DeepReflectionModule(tmp_path, profile="main")

    report = module.doctor(store=store)

    assert report["status"] == "warning"
    assert report["findings"][0]["code"] == "store_contains_other_profiles"


def test_deep_reflection_does_not_touch_profile_isolation_fixture(tmp_path):
    fixture = build_sannai_multi_root_fixture(tmp_path / "fixture")
    soul = fixture.hermes_home / "SOUL.md"
    before = soul.stat().st_mtime_ns
    store = _store(tmp_path / "main", profile="main")
    store.append_event(EventEnvelope.from_dict(build_event(seed=2, profile="main")))
    module = DeepReflectionModule(tmp_path / "main", profile="main")

    module.run_once(store=store, dry_run=True)

    assert soul.stat().st_mtime_ns == before
    assert not (fixture.hermes_home / "system-modules").exists()
