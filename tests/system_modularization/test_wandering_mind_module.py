import json

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

    # V1: wandering_mind no longer records would_send; delivery is handled by cognitive_loop._spontaneous_expression
    assert result["would_send"] is False
    assert result["actual_send"] is False
    assert result["output"] != "[SILENT]"
    records = module.read_would_send_records()
    assert len(records) == 0


def test_wandering_mind_skips_unchanged_signal_until_owner_reaction_changes(tmp_path):
    store = _store(tmp_path)
    store.append_event(EventEnvelope.from_dict(build_event(seed=4, profile="main")))
    HouseholdDigestModule(tmp_path, profile="main").build_digest(store=store)
    module = WanderingMindModule(tmp_path, profile="main")

    first = module.run_once(store=store, min_events=1)
    second = module.run_once(store=store, min_events=1)

    # V1: wandering_mind no longer records would_send; delivery is handled by cognitive_loop._spontaneous_expression
    assert first["would_send"] is False
    assert second["status"] == "skipped"
    assert second["cadence_skipped"] is True
    assert second["reason"] == "unchanged_right_brain_signal"
    assert len(module.read_would_send_records()) == 0

    feedback_path = store.roots.memory_os_root / "system" / "expression_feedback_ledger.jsonl"
    feedback_path.parent.mkdir(parents=True, exist_ok=True)
    feedback_path.write_text(
        json.dumps(
            {
                "schema_version": "memory-os.expression_feedback.v0",
                "feedback_id": "exprfb_test_001",
                "target_id": "latest_outcome",
                "action_type": "expression_feedback_too_mechanical",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    after_reaction = module.run_once(store=store, min_events=1)

    # V1: wandering_mind no longer records would_send
    assert after_reaction["would_send"] is False
    assert after_reaction["signal_summary"]["feedback_count"] == 1
    assert len(module.read_would_send_records()) == 0
    status = module.status()
    assert status["generated_count"] == 2
    assert status["skipped_count"] == 1


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
