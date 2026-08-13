import json

from plugins.memory.memory_os.lane_last_run import (
    LANE_LAST_RUN_SCHEMA_VERSION,
    lane_last_run_path,
    read_lane_last_run,
    record_lane_last_run,
)


def test_record_and_read_round_trip(tmp_path):
    assert record_lane_last_run(
        tmp_path,
        "index_sync",
        status="ok",
        reason="synced",
        counters={"events": 3, "drift_count": 0},
    )

    record = read_lane_last_run(tmp_path, "index_sync")

    assert record is not None
    assert record["schema_version"] == LANE_LAST_RUN_SCHEMA_VERSION
    assert record["lane_id"] == "index_sync"
    assert record["status"] == "ok"
    assert record["reason"] == "synced"
    assert record["counters"] == {"events": 3, "drift_count": 0}
    assert record["recorded_at"].endswith("Z")


def test_record_overwrites_previous_run(tmp_path):
    record_lane_last_run(tmp_path, "lane_x", status="ok", reason="produced")
    record_lane_last_run(tmp_path, "lane_x", status="skipped", reason="no_eligible_input")

    record = read_lane_last_run(tmp_path, "lane_x")

    assert record["status"] == "skipped"
    assert record["reason"] == "no_eligible_input"


def test_unknown_status_is_coerced_to_error_and_error_text_bounded(tmp_path):
    record_lane_last_run(
        tmp_path,
        "lane_y",
        status="mystery",
        reason="boom",
        error="x" * 1000,
    )

    record = read_lane_last_run(tmp_path, "lane_y")

    assert record["status"] == "error"
    assert len(record["error"]) <= 300


def test_non_int_counters_are_dropped_not_fatal(tmp_path):
    record_lane_last_run(
        tmp_path,
        "lane_z",
        status="ok",
        reason="produced",
        counters={"good": 1, "bad": "not-an-int"},
    )

    record = read_lane_last_run(tmp_path, "lane_z")

    assert record["counters"] == {"good": 1}


def test_write_failure_is_fail_open(tmp_path, capsys):
    # Occupy the lane_last_run *path segment* with a file so mkdir fails.
    blocker = tmp_path / "memory-os" / "system"
    blocker.parent.mkdir(parents=True)
    blocker.write_text("not a directory", encoding="utf-8")

    assert record_lane_last_run(tmp_path, "lane_w", status="ok", reason="produced") is False
    assert "lane_last_run: write failed" in capsys.readouterr().err


def test_read_returns_none_for_absent_or_malformed(tmp_path):
    assert read_lane_last_run(tmp_path, "missing_lane") is None

    path = lane_last_run_path(tmp_path, "broken_lane")
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    assert read_lane_last_run(tmp_path, "broken_lane") is None

    path.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")
    assert read_lane_last_run(tmp_path, "broken_lane") is None
