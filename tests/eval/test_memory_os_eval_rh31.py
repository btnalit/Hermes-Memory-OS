from __future__ import annotations

import argparse
import json
from pathlib import Path

from plugins.memory.memory_os.cli import memory_os_command, register_cli
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.schema import EVENT_SCHEMA_VERSION, EventEnvelope
from plugins.memory.memory_os.store import MemoryOSStore


def test_rh31_inventory_reports_bounded_monitor_aligned_metadata(tmp_path):
    from eval.memory_os.runner.inventory import build_inventory

    store = _store(tmp_path)
    store.append_event(
        EventEnvelope(
            schema_version=EVENT_SCHEMA_VERSION,
            id="evt_001",
            ts="2026-05-25T01:02:03",
            profile="default",
            source="synthetic",
            kind="note",
            summary="互联网数据采集系统分层设计",
            tags=["design"],
        )
    )
    store.write_working_document(
        "lingering",
        {
            "schema_version": "memory-os.working.v0",
            "updated_at": "2026-05-25T01:03:00Z",
            "items": [
                {
                    "id": "work_001",
                    "kind": "thought",
                    "status": "active",
                    "created_at": "2026-05-25T01:03:00Z",
                    "updated_at": "2026-05-25T01:03:00Z",
                    "text": "n8n 与智能体编排方案",
                    "source_event_id": "evt_001",
                    "tags": ["automation"],
                    "weight": 0.8,
                }
            ],
        },
    )

    inventory = build_inventory(store)

    rendered = json.dumps(inventory, ensure_ascii=False)
    assert inventory["schema_version"] == "memory-os.rh31_inventory.v0"
    assert inventory["event_distribution"]["by_source"] == {"synthetic": 1}
    assert inventory["working_distribution"]["by_status"] == {"active": 1}
    assert "monitor_field_mapping" in inventory
    assert "memory_sources" in inventory["monitor_field_mapping"]
    assert "互联网数据采集系统分层设计" not in rendered
    assert "n8n 与智能体编排方案" not in rendered


def test_rh31_runner_writes_scorecard_artifacts_without_canonical_writes(tmp_path):
    from eval.memory_os.runner.run import run_rh31_eval

    report_root = tmp_path / "eval" / "reports"

    summary = run_rh31_eval(
        fixture="synthetic",
        adapters=["all"],
        report_root=report_root,
        write_report=True,
    )

    run_dir = Path(summary["report_dir"])
    assert summary["schema_version"] == "memory-os.rh31_summary.v0"
    assert summary["status"] in {"pass", "warning"}
    assert summary["adapter_count"] == 6
    assert summary["boundary_true_count"] == 0
    assert summary["forbidden_field_count"] == 0
    assert (run_dir / "summary.json").exists()
    assert (run_dir / "scores.ndjson").exists()
    assert (run_dir / "failure_cases.ndjson").exists()
    assert (run_dir / "source_distribution.json").exists()
    assert (run_dir / "scorecard.md").exists()
    assert not (tmp_path / "memory-os" / "events").exists()
    assert "raw private" not in (run_dir / "summary.json").read_text(encoding="utf-8").lower()


def test_rh31_synthetic_fixtures_are_reviewable_jsonl_and_secret_free():
    from eval.memory_os.data.rh31_synthetic import load_cases, load_corpus, load_expected

    cases = load_cases()
    corpus = load_corpus()
    expected = load_expected()
    rendered = json.dumps(
        {
            "cases": [case.__dict__ for case in cases],
            "corpus": [document.__dict__ for document in corpus],
            "expected": expected,
        },
        ensure_ascii=False,
        sort_keys=True,
    )

    assert len(cases) >= 6
    assert len(corpus) >= 5
    assert set(expected) == {case.case_id for case in cases}
    assert "api_key" not in rendered.lower()
    assert "password" not in rendered.lower()
    assert "cookie" not in rendered.lower()


def test_rh31_synthetic_candidate_fixture_populates_candidate_queue():
    from eval.memory_os.data.rh31_synthetic import load_corpus
    from eval.memory_os.runner.fixture_store import synthetic_store
    from plugins.memory.memory_os.crystallized import read_candidate_queue

    with synthetic_store(load_corpus()) as store:
        candidates = read_candidate_queue(store.roots)

    assert len(candidates) == 1
    assert candidates[0].candidate_id == "cand_rh31_003"
    assert "不是已经批准的长期记忆" in candidates[0].body
    assert "crystallized candidates" not in candidates[0].body.lower()


def test_rh31_first_six_adapters_are_deterministic_and_report_metric_scope(tmp_path):
    from eval.memory_os.runner.run import run_rh31_eval

    summary = run_rh31_eval(
        fixture="synthetic",
        adapters=["all"],
        report_root=tmp_path / "eval" / "reports",
        write_report=False,
    )

    names = [adapter["name"] for adapter in summary["adapters"]]
    assert names == [
        "grep",
        "memory_os_fts",
        "context_projection",
        "low_clue_candidates",
        "memory_sources_replay",
        "diagnostic_grounding",
    ]
    assert {score["metric_scope"] for score in summary["scores"]} <= {"context", "performance", "answer"}
    assert any(score["metric_scope"] == "context" for score in summary["scores"])
    assert all(score["live_behavior_changed"] is False for score in summary["scores"])


def test_rh31_context_projection_candidate_boundary_uses_review_candidate_section(tmp_path):
    from eval.memory_os.runner.run import run_rh31_eval

    summary = run_rh31_eval(
        fixture="synthetic",
        adapters=["context_projection"],
        report_root=tmp_path / "eval" / "reports",
        write_report=False,
    )
    score = next(item for item in summary["scores"] if item["case_id"] == "candidate_boundary_001")

    assert score["status"] == "pass"
    assert score["actual_route"] == "candidate_review"
    assert "Crystallized Review Candidates" in score["actual_headings"]


def test_rh31_memory_sources_replay_exercises_every_case_before_scoring(tmp_path):
    from eval.memory_os.data.rh31_synthetic import load_cases
    from eval.memory_os.runner.run import run_rh31_eval

    cases = load_cases()
    summary = run_rh31_eval(
        fixture="synthetic",
        adapters=["memory_sources_replay"],
        report_root=tmp_path / "eval" / "reports",
        write_report=False,
    )

    assert summary["adapter_count"] == 1
    assert summary["case_count"] == len(cases)
    assert summary["score_count"] == len(cases)
    for score in summary["scores"]:
        details = score["details"]
        assert details["replayed_case_count"] == len(cases)
        assert details["record_count"] == len(cases)
        assert score["status"] == "pass"


def test_rh31_report_retention_dry_run_keeps_latest_and_never_touches_canonical(tmp_path):
    from eval.memory_os.runner.retention import build_report_retention_plan

    reports_root = tmp_path / "eval" / "reports" / "memory-os-rh31"
    canonical = tmp_path / "memory-os" / "events"
    canonical.mkdir(parents=True)
    for index in range(5):
        run_dir = reports_root / f"rh31_20260525T010{index}00Z"
        run_dir.mkdir(parents=True)
        (run_dir / "summary.json").write_text(json.dumps({"index": index}), encoding="utf-8")
    plan = build_report_retention_plan(reports_root, keep_latest=2, retention_days=0)

    assert [Path(item["path"]).name for item in plan["would_archive_or_prune"]] == [
        "rh31_20260525T010200Z",
        "rh31_20260525T010100Z",
        "rh31_20260525T010000Z",
    ]
    assert plan["canonical_paths_touched"] == []
    assert canonical.exists()


def test_provider_cli_exposes_rh31_eval_run_and_summary(tmp_path, monkeypatch, capsys):
    parser = argparse.ArgumentParser()
    register_cli(parser)
    run_args = parser.parse_args(
        [
            "eval",
            "rh31",
            "run",
            "--fixture",
            "synthetic",
            "--adapter",
            "grep",
            "--report-root",
            str(tmp_path / "eval" / "reports"),
        ]
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    assert memory_os_command(run_args) == 0
    run_output = json.loads(capsys.readouterr().out)
    assert run_output["schema_version"] == "memory-os.rh31_summary.v0"
    assert run_output["adapters"][0]["name"] == "grep"

    summary_args = parser.parse_args(
        [
            "eval",
            "rh31",
            "summary",
            "--report-root",
            str(tmp_path / "eval" / "reports"),
        ]
    )
    assert memory_os_command(summary_args) == 0
    summary_output = json.loads(capsys.readouterr().out)
    assert summary_output["schema_version"] == "memory-os.rh31_summary.v0"


def _store(tmp_path: Path) -> MemoryOSStore:
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path))
    store.initialize()
    return store
