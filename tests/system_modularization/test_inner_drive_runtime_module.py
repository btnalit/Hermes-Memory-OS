import json
from datetime import datetime, timezone

from plugins.memory.memory_os.crystallized import read_candidate_queue
from plugins.memory.memory_os.fixtures import build_event, build_sannai_multi_root_fixture
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.schema import EventEnvelope
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.modules.cognition.inner_drive import InnerDriveRuntimeModule, inner_drive_manifest
from plugins.system.lifecycle import ModuleLifecycle
from plugins.system.scheduler import ScheduleCoordinator


def _store(tmp_path, *, profile="main"):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile=profile)
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def test_inner_drive_manifest_installs_through_lifecycle(tmp_path):
    lifecycle = ModuleLifecycle(
        tmp_path,
        profile="main",
        available_dependencies=("memory_os", "scheduler"),
    )

    status = lifecycle.install(inner_drive_manifest())
    enabled = lifecycle.enable("inner_drive")

    assert status.installed is True
    assert enabled.enabled is True
    assert enabled.delivery_mode == "no-send"
    assert lifecycle.doctor("inner_drive").status == "ok"


def test_inner_drive_processes_events_into_working_memory_and_candidates(tmp_path):
    store = _store(tmp_path)
    event = EventEnvelope.from_dict(
        {
            **build_event(seed=1, profile="main"),
            "source": "telegram",
            "kind": "conversation_turn",
            "summary": "Owner asked about runtime cognition.",
        }
    )
    store.append_event(event)
    module = InnerDriveRuntimeModule(tmp_path, profile="main")

    result = module.run_once(store=store)

    assert result["status"] == "ok"
    assert result["processed_event_count"] == 1
    lingering = json.loads((store.roots.working_root / "lingering.json").read_text(encoding="utf-8"))
    assert lingering["items"][0]["source_event_id"] == event.id
    assert lingering["items"][0]["text"] == "Owner asked about runtime cognition."
    candidates = read_candidate_queue(store)
    assert len(candidates) == 1
    assert candidates[0].source_event_ids == [event.id]
    assert candidates[0].bridge_state == "inner_drive_candidate"
    assert result["actual_send"] is False


def test_inner_drive_is_idempotent_for_already_processed_events(tmp_path):
    store = _store(tmp_path)
    store.append_event(
        EventEnvelope.from_dict(
            {
                **build_event(seed=2, profile="main"),
                "source": "telegram",
                "kind": "conversation_turn",
            }
        )
    )
    module = InnerDriveRuntimeModule(tmp_path, profile="main")

    first = module.run_once(store=store)
    second = module.run_once(store=store)

    assert first["processed_event_count"] == 1
    assert second["processed_event_count"] == 0
    assert second["already_processed_event_count"] == 1
    assert len(read_candidate_queue(store)) == 1


def test_inner_drive_defers_without_memory_writes_when_runtime_lock_is_held(tmp_path):
    store = _store(tmp_path)
    store.append_event(EventEnvelope.from_dict(build_event(seed=3, profile="main")))
    coordinator = ScheduleCoordinator(tmp_path / "system-modules" / "locks")
    coordinator.acquire_lock(
        "inner_drive.runtime",
        owner="other-module",
        ttl_seconds=60,
        now=datetime(2026, 5, 20, 0, 0, 0, tzinfo=timezone.utc),
    )
    module = InnerDriveRuntimeModule(tmp_path, profile="main")

    result = module.run_once(
        store=store,
        coordinator=coordinator,
        now=datetime(2026, 5, 20, 0, 0, 30, tzinfo=timezone.utc),
    )

    assert result["status"] == "deferred"
    assert result["reason"] == "lock_held"
    assert result["processed_event_count"] == 0
    assert not (store.roots.working_root / "lingering.json").exists()
    assert read_candidate_queue(store) == []


def test_inner_drive_degrades_gracefully_with_sparse_events(tmp_path):
    store = _store(tmp_path)
    store.append_event(EventEnvelope.from_dict(build_event(seed=4, profile="main")))
    module = InnerDriveRuntimeModule(tmp_path, profile="main")

    result = module.run_once(store=store, min_events=50)

    assert result["status"] == "warning"
    assert result["degraded"] is True
    assert result["reason"] == "insufficient_events"
    assert result["processed_event_count"] == 1
    assert module.doctor(store=store, min_events=50)["status"] == "warning"


def test_inner_drive_doctor_warns_when_events_are_missing(tmp_path):
    store = _store(tmp_path)
    module = InnerDriveRuntimeModule(tmp_path, profile="main")

    report = module.doctor(store=store)

    assert report["status"] == "warning"
    assert report["findings"][0]["code"] == "no_memory_os_events"


def test_inner_drive_does_not_touch_sannai_shape_fixture(tmp_path):
    fixture = build_sannai_multi_root_fixture(tmp_path / "fixture")
    soul = fixture.hermes_home / "SOUL.md"
    before = soul.stat().st_mtime_ns
    store = _store(tmp_path / "main", profile="main")
    store.append_event(EventEnvelope.from_dict(build_event(seed=5, profile="main")))
    module = InnerDriveRuntimeModule(tmp_path / "main", profile="main")

    module.run_once(store=store)

    assert soul.stat().st_mtime_ns == before
    assert not (fixture.hermes_home / "system-modules").exists()


def test_inner_drive_module_respects_mirror_event_policy(tmp_path):
    store = _store(tmp_path)
    store.append_event(
        EventEnvelope.from_dict(
            {
                **build_event(seed=20, profile="main"),
                "source": "cron",
                "kind": "cron_job_run",
                "summary": "Cron metadata should not become a candidate.",
                "safe_ref": {"source_module": "cron_mirror", "drive_policy": "index_only", "candidate_allowed": False},
            }
        )
    )
    store.append_event(
        EventEnvelope.from_dict(
            {
                **build_event(seed=21, profile="main"),
                "source": "session_mirror",
                "kind": "conversation_turn_mirrored",
                "summary": "Mirrored conversation can become bounded working memory.",
                "safe_ref": {
                    "source_module": "session_mirror",
                    "drive_policy": "eligible",
                    "body_policy": "bounded_summary",
                    "candidate_allowed": False,
                },
            }
        )
    )
    module = InnerDriveRuntimeModule(tmp_path, profile="main")

    result = module.run_once(store=store)

    assert result["processed_event_count"] == 2
    assert result["policy_skipped_event_count"] == 1
    assert result["candidate_count"] == 0
    assert len(read_candidate_queue(store)) == 0
    lingering = json.loads((store.roots.working_root / "lingering.json").read_text(encoding="utf-8"))
    assert len(lingering["items"]) == 1
    assert lingering["items"][0]["text"] == "Mirrored conversation can become bounded working memory."


def test_source_class_recognizes_self_activity():
    """V2.2: _source_class() returns 'self_activity' for self_activity events."""
    from plugins.memory.memory_os.inner_drive import _source_class

    sa_event = EventEnvelope.from_dict({
        "schema_version": "memory-os.event.v0",
        "id": "evt_sa",
        "ts": "2026-06-17T12:00:00Z",
        "profile": "main",
        "source": "governance_feedback",
        "kind": "governance_speak_gate_delivery",
        "summary": "self activity event",
        "safe_ref": {"source_class": "self_activity", "self_activity_subtype": "speech"},
        "tags": [],
        "sensitivity": "private",
        "body_policy": "summary_only",
        "hashes": {},
        "promotion_state": "raw",
    })
    result = _source_class(sa_event)
    assert result == "self_activity", (
        f"expected 'self_activity' but got '{result}' — _source_class must recognize self_activity"
    )


def test_self_activity_capped_by_select_events_for_inner_drive():
    """V2.7: self_activity events are capped per-source-class by select_events_for_inner_drive."""
    from plugins.memory.memory_os.inner_drive import select_events_for_inner_drive

    def make_sa_event(seed):
        return EventEnvelope.from_dict({
            "schema_version": "memory-os.event.v0",
            "id": f"evt_sa_{seed}",
            "ts": f"2026-06-17T12:{seed:02d}:00Z",
            "profile": "main",
            "source": "governance_feedback",
            "kind": "governance_speak_gate_delivery",
            "summary": f"self activity {seed}",
            "safe_ref": {"source_class": "self_activity", "self_activity_subtype": "speech"},
            "tags": [],
            "sensitivity": "private",
            "body_policy": "summary_only",
            "hashes": {},
            "promotion_state": "raw",
        })

    def make_normal_event(seed):
        return EventEnvelope.from_dict({
            "schema_version": "memory-os.event.v0",
            "id": f"evt_norm_{seed}",
            "ts": f"2026-06-17T13:{seed:02d}:00Z",
            "profile": "main",
            "source": "telegram",
            "kind": "conversation_turn",
            "summary": f"normal chat {seed}",
            "safe_ref": {"source_class": "foreground"},
            "tags": [],
            "sensitivity": "private",
            "body_policy": "summary_only",
            "hashes": {},
            "promotion_state": "raw",
        })

    # Create 30 self_activity events + 30 normal events (place normal first
    # so the fraction gate has room before self_activity events are encountered)
    sa_events = [make_sa_event(i) for i in range(30)]
    normal_events = [make_normal_event(i) for i in range(30)]
    all_events = normal_events + sa_events

    # Cap self_activity at 3, all else at 100
    caps = {"self_activity": 3, "*": 100}
    selected, deferred = select_events_for_inner_drive(
        all_events, set(), max_events=200, max_events_per_source_class=caps,
    )

    sa_selected = [e for e in selected if e.id.startswith("evt_sa_")]
    sa_deferred = [e for e in deferred if e.id.startswith("evt_sa_")]
    norm_selected = [e for e in selected if e.id.startswith("evt_norm_")]

    assert len(sa_selected) == 3, f"expected 3 self_activity selected, got {len(sa_selected)}"
    assert len(sa_deferred) >= 27, f"expected >=27 self_activity deferred, got {len(sa_deferred)}"
    assert len(norm_selected) == 30, f"expected 30 normal events selected, got {len(norm_selected)}"


def test_V2_7_self_activity_fraction_gate_defers_excess():
    """V2.7: self_activity events >15% of selected batch -> excess deferred."""
    from plugins.memory.memory_os.inner_drive import (
        select_events_for_inner_drive,
        SELF_ACTIVITY_MAX_FRACTION,
    )
    from plugins.memory.memory_os.schema import EventEnvelope

    now = datetime.now(timezone.utc)
    # Create 20 foreground events + 10 self_activity events
    events = []
    for i in range(20):
        events.append(EventEnvelope.from_dict({
            "schema_version": "memory-os.event.v0",
            "id": f"fg_{i}", "ts": now.isoformat(), "profile": "main",
            "source": "telegram",
            "kind": "conversation_turn", "summary": f"fg {i}",
            "safe_ref": {"source_class": "foreground"},
            "tags": [], "sensitivity": "private", "body_policy": "summary_only",
            "hashes": {}, "promotion_state": "raw",
        }))
    for i in range(10):
        events.append(EventEnvelope.from_dict({
            "schema_version": "memory-os.event.v0",
            "id": f"sa_{i}", "ts": now.isoformat(), "profile": "main",
            "source": "governance_feedback",
            "kind": "governance_feedback_event", "summary": f"sa {i}",
            "safe_ref": {"source_class": "self_activity", "drive_policy": "evidence_only"},
            "tags": [], "sensitivity": "private", "body_policy": "summary_only",
            "hashes": {}, "promotion_state": "raw",
        }))

    selected, deferred = select_events_for_inner_drive(
        events, set(), max_events=100,
    )
    sa_selected = [e for e in selected if e.id.startswith("sa_")]
    fg_selected = [e for e in selected if e.id.startswith("fg_")]

    # self_activity must not exceed SELF_ACTIVITY_MAX_FRACTION of selected
    max_sa = max(1, int(len(selected) * SELF_ACTIVITY_MAX_FRACTION))
    assert len(sa_selected) <= max_sa, (
        f"self_activity count {len(sa_selected)} exceeds max {max_sa}"
    )
    # Foreground events must be present (not drowned out)
    assert len(fg_selected) > 0, "foreground events must not be drowned"
    # Excess self_activity must be deferred
    sa_deferred = [e for e in deferred if e.id.startswith("sa_")]
    assert len(sa_deferred) > 0, "excess self_activity must be deferred"
