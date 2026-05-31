from eval.memory_os.data.v7_simulated import load_scenarios
from eval.memory_os.runner.run import run_rh31_eval


def test_imagination_loop_first_three_fixtures_are_simulated():
    scenarios = load_scenarios()
    ids = {scenario["scenario_id"] for scenario in scenarios}

    assert {"owner_can_be_wrong", "double_blind_unanchored", "cold_start_thin_evidence"} <= ids
    assert all(scenario["provenance"] == "simulated" for scenario in scenarios)


def test_simulation_coverage_adapter_passes_required_dimensions(tmp_path):
    summary = run_rh31_eval(
        fixture="synthetic",
        adapters=["simulation_coverage"],
        report_root=tmp_path / "eval" / "reports",
        write_report=False,
    )

    assert summary["status"] == "pass"
    assert summary["adapter_count"] == 1
    assert summary["scores"][0]["adapter"] == "simulation_coverage"
    assert summary["scores"][0]["live_behavior_changed"] is False


def test_v7_simulation_adapter_does_not_expand_default_all(tmp_path):
    summary = run_rh31_eval(
        fixture="synthetic",
        adapters=["all"],
        report_root=tmp_path / "eval" / "reports",
        write_report=False,
    )

    assert [adapter["name"] for adapter in summary["adapters"]] == [
        "grep",
        "memory_os_fts",
        "context_projection",
        "low_clue_candidates",
        "memory_sources_replay",
        "diagnostic_grounding",
    ]
