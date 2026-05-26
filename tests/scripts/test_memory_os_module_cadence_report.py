import importlib.util
import json
import sys
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "memory_os_module_cadence_report.py"
    spec = importlib.util.spec_from_file_location("memory_os_module_cadence_report", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _write_jobs(home: Path) -> None:
    cron = home / "cron"
    cron.mkdir(parents=True)
    (cron / "jobs.json").write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "id": "digest-job",
                        "name": "memory-os-owner-review-digest",
                        "schedule": "0 8 * * *",
                        "deliver": "origin",
                        "enabled": True,
                    },
                    {
                        "id": "right-brain-job",
                        "name": "memory-os-right-brain-expression",
                        "schedule": "30 4 * * 0",
                        "deliver": "origin",
                        "enabled": True,
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    digest_output = cron / "output" / "digest-job"
    digest_output.mkdir(parents=True)
    (digest_output / "2026-05-26_08-00-00.md").write_text("digest", encoding="utf-8")


def test_module_cadence_report_is_report_only_and_detects_split_candidates(tmp_path):
    module = _load_module()
    home = tmp_path / "home"
    _write_jobs(home)
    loop_root = home / "system-modules" / "cognitive_loop"
    loop_root.mkdir(parents=True)
    (loop_root / "reports.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "cycle_id": "cloop_1",
                        "status": "ok",
                        "finished_at": "2026-05-26T01:00:00+00:00",
                        "steps": [
                            {
                                "step": "self_evolution",
                                "status": "ok",
                                "result": {"status": "ok", "proposal_created": True},
                            },
                            {
                                "step": "evidence_scoring",
                                "status": "error",
                                "error": "score failure",
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "cycle_id": "cloop_2",
                        "status": "warning",
                        "finished_at": "2026-05-26T02:00:00+00:00",
                        "steps": [
                            {
                                "step": "self_evolution",
                                "status": "ok",
                                "result": {
                                    "status": "ok",
                                    "novelty_skipped": True,
                                    "reason": "duplicate_unresolved_proposal",
                                },
                            },
                            {
                                "step": "digest_consolidation",
                                "status": "ok",
                                "result": {"status": "ok", "daily_written": True},
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    evidence_root = home / "system-modules" / "evidence_scoring"
    evidence_root.mkdir(parents=True)
    (evidence_root / "runs.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "schema_version": "hermes.evidence_scoring_result.v0",
                        "status": "ok",
                        "skipped": True,
                        "cadence_skipped": True,
                        "reason": "unchanged_input_fingerprint",
                    },
                    ensure_ascii=False,
                )
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    report = module.build_cadence_report(hermes_home=home, profile="main", apply=True)

    assert report["schema_version"] == "memory-os.module_cadence_report.v0"
    assert report["status"] == "warning"
    assert report["cron_job_count"] == 2
    assert report["latest_cognitive_loop_cycle_id"] == "cloop_2"
    assert report["expected_hermes_cron_missing_count"] == 0
    assert report["split_recommended_count"] > 0
    assert report["boundary"] == {
        "actual_send": False,
        "actual_execute": False,
        "actual_identity_write": False,
        "actual_unapproved_crystallized_approval": False,
        "cron_modified": False,
    }
    records = [
        json.loads(line)
        for line in (home / "system-modules" / "module_cadence" / "reports.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(records) == 1
    by_module = {item["module"]: item for item in records[0]["modules"]}
    assert by_module["owner_review_digest"]["current_cron_job_count"] == 1
    assert by_module["owner_review_digest"]["cadence_counters"]["generated_count"] == 1
    assert by_module["cognitive_loop"]["cadence_counters"]["generated_count"] == 2
    assert by_module["right_brain_expression_adapter"]["current_cron_job_count"] == 1
    assert by_module["self_evolution"]["production_split_recommended"] is True
    assert by_module["self_evolution"]["cadence_counters"] == {
        "run_count": 2,
        "generated_count": 1,
        "skipped_count": 1,
        "error_count": 0,
        "duplicate_count": 1,
        "last_run_at": "2026-05-26T02:00:00+00:00",
        "last_status": "ok",
    }
    assert by_module["digest_consolidation"]["cadence_counters"]["generated_count"] == 1
    assert by_module["evidence_scoring"]["cadence_counters"]["error_count"] == 1
    assert by_module["evidence_scoring"]["cadence_counters"]["skipped_count"] == 1
    assert report["generated_count"] >= 2
    assert report["skipped_count"] >= 1
    assert report["error_count"] >= 1
    assert report["duplicate_count"] >= 1


def test_module_cadence_report_warns_when_expected_cron_is_missing(tmp_path):
    module = _load_module()
    home = tmp_path / "home"
    (home / "cron").mkdir(parents=True)
    (home / "cron" / "jobs.json").write_text('{"jobs":[]}', encoding="utf-8")

    report = module.build_cadence_report(hermes_home=home, profile="main")

    assert report["status"] == "warning"
    assert report["expected_hermes_cron_missing_count"] == 2
    assert {
        finding["module"]
        for finding in report["findings"]
        if finding["code"] == "expected_hermes_cron_missing"
    } == {"owner_review_digest", "right_brain_expression_adapter"}


def test_module_cadence_cli_summary_does_not_write_without_apply(tmp_path, capsys, monkeypatch):
    module = _load_module()
    home = tmp_path / "home"
    _write_jobs(home)
    monkeypatch.setenv("HERMES_HOME", str(home))
    old_argv = sys.argv
    try:
        sys.argv = ["memory_os_module_cadence_report.py", "--format", "summary"]
        assert module.main() == 0
    finally:
        sys.argv = old_argv

    summary = capsys.readouterr().out
    assert "status=warning" in summary
    assert "cron_modified=False" in summary
    assert not (home / "system-modules" / "module_cadence" / "reports.jsonl").exists()
