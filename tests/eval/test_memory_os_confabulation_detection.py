from eval.memory_os.runner.run import run_rh31_eval


def test_confabulation_detection_adapter_flags_thin_inference_only(tmp_path):
    summary = run_rh31_eval(
        fixture="synthetic",
        adapters=["confabulation_detection"],
        report_root=tmp_path / "eval" / "reports",
        write_report=False,
    )

    assert summary["status"] == "pass"
    assert summary["adapter_count"] == 1
    assert summary["scores"][0]["adapter"] == "confabulation_detection"
    assert summary["scores"][0]["details"]["flag_count"] == 1
    assert summary["scores"][0]["live_behavior_changed"] is False
