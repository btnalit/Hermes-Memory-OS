import json
from pathlib import Path

from plugins.memory.memory_os.jsonl_io import (
    append_jsonl,
    latest_jsonl_record,
    read_jsonl,
    read_jsonl_result,
    read_json_state_result,
    write_json_atomic,
    write_jsonl,
)


def test_jsonl_io_appends_reads_limits_and_skips_malformed_lines(tmp_path):
    path = tmp_path / "records.jsonl"

    append_jsonl(path, {"id": "a", "value": 1})
    path.write_text(path.read_text(encoding="utf-8") + "{not-json}\n[]\n", encoding="utf-8")
    append_jsonl(path, {"id": "b", "value": 2})

    assert read_jsonl(path) == [{"id": "a", "value": 1}, {"id": "b", "value": 2}]
    assert read_jsonl(path, limit=1) == [{"id": "a", "value": 1}]
    assert latest_jsonl_record(path) == {"id": "b", "value": 2}


def test_jsonl_io_writes_jsonl_and_atomic_json(tmp_path):
    jsonl_path = tmp_path / "nested" / "records.jsonl"
    json_path = tmp_path / "nested" / "state.json"

    write_jsonl(jsonl_path, [{"id": "x"}, {"id": "y"}])
    write_json_atomic(json_path, {"status": "ok", "count": 2})

    assert read_jsonl(jsonl_path) == [{"id": "x"}, {"id": "y"}]
    assert json.loads(json_path.read_text(encoding="utf-8")) == {"status": "ok", "count": 2}


def test_jsonl_io_result_records_malformed_lines_as_error_records(tmp_path):
    path = tmp_path / "records.jsonl"
    path.write_text('{"id":"ok"}\n{not-json}\n[]\n', encoding="utf-8")

    result = read_jsonl_result(path, component="fixture", operation="read_fixture")

    assert result.records == [{"id": "ok"}]
    assert result.suppressed_error_count == 2
    assert result.recent_error_codes == ["jsonl_malformed_line", "jsonl_non_object_line"]
    assert result.error_records[0]["schema_version"] == "memory-os.error_record.v0"
    assert result.error_records[0]["component"] == "fixture"
    assert result.error_records[0]["operation"] == "read_fixture"
    assert result.error_records[0]["error_code"] == "jsonl_malformed_line"
    assert result.error_records[0]["severity"] == "warning"
    assert result.error_records[0]["recoverable"] is True
    assert result.error_records[0]["path"] == str(path)
    assert result.error_records[0]["line_number"] == 2


def test_json_state_result_records_malformed_state_as_error_record(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not-json}", encoding="utf-8")

    result = read_json_state_result(path, component="fixture_state", operation="load_state")

    assert result.data == {}
    assert result.suppressed_error_count == 1
    assert result.recent_error_codes == ["json_state_malformed"]
    assert result.error_records[0]["schema_version"] == "memory-os.error_record.v0"
    assert result.error_records[0]["component"] == "fixture_state"
    assert result.error_records[0]["operation"] == "load_state"
    assert result.error_records[0]["path"] == str(path)


# ── jsonl_compact tests ────────────────────────────────────────────────────

from plugins.memory.memory_os.jsonl_io import jsonl_compact


class TestJsonlCompact:
    def test_compact_keeps_matching_predicate(self, tmp_path):
        path = tmp_path / "data.jsonl"
        write_jsonl(path, [
            {"id": "a", "status": "active"},
            {"id": "b", "status": "superseded"},
            {"id": "c", "status": "active"},
            {"id": "d", "status": "superseded"},
        ])

        result = jsonl_compact(path, lambda r: r.get("status") == "active", dry_run=False, backup=False)
        assert result["status"] == "ok"
        assert result["lines_before"] == 4
        assert result["lines_after"] == 2
        assert result["kept"] == 2
        assert result["dropped"] == 2

        kept = read_jsonl(path)
        assert [r["id"] for r in kept] == ["a", "c"]

    def test_compact_dry_run_does_not_write(self, tmp_path):
        path = tmp_path / "data.jsonl"
        write_jsonl(path, [{"n": i} for i in range(10)])

        original = path.read_text(encoding="utf-8")
        result = jsonl_compact(path, lambda r: r["n"] < 3, dry_run=True)
        assert result["dry_run"] is True
        assert result["lines_after"] == 3
        assert path.read_text(encoding="utf-8") == original  # unchanged

    def test_compact_max_lines_caps_output(self, tmp_path):
        path = tmp_path / "data.jsonl"
        write_jsonl(path, [{"n": i} for i in range(20)])

        result = jsonl_compact(path, lambda r: True, max_lines=5, dry_run=False, backup=False)
        assert result["lines_after"] == 5
        assert result["max_lines_applied"] is True

        kept = read_jsonl(path)
        assert [r["n"] for r in kept] == [15, 16, 17, 18, 19]  # tail

    def test_compact_skips_malformed_lines(self, tmp_path):
        path = tmp_path / "data.jsonl"
        write_jsonl(path, [{"id": "a"}, {"id": "b"}])
        # Insert malformed line
        raw = path.read_text(encoding="utf-8")
        path.write_text(raw + "{bad json\n", encoding="utf-8")

        result = jsonl_compact(path, lambda r: True, dry_run=False, backup=False)
        assert result["malformed"] == 1
        assert result["lines_before"] == 3  # 2 good + 1 malformed
        assert result["lines_after"] == 2

    def test_compact_no_change_returns_no_change(self, tmp_path):
        path = tmp_path / "data.jsonl"
        write_jsonl(path, [{"id": "a"}, {"id": "b"}])

        result = jsonl_compact(path, lambda r: True, dry_run=False, backup=False)
        assert result["status"] == "no_change"

    def test_compact_no_file_returns_no_file(self, tmp_path):
        path = tmp_path / "nonexistent.jsonl"
        result = jsonl_compact(path, lambda r: True)
        assert result["status"] == "no_file"

    def test_compact_creates_backup_when_requested(self, tmp_path):
        path = tmp_path / "data.jsonl"
        write_jsonl(path, [{"id": "a", "status": "active"}, {"id": "b", "status": "old"}])

        result = jsonl_compact(path, lambda r: r.get("status") == "active", dry_run=False, backup=True)
        assert result["status"] == "ok"
        assert result.get("backup_path") is not None
        assert Path(result["backup_path"]).exists()

    def test_compact_24k_superseded_stress(self, tmp_path):
        """Simulate 3.200's 24k superseded scenario: compact drops all but recent."""
        import json as _json
        path = tmp_path / "data.jsonl"
        # Build: 100 active/completed + 24000 superseded
        records = []
        for i in range(50):
            records.append({"id": f"active_{i}", "status": "active", "n": i})
        for i in range(50):
            records.append({"id": f"completed_{i}", "status": "completed", "n": i})
        for i in range(24000):
            records.append({"id": f"superseded_{i}", "status": "superseded", "n": i})
        path.write_text(
            "".join(_json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in records),
            encoding="utf-8",
        )

        result = jsonl_compact(path, lambda r: r.get("status") != "superseded", dry_run=False, backup=False)
        assert result["lines_before"] == 24100
        assert result["lines_after"] == 100  # only non-superseded
        assert result["kept"] == 100
        assert result["dropped"] == 24000
