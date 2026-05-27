from plugins.memory.memory_os.fixtures import build_event, build_sannai_multi_root_fixture
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.schema import EventEnvelope
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.modules.cognition.wandering_mind import WanderingMindModule, wandering_mind_manifest
from plugins.modules.context.household_digest import HouseholdDigestModule
from plugins.system.lifecycle import ModuleLifecycle


def _store(tmp_path, *, profile="main"):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile=profile)
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def test_wandering_mind_manifest_installs_through_lifecycle(tmp_path):
    lifecycle = ModuleLifecycle(
        tmp_path,
        profile="main",
        available_dependencies=("memory_os", "scheduler", "household_digest"),
    )

    status = lifecycle.install(wandering_mind_manifest())
    enabled = lifecycle.enable("wandering_mind")

    assert status.installed is True
    assert enabled.enabled is True
    assert enabled.delivery_mode == "no-send"
    assert lifecycle.doctor("wandering_mind").status == "ok"


def test_wandering_mind_builds_bounded_context_from_digest_and_events(tmp_path):
    store = _store(tmp_path)
    store.append_event(
        EventEnvelope.from_dict(
            {**build_event(seed=1, profile="main"), "summary": "Owner paused over a quiet sentence."}
        )
    )
    HouseholdDigestModule(tmp_path, profile="main").build_digest(store=store)
    module = WanderingMindModule(tmp_path, profile="main")

    context = module.build_context(store=store, limit=5)

    assert "Household Digest" in context
    assert "Owner paused over a quiet sentence." in context
    assert "cron" not in context.lower()
    assert "job_id" not in context.lower()
    assert "proposal" not in context.lower()
    assert "body" not in context.lower()


def test_wandering_mind_returns_silent_when_context_is_too_sparse(tmp_path):
    store = _store(tmp_path)
    module = WanderingMindModule(tmp_path, profile="main")

    result = module.run_once(store=store, min_events=2)

    assert result["output"] == "[SILENT]"
    assert result["would_send"] is False
    assert result["reason"] == "insufficient_context"
    assert module.read_would_send_records() == []


def test_wandering_mind_records_would_send_without_real_delivery(tmp_path):
    store = _store(tmp_path)
    store.append_event(EventEnvelope.from_dict(build_event(seed=2, profile="main")))
    HouseholdDigestModule(tmp_path, profile="main").build_digest(store=store)
    module = WanderingMindModule(tmp_path, profile="main")

    result = module.run_once(store=store, min_events=1)

    assert result["would_send"] is True
    assert result["actual_send"] is False
    assert result["output"] != "[SILENT]"
    records = module.read_would_send_records()
    assert len(records) == 1
    assert records[0]["payload_ref"] == result["output_ref"]
    assert records[0]["created_at"] == records[0]["ts"]
    assert "body" not in records[0]


def test_wandering_mind_does_not_touch_sannai_shape_fixture(tmp_path):
    fixture = build_sannai_multi_root_fixture(tmp_path / "fixture")
    soul = fixture.hermes_home / "SOUL.md"
    before = soul.stat().st_mtime_ns
    store = _store(tmp_path / "main", profile="main")
    store.append_event(EventEnvelope.from_dict(build_event(seed=3, profile="main")))
    HouseholdDigestModule(tmp_path / "main", profile="main").build_digest(store=store)
    module = WanderingMindModule(tmp_path / "main", profile="main")

    module.run_once(store=store, min_events=1)

    assert soul.stat().st_mtime_ns == before
    assert not (fixture.hermes_home / "system-modules").exists()
