import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "memory_os_right_brain_expression_outcome.py"
    spec = importlib.util.spec_from_file_location("memory_os_right_brain_expression_outcome", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _write_job(home: Path, *, job_id: str = "job-rb") -> None:
    cron = home / "cron"
    cron.mkdir(parents=True)
    (cron / "jobs.json").write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "id": job_id,
                        "name": "memory-os-right-brain-expression",
                        "deliver": "origin",
                        "script": "memory_os_right_brain_expression.py",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_outcome_scanner_is_inert_after_retirement_marker(tmp_path):
    module = _load_module()
    home = tmp_path / "home"
    marker = home / "memory-os" / "system" / "legacy_right_brain_retirement.json"
    marker.parent.mkdir(parents=True)
    marker.write_text("{not-json\n", encoding="utf-8")

    report = module.scan_outcomes(
        hermes_home=home,
        profile="main",
        job_name="memory-os-right-brain-expression",
        apply=True,
    )

    assert report["status"] == "retired"
    assert report["written_outcome_count"] == 0
    assert not (home / "system-modules" / "right_brain_expression_adapter").exists()


def test_outcome_scanner_records_bounded_cron_expression_once(tmp_path):
    module = _load_module()
    home = tmp_path / "home"
    _write_job(home)
    adapter_root = home / "system-modules" / "right_brain_expression_adapter"
    adapter_root.mkdir(parents=True)
    request_time = datetime.now(timezone.utc) - timedelta(minutes=1)
    (adapter_root / "requests.jsonl").write_text(
        json.dumps(
            {
                "schema_version": "memory-os.right_brain_expression_adapter_request.v0",
                "request_id": "rbexpr_001",
                "created_at": request_time.isoformat(),
                "policy_id": "rbpol_001",
                "policy_version": 2,
                "raw_body_included": False,
                "actual_send": False,
                "actual_execute": False,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    output_dir = home / "cron" / "output" / "job-rb"
    output_dir.mkdir(parents=True)
    (output_dir / "2026-05-26.md").write_text(
        "Cronjob Response: memory-os-right-brain-expression\n"
        "(job_id: job-rb)\n"
        "-------------\n\n"
        "今天这边很安静，我就轻轻在场。\n"
        "你如果刚好路过，我也在。\n\n"
        'To stop or manage this job, send me a new message (e.g. "stop reminder memory-os-right-brain-expression").\n',
        encoding="utf-8",
    )

    first = module.scan_outcomes(hermes_home=home, profile="main", job_name="memory-os-right-brain-expression", apply=True)
    second = module.scan_outcomes(hermes_home=home, profile="main", job_name="memory-os-right-brain-expression", apply=True)

    assert first["status"] == "ok"
    assert first["new_outcome_count"] == 1
    assert first["written_outcome_count"] == 1
    assert second["new_outcome_count"] == 0
    records = [
        json.loads(line)
        for line in (adapter_root / "outcomes.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(records) == 1
    outcome = records[0]
    assert outcome["request_id"] == "rbexpr_001"
    assert outcome["policy_version"] == 2
    assert outcome["delivery_channel"] == "origin"
    assert outcome["silent"] is False
    assert "今天这边很安静" in outcome["outcome_preview"]
    assert "Cronjob Response" not in outcome["outcome_preview"]
    assert "To stop or manage" not in outcome["outcome_preview"]
    assert outcome["raw_body_included"] is False
    assert outcome["actual_send"] is False
    assert outcome["actual_execute"] is False


def test_outcome_scanner_handles_silent_output(tmp_path):
    module = _load_module()
    home = tmp_path / "home"
    _write_job(home)
    output_dir = home / "cron" / "output" / "job-rb"
    output_dir.mkdir(parents=True)
    (output_dir / "silent.md").write_text("[SILENT]\n", encoding="utf-8")

    report = module.scan_outcomes(hermes_home=home, profile="main", job_name="memory-os-right-brain-expression", apply=True)

    records = [
        json.loads(line)
        for line in (home / "system-modules" / "right_brain_expression_adapter" / "outcomes.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert report["status"] == "ok"
    assert records[-1]["silent"] is True
    assert records[-1]["outcome_preview"] == "[SILENT]"


def test_outcome_scanner_extracts_hermes_cron_markdown_response(tmp_path):
    module = _load_module()
    home = tmp_path / "home"
    _write_job(home)
    output_dir = home / "cron" / "output" / "job-rb"
    output_dir.mkdir(parents=True)
    (output_dir / "markdown.md").write_text(
        "# Cron Job: memory-os-right-brain-expression\n\n"
        "**Job ID:** job-rb\n\n"
        "## Prompt\n\n"
        "[IMPORTANT: delivery wrapper]\n\n"
        "## Script Output\n"
        "```\n"
        "adapter_request_id: rbexpr_001\n"
        "Bounded context summaries:\n"
        "- source_ref: evt_1\n"
        "```\n\n"
        "## Response\n\n"
        "今天这边很安静，我就轻轻在场。\n"
        "你如果刚好路过，我也在。\n",
        encoding="utf-8",
    )

    report = module.scan_outcomes(hermes_home=home, profile="main", job_name="memory-os-right-brain-expression", apply=True)
    records = [
        json.loads(line)
        for line in (home / "system-modules" / "right_brain_expression_adapter" / "outcomes.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]

    assert report["status"] == "ok"
    assert report["internal_marker_count"] == 0
    assert records[-1]["internal_marker_count"] == 0
    assert records[-1]["outcome_preview"] == "今天这边很安静，我就轻轻在场。\n你如果刚好路过，我也在。"


def test_outcome_cli_prints_report_and_does_not_write_without_apply(tmp_path, capsys, monkeypatch):
    module = _load_module()
    home = tmp_path / "home"
    _write_job(home)
    output_dir = home / "cron" / "output" / "job-rb"
    output_dir.mkdir(parents=True)
    (output_dir / "dry-run.md").write_text("一条很短的右脑表达。\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))
    old_argv = sys.argv
    try:
        sys.argv = ["memory_os_right_brain_expression_outcome.py"]
        assert module.main() == 0
    finally:
        sys.argv = old_argv

    report = json.loads(capsys.readouterr().out)
    assert report["new_outcome_count"] == 1
    assert report["written_outcome_count"] == 0
    assert not (home / "system-modules" / "right_brain_expression_adapter" / "outcomes.jsonl").exists()
