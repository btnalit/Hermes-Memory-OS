from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "memory_os_owner_cron_onboarding.py"
    spec = importlib.util.spec_from_file_location("memory_os_owner_cron_onboarding", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _fake_hermes(tmp_path: Path) -> Path:
    script = tmp_path / "fake_hermes.py"
    script.write_text(
        """
import json
import os
import pathlib
import sys

args = sys.argv[1:]
home = pathlib.Path(os.environ.get("HERMES_HOME", "."))

if args[:3] == ["cron", "create", "--help"]:
    print("usage: hermes cron create [--name NAME] [--deliver DELIVER] [--script SCRIPT] [--no-agent] schedule prompt")
    raise SystemExit(0)

if args[:3] == ["memory-os-agent-os", "review", "render-digest"]:
    print("Memory-OS owner review digest\\nA1 Human readable proposal")
    raise SystemExit(0)

if args[:2] == ["cron", "create"]:
    def value(flag):
        return args[args.index(flag) + 1] if flag in args else ""
    jobs_path = home / "cron" / "jobs.json"
    jobs_path.parent.mkdir(parents=True, exist_ok=True)
    if jobs_path.exists():
        loaded = json.loads(jobs_path.read_text(encoding="utf-8"))
    else:
        loaded = {"jobs": []}
    jobs = loaded.get("jobs", [])
    job_name = value("--name")
    job = {
        "id": "job_" + job_name.replace("-", "_"),
        "name": job_name,
        "enabled": True,
        "deliver": value("--deliver"),
        "script": value("--script"),
        "no_agent": "--no-agent" in args,
        "prompt": args[-1],
    }
    jobs.append(job)
    jobs_path.write_text(json.dumps({"jobs": jobs}), encoding="utf-8")
    print("created", job["id"])
    raise SystemExit(0)

if args[:2] == ["cron", "edit"]:
    def value(flag):
        return args[args.index(flag) + 1] if flag in args else None
    jobs_path = home / "cron" / "jobs.json"
    loaded = json.loads(jobs_path.read_text(encoding="utf-8"))
    jobs = loaded.get("jobs", [])
    job_id = args[-1]
    for job in jobs:
        if job.get("id") == job_id:
            if value("--schedule") is not None:
                job["schedule_display"] = value("--schedule")
                job["schedule"] = {"kind": "cron", "expr": value("--schedule")}
            if value("--prompt") is not None:
                job["prompt"] = value("--prompt")
            if value("--name") is not None:
                job["name"] = value("--name")
            if value("--deliver") is not None:
                job["deliver"] = value("--deliver")
            if value("--script") is not None:
                job["script"] = value("--script")
            if "--no-agent" in args:
                job["no_agent"] = True
            if "--agent" in args:
                job["no_agent"] = False
            jobs_path.write_text(json.dumps({"jobs": jobs}), encoding="utf-8")
            print("updated", job_id)
            raise SystemExit(0)
    print("missing job", job_id, file=sys.stderr)
    raise SystemExit(2)

if args[:2] == ["cron", "pause"]:
    jobs_path = home / "cron" / "jobs.json"
    loaded = json.loads(jobs_path.read_text(encoding="utf-8"))
    jobs = loaded.get("jobs", [])
    job_id = args[2]
    for job in jobs:
        if job.get("id") == job_id:
            job["enabled"] = False
            jobs_path.write_text(json.dumps({"jobs": jobs}), encoding="utf-8")
            print("paused", job_id)
            raise SystemExit(0)
    print("missing job", job_id, file=sys.stderr)
    raise SystemExit(2)

print("unexpected command", args, file=sys.stderr)
raise SystemExit(2)
""".lstrip(),
        encoding="utf-8",
    )
    if os.name == "nt":
        launcher = tmp_path / "hermes.cmd"
        launcher.write_text(f'@"{sys.executable}" "{script}" %*\n', encoding="utf-8")
    else:
        launcher = tmp_path / "hermes"
        launcher.write_text(f'#! /bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        launcher.chmod(0o755)
    return launcher


def _home_with_helpers(
    tmp_path: Path,
    *,
    platforms: dict[str, list[dict[str, str]]],
    omit_helpers: set[str] | None = None,
) -> Path:
    home = tmp_path / "home"
    scripts = home / "scripts"
    scripts.mkdir(parents=True)
    omitted = omit_helpers or set()
    for helper in (
        "memory_os_owner_review_digest.py",
        "memory_os_cron_owner_review_digest_gate.py",
        "memory_os_right_brain_expression.py",
        "memory_os_cron_right_brain_expression_gate.py",
        "memory_os_module_cadence_report_cron.py",
        "memory_os_cron_module_cadence_report_gate.py",
        "memory_os_right_brain_expression_outcome_cron.py",
        "memory_os_cron_right_brain_expression_outcome_gate.py",
        "memory_os_proposal_followups_ops_gate.py",
        "memory_os_cron_proposal_followups_opsgate_gate.py",
        "memory_os_expression_feedback_prompt.py",
        "memory_os_cron_expression_feedback_request_gate.py",
        "memory_os_memory_sources_feedback_prompt.py",
        "memory_os_cron_memory_sources_feedback_request_gate.py",
        "memory_os_candidate_aggregation_lane.py",
        "memory_os_cron_candidate_aggregation_gate.py",
        "memory_os_fact_judge_lane.py",
        "memory_os_cron_fact_judge_gate.py",
        "memory_os_index_sync.py",
        "memory_os_cron_index_sync_gate.py",
        "cleanup_expired_working.py",
        "memory_os_cron_working_cleanup_gate.py",
        "memory_os_l3_probe_helper.py",
        "memory_os_cron_l3_probe_verification_gate.py",
    ):
        if helper in omitted:
            continue
        scripts.joinpath(helper).write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    home.joinpath("channel_directory.json").write_text(
        json.dumps({"platforms": platforms}, ensure_ascii=False),
        encoding="utf-8",
    )
    return home


def test_discovers_configured_owner_channel_without_telegram_default(tmp_path):
    module = _load_module()
    home = _home_with_helpers(
        tmp_path,
        platforms={"telegram": [], "discord": [{"id": "room-1", "type": "dm", "name": "owner"}]},
    )

    channels = module.discover_owner_channels(home)

    assert channels[0]["deliver"] == "discord"
    assert channels[0]["source"] == "channel_directory"
    assert all(channel["deliver"] != "telegram" for channel in channels)


def test_onboarding_dry_run_selects_detected_channel_and_does_not_create_jobs(tmp_path):
    module = _load_module()
    home = _home_with_helpers(
        tmp_path,
        platforms={"telegram": [], "discord": [{"id": "room-1", "type": "dm", "name": "owner"}]},
    )
    args = module.build_parser().parse_args(
        [
            "--hermes-home",
            str(home),
            "--hermes-bin",
            str(_fake_hermes(tmp_path)),
            "--owner-review-deliver",
            "auto",
            "--right-brain-deliver",
            "origin",
        ]
    )

    report = module.run_onboarding(args)

    assert report["status"] == "dry_run"
    assert report["selected_owner_review_deliver"] == "discord"
    assert report["selected_owner_review_channel"] == "discord"
    assert report["selected_right_brain_deliver"] == "origin"
    assert report["apply_requested"] is False
    assert report["cron_profile"] == "active-closure"
    assert len(report["operational_cron_jobs"]) == 3
    assert {job["name"] for job in report["operational_cron_jobs"]} == {
        "memory-os-owner-review-digest",
        "memory-os-proposal-followups-opsgate",
        "memory-os-index-sync",
    }
    index_sync = [job for job in report["operational_cron_jobs"] if job["name"] == "memory-os-index-sync"][0]
    assert index_sync["script"] == "memory_os_cron_index_sync_gate.py"
    assert index_sync["raw_script"] == "memory_os_index_sync.py"
    assert index_sync["deliver"] == "local"
    assert index_sync["no_agent"] is True
    for job in report["operational_cron_jobs"]:
        assert home.joinpath("scripts", job["script"]).is_file(), job["script"]
    assert not home.joinpath("cron", "jobs.json").exists()


def test_onboarding_fail_closed_when_active_closure_wrapper_script_missing(tmp_path):
    module = _load_module()
    home = _home_with_helpers(
        tmp_path,
        platforms={"telegram": [{"id": "owner", "type": "dm", "name": "owner"}]},
        omit_helpers={"memory_os_cron_index_sync_gate.py"},
    )
    args = module.build_parser().parse_args(
        [
            "--hermes-home",
            str(home),
            "--hermes-bin",
            str(_fake_hermes(tmp_path)),
            "--owner-review-deliver",
            "auto",
            "--right-brain-deliver",
            "origin",
        ]
    )

    report = module.run_onboarding(args)

    assert report["status"] == "blocked"
    assert any(item["code"] == "memory-os-index-sync_script_missing" for item in report["findings"])
    assert not report["operational_cron_jobs"]


def test_onboarding_apply_requires_owner_approval(tmp_path):
    module = _load_module()
    home = _home_with_helpers(
        tmp_path,
        platforms={"telegram": [{"id": "6808688675", "type": "dm", "name": "owner"}]},
    )
    args = module.build_parser().parse_args(
        [
            "--hermes-home",
            str(home),
            "--hermes-bin",
            str(_fake_hermes(tmp_path)),
            "--owner-review-deliver",
            "auto",
            "--right-brain-deliver",
            "origin",
            "--apply",
        ]
    )

    report = module.run_onboarding(args)

    assert report["status"] == "blocked"
    assert any(item["code"] == "owner_approval_required_for_apply" for item in report["findings"])
    assert not home.joinpath("cron", "jobs.json").exists()


def test_onboarding_apply_creates_owner_review_and_right_brain_cron_jobs(tmp_path):
    module = _load_module()
    home = _home_with_helpers(
        tmp_path,
        platforms={"telegram": [{"id": "6808688675", "type": "dm", "name": "owner"}]},
    )
    args = module.build_parser().parse_args(
        [
            "--hermes-home",
            str(home),
            "--hermes-bin",
            str(_fake_hermes(tmp_path)),
            "--owner-review-deliver",
            "auto",
            "--right-brain-deliver",
            "origin",
            "--cron-profile",
            "full",
            "--apply",
            "--owner-approved",
        ]
    )

    report = module.run_onboarding(args)

    assert report["status"] == "applied"
    assert report["selected_owner_review_deliver"] == "telegram"
    assert report["selected_owner_review_channel"] == "telegram"
    assert report["cron_profile"] == "full"
    assert len(report["operational_cron_jobs"]) == 12
    jobs = json.loads(home.joinpath("cron", "jobs.json").read_text(encoding="utf-8"))["jobs"]
    by_name = {job["name"]: job for job in jobs}
    assert set(by_name) == {
        "memory-os-owner-review-digest",
        "memory-os-right-brain-expression",
        "memory-os-module-cadence-report",
        "memory-os-right-brain-expression-outcome",
        "memory-os-proposal-followups-opsgate",
        "memory-os-expression-feedback-request",
        "memory-os-memory-sources-feedback-request",
        "memory-os-candidate-aggregation",
        "memory-os-fact-judge",
        "memory-os-index-sync",
        "memory-os-working-cleanup",
        "memory-os-l3-probe-verification",
    }
    assert by_name["memory-os-owner-review-digest"]["deliver"] == "telegram"
    assert by_name["memory-os-owner-review-digest"]["script"] == "memory_os_cron_owner_review_digest_gate.py"
    assert by_name["memory-os-owner-review-digest"]["no_agent"] is False
    assert by_name["memory-os-right-brain-expression"]["deliver"] == "origin"
    assert by_name["memory-os-right-brain-expression"]["script"] == "memory_os_cron_right_brain_expression_gate.py"
    assert by_name["memory-os-right-brain-expression"]["no_agent"] is False
    assert by_name["memory-os-module-cadence-report"]["deliver"] == "local"
    assert by_name["memory-os-module-cadence-report"]["script"] == "memory_os_cron_module_cadence_report_gate.py"
    assert by_name["memory-os-module-cadence-report"]["no_agent"] is True
    assert by_name["memory-os-right-brain-expression-outcome"]["deliver"] == "local"
    assert by_name["memory-os-right-brain-expression-outcome"]["script"] == "memory_os_cron_right_brain_expression_outcome_gate.py"
    assert by_name["memory-os-right-brain-expression-outcome"]["no_agent"] is True
    assert by_name["memory-os-proposal-followups-opsgate"]["deliver"] == "local"
    assert by_name["memory-os-proposal-followups-opsgate"]["script"] == "memory_os_cron_proposal_followups_opsgate_gate.py"
    assert by_name["memory-os-proposal-followups-opsgate"]["no_agent"] is True
    assert by_name["memory-os-expression-feedback-request"]["deliver"] == "telegram"
    assert by_name["memory-os-expression-feedback-request"]["script"] == "memory_os_cron_expression_feedback_request_gate.py"
    assert by_name["memory-os-expression-feedback-request"]["no_agent"] is False
    assert by_name["memory-os-memory-sources-feedback-request"]["deliver"] == "telegram"
    assert by_name["memory-os-memory-sources-feedback-request"]["script"] == "memory_os_cron_memory_sources_feedback_request_gate.py"
    assert by_name["memory-os-memory-sources-feedback-request"]["no_agent"] is False
    assert (home / "scripts" / "memory_os_execution_gate_runner.py").is_file()
    assert (home / "scripts" / "memory_os_cron_module_cadence_report_gate.py").is_file()
    memory_sources_prompt = by_name["memory-os-memory-sources-feedback-request"]["prompt"]
    assert "不要写 Cron Run Report" in memory_sources_prompt
    assert "只输出 OWNER_MESSAGE_BEGIN 和 OWNER_MESSAGE_END 之间的内容" in memory_sources_prompt
    config = json.loads(home.joinpath("memory-os", "config.json").read_text(encoding="utf-8"))
    assert config["owner_review"]["recurring_delivery_enabled"] is True
    assert config["right_brain_expression"]["recurring_delivery_enabled"] is True


def test_onboarding_migrates_existing_memory_os_raw_helper_to_gate_wrapper(tmp_path):
    module = _load_module()
    home = _home_with_helpers(
        tmp_path,
        platforms={"telegram": [{"id": "6808688675", "type": "dm", "name": "owner"}]},
    )
    jobs_path = home / "cron" / "jobs.json"
    jobs_path.parent.mkdir(parents=True)
    jobs_path.write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "id": "job_memory_os_module_cadence_report",
                        "name": "memory-os-module-cadence-report",
                        "enabled": True,
                        "deliver": "local",
                        "script": "memory_os_module_cadence_report_cron.py",
                        "no_agent": True,
                        "prompt": "",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    args = module.build_parser().parse_args(
        [
            "--hermes-home",
            str(home),
            "--hermes-bin",
            str(_fake_hermes(tmp_path)),
            "--owner-review-deliver",
            "auto",
            "--right-brain-deliver",
            "origin",
            "--cron-profile",
            "full",
            "--apply",
            "--owner-approved",
        ]
    )

    report = module.run_onboarding(args)

    jobs = json.loads(jobs_path.read_text(encoding="utf-8"))["jobs"]
    cadence = next(job for job in jobs if job["name"] == "memory-os-module-cadence-report")
    assert report["status"] in {"applied", "updated"}
    assert cadence["script"] == "memory_os_cron_module_cadence_report_gate.py"
    assert any(
        item["name"] == "memory-os-module-cadence-report" and item["status"] == "updated"
        for item in report["operational_cron_jobs"]
    )


def test_active_closure_onboarding_pauses_known_optional_memory_os_jobs(tmp_path):
    module = _load_module()
    home = _home_with_helpers(
        tmp_path,
        platforms={"telegram": [{"id": "owner", "type": "dm", "name": "owner"}]},
    )
    jobs_path = home / "cron" / "jobs.json"
    jobs_path.parent.mkdir(parents=True)
    jobs_path.write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "id": "job_memory_sources_feedback",
                        "name": "memory-os-memory-sources-feedback-request",
                        "enabled": True,
                        "deliver": "telegram",
                        "script": "memory_os_cron_memory_sources_feedback_request_gate.py",
                        "no_agent": False,
                        "prompt": "",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    args = module.build_parser().parse_args(
        [
            "--hermes-home",
            str(home),
            "--hermes-bin",
            str(_fake_hermes(tmp_path)),
            "--owner-review-deliver",
            "auto",
            "--right-brain-deliver",
            "origin",
            "--apply",
            "--owner-approved",
        ]
    )

    report = module.run_onboarding(args)

    assert report["status"] in {"already_configured", "updated", "applied"}
    assert report["cron_profile"] == "active-closure"
    assert report["paused_optional_cron_jobs"] == [
        {
            "name": "memory-os-memory-sources-feedback-request",
            "job_id": "job_memory_sources_feedback",
            "registry_key": "memory_sources_feedback_request",
            "script": "memory_os_cron_memory_sources_feedback_request_gate.py",
            "was_enabled": True,
            "status": "paused",
        }
    ]
    jobs = json.loads(jobs_path.read_text(encoding="utf-8"))["jobs"]
    by_name = {job["name"]: job for job in jobs}
    assert by_name["memory-os-owner-review-digest"]["enabled"] is True
    assert by_name["memory-os-proposal-followups-opsgate"]["enabled"] is True
    assert by_name["memory-os-index-sync"]["enabled"] is True
    assert by_name["memory-os-index-sync"]["script"] == "memory_os_cron_index_sync_gate.py"
    assert by_name["memory-os-index-sync"]["no_agent"] is True
    assert by_name["memory-os-memory-sources-feedback-request"]["enabled"] is False


def test_updates_existing_memory_sources_feedback_cron_prompt(tmp_path, monkeypatch):
    module = _load_module()
    home = _home_with_helpers(
        tmp_path,
        platforms={"telegram": [{"id": "owner", "type": "dm", "name": "owner"}]},
    )
    monkeypatch.setenv("HERMES_HOME", str(home))
    jobs_path = home / "cron" / "jobs.json"
    jobs_path.parent.mkdir(parents=True)
    jobs_path.write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "id": "job_memory_sources",
                        "name": "memory-os-memory-sources-feedback-request",
                        "enabled": True,
                        "deliver": "telegram",
                        "script": "memory_os_memory_sources_feedback_prompt.py",
                        "no_agent": False,
                        "prompt": "旧提示：请写报告",
                        "schedule_display": "30 10 * * *",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    args = module.build_parser().parse_args(
        [
            "--hermes-home",
            str(home),
            "--hermes-bin",
            str(_fake_hermes(tmp_path)),
            "--owner-review-deliver",
            "auto",
            "--right-brain-deliver",
            "origin",
            "--cron-profile",
            "full",
            "--apply",
            "--owner-approved",
        ]
    )

    report = module.run_onboarding(args)

    assert report["status"] == "applied"
    memory_sources_job_report = [
        job for job in report["operational_cron_jobs"] if job["name"] == "memory-os-memory-sources-feedback-request"
    ][0]
    assert memory_sources_job_report["status"] == "updated"
    updated_jobs = json.loads(jobs_path.read_text(encoding="utf-8"))["jobs"]
    updated_job = [job for job in updated_jobs if job["name"] == "memory-os-memory-sources-feedback-request"][0]
    assert "旧提示" not in updated_job["prompt"]
    assert "不要写 Cron Run Report" in updated_job["prompt"]
    assert "只输出 OWNER_MESSAGE_BEGIN 和 OWNER_MESSAGE_END 之间的内容" in updated_job["prompt"]
