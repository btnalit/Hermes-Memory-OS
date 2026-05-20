import json

from plugins.memory import load_memory_provider
from plugins.memory.memory_os.crystallized import read_candidate_queue
from plugins.memory.memory_os.prefetch import build_prefetch
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.runtime import MemoryOSRuntime
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.memory.memory_os.cli import build_status_report


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
