"""Tests for community roster management."""

import pytest
import json
from pathlib import Path
from plugins.memory.memory_os.community import (
    RosterEntry, validate_roster, add_to_roster, get_active_roster, build_community_snapshot
)


class TestRosterEntry:
    def test_defaults(self):
        entry = RosterEntry(id="test-01", name="Test")
        assert entry.status == "active"
        assert entry.relationship == "acquaintance"
        assert entry.lifecycle == "open-ended"

    def test_to_dict(self):
        entry = RosterEntry(id="test-01", name="Test", backend="kimi-k2.6")
        d = entry.to_dict()
        assert d["id"] == "test-01"
        assert d["schema_version"] == "memory-os.community.roster.v1"


class TestValidateRoster:
    def test_missing_file(self, tmp_path: Path) -> None:
        errors = validate_roster(tmp_path / "nonexistent.jsonl")
        assert "roster file not found" in errors

    def test_valid_roster(self, tmp_path: Path) -> None:
        p = tmp_path / "roster.jsonl"
        p.write_text(json.dumps({"id": "kimi-01", "name": "阿澜", "status": "active"}) + "\n")
        errors = validate_roster(p)
        assert errors == []

    def test_duplicate_id(self, tmp_path: Path) -> None:
        p = tmp_path / "roster.jsonl"
        p.write_text(
            json.dumps({"id": "kimi-01", "name": "阿澜", "status": "active"}) + "\n" +
            json.dumps({"id": "kimi-01", "name": "阿澜2", "status": "active"}) + "\n"
        )
        errors = validate_roster(p)
        assert any("duplicate id" in e for e in errors)

    def test_invalid_status(self, tmp_path: Path) -> None:
        p = tmp_path / "roster.jsonl"
        p.write_text(json.dumps({"id": "kimi-01", "name": "阿澜", "status": "unknown"}) + "\n")
        errors = validate_roster(p)
        assert any("invalid status" in e for e in errors)


class TestAddToRoster:
    def test_add_new(self, tmp_path: Path) -> None:
        p = tmp_path / "roster.jsonl"
        entry = RosterEntry(id="kimi-01", name="阿澜")
        errors = add_to_roster(p, entry)
        assert errors == []
        assert p.exists()

    def test_duplicate_rejected(self, tmp_path: Path) -> None:
        p = tmp_path / "roster.jsonl"
        entry = RosterEntry(id="kimi-01", name="阿澜")
        add_to_roster(p, entry)
        errors = add_to_roster(p, entry)
        assert any("duplicate" in e for e in errors)


class TestGetActiveRoster:
    def test_active_only(self, tmp_path: Path) -> None:
        p = tmp_path / "roster.jsonl"
        p.write_text(
            json.dumps({"id": "kimi-01", "name": "阿澜", "status": "active"}) + "\n" +
            json.dumps({"id": "kimi-02", "name": "退休君", "status": "retired"}) + "\n"
        )
        entries = get_active_roster(p)
        assert len(entries) == 1
        assert entries[0].name == "阿澜"


class TestBuildSnapshot:
    def test_snapshot(self, tmp_path: Path) -> None:
        p = tmp_path / "roster.jsonl"
        p.write_text(json.dumps({"id": "kimi-01", "name": "阿澜", "status": "active"}) + "\n")
        snap = build_community_snapshot(p)
        assert snap["active_partners"] == ["阿澜"]
        assert snap["partner_count"] == 1