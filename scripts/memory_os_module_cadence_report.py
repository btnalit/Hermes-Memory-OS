#!/usr/bin/env python3
"""Report current Memory-OS module cadence without changing schedules.

Hermes owns cron, origin delivery, retry, and profile scheduling. This helper
only reads Hermes cron metadata plus Memory-OS report ledgers and writes bounded
cadence evidence for P1-T.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "memory-os.module_cadence_report.v0"
DEFAULT_PROFILE = "main"

MODULE_TARGETS: tuple[dict[str, Any], ...] = (
    {
        "module": "heartbeat_inner_drive",
        "target_cadence_class": "event_driven_fast",
        "current_runner": "systemd_timer",
        "notes": "heartbeat and inner-drive processing stay fast and local",
    },
    {
        "module": "cognitive_loop",
        "target_cadence_class": "test_host_integration_harness",
        "current_runner": "systemd_timer",
        "notes": "test-host integration harness, not production cadence authority",
    },
    {
        "module": "owner_review_digest",
        "target_cadence_class": "owner_daily",
        "current_runner": "hermes_cron",
        "cron_names": ("memory-os-owner-review-digest",),
        "notes": "owner-facing agenda/digest uses Hermes cron and origin/platform delivery",
    },
    {
        "module": "right_brain_expression_adapter",
        "target_cadence_class": "owner_low_frequency",
        "current_runner": "hermes_cron",
        "cron_names": ("memory-os-right-brain-expression",),
        "notes": "Hermes agent owns wording, silence judgment, and origin delivery",
    },
    {
        "module": "digest_consolidation",
        "target_cadence_class": "daily_weekly",
        "current_runner": "cognitive_loop",
        "split_recommended": True,
        "notes": "daily/weekly digest should not permanently run every integration cycle",
    },
    {
        "module": "household_digest",
        "target_cadence_class": "daily_or_on_signal",
        "current_runner": "cognitive_loop",
        "split_recommended": True,
        "notes": "bounded context substrate for right-brain and reflection",
    },
    {
        "module": "wandering_mind",
        "target_cadence_class": "owner_low_frequency_or_on_signal",
        "current_runner": "cognitive_loop",
        "split_recommended": True,
        "notes": "formal expression goes through ExpressionDraft/SpeakGate/Hermes cron",
    },
    {
        "module": "expression_draft",
        "target_cadence_class": "on_signal",
        "current_runner": "cognitive_loop",
        "split_recommended": True,
        "notes": "draft generation should follow expression source signals",
    },
    {
        "module": "speak_gate",
        "target_cadence_class": "on_signal",
        "current_runner": "cognitive_loop",
        "split_recommended": True,
        "notes": "gate every non-silent draft; no standalone transport ownership",
    },
    {
        "module": "evidence_scoring",
        "target_cadence_class": "daily_or_on_new_signal",
        "current_runner": "cognitive_loop",
        "split_recommended": True,
        "notes": "feature scoring should skip unchanged inputs in production cadence",
    },
    {
        "module": "self_evolution",
        "target_cadence_class": "daily_weekly_or_on_new_signal",
        "current_runner": "cognitive_loop",
        "split_recommended": True,
        "notes": "proposal generation needs novelty/idempotency and lower frequency",
    },
    {
        "module": "governance_feedback",
        "target_cadence_class": "daily_or_on_new_signal",
        "current_runner": "cognitive_loop",
        "split_recommended": True,
        "notes": "feedback bridge should run when new bounded signals exist",
    },
    {
        "module": "deep_reflection",
        "target_cadence_class": "daily_weekly_or_min_signal",
        "current_runner": "cognitive_loop",
        "split_recommended": True,
        "notes": "slow reflection should not be treated as every-cycle plumbing",
    },
    {
        "module": "ops_gate",
        "target_cadence_class": "on_approved_proposal",
        "current_runner": "cognitive_loop",
        "split_recommended": True,
        "notes": "OpsGate should run when approved proposals need report-only review",
    },
    {
        "module": "left_brain_pipeline_check",
        "target_cadence_class": "monitor_poll_or_daily",
        "current_runner": "cognitive_loop",
        "split_recommended": True,
        "notes": "checker is report-only and should be cheap/skip-aware",
    },
    {
        "module": "session_mirror",
        "target_cadence_class": "on_demand_or_operator_approved_apply",
        "current_runner": "manual_or_monitor",
        "notes": "pending sessions stay dry-run until owner approves apply",
    },
    {
        "module": "rh31_eval",
        "target_cadence_class": "on_demand_or_monitor_poll",
        "current_runner": "manual_or_monitor",
        "notes": "scorecard remains measurement until mapped to live evidence",
    },
    {
        "module": "metadata_retention",
        "target_cadence_class": "on_demand_dry_run",
        "current_runner": "manual_or_monitor",
        "notes": "physical apply remains gated; canonical memory untouched",
    },
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hermes-home", default=os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
    parser.add_argument("--profile", default=os.environ.get("HERMES_PROFILE", DEFAULT_PROFILE))
    parser.add_argument("--apply", action="store_true", help="Append the report to system-modules/module_cadence/reports.jsonl.")
    parser.add_argument("--format", choices=["json", "summary"], default="json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = build_cadence_report(
        hermes_home=Path(args.hermes_home).expanduser().resolve(),
        profile=args.profile,
        apply=bool(args.apply),
    )
    if args.format == "summary":
        print(render_summary(report))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] in {"ok", "warning"} else 2


def build_cadence_report(*, hermes_home: Path, profile: str = DEFAULT_PROFILE, apply: bool = False) -> dict[str, Any]:
    created_at = datetime.now(timezone.utc).isoformat()
    cron_jobs = _read_cron_jobs(hermes_home)
    cron_by_name: dict[str, list[dict[str, Any]]] = {}
    for job in cron_jobs:
        cron_by_name.setdefault(str(job.get("name") or ""), []).append(job)

    cognitive_reports = _read_jsonl(hermes_home / "system-modules" / "cognitive_loop" / "reports.jsonl")
    latest_cycle = cognitive_reports[-1] if cognitive_reports and isinstance(cognitive_reports[-1], dict) else {}
    observed_counters = _observed_module_counters(hermes_home, cognitive_reports)
    modules: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []

    for target in MODULE_TARGETS:
        module = str(target["module"])
        cron_matches = _matching_jobs(cron_by_name, target.get("cron_names", ()))
        if target.get("current_runner") == "hermes_cron":
            _merge_artifact_counter(
                observed_counters,
                module,
                generated_count=_cron_output_count(hermes_home, cron_matches),
            )
        module_counters = observed_counters.get(module, _empty_counters())
        module_local_skip_gate_visible = _module_local_skip_gate_visible(module_counters)
        split_recommended = bool(target.get("split_recommended"))
        finding_codes: list[str] = []
        if split_recommended and not module_local_skip_gate_visible:
            finding_codes.append("production_cadence_split_pending")
            findings.append(
                {
                    "severity": "warning",
                    "code": "production_cadence_split_pending",
                    "module": module,
                    "current_runner": target.get("current_runner"),
                    "target_cadence_class": target.get("target_cadence_class"),
                }
            )
        if target.get("current_runner") == "hermes_cron" and not cron_matches:
            finding_codes.append("expected_hermes_cron_missing")
            findings.append(
                {
                    "severity": "warning",
                    "code": "expected_hermes_cron_missing",
                    "module": module,
                    "expected_cron_names": list(target.get("cron_names", ())),
                }
            )
        modules.append(
            {
                "module": module,
                "target_cadence_class": target.get("target_cadence_class"),
                "current_runner": target.get("current_runner"),
                "current_cron_job_count": len(cron_matches),
                "current_cron_jobs": [_job_summary(job) for job in cron_matches],
                "integration_harness_member": target.get("current_runner") == "cognitive_loop",
                "production_split_recommended": split_recommended,
                "module_local_skip_gate_visible": module_local_skip_gate_visible,
                "cadence_counters": module_counters,
                "current_window_error_count": _current_window_error_count(module_counters),
                "finding_codes": finding_codes,
                "notes": target.get("notes"),
            }
        )

    aggregate_counters = _aggregate_counters(modules)
    status = "warning" if findings else "ok"
    report_id = "cadence_" + hashlib.sha256(f"{profile}:{created_at}".encode("utf-8")).hexdigest()[:16]
    report = {
        "schema_version": SCHEMA_VERSION,
        "report_id": report_id,
        "created_at": created_at,
        "profile": profile,
        "status": status,
        "apply": apply,
        "module_count": len(modules),
        "cron_job_count": len(cron_jobs),
        "cognitive_loop_report_count": len(cognitive_reports),
        "latest_cognitive_loop_cycle_id": str(latest_cycle.get("cycle_id") or ""),
        "latest_cognitive_loop_status": str(latest_cycle.get("status") or ""),
        "integration_harness_member_count": sum(1 for item in modules if item["integration_harness_member"]),
        "split_recommended_count": sum(1 for item in modules if item["production_split_recommended"]),
        "expected_hermes_cron_missing_count": sum(
            1 for finding in findings if finding["code"] == "expected_hermes_cron_missing"
        ),
        **aggregate_counters,
        "findings": findings,
        "finding_count": len(findings),
        "modules": modules,
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
            "cron_modified": False,
        },
    }
    if apply:
        path = _reports_path(hermes_home)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(report, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        report["report_path"] = str(path)
    else:
        report["report_path"] = str(_reports_path(hermes_home))
    return report


def render_summary(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"status={report.get('status')}",
            f"module_count={report.get('module_count')}",
            f"cron_job_count={report.get('cron_job_count')}",
            f"integration_harness_member_count={report.get('integration_harness_member_count')}",
            f"split_recommended_count={report.get('split_recommended_count')}",
            f"expected_hermes_cron_missing_count={report.get('expected_hermes_cron_missing_count')}",
            f"finding_count={report.get('finding_count')}",
            f"generated_count={report.get('generated_count')}",
            f"skipped_count={report.get('skipped_count')}",
            f"error_count={report.get('error_count')}",
            f"historical_error_count={report.get('historical_error_count')}",
            f"current_window_error_count={report.get('current_window_error_count')}",
            f"duplicate_count={report.get('duplicate_count')}",
            f"actual_send={report.get('boundary', {}).get('actual_send')}",
            f"actual_execute={report.get('boundary', {}).get('actual_execute')}",
            f"cron_modified={report.get('boundary', {}).get('cron_modified')}",
        ]
    )


def _matching_jobs(cron_by_name: dict[str, list[dict[str, Any]]], names: Any) -> list[dict[str, Any]]:
    if not names:
        return []
    return [job for name in names for job in cron_by_name.get(str(name), [])]


def _job_summary(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(job.get("id") or job.get("job_id") or ""),
        "name": str(job.get("name") or ""),
        "schedule": str(job.get("schedule") or job.get("cron") or job.get("rrule") or ""),
        "deliver": str(job.get("deliver") or job.get("delivery") or job.get("target") or ""),
        "enabled": job.get("enabled"),
    }


def _cron_output_count(hermes_home: Path, jobs: list[dict[str, Any]]) -> int:
    total = 0
    output_root = hermes_home / "cron" / "output"
    for job in jobs:
        job_id = str(job.get("id") or job.get("job_id") or "")
        if not job_id:
            continue
        job_root = output_root / job_id
        if job_root.exists():
            total += sum(1 for path in job_root.glob("*") if path.is_file())
    return total


def _read_cron_jobs(hermes_home: Path) -> list[dict[str, Any]]:
    path = hermes_home / "cron" / "jobs.json"
    if not path.exists():
        return []
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    jobs = loaded.get("jobs", []) if isinstance(loaded, dict) else loaded
    return [dict(item) for item in jobs if isinstance(item, dict)] if isinstance(jobs, list) else []


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            records.append(parsed)
    return records


def _reports_path(hermes_home: Path) -> Path:
    return hermes_home / "system-modules" / "module_cadence" / "reports.jsonl"


def _observed_module_counters(hermes_home: Path, cognitive_reports: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    counters: dict[str, dict[str, Any]] = {}
    _merge_artifact_counter(
        counters,
        "cognitive_loop",
        generated_count=sum(1 for item in cognitive_reports if str(item.get("status") or "") != "error"),
        error_count=sum(1 for item in cognitive_reports if str(item.get("status") or "") == "error"),
    )
    for report in cognitive_reports:
        finished_at = str(report.get("finished_at") or report.get("created_at") or "")
        steps = report.get("steps") if isinstance(report.get("steps"), list) else []
        for step in steps:
            if not isinstance(step, dict):
                continue
            step_name = str(step.get("step") or "")
            for module in _modules_for_step(step_name):
                _record_step(counters.setdefault(module, _empty_counters()), step, finished_at)
            if step_name == "wandering_mind":
                _record_expression_submodule_steps(counters, step, finished_at)

    _merge_artifact_counter(
        counters,
        "right_brain_expression_adapter",
        generated_count=len(_read_jsonl(hermes_home / "system-modules" / "right_brain_expression_adapter" / "requests.jsonl")),
        error_count=_jsonl_error_count(hermes_home / "system-modules" / "right_brain_expression_adapter" / "requests.jsonl"),
    )
    _merge_artifact_counter(
        counters,
        "ops_gate",
        generated_count=len(_read_jsonl(hermes_home / "system-modules" / "ops_gate" / "reports.jsonl")),
        skipped_count=sum(
            1
            for item in _read_jsonl(hermes_home / "system-modules" / "ops_gate" / "runs.jsonl")
            if isinstance(item, dict) and (item.get("skipped") is True or item.get("cadence_skipped") is True)
        ),
        duplicate_count=_duplicate_ops_gate_followup_count(
            _read_jsonl(hermes_home / "system-modules" / "ops_gate" / "reports.jsonl")
        ),
    )
    _merge_artifact_counter(
        counters,
        "deep_reflection",
        generated_count=len(_read_jsonl(hermes_home / "system-modules" / "deep_reflection" / "reports.jsonl")),
        skipped_count=sum(
            1
            for item in _read_jsonl(hermes_home / "system-modules" / "deep_reflection" / "reports.jsonl")
            if isinstance(item, dict) and (item.get("skipped") is True or item.get("cadence_skipped") is True)
        ),
        error_count=_jsonl_error_count(hermes_home / "system-modules" / "deep_reflection" / "reports.jsonl"),
    )
    _merge_artifact_counter(
        counters,
        "self_evolution",
        generated_count=len(_read_jsonl(hermes_home / "system-modules" / "self_evolution" / "reports.jsonl")),
        skipped_count=sum(
            1
            for item in _read_jsonl(hermes_home / "system-modules" / "self_evolution" / "reports.jsonl")
            if isinstance(item, dict)
            and (
                item.get("skipped") is True
                or item.get("novelty_skipped") is True
                or item.get("cadence_skipped") is True
            )
        ),
        duplicate_count=sum(
            1
            for item in _read_jsonl(hermes_home / "system-modules" / "self_evolution" / "reports.jsonl")
            if isinstance(item, dict) and "duplicate" in str(item.get("reason") or "")
        ),
    )
    _merge_artifact_counter(
        counters,
        "evidence_scoring",
        generated_count=len(_read_jsonl(hermes_home / "system-modules" / "evidence_scoring" / "feature_scores.jsonl")),
        skipped_count=sum(
            1
            for item in _read_jsonl(hermes_home / "system-modules" / "evidence_scoring" / "runs.jsonl")
            if isinstance(item, dict) and (item.get("skipped") is True or item.get("cadence_skipped") is True)
        ),
        error_count=_jsonl_error_count(hermes_home / "system-modules" / "evidence_scoring" / "feature_scores.jsonl"),
    )
    _merge_artifact_counter(
        counters,
        "wandering_mind",
        generated_count=len(_read_jsonl(hermes_home / "system-modules" / "wandering_mind" / "outputs.jsonl")),
        skipped_count=sum(
            1
            for item in _read_jsonl(hermes_home / "system-modules" / "wandering_mind" / "outputs.jsonl")
            if isinstance(item, dict) and item.get("output") == "[SILENT]"
        ),
    )
    _merge_artifact_counter(
        counters,
        "expression_draft",
        generated_count=len(_read_jsonl(hermes_home / "system-modules" / "expression_draft" / "drafts.jsonl")),
        error_count=_jsonl_error_count(hermes_home / "system-modules" / "expression_draft" / "drafts.jsonl"),
    )
    _merge_artifact_counter(
        counters,
        "speak_gate",
        generated_count=len(_read_jsonl(hermes_home / "system-modules" / "speak_gate" / "would_send.jsonl")),
        error_count=_jsonl_error_count(hermes_home / "system-modules" / "speak_gate" / "would_send.jsonl"),
    )
    _merge_artifact_counter(
        counters,
        "digest_consolidation",
        generated_count=len(list((hermes_home / "system-modules" / "digest_consolidation" / "daily").glob("*.json")))
        + len(list((hermes_home / "system-modules" / "digest_consolidation" / "weekly").glob("*.json"))),
    )
    _merge_artifact_counter(
        counters,
        "household_digest",
        generated_count=1 if (hermes_home / "system-modules" / "household_digest" / "household_digest.md").exists() else 0,
    )
    _merge_artifact_counter(
        counters,
        "left_brain_pipeline_check",
        generated_count=1 if (hermes_home / "system-modules" / "left_brain_pipeline_check" / "latest.json").exists() else 0,
        error_count=1 if _json_status_is_error(hermes_home / "system-modules" / "left_brain_pipeline_check" / "latest.json") else 0,
    )
    return counters


def _empty_counters() -> dict[str, Any]:
    return {
        "run_count": 0,
        "generated_count": 0,
        "skipped_count": 0,
        "error_count": 0,
        "duplicate_count": 0,
        "last_run_at": "",
        "last_status": "missing",
    }


def _module_local_skip_gate_visible(counters: dict[str, Any]) -> bool:
    return int(counters.get("skipped_count") or 0) > 0 or int(counters.get("duplicate_count") or 0) > 0


def _current_window_error_count(counters: dict[str, Any]) -> int:
    return int(str(counters.get("last_status") or "").lower() == "error")


def _modules_for_step(step_name: str) -> tuple[str, ...]:
    if step_name in {"heartbeat_pre", "heartbeat_post"}:
        return ("heartbeat_inner_drive",)
    if step_name == "doctor_boundary_report":
        return ()
    return (step_name,) if step_name else ()


def _record_step(counter: dict[str, Any], step: dict[str, Any], finished_at: str) -> None:
    result = step.get("result") if isinstance(step.get("result"), dict) else {}
    status = str(step.get("status") or result.get("status") or "").lower()
    counter["run_count"] += 1
    counter["last_run_at"] = finished_at
    counter["last_status"] = status or "unknown"
    if status == "error" or "error" in step or result.get("status") == "error":
        counter["error_count"] += 1
    elif _result_is_duplicate(result):
        counter["skipped_count"] += 1
        counter["duplicate_count"] += 1
    elif _result_is_skipped(result, status):
        counter["skipped_count"] += 1
    else:
        counter["generated_count"] += 1


def _record_expression_submodule_steps(
    counters: dict[str, dict[str, Any]], step: dict[str, Any], finished_at: str
) -> None:
    result = step.get("result") if isinstance(step.get("result"), dict) else {}
    if result.get("expression_draft_created") is True or isinstance(result.get("expression_draft"), dict):
        _record_synthetic_result(counters, "expression_draft", finished_at, generated=True)
    elif result.get("expression_draft_skipped") is True:
        _record_synthetic_result(counters, "expression_draft", finished_at, skipped=True)
    elif result.get("output") == "[SILENT]":
        _record_synthetic_result(counters, "expression_draft", finished_at, skipped=True)
    if isinstance(result.get("speak_gate_decision"), dict):
        _record_synthetic_result(counters, "speak_gate", finished_at, generated=True)
    elif result.get("speak_gate_skipped") is True:
        _record_synthetic_result(counters, "speak_gate", finished_at, skipped=True)
    elif result.get("would_send") is True:
        _record_synthetic_result(counters, "speak_gate", finished_at, error=True)


def _record_synthetic_result(
    counters: dict[str, dict[str, Any]],
    module: str,
    finished_at: str,
    *,
    generated: bool = False,
    skipped: bool = False,
    error: bool = False,
) -> None:
    counter = counters.setdefault(module, _empty_counters())
    counter["run_count"] += 1
    counter["last_run_at"] = finished_at
    counter["last_status"] = "error" if error else "skipped" if skipped else "ok"
    if error:
        counter["error_count"] += 1
    elif skipped:
        counter["skipped_count"] += 1
    elif generated:
        counter["generated_count"] += 1


def _result_is_skipped(result: dict[str, Any], status: str) -> bool:
    if status in {"skipped", "deferred", "skipped_dependency_failed"}:
        return True
    if result.get("skipped") is True or result.get("novelty_skipped") is True or result.get("cadence_skipped") is True:
        return True
    return result.get("output") == "[SILENT]"


def _result_is_duplicate(result: dict[str, Any]) -> bool:
    if result.get("duplicate") is True:
        return True
    if result.get("novelty_skipped") is True and "duplicate" in str(result.get("reason") or ""):
        return True
    if "duplicate" in str(result.get("status") or ""):
        return True
    return False


def _merge_artifact_counter(
    counters: dict[str, dict[str, Any]],
    module: str,
    *,
    generated_count: int = 0,
    skipped_count: int = 0,
    error_count: int = 0,
    duplicate_count: int = 0,
) -> None:
    counter = counters.setdefault(module, _empty_counters())
    counter["generated_count"] = max(int(counter["generated_count"]), max(generated_count, 0))
    counter["skipped_count"] = max(int(counter["skipped_count"]), max(skipped_count, 0))
    counter["error_count"] = max(int(counter["error_count"]), max(error_count, 0))
    counter["duplicate_count"] = max(int(counter["duplicate_count"]), max(duplicate_count, 0))
    observed_total = (
        int(counter["generated_count"])
        + int(counter["skipped_count"])
        + int(counter["error_count"])
    )
    counter["run_count"] = max(int(counter["run_count"]), observed_total)
    if observed_total > 0 and counter["last_status"] == "missing":
        counter["last_status"] = "observed"


def _jsonl_error_count(path: Path) -> int:
    return sum(1 for item in _read_jsonl(path) if isinstance(item, dict) and str(item.get("status") or "") == "error")


def _json_status_is_error(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return isinstance(loaded, dict) and str(loaded.get("status") or "") == "error"


def _duplicate_ops_gate_followup_count(reports: list[dict[str, Any]]) -> int:
    action_counts: dict[str, int] = {}
    for report in reports:
        decisions = report.get("decisions") if isinstance(report.get("decisions"), list) else []
        for decision in decisions:
            if not isinstance(decision, dict):
                continue
            action_id = str(decision.get("action_id") or "")
            if action_id.startswith("proposal_followup:"):
                action_counts[action_id] = action_counts.get(action_id, 0) + 1
    return sum(max(count - 1, 0) for count in action_counts.values())


def _aggregate_counters(modules: list[dict[str, Any]]) -> dict[str, int]:
    totals = {
        "generated_count": 0,
        "skipped_count": 0,
        "error_count": 0,
        "historical_error_count": 0,
        "current_window_error_count": 0,
        "duplicate_count": 0,
        "counter_coverage_count": 0,
    }
    for module in modules:
        counters = module.get("cadence_counters") if isinstance(module.get("cadence_counters"), dict) else {}
        if counters:
            totals["counter_coverage_count"] += 1
        for key in ("generated_count", "skipped_count", "error_count", "duplicate_count"):
            totals[key] += int(counters.get(key) or 0)
        totals["current_window_error_count"] += int(module.get("current_window_error_count") or 0)
    totals["historical_error_count"] = totals["error_count"]
    return totals


if __name__ == "__main__":
    raise SystemExit(main())
