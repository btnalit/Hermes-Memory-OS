from eval.memory_os.runner.run import run_rh31_eval


def test_cross_check_anchoring_adapter_escalates_unanchored_double_blind(tmp_path):
    summary = run_rh31_eval(
        fixture="synthetic",
        adapters=["cross_check_anchoring"],
        report_root=tmp_path / "eval" / "reports",
        write_report=False,
    )

    assert summary["status"] == "pass"
    assert summary["adapter_count"] == 1
    assert summary["scores"][0]["adapter"] == "cross_check_anchoring"
    assert summary["scores"][0]["details"]["decision"] == "unresolvable"
    assert summary["scores"][0]["live_behavior_changed"] is False
