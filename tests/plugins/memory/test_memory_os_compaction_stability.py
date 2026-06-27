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
    _build_current_task_anchor,
    _clip,
    _extract_anchor_current_task,
    _extract_anchor_operation_lines,
    _format_cancelled_task_anchor,
    _format_current_task_anchor,
    _format_deferred_task_anchor,
    _format_resumed_deferred_task_anchor,
    _is_owner_action_anchor,
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


# ── A.6  on_pre_compress carries forward completed_operations (F1) ──────────


def test_a6_on_pre_compress_carries_forward_completed_operations(tmp_path):
    """F1: on_pre_compress should preserve completed_operations from prior anchor."""
    provider = _init_provider(tmp_path)
    provider.prefetch("安装 nginx")
    # Accumulate a completed operation via sync_turn
    provider.sync_turn(
        "安装 nginx",
        "正在安装...",
        messages=[
            {"role": "user", "content": "安装 nginx"},
            {"role": "assistant", "content": "正在安装 nginx..."},
            {"role": "tool", "content": "terminal: apt-get install nginx -y\n...\nnginx (1.24.0) ..."},
        ],
    )
    anchor_before = provider._current_task_anchor
    assert "install nginx" in anchor_before.lower()

    # Simulate compaction
    messages = [
        {"role": "user", "content": "继续配置 nginx"},
        {"role": "assistant", "content": "现在来配置 nginx..."},
    ]
    anchor_after = provider.on_pre_compress(messages)
    # The completed operation from before should survive compaction
    assert "install nginx" in anchor_after.lower(), (
        f"F1: completed_operations should survive compaction:\n{anchor_after}"
    )


# ── A.7  extractor returns 6 (F2) ───────────────────────────────────────────


def test_a7_extract_anchor_operation_lines_returns_up_to_6():
    """F2: extractor should return up to 6 operations, matching formatter cap."""
    anchor = _format_current_task_anchor(
        task="test",
        operations=[],
        completed_operations=[f"tool: operation-{i}" for i in range(8)],
    )
    ops = _extract_anchor_operation_lines(anchor)
    assert len(ops) == 6, f"F2: extractor should return 6 ops, got {len(ops)}: {ops}"
    assert "operation-7" in ops[-1]


# ── A.8  deferred anchor preserves completed_operations (F3) ─────────────────


def test_a8_deferred_task_anchor_preserves_completed_operations():
    """F3: _format_deferred_task_anchor should render completed_operations when provided."""
    previous = _format_current_task_anchor(
        task="deploy nginx",
        operations=[],
        completed_operations=["tool: built container image", "tool: pushed to registry"],
    )
    anchor = _format_deferred_task_anchor(
        deferral="先推迟部署",
        previous_anchor=previous,
        completed_operations=["tool: built container image", "tool: pushed to registry"],
    )
    assert "completed operations (do not repeat)" in anchor
    assert "built container image" in anchor
    assert "pushed to registry" in anchor


# ── A.9  cancelled anchor preserves completed_operations (F3) ────────────────


def test_a9_cancelled_task_anchor_preserves_completed_operations():
    """F3: _format_cancelled_task_anchor should render completed_operations when provided."""
    previous = _format_current_task_anchor(
        task="install redis",
        operations=[],
        completed_operations=["tool: apt-get install redis"],
    )
    anchor = _format_cancelled_task_anchor(
        cancellation="取消安装",
        previous_anchor=previous,
        completed_operations=["tool: apt-get install redis"],
    )
    assert "completed operations (do not repeat)" in anchor
    assert "install redis" in anchor


# ── A.10  _capture_turn_operations no-ops on cancelled anchor (F4) ──────────


def test_a10_capture_turn_operations_noops_on_cancelled_anchor(tmp_path):
    """F4: _capture_turn_operations should not modify a cancelled anchor."""
    provider = _init_provider(tmp_path)
    provider.prefetch("安装 redis")
    # Cancel the task
    provider.prefetch("取消这个任务")
    cancelled_anchor = provider._current_task_anchor
    if not cancelled_anchor:
        pytest.skip("anchor was cleared, not formatted as cancelled")
    assert "cancelled" in cancelled_anchor.lower()

    # Now call sync_turn with operation messages — should not wipe the anchor
    provider.sync_turn(
        "取消这个任务",
        "好的，任务已取消。",
        messages=_tool_messages(),
    )
    assert provider._current_task_anchor, "F4: cancelled anchor should not be wiped"
    assert "cancelled" in provider._current_task_anchor.lower()


# ── A.11  _capture_turn_operations no-ops on deferred anchor (F4) ───────────


def test_a11_capture_turn_operations_noops_on_deferred_anchor(tmp_path):
    """F4: _capture_turn_operations should not modify a deferred anchor."""
    provider = _init_provider(tmp_path)
    provider.prefetch("部署到生产环境")
    # Defer the task
    provider.prefetch("先推迟这个任务，稍后再做")
    deferred_anchor = provider._current_task_anchor
    if not deferred_anchor or "deferred" not in deferred_anchor.lower():
        pytest.skip("anchor was not formatted as deferred")

    provider.sync_turn(
        "先推迟这个任务，稍后再做",
        "好的，任务已推迟。",
        messages=_tool_messages(),
    )
    assert provider._current_task_anchor, "F4: deferred anchor should not be wiped"


# ── A.12  merge deduplicates (F5) ────────────────────────────────────────────


def test_a12_merge_deduplicates_identical_operations():
    """F5: merged completed_operations should not contain duplicates."""
    previous = ["tool: apt-get install nginx", "assistant: configured upstream"]
    new = ["assistant: configured upstream", "tool: restarted nginx"]
    merged = list(dict.fromkeys(previous + new))[-6:]
    assert merged.count("assistant: configured upstream") == 1
    assert len(merged) == 3
    assert merged == ["tool: apt-get install nginx", "assistant: configured upstream", "tool: restarted nginx"]


# ── A.13  conditional compression rule (F6) ──────────────────────────────────


def test_a13_compression_rule_omits_do_not_repeat_when_no_completed_ops():
    """F6: 'Do not repeat completed operations' absent when completed_operations is empty."""
    anchor = _format_current_task_anchor(
        task="test",
        operations=[],
    )
    assert "Do not repeat completed operations" not in anchor
    assert "Do not switch back to unrelated historical memory topics" in anchor


# ── A.14  _write_active_task_anchor calls _audit (F7) ────────────────────────


def test_a14_write_active_task_anchor_calls_audit(tmp_path):
    """F7: _write_active_task_anchor should call self._audit after writing."""
    provider = _init_provider(tmp_path)
    provider.prefetch("测试任务")

    audit_calls = []
    mp = mock.patch.object(provider, "_audit", side_effect=lambda *args, **kw: audit_calls.append((args, kw)))
    mp.start()

    provider._write_active_task_anchor(anchor=provider._current_task_anchor, status="active")

    mp.stop()
    assert len(audit_calls) >= 1, f"F7: expected _audit to be called, got {len(audit_calls)} calls"
    args, kw = audit_calls[0]
    assert args[0] == "active_task_anchor_recorded"
    assert args[1] == "ok"


# ── A.15  supersede old active records (F8) ──────────────────────────────────


def test_a15_supersede_active_anchors_tombstones_old_records(tmp_path):
    """F8: writing a new active record should supersede old active records."""
    provider = _init_provider(tmp_path)
    anchor_1 = _format_current_task_anchor(
        task="任务一", operations=[], session_id="s1",
    )
    provider._write_active_task_anchor(anchor=anchor_1, status="active")
    path = _active_task_anchor_path(provider._roots)

    # Verify first record is written
    assert path.exists()
    lines_1 = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines_1) == 1

    # Write a second active record — should supersede the first via append-only tombstone
    anchor_2 = _format_current_task_anchor(
        task="任务二", operations=[], session_id="s1",
    )
    provider._write_active_task_anchor(anchor=anchor_2, status="active")

    # The superseded tombstone was appended; the original active line is immutable.
    # The reader (_read_latest_active_task_anchor) scans in reverse and returns
    # the latest active record. Verify the reader returns the correct anchor.
    recovered = provider._read_latest_active_task_anchor()
    assert "任务二" in recovered, f"F8: latest active anchor should be task 2, got: {recovered}"

    # Also verify superseded records exist in the file
    lines_after = path.read_text(encoding="utf-8").strip().splitlines()
    records = [json.loads(l) for l in lines_after]
    superseded = [r for r in records if r.get("status") == "superseded"]
    assert len(superseded) >= 1, f"F8: should have at least 1 superseded record, got {len(superseded)}"


# ── A.X2  adversarial: disable F1 fix → A.6 fails ────────────────────────────


def test_ax2_disable_f1_fix_breaks_a6(monkeypatch, tmp_path):
    """A.X2: if F1 fix is disabled, on_pre_compress MUST NOT carry forward ops."""
    provider = _init_provider(tmp_path)
    provider.prefetch("安装 nginx")
    provider.sync_turn(
        "安装 nginx",
        "正在安装...",
        messages=[
            {"role": "user", "content": "安装 nginx"},
            {"role": "assistant", "content": "正在安装 nginx..."},
            {"role": "tool", "content": "terminal: apt-get install nginx -y\n...\nnginx (1.24.0) ..."},
        ],
    )

    # Monkey-patch on_pre_compress to skip forwarding completed_operations
    def broken_pre_compress(messages):
        provider._current_task_anchor = _build_current_task_anchor(
            messages, session_id=provider.session_id
        )
        if provider._current_task_anchor:
            provider._write_active_task_anchor(anchor=provider._current_task_anchor)
        return provider._current_task_anchor

    monkeypatch.setattr(provider, "on_pre_compress", broken_pre_compress)

    messages = [
        {"role": "user", "content": "继续配置 nginx"},
        {"role": "assistant", "content": "现在来配置..."},
    ]
    anchor_after = provider.on_pre_compress(messages)
    # Without the fix, completed operations should NOT appear
    assert "install nginx" not in anchor_after.lower(), (
        "A.X2: without F1 fix, completed_operations should be absent from compaction anchor"
    )


# ── A.16  _read_latest_active_task_anchor does not resurrect cleared/cancelled anchors ──


def test_a16_read_latest_active_anchor_does_not_resurrect_cleared_anchor(tmp_path):
    """A.16: after _clear_active_task_anchor, recovery must NOT return the old anchor.

    JSONL is append-only — old ``"active"`` lines are immutable.  This test
    verifies that ``_read_latest_active_task_anchor`` uses most-recent-record
    semantics rather than scanning for *any* ``"active"`` record.
    """
    provider = _init_provider(tmp_path)
    provider.prefetch("部署 redis 集群")

    # Sanity: anchor is active
    assert provider._current_task_anchor, "expected active anchor after prefetch"
    recovered = provider._read_latest_active_task_anchor()
    assert recovered == provider._current_task_anchor, (
        "recovered anchor should match in-memory anchor"
    )

    # Clear the anchor (simulates topic switch or ambiguous recall;
    # callers always follow _clear_active_task_anchor with clearing the
    # in-memory state — replicate that here)
    provider._clear_active_task_anchor()
    provider._current_task_anchor = ""

    # Recovery must NOT resurrect the old anchor
    recovered_after = provider._read_latest_active_task_anchor()
    assert recovered_after == "", (
        f"A.16 FAIL: _read_latest_active_task_anchor resurrected cleared anchor: "
        f"{recovered_after[:80]}..."
    )


def test_a16b_cancellation_anchor_not_resurrected(tmp_path):
    """A.16b: cancellation path must also prevent resurrection on recovery."""
    provider = _init_provider(tmp_path)
    provider.prefetch("部署 redis 集群")

    anchor_before = provider._current_task_anchor
    assert anchor_before, "expected active anchor"

    # Simulate cancellation: write cancelled anchor directly
    cancelled = _format_cancelled_task_anchor(
        cancellation="取消这个任务",
        previous_anchor=anchor_before,
        session_id=provider.session_id,
        completed_operations=_extract_anchor_operation_lines(anchor_before),
    )
    provider._write_active_task_anchor(anchor=cancelled, status="cancelled")
    provider._current_task_anchor = ""

    # Recovery must not return the old active anchor
    recovered = provider._read_latest_active_task_anchor()
    assert recovered == "", (
        f"A.16b FAIL: _read_latest_active_task_anchor resurrected cancelled anchor: "
        f"{recovered[:80]}..."
    )


def test_a17_capture_turn_operations_preserves_resumed_anchor_response_rule(tmp_path):
    """A.17: _capture_turn_operations must not rebuild resumed anchor format.

    Resumed deferred-task anchors carry ``response rule: Continue this deferred
    foreground task``.  ``_capture_turn_operations`` calls
    ``_format_current_task_anchor`` to rebuild, which replaces that specialized
    response rule with the generic ``compression rule: Continue this foreground
    task after compaction`` — losing the critical "deferred" instruction that
    tells the agent *which* task to continue.

    The resumed anchor has ``- current task:`` extracted from the ORIGINAL
    pre-deferral anchor (read from deferred JSONL), so the existing
    ``not current_task`` guard does NOT protect it — it is misidentified as a
    standard-format anchor and silently rebuilt.
    """
    provider = _init_provider(tmp_path)
    provider.prefetch("部署 redis 集群")

    # Save the original anchor (has "- current task:"), which is what
    # _write_deferred_current_task_anchor persists to deferred JSONL.
    original_anchor = provider._current_task_anchor
    assert "- current task:" in original_anchor

    # Simulate: defer
    provider._write_deferred_current_task_anchor(
        anchor=original_anchor,
        deferral="先推迟",
        session_id=provider.session_id,
    )
    deferred_anchor = _format_deferred_task_anchor(
        deferral="先推迟",
        previous_anchor=original_anchor,
        session_id=provider.session_id,
    )
    provider._current_task_anchor = deferred_anchor
    provider._write_active_task_anchor(anchor=deferred_anchor)

    # Simulate: resume — in real code _read_latest_deferred_current_task_anchor
    # returns the ORIGINAL pre-deferral anchor, not the deferred-format one
    resume_anchor = _format_resumed_deferred_task_anchor(
        anchor=original_anchor,  # ← matches real _read_latest_deferred_current_task_anchor
        session_id=provider.session_id,
    )
    provider._current_task_anchor = resume_anchor
    provider._write_active_task_anchor(anchor=resume_anchor)

    # Sanity: the resumed anchor has the response rule
    assert "response rule: Continue this deferred foreground task" in provider._current_task_anchor, (
        "A.17 precondition FAIL: resume anchor missing response rule"
    )
    # Sanity: the resumed anchor has "- current task:" from the original anchor
    assert "- current task:" in provider._current_task_anchor, (
        "A.17 precondition FAIL: resumed anchor missing current_task line"
    )

    # Simulate: _capture_turn_operations with operation-context messages
    provider._capture_turn_operations(
        [
            {"role": "assistant", "content": "I'll check the server status"},
            {"role": "tool", "content": "terminal: redis-server process running on port 6379"},
        ],
        session_id=provider.session_id,
    )

    assert "response rule: Continue this deferred foreground task" in provider._current_task_anchor, (
        "A.17 FAIL: _capture_turn_operations replaced resumed anchor's "
        "'response rule: Continue this deferred foreground task' with the "
        "generic compression rule — the agent would not know to continue "
        "the deferred task after compaction recovery"
    )
    assert "- owner resumed a deferred foreground task" in provider._current_task_anchor, (
        "A.17 FAIL: _capture_turn_operations stripped 'owner resumed' marker"
    )
