from plugins.memory import load_memory_provider
from plugins.memory.memory_os.config import save_config
from plugins.memory.memory_os.prefetch import build_prefetch
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore


def _store(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def test_provider_on_pre_compress_returns_bounded_current_task_anchor(tmp_path):
    provider = load_memory_provider("memory_os")
    provider.initialize("session-1", hermes_home=str(tmp_path), platform="telegram", agent_identity="memoryos-test")

    anchor = provider.on_pre_compress(
        [
            {"role": "user", "content": "你了解我们记忆系统吗？"},
            {"role": "assistant", "content": "Memory-OS / Hindsight status discussion."},
            {"role": "user", "content": "你直接安装 ComfyUI 必须装和建议装的插件"},
            {"role": "assistant", "content": 'terminal: "cm_cli install ComfyUI_IPAdapter_plus --no-deps"'},
            {"role": "tool", "content": "proc_abc is still running; downloading clip_vision_h.safetensors"},
        ]
    )
    provider.shutdown()

    assert "Memory-OS Current Task Anchor" in anchor
    assert "ComfyUI" in anchor
    assert "cm_cli install ComfyUI_IPAdapter_plus" in anchor
    assert "proc_abc" in anchor
    assert "Hindsight status discussion" not in anchor
    assert len(anchor) <= 1200


def test_provider_system_prompt_block_exposes_current_task_anchor_after_pre_compress(tmp_path):
    provider = load_memory_provider("memory_os")
    provider.initialize("session-1", hermes_home=str(tmp_path), platform="telegram", agent_identity="memoryos-test")

    provider.on_pre_compress(
        [
            {"role": "user", "content": "安装 ComfyUI Impact Pack，失败后只汇总失败原因和下一步"},
            {"role": "assistant", "content": 'terminal: "git clone https://github.com/ltdrdata/ComfyUI-Impact-Pack.git"'},
            {"role": "tool", "content": "fatal: unable to access github.com: Could not connect to server"},
        ]
    )

    prompt_block = provider.system_prompt_block()
    provider.shutdown()

    assert "Memory-OS Current Task Anchor" in prompt_block
    assert "ComfyUI Impact Pack" in prompt_block
    assert "Could not connect to server" in prompt_block
    assert "Do not switch back to unrelated historical memory topics" in prompt_block


def test_prefetch_can_place_current_task_anchor_above_memory_layers(tmp_path):
    store = _store(tmp_path)

    context = build_prefetch(
        "继续当前任务",
        budget_chars=2200,
        store=store,
        index=None,
        current_task_anchor="Current task: finish ComfyUI plugin installation and report success/failure/retry.",
    )

    assert context.startswith("## Memory-OS Context")
    assert "### Current Foreground Task" in context
    assert "finish ComfyUI plugin installation" in context


def test_provider_prefetch_includes_current_task_anchor_after_pre_compress(tmp_path):
    provider = load_memory_provider("memory_os")
    provider.initialize("session-1", hermes_home=str(tmp_path), platform="telegram", agent_identity="memoryos-test")
    provider.on_pre_compress(
        [
            {"role": "user", "content": "安装 ComfyUI Impact Pack"},
            {"role": "tool", "content": "fatal: unable to access github.com"},
        ]
    )

    context = provider.prefetch("继续当前任务", session_id="session-1")
    provider.shutdown()

    assert "### Current Foreground Task" in context
    assert "ComfyUI Impact Pack" in context
    assert "fatal: unable to access github.com" in context


def test_cancellation_query_does_not_pivot_to_background_memory(tmp_path):
    provider = load_memory_provider("memory_os")
    provider.initialize("session-1", hermes_home=str(tmp_path), platform="telegram", agent_identity="memoryos-test")
    provider.on_pre_compress(
        [
            {"role": "user", "content": "剪一个 ComfyUI 教程视频，修掉内容消失的问题"},
            {"role": "assistant", "content": "terminal: ffmpeg render tutorial clip"},
            {"role": "tool", "content": "render produced bad crop"},
        ]
    )
    provider._store.write_working_document(
        "lingering",
        {
            "schema_version": "memory-os.working.v0",
            "updated_at": "2026-05-22T00:00:00+00:00",
            "items": [
                {
                    "kind": "lingering",
                    "text": "Hindsight / hermes02 legacy memory architecture discussion should not appear here.",
                    "source_event_id": "evt-hindsight",
                    "weight": 0.8,
                    "updated_at": "2026-05-22T00:00:00+00:00",
                }
            ],
        },
    )

    context = provider.prefetch("太垃圾了，算了，你还是别做视频了", session_id="session-1")
    prompt_block = provider.system_prompt_block()
    provider.shutdown()

    assert "### Current Foreground Task" in context
    assert "owner cancelled" in context
    assert "Do not pivot to unrelated system-memory" in context
    assert "Conversation Carryover" not in context
    assert "Working Memory" not in context
    assert "Hindsight" not in context
    assert "hermes02" not in context
    assert "owner cancelled" in prompt_block


def test_continue_query_after_anchor_uses_foreground_only_prefetch(tmp_path):
    provider = load_memory_provider("memory_os")
    provider.initialize("session-1", hermes_home=str(tmp_path), platform="telegram", agent_identity="memoryos-test")
    provider.on_pre_compress(
        [
            {"role": "user", "content": "安装 ComfyUI Impact Pack"},
            {"role": "tool", "content": "fatal: unable to access github.com"},
        ]
    )
    provider._store.write_working_document(
        "lingering",
        {
            "schema_version": "memory-os.working.v0",
            "updated_at": "2026-05-22T00:00:00+00:00",
            "items": [
                {
                    "kind": "lingering",
                    "text": "Unrelated Hindsight background should not compete with current task.",
                    "source_event_id": "evt-bg",
                    "weight": 0.8,
                    "updated_at": "2026-05-22T00:00:00+00:00",
                }
            ],
        },
    )

    context = provider.prefetch("继续当前任务", session_id="session-1")
    provider.shutdown()

    assert "### Current Foreground Task" in context
    assert "ComfyUI Impact Pack" in context
    assert "Working Memory" not in context
    assert "Hindsight" not in context


def test_deictic_yesterday_continue_routes_deferred_task_as_low_clue_candidate(tmp_path):
    save_config(
        {
            "context_router": {"enabled": True, "mode": "apply", "apply_routes": ["all"]},
            "low_clue_recall": {"enabled": True, "llm_judge": {"enabled": False, "mode": "none"}},
            "memory_sources": {"enabled": True},
        },
        tmp_path,
    )
    provider = load_memory_provider("memory_os")
    provider.initialize("session-1", hermes_home=str(tmp_path), platform="telegram", agent_identity="memoryos-test")
    provider.on_pre_compress(
        [
            {"role": "user", "content": "继续处理 ComfyUI 的视频问题"},
            {"role": "assistant", "content": "terminal: hyperframes inspect"},
            {"role": "tool", "content": "layout_report.json failed: No composition found"},
        ]
    )
    provider._store.write_working_document(
        "lingering",
        {
            "schema_version": "memory-os.working.v0",
            "updated_at": "2026-05-24T00:00:00+00:00",
            "items": [
                {
                    "kind": "lingering",
                    "text": "Unrelated n8n AI agent orchestration discussion should not win a deferred task resume.",
                    "source_event_id": "evt-n8n",
                    "weight": 0.8,
                    "updated_at": "2026-05-24T00:00:00+00:00",
                }
            ],
        },
    )

    deferred_context = provider.prefetch("这个先放一下，明天再说。", session_id="session-1")
    provider.shutdown()

    resumed = load_memory_provider("memory_os")
    resumed.initialize("session-2", hermes_home=str(tmp_path), platform="telegram", agent_identity="memoryos-test")
    resume_context = resumed.prefetch("继续昨天那个。", session_id="session-2")
    resumed.shutdown()

    assert "### Current Foreground Task" in deferred_context
    assert "deferred" in deferred_context.lower()
    assert "### Recall Clarification Guard" in resume_context
    assert "Plausible recall candidates" in resume_context
    assert "ComfyUI" in resume_context
    assert "deferred" in resume_context.lower()
    assert "Continue this deferred foreground task" not in resume_context
    assert "Working Memory" not in resume_context
    assert "current task: 继续昨天那个" not in resumed.system_prompt_block()


def test_explicit_deferred_task_resume_still_uses_foreground_only(tmp_path):
    save_config(
        {
            "context_router": {"enabled": True, "mode": "apply", "apply_routes": ["all"]},
            "memory_sources": {"enabled": True},
        },
        tmp_path,
    )
    provider = load_memory_provider("memory_os")
    provider.initialize("session-1", hermes_home=str(tmp_path), platform="telegram", agent_identity="memoryos-test")
    provider.on_pre_compress(
        [
            {"role": "user", "content": "继续处理 ComfyUI 的视频问题"},
            {"role": "tool", "content": "layout_report.json failed: No composition found"},
        ]
    )
    provider.prefetch("这个先放一下，明天再说。", session_id="session-1")
    provider.shutdown()

    resumed = load_memory_provider("memory_os")
    resumed.initialize("session-2", hermes_home=str(tmp_path), platform="telegram", agent_identity="memoryos-test")
    resume_context = resumed.prefetch("continue the deferred task", session_id="session-2")
    resumed.shutdown()
    source_records = (tmp_path / "memory-os" / "system" / "memory_sources.jsonl").read_text(encoding="utf-8")

    assert "### Current Foreground Task" in resume_context
    assert "ComfyUI" in resume_context
    assert "Continue this deferred foreground task" in resume_context
    assert "Recall Clarification Guard" not in resume_context
    assert '"route": "foreground_control"' in source_records
    assert "explicit_deferred_resume" in source_records


def test_chinese_explicit_deferred_task_resume_uses_matching_foreground_attribution(tmp_path):
    save_config(
        {
            "context_router": {"enabled": True, "mode": "apply", "apply_routes": ["all"]},
            "memory_sources": {"enabled": True},
        },
        tmp_path,
    )
    provider = load_memory_provider("memory_os")
    provider.initialize("session-1", hermes_home=str(tmp_path), platform="telegram", agent_identity="memoryos-test")
    provider.on_pre_compress(
        [
            {"role": "user", "content": "继续处理 ComfyUI 的视频问题"},
            {"role": "tool", "content": "layout_report.json failed: No composition found"},
        ]
    )
    provider.prefetch("这个先放一下，明天再说。", session_id="session-1")
    provider.shutdown()

    resumed = load_memory_provider("memory_os")
    resumed.initialize("session-2", hermes_home=str(tmp_path), platform="telegram", agent_identity="memoryos-test")
    resume_context = resumed.prefetch("继续搁置的任务", session_id="session-2")
    resumed.shutdown()
    source_records = (tmp_path / "memory-os" / "system" / "memory_sources.jsonl").read_text(encoding="utf-8")

    assert "### Current Foreground Task" in resume_context
    assert "ComfyUI" in resume_context
    assert "Recall Clarification Guard" not in resume_context
    assert '"route": "foreground_control"' in source_records
    assert "explicit_deferred_resume" in source_records


def test_deferred_continue_without_record_asks_for_clarification(tmp_path):
    save_config(
        {
            "context_router": {"enabled": True, "mode": "apply", "apply_routes": ["all"]},
            "low_clue_recall": {"enabled": True, "llm_judge": {"enabled": False, "mode": "none"}},
        },
        tmp_path,
    )
    provider = load_memory_provider("memory_os")
    provider.initialize("session-1", hermes_home=str(tmp_path), platform="telegram", agent_identity="memoryos-test")
    provider._store.write_working_document(
        "lingering",
        {
            "schema_version": "memory-os.working.v0",
            "updated_at": "2026-05-24T00:00:00+00:00",
            "items": [
                {
                    "kind": "lingering",
                    "text": "Recent n8n AI agent orchestration discussion should not be assumed for vague yesterday resume.",
                    "source_event_id": "evt-n8n",
                    "weight": 0.8,
                    "updated_at": "2026-05-24T00:00:00+00:00",
                }
            ],
        },
    )

    context = provider.prefetch("继续昨天那个。", session_id="session-1")
    provider.shutdown()

    assert "### Recall Clarification Guard" in context
    assert "Plausible recall candidates" in context
    assert "n8n" in context
    assert "Working Memory" not in context
    assert "current task: 继续昨天那个" not in provider.system_prompt_block()


def test_current_task_anchor_redacts_secrets(tmp_path):
    provider = load_memory_provider("memory_os")
    provider.initialize("session-1", hermes_home=str(tmp_path), platform="telegram", agent_identity="memoryos-test")

    anchor = provider.on_pre_compress(
        [
            {"role": "user", "content": "部署脚本，api_key=SHOULD_NOT_LEAK token: ALSO_SECRET"},
            {"role": "assistant", "content": "terminal: deploy with password=NOPE"},
        ]
    )
    provider.shutdown()

    assert "SHOULD_NOT_LEAK" not in anchor
    assert "ALSO_SECRET" not in anchor
    assert "NOPE" not in anchor
    assert "[redacted]" in anchor
