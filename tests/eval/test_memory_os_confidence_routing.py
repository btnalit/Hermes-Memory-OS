from eval.memory_os.runner.run import run_rh31_eval


def test_confidence_routing_adapter_exercises_shadow_bands(tmp_path):
    summary = run_rh31_eval(
        fixture="synthetic",
        adapters=["confidence_routing"],
        report_root=tmp_path / "eval" / "reports",
        write_report=False,
    )

    assert summary["status"] == "pass"
    assert summary["adapter_count"] == 1
    assert summary["scores"][0]["adapter"] == "confidence_routing"
    assert summary["scores"][0]["details"]["band_distribution"] == {"high": 1, "low": 1, "mid": 1}
    assert summary["scores"][0]["live_behavior_changed"] is False
