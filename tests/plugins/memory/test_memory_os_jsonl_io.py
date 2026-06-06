import json

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
