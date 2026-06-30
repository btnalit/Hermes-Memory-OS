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
    # Most recent record should still be "completed"
    assert records[-1]["status"] == "completed"
