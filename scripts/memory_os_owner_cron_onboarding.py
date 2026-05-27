#!/usr/bin/env python3
"""Interactive/dry-run onboarding for Memory-OS owner-facing Hermes cron.

Hermes owns channel delivery, cron scheduling, and agent interaction. This
script discovers configured Hermes owner channels, then delegates job creation
to the existing owner-review and right-brain cron gates.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "memory-os.owner_cron_onboarding.v0"
DEFAULT_OWNER_REVIEW_SCHEDULE = "0 9 * * *"
DEFAULT_RIGHT_BRAIN_SCHEDULE = "30 4 * * 0"
EXPRESSION_FEEDBACK_AGENT_PROMPT = (
    "你正在处理 Memory-OS 右脑表达反馈请求。Script Output 为空时只回复 [SILENT]。"
    "如果非空，请用中文自然询问 owner，并保留每个 memory feedback oa_... token 命令。"
    "不要替 owner 判断；owner 明确给 token/rating 后才调用 memory_os_review_reply。"
)
MEMORY_SOURCES_FEEDBACK_AGENT_PROMPT = (
    "你正在处理 Memory-OS MemorySources 反馈请求。Script Output 为空时只回复 [SILENT]。"
    "如果非空，请用中文自然询问这次上下文是否有帮助；一次只收一个 rating，"
    "用户给多个 rating 时先反问确认；不要替 owner 判断，明确后调用 memory_os_review_reply。"
)
CHANNEL_PRIORITY = (
    "telegram",
    "discord",
    "signal",
    "whatsapp",
    "slack",
    "matrix",
    "mattermost",
    "email",
    "sms",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Onboard Memory-OS owner-review and right-brain Hermes cron jobs.")
    parser.add_argument("--hermes-home", default=os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
    parser.add_argument("--hermes-bin", default=os.environ.get("HERMES_BIN", "hermes"))
    parser.add_argument("--owner", default=os.environ.get("MEMORY_OS_OWNER", "owner"))
    parser.add_argument("--channel", default=os.environ.get("MEMORY_OS_OWNER_REVIEW_CHANNEL", "owner_review_cron"))
    parser.add_argument("--owner-review-deliver", default="auto")
    parser.add_argument("--right-brain-deliver", default="origin")
    parser.add_argument("--owner-review-schedule", default=DEFAULT_OWNER_REVIEW_SCHEDULE)
    parser.add_argument("--right-brain-schedule", default=DEFAULT_RIGHT_BRAIN_SCHEDULE)
    parser.add_argument("--module-cadence-schedule", default="15 */6 * * *")
    parser.add_argument("--right-brain-outcome-schedule", default="45 4 * * 0")
    parser.add_argument("--proposal-followups-schedule", default="*/30 * * * *")
    parser.add_argument("--expression-feedback-schedule", default="0 5 * * 0")
    parser.add_argument("--memory-sources-feedback-schedule", default="30 10 * * *")
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--owner-approved", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_onboarding(args)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] in {"dry_run", "applied", "already_configured", "updated"} else 2


def run_onboarding(args: argparse.Namespace) -> dict[str, Any]:
    hermes_home = Path(args.hermes_home).expanduser().resolve()
    channels = discover_owner_channels(hermes_home)
    findings: list[dict[str, str]] = []

    owner_review_deliver = _resolve_deliver(
        requested=str(args.owner_review_deliver),
        channels=channels,
        interactive=bool(args.interactive),
        prompt="Select owner review delivery channel",
    )
    right_brain_deliver = _resolve_deliver(
        requested=str(args.right_brain_deliver),
        channels=channels,
        interactive=bool(args.interactive),
        prompt="Select right-brain expression delivery channel",
        allow_origin=True,
    )

    if owner_review_deliver == "auto":
        findings.append(_finding("owner_review_deliver_auto_unresolved", "error"))
    if not owner_review_deliver:
        findings.append(_finding("owner_review_deliver_missing", "error"))
    if not right_brain_deliver:
        findings.append(_finding("right_brain_deliver_missing", "error"))
    if args.apply and not args.owner_approved:
        findings.append(_finding("owner_approval_required_for_apply", "error"))

    status = "blocked" if _has_error(findings) else "dry_run"
    owner_review_channel = _resolve_owner_review_channel(str(args.channel), owner_review_deliver)
    owner_report: dict[str, Any] = {}
    right_brain_report: dict[str, Any] = {}
    operational_jobs: list[dict[str, Any]] = []
    operational_specs = _operational_specs(args, owner_review_deliver)
    for spec in operational_specs:
        if not (hermes_home / "scripts" / spec["script"]).is_file():
            findings.append(_finding(f"{spec['name']}_helper_missing", "error"))
    if not _has_error(findings):
        owner_gate = _load_script_module("memory_os_owner_review_cron_gate.py")
        right_brain_gate = _load_script_module("memory_os_right_brain_expression_cron_gate.py")
        owner_args = owner_gate.build_parser().parse_args(
            [
                "--hermes-home",
                str(hermes_home),
                "--hermes-bin",
                str(args.hermes_bin),
                "--schedule",
                str(args.owner_review_schedule),
                "--deliver",
                owner_review_deliver,
                "--owner",
                str(args.owner),
                "--channel",
                owner_review_channel,
                *(["--apply"] if args.apply else []),
                *(["--owner-approved"] if args.owner_approved else []),
            ]
        )
        rb_args = right_brain_gate.build_parser().parse_args(
            [
                "--hermes-home",
                str(hermes_home),
                "--hermes-bin",
                str(args.hermes_bin),
                "--schedule",
                str(args.right_brain_schedule),
                "--deliver",
                right_brain_deliver,
                *(["--apply"] if args.apply else []),
                *(["--owner-approved"] if args.owner_approved else []),
            ]
        )
        owner_report = owner_gate.run_gate(owner_args)
        right_brain_report = right_brain_gate.run_gate(rb_args)
        findings.extend(_prefixed_findings("owner_review", owner_report.get("findings")))
        findings.extend(_prefixed_findings("right_brain", right_brain_report.get("findings")))
        if _has_error(findings):
            status = "blocked"
        elif args.apply:
            operational_jobs = [
                _gate_job_entry(
                    name="memory-os-owner-review-digest",
                    report=owner_report,
                    deliver=owner_review_deliver,
                    script="memory_os_owner_review_digest.py",
                    no_agent=False,
                    schedule=str(args.owner_review_schedule),
                ),
                _gate_job_entry(
                    name="memory-os-right-brain-expression",
                    report=right_brain_report,
                    deliver=right_brain_deliver,
                    script="memory_os_right_brain_expression.py",
                    no_agent=False,
                    schedule=str(args.right_brain_schedule),
                ),
            ]
            for spec in operational_specs:
                operational_jobs.append(_ensure_cron_job(hermes_home=hermes_home, hermes_bin=str(args.hermes_bin), spec=spec))
            gate_statuses = {str(owner_report.get("status") or ""), str(right_brain_report.get("status") or "")}
            if gate_statuses <= {"already_configured"}:
                status = "already_configured"
            elif gate_statuses <= {"applied", "already_configured", "updated"}:
                status = "applied" if "applied" in gate_statuses else "updated"
            else:
                status = "blocked"
        else:
            status = "dry_run"
            operational_jobs = [
                _gate_job_entry(
                    name="memory-os-owner-review-digest",
                    report=owner_report,
                    deliver=owner_review_deliver,
                    script="memory_os_owner_review_digest.py",
                    no_agent=False,
                    schedule=str(args.owner_review_schedule),
                ),
                _gate_job_entry(
                    name="memory-os-right-brain-expression",
                    report=right_brain_report,
                    deliver=right_brain_deliver,
                    script="memory_os_right_brain_expression.py",
                    no_agent=False,
                    schedule=str(args.right_brain_schedule),
                ),
                *[
                {
                    "name": spec["name"],
                    "schedule": spec["schedule"],
                    "deliver": spec["deliver"],
                    "script": spec["script"],
                    "no_agent": spec["no_agent"],
                    "status": "dry_run",
                }
                for spec in operational_specs
                ],
            ]

    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "apply_requested": bool(args.apply),
        "owner_approved": bool(args.owner_approved),
        "detected_channels": channels,
        "selected_owner_review_deliver": owner_review_deliver,
        "selected_owner_review_channel": owner_review_channel,
        "selected_right_brain_deliver": right_brain_deliver,
        "owner_review_schedule": str(args.owner_review_schedule),
        "right_brain_schedule": str(args.right_brain_schedule),
        "owner_review": _summarize_gate(owner_report),
        "right_brain": _summarize_gate(right_brain_report),
        "operational_cron_jobs": operational_jobs,
        "findings": findings,
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
        },
    }


def _operational_specs(args: argparse.Namespace, owner_deliver: str) -> list[dict[str, Any]]:
    return [
        {
            "name": "memory-os-module-cadence-report",
            "schedule": str(args.module_cadence_schedule),
            "deliver": "local",
            "script": "memory_os_module_cadence_report_cron.py",
            "no_agent": True,
            "prompt": "",
        },
        {
            "name": "memory-os-right-brain-expression-outcome",
            "schedule": str(args.right_brain_outcome_schedule),
            "deliver": "local",
            "script": "memory_os_right_brain_expression_outcome_cron.py",
            "no_agent": True,
            "prompt": "",
        },
        {
            "name": "memory-os-proposal-followups-opsgate",
            "schedule": str(args.proposal_followups_schedule),
            "deliver": "local",
            "script": "memory_os_proposal_followups_ops_gate.py",
            "no_agent": True,
            "prompt": "",
        },
        {
            "name": "memory-os-expression-feedback-request",
            "schedule": str(args.expression_feedback_schedule),
            "deliver": owner_deliver,
            "script": "memory_os_expression_feedback_prompt.py",
            "no_agent": False,
            "prompt": EXPRESSION_FEEDBACK_AGENT_PROMPT,
        },
        {
            "name": "memory-os-memory-sources-feedback-request",
            "schedule": str(args.memory_sources_feedback_schedule),
            "deliver": owner_deliver,
            "script": "memory_os_memory_sources_feedback_prompt.py",
            "no_agent": False,
            "prompt": MEMORY_SOURCES_FEEDBACK_AGENT_PROMPT,
        },
    ]


def _ensure_cron_job(*, hermes_home: Path, hermes_bin: str, spec: dict[str, Any]) -> dict[str, Any]:
    existing = _find_job_by_name(_read_jobs(hermes_home / "cron" / "jobs.json"), str(spec["name"]))
    if existing:
        return {
            "name": spec["name"],
            "job_id": str(existing.get("id") or existing.get("job_id") or ""),
            "status": "already_configured",
            "deliver": str(existing.get("deliver") or spec["deliver"]),
            "script": str(existing.get("script") or spec["script"]),
            "no_agent": bool(existing.get("no_agent")),
        }
    command = [
        hermes_bin,
        "cron",
        "create",
        "--name",
        str(spec["name"]),
        "--deliver",
        str(spec["deliver"]),
        "--script",
        str(spec["script"]),
    ]
    if spec.get("no_agent"):
        command.append("--no-agent")
    command.append(str(spec["schedule"]))
    if spec.get("prompt"):
        command.append(str(spec["prompt"]))
    env = dict(os.environ)
    env["HERMES_HOME"] = str(hermes_home)
    completed = subprocess.run(command, check=False, text=True, capture_output=True, env=env)
    if completed.returncode != 0:
        return {
            "name": spec["name"],
            "status": "error",
            "stderr": (completed.stderr or completed.stdout or "").strip()[:500],
            "deliver": str(spec["deliver"]),
            "script": str(spec["script"]),
            "no_agent": bool(spec.get("no_agent")),
        }
    created = _find_job_by_name(_read_jobs(hermes_home / "cron" / "jobs.json"), str(spec["name"]))
    return {
        "name": spec["name"],
        "job_id": str((created or {}).get("id") or (created or {}).get("job_id") or ""),
        "status": "applied",
        "deliver": str(spec["deliver"]),
        "script": str(spec["script"]),
        "no_agent": bool(spec.get("no_agent")),
    }


def _gate_job_entry(
    *,
    name: str,
    report: dict[str, Any],
    deliver: str,
    script: str,
    no_agent: bool,
    schedule: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "job_id": str(report.get("job_id") or ""),
        "status": str(report.get("status") or "dry_run"),
        "schedule": schedule,
        "deliver": deliver,
        "script": script,
        "no_agent": no_agent,
    }


def _read_jobs(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    jobs = loaded.get("jobs", loaded) if isinstance(loaded, dict) else loaded
    return [dict(item) for item in jobs if isinstance(item, dict)] if isinstance(jobs, list) else []


def _find_job_by_name(jobs: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for job in jobs:
        if str(job.get("name") or "") == name:
            return job
    return None


def discover_owner_channels(hermes_home: str | Path) -> list[dict[str, str]]:
    home = Path(hermes_home).expanduser().resolve()
    directory = home / "channel_directory.json"
    platforms: dict[str, Any] = {}
    if directory.exists():
        try:
            loaded = json.loads(directory.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("platforms"), dict):
                platforms = dict(loaded["platforms"])
        except json.JSONDecodeError:
            platforms = {}
    ordered_platforms = [name for name in CHANNEL_PRIORITY if name in platforms]
    ordered_platforms.extend(sorted(name for name in platforms if name not in ordered_platforms))
    channels: list[dict[str, str]] = []
    for platform in ordered_platforms:
        entries = platforms.get(platform)
        if not isinstance(entries, list) or not entries:
            continue
        first = entries[0] if isinstance(entries[0], dict) else {}
        channels.append(
            {
                "platform": str(platform),
                "deliver": str(platform),
                "target_class": "platform_home",
                "source": "channel_directory",
                "entry_count": str(len(entries)),
                "sample_type": str(first.get("type") or ""),
                "sample_name": str(first.get("name") or ""),
            }
        )
    return channels


def _resolve_deliver(
    *,
    requested: str,
    channels: list[dict[str, str]],
    interactive: bool,
    prompt: str,
    allow_origin: bool = False,
) -> str:
    value = str(requested or "").strip()
    if value != "auto":
        return value
    choices = list(channels)
    if allow_origin:
        choices.insert(
            0,
            {
                "platform": "origin",
                "deliver": "origin",
                "target_class": "origin",
                "source": "hermes_origin",
                "entry_count": "",
                "sample_type": "",
                "sample_name": "",
            },
        )
    if not choices:
        return "auto"
    if interactive and sys.stdin.isatty():
        for idx, channel in enumerate(choices, start=1):
            suffix = f" ({channel.get('sample_name')})" if channel.get("sample_name") else ""
            print(f"{idx}. {channel['deliver']}{suffix}")
        selected = input(f"{prompt} [1]: ").strip()
        if selected:
            try:
                index = int(selected)
            except ValueError:
                return selected
            if 1 <= index <= len(choices):
                return choices[index - 1]["deliver"]
    return choices[0]["deliver"]


def _resolve_owner_review_channel(requested: str, owner_review_deliver: str) -> str:
    value = str(requested or "").strip()
    if value and value not in {"auto", "owner_review_cron", "unknown"}:
        return value
    label = str(owner_review_deliver or "").strip()
    label = label.split(":", 1)[0]
    label = label.replace("-", "_")
    return label or "owner_review"


def _load_script_module(filename: str):
    path = Path(__file__).resolve().parent / filename
    spec = importlib.util.spec_from_file_location(Path(filename).stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _summarize_gate(report: dict[str, Any]) -> dict[str, Any]:
    if not report:
        return {}
    return {
        "status": report.get("status"),
        "job_name": report.get("job_name"),
        "job_id": report.get("job_id"),
        "deliver_target_class": report.get("deliver_target_class"),
        "config_updated": report.get("config_updated"),
        "findings": report.get("findings") if isinstance(report.get("findings"), list) else [],
    }


def _prefixed_findings(prefix: str, findings: Any) -> list[dict[str, str]]:
    if not isinstance(findings, list):
        return []
    result: list[dict[str, str]] = []
    for item in findings:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "")
        if code == "cron_job_already_present":
            continue
        result.append({"code": f"{prefix}_{code}", "severity": str(item.get("severity") or "warning")})
    return result


def _has_error(findings: list[dict[str, str]]) -> bool:
    return any(item.get("severity") == "error" for item in findings)


def _finding(code: str, severity: str) -> dict[str, str]:
    return {"code": code, "severity": severity}


if __name__ == "__main__":
    raise SystemExit(main())
