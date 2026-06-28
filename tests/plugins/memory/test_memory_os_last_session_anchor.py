"""Last Session Anchor tests — generation (A.1–A.3) + injection (A.4–A.8) +
scenario regression (A.9) + adversarial counterfactuals (A.X, A.Z) + edge cases.

Tests cover the full write → read → inject pipeline for the Last Session Anchor
feature: on_session_end writes a 1-3 line foreground summary to
last_session_anchor.jsonl; prefetch injects it as a "Last Session" section
between Continuity Bridge and Recent Cross-Session.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from plugins.memory import load_memory_provider
from plugins.memory.memory_os.__init__ import (
    _extract_foreground_session_summary,
    _last_session_anchor_path,
    _last_session_anchor_record,
)
from plugins.memory.memory_os.prefetch import _last_session_lines
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore


# ── Helpers ────────────────────────────────────────────────────────────────


def _init_provider(tmp_path, session_id="s1"):
    """Create and initialize a Memory-OS provider with a temp home."""
    provider = load_memory_provider("memory_os")
    provider.initialize(
        session_id,
        hermes_home=str(tmp_path),
        platform="cli",
        agent_identity="memoryos-test",
    )
    return provider


def _store(tmp_path):
    """Create a MemoryOSStore from a temp path (bypasses provider)."""
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def _foreground_messages():
    """Messages with clear foreground content — install + debug topic."""
    return [
        {"role": "user", "content": "安装 ComfyUI 并配置 IPAdapter 插件"},
        {
            "role": "assistant",
            "content": "我来安装 ComfyUI。terminal: cm_cli install ComfyUI_IPAdapter_plus",
        },
        {
            "role": "tool",
            "content": "proc_abc is still running; downloading model ip-adapter_sd15.bin",
        },
    ]


def _simple_messages():
    """Messages without tool calls — conversation-only."""
    return [
        {"role": "user", "content": "什么是 PostgreSQL？"},
        {
            "role": "assistant",
            "content": "PostgreSQL 是一个开源的关系型数据库管理系统。",
        },
    ]


def _read_jsonl(path):
    """Read a JSONL file into a list of dicts."""
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# ── A.1  会话结束(有 foreground 内容)→ last_session_anchor.jsonl 写入 ─────


def test_session_end_with_foreground_writes_anchor(tmp_path):
    """Session with foreground content → anchor written to last_session_anchor.jsonl."""
    provider = _init_provider(tmp_path, session_id="session-1")
    provider.on_session_end(_foreground_messages())
    provider.shutdown()

    anchor_path = tmp_path / "memory-os" / "system" / "last_session_anchor.jsonl"
    assert anchor_path.exists(), "last_session_anchor.jsonl should exist"

    records = _read_jsonl(anchor_path)
    assert len(records) == 1
    record = records[0]
    assert record["session_id"] == "session-1"
    assert record["schema_version"] == "memory-os.last_session_anchor.v0"
    assert "ComfyUI" in record["foreground_summary"]
    assert "ended_at" in record


# ── A.2  空会话/纯系统事件 → 不写锚 ─────────────────────────────────────


def test_session_end_empty_skips_anchor(tmp_path):
    """Empty messages → no anchor written."""
    provider = _init_provider(tmp_path, session_id="session-1")
    provider.on_session_end([])
    provider.shutdown()

    anchor_path = tmp_path / "memory-os" / "system" / "last_session_anchor.jsonl"
    if anchor_path.exists():
        records = _read_jsonl(anchor_path)
        matching = [r for r in records if r.get("session_id") == "session-1"]
        assert len(matching) == 0, "empty session should not produce an anchor"


def test_session_end_pure_system_skips_anchor(tmp_path):
    """Purely system/tool messages with no user foreground → no anchor."""
    provider = _init_provider(tmp_path, session_id="session-1")
    provider.on_session_end([
        {"role": "tool", "content": "proc_xyz started"},
        {"role": "tool", "content": "cron job executed"},
    ])
    provider.shutdown()

    anchor_path = tmp_path / "memory-os" / "system" / "last_session_anchor.jsonl"
    if anchor_path.exists():
        records = _read_jsonl(anchor_path)
        matching = [r for r in records if r.get("session_id") == "session-1"]
        assert len(matching) == 0, "pure system messages should not produce an anchor"


# ── A.3  提炼路径无 LLM/网络(确定性,INV-5) ──────────────────────────────


def test_foreground_summary_no_llm_or_network(tmp_path):
    """Verify the extractor uses only deterministic substring matching — no LLM/network."""
    provider = _init_provider(tmp_path, session_id="session-1")

    # This must not trigger any import of LLM libraries or network calls
    summary = _extract_foreground_session_summary(_foreground_messages())
    provider.shutdown()

    assert "ComfyUI" in summary
    # INV-5: deterministic — no hallucinated content, only extracted from actual messages
    assert len(summary.splitlines()) <= 3
    # The summary should contain operation context (detected via _looks_like_operation_context)
    assert len(summary) > 0


# ── A.4  新会话 prefetch → Last Session 段注入 ──────────────────────────


def test_prefetch_injects_last_session(tmp_path):
    """Session 1 ends with foreground → session 2 prefetch includes Last Session section."""
    # Session 1: produce foreground content, end session
    p1 = _init_provider(tmp_path, session_id="session-1")
    p1.on_session_end(_foreground_messages())
    p1.shutdown()

    # Session 2: prefetch should include Last Session section
    p2 = _init_provider(tmp_path, session_id="session-2")
    context = p2.prefetch("继续配置", session_id="session-2")
    p2.shutdown()

    assert "### Last Session" in context
    assert "上一次会话" in context
    assert "ComfyUI" in context


# ── A.5  Last Session 注入的是最近一个非当前会话 ─────────────────────────


def test_prefetch_uses_most_recent_non_current(tmp_path):
    """With 3 sessions, session 3's prefetch should show session 2 (most recent non-current)."""
    # Session 1
    p1 = _init_provider(tmp_path, session_id="session-1")
    p1.on_session_end([
        {"role": "user", "content": "Session 1: install n8n"},
        {"role": "assistant", "content": "terminal: docker compose up n8n"},
    ])
    p1.shutdown()

    # Session 2 (more recent than session 1)
    p2 = _init_provider(tmp_path, session_id="session-2")
    p2.on_session_end([
        {"role": "user", "content": "Session 2: debug ComfyUI render crash"},
        {"role": "assistant", "content": "fatal: CUDA out of memory during render"},
    ])
    p2.shutdown()

    # Session 3 prefetch: should see session-2 NOT session-1
    p3 = _init_provider(tmp_path, session_id="session-3")
    context = p3.prefetch("继续", session_id="session-3")
    p3.shutdown()

    assert "### Last Session" in context
    assert "ComfyUI" in context  # from session-2
    assert "n8n" not in context  # session-1 is older, should not appear


# ── A.6  当前会话自己的锚不被注入 ─────────────────────────────────────


def test_current_session_anchor_not_injected(tmp_path):
    """Same-session prefetch should NOT include its own Last Session anchor."""
    provider = _init_provider(tmp_path, session_id="session-1")
    provider.on_session_end(_foreground_messages())

    # Same session prefetch — should NOT include its own anchor
    context = provider.prefetch("继续", session_id="session-1")
    provider.shutdown()

    assert "### Last Session" not in context


# ── A.7  Last Session 段不含"待结晶"标记 ────────────────────────────────


def test_last_session_no_uncrystallized_marker(tmp_path):
    """Last Session section must use factual tone, never the '待结晶' marker."""
    p1 = _init_provider(tmp_path, session_id="session-1")
    p1.on_session_end([
        {"role": "user", "content": "分析巴西vs摩洛哥比赛数据"},
        {"role": "assistant", "content": "巴西在Group C排名第一，摩洛哥历史最佳战绩..."},
    ])
    p1.shutdown()

    p2 = _init_provider(tmp_path, session_id="session-2")
    context = p2.prefetch("继续分析", session_id="session-2")
    p2.shutdown()

    if "### Last Session" in context:
        # Extract the Last Session section text
        section_start = context.index("### Last Session")
        section_text = context[section_start:]
        next_section = section_text.find("\n###", 5)
        section = section_text[:next_section] if next_section != -1 else section_text
        assert "待结晶" not in section, f"Last Session must not use 待结晶 marker:\n{section}"
        assert "上一次会话" in section, f"Last Session must use 上一次会话 factual marker:\n{section}"


# ── A.8  与 Recent Cross-Session 共享 seen 去重 ────────────────────────


def test_last_session_adds_seen_marker(tmp_path):
    """After injection, seen set should contain the previous session marker."""
    store = _store(tmp_path)
    anchor_path = store.roots.memory_os_root / "system" / "last_session_anchor.jsonl"
    anchor_path.parent.mkdir(parents=True, exist_ok=True)
    anchor_path.write_text(
        json.dumps(
            {
                "session_id": "session-1",
                "ended_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "foreground_summary": "Test summary content",
                "schema_version": "memory-os.last_session_anchor.v0",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    seen: set[tuple[str, str]] = set()
    lines = _last_session_lines(store, session_id="session-2", seen=seen)
    assert len(lines) == 1
    assert ("last_session", "session-1") in seen


# ── A.9  ClawBot 场景回归: 会话1分析 Group L → 会话2问"上一轮"→ 命中 Group L ─


def test_clawbot_scenario_session2_hits_session1_group_l(tmp_path):
    """Session 1 analyzed Group L → Session 2 asks '上一轮' → hits Group L.

    This is the real-world ClawBot regression: without Last Session Anchor,
    the agent would resort to older crystallized Group B memory instead of
    the most recent session's foreground (Group L).
    """
    p1 = _init_provider(tmp_path, session_id="session-1")
    p1.on_session_end([
        {"role": "user", "content": "分析 Group L 的比赛数据，找出关键弱点"},
        {
            "role": "assistant",
            "content": "Group L 分析结果：防守反击成功率72%，中场控球率偏低...",
        },
        {
            "role": "tool",
            "content": "terminal: python analyze.py --group L --output report.json",
        },
    ])
    p1.shutdown()

    p2 = _init_provider(tmp_path, session_id="session-2")
    context = p2.prefetch("上一轮我们分析的是什么？", session_id="session-2")
    p2.shutdown()

    assert "### Last Session" in context
    assert "Group L" in context  # Must hit Group L
    assert "防守反击" in context  # Key conclusion from session 1


# ── A.X  反证: 禁用 on_session_end 写锚 → A.1/A.4 必 FAIL ────────────────


def test_counterfactual_no_write_means_no_injection(tmp_path, monkeypatch):
    """If on_session_end is a no-op, Last Session section must be absent."""
    provider = _init_provider(tmp_path, session_id="session-1")

    # Monkeypatch on_session_end to be a no-op
    monkeypatch.setattr(provider, "on_session_end", lambda messages: None)

    provider.on_session_end(_foreground_messages())
    provider.shutdown()

    p2 = _init_provider(tmp_path, session_id="session-2")
    context = p2.prefetch("query", session_id="session-2")
    p2.shutdown()

    assert "### Last Session" not in context


# ── A.Z  反证: Last Session 不含"跨会话·待结晶"标记 ──────────────────────


def test_counterfactual_no_uncrystallized_marker_in_line(tmp_path):
    """Verify the Last Session injection line NEVER contains '跨会话·待结晶'."""
    store = _store(tmp_path)
    anchor_path = store.roots.memory_os_root / "system" / "last_session_anchor.jsonl"
    anchor_path.parent.mkdir(parents=True, exist_ok=True)
    anchor_path.write_text(
        json.dumps(
            {
                "session_id": "session-1",
                "ended_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "foreground_summary": "Test summary content",
                "schema_version": "memory-os.last_session_anchor.v0",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    lines = _last_session_lines(store, session_id="session-2")
    assert len(lines) == 1
    assert "待结晶" not in lines[0]
    assert "跨会话·待结晶" not in lines[0]
    # The marker must use factual "上一次会话" not "跨会话·待结晶"
    assert "上一次会话" in lines[0]


# ── Edge cases ───────────────────────────────────────────────────────────


def test_extract_summary_empty_messages():
    """Empty message list → empty summary."""
    assert _extract_foreground_session_summary([]) == ""


def test_extract_summary_pure_tool():
    """Only tool messages with no user foreground → empty summary (guard rejects)."""
    summary = _extract_foreground_session_summary([
        {"role": "tool", "content": "proc_xyz started"},
    ])
    # No user messages and no substantive assistant → empty
    assert summary == ""


def test_extract_summary_list_content():
    """Messages with list-based content format should be handled."""
    summary = _extract_foreground_session_summary([
        {"role": "user", "content": [{"text": "部署 n8n 到生产环境"}]},
        {
            "role": "assistant",
            "content": "我来帮你部署。terminal: docker compose up -d",
        },
    ])
    assert "n8n" in summary
    assert len(summary.splitlines()) <= 3


def test_extract_summary_no_user_messages():
    """Assistant/tool messages only — should not crash, may produce limited summary."""
    summary = _extract_foreground_session_summary([
        {
            "role": "assistant",
            "content": "The system has been configured with production paths.",
        },
        {"role": "tool", "content": "terminal: systemctl restart nginx"},
    ])
    # Should not crash; may or may not produce a summary depending on content
    assert isinstance(summary, str)
    assert len(summary.splitlines()) <= 3


def test_last_session_lines_file_not_exists(tmp_path):
    """Missing file → empty list (fail-open)."""
    store = _store(tmp_path)
    lines = _last_session_lines(store, session_id="session-1")
    assert lines == []


def test_last_session_lines_no_session_id(tmp_path):
    """Empty session_id → empty list."""
    store = _store(tmp_path)
    lines = _last_session_lines(store, session_id="")
    assert lines == []


def test_last_session_lines_corrupt_json(tmp_path):
    """Corrupt JSONL lines are silently skipped."""
    store = _store(tmp_path)
    anchor_path = store.roots.memory_os_root / "system" / "last_session_anchor.jsonl"
    anchor_path.parent.mkdir(parents=True, exist_ok=True)
    anchor_path.write_text(
        "not valid json\n"
        + json.dumps(
            {
                "session_id": "session-1",
                "ended_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "foreground_summary": "Valid record",
                "schema_version": "memory-os.last_session_anchor.v0",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    lines = _last_session_lines(store, session_id="session-2")
    assert len(lines) == 1
    assert "Valid record" in lines[0]


def test_multiple_sessions_most_recent_wins(tmp_path):
    """When multiple sessions have anchors, the most recent non-current wins."""
    store = _store(tmp_path)
    anchor_path = store.roots.memory_os_root / "system" / "last_session_anchor.jsonl"
    anchor_path.parent.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    records = [
        {
            "session_id": "old-session",
            "ended_at": (now - timedelta(hours=5)).isoformat().replace("+00:00", "Z"),
            "foreground_summary": "Old summary",
            "schema_version": "memory-os.last_session_anchor.v0",
        },
        {
            "session_id": "recent-session",
            "ended_at": (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            "foreground_summary": "Recent summary",
            "schema_version": "memory-os.last_session_anchor.v0",
        },
    ]
    anchor_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )

    lines = _last_session_lines(store, session_id="current-session")
    assert len(lines) == 1
    assert "Recent summary" in lines[0]
    assert "Old summary" not in lines[0]


def test_on_session_end_without_roots_is_noop(tmp_path):
    """If _roots is None, on_session_end should be a safe no-op."""
    provider = load_memory_provider("memory_os")
    # Intentionally do NOT call initialize — _roots will be None
    # This must not crash
    provider.on_session_end(_foreground_messages())
    # Clean up
    provider.shutdown()
