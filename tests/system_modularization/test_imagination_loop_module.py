from plugins.modules.cognition.imagination_loop import ImaginationLoopModule


def test_imagination_loop_never_marks_live_behavior_changed(tmp_path):
    result = ImaginationLoopModule(tmp_path, profile="main").run_once()

    assert result["actual_send"] is False
    assert result["actual_execute"] is False
    assert result["live_behavior_changed"] is False
    assert result["candidate_written_to_canonical"] is False


def test_imagination_loop_writes_simulated_shadow_scenarios(tmp_path):
    module = ImaginationLoopModule(tmp_path, profile="main")

    result = module.run_once()

    assert result["status"] == "ok"
    assert result["scenario_count"] >= 5
    assert module.scenarios_path.exists()
    assert {record["provenance"] for record in module.read_scenarios()} == {"simulated"}
    assert all(record["live_applied"] is False for record in module.read_scenarios())


def test_imagination_loop_status_reports_jsonl_suppressed_errors(tmp_path):
    module = ImaginationLoopModule(tmp_path, profile="main")
    module.scenarios_path.parent.mkdir(parents=True)
    module.scenarios_path.write_text('{"provenance":"simulated"}\n{bad-json}\n', encoding="utf-8")

    status = module.status()

    assert status["scenario_count"] == 1
    assert status["suppressed_error_count"] == 1
    assert status["recent_error_codes"] == ["jsonl_malformed_line"]
