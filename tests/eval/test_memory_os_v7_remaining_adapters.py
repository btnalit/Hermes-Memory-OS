from eval.memory_os.runner.run import run_rh31_eval


def test_remaining_v7_eval_adapters_pass_in_shadow_mode(tmp_path):
    adapters = [
        "scoring_band",
        "judge_consistency",
        "review_accuracy",
        "shadow_recall",
        "deferral_accuracy",
        "migration_regression",
        "expression_quality",
        "distillation_fidelity",
    ]

    summary = run_rh31_eval(
        fixture="synthetic",
        adapters=adapters,
        report_root=tmp_path / "reports",
        write_report=False,
    )

    assert summary["status"] == "pass"
    assert [adapter["name"] for adapter in summary["adapters"]] == adapters
    assert summary["boundary_true_count"] == 0
    assert summary["forbidden_field_count"] == 0
    assert {score["metric_scope"] for score in summary["scores"]} >= set(adapters)
