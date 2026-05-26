#!/usr/bin/env python3
"""Right-brain expression Hermes cron enable gate.

This gate creates a low-frequency Hermes cron job in agent mode. Memory-OS
provides bounded context through memory_os_right_brain_expression.py; Hermes
owns the final wording, silence decision, scheduling, and delivery.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "memory-os.right_brain_expression_cron_enable_gate.v0"
DEFAULT_JOB_NAME = "memory-os-right-brain-expression"
HELPER_NAME = "memory_os_right_brain_expression.py"
CONFIG_RELATIVE_PATH = Path("memory-os") / "config.json"
RIGHT_BRAIN_AGENT_PROMPT = (
    "这是 Memory-OS 右脑低频表达任务。Script Output 是 bounded context 和表达边界，不是最终文案。"
    "你是 Hermes agent：请判断是否应该表达；可以自然说一句，也可以回复 [SILENT]。"
    "不要执行任务、不要审批、不要改系统、不要输出内部 schema。"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate or enable Hermes cron delivery for right-brain expression.")
    parser.add_argument("--hermes-home", default=os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
    parser.add_argument("--hermes-bin", default=os.environ.get("HERMES_BIN", "hermes"))
    parser.add_argument("--schedule", required=True)
    parser.add_argument("--deliver", required=True)
    parser.add_argument("--job-name", default=DEFAULT_JOB_NAME)
    parser.add_argument("--workdir", default="")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--owner-approved", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_gate(args)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] in {"dry_run", "applied", "already_configured"} else 2


def run_gate(args: argparse.Namespace) -> dict[str, Any]:
    hermes_home = Path(args.hermes_home).expanduser().resolve()
    helper_path = hermes_home / "scripts" / HELPER_NAME
    jobs_path = hermes_home / "cron" / "jobs.json"
    env = dict(os.environ)
    env["HERMES_HOME"] = str(hermes_home)
    findings: list[dict[str, str]] = []
    if not helper_path.is_file():
        findings.append(_finding("cron_helper_missing", "error"))
    target_class = _delivery_target_class(args.deliver)
    if target_class in {"missing", "auto", "local"}:
        findings.append(_finding(f"deliver_target_{target_class}_not_allowed", "error"))
    if args.apply and not args.owner_approved:
        findings.append(_finding("owner_approval_required_for_apply", "error"))
    cron_help = _cron_create_help(args.hermes_bin, env)
    if not cron_help["supports"]:
        findings.append(_finding("hermes_cron_create_missing_required_flags", "error"))
    existing_job = _find_existing_job(jobs_path, args.job_name)

    status = "blocked" if _has_error(findings) else "dry_run"
    applied_job_id = ""
    config_updated = False
    if args.apply and not _has_error(findings):
        if existing_job:
            status = "already_configured"
            _write_recurring_config(hermes_home, args)
            config_updated = True
            applied_job_id = str(existing_job.get("id") or existing_job.get("job_id") or "")
        else:
            completed = subprocess.run(_cron_create_command(args), check=False, text=True, capture_output=True, env=env)
            if completed.returncode != 0:
                status = "error"
                findings.append(_finding("hermes_cron_create_failed", "error"))
            else:
                status = "applied"
                _write_recurring_config(hermes_home, args)
                config_updated = True
                applied_job_id = _read_job_id(jobs_path, args.job_name)

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
        "deliver_target_class": target_class,
        "checks": {
            "helper_script_present": helper_path.is_file(),
            "hermes_cron_create_available": cron_help["available"],
            "hermes_cron_supports_agent_script_deliver": cron_help["supports"],
            "existing_job_present": bool(existing_job),
        },
        "findings": findings,
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
        },
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
    command.append(RIGHT_BRAIN_AGENT_PROMPT)
    return command


def _cron_create_help(hermes_bin: str, env: dict[str, str]) -> dict[str, Any]:
    try:
        completed = subprocess.run([hermes_bin, "cron", "create", "--help"], check=False, text=True, capture_output=True, env=env)
    except FileNotFoundError:
        return {"available": False, "supports": False}
    output = f"{completed.stdout}\n{completed.stderr}"
    return {"available": completed.returncode == 0, "supports": all(flag in output for flag in ("--script", "--deliver"))}


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
    right_brain = config.get("right_brain_expression")
    if not isinstance(right_brain, dict):
        right_brain = {}
    right_brain.update(
        {
            "recurring_delivery_enabled": True,
            "recurring_delivery_mode": "hermes_cron_agent",
            "recurring_delivery_channel": _delivery_channel(args.deliver),
            "recurring_delivery_target_class": _delivery_target_class(args.deliver),
            "cron_job_name": args.job_name,
        }
    )
    config["right_brain_expression"] = right_brain
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_job_id(path: Path, job_name: str) -> str:
    job = _find_existing_job(path, job_name)
    return str((job or {}).get("id") or (job or {}).get("job_id") or "")


def _find_existing_job(path: Path, job_name: str) -> dict[str, Any]:
    if not path.exists():
        return {}
    loaded = json.loads(path.read_text(encoding="utf-8"))
    jobs = loaded.get("jobs", []) if isinstance(loaded, dict) else loaded
    if not isinstance(jobs, list):
        return {}
    for job in jobs:
        if isinstance(job, dict) and str(job.get("name") or "") == job_name:
            return job
    return {}


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


def _delivery_channel(target: str) -> str:
    value = str(target or "").strip().lower().replace("-", "_")
    if value in {"origin", "local"}:
        return value
    if ":" in value:
        return value.split(":", 1)[0]
    return value or "unknown"


def _has_error(findings: list[dict[str, str]]) -> bool:
    return any(item.get("severity") == "error" for item in findings)


def _finding(code: str, severity: str) -> dict[str, str]:
    return {"code": code, "severity": severity}


if __name__ == "__main__":
    raise SystemExit(main())
