"""Tests for partner creation."""

import pytest
import json
from pathlib import Path
from plugins.memory.memory_os.partner_create import (
    create_partner, generate_partner_id, make_soul_md
)


class TestGeneratePartnerId:
    def test_simple(self):
        pid = generate_partner_id("阿澜")
        assert pid.startswith("阿澜-")
        assert len(pid) > 5

    def test_special_chars(self):
        pid = generate_partner_id("Test Friend!")
        assert pid.startswith("testfriend-")


class TestMakeSoulMd:
    def test_contains_name(self):
        soul = make_soul_md("阿澜", "理性、好奇", "alan-001")
        assert "阿澜" in soul
        assert "alan-001" in soul
        assert "理性、好奇" in soul


class TestCreatePartner:
    def test_create_partner(self, tmp_path: Path) -> None:
        mos_root = tmp_path / "memory-os"
        (mos_root / "community").mkdir(parents=True)
        (mos_root / "community" / "roster.jsonl").touch()
        (mos_root / "community" / "charters").mkdir()

        result = create_partner(
            mos_root,
            name="测试伙伴",
            personality="好奇、友善",
            partner_id="test-001",
            tags=["测试"],
        )
        assert result.status == "ok"
        assert result.partner_id == "test-001"

        # Verify roster
        roster = mos_root / "community" / "roster.jsonl"
        content = roster.read_text()
        assert "test-001" in content
        assert "测试伙伴" in content

        # Verify profile
        profile = mos_root / "community" / "partners" / "test-001"
        assert (profile / "SOUL.md").exists()
        assert (profile / "memory" / "about_sannai.jsonl").exists()
        assert (profile / "memory" / "state.json").exists()

    def test_duplicate_id(self, tmp_path: Path) -> None:
        mos_root = tmp_path / "memory-os"
        (mos_root / "community").mkdir(parents=True)
        (mos_root / "community" / "roster.jsonl").touch()
        (mos_root / "community" / "charters").mkdir()

        # Create first
        r1 = create_partner(mos_root, "A", "friendly", partner_id="dup-01")
        assert r1.status == "ok"

        # Create second with same id - should still work (append-only)
        r2 = create_partner(mos_root, "B", "curious", partner_id="dup-01")
        assert r2.status == "ok"  # append-only, not a duplicate check