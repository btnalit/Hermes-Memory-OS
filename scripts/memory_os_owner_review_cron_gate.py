#!/usr/bin/env python3
"""Explicit opt-in gate for Memory-OS owner review delivery via Hermes cron.

This script does not send messages directly. In apply mode it creates or updates
a Hermes cron job that runs the Memory-OS bounded digest helper in agent mode:
the helper stdout is injected into Hermes' prompt, and Hermes owns judgment,
wording, interaction, scheduling, and delivery.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "memory-os.owner_review_cron_enable_gate.v0"
DEFAULT_JOB_NAME = "memory-os-owner-review-digest"
HELPER_NAME = "memory_os_owner_review_digest.py"
CONFIG_RELATIVE_PATH = Path("memory-os") / "config.json"
OWNER_REVIEW_AGENT_PROMPT = (
    "你正在处理 Memory-OS owner review digest。步骤：1) 读取 Script Output，它是 Memory-OS 生成的 bounded review brief，"
    "不是最终用户文案。2) 如果 Script Output 为空，最终只回复 [SILENT]。3) 用中文给 owner 输出一份简洁审批摘要，"
    "不要逐字照搬英文/内部字段。4) 默认把它当作今日议程：只推需要 owner 决策的事项和真实告警；不要展开 Review Suggested/FYI/backlog 总数，"
    "除非 Script Output 明确把它们列为告警。未展示项只用一句话说明可主动要求展开。5) 每个可操作项必须写清楚：事项是什么、owner 要决定什么、"
    "审批内容、批准/拒绝/允许后的后果、完整 stable action token 命令。不要只列命令。"
    "如果 Script Output 中有 `内容:`，必须保留为 `审批内容:`；如果内容里有 `具体改动`、`证据`、`验收标准`、`后续状态`、`边界`，"
    "必须完整保留这些要点，不要摘要成标题。6) 必须保留每个可操作项的 stable action token 和完整命令，例如 "
    "memory approve oa_... / memory reject oa_...。7) 明确告诉 owner：A1/R1/F1 只是列表编号，不是审批 ID；"
    "owner 可以复制完整命令，也可以只回复 oa_... 后由你继续追问 approve/reject/allow/feedback。"
    "8) 不要自动审批、不要自动执行、不要改写 Memory-OS 状态；owner 回复后再调用 Memory-OS review tool。"
    "9) 只使用 Script Output 里的事实；不要编造候选内容、原因、后果或执行结果。"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate or enable Hermes cron delivery for Memory-OS owner review.")
    parser.add_argument("--hermes-home", default=os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
    parser.add_argument("--hermes-bin", default=os.environ.get("HERMES_BIN", "hermes"))
    parser.add_argument("--schedule", required=True, help="Hermes cron schedule, e.g. '0 9 * * *' or 'every 24h'.")
    parser.add_argument("--deliver", required=True, help="Hermes cron --deliver target. Redacted in reports.")
    parser.add_argument("--owner", default=os.environ.get("MEMORY_OS_OWNER_REVIEW_OWNER", "owner"))
    parser.add_argument("--channel", default=os.environ.get("MEMORY_OS_OWNER_REVIEW_CHANNEL", "owner_review_cron"))
    parser.add_argument("--job-name", default=DEFAULT_JOB_NAME)
    parser.add_argument("--workdir", default="")
    parser.add_argument("--apply", action="store_true", help="Create the Hermes cron job and update Memory-OS recurring config.")
    parser.add_argument("--owner-approved", action="store_true", help="Required with --apply to make recurring delivery explicit.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_gate(args)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] in {"ok", "dry_run", "applied", "already_configured"} else 2


def run_gate(args: argparse.Namespace) -> dict[str, Any]:
    hermes_home = Path(args.hermes_home).expanduser().resolve()
    helper_path = hermes_home / "scripts" / HELPER_NAME
    jobs_path = hermes_home / "cron" / "jobs.json"
    env = dict(os.environ)
    env["HERMES_HOME"] = str(hermes_home)

    checks: dict[str, Any] = {
        "helper_script_present": helper_path.is_file(),
        "deliver_target_class": _delivery_target_class(args.deliver),
        "owner_approved": bool(args.owner_approved),
        "apply_requested": bool(args.apply),
    }
    findings: list[dict[str, str]] = []
    if not checks["helper_script_present"]:
        findings.append(_finding("cron_helper_missing", "error"))
    if not str(args.deliver).strip():
        findings.append(_finding("deliver_target_missing", "error"))
    if _delivery_target_class(args.deliver) == "auto":
        findings.append(_finding("deliver_target_auto_unresolved", "error"))
    if _delivery_target_class(args.deliver) == "local":
        findings.append(_finding("deliver_target_local_not_owner_channel", "error"))
    if args.apply and not args.owner_approved:
        findings.append(_finding("owner_approval_required_for_apply", "error"))

    cron_help = _cron_create_help(args.hermes_bin, env)
    checks["hermes_cron_create_available"] = cron_help["available"]
    checks["hermes_cron_supports_agent_script_deliver"] = cron_help["supports"]
    if not cron_help["supports"]:
        findings.append(_finding("hermes_cron_create_missing_required_flags", "error"))

    jobs = _read_jobs(jobs_path)
    matched_job = _find_job(jobs, job_name=args.job_name, helper_name=HELPER_NAME)
    checks["existing_job_present"] = bool(matched_job)
    checks["existing_job_enabled"] = bool((matched_job or {}).get("enabled")) if matched_job else False
    checks["existing_job_id"] = str((matched_job or {}).get("id") or (matched_job or {}).get("job_id") or "")
    checks["existing_job_no_agent"] = bool((matched_job or {}).get("no_agent")) if matched_job else False
    checks["existing_job_needs_update"] = bool(matched_job) and _job_needs_update(matched_job, args)
    if matched_job:
        findings.append(_finding("cron_job_already_present", "warning"))

    render_check = _render_check(args, env) if not _has_error(findings) else {"ok": False, "skipped": True}
    checks["render_check"] = render_check
    if render_check.get("raw_body_included"):
        findings.append(_finding("render_check_raw_body_included", "error"))
    if render_check.get("internal_schema_primary"):
        findings.append(_finding("render_check_internal_schema_primary", "error"))
    if render_check.get("error"):
        findings.append(_finding("render_check_failed", "error"))

    command = _cron_create_command(args)
    status = "dry_run"
    applied_job_id = ""
    config_updated = False
    if args.apply:
        if _has_error(findings):
            status = "blocked"
        elif matched_job:
            if checks["existing_job_needs_update"]:
                completed = subprocess.run(_cron_edit_command(args, checks["existing_job_id"]), check=False, text=True, capture_output=True, env=env)
                if completed.returncode != 0:
                    status = "error"
                    findings.append(_finding("hermes_cron_edit_failed", "error"))
                    checks["hermes_cron_edit_stderr"] = (completed.stderr or completed.stdout or "").strip()[:500]
                else:
                    status = "updated"
                    _write_recurring_config(hermes_home, args)
                    config_updated = True
                    applied_job_id = checks["existing_job_id"]
            else:
                status = "already_configured"
                _write_recurring_config(hermes_home, args)
                config_updated = True
                applied_job_id = checks["existing_job_id"]
        else:
            completed = subprocess.run(command, check=False, text=True, capture_output=True, env=env)
            if completed.returncode != 0:
                status = "error"
                findings.append(_finding("hermes_cron_create_failed", "error"))
                checks["hermes_cron_create_stderr"] = (completed.stderr or completed.stdout or "").strip()[:500]
            else:
                status = "applied"
                _write_recurring_config(hermes_home, args)
                config_updated = True
                jobs_after = _read_jobs(jobs_path)
                created = _find_job(jobs_after, job_name=args.job_name, helper_name=HELPER_NAME)
                applied_job_id = str((created or {}).get("id") or (created or {}).get("job_id") or "")
    elif _has_error(findings):
        status = "blocked"

    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "apply_requested": bool(args.apply),
        "config_updated": config_updated,
        "job_name": args.job_name,
        "job_id": applied_job_id,
        "schedule_display": str(args.schedule),
        "helper_script_name": HELPER_NAME,
        "helper_script_path": str(helper_path),
        "deliver_target_class": _delivery_target_class(args.deliver),
        "command_preview": _redacted_command_preview(args),
        "checks": checks,
        "findings": findings,
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
        },
    }


def _cron_create_help(hermes_bin: str, env: dict[str, str]) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            [hermes_bin, "cron", "create", "--help"],
            check=False,
            text=True,
            capture_output=True,
            env=env,
        )
    except FileNotFoundError:
        return {"available": False, "supports": False}
    output = f"{completed.stdout}\n{completed.stderr}"
    return {
        "available": completed.returncode == 0,
        "supports": all(flag in output for flag in ("--script", "--deliver")),
    }


def _render_check(args: argparse.Namespace, env: dict[str, str]) -> dict[str, Any]:
    command = [
        args.hermes_bin,
        "memory-os-agent-os",
        "review",
        "render-digest",
        "--owner",
        args.owner,
        "--channel",
        args.channel,
        "--format",
        "text",
        "--bounded",
    ]
    try:
        completed = subprocess.run(command, check=False, text=True, capture_output=True, env=env)
    except FileNotFoundError:
        return {"ok": False, "error": "hermes_command_missing"}
    text = completed.stdout or ""
    if completed.returncode != 0:
        return {"ok": False, "error": "render_digest_failed", "stderr": (completed.stderr or "")[:500]}
    return {
        "ok": True,
        "text_char_count": len(text),
        "raw_body_included": "raw_body" in text or "RAW " in text,
        "internal_schema_primary": any(marker in text for marker in ("Candidate kind=", "source_events=", "sensitivity=")),
    }


def _cron_create_command(args: argparse.Namespace) -> list[str]:
    command = [
        args.hermes_bin,
        "cron",
        "create",
        "--name",
        args.job_name,
        "--deliver",
        args.deliver,
        "--script",
        HELPER_NAME,
    ]
    if args.workdir:
        command.extend(["--workdir", args.workdir])
    command.append(args.schedule)
    command.append(OWNER_REVIEW_AGENT_PROMPT)
    return command


def _cron_edit_command(args: argparse.Namespace, job_id: str) -> list[str]:
    command = [
        args.hermes_bin,
        "cron",
        "edit",
        job_id,
        "--schedule",
        args.schedule,
        "--deliver",
        args.deliver,
        "--script",
        HELPER_NAME,
        "--agent",
        "--prompt",
        OWNER_REVIEW_AGENT_PROMPT,
    ]
    if args.workdir:
        command.extend(["--workdir", args.workdir])
    return command


def _job_needs_update(job: dict[str, Any], args: argparse.Namespace) -> bool:
    return any(
        [
            bool(job.get("no_agent")),
            str(job.get("script") or "") != HELPER_NAME,
            str(job.get("deliver") or "") != str(args.deliver),
            str(job.get("prompt") or "") != OWNER_REVIEW_AGENT_PROMPT,
        ]
    )


def _redacted_command_preview(args: argparse.Namespace) -> list[str]:
    command = _cron_create_command(args)
    redacted: list[str] = []
    skip_next = False
    for item in command:
        if skip_next:
            redacted.append("<delivery-target>")
            skip_next = False
            continue
        redacted.append(item)
        if item == "--deliver":
            skip_next = True
    return redacted


def _read_jobs(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    jobs = loaded.get("jobs", loaded) if isinstance(loaded, dict) else loaded
    return [dict(item) for item in jobs if isinstance(item, dict)] if isinstance(jobs, list) else []


def _find_job(jobs: list[dict[str, Any]], *, job_name: str, helper_name: str) -> dict[str, Any] | None:
    for job in jobs:
        if str(job.get("name") or "") == job_name:
            return job
        if str(job.get("script") or "").endswith(helper_name):
            return job
    return None


def _write_recurring_config(hermes_home: Path, args: argparse.Namespace) -> None:
    path = hermes_home / CONFIG_RELATIVE_PATH
    config: dict[str, Any] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                config = loaded
        except json.JSONDecodeError:
            config = {}
    owner_review = config.get("owner_review")
    if not isinstance(owner_review, dict):
        owner_review = {}
    owner_review.update(
        {
            "recurring_delivery_enabled": True,
            "recurring_delivery_mode": "hermes_cron_agent",
            "recurring_delivery_channel": _delivery_channel(args.deliver, configured_channel=args.channel),
            "recurring_delivery_target_class": _delivery_target_class(args.deliver),
            "cron_job_name": args.job_name,
            "owner_id": args.owner,
        }
    )
    config["owner_review"] = owner_review
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _delivery_target_class(target: str) -> str:
    value = str(target or "").strip()
    if not value:
        return "missing"
    if value == "origin":
        return "origin"
    if value == "auto":
        return "auto"
    if value == "local":
        return "local"
    if ":" in value:
        return "explicit_target"
    return "platform_home"


def _delivery_channel(target: str, *, configured_channel: str = "") -> str:
    configured = str(configured_channel or "").strip().lower().replace("-", "_")
    if configured not in {"", "auto", "owner_review_cron", "unknown"}:
        return configured
    value = str(target or "").strip().lower().replace("-", "_")
    if not value:
        return "unknown"
    if value in {"origin", "local"}:
        return value
    if ":" in value:
        value = value.split(":", 1)[0]
    return value or "unknown"


def _has_error(findings: list[dict[str, str]]) -> bool:
    return any(item.get("severity") == "error" for item in findings)


def _finding(code: str, severity: str) -> dict[str, str]:
    return {"code": code, "severity": severity}


if __name__ == "__main__":
    raise SystemExit(main())
