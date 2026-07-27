"""Tests for community shared memory, triggers, and snapshot."""

import pytest
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from plugins.memory.memory_os.community_shared import (
    write_shared_memory, read_shared_memory, get_open_threads,
    write_newspaper_entry, get_community_newspaper
)
from plugins.memory.memory_os.community_triggers import (
    PartnerState, check_silence_trigger, check_pending_thoughts_trigger,
    check_shared_followup_trigger, check_newspaper_trigger, evaluate_all_triggers
)
from plugins.memory.memory_os.community_snapshot import build_community_snapshot


class TestSharedMemory:
    def test_write_and_read(self, tmp_path: Path) -> None:
        entry = write_shared_memory(tmp_path, "test-01", "聊了关于记忆系统的话题", actor="sannai")
        assert entry.summary == "聊了关于记忆系统的话题"
        entries = read_shared_memory(tmp_path, "test-01")
        assert len(entries) == 1
        assert entries[0].summary == "聊了关于记忆系统的话题"

    def test_open_threads(self, tmp_path: Path) -> None:
        write_shared_memory(tmp_path, "test-01", "话题1", actor="sannai", thread="open")
        write_shared_memory(tmp_path, "test-01", "话题2", actor="sannai", thread="closed")
        open_threads = get_open_threads(tmp_path, "test-01")
        assert len(open_threads) == 1
        assert open_threads[0].summary == "话题1"

    def test_newspaper(self, tmp_path: Path) -> None:
        write_newspaper_entry(tmp_path, "今日新闻：AI 新突破", actor="info_collect")
        entries = get_community_newspaper(tmp_path)
        assert len(entries) == 1
        assert "AI 新突破" in entries[0].summary


class TestTriggers:
    def test_silence_trigger(self):
        state = PartnerState(
            partner_id="test-01",
            name="测试",
            last_interaction=(datetime.now(timezone.utc) - timedelta(hours=72)).isoformat(),
        )
        result = check_silence_trigger(state, silence_hours=48)
        assert result.should_trigger
        assert "久没聊" in result.suggested_message

    def test_no_silence_trigger(self):
        state = PartnerState(
            partner_id="test-01",
            name="测试",
            last_interaction=datetime.now(timezone.utc).isoformat(),
        )
        result = check_silence_trigger(state, silence_hours=48)
        assert not result.should_trigger

    def test_pending_thoughts(self):
        state = PartnerState(
            partner_id="test-01",
            name="测试",
            pending_thoughts=["想问问她最近在忙什么"],
        )
        result = check_pending_thoughts_trigger(state)
        assert result.should_trigger
        assert result.priority == "high"

    def test_shared_followup(self, tmp_path: Path):
        from plugins.memory.memory_os.community_shared import write_shared_memory
        write_shared_memory(tmp_path, "test-01", "在修一个 bug", actor="sannai", thread="open", sannai_feeling="好奇")
        state = PartnerState(partner_id="test-01", name="测试")
        result = check_shared_followup_trigger(state, tmp_path)
        assert result.should_trigger

    def test_newspaper_trigger(self, tmp_path: Path):
        from plugins.memory.memory_os.community_shared import write_newspaper_entry
        write_newspaper_entry(tmp_path, "新文章：关于记忆系统", actor="info_collect")
        state = PartnerState(partner_id="test-01", name="测试")
        result = check_newspaper_trigger(state, tmp_path)
        assert result.should_trigger


class TestSnapshot:
    def test_empty_community(self, tmp_path: Path) -> None:
        community = tmp_path / "community"
        community.mkdir()
        snap = build_community_snapshot(community)
        assert snap["partner_count"] == 0

    def test_with_roster(self, tmp_path: Path) -> None:
        community = tmp_path / "community"
        community.mkdir()
        roster = community / "roster.jsonl"
        roster.write_text(json.dumps({"id": "test-01", "name": "阿澜", "status": "active"}) + "\n")
        snap = build_community_snapshot(community)
        assert snap["partner_count"] == 1
        assert "阿澜" in snap["active_partners"]