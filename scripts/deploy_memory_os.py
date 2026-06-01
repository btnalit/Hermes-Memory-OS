#!/usr/bin/env python3
"""Automated Memory-OS deployment orchestrator.

This script coordinates existing safe primitives. It does not replace
install_memory_os.sh and does not restart Hermes unless explicitly requested.
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
from pathlib import Path
from typing import Any, Callable


Runner = Callable[..., dict[str, Any]]


def deploy_memory_os(
    *,
    repo_root: Path,
    remote_repo_root: str = "",
    hermes_home: str,
    mode: str,
    hindsight_mode: str,
    phase: str,
    profile: str,
    host: str = "",
    timeout: int = 60,
    allow_restart: bool = False,
    restart_command: str = "",
    python_bin: str | None = None,
    run_command: Runner | None = None,
) -> dict[str, Any]:
    if phase not in {"plan", "preflight", "dry-run", "apply", "postcheck"}:
        raise SystemExit("--phase must be one of: plan, preflight, dry-run, apply, postcheck")
    if profile not in {"fresh", "upgrade"}:
        raise SystemExit("--profile must be fresh or upgrade")
    if mode not in {"production-safe", "test-host", "operational"}:
        raise SystemExit("--mode must be production-safe, test-host, or operational")
    if hindsight_mode not in {"auto", "off", "adopt", "wizard"}:
        raise SystemExit("--hindsight must be auto, off, adopt, or wizard")

    runner = run_command or _run_command
    repo_root = repo_root.expanduser().resolve()
    command_repo_root = remote_repo_root or str(repo_root)
    effective_python_bin = python_bin or ("python3" if host else "python")
    commands = _build_commands(
        repo_root=command_repo_root,
        hermes_home=hermes_home,
        mode=mode,
        hindsight_mode=hindsight_mode,
        host=host,
        python_bin=effective_python_bin,
        allow_restart=allow_restart,
        restart_command=restart_command,
    )
    report: dict[str, Any] = {
        "schema_version": "memory-os.deploy.v0",
        "phase": phase,
        "profile": profile,
        "host": host or "local",
        "hermes_home": hermes_home,
        "mode": mode,
        "hindsight_mode": hindsight_mode,
        "restart_requested": bool(allow_restart and restart_command),
        "commands": commands,
        "preflight": {"status": "not_run"},
        "dry_run": {"status": "not_run"},
        "apply": {"status": "not_run"},
        "postcheck": {"status": "not_run"},
        "rollback_hint": "rerun installer with previous config backup or disable substrate_providers.hindsight.enabled",
    }
    if phase == "plan":
        return report
    if phase == "postcheck":
        postcheck = _run_json(
            commands["compat"],
            runner=runner,
            host=host,
            timeout=timeout,
            expected_schema="memory-os.hermes_upgrade_compat.v0",
        )
        report["postcheck"] = _classify_postcheck(postcheck)
        return report

    preflight = _run_json(
        commands["compat"],
        runner=runner,
        host=host,
        timeout=timeout,
        expected_schema="memory-os.hermes_upgrade_compat.v0",
    )
    report["preflight"] = _classify_preflight(preflight, profile=profile)
    if phase == "preflight":
        return report
    allowed_upgrade_preflight = {"pass", "warn_expected_for_upgrade_preinstall"}
    if phase == "apply" and profile == "upgrade" and report["preflight"]["status"] not in allowed_upgrade_preflight:
        report["apply"] = {"status": "blocked", "reason": "preflight_compat_failed"}
        return report

    if phase in {"dry-run", "apply"}:
        dry_run = _run_json(
            commands["install_dry_run"],
            runner=runner,
            host=host,
            timeout=timeout,
            expected_schema="memory-os.install.v0",
        )
        report["dry_run"] = _classify_install(dry_run, expected_dry_run=True)
        if phase == "dry-run":
            return report

    if phase == "apply":
        if report["dry_run"]["status"] != "pass":
            report["apply"] = {"status": "blocked", "reason": "install_dry_run_failed"}
            return report
        apply_result = _run_json(
            commands["install_apply"],
            runner=runner,
            host=host,
            timeout=timeout,
            expected_schema="memory-os.install.v0",
        )
        report["apply"] = _classify_install(apply_result, expected_dry_run=False)
        if report["restart_requested"]:
            report["restart"] = _redact_process_result(
                runner(commands["restart"], host=host or None, timeout=timeout)
            )
        postcheck = _run_json(
            commands["compat"],
            runner=runner,
            host=host,
            timeout=timeout,
            expected_schema="memory-os.hermes_upgrade_compat.v0",
        )
        report["postcheck"] = _classify_postcheck(postcheck)
        return report

    return report


def _build_commands(
    *,
    repo_root: str,
    hermes_home: str,
    mode: str,
    hindsight_mode: str,
    host: str,
    python_bin: str,
    allow_restart: bool,
    restart_command: str,
) -> dict[str, list[str]]:
    repo = repo_root.rstrip("/\\")
    install_base = [
        "bash",
        f"{repo}/scripts/install_memory_os.sh",
        "--yes",
        f"--{mode}",
        "--hermes-home",
        hermes_home,
        "--hindsight",
        hindsight_mode,
        "--skip-verify",
    ]
    compat = [
        python_bin,
        f"{repo}/scripts/memory_os_upgrade_compat_check.py",
        "--hermes-home",
        hermes_home,
        "--output",
        "json",
    ]
    commands: dict[str, list[str]] = {
        "compat": compat,
        "install_dry_run": install_base + ["--dry-run"],
        "install_apply": install_base,
    }
    if allow_restart and restart_command:
        commands["restart"] = shlex.split(restart_command)
    if host:
        return {name: _ssh_wrap(host, argv) for name, argv in commands.items()}
    return commands


def _ssh_wrap(host: str, argv: list[str]) -> list[str]:
    return ["ssh", host, shlex.join(argv)]


def _run_json(
    command: list[str],
    *,
    runner: Runner,
    host: str,
    timeout: int,
    expected_schema: str = "",
) -> dict[str, Any]:
    result = runner(command, host=host or None, timeout=timeout)
    redacted = _redact_process_result(result)
    redacted["json"] = _parse_json_from_output(str(result.get("stdout") or ""), expected_schema=expected_schema)
    return redacted


def _run_command(argv: list[str], *, host: str | None = None, timeout: int = 60) -> dict[str, Any]:
    del host
    completed = subprocess.run(argv, text=True, capture_output=True, timeout=timeout, check=False)
    return {"exit_code": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr}


def _redact_process_result(result: dict[str, Any]) -> dict[str, Any]:
    text = json.dumps(result, ensure_ascii=False)
    for marker in ("apiKey", "api_key", "token", "SECRET"):
        text = text.replace(marker, "[redacted]")
    return json.loads(text)


def _parse_json_from_output(output: str, *, expected_schema: str = "") -> Any:
    text = str(output or "")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    parsed: Any = None
    schema_versioned: Any = None
    for index, char in enumerate(text):
        if char not in "[{":
            continue
        try:
            value, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        parsed = value
        if isinstance(value, dict) and value.get("schema_version"):
            if expected_schema and value.get("schema_version") == expected_schema:
                return value
            schema_versioned = value
    return schema_versioned if schema_versioned is not None else parsed


def _classify_preflight(result: dict[str, Any], *, profile: str) -> dict[str, Any]:
    fail = _classification_failures(result)
    if not fail:
        return {"status": "pass", "compat": result.get("json")}
    if profile == "fresh" and _only_fresh_preinstall_memory_os_missing(fail):
        return {"status": "warn_expected_for_fresh", "compat": result.get("json"), "warn": fail}
    if profile == "upgrade" and _only_preinstall_hindsight_status_missing(fail):
        return {"status": "warn_expected_for_upgrade_preinstall", "compat": result.get("json"), "warn": fail}
    return {"status": "fail", "compat": result.get("json"), "fail": fail}


def _classify_install(result: dict[str, Any], *, expected_dry_run: bool) -> dict[str, Any]:
    if int(result.get("exit_code", 1)) != 0:
        return {"status": "fail", "exit_code": result.get("exit_code")}
    data = result.get("json")
    if not isinstance(data, dict) or data.get("schema_version") != "memory-os.install.v0":
        return {"status": "fail", "reason": "install_json_invalid"}
    if bool(data.get("dry_run")) != expected_dry_run:
        return {"status": "fail", "reason": "dry_run_mismatch"}
    return {"status": "pass" if expected_dry_run else "applied", "install": data}


def _classify_postcheck(result: dict[str, Any]) -> dict[str, Any]:
    fail = _classification_failures(result)
    if fail:
        return {"status": "fail", "compat": result.get("json"), "fail": fail}
    return {"status": "pass", "compat": result.get("json")}


def _classification_failures(result: dict[str, Any]) -> list[dict[str, Any]]:
    data = result.get("json")
    if not isinstance(data, dict):
        return [{"code": "compat_json_invalid"}]
    classification = data.get("classification") if isinstance(data.get("classification"), dict) else {}
    fail = classification.get("fail") if isinstance(classification.get("fail"), list) else []
    return [item for item in fail if isinstance(item, dict)]


def _only_preinstall_hindsight_status_missing(fail: list[dict[str, Any]]) -> bool:
    allowed = {
        "hindsight_status_command_failed",
        "hindsight_status_missing_json",
        "hindsight_provider_bank_evidence_missing",
    }
    codes = {str(item.get("code") or "") for item in fail}
    return bool(codes) and codes <= allowed


def _only_fresh_preinstall_memory_os_missing(fail: list[dict[str, Any]]) -> bool:
    allowed = {
        "memory_provider_not_memory_os",
        "shell_status_command_failed",
        "shell_doctor_command_failed",
        "hindsight_status_command_failed",
        "modules_status_command_failed",
        "modules_doctor_command_failed",
        "modules_run_once_cron_mirror_dry_run_command_failed",
        "modules_validate_no_send_command_failed",
        "low_clue_recall_command_failed",
        "memory_sources_stats_command_failed",
        "shell_status_schema_mismatch",
        "shell_doctor_missing_json",
        "hindsight_status_missing_json",
        "modules_status_schema_mismatch",
        "modules_doctor_missing_json",
        "modules_run_once_cron_mirror_dry_run_schema_mismatch",
        "modules_validate_no_send_schema_mismatch",
        "low_clue_recall_schema_mismatch",
        "memory_sources_stats_schema_mismatch",
    }
    nullable_value_allowed = {"modules_run_once_not_dry_run", "memory_sources_boundary_true"}
    for item in fail:
        code = str(item.get("code") or "")
        if code in allowed:
            continue
        if code in nullable_value_allowed and item.get("value") is None:
            continue
        return False
    return bool(fail)


def classify_deploy_report(report: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    fail: list[dict[str, Any]] = []
    warn: list[dict[str, Any]] = []
    passed: list[dict[str, Any]] = []
    for key in ("preflight", "dry_run", "apply", "postcheck"):
        section = report.get(key) if isinstance(report.get(key), dict) else {}
        status = section.get("status")
        if status in {"pass", "applied"}:
            passed.append({"code": f"{key}_{status}"})
        elif status == "warn_expected_for_fresh":
            warn.append({"code": "fresh_preflight_memory_os_preinstall_expected"})
        elif status == "warn_expected_for_upgrade_preinstall":
            warn.append({"code": "upgrade_preflight_hindsight_status_pending_install"})
        elif status == "blocked":
            fail.append({"code": str(section.get("reason") or f"{key}_blocked")})
        elif status == "fail":
            fail.append({"code": f"{key}_failed"})
    return {"pass": passed, "warn": warn, "fail": fail}


def render_deploy_plan(report: dict[str, Any]) -> str:
    lines = [
        f"Memory-OS deploy plan: phase={report['phase']} profile={report['profile']} host={report['host']}",
        f"restart_requested={str(report['restart_requested']).lower()}",
    ]
    classification = classify_deploy_report(report)
    if any(classification.values()):
        lines.append(
            "classification: "
            f"pass={_codes(classification['pass']) or '[]'} "
            f"warn={_codes(classification['warn']) or '[]'} "
            f"fail={_codes(classification['fail']) or '[]'}"
        )
    for name in ("preflight", "dry_run", "apply", "postcheck"):
        section = report.get(name) if isinstance(report.get(name), dict) else {}
        status = section.get("status")
        if status and status != "not_run":
            lines.append(f"{name}_status={status}")
    commands = report.get("commands") if isinstance(report.get("commands"), dict) else {}
    for name, argv in commands.items():
        lines.append(f"{name}: {shlex.join(argv)}")
    return "\n".join(lines)


def _codes(items: list[dict[str, Any]]) -> str:
    codes = [str(item.get("code") or "") for item in items if item.get("code")]
    return ",".join(codes)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Automate Memory-OS deployment with compatibility gates.")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--remote-repo-root",
        default="",
        help="Path to this checkout on the SSH target. Required when --host cannot use --repo-root.",
    )
    parser.add_argument("--host", default="")
    parser.add_argument("--hermes-home", required=True)
    parser.add_argument("--mode", choices=["production-safe", "test-host", "operational"], default="production-safe")
    parser.add_argument("--hindsight", choices=["auto", "off", "adopt", "wizard"], default="auto")
    parser.add_argument("--phase", choices=["plan", "preflight", "dry-run", "apply", "postcheck"], default="plan")
    parser.add_argument("--profile", choices=["fresh", "upgrade"], default="upgrade")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument(
        "--python-bin",
        default="",
        help="Python executable for target commands. Defaults to python locally and python3 over SSH.",
    )
    parser.add_argument("--allow-restart", action="store_true")
    parser.add_argument("--restart-command", default="")
    parser.add_argument("--output", choices=["summary", "json"], default="summary")
    args = parser.parse_args(argv)

    report = deploy_memory_os(
        repo_root=args.repo_root,
        remote_repo_root=args.remote_repo_root,
        host=args.host,
        hermes_home=args.hermes_home,
        mode=args.mode,
        hindsight_mode=args.hindsight,
        phase=args.phase,
        profile=args.profile,
        timeout=args.timeout,
        allow_restart=args.allow_restart,
        restart_command=args.restart_command,
        python_bin=args.python_bin or None,
    )
    if args.output == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render_deploy_plan(report))
    return 1 if classify_deploy_report(report)["fail"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
