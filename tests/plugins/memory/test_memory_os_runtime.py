import json

from plugins.memory import load_memory_provider
from plugins.memory.memory_os.crystallized import read_candidate_queue
from plugins.memory.memory_os.fixtures import build_event
from plugins.memory.memory_os.index import MemoryOSIndex
from plugins.memory.memory_os.prefetch import build_prefetch
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.runtime import MemoryOSRuntime
from plugins.memory.memory_os.schema import EventEnvelope
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.memory.memory_os.cli import build_status_report


def _event(seed, *, profile="main", source="telegram", kind="conversation_turn", summary=None, safe_ref=None, tags=None):
    return EventEnvelope.from_dict(
        {
            **build_event(seed=seed, profile=profile),
            "source": source,
            "kind": kind,
            "summary": summary or f"runtime policy event {seed}",
            "safe_ref": safe_ref or {},
            "tags": tags or [],
        }
    )


def test_runtime_heartbeat_processes_new_events_into_working_and_candidates(tmp_path):
    provider = load_memory_provider("memory_os")
    provider.initialize("session-1", hermes_home=str(tmp_path), platform="cli", agent_identity="main")
    provider.sync_turn("runtime marker alpha", "stored alpha", session_id="session-1")
    provider.sync_turn("runtime marker beta", "stored beta", session_id="session-1")
    provider.shutdown()
    roots = MemoryOSRoots.from_hermes_home(tmp_path)
    store = MemoryOSStore(roots)

    report = MemoryOSRuntime(store).heartbeat()

    assert report["processed_event_count"] == 2
    assert report["working_item_count"] == 2
    assert report["candidate_count"] == 2
    assert report["crystallized_record_count"] == 0
    lingering = json.loads((tmp_path / "memory-os" / "working" / "lingering.json").read_text(encoding="utf-8"))
    assert len(lingering["items"]) == 2
    candidates = read_candidate_queue(roots)
    assert [candidate.candidate_id for candidate in candidates] == [
        f"cand_{event.id}" for event in store.read_events()
    ]
    context = build_prefetch("runtime marker", budget_chars=2000, store=store, index=None)
    assert "### Working Memory" in context
    assert "runtime marker alpha" in context
    status = build_status_report(store)
    assert status["counts"]["working_items"] == 2
    assert status["counts"]["crystallized_candidates"] == 2


def test_runtime_heartbeat_is_idempotent_for_processed_events(tmp_path):
    provider = load_memory_provider("memory_os")
    provider.initialize("session-1", hermes_home=str(tmp_path), platform="cli", agent_identity="main")
    provider.sync_turn("runtime idempotent marker", "stored", session_id="session-1")
    provider.shutdown()
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path))

    first = MemoryOSRuntime(store).heartbeat()
    second = MemoryOSRuntime(store).heartbeat()

    assert first["processed_event_count"] == 1
    assert second["processed_event_count"] == 0
    assert second["already_processed_event_count"] == 1
    assert len(read_candidate_queue(store.roots)) == 1


def test_runtime_heartbeat_indexes_new_events_without_duplicates(tmp_path):
    provider = load_memory_provider("memory_os")
    provider.initialize("session-1", hermes_home=str(tmp_path), platform="cli", agent_identity="main")
    provider.sync_turn("runtime index marker alpha", "stored alpha", session_id="session-1")
    provider.sync_turn("runtime index marker beta", "stored beta", session_id="session-1")
    provider.shutdown()
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path))

    first = MemoryOSRuntime(store).heartbeat()
    second = MemoryOSRuntime(store).heartbeat()

    assert first["index_counts"]["events"] == 2
    assert second["index_counts"]["events"] == 2
    assert MemoryOSIndex(store.roots).counts()["events"] == 2


def test_runtime_heartbeat_indexes_candidates_separately_from_crystallized_records(tmp_path):
    provider = load_memory_provider("memory_os")
    provider.initialize("session-1", hermes_home=str(tmp_path), platform="cli", agent_identity="main")
    provider.sync_turn("runtime candidate index marker", "stored", session_id="session-1")
    provider.shutdown()
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path))

    report = MemoryOSRuntime(store).heartbeat()

    assert report["index_counts"]["crystallized_candidates"] == 1
    assert report["index_counts"]["crystallized_records"] == 0
    assert MemoryOSIndex(store.roots).counts()["crystallized_candidates"] == 1


def test_runtime_policy_prevents_mirror_metadata_from_creating_candidates(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="main"))
    store.initialize()
    cron = _event(
        101,
        source="cron",
        kind="cron_job_run",
        summary="Cron mirror metadata should stay index only.",
        safe_ref={"source_module": "cron_mirror", "drive_policy": "index_only", "candidate_allowed": False},
        tags=["cron", "mirror"],
    )
    observed = _event(
        102,
        source="session_mirror",
        kind="session_observed",
        summary="Metadata-only session should not become lingering.",
        safe_ref={"source_module": "session_mirror", "drive_policy": "index_only", "candidate_allowed": False},
    )
    candidate_surface = _event(
        103,
        source="state_source_mirror",
        kind="candidate_surface_changed",
        summary="Candidate surface should not recursively create candidates.",
        safe_ref={"source_module": "state_source_mirror", "drive_policy": "candidate_surface", "candidate_allowed": False},
    )
    unknown = _event(104, source="mystery", kind="new_unknown_kind", summary="Unknown event must default index only.")
    for event in (cron, observed, candidate_surface, unknown):
        store.append_event(event)

    report = MemoryOSRuntime(store).heartbeat()

    assert report["processed_event_count"] == 4
    assert report["policy_skipped_event_count"] == 4
    assert report["candidate_count"] == 0
    assert read_candidate_queue(store.roots) == []
    assert not (store.roots.working_root / "lingering.json").exists()


def test_runtime_policy_allows_bounded_mirrored_conversation_working_without_candidate(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="main"))
    store.initialize()
    mirrored = _event(
        110,
        source="session_mirror",
        kind="conversation_turn_mirrored",
        summary="Bounded mirrored conversation can influence working memory.",
        safe_ref={
            "source_module": "session_mirror",
            "drive_policy": "eligible",
            "body_policy": "bounded_summary",
            "candidate_allowed": False,
        },
    )
    store.append_event(mirrored)

    report = MemoryOSRuntime(store).heartbeat()

    assert report["processed_event_count"] == 1
    assert report["working_item_count"] == 1
    assert report["candidate_count"] == 0
    lingering = json.loads((store.roots.working_root / "lingering.json").read_text(encoding="utf-8"))
    assert lingering["items"][0]["source_event_id"] == mirrored.id
    assert lingering["items"][0]["weight"] <= 0.35
    assert read_candidate_queue(store.roots) == []


def test_runtime_policy_source_caps_prevent_cron_batch_from_dominating(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="main"))
    store.initialize()
    for seed in range(120, 130):
        store.append_event(
            _event(
                seed,
                source="cron",
                kind="cron_job_run",
                safe_ref={"source_module": "cron_mirror", "drive_policy": "index_only", "candidate_allowed": False},
            )
        )
    foreground = _event(140, summary="Foreground should still be processed despite cron batch.")
    store.append_event(foreground)

    report = MemoryOSRuntime(store).heartbeat(max_events=20, max_events_per_source_class=2)

    assert report["processed_event_count"] == 3
    assert report["policy_skipped_event_count"] == 2
    assert report["cap_deferred_event_count"] == 8
    assert report["source_class_counts"]["cron"] == 2
    assert report["source_class_counts"]["foreground"] == 1
    assert report["candidate_count"] == 1
