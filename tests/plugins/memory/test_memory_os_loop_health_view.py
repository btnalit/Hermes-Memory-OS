import json
from datetime import datetime, timezone

from plugins.memory.memory_os.cron_registry import (
    LANE_LAST_RUN_EVIDENCE,
    MEMORY_OS_CRON_LANES,
)
from plugins.memory.memory_os.lane_last_run import lane_last_run_path, record_lane_last_run
from plugins.memory.memory_os.loop_health_view import (
    LOOP_MEMBERS,
    build_loop_health_view,
    render_loop_health_summary,
)

_NOW = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)


def _loop(view, name):
    return next(loop for loop in view["loops"] if loop["loop"] == name)


def test_loop_members_partition_every_registered_lane_exactly_once():
    # Census in both directions, like the lane-evidence table: a new lane
    # cannot ship without being placed in a loop, and the view can never
    # name a lane that does not exist.
    registered = {lane.lane_id for lane in MEMORY_OS_CRON_LANES}
    placed: list[str] = [lane_id for members in LOOP_MEMBERS.values() for lane_id in members]

    assert sorted(placed) == sorted(set(placed)), "a lane appears in two loops"
    assert set(placed) == registered, (
        f"unplaced: {sorted(registered - set(placed))}; unknown: {sorted(set(placed) - registered)}"
    )


def test_view_reports_no_evidence_on_empty_home(tmp_path):
    view = build_loop_health_view(tmp_path, now=_NOW)

    assert view["schema_version"] == "memory-os.loop_health_view.v0"
    observability = _loop(view, "observability")
    assert observability["state"] == "no_evidence"
    assert observability["members"][0]["status"] == "no_evidence"


def test_fresh_ok_run_marks_loop_active(tmp_path):
    record_lane_last_run(tmp_path, "full_monitor_refresh", status="ok", reason="artifact_published")

    view = build_loop_health_view(tmp_path, now=datetime.now(timezone.utc))

    assert _loop(view, "observability")["state"] == "active"


def test_error_run_marks_loop_attention_even_with_fresh_ok_sibling(tmp_path):
    record_lane_last_run(tmp_path, "index_sync", status="ok", reason="synced")
    record_lane_last_run(tmp_path, "fact_judge", status="error", reason="lane_failed")

    view = build_loop_health_view(tmp_path, now=datetime.now(timezone.utc))

    memory_loop = _loop(view, "memory")
    assert memory_loop["state"] == "attention"
    fact_judge_row = next(m for m in memory_loop["members"] if m["lane_id"] == "fact_judge")
    assert fact_judge_row["reason"] == "lane_failed"


def test_only_skips_mark_loop_idle(tmp_path):
    record_lane_last_run(tmp_path, "expression_feedback_request", status="skipped", reason="outcome_silent")

    view = build_loop_health_view(tmp_path, now=datetime.now(timezone.utc))

    assert _loop(view, "expression")["state"] == "idle"


def test_stale_ok_run_does_not_count_as_active(tmp_path):
    # A weekly lane's ok from months ago must not keep its loop "active";
    # freshness derives from the lane's own due_interval_minutes.
    path = lane_last_run_path(tmp_path, "expression_feedback_request")
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "memory-os.lane_last_run.v0",
                "lane_id": "expression_feedback_request",
                "recorded_at": "2026-01-01T00:00:00Z",
                "status": "ok",
                "reason": "prompt_rendered",
            }
        ),
        encoding="utf-8",
    )

    view = build_loop_health_view(tmp_path, now=_NOW)

    expression = _loop(view, "expression")
    assert expression["members"][0]["stale"] is True
    assert expression["state"] == "idle"


def test_dedicated_artifact_lanes_point_to_their_own_evidence(tmp_path):
    view = build_loop_health_view(tmp_path, now=_NOW)

    graph = _loop(view, "graph")
    wandering = next(m for m in graph["members"] if m["lane_id"] == "v3_wandering")
    assert wandering["evidence"] == "dedicated_artifact"
    assert wandering["status"] == "see_dedicated_artifact"
    assert LANE_LAST_RUN_EVIDENCE["v3_wandering"] == "dedicated_artifact"


def test_render_summary_names_loops_and_reasons(tmp_path):
    record_lane_last_run(tmp_path, "index_sync", status="ok", reason="synced")

    text = render_loop_health_summary(build_loop_health_view(tmp_path, now=datetime.now(timezone.utc)))

    assert "memory" in text
    assert "index_sync=ok(synced)" in text
