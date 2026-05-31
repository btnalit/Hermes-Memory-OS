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
