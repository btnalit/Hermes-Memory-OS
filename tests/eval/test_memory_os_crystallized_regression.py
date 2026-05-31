from eval.memory_os.runner.run import run_rh31_eval


def test_crystallized_regression_adapter_flags_would_demotion_only(tmp_path):
    summary = run_rh31_eval(
        fixture="synthetic",
        adapters=["crystallized_regression"],
        report_root=tmp_path / "eval" / "reports",
        write_report=False,
    )

    assert summary["status"] == "pass"
    assert summary["adapter_count"] == 1
    assert summary["scores"][0]["adapter"] == "crystallized_regression"
    assert summary["scores"][0]["details"]["flag_count"] == 1
    assert summary["scores"][0]["live_behavior_changed"] is False
