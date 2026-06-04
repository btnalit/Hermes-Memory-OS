import json

from plugins.memory.memory_os.jsonl_io import (
    append_jsonl,
    latest_jsonl_record,
    read_jsonl,
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
