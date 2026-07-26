"""Tests for seed evidence incremental reader."""

import pytest
import json
from pathlib import Path
from plugins.memory.memory_os.seed_evidence_incremental import (
    read_seed_evidence_incremental,
    read_seed_evidence_by_cursor,
    get_seed_evidence_cursor,
    verify_incremental_equivalence,
)


def _write_jsonl(path: Path, records: list[dict]) -> None:
    lines = [json.dumps(r) for r in records]
    path.write_text("\n".join(lines), encoding="utf-8")


class TestReadIncremental:
    def test_read_all(self, tmp_path: Path) -> None:
        p = tmp_path / "test.jsonl"
        _write_jsonl(p, [{"id": str(i), "created_at": f"2026-07-2{i}T00:00:00Z"} for i in range(5)])
        result = read_seed_evidence_incremental(p, offset=0, limit=10)
        assert len(result) == 5

    def test_offset(self, tmp_path: Path) -> None:
        p = tmp_path / "test.jsonl"
        _write_jsonl(p, [{"id": str(i)} for i in range(10)])
        result = read_seed_evidence_incremental(p, offset=5, limit=10)
        assert len(result) == 5
        assert result[0]["id"] == "5"

    def test_limit(self, tmp_path: Path) -> None:
        p = tmp_path / "test.jsonl"
        _write_jsonl(p, [{"id": str(i)} for i in range(100)])
        result = read_seed_evidence_incremental(p, offset=0, limit=10)
        assert len(result) == 10

    def test_empty_file(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.jsonl"
        p.write_text("", encoding="utf-8")
        result = read_seed_evidence_incremental(p)
        assert len(result) == 0


class TestReadByCursor:
    def test_cursor_filter(self, tmp_path: Path) -> None:
        p = tmp_path / "test.jsonl"
        _write_jsonl(p, [
            {"id": "1", "created_at": "2026-07-20T00:00:00Z"},
            {"id": "2", "created_at": "2026-07-22T00:00:00Z"},
            {"id": "3", "created_at": "2026-07-24T00:00:00Z"},
        ])
        result = read_seed_evidence_by_cursor(p, cursor_value="2026-07-22T00:00:00Z")
        assert len(result) == 1
        assert result[0]["id"] == "3"

    def test_no_cursor(self, tmp_path: Path) -> None:
        p = tmp_path / "test.jsonl"
        _write_jsonl(p, [{"id": "1"}, {"id": "2"}])
        result = read_seed_evidence_by_cursor(p)
        assert len(result) == 2


class TestGetCursor:
    def test_get_last_cursor(self, tmp_path: Path) -> None:
        p = tmp_path / "test.jsonl"
        _write_jsonl(p, [
            {"id": "1", "created_at": "2026-07-20T00:00:00Z"},
            {"id": "2", "created_at": "2026-07-22T00:00:00Z"},
        ])
        cursor = get_seed_evidence_cursor(p)
        assert cursor == "2026-07-22T00:00:00Z"

    def test_empty_file(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.jsonl"
        p.write_text("", encoding="utf-8")
        cursor = get_seed_evidence_cursor(p)
        assert cursor == ""


class TestVerifyEquivalence:
    def test_equivalent(self, tmp_path: Path) -> None:
        p = tmp_path / "test.jsonl"
        records = [{"id": str(i), "value": f"x{i}"} for i in range(25)]
        _write_jsonl(p, records)
        result = verify_incremental_equivalence(p, chunk_size=10)
        assert result["equivalent"] is True
        assert result["full_count"] == 25
        assert result["incremental_count"] == 25