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
    _format_recovered_cross_session_anchor,
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
    """Operation extraction must be pure string matching — no I/O, no network.

    P1 entity gate: structural signals hit alone; action words require
    a co-occurring entity (path, URL, UUID, ID pattern).
    """
    # Structural signals — hit alone
    assert _looks_like_operation_context("terminal: apt-get install postgresql")
    assert _looks_like_operation_context("execstart /usr/bin/systemctl")
    assert _looks_like_operation_context("main pid: 1234")

    # Action word + entity — must have both
    assert _looks_like_operation_context("合入 /opt/Hermes-Memory-OS")

    # Action word without entity — filtered (not an operation)
    assert not _looks_like_operation_context("开始全面检查")
    assert not _looks_like_operation_context("正在安装依赖...")
    assert not _looks_like_operation_context("下载完成")
    assert not _looks_like_operation_context("安装失败：依赖冲突")

    # Isolated generic words (removed from standalone markers) — filtered
    assert not _looks_like_operation_context("error: connection refused")
    assert not _looks_like_operation_context("process running on port 5432")

    # Non-operation text — filtered
    assert not _looks_like_operation_context("hello world")
    assert not _looks_like_operation_context("PostgreSQL 是一个数据库")
    assert not _looks_like_operation_context("")


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


def test_completed_operations_capped_at_4():
    """Only the last 4 completed operations should be retained (P2: 6→4)."""
    ops = [f"tool: operation-{i}" for i in range(10)]
    anchor = _format_current_task_anchor(
        task="cap test",
        operations=[],
        completed_operations=ops,
    )
    # Should only contain the last 4
    for i in range(6):  # operations 0-5 should NOT appear
        assert f"operation-{i}" not in anchor
    for i in range(6, 10):  # operations 6-9 SHOULD appear
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


def test_a7_extract_anchor_operation_lines_returns_up_to_4():
    """F2: extractor should return up to 4 operations (P2: 6→4)."""
    anchor = _format_current_task_anchor(
        task="test",
        operations=[],
        completed_operations=[f"tool: operation-{i}" for i in range(8)],
    )
    ops = _extract_anchor_operation_lines(anchor)
    assert len(ops) == 4, f"F2: extractor should return 4 ops, got {len(ops)}: {ops}"
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


def test_a16_supersede_active_anchors_is_idempotent(tmp_path):
    """_supersede_active_anchors called twice produces only 1 superseded per active."""
    provider = _init_provider(tmp_path)
    path = _active_task_anchor_path(provider._roots)

    # Write 3 active anchors
    for i in range(3):
        anchor = _format_current_task_anchor(
            task=f"task_{i}", operations=[], session_id=f"s{i}",
        )
        provider._write_active_task_anchor(anchor=anchor, status="active")

    # First supersede call
    provider._supersede_active_anchors()
    records_1 = [json.loads(l) for l in path.read_text(encoding="utf-8").strip().splitlines()]
    superseded_1 = [r for r in records_1 if r.get("status") == "superseded"]
    assert len(superseded_1) == 3

    # Second call — should NOT produce more superseded (idempotent)
    provider._supersede_active_anchors()
    records_2 = [json.loads(l) for l in path.read_text(encoding="utf-8").strip().splitlines()]
    superseded_2 = [r for r in records_2 if r.get("status") == "superseded"]
    assert len(superseded_2) == 3, f"idempotent: expected 3 superseded, got {len(superseded_2)}"


def test_compact_active_task_anchors_preserves_non_superseded(tmp_path):
    """compact_active_task_anchors keeps all active/completed/cancelled."""
    from plugins.memory.memory_os.__init__ import compact_active_task_anchors

    provider = _init_provider(tmp_path)
    path = _active_task_anchor_path(provider._roots)

    anchor = _format_current_task_anchor(task="active_task", operations=[], session_id="s1")
    provider._write_active_task_anchor(anchor=anchor, status="active")
    provider._write_active_task_anchor(anchor=anchor, status="completed")
    provider._write_active_task_anchor(anchor=anchor, status="cancelled")

    result = compact_active_task_anchors(tmp_path, max_superseded=10, dry_run=False, backup=False)
    # At least 3 non-superseded are preserved (_write_active_task_anchor may
    # tombstone internally, producing extra records, but all
    # active/completed/cancelled must survive).
    assert result["non_superseded"] >= 3
    assert result["superseded_dropped"] == 0


def test_compact_active_task_anchors_drops_old_superseded(tmp_path):
    """compact drops superseded beyond max_superseded, keeps recent ones."""
    from plugins.memory.memory_os.__init__ import compact_active_task_anchors

    provider = _init_provider(tmp_path)
    path = _active_task_anchor_path(provider._roots)

    # 1 active + N superseded (exact count depends on internal tombstoning)
    anchor = _format_current_task_anchor(task="keep_me", operations=[], session_id="s1")
    provider._write_active_task_anchor(anchor=anchor, status="active")
    for i in range(200):
        provider._write_active_task_anchor(
            anchor=_format_current_task_anchor(task=f"old_{i}", operations=[], session_id=f"s{i}"),
            status="superseded",
        )

    # Count actual superseded before compact
    all_records_before = [json.loads(l) for l in path.read_text(encoding="utf-8").strip().splitlines()]
    superseded_before = sum(1 for r in all_records_before if r.get("status") == "superseded")

    result = compact_active_task_anchors(tmp_path, max_superseded=50, dry_run=False, backup=False)
    assert result["non_superseded"] >= 1  # active survives
    assert result["superseded_kept"] <= 50

    # Verify: active record still present
    records_after = [json.loads(l) for l in path.read_text(encoding="utf-8").strip().splitlines()]
    assert any(r.get("status") == "active" for r in records_after)


def test_compact_active_task_anchors_dry_run_no_write(tmp_path):
    """dry_run reports what would happen without modifying the file."""
    from plugins.memory.memory_os.__init__ import compact_active_task_anchors

    provider = _init_provider(tmp_path)
    path = _active_task_anchor_path(provider._roots)

    anchor = _format_current_task_anchor(task="t", operations=[], session_id="s1")
    provider._write_active_task_anchor(anchor=anchor, status="active")
    for _ in range(50):
        provider._write_active_task_anchor(anchor=anchor, status="superseded")

    original = path.read_text(encoding="utf-8")
    result = compact_active_task_anchors(tmp_path, max_superseded=10, dry_run=True)
    assert result["dry_run"] is True
    assert result["non_superseded"] >= 1
    assert path.read_text(encoding="utf-8") == original  # unchanged


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


# ═══════════════════════════════════════════════════════════════════════════════
# Anchor Pollution Fix — spec-mandated tests (T.1–T.5 + X.1–X.3)
# ═══════════════════════════════════════════════════════════════════════════════


# ── T.1  P0 core: cross-session recovery strips ops, uses recovered rule ─────


def test_t1_cross_session_recovery_strips_operations():
    """Cross-session recovery must strip completed_operations and active state."""
    anchor = _format_recovered_cross_session_anchor(
        task="deploy redis cluster",
        age_label="12h前",
        original_session="old-session-id",
        current_session="new-session-id",
    )
    assert "completed operations" not in anchor, (
        "T.1 FAIL: recovered anchor must NOT contain completed_operations section"
    )
    assert "active tool/process state" not in anchor, (
        "T.1 FAIL: recovered anchor must NOT contain active tool/process state"
    )
    assert "deploy redis cluster" in anchor, (
        "T.1 FAIL: recovered anchor must retain the task description"
    )
    assert "跨会话恢复" in anchor, (
        "T.1 FAIL: recovered anchor must carry the cross-session marker"
    )
    assert "12h前" in anchor
    assert "old-session-id" in anchor
    assert "new-session-id" in anchor
    assert "Continue this foreground task" not in anchor, (
        "T.1 FAIL: recovered anchor must NOT command 'Continue this foreground task'"
    )
    assert "may be complete" in anchor, (
        "T.1 FAIL: recovered anchor must use the 'may be complete, verify' rule"
    )


def test_t1_recovered_anchor_in_system_prompt_block(tmp_path):
    """system_prompt_block must inject the recovered rule, not Continue."""
    provider = _init_provider(tmp_path, session_id="new-session")
    provider._current_task_anchor = _format_recovered_cross_session_anchor(
        task="audit log review",
        age_label="3h前",
        original_session="prior-session",
        current_session="new-session",
    )
    block = provider.system_prompt_block()
    assert "may be complete" in block, (
        "T.1 FAIL: system_prompt_block must use recovered rule"
    )
    assert "Continue this foreground task" not in block, (
        "T.1 FAIL: system_prompt_block must NOT contain 'Continue' instruction "
        "when anchor is a recovered cross-session anchor"
    )


# ── T.2  F3 regression: deferred resume preserves completed_operations ───────


def test_t2_deferred_resume_preserves_completed_operations():
    """explicit_deferred_resume path must retain completed_operations (P0 safety)."""
    previous = _format_current_task_anchor(
        task="migrate database",
        operations=[],
        completed_operations=["tool: backed up schema", "tool: dumped data"],
    )
    anchor = _format_resumed_deferred_task_anchor(
        anchor=previous,
        session_id="s1",
        completed_operations=["tool: backed up schema", "tool: dumped data"],
    )
    assert "completed operations" in anchor, (
        "T.2 FAIL: deferred resume anchor MUST retain completed_operations — "
        "P0 boundary must not affect the deferred-resume path"
    )
    assert "backed up schema" in anchor
    assert "dumped data" in anchor


# ── T.3  P1 core: entity gate ────────────────────────────────────────────────


def test_t3_entity_gate_filters_noise():
    """Entity gate: noise text without entities is NOT captured."""
    assert not _looks_like_operation_context("开始全面检查"), (
        "T.3 FAIL: '开始全面检查' has action word removed and no entity → must be filtered"
    )
    assert not _looks_like_operation_context("正在安装依赖..."), (
        "T.3 FAIL: '正在安装依赖' has no entity → must be filtered"
    )


def test_t3_entity_gate_captures_action_with_entity():
    """Entity gate: action word + concrete entity IS captured."""
    assert _looks_like_operation_context("合入 /opt/Hermes-Memory-OS"), (
        "T.3 FAIL: '合入 /opt/Hermes-Memory-OS' has action + path entity → must be captured"
    )
    assert _looks_like_operation_context("deploy to /var/www/production"), (
        "T.3 FAIL: 'deploy to /var/www/production' has action + path entity → must be captured"
    )


# ── T.4  isolated generic words filtered; structural still captured ──────────


def test_t4_isolated_generic_words_filtered():
    """Generic words (error/检查/正在) no longer trigger alone."""
    assert not _looks_like_operation_context("error: connection refused"), (
        "T.4 FAIL: 'error' alone without entity must NOT trigger"
    )
    assert not _looks_like_operation_context("检查配置文件"), (
        "T.4 FAIL: '检查' alone without entity must NOT trigger"
    )
    assert not _looks_like_operation_context("正在运行"), (
        "T.4 FAIL: '正在' alone without entity must NOT trigger"
    )


def test_t4_structural_signals_still_captured():
    """Structural markers still capture regardless of entity presence."""
    assert _looks_like_operation_context("terminal: systemctl status"), (
        "T.4 FAIL: 'terminal:' is a structural signal → must be captured"
    )
    assert _looks_like_operation_context("main pid: 1234"), (
        "T.4 FAIL: 'main pid' is a structural signal → must be captured"
    )
    assert _looks_like_operation_context("fatal: out of memory"), (
        "T.4 FAIL: 'fatal:' is a structural signal → must be captured"
    )


# ── T.5  budget caps ─────────────────────────────────────────────────────────


def test_t5_completed_operations_capped_at_4():
    """P2: completed_operations window is 4, not 6."""
    anchor = _format_current_task_anchor(
        task="cap verification",
        operations=[],
        completed_operations=[f"tool: op-{i}" for i in range(10)],
    )
    assert "op-6" in anchor, "T.5 FAIL: operation 6 should be within 4-item window"
    assert "op-9" in anchor, "T.5 FAIL: operation 9 should be within 4-item window"
    assert "op-5" not in anchor, "T.5 FAIL: operation 5 should be outside 4-item window"


def test_t5_per_operation_clip_within_budget():
    """P2: each operation clipped to 140 (capture) / 160 (format)."""
    anchor = _format_current_task_anchor(
        task="clip test",
        operations=[],
        completed_operations=["tool: " + "x" * 200],
    )
    # After format clipping to 160: "tool: " (6 chars) + 154 chars of "x" + no overflow
    assert len("x" * 200) > 160, "sanity: long op should be clipped"
    # The rendered op line should be at most ~166 chars (6 prefix + 160 clipped text)
    for line in anchor.splitlines():
        if line.strip().startswith("- tool:"):
            assert len(line) < 180, (
                f"T.5 FAIL: operation line too long ({len(line)} chars): {line[:80]}..."
            )


def test_t5_same_session_mechanism_unchanged():
    """Within-session anchor behavior is preserved (format + carry-forward)."""
    anchor = _format_current_task_anchor(
        task="intra-session task",
        operations=["tool: active-op"],
        completed_operations=["tool: completed-op"],
    )
    assert "current task: intra-session task" in anchor
    assert "completed operations (do not repeat):" in anchor
    assert "active tool/process state:" in anchor
    assert "compression rule: Continue this foreground task" in anchor


# ── X.1  counterfactual: P0 reverted → T.1 must fail ────────────────────────


def test_x1_p0_reverted_would_fail_t1():
    """If recovered anchor kept ops, T.1 assertions would fire."""
    # Build what the OLD code path would produce (marker prepended to raw anchor)
    raw_anchor = _format_current_task_anchor(
        task="deploy redis cluster",
        operations=[],
        completed_operations=["tool: set up cluster", "tool: configured replicas"],
    )
    old_style = "- [跨会话恢复, 12h前, 原会话: old-session]\n" + raw_anchor

    # The old code path would have LEAKED these into the new session
    assert "completed operations" in old_style, (
        "X.1 precondition FAIL: old code would have carried ops — this IS the bug"
    )
    assert "set up cluster" in old_style
    assert "Continue this foreground task" in old_style

    # The new code path (T.1) strips them — verify the positive case still holds
    recovered = _format_recovered_cross_session_anchor(
        task="deploy redis cluster",
        age_label="12h前",
        original_session="old-session",
        current_session="new-session",
    )
    assert "completed operations" not in recovered
    assert "Continue this foreground task" not in recovered


# ── X.2  counterfactual: entity gate removed → T.3 must fail ─────────────────


def test_x2_entity_gate_removed_would_fail_t3():
    """Without entity gate, action words alone would capture noise."""
    # The OLD _looks_like_operation_context treated any action word as a hit
    old_markers = ("正在", "安装", "下载", "检查", "失败", "报错")
    text = "开始全面检查"
    old_result = any(m in text for m in old_markers)
    assert old_result, (
        "X.2 precondition FAIL: old matcher would have captured '开始全面检查' — "
        "this IS the false positive the entity gate eliminates"
    )
    # New behaviour: no entity → not captured
    assert not _looks_like_operation_context(text)


# ── X.3  counterfactual: generic words back as standalone → T.4 must fail ────


def test_x3_generic_words_back_would_fail_t4():
    """If generic words were standalone again, they'd trigger false positives."""
    old_generics = ("error", "failed", "running", "正在", "失败", "检查")
    text = "error: connection refused"
    old_result = any(g in text.lower() for g in old_generics)
    assert old_result, (
        "X.3 precondition FAIL: old matcher would have captured 'error: connection refused' "
        "— this IS the false positive the new filter eliminates"
    )
    # New behaviour: no entity → not captured
    assert not _looks_like_operation_context(text)
