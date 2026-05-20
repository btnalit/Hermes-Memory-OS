import json
import time

from plugins.memory import load_memory_provider
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore


def _events(hermes_home):
    roots = MemoryOSRoots.from_hermes_home(hermes_home, profile="memoryos-test")
    return MemoryOSStore(roots).read_events()


def test_memory_os_provider_is_discoverable_without_initializing_storage():
    provider = load_memory_provider("memory_os")

    assert provider is not None
    assert provider.name == "memory-os"
    assert provider.is_available() is True
    assert [schema["name"] for schema in provider.get_tool_schemas()] == ["memory_os_status"]
    assert provider.prefetch("hello") == ""


def test_memory_os_lifecycle_initializes_store_under_supplied_hermes_home(tmp_path):
    provider = load_memory_provider("memory_os")

    provider.initialize("session-1", hermes_home=str(tmp_path), platform="cli")
    provider.on_session_end([])
    provider.on_pre_compress([])
    provider.on_memory_write("add", "memory", "content")
    provider.shutdown()

    assert (tmp_path / "memory-os").is_dir()
    assert not (tmp_path.parent / "memory-os").exists()


def test_memory_os_config_schema_and_save_config(tmp_path):
    provider = load_memory_provider("memory_os")

    schema = {field["key"]: field for field in provider.get_config_schema()}
    assert schema["capture_policy"]["default"] == "summary_only"
    assert schema["prefetch_char_budget"]["default"] == 2200
    assert schema["hindsight_adapter_enabled"]["default"] is False
    assert schema["allow_full_local_capture"]["default"] is False

    provider.save_config({"prefetch_char_budget": 1200}, str(tmp_path))

    saved = json.loads((tmp_path / "memory-os" / "config.json").read_text(encoding="utf-8"))
    assert saved["capture_policy"] == "summary_only"
    assert saved["prefetch_char_budget"] == 1200
    assert saved["hindsight_adapter_enabled"] is False
    assert saved["allow_full_local_capture"] is False


def test_sync_turn_enqueues_summary_only_event_and_returns_quickly(tmp_path):
    provider = load_memory_provider("memory_os")
    provider.initialize("session-1", hermes_home=str(tmp_path), platform="cli", agent_identity="memoryos-test")
    user_content = "user " + ("x" * 5000)
    assistant_content = "assistant " + ("y" * 5000)

    durations = []
    for _ in range(5):
        start = time.perf_counter()
        provider.sync_turn(user_content, assistant_content, session_id="session-1")
        durations.append(time.perf_counter() - start)
    provider.shutdown()

    assert sorted(durations)[-1] < 0.020
    events = _events(tmp_path)
    assert len(events) == 5
    assert all(event.kind == "conversation_turn" for event in events)
    assert all(event.body_policy == "summary_only" for event in events)
    assert all(event.safe_ref["session_id"] == "session-1" for event in events)
    assert all(user_content not in event.summary for event in events)
    assert all(assistant_content not in event.summary for event in events)


def test_sync_turn_drops_newest_when_queue_is_full_and_audits(tmp_path):
    provider = load_memory_provider("memory_os")
    provider.initialize(
        "session-1",
        hermes_home=str(tmp_path),
        platform="cli",
        agent_identity="memoryos-test",
        queue_max_size=1,
        worker_autostart=False,
    )

    provider.sync_turn("first user", "first assistant", session_id="session-1")
    provider.sync_turn("second user", "second assistant", session_id="session-1")
    provider.shutdown()

    events = _events(tmp_path)
    assert len(events) == 1
    assert "first user" in events[0].summary
    audit_lines = (tmp_path / "memory-os" / "audit" / "write_audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert any("sync_turn_dropped" in line for line in audit_lines)


def test_worker_error_is_audited_and_later_items_continue(tmp_path):
    provider = load_memory_provider("memory_os")
    provider.initialize("session-1", hermes_home=str(tmp_path), platform="cli", agent_identity="memoryos-test")
    original_append = provider._store.append_event
    calls = {"count": 0}

    def flaky_append(event):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("boom")
        return original_append(event)

    provider._store.append_event = flaky_append

    provider.sync_turn("first user", "first assistant", session_id="session-1")
    provider.sync_turn("second user", "second assistant", session_id="session-1")
    provider.shutdown()

    events = _events(tmp_path)
    assert len(events) == 1
    assert "second user" in events[0].summary
    audit_lines = (tmp_path / "memory-os" / "audit" / "write_audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert any("worker_error" in line and "boom" in line for line in audit_lines)


def test_v0_does_not_recover_unflushed_in_memory_queue_after_unclean_restart(tmp_path):
    provider = load_memory_provider("memory_os")
    provider.initialize(
        "session-1",
        hermes_home=str(tmp_path),
        platform="cli",
        agent_identity="memoryos-test",
        worker_autostart=False,
    )
    provider.sync_turn("queued user", "queued assistant", session_id="session-1")

    restarted = load_memory_provider("memory_os")
    restarted.initialize("session-2", hermes_home=str(tmp_path), platform="cli", agent_identity="memoryos-test")
    restarted.shutdown()

    assert _events(tmp_path) == []


def test_on_memory_write_mirrors_allowed_write_as_event_only(tmp_path):
    provider = load_memory_provider("memory_os")
    provider.initialize("session-1", hermes_home=str(tmp_path), platform="cli", agent_identity="memoryos-test")

    provider.on_memory_write("add", "memory", "Remember owner preference.", metadata={"session_id": "session-1"})
    provider.on_memory_write("replace", "memory", "Do not mirror replace.", metadata={"session_id": "session-1"})
    provider.shutdown()

    events = _events(tmp_path)
    assert len(events) == 1
    assert events[0].kind == "memory_write"
    assert "Remember owner preference." in events[0].summary
    assert not (tmp_path / "memories" / "MEMORY.md").exists()


def test_memory_os_status_tool_reports_local_store_not_hindsight(tmp_path):
    provider = load_memory_provider("memory_os")
    provider.initialize("session-1", hermes_home=str(tmp_path), platform="cli", agent_identity="main")

    provider.sync_turn("check provider", "Memory-OS is active", session_id="session-1")
    provider.shutdown()

    report = json.loads(provider.handle_tool_call("memory_os_status", {}))
    rendered = json.dumps(report, ensure_ascii=False)
    assert report["schema_version"] == "memory-os.tool_status.v0"
    assert report["provider"] == "memory_os"
    assert report["status"] == "active"
    assert report["storage_model"] == "local_filesystem_jsonl_markdown"
    assert report["canonical_store"] == str(tmp_path / "memory-os")
    assert report["event_count"] == 1
    assert report["hindsight_adapter_enabled"] is False
    assert report["uses_hindsight_http_api"] is False
    assert "172.18.0.99" not in rendered
    assert "api_url" not in rendered
