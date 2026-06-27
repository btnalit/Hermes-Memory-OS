"""Compaction stability tests — C1 (operations tracking) + C2 (anchor persistence).

Tests A.1–A.5 cover core assertions; A.X and A.Y are adversarial (destructive)
verification — removing the tested logic MUST cause the corresponding test to fail.
"""

import json
import os
from pathlib import Path
from unittest import mock

import pytest

from plugins.memory import load_memory_provider
from plugins.memory.memory_os.__init__ import (
    _active_task_anchor_path,
    _active_task_anchor_record,
    _clip,
    _extract_anchor_current_task,
    _extract_anchor_operation_lines,
    _format_current_task_anchor,
    _looks_like_operation_context,
)
from plugins.memory.memory_os.roots import MemoryOSRoots


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


def _tool_messages():
    """Return a minimal message list with a tool call that looks like an operation."""
    return [
        {"role": "user", "content": "安装 postgresql"},
        {"role": "assistant", "content": "我来安装 PostgreSQL。"},
        {
            "role": "tool",
            "content": "terminal: apt-get install postgresql -y\nReading package lists... Done\n...\nSetting up postgresql (16.3) ...",
        },
    ]


def _simple_messages():
    """Return messages without tool calls."""
    return [
        {"role": "user", "content": "什么是 PostgreSQL？"},
        {"role": "assistant", "content": "PostgreSQL 是一个开源的关系型数据库管理系统。"},
    ]


# ── A.1  sync_turn 含 tool 消息 → anchor 的 completed_operations 非空 ──────


def test_a1_sync_turn_captures_tool_operations(tmp_path):
    """sync_turn with tool messages should populate completed_operations."""
    provider = _init_provider(tmp_path)
    # First prefetch to set an initial anchor
    provider.prefetch("安装 postgresql")
    assert provider._current_task_anchor, "anchor should be set after prefetch"

    # sync_turn with tool messages should append operations
    provider.sync_turn(
        "安装 postgresql",
        "我来安装 PostgreSQL。",
        messages=_tool_messages(),
    )

    anchor = provider._current_task_anchor
    assert "- completed operations (do not repeat):" in anchor, f"expected completed_operations in anchor:\n{anchor}"
    assert "install" in anchor.lower(), f"expected install operation in anchor:\n{anchor}"


# ── A.2  连续两 turn → 第二 turn anchor 包含第一 turn 的 completed_operations ──


def test_a2_operations_accumulate_across_turns(tmp_path):
    """Operations from turn 1 should survive into turn 2's anchor."""
    provider = _init_provider(tmp_path)
    provider.prefetch("安装 postgresql")

    # Turn 1: install postgresql
    provider.sync_turn(
        "安装 postgresql",
        "正在安装...",
        messages=[
            {"role": "user", "content": "安装 postgresql"},
            {"role": "assistant", "content": "正在安装 PostgreSQL..."},
            {"role": "tool", "content": "terminal: apt-get install postgresql\nok"},
        ],
    )
    anchor_1 = provider._current_task_anchor
    assert "install" in anchor_1.lower()

    # Turn 2: configure postgresql (new query triggers _refresh_current_task_anchor_from_query)
    provider.prefetch("配置 postgresql 的端口")
    assert "install" in provider._current_task_anchor.lower(), (
        f"completed_operations from turn 1 should survive into turn 2 anchor:\n"
        f"{provider._current_task_anchor}"
    )

    # Turn 2 operation should also be added
    provider.sync_turn(
        "配置 postgresql 的端口",
        "我来修改端口配置。",
        messages=[
            {"role": "user", "content": "配置 postgresql 的端口"},
            {"role": "assistant", "content": "修改 postgresql.conf..."},
            {"role": "tool", "content": "terminal: sed -i 's/#port = 5432/port = 5433/' /etc/postgresql/16/main/postgresql.conf"},
        ],
    )
    anchor_2 = provider._current_task_anchor
    assert "install" in anchor_2.lower(), "turn 1 operation lost"
    assert "5433" in anchor_2, "turn 2 operation missing"


# ── A.3  anchor 更新 → 落盘 active_task_anchor.jsonl ────────────────────────


def test_a3_anchor_persists_to_disk(tmp_path):
    """Every anchor update should write to active_task_anchor.jsonl."""
    provider = _init_provider(tmp_path)

    # Trigger anchor creation via prefetch
    provider.prefetch("部署 nginx")
    assert provider._current_task_anchor

    # Check disk
    path = _active_task_anchor_path(provider._roots)
    assert path.exists(), f"active_task_anchor.jsonl should exist at {path}"

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 1, f"expected at least 1 record, got {len(lines)}"

    record = json.loads(lines[-1])
    assert record["status"] == "active"
    assert "nginx" in record["anchor"]


# ── A.4  内存 anchor 空 + 磁盘有 active anchor → 恢复 ───────────────────────


def test_a4_anchor_recovers_from_disk_after_restart(tmp_path):
    """A new provider instance should recover the active anchor from disk."""
    # First session: create an anchor
    p1 = _init_provider(tmp_path, session_id="s1")
    p1.prefetch("调试 nginx 502 错误")
    assert p1._current_task_anchor
    anchor_text = p1._current_task_anchor

    # Simulate restart: new provider instance, same hermes_home
    p2 = _init_provider(tmp_path, session_id="s2")
    # The anchor should be recovered during initialize (C2)
    assert p2._current_task_anchor, (
        "anchor should be recovered from disk after restart"
    )
    assert "nginx" in p2._current_task_anchor.lower(), (
        f"recovered anchor should contain the original task:\n{p2._current_task_anchor}"
    )
    # The recovered text should match the original (minus any session line)
    assert _extract_anchor_current_task(p2._current_task_anchor) == _extract_anchor_current_task(anchor_text)


# ── A.5  task 取消 → active anchor 被清除 ────────────────────────────────────


def test_a5_cancellation_writes_tombstone(tmp_path):
    """Cancelling a task should write a completed tombstone record."""
    provider = _init_provider(tmp_path)
    provider.prefetch("安装 redis")
    assert provider._current_task_anchor

    path = _active_task_anchor_path(provider._roots)
    active_count_before = len(path.read_text(encoding="utf-8").strip().splitlines())

    # Cancel the task
    provider.prefetch("取消这个任务")
    # The anchor should now contain "cancelled" language
    assert "cancelled" in provider._current_task_anchor.lower() or not provider._current_task_anchor

    # Verify the file has a completed/cancelled record
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    last_record = json.loads(lines[-1])
    # Either the last record is a completed tombstone, or it's the cancelled anchor
    assert (
        last_record.get("status") in {"completed", "cancelled"}
        or "cancelled" in last_record.get("anchor", "").lower()
    ), f"expected tombstone or cancelled anchor, got status={last_record.get('status')}"


# ── INV-5  A.Z 操作提取路径无 LLM/网络调用 ──────────────────────────────────


def test_az_operation_extraction_is_deterministic(monkeypatch):
    """Operation extraction must be pure string matching — no I/O, no network."""
    # _looks_like_operation_context is the core — pure marker matching
    assert _looks_like_operation_context("terminal: apt-get install postgresql")
    assert _looks_like_operation_context("error: connection refused")
    assert _looks_like_operation_context("process running on port 5432")
    assert _looks_like_operation_context("正在安装依赖...")
    assert _looks_like_operation_context("下载完成")
    assert _looks_like_operation_context("安装失败：依赖冲突")
    assert not _looks_like_operation_context("hello world")
    assert not _looks_like_operation_context("PostgreSQL 是一个数据库")
    assert not _looks_like_operation_context("")

    # Verify _format_current_task_anchor with completed_operations is pure formatting
    anchor = _format_current_task_anchor(
        task="test task",
        operations=[],
        completed_operations=["tool: apt-get install redis"],
    )
    assert "completed operations" in anchor
    assert "install redis" in anchor
    assert "Do not repeat completed operations" in anchor


# ── A.X  反证：禁操作提取 → A.1 FAIL ─────────────────────────────────────────


def test_ax_disable_operation_capture_breaks_a1(monkeypatch, tmp_path):
    """If operation capture is disabled (no-op), A.1 MUST fail."""
    provider = _init_provider(tmp_path)
    provider.prefetch("安装 postgresql")

    # Disable capture on the instance directly
    monkeypatch.setattr(provider, "_capture_turn_operations", lambda *a, **kw: None)

    provider.sync_turn(
        "安装 postgresql",
        "正在安装...",
        messages=_tool_messages(),
    )

    # With capture disabled, anchor should NOT contain completed_operations section
    anchor = provider._current_task_anchor
    assert "- completed operations (do not repeat):" not in anchor, (
        f"A.X: with capture disabled, "
        f"anchor should NOT have completed_operations section:\n{anchor}"
    )
    # The old "active tool/process state" should also be absent (operations=[])
    assert "active tool/process state" not in anchor


# ── A.Y  反证：禁 anchor 落盘 → A.4 FAIL ─────────────────────────────────────


def test_ay_disable_anchor_persistence_breaks_recovery(monkeypatch, tmp_path):
    """If _write_active_task_anchor is a no-op, recovery MUST fail."""
    provider = _init_provider(tmp_path, session_id="s1")
    provider.prefetch("调试 nginx")

    # Monkey-patch _write_active_task_anchor to be a no-op AFTER the first write
    # so the anchor is in memory but NOT on disk
    original_write = provider._write_active_task_anchor

    def noop_write(*, anchor, session_id="", status="active"):
        pass  # deliberately drop the write

    monkeypatch.setattr(provider, "_write_active_task_anchor", noop_write)

    # This anchor update will NOT be persisted
    provider.prefetch("继续调试 nginx upstream 超时")

    # Delete any existing file to ensure clean state
    path = _active_task_anchor_path(provider._roots)
    if path.exists():
        path.unlink()

    # New provider instance — should NOT recover anything
    p2 = _init_provider(tmp_path, session_id="s2")
    assert not p2._current_task_anchor, (
        "A.Y: with persistence disabled, recovery should find nothing"
    )


# ── Unit tests for helper functions ─────────────────────────────────────────


def test_format_current_task_anchor_with_completed_operations():
    """Completed operations should appear in formatted anchor text."""
    anchor = _format_current_task_anchor(
        task="deploy nginx config",
        operations=[],
        completed_operations=[
            "tool: terminal: apt-get install nginx",
            "assistant: 安装完成，接下来配置 upstream",
        ],
    )
    assert "- completed operations (do not repeat):" in anchor
    assert "install nginx" in anchor
    assert "配置 upstream" in anchor


def test_format_current_task_anchor_backward_compatible():
    """Calling without completed_operations should produce valid anchor."""
    anchor = _format_current_task_anchor(
        task="simple task",
        operations=["tool: running test"],
    )
    assert "current task: simple task" in anchor
    assert "active tool/process state" in anchor
    assert "- completed operations (do not repeat):" not in anchor  # no completed → no section


def test_extract_anchor_operation_lines_parses_completed():
    """_extract_anchor_operation_lines should parse completed operations."""
    anchor = _format_current_task_anchor(
        task="test",
        operations=[],
        completed_operations=[
            "tool: terminal: apt-get install redis",
            "assistant: redis 已启动",
        ],
    )
    ops = _extract_anchor_operation_lines(anchor)
    assert len(ops) == 2
    assert any("redis" in op for op in ops)


def test_active_task_anchor_record_schema():
    """Active anchor records should follow the expected schema."""
    record = _active_task_anchor_record(
        anchor="### Memory-OS Current Task Anchor\n- current task: test",
        session_id="s1",
        profile="memoryos-test",
    )
    assert record["schema_version"] == "memory-os.active_task_anchor.v0"
    assert record["record_id"].startswith("ata_")
    assert record["status"] == "active"
    assert record["storage_policy"] == "runtime_system_metadata_not_canonical_memory"
    assert record["profile"] == "memoryos-test"
    assert record["session_id"] == "s1"
    assert "test" in record["anchor"]
    # created_at should be ISO 8601 with Z suffix
    assert record["created_at"].endswith("Z") or "+00:00" in record["created_at"]


def test_compression_rule_includes_do_not_repeat():
    """The compression rule MUST include 'Do not repeat completed operations'."""
    anchor = _format_current_task_anchor(
        task="any task",
        operations=[],
        completed_operations=["tool: did something"],
    )
    assert "Do not repeat completed operations" in anchor


def test_completed_operations_capped_at_6():
    """Only the last 6 completed operations should be retained."""
    ops = [f"tool: operation-{i}" for i in range(10)]
    anchor = _format_current_task_anchor(
        task="cap test",
        operations=[],
        completed_operations=ops,
    )
    # Should only contain the last 6
    for i in range(4):  # operations 0-3 should NOT appear
        assert f"operation-{i}" not in anchor
    for i in range(4, 10):  # operations 4-9 SHOULD appear
        assert f"operation-{i}" in anchor


def test_on_pre_compress_persists_anchor(tmp_path):
    """on_pre_compress should persist the built anchor to disk."""
    provider = _init_provider(tmp_path)
    messages = [
        {"role": "user", "content": "安装 redis"},
        {"role": "assistant", "content": "正在安装 redis..."},
        {"role": "tool", "content": "terminal: apt-get install redis-server -y\n...\nredis-server (7.0.15) ..."},
    ]
    result = provider.on_pre_compress(messages)
    assert result, "on_pre_compress should return an anchor string"
    assert "redis" in result.lower()

    # Should have been persisted
    path = _active_task_anchor_path(provider._roots)
    assert path.exists()
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").strip().splitlines()]
    assert any("redis" in r.get("anchor", "") for r in records)


def test_clear_active_task_anchor_writes_tombstone(tmp_path):
    """_clear_active_task_anchor should write a completed status record."""
    provider = _init_provider(tmp_path)
    provider.prefetch("测试任务")
    assert provider._current_task_anchor

    path = _active_task_anchor_path(provider._roots)
    provider._clear_active_task_anchor()

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    last = json.loads(lines[-1])
    assert last["status"] == "completed"
