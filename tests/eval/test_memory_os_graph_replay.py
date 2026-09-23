"""G4 — offline graph replay evaluation.

Targets PR-G1's acceptance bar (docs/plans/2026-09-23-memory-os-next-phase-plan.md
Phase 3): 100% recall on the near-verbatim-restatement subset, zero false
positives on the paraphrase / cross-kind subsets, zero stale-version
injections. These assertions describe the POST-G1 behaviour the deterministic
structural proposer must reach — before PR-G1 lands, `updates_recall` on the
positive subset is 0.0 (the relation does not exist yet), which is the
expected pre-G1 baseline, not a bug in this test.
"""
from __future__ import annotations

from eval.memory_os.runner.run import run_rh31_eval


def test_graph_replay_report_schema_and_case_coverage():
    from eval.memory_os.adapters.graph_replay import build_graph_replay_report

    report = build_graph_replay_report()

    assert report["schema_version"] == "memory-os.graph_replay_eval.v0"
    assert report["case_count"] >= 30
    assert set(report["subset_case_counts"]) == {
        "near_verbatim_restatement",
        "paraphrase_low_dice",
        "unrelated_same_kind",
        "cross_kind_high_overlap",
    }
    assert all(count > 0 for count in report["subset_case_counts"].values())
    assert report["route_live_applied"] is False
    assert report["score_live_applied"] is False
    assert report["canonical_state_changed"] is False
    assert report["forbidden_field_count"] == 0
    assert report["boundary_true_count"] == 0


def test_graph_replay_recall_on_near_verbatim_restatement_subset():
    from eval.memory_os.adapters.graph_replay import build_graph_replay_report

    report = build_graph_replay_report()
    entry = report["subset_reports"]["near_verbatim_restatement"]
    assert entry["status"] == "sampled"
    assert entry["updates_recall"] == 1.0, (
        "deterministic proposer must fire `updates` on every near-verbatim, "
        "same-kind restatement pair once PR-G1 lands"
    )


def test_graph_replay_zero_false_positives_on_paraphrase_and_cross_kind():
    from eval.memory_os.adapters.graph_replay import build_graph_replay_report

    report = build_graph_replay_report()
    for subset in ("paraphrase_low_dice", "cross_kind_high_overlap", "unrelated_same_kind"):
        entry = report["subset_reports"][subset]
        assert entry["status"] == "sampled"
        assert entry["false_positive_count"] == 0, (
            f"deterministic `updates` must never fire on subset={subset}"
        )


def test_graph_replay_direction_is_newer_to_older():
    from eval.memory_os.adapters.graph_replay import build_graph_replay_report

    report = build_graph_replay_report()
    direction = report["direction_report"]
    assert direction["status"] == "sampled"
    assert direction["accuracy"] == 1.0


def test_graph_replay_no_stale_version_double_injection():
    from eval.memory_os.adapters.graph_replay import build_graph_replay_report

    report = build_graph_replay_report()
    assert report["stale_version_injection_count"] == 0


def test_graph_replay_gate_fails_when_latest_wins_suppression_breaks(tmp_path, monkeypatch):
    """Review SHOULD-FIX 3 counterfactual: stale_version_injection_count can
    only move if one updates pair is injected twice inside a two-record case,
    which cannot happen, so the gate never measured the injection half of
    PR-G1. With suppression broken the eval must fail."""
    from plugins.memory.memory_os.index import MemoryOSIndex

    healthy = run_rh31_eval(
        fixture="synthetic", adapters=["graph_replay"],
        report_root=tmp_path / "healthy", write_report=False,
    )
    latest = healthy["scores"][0]["details"]["latest_wins_report"]
    assert latest["status"] == "sampled" and latest["expected_count"] > 0
    assert latest["observed_count"] == latest["expected_count"]

    original = MemoryOSIndex.query_edges

    def _no_updates_lookup(self, anchor_ids, *args, relation_types=None, **kwargs):
        if relation_types == ["updates"]:
            return []
        return original(self, anchor_ids, *args, relation_types=relation_types, **kwargs)

    monkeypatch.setattr(MemoryOSIndex, "query_edges", _no_updates_lookup)
    broken = run_rh31_eval(
        fixture="synthetic", adapters=["graph_replay"],
        report_root=tmp_path / "broken", write_report=False,
    )
    assert broken["scores"][0]["details"]["latest_wins_report"]["observed_count"] == 0
    assert broken["status"] != "pass"


def test_graph_replay_empty_corpus_reports_healthy_no_sample(tmp_path):
    from eval.memory_os.adapters.graph_replay import build_graph_replay_report

    empty_path = tmp_path / "empty_graph_replay_cases.jsonl"
    empty_path.write_text("", encoding="utf-8")

    report = build_graph_replay_report(cases_path=empty_path)

    assert report["case_count"] == 0
    for subset in report["subset_reports"].values():
        assert subset["status"] == "healthy_no_sample"
    assert report["direction_report"]["status"] == "healthy_no_sample"
    assert report["novelty_report"]["status"] == "healthy_no_sample"
    assert report["novelty_report"]["mean_injected_novelty"] is None
    assert report["coverage_report"]["status"] == "healthy_no_sample"


def test_graph_replay_missing_cases_file_reports_healthy_no_sample(tmp_path):
    from eval.memory_os.adapters.graph_replay import build_graph_replay_report

    report = build_graph_replay_report(cases_path=tmp_path / "does_not_exist.jsonl")

    assert report["case_count"] == 0
    assert report["forbidden_field_count"] == 0


def test_graph_replay_adapter_runs_through_rh31_registry(tmp_path):
    summary = run_rh31_eval(
        fixture="synthetic",
        adapters=["graph_replay"],
        report_root=tmp_path / "reports",
        write_report=False,
    )

    assert summary["schema_version"] == "memory-os.rh31_summary.v0"
    assert [adapter["name"] for adapter in summary["adapters"]] == ["graph_replay"]
    assert summary["boundary_true_count"] == 0
    assert summary["forbidden_field_count"] == 0
    score = summary["scores"][0]
    assert score["metric_scope"] == "graph_replay"
    assert score["details"]["schema_version"] == "memory-os.graph_replay_eval.v0"
    assert summary["status"] == "pass"
