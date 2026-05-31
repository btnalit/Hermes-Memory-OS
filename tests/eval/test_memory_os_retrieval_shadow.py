from __future__ import annotations

from eval.memory_os.runner.run import run_rh31_eval


def test_retrieval_shadow_reports_semantic_gap_without_live_route_apply():
    from eval.memory_os.adapters.retrieval_shadow import build_retrieval_shadow_report

    report = build_retrieval_shadow_report()

    assert report["schema_version"] == "memory-os.retrieval_shadow_eval.v0"
    assert report["case_count"] >= 1
    assert report["lexical_baseline_hit_count"] >= 0
    assert report["hybrid_would_retrieve_count"] >= 1
    assert report["semantic_gap_count"] >= 1
    assert report["rrf_would_rank_count"] >= 1
    assert report["route_live_applied"] is False
    assert report["score_live_applied"] is False
    assert report["canonical_state_changed"] is False
    assert report["forbidden_field_count"] == 0
    assert report["boundary_true_count"] == 0
    assert report["boundaries"] == {
        "actual_send": False,
        "actual_execute": False,
        "actual_identity_write": False,
        "actual_crystallized_approval": False,
    }


def test_retrieval_shadow_reads_live_memory_sources_metadata_only(tmp_path):
    from eval.memory_os.adapters.retrieval_shadow import build_retrieval_shadow_report

    hermes_home = tmp_path / "hermes-home"
    ledger = hermes_home / "memory-os" / "system" / "memory_sources.jsonl"
    ledger.parent.mkdir(parents=True)
    ledger.write_text(
        "\n".join(
            [
                (
                    '{"schema_version":"memory-os.memory_sources.v0","record_id":"msrc_1",'
                    '"route":"personal_recall","query_class":"personal_recall",'
                    '"selected":[{"heading":"Approved event","source_class":"event",'
                    '"source_ids":["event:abc","not-safe-id"],"chars":120,"score":0.9,'
                    '"reason_codes":["route_match"]}],'
                    '"dropped":[{"heading":"Candidate note","source_class":"candidate",'
                    '"count":1,"chars":80,"score":0.6,"reason_codes":["budget"]}],'
                    '"selected_chars_total":120,"boundary":{"actual_send":false}}'
                ),
                (
                    '{"schema_version":"memory-os.memory_sources.v0","record_id":"msrc_2",'
                    '"route":"ambiguous_recall","query_class":"ambiguous_recall",'
                    '"selected":[],"dropped":[{"heading":"Working note","source_class":"working",'
                    '"count":1,"chars":90,"score":0.5,"reason_codes":["low_budget"]}],'
                    '"selected_chars_total":0,"boundary":{"actual_send":false}}'
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    report = build_retrieval_shadow_report(hermes_home=hermes_home)

    assert report["live_input_available"] is True
    assert report["live_memory_sources_record_count"] == 2
    assert report["live_bounded_source_ref_count"] == 1
    assert report["live_route_distribution"] == {
        "ambiguous_recall": 1,
        "personal_recall": 1,
    }
    assert report["live_selected_source_class_distribution"] == {"event": 1}
    assert report["live_dropped_source_class_distribution"] == {
        "candidate": 1,
        "working": 1,
    }
    assert report["live_shadow_source_selection_miss_count"] == 1
    assert report["live_shadow_diversification_gap_count"] == 2
    assert report["live_shadow_low_coverage_count"] == 1
    assert report["live_route_live_applied"] is False
    assert report["live_score_live_applied"] is False
    assert report["live_canonical_state_changed"] is False
    rendered = str(report)
    assert "not-safe-id" not in rendered
    assert "Approved event" not in rendered
    assert report["forbidden_field_count"] == 0


def test_retrieval_shadow_adapter_runs_through_rh31_registry(tmp_path):
    summary = run_rh31_eval(
        fixture="synthetic",
        adapters=["retrieval_shadow"],
        report_root=tmp_path / "reports",
        write_report=False,
    )

    assert summary["schema_version"] == "memory-os.rh31_summary.v0"
    assert summary["status"] == "pass"
    assert [adapter["name"] for adapter in summary["adapters"]] == ["retrieval_shadow"]
    assert summary["boundary_true_count"] == 0
    assert summary["forbidden_field_count"] == 0
    score = summary["scores"][0]
    assert score["metric_scope"] == "retrieval_shadow"
    assert score["details"]["schema_version"] == "memory-os.retrieval_shadow_eval.v0"
    assert score["details"]["semantic_gap_count"] >= 1
    assert score["details"]["route_live_applied"] is False
    assert score["details"]["score_live_applied"] is False
