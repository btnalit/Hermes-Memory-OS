from eval.memory_os.runner.run import run_rh31_eval


def test_offload_integrity_eval_round_trips_offloaded_node(tmp_path):
    summary = run_rh31_eval(
        fixture="synthetic",
        adapters=["offload_integrity"],
        report_root=tmp_path / "reports",
        write_report=False,
    )

    assert summary["status"] == "pass"
    assert [adapter["name"] for adapter in summary["adapters"]] == ["offload_integrity"]
    score = summary["scores"][0]
    assert score["status"] == "pass"
    assert score["metric_scope"] == "offload_integrity"
    assert score["details"]["round_trip_exact"] is True
    assert score["details"]["actual_execute"] is False
