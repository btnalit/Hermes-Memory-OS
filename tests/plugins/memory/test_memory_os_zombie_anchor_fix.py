"""Tests for the zombie active_task_anchor fix.

Validates the three-layer defense:
1. on_session_end tombstones the active anchor (completed tombstone)
2. _read_latest_active_task_anchor rejects stale anchors (age gate)
3. Cross-session recovery adds a source marker
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from plugins.memory import load_memory_provider
from plugins.memory.memory_os.__init__ import (
    _active_task_anchor_path,
)


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


def _foreground_messages():
    """Messages with clear foreground content."""
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


def _read_jsonl(path):
    """Read a JSONL file into a list of dicts."""
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# ── Layer 1: on_session_end tombstones active anchor ────────────────────


def test_on_session_end_writes_completed_tombstone(tmp_path):
    """After on_session_end, active_task_anchor.jsonl's most recent record
    should have status=completed — not active."""
    provider = _init_provider(tmp_path, session_id="session-a")

    # Create an active anchor first (simulating the session having a task)
    provider.on_pre_compress(_foreground_messages())

    # Verify it's active before session end
    anchor_path = _active_task_anchor_path(provider._roots)
    records_before = _read_jsonl(anchor_path)
    assert len(records_before) >= 1
    assert records_before[-1]["status"] == "active"

    # End the session
    provider.on_session_end(_foreground_messages())
    provider.shutdown()

    # Verify the most recent record is now "completed"
    records_after = _read_jsonl(anchor_path)
    assert len(records_after) >= 2  # original active + tombstone
    assert records_after[-1]["status"] == "completed"


def test_new_session_does_not_recover_completed_anchor(tmp_path):
    """Session A's completed anchor should NOT be recovered by Session B."""
    # Session A: create anchor, end session (tombstones it)
    p1 = _init_provider(tmp_path, session_id="session-a")
    p1.on_pre_compress(_foreground_messages())
    p1.on_session_end(_foreground_messages())
    p1.shutdown()

    # Session B: initialize should NOT recover the completed anchor
    p2 = _init_provider(tmp_path, session_id="session-b")
    assert p2._current_task_anchor == ""
    context = p2.prefetch("新任务", session_id="session-b")
    p2.shutdown()

    # Current Foreground Task should be the NEW query, not the old ComfyUI task
    if "### Current Foreground Task" in context:
        fg_start = context.index("### Current Foreground Task")
        fg_section = context[fg_start:]
        next_section = fg_section.find("\n###", 5)
        fg_text = fg_section[:next_section] if next_section != -1 else fg_section
        assert "ComfyUI" not in fg_text, (
            f"Zombie anchor detected in Current Foreground Task:\n{fg_text}"
        )


# ── Layer 2: Age gate rejects stale anchors ─────────────────────────────


def test_read_latest_active_task_anchor_rejects_old_anchor(tmp_path):
    """An anchor older than max_age_hours should be rejected."""
    provider = _init_provider(tmp_path, session_id="session-a")

    # Manually write an old active anchor (simulating a zombie from 48h ago)
    anchor_path = _active_task_anchor_path(provider._roots)
    anchor_path.parent.mkdir(parents=True, exist_ok=True)
    old_time = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat().replace("+00:00", "Z")
    old_record = {
        "schema_version": "memory-os.active_task_anchor.v0",
        "record_id": "ata_oldzombie",
        "created_at": old_time,
        "profile": "memoryos-test",
        "session_id": "session-zombie",
        "anchor": "### Memory-OS Current Task Anchor\n- current task: 德国vs巴拉圭赛前分析\n- session: session-zombie",
        "status": "active",
        "storage_policy": "runtime_system_metadata_not_canonical_memory",
    }
    anchor_path.write_text(
        json.dumps(old_record, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Recovery with max_age_hours=24 should reject the 48h-old anchor
    recovered = provider._read_latest_active_task_anchor(max_age_hours=24)
    provider.shutdown()

    assert recovered == "", f"Expected empty string for 48h-old anchor, got: {recovered!r}"


def test_read_latest_active_task_anchor_accepts_recent_anchor(tmp_path):
    """An anchor within max_age_hours should be recovered."""
    provider = _init_provider(tmp_path, session_id="session-recent")

    # Manually write a recent active anchor (1h ago)
    anchor_path = _active_task_anchor_path(provider._roots)
    anchor_path.parent.mkdir(parents=True, exist_ok=True)
    recent_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    recent_record = {
        "schema_version": "memory-os.active_task_anchor.v0",
        "record_id": "ata_recent",
        "created_at": recent_time,
        "profile": "memoryos-test",
        "session_id": "session-recent",
        "anchor": "### Memory-OS Current Task Anchor\n- current task: 持续部署任务\n- session: session-recent",
        "status": "active",
        "storage_policy": "runtime_system_metadata_not_canonical_memory",
    }
    anchor_path.write_text(
        json.dumps(recent_record, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Recovery with max_age_hours=24 should accept the 1h-old anchor
    recovered = provider._read_latest_active_task_anchor(max_age_hours=24)
    provider.shutdown()

    assert recovered != ""
    assert "持续部署任务" in recovered


def test_read_latest_active_task_anchor_default_no_age_limit(tmp_path):
    """Default max_age_hours=0 means no age limit (backward compatible)."""
    provider = _init_provider(tmp_path, session_id="session-a")

    anchor_path = _active_task_anchor_path(provider._roots)
    anchor_path.parent.mkdir(parents=True, exist_ok=True)
    old_time = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat().replace("+00:00", "Z")
    old_record = {
        "schema_version": "memory-os.active_task_anchor.v0",
        "record_id": "ata_olddefault",
        "created_at": old_time,
        "profile": "memoryos-test",
        "session_id": "session-old",
        "anchor": "### Memory-OS Current Task Anchor\n- current task: 旧任务\n- session: session-old",
        "status": "active",
        "storage_policy": "runtime_system_metadata_not_canonical_memory",
    }
    anchor_path.write_text(
        json.dumps(old_record, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Default (no max_age_hours) should still recover it
    recovered = provider._read_latest_active_task_anchor()
    provider.shutdown()

    assert recovered != ""
    assert "旧任务" in recovered


# ── Layer 3: Cross-session marker ──────────────────────────────────────


def test_cross_session_recovery_adds_marker(tmp_path):
    """When an anchor is recovered from a different session, a source marker
    should be prepended."""
    provider = _init_provider(tmp_path, session_id="session-current")

    # Write an active anchor from a DIFFERENT session (1h ago)
    anchor_path = _active_task_anchor_path(provider._roots)
    anchor_path.parent.mkdir(parents=True, exist_ok=True)
    recent_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    other_record = {
        "schema_version": "memory-os.active_task_anchor.v0",
        "record_id": "ata_other",
        "created_at": recent_time,
        "profile": "memoryos-test",
        "session_id": "session-other",
        "anchor": "### Memory-OS Current Task Anchor\n- current task: 跨会话任务\n- session: session-other",
        "status": "active",
        "storage_policy": "runtime_system_metadata_not_canonical_memory",
    }
    anchor_path.write_text(
        json.dumps(other_record, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # self.session_id is "session-current", anchor is from "session-other"
    recovered = provider._read_latest_active_task_anchor(max_age_hours=24)
    provider.shutdown()

    assert "跨会话恢复" in recovered, f"Expected cross-session marker, got: {recovered!r}"
    assert "session-other" in recovered
    assert "跨会话任务" in recovered


def test_same_session_recovery_no_marker(tmp_path):
    """When an anchor is from the same session, no cross-session marker."""
    provider = _init_provider(tmp_path, session_id="session-same")

    # Write an active anchor from the SAME session
    anchor_path = _active_task_anchor_path(provider._roots)
    anchor_path.parent.mkdir(parents=True, exist_ok=True)
    recent_time = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    same_record = {
        "schema_version": "memory-os.active_task_anchor.v0",
        "record_id": "ata_same",
        "created_at": recent_time,
        "profile": "memoryos-test",
        "session_id": "session-same",
        "anchor": "### Memory-OS Current Task Anchor\n- current task: 当前会话任务\n- session: session-same",
        "status": "active",
        "storage_policy": "runtime_system_metadata_not_canonical_memory",
    }
    anchor_path.write_text(
        json.dumps(same_record, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    recovered = provider._read_latest_active_task_anchor(max_age_hours=24)
    provider.shutdown()

    assert "跨会话恢复" not in recovered, f"Same-session anchor should not have marker: {recovered!r}"
    assert "当前会话任务" in recovered


# ── Layer 1 + Layer 2 integration: end-to-end zombie prevention ────────


def test_end_to_end_zombie_prevention(tmp_path):
    """Full pipeline: session A completes → session B starts fresh, no zombie."""
    # Session A: create anchor, do work, end session
    p1 = _init_provider(tmp_path, session_id="session-a")
    p1.on_pre_compress(_foreground_messages())
    p1.on_session_end(_foreground_messages())
    p1.shutdown()

    # Session B: initialize — should NOT recover session A's anchor
    p2 = _init_provider(tmp_path, session_id="session-b")
    assert p2._current_task_anchor == "", (
        f"Session B should start with empty anchor, got: {p2._current_task_anchor!r}"
    )
    context = p2.prefetch("新的独立任务", session_id="session-b")
    p2.shutdown()

    # The Current Foreground Task should be about the NEW query, not ComfyUI
    assert "新的独立任务" in context
    # ComfyUI should only appear in Last Session, not in Current Foreground Task
    if "### Current Foreground Task" in context:
        fg_start = context.index("### Current Foreground Task")
        fg_section = context[fg_start:]
        next_section = fg_section.find("\n###", 5)
        fg_text = fg_section[:next_section] if next_section != -1 else fg_section
        assert "ComfyUI" not in fg_text, (
            f"Zombie anchor detected in Current Foreground Task:\n{fg_text}"
        )


# ── Edge cases ──────────────────────────────────────────────────────────


def test_on_session_end_noop_when_no_active_anchor(tmp_path):
    """on_session_end should not crash when there's no active anchor to clear."""
    provider = _init_provider(tmp_path, session_id="session-empty")
    # No on_pre_compress call — no anchor was ever created
    # This must not crash
    provider.on_session_end(_foreground_messages())
    provider.shutdown()


def test_multiple_session_ends_dont_stack_tombstones(tmp_path):
    """Calling on_session_end multiple times should not corrupt the anchor file."""
    provider = _init_provider(tmp_path, session_id="session-multi")
    provider.on_pre_compress(_foreground_messages())

    # End session twice (simulating edge case)
    provider.on_session_end(_foreground_messages())
    provider.on_session_end(_foreground_messages())
    provider.shutdown()

    anchor_path = _active_task_anchor_path(provider._roots)
    records = _read_jsonl(anchor_path)
    # Most recent record should not be "active" (append-only JSONL means
    # the original active record is still on disk; the tombstone/
    # supersede records are the terminal state).  Both "completed" and
    # "superseded" are valid terminal states.
    assert records[-1]["status"] in {"completed", "superseded"}, (
        f"Expected completed or superseded, got: {records[-1]['status']}"
    )


# ── Regression: on_session_end tombstones even w/o foreground ───────────


def test_on_session_end_tombstones_without_foreground(tmp_path):
    """Session with no user foreground (pure tool/system) should still
    get its active anchor tombstoned — the tombstone must fire before
    the foreground guard, not after it."""
    provider = _init_provider(tmp_path, session_id="session-nofg")
    # Create an active anchor
    provider.on_pre_compress(_foreground_messages())

    # End session with pure tool messages (no user content → no foreground summary)
    provider.on_session_end([
        {"role": "tool", "content": "proc_xyz: clean shutdown"},
    ])
    provider.shutdown()

    anchor_path = _active_task_anchor_path(provider._roots)
    records = _read_jsonl(anchor_path)
    assert len(records) >= 2
    assert records[-1]["status"] == "completed", (
        f"Tombstone NOT written for session with no foreground: {records[-1]}"
    )


# ── Regression: unparseable timestamp rejected when age-gated ──────────


def test_unparseable_timestamp_rejected_with_age_gate(tmp_path):
    """When max_age_hours > 0 and created_at is unparseable, the anchor
    should be REJECTED (not silently recovered)."""
    provider = _init_provider(tmp_path, session_id="session-now")

    anchor_path = _active_task_anchor_path(provider._roots)
    anchor_path.parent.mkdir(parents=True, exist_ok=True)
    bad_record = {
        "schema_version": "memory-os.active_task_anchor.v0",
        "record_id": "ata_baddate",
        "created_at": "garbage-not-a-date",
        "profile": "memoryos-test",
        "session_id": "session-old",
        "anchor": "### Memory-OS Current Task Anchor\n- current task: 损坏时间戳任务\n- session: session-old",
        "status": "active",
        "storage_policy": "runtime_system_metadata_not_canonical_memory",
    }
    anchor_path.write_text(
        json.dumps(bad_record, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    recovered = provider._read_latest_active_task_anchor(max_age_hours=24)
    provider.shutdown()

    assert recovered == "", (
        f"Anchor with unparseable timestamp should be rejected when age-gated,"
        f" got: {recovered!r}"
    )


# ── Regression: unparseable timestamp still recovered w/o age gate ──────


def test_unparseable_timestamp_recovered_without_age_gate(tmp_path):
    """When max_age_hours=0 (default), unparseable timestamps should still
    be recovered (backward-compatible fail-open)."""
    provider = _init_provider(tmp_path, session_id="session-now")

    anchor_path = _active_task_anchor_path(provider._roots)
    anchor_path.parent.mkdir(parents=True, exist_ok=True)
    bad_record = {
        "schema_version": "memory-os.active_task_anchor.v0",
        "record_id": "ata_baddate2",
        "created_at": "garbage-not-a-date",
        "profile": "memoryos-test",
        "session_id": "session-other",
        "anchor": "### Memory-OS Current Task Anchor\n- current task: 无年龄门任务\n- session: session-other",
        "status": "active",
        "storage_policy": "runtime_system_metadata_not_canonical_memory",
    }
    anchor_path.write_text(
        json.dumps(bad_record, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    recovered = provider._read_latest_active_task_anchor()
    provider.shutdown()

    assert recovered != "", "Without age gate, even bad-timestamp anchors should recover"
    assert "无年龄门任务" in recovered


# ── on_pre_compress: preserve in-memory anchor when builder returns "" ────


def test_on_pre_compress_preserves_anchor_when_no_user_foreground(tmp_path):
    """When _build_current_task_anchor returns '' (no user messages), the
    in-memory anchor should NOT be overwritten so _clear_active_task_anchor
    can still tombstone it at session end."""
    provider = _init_provider(tmp_path, session_id="session-pf")

    # Set up a known in-memory anchor (simulating recovery from disk)
    provider._current_task_anchor = (
        "### Memory-OS Current Task Anchor\n"
        "- current task: 已恢复的部署任务\n"
        "- session: session-pf"
    )

    # Call on_pre_compress with messages that have NO user role
    result = provider.on_pre_compress([
        {"role": "tool", "content": "proc_xyz: background heartbeat"},
        {"role": "assistant", "content": "checkpoint saved"},
    ])

    # The in-memory anchor should survive — not be replaced with ""
    assert provider._current_task_anchor != "", (
        "on_pre_compress should preserve the previous anchor when no user foreground exists"
    )
    assert "已恢复的部署任务" in provider._current_task_anchor
    # And the return value should also reflect the preserved anchor
    assert "已恢复的部署任务" in result
    provider.shutdown()


def test_on_pre_compress_preserves_anchor_allows_tombstone(tmp_path):
    """Full chain: preserved anchor → on_session_end can still tombstone it."""
    provider = _init_provider(tmp_path, session_id="session-chain")

    # First, a normal pre_compress with user content writes an active anchor
    provider.on_pre_compress([
        {"role": "user", "content": "部署生产环境"},
        {"role": "assistant", "content": "terminal: deploy production"},
    ])

    anchor_path = _active_task_anchor_path(provider._roots)
    records_before = _read_jsonl(anchor_path)
    assert records_before[-1]["status"] == "active"

    # Then a tool-only pre_compress — this must NOT nuke the in-memory anchor
    provider.on_pre_compress([
        {"role": "tool", "content": "proc_xyz: health check OK"},
    ])

    # The in-memory anchor should still have the original task
    assert "部署生产环境" in provider._current_task_anchor, (
        "on_pre_compress with no user foreground should not overwrite the anchor"
    )

    # End the session — tombstone MUST be written
    provider.on_session_end([
        {"role": "tool", "content": "proc_xyz: clean shutdown"},
    ])
    provider.shutdown()

    records_after = _read_jsonl(anchor_path)
    # The last two records should be the tombstone chain (superseded → completed).
    # The original "active" record is at position -3 (append-only keeps it).
    statuses = [r["status"] for r in records_after]
    assert "completed" in statuses, (
        f"Tombstone NOT written after tool-only compress + session end."
        f" Statuses: {statuses}"
    )
    assert "active" not in statuses[-2:], (
        f"Recent records should not contain active status."
        f" Last 2 statuses: {statuses[-2:]}"
    )


# ── on_session_end: _supersede_active_anchors safety net ────────────────


def test_on_session_end_supersedes_without_in_memory_anchor(tmp_path):
    """When _current_task_anchor is empty, on_session_end must still scan
    the disk and supersede any active records (safety net)."""
    provider = _init_provider(tmp_path, session_id="session-net")

    # Manually write an active record to disk WITHOUT setting the in-memory field
    anchor_path = _active_task_anchor_path(provider._roots)
    anchor_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    orphan_record = {
        "schema_version": "memory-os.active_task_anchor.v0",
        "record_id": "ata_orphan",
        "created_at": now,
        "profile": "memoryos-test",
        "session_id": "session-net",
        "anchor": "### Memory-OS Current Task Anchor\n- current task: 孤立任务\n- session: session-net",
        "status": "active",
        "storage_policy": "runtime_system_metadata_not_canonical_memory",
    }
    anchor_path.write_text(
        json.dumps(orphan_record, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Ensure in-memory anchor is empty (simulating the bug scenario)
    provider._current_task_anchor = ""

    # End the session — even without in-memory anchor, the disk must be cleaned
    provider.on_session_end([
        {"role": "tool", "content": "proc_xyz: shutdown"},
    ])
    provider.shutdown()

    records = _read_jsonl(anchor_path)
    # Most recent record should be superseded (from _supersede_active_anchors)
    assert len(records) >= 2, f"Expected at least 2 records, got {len(records)}"
    assert records[-1]["status"] == "superseded", (
        f"Safety net failed: expected 'superseded' as last record,"
        f" got {records[-1]['status']}"
    )


def test_on_session_end_both_tombstone_and_supersede(tmp_path):
    """Normal path: on_session_end writes a completed tombstone.  The
    internal _supersede_active_anchors inside _write_active_task_anchor
    already cleans up the prior active record."""
    provider = _init_provider(tmp_path, session_id="session-both")

    # Create an active anchor normally
    provider.on_pre_compress([
        {"role": "user", "content": "正常任务"},
        {"role": "assistant", "content": "terminal: run task"},
    ])

    anchor_path = _active_task_anchor_path(provider._roots)
    records_before = _read_jsonl(anchor_path)
    assert records_before[-1]["status"] == "active"

    # End session normally
    provider.on_session_end([
        {"role": "user", "content": "结束"},
    ])
    provider.shutdown()

    records_after = _read_jsonl(anchor_path)
    statuses = [r["status"] for r in records_after]

    # Normal path: _clear_active_task_anchor writes completed (which internally
    # supersedes the active first).  The direct _supersede_active_anchors is NOT
    # called because _current_task_anchor is set.  So we get:
    #   active → superseded → completed
    assert "completed" in statuses, f"Expected completed tombstone, got statuses: {statuses}"
    assert records_after[-1]["status"] == "completed", (
        f"Last record should be 'completed' in normal path,"
        f" got {records_after[-1]['status']}"
    )
    # The original active record is at -3; the last two (superseded, completed) should
    # contain no active status.
    assert statuses[-2:].count("active") == 0, (
        f"No active status expected in last 2 records, got: {statuses[-2:]}"
    )
