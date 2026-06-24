import json
import time

import plugins.memory.memory_os as memory_os_module
from plugins.memory import load_memory_provider
from plugins.memory.memory_os.config import save_config
from plugins.memory.memory_os.index import MemoryOSIndex
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.status_tool_contract import (
    MEMORY_OS_REVIEW_REPLY_TOOL_DESCRIPTION,
    MEMORY_OS_REVIEW_SURFACE_TOOL_DESCRIPTION,
    memory_os_status_tool_contract,
    validate_memory_os_status_tool_description,
)
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.memory.memory_os.__init__ import _looks_like_owner_review_reply


def _events(hermes_home):
    roots = MemoryOSRoots.from_hermes_home(hermes_home, profile="memoryos-test")
    return MemoryOSStore(roots).read_events()


def test_memory_os_provider_is_discoverable_without_initializing_storage():
    provider = load_memory_provider("memory_os")

    assert provider is not None
    assert provider.name == "memory-os"
    assert provider.is_available() is True
    assert [schema["name"] for schema in provider.get_tool_schemas()] == [
        "memory_os_status",
        "memory_os_review_reply",
        "memory_os_review_surface",
    ]
    assert provider.prefetch("hello") == ""


def test_provider_prefetch_runs_active_hindsight_recall_as_advisory_context(monkeypatch, tmp_path):
    class FakeHindsightClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def recall(self, *, bank_id, query, budget, max_tokens):
            return {
                "results": [
                    {
                        "id": "h_fact_1",
                        "text": "Hindsight active integration fact.",
                        "document_id": "cmem_hindsight",
                    }
                ]
            }

    monkeypatch.setattr(memory_os_module, "HindsightHttpClient", FakeHindsightClient)
    save_config(
        {
            "substrate_providers": {
                "hindsight": {
                    "enabled": True,
                    "api_url": "http://127.0.0.1:8888",
                    "bank_id": "bank",
                    "recall_mode": "active",
                }
            }
        },
        tmp_path,
    )
    provider = load_memory_provider("memory_os")
    provider.initialize("session-1", hermes_home=str(tmp_path), platform="cli", agent_identity="memoryos-test")

    context = provider.prefetch("active hindsight recall smoke")

    assert "### Substrate Recall" in context
    assert "Hindsight active integration fact." in context
    assert "[hindsight advisory; authority=derived_projection]" in context


def test_memory_os_status_tool_description_is_diagnostic_only():
    provider = load_memory_provider("memory_os")

    schemas = {schema["name"]: schema for schema in provider.get_tool_schemas()}
    description = schemas["memory_os_status"]["description"]
    contract = memory_os_status_tool_contract()

    assert description == contract["description"]
    assert "explicitly asks for current architecture" in description
    assert "provider/backend" in description
    assert "Do not use for ordinary chat" in description
    assert "opinions, feelings, design discussion" in description
    assert validate_memory_os_status_tool_description(description)["status"] == "ok"


def test_memory_os_review_reply_tool_prefers_structured_action_token():
    provider = load_memory_provider("memory_os")
    schemas = {schema["name"]: schema for schema in provider.get_tool_schemas()}
    schema = schemas["memory_os_review_reply"]

    assert schema["description"] == MEMORY_OS_REVIEW_REPLY_TOOL_DESCRIPTION
    assert "Use structured arguments only" in schema["description"]
    assert "action=`approve|reject|revoke|allow|feedback|apply`" in schema["description"]
    assert "apply" in schema["parameters"]["properties"]["action"]["enum"]
    assert "revoke" in schema["parameters"]["properties"]["action"]["enum"]
    assert "Do not send a free-form command string" in schema["description"]
    assert "display anchors such as A1/R1 without resolving" in schema["description"]
    assert "reply" not in schema["parameters"]["properties"]
    assert "action" in schema["parameters"]["properties"]
    assert "action_token" in schema["parameters"]["properties"]
    assert "too_mechanical" in schema["parameters"]["properties"]["rating"]["enum"]
    assert "off_voice" in schema["parameters"]["properties"]["rating"]["enum"]
    assert "owner_utterance" in schema["parameters"]["properties"]
    assert schema["parameters"]["required"] == ["action", "action_token"]


def test_owner_review_reply_guard_accepts_expression_feedback_rating():
    assert _looks_like_owner_review_reply("memory feedback oa_12345678 too_mechanical")
    assert _looks_like_owner_review_reply("反馈 oa_12345678 off_voice")
    assert _looks_like_owner_review_reply("memory revoke oa_12345678")


def test_memory_os_review_surface_tool_is_read_only_agent_surface():
    provider = load_memory_provider("memory_os")
    schemas = {schema["name"]: schema for schema in provider.get_tool_schemas()}
    schema = schemas["memory_os_review_surface"]

    assert schema["description"] == MEMORY_OS_REVIEW_SURFACE_TOOL_DESCRIPTION
    assert "Read bounded Memory-OS owner-review surface data" in schema["description"]
    assert "read-only" in schema["description"]
    assert "Hermes agent owns" in schema["description"]
    assert set(schema["parameters"]["properties"]["operation"]["enum"]) == {
        "overview",
        "page",
        "next_page",
        "detail",
        "proposal_followups",
        "expression_feedback_context",
        "memory_sources_feedback_context",
    }
    assert schema["parameters"]["required"] == ["operation"]


def test_system_prompt_routes_expression_reactions_to_review_reply_not_profile_memory(tmp_path):
    provider = load_memory_provider("memory_os")
    provider.initialize("session-1", hermes_home=str(tmp_path), platform="telegram", agent_identity="memoryos-test")

    prompt = provider.system_prompt_block()

    assert "If the owner reacts to the latest right-brain expression" in prompt
    assert "natural words such as `喜欢`" in prompt
    assert "like_expression" in prompt
    assert "labels, not action IDs" in prompt
    assert "ask them to pick/copy the tokenized option" in prompt
    assert "Do not call general memory/user/profile tools" in prompt
    assert "record tokenized expression feedback through `memory_os_review_reply`" in prompt


def test_system_prompt_forbids_owner_review_terminal_fallback(tmp_path):
    provider = load_memory_provider("memory_os")
    provider.initialize("session-1", hermes_home=str(tmp_path), platform="telegram", agent_identity="memoryos-test")

    prompt = provider.system_prompt_block()

    assert "Never handle Memory-OS owner-review tokens with terminal, execute_code, CLI fallback" in prompt
    assert "report the tool-schema mismatch and stop" in prompt
    assert "even if the same token appears already processed in conversation history" in prompt
    assert "Do not answer `already applied`" in prompt


def test_memory_os_status_tool_contract_has_chinese_and_mixed_fixtures():
    contract = memory_os_status_tool_contract()

    allowed_text = "\n".join(contract["allowed_prompt_examples"])
    disallowed_text = "\n".join(contract["disallowed_prompt_examples"])

    assert contract["schema_version"] == "memory-os.status_tool_contract.v0"
    assert "当前记忆架构是什么？" in allowed_text
    assert "memory provider" in allowed_text
    assert "你觉得这套记忆系统怎么样？" in disallowed_text
    assert "别像报告一样" in disallowed_text


def test_memory_os_status_tool_contract_rejects_broad_descriptions():
    report = validate_memory_os_status_tool_description(
        "Use memory_os_status whenever the user asks about the memory system, "
        "opinions, feelings, usefulness, or design discussion."
    )

    assert report["status"] == "fail"
    codes = {finding["code"] for finding in report["findings"]}
    assert "missing_required_boundary" in codes
    assert "forbidden_broad_trigger" in codes


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
    assert schema["prefetch_char_budget"]["default"] == 20000
    assert schema["hindsight_adapter_enabled"]["default"] is False
    assert schema["allow_full_local_capture"]["default"] is False
    assert schema["l4"]["default"]["kill_switch_enabled"] is False

    provider.save_config({"prefetch_char_budget": 1200}, str(tmp_path))

    saved = json.loads((tmp_path / "memory-os" / "config.json").read_text(encoding="utf-8"))
    assert saved["capture_policy"] == "summary_only"
    assert saved["prefetch_char_budget"] == 1200
    assert saved["hindsight_adapter_enabled"] is False
    assert saved["allow_full_local_capture"] is False
    assert saved["l4"]["kill_switch_enabled"] is False


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


def test_sync_turn_redacts_secrets_before_persisting_summary_and_index(tmp_path):
    provider = load_memory_provider("memory_os")
    provider.initialize("session-1", hermes_home=str(tmp_path), platform="cli", agent_identity="memoryos-test")
    user_secret = "sk-redaction-user-UNIQUE-20260601-aaaaaaaaaaaaaaaa"
    assistant_secret = "assistant-redaction-UNIQUE-20260601-bbbbbbbbbbbbbbbb"
    user_content = (
        "u" * 150
        + f" API_KEY={user_secret} password=RedactionPassword-UNIQUE-20260601 "
        + "tail text"
    )
    assistant_content = (
        f"Assistant summary with token: {assistant_secret} "
        "and api-key=AssistantHyphenSecret-UNIQUE-20260601."
    )

    provider.sync_turn(user_content, assistant_content, session_id="session-1")
    provider.shutdown()

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    events = MemoryOSStore(roots).read_events()
    assert len(events) == 1
    summary = events[0].summary
    assert "API_KEY=[redacted]" in summary
    assert "token: [redacted]" in summary
    for leaked in (
        user_secret,
        assistant_secret,
        "RedactionPassword-UNIQUE-20260601",
        "AssistantHyphenSecret-UNIQUE-20260601",
    ):
        assert leaked not in summary

    store = MemoryOSStore(roots)
    index = MemoryOSIndex(roots)
    index.sync_from_store(store)
    indexed_text = json.dumps(index.search("redaction UNIQUE", limit=10), ensure_ascii=False)
    assert user_secret not in indexed_text
    assert assistant_secret not in indexed_text
    assert "RedactionPassword-UNIQUE-20260601" not in indexed_text
    assert "AssistantHyphenSecret-UNIQUE-20260601" not in indexed_text


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
    assert "vector_available" in report
    assert isinstance(report["vector_available"], bool)
    assert "172.18.0.99" not in rendered
    assert "api_url" not in rendered
