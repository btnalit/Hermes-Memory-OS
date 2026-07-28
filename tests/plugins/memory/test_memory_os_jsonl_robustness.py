"""
Property-based and fuzz tests for JSONL IO robustness.

Tests cover: truncated lines, BOM, mixed encoding, non-object JSON,
over-long lines, empty lines, and error-record boundaries.
"""

import pytest
import json
from pathlib import Path
from plugins.memory.memory_os.jsonl_io import (
    read_jsonl,
    read_jsonl_result,
    append_jsonl,
    build_error_record,
    JsonlReadResult,
    ERROR_RECORD_SCHEMA_VERSION,
)


def _write_jsonl(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines), encoding="utf-8")


class TestReadJsonl:
    def test_empty_file(self, tmp_path: Path) -> None:
        p = tmp_path / "test.jsonl"
        p.write_text("", encoding="utf-8")
        result = read_jsonl(p)
        assert isinstance(result, list)
        assert len(result) == 0

    def test_valid_jsonl(self, tmp_path: Path) -> None:
        p = tmp_path / "test.jsonl"
        _write_jsonl(p, [
            '{"id": "1", "value": "a"}',
            '{"id": "2", "value": "b"}',
        ])
        result = read_jsonl(p)
        assert len(result) == 2
        assert result[0]["id"] == "1"
        assert result[1]["id"] == "2"

    def test_trailing_newline(self, tmp_path: Path) -> None:
        p = tmp_path / "test.jsonl"
        p.write_text('{"id": "1"}\n', encoding="utf-8")
        result = read_jsonl(p)
        assert len(result) == 1

    def test_mixed_whitespace_lines(self, tmp_path: Path) -> None:
        p = tmp_path / "test.jsonl"
        p.write_text('\n\n{"id": "1"}\n  \n{"id": "2"}\n\n', encoding="utf-8")
        result = read_jsonl(p)
        assert len(result) == 2

    def test_truncated_line(self, tmp_path: Path) -> None:
        p = tmp_path / "test.jsonl"
        p.write_text('{"id": "1", "value": "truncat', encoding="utf-8")
        result = read_jsonl(p)
        # Truncated JSON should not crash
        assert isinstance(result, list)

    def test_non_object_json(self, tmp_path: Path) -> None:
        p = tmp_path / "test.jsonl"
        _write_jsonl(p, [
            '{"id": "1"}',
            '"just a string"',
            '["an array"]',
            'null',
            '42',
            '{"id": "2"}',
        ])
        result = read_jsonl(p)
        # Non-object JSON lines should be skipped
        assert len(result) >= 2
        assert result[0]["id"] == "1"
        assert result[-1]["id"] == "2"

    def test_bom_utf8(self, tmp_path: Path) -> None:
        p = tmp_path / "test.jsonl"
        p.write_bytes(b'\xef\xbb\xbf{"id": "1"}\n{"id": "2"}')
        result = read_jsonl(p)
        # Should not crash, BOM may cause first line to be skipped
        assert isinstance(result, list)

    def test_mixed_encoding(self, tmp_path: Path) -> None:
        p = tmp_path / "test.jsonl"
        # Write a mix of valid UTF-8 and Latin-1 bytes
        p.write_bytes(b'{"id": "1", "text": "valid"}\n{"id": "2", "text": "\xe9\xe0\xf0"}\n')
        result = read_jsonl_result(p)
        assert result.records == [{"id": "1", "text": "valid"}]
        assert result.recent_error_codes == ["jsonl_invalid_utf8"]

    def test_nonexistent_file(self, tmp_path: Path) -> None:
        p = tmp_path / "nonexistent.jsonl"
        result = read_jsonl(p)
        assert len(result) == 0

    def test_large_file(self, tmp_path: Path) -> None:
        p = tmp_path / "large.jsonl"
        lines = [json.dumps({"id": str(i), "value": "x" * 100}) for i in range(1000)]
        _write_jsonl(p, lines)
        result = read_jsonl(p)
        assert len(result) == 1000

    def test_overlong_line(self, tmp_path: Path) -> None:
        """Very long lines should not crash the reader."""
        p = tmp_path / "long.jsonl"
        long_value = "x" * 100_000
        p.write_text(f'{{"id": "1", "value": "{long_value}"}}', encoding="utf-8")
        result = read_jsonl(p)
        assert len(result) >= 1

    def test_special_characters(self, tmp_path: Path) -> None:
        """Unicode, CJK, emoji, and control characters should not crash."""
        p = tmp_path / "special.jsonl"
        _write_jsonl(p, [
            json.dumps({"id": "1", "text": "中文测试"}),
            json.dumps({"id": "2", "text": "😀🚀测试"}),
            json.dumps({"id": "3", "text": "tab\there\nnewline"}),
            json.dumps({"id": "4", "text": "null\u0000char"}),
        ])
        result = read_jsonl(p)
        assert len(result) == 4


class TestReadJsonlResult:
    def test_read_with_errors(self, tmp_path: Path) -> None:
        p = tmp_path / "test.jsonl"
        _write_jsonl(p, [
            '{"id": "1"}',
            'invalid json',
            '{"id": "2"}',
        ])
        result = read_jsonl_result(p)
        assert isinstance(result, JsonlReadResult)
        assert len(result.records) >= 2
        assert result.suppressed_error_count >= 1


class TestBuildErrorRecord:
    def test_error_record_structure(self) -> None:
        error = build_error_record(
            component="test",
            operation="test_op",
            error_code="test_error",
            details={"key": "value"},
        )
        assert error.get("schema_version") == ERROR_RECORD_SCHEMA_VERSION
        assert error.get("error_code") == "test_error"
        assert error.get("component") == "test"
        assert error.get("operation") == "test_op"

    def test_error_record_optional_fields(self) -> None:
        error = build_error_record(
            component="test",
            operation="test_op",
            error_code="test_error",
            severity="error",
            recoverable=False,
            path="/tmp/test.jsonl",
        )
        assert error.get("severity") == "error"
        assert error.get("recoverable") is False
        assert error.get("path") == "/tmp/test.jsonl"


class TestAppendJsonl:
    def test_append_and_read(self, tmp_path: Path) -> None:
        p = tmp_path / "test.jsonl"
        append_jsonl(p, {"id": "1"})
        append_jsonl(p, {"id": "2"})
        result = read_jsonl(p)
        assert len(result) == 2
        assert result[0]["id"] == "1"
        assert result[1]["id"] == "2"

    def test_append_to_new_file(self, tmp_path: Path) -> None:
        p = tmp_path / "new.jsonl"
        assert not p.exists()
        append_jsonl(p, {"id": "1"})
        assert p.exists()
        result = read_jsonl(p)
        assert len(result) == 1