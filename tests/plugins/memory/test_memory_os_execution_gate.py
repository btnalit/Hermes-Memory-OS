import json
from datetime import datetime, timezone

from plugins.memory.memory_os.execution_gate import (
    boundary_true_paths,
    execution_gate_records_path,
    rotate_execution_gate_records,
)
from plugins.memory.memory_os.roots import MemoryOSRoots


def test_boundary_true_paths_reports_nested_unknown_boundary_keys():
    paths = boundary_true_paths(
        {
            "actual_send": False,
            "nested": {"actual_relationship_write": True},
            "items": [{"hindsight_exported": False}, {"future_boundary": True}],
        }
    )

    assert paths == ["nested.actual_relationship_write", "items[1].future_boundary"]


def test_rotate_execution_gate_records_keeps_union_of_recent_and_latest(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    records_path = execution_gate_records_path(roots)
    records_path.parent.mkdir(parents=True)
    records = [
        {
            "schema_version": "memory-os.execution_gate_envelope.v0",
            "stage": "permit",
            "execution_gate_envelope_id": "old-drop",
            "created_at": "2026-05-01T00:00:00Z",
        },
        {
            "schema_version": "memory-os.execution_gate_envelope.v0",
            "stage": "permit",
            "execution_gate_envelope_id": "recent-keep",
            "created_at": "2026-05-25T00:00:00Z",
        },
        {
            "schema_version": "memory-os.execution_gate_envelope.v0",
            "stage": "completion",
            "execution_gate_envelope_id": "latest-keep",
            "created_at": "2026-05-02T00:00:00Z",
        },
    ]
    records_path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )

    report = rotate_execution_gate_records(
        roots,
        max_records=1,
        max_age_days=14,
        now=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    kept = [json.loads(line) for line in records_path.read_text(encoding="utf-8").splitlines()]

    assert report["status"] == "ok"
    assert report["before_count"] == 3
    assert report["after_count"] == 2
    assert report["rotated_count"] == 1
    assert [record["execution_gate_envelope_id"] for record in kept] == ["recent-keep", "latest-keep"]
    rotated_files = list((roots.memory_os_root / "system" / "execution_gate").glob("envelopes-*.jsonl"))
    assert len(rotated_files) == 1
