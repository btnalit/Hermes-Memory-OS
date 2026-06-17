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


def test_self_activity_excluded_from_right_brain_eligible():
    """V2.1: Events with safe_ref.source_class='self_activity' are excluded from expression triggers."""
    from plugins.modules.cognition.wandering_mind import _right_brain_eligible_events
    from plugins.memory.memory_os.schema import EventEnvelope

    now = "2026-06-17T12:00:00Z"
    normal_event = EventEnvelope.from_dict({
        "schema_version": "memory-os.event.v0",
        "id": "evt_normal",
        "ts": now,
        "profile": "main",
        "source": "telegram",
        "kind": "conversation_turn",
        "summary": "normal chat",
        "safe_ref": {"source_class": "foreground"},
        "tags": [],
        "sensitivity": "private",
        "body_policy": "summary_only",
        "hashes": {},
        "promotion_state": "raw",
    })
    # Use a source/kind that would normally be eligible (telegram/conversation_turn)
    # so the only thing excluding it is the source_class == "self_activity" gate
    self_activity_event = EventEnvelope.from_dict({
        "schema_version": "memory-os.event.v0",
        "id": "evt_self",
        "ts": now,
        "profile": "main",
        "source": "telegram",
        "kind": "conversation_turn",
        "summary": "I said something",
        "safe_ref": {"source_class": "self_activity", "self_activity_subtype": "speech"},
        "tags": [],
        "sensitivity": "private",
        "body_policy": "summary_only",
        "hashes": {},
        "promotion_state": "raw",
    })

    eligible = _right_brain_eligible_events([normal_event, self_activity_event])
    eligible_ids = {e.id for e in eligible}
    assert "evt_normal" in eligible_ids, "normal events must be eligible"
    assert "evt_self" not in eligible_ids, (
        "self_activity events must be EXCLUDED from expression triggers"
    )


def test_speech_does_not_trigger_new_expression(tmp_path):
    """V2.3 E2E: speech feedback event (self_activity) is NOT eligible for expression triggers
    while normal conversation events remain eligible. Tests full pipeline through store."""
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore
    from plugins.memory.memory_os.schema import EventEnvelope
    from plugins.modules.cognition.wandering_mind import _right_brain_eligible_events

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="main")
    store = MemoryOSStore(roots)
    store.initialize()

    conversation_event = EventEnvelope.from_dict({
        "schema_version": "memory-os.event.v0",
        "id": "evt_conv_1",
        "ts": "2026-06-17T10:00:00Z",
        "profile": "main",
        "source": "telegram",
        "kind": "conversation_turn",
        "summary": "Owner asked about weather",
        "safe_ref": {"source_class": "foreground"},
        "tags": [],
        "sensitivity": "private",
        "body_policy": "summary_only",
        "hashes": {},
        "promotion_state": "raw",
    })
    speech_feedback_event = EventEnvelope.from_dict({
        "schema_version": "memory-os.event.v0",
        "id": "evt_speech_1",
        "ts": "2026-06-17T10:01:00Z",
        "profile": "main",
        "source": "governance_feedback",
        "kind": "governance_speak_gate_delivery",
        "summary": "System said: it looks sunny today",
        "safe_ref": {"source_class": "self_activity", "self_activity_subtype": "speech"},
        "tags": ["governance", "speak_gate", "summary_only"],
        "sensitivity": "private",
        "body_policy": "summary_only",
        "hashes": {},
        "promotion_state": "raw",
    })

    store.append_event(conversation_event)
    store.append_event(speech_feedback_event)

    events = store.read_events()
    eligible = _right_brain_eligible_events(events)

    eligible_ids = {e.id for e in eligible}
    assert "evt_conv_1" in eligible_ids, "conversation event must be eligible for expression"
    assert "evt_speech_1" not in eligible_ids, (
        "self_activity speech event MUST NOT be eligible — anti-spiral gate failed"
    )


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
