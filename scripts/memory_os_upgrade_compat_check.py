"""Read-only Hermes upgrade compatibility gate for Memory-OS.

The check validates the natural operator paths that should survive Hermes
upgrades. It does not install, restart, run heartbeat, run cognitive loop,
apply cleanup, apply shadow journals, or read private transcripts.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
from dataclasses import dataclass
from typing import Any, Callable


PREVIEW_LIMIT = 4000


@dataclass(frozen=True)
class CommandSpec:
    name: str
    argv: tuple[str, ...]
    json_output: bool = True
    required: bool = True


COMMANDS: tuple[CommandSpec, ...] = (
    CommandSpec("hermes_version", ("hermes", "--version"), json_output=False, required=False),
    CommandSpec("memory_provider", ("hermes", "memory"), json_output=False),
    CommandSpec("shell_status", ("hermes", "memory-os-agent-os", "status")),
    CommandSpec("shell_doctor", ("hermes", "memory-os-agent-os", "doctor")),
    CommandSpec("hindsight_status", ("hermes", "memory-os-agent-os", "hindsight", "status")),
    CommandSpec("modules_status", ("hermes", "memory-os-agent-os", "modules", "status")),
    CommandSpec("modules_doctor", ("hermes", "memory-os-agent-os", "modules", "doctor")),
    CommandSpec(
        "modules_run_once_cron_mirror_dry_run",
        ("hermes", "memory-os-agent-os", "modules", "run-once", "--module", "cron_mirror", "--dry-run"),
    ),
    CommandSpec("modules_validate_no_send", ("hermes", "memory-os-agent-os", "modules", "validate-no-send")),
    CommandSpec(
        "low_clue_recall",
        ("hermes", "memory-os-agent-os", "low-clue-recall", "dry-run", "--query", "继续昨天那个"),
    ),
    CommandSpec(
        "memory_sources_stats",
        ("hermes", "memory-os-agent-os", "memory-sources", "stats", "--hours", "24"),
    ),
)


RunCommand = Callable[[tuple[str, ...], str | None, str | None, int], dict[str, Any]]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run read-only Memory-OS Hermes upgrade compatibility checks.")
    parser.add_argument("--host", default="", help="Optional SSH host, for example hermes-media.")
    parser.add_argument("--hermes-home", default="", help="Optional HERMES_HOME to set for each command.")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--output", choices=["summary", "json"], default="summary")
    args = parser.parse_args(argv)

    report = run_upgrade_compat_check(
        host=args.host or None,
        hermes_home=args.hermes_home or None,
        timeout=args.timeout,
    )
    if args.output == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render_summary(report))
    return 1 if report["classification"]["fail"] else 0


def run_upgrade_compat_check(
    *,
    host: str | None = None,
    hermes_home: str | None = None,
    timeout: int = 30,
    run_command: RunCommand | None = None,
) -> dict[str, Any]:
    runner = run_command or run_command_default
    command_results = {
        spec.name: _run_spec(spec, host=host, hermes_home=hermes_home, timeout=timeout, run_command=runner)
        for spec in COMMANDS
    }
    classification = classify_report(command_results)
    return {
        "schema_version": "memory-os.hermes_upgrade_compat.v0",
        "host": host or "local",
        "hermes_home": hermes_home or "",
        "commands": command_results,
        "classification": classification,
    }


def run_command_default(
    argv: tuple[str, ...],
    host: str | None,
    hermes_home: str | None,
    timeout: int,
) -> dict[str, Any]:
    env = os.environ.copy()
    if hermes_home:
        env["HERMES_HOME"] = hermes_home
    if host:
        remote_command = shlex.join(argv)
        if hermes_home:
            remote_command = f"HERMES_HOME={shlex.quote(hermes_home)} {remote_command}"
        completed = subprocess.run(
            ["ssh", host, remote_command],
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    else:
        completed = subprocess.run(
            list(argv),
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            env=env,
        )
    return {
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def classify_report(command_results: dict[str, dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    passed: list[dict[str, Any]] = []
    warn: list[dict[str, Any]] = []
    fail: list[dict[str, Any]] = []

    _classify_command_exit(command_results, passed, warn, fail)
    _require_memory_provider(command_results, passed, fail)
    _require_schema(command_results, "shell_status", "memory-os.status.v0", passed, fail)
    _require_doctor_ok(command_results, "shell_doctor", passed, fail)
    _require_hindsight_status(command_results, passed, fail)
    _require_schema(command_results, "modules_status", "memory-os.modules_status.v0", passed, fail)
    _require_doctor_ok(command_results, "modules_doctor", passed, fail)
    _require_schema(
        command_results,
        "modules_run_once_cron_mirror_dry_run",
        "memory-os.cron_mirror_report.v0",
        passed,
        fail,
    )
    _require_json_field(
        command_results,
        "modules_run_once_cron_mirror_dry_run",
        ("dry_run",),
        True,
        "modules_run_once_not_dry_run",
        passed,
        fail,
    )
    _require_schema(command_results, "modules_validate_no_send", "memory-os.modules_no_send_validation.v0", passed, fail)
    _require_false_boundaries(command_results, "modules_validate_no_send", passed, fail)
    _require_schema(command_results, "low_clue_recall", "memory-os.low_clue_recall.v0", passed, fail)
    _require_false_boundaries(command_results, "low_clue_recall", passed, fail)
    _require_schema(command_results, "memory_sources_stats", "memory-os.memory_sources_stats.v0", passed, fail)
    _require_json_field(command_results, "memory_sources_stats", ("boundary_true_count",), 0, "memory_sources_boundary_true", passed, fail)
    _require_no_forbidden_fields(command_results, "memory_sources_stats", passed, fail)

    return {"pass": _dedupe(passed), "warn": _dedupe(warn), "fail": _dedupe(fail)}


def render_summary(report: dict[str, Any]) -> str:
    classification = report["classification"]
    lines = [
        f"Memory-OS Hermes upgrade compatibility: {'FAIL' if classification['fail'] else 'PASS'}",
        f"- host={report.get('host')} hermes_home={report.get('hermes_home') or '(default)'}",
    ]
    for name, result in report["commands"].items():
        status = "ok" if result.get("exit_code") == 0 else f"exit={result.get('exit_code')}"
        schema = result.get("json", {}).get("schema_version") if isinstance(result.get("json"), dict) else ""
        if schema:
            lines.append(f"- {name}: {status} schema={schema}")
        else:
            preview = str(result.get("stdout_preview") or result.get("stderr_preview") or "").splitlines()
            suffix = f" {preview[0]}" if preview else ""
            lines.append(f"- {name}: {status}{suffix}")
    lines.append(f"PASS: {[item['code'] for item in classification['pass']]}")
    lines.append(f"WARN: {[item['code'] for item in classification['warn']]}")
    lines.append(f"FAIL: {[item['code'] for item in classification['fail']]}")
    return "\n".join(lines)


def _run_spec(
    spec: CommandSpec,
    *,
    host: str | None,
    hermes_home: str | None,
    timeout: int,
    run_command: RunCommand,
) -> dict[str, Any]:
    try:
        raw = run_command(spec.argv, host, hermes_home, timeout)
    except subprocess.TimeoutExpired as exc:
        raw = {"exit_code": 124, "stdout": exc.stdout or "", "stderr": exc.stderr or "timeout"}
    except FileNotFoundError as exc:
        raw = {"exit_code": 127, "stdout": "", "stderr": str(exc)}
    stdout = str(raw.get("stdout", ""))
    stderr = str(raw.get("stderr", ""))
    result = {
        "command": list(spec.argv),
        "required": spec.required,
        "exit_code": int(raw.get("exit_code", 1)),
        "stdout_preview": _preview(stdout),
        "stderr_preview": _preview(stderr),
    }
    if spec.json_output and result["exit_code"] == 0:
        result["json"] = _parse_json(stdout)
        if result["json"] is None:
            result["json_parse_error"] = True
    return result


def _parse_json(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _classify_command_exit(
    results: dict[str, dict[str, Any]],
    passed: list[dict[str, Any]],
    warn: list[dict[str, Any]],
    fail: list[dict[str, Any]],
) -> None:
    for spec in COMMANDS:
        result = results.get(spec.name, {})
        if int(result.get("exit_code", 1)) == 0:
            passed.append({"code": f"{spec.name}_command_ok"})
            if spec.json_output and result.get("json") is None:
                fail.append({"code": f"{spec.name}_json_invalid"})
        elif spec.required:
            fail.append({"code": f"{spec.name}_command_failed", "exit_code": result.get("exit_code")})
        else:
            warn.append({"code": f"{spec.name}_unavailable", "exit_code": result.get("exit_code")})


def _require_memory_provider(results: dict[str, dict[str, Any]], passed: list[dict[str, Any]], fail: list[dict[str, Any]]) -> None:
    result = results.get("memory_provider", {})
    if int(result.get("exit_code", 1)) != 0:
        return
    output = f"{result.get('stdout_preview', '')}\n{result.get('stderr_preview', '')}"
    if "memory_os" in output and ("active" in output.lower() or "Provider:" in output):
        passed.append({"code": "memory_provider_active"})
    else:
        fail.append({"code": "memory_provider_not_memory_os"})


def _require_schema(
    results: dict[str, dict[str, Any]],
    name: str,
    expected_schema: str,
    passed: list[dict[str, Any]],
    fail: list[dict[str, Any]],
) -> None:
    data = results.get(name, {}).get("json")
    if isinstance(data, dict) and data.get("schema_version") == expected_schema:
        passed.append({"code": f"{name}_schema_ok"})
    else:
        fail.append({"code": f"{name}_schema_mismatch", "expected": expected_schema})


def _require_doctor_ok(
    results: dict[str, dict[str, Any]],
    name: str,
    passed: list[dict[str, Any]],
    fail: list[dict[str, Any]],
) -> None:
    data = results.get(name, {}).get("json")
    if not isinstance(data, dict):
        fail.append({"code": f"{name}_missing_json"})
        return
    error_findings = [
        finding for finding in data.get("findings", []) or []
        if isinstance(finding, dict) and finding.get("severity") == "error"
    ]
    if data.get("status") in {"ok", "warning"} and not error_findings:
        passed.append({"code": f"{name}_no_error_findings"})
    else:
        fail.append({"code": f"{name}_has_error_findings"})


def _require_hindsight_status(
    results: dict[str, dict[str, Any]],
    passed: list[dict[str, Any]],
    fail: list[dict[str, Any]],
) -> None:
    data = results.get("hindsight_status", {}).get("json")
    if not isinstance(data, dict):
        fail.append({"code": "hindsight_status_missing_json"})
        return
    if data.get("schema_version") != "memory-os.hindsight_substrate_status.v0":
        fail.append({"code": "hindsight_status_schema_mismatch"})
        return
    _classify_hindsight_status_payload(data, passed, fail)


def _classify_hindsight_status_payload(
    data: dict[str, Any],
    passed: list[dict[str, Any]],
    fail: list[dict[str, Any]],
) -> None:
    if data.get("enabled") is False and data.get("status") == "optional_not_configured":
        passed.append({"code": "hindsight_optional_off_ok"})
        return
    if data.get("enabled") is True and data.get("recall_mode") in {"shadow", "active", "off"}:
        provider_bank_id = str(data.get("provider_bank_id") or "")
        bank_id = str(data.get("bank_id") or "")
        if data.get("adoption_source") == "hermes_hindsight_config":
            if not provider_bank_id:
                fail.append({"code": "hindsight_provider_bank_evidence_missing"})
            elif bank_id != provider_bank_id:
                fail.append(
                    {
                        "code": "hindsight_provider_bank_mismatch",
                        "bank_id": bank_id,
                        "provider_bank_id": provider_bank_id,
                    }
                )
            elif str(data.get("bank_selection_reason") or "") == "ambiguous_provider_bank":
                fail.append({"code": "hindsight_provider_bank_selection_ambiguous"})
            else:
                passed.append(
                    {
                        "code": "hindsight_provider_bank_selected",
                        "bank_selection_reason": data.get("bank_selection_reason"),
                        "non_provider_configured_bank_count": data.get("non_provider_configured_bank_count"),
                    }
                )
        monitor = data.get("substrate_monitor") if isinstance(data.get("substrate_monitor"), dict) else {}
        if int(monitor.get("raw_retained_count") or 0) > 0 or monitor.get("no_raw_retained") is False:
            fail.append({"code": "hindsight_raw_retain_detected"})
        if int(monitor.get("projection_stale_count") or 0) > 0:
            fail.append({"code": "hindsight_projection_stale"})
        if monitor.get("local_first_authority_preserved") is False or int(
            monitor.get("external_authoritative_count") or 0
        ) > 0:
            fail.append({"code": "hindsight_overrode_local_authority"})
        if not [item for item in fail if str(item.get("code", "")).startswith("hindsight_")]:
            passed.append({"code": "hindsight_configured_ok"})
        return
    fail.append({"code": "hindsight_status_invalid", "status": data.get("status")})


def _require_false_boundaries(
    results: dict[str, dict[str, Any]],
    name: str,
    passed: list[dict[str, Any]],
    fail: list[dict[str, Any]],
) -> None:
    data = results.get(name, {}).get("json")
    boundaries = data.get("boundaries", data) if isinstance(data, dict) else {}
    true_keys = [
        key for key in (
            "actual_send",
            "actual_execute",
            "actual_identity_write",
            "actual_relationship_write",
            "actual_crystallized_approval",
            "hindsight_exported",
        )
        if boundaries.get(key) is True
    ]
    if true_keys:
        fail.append({"code": f"{name}_boundary_true", "keys": true_keys})
    else:
        passed.append({"code": f"{name}_boundaries_false"})


def _require_json_field(
    results: dict[str, dict[str, Any]],
    name: str,
    path: tuple[str, ...],
    expected: Any,
    failure_code: str,
    passed: list[dict[str, Any]],
    fail: list[dict[str, Any]],
) -> None:
    data = results.get(name, {}).get("json")
    value: Any = data
    for key in path:
        value = value.get(key) if isinstance(value, dict) else None
    if value == expected:
        passed.append({"code": f"{name}_{'_'.join(path)}_ok"})
    else:
        fail.append({"code": failure_code, "value": value})


def _require_no_forbidden_fields(
    results: dict[str, dict[str, Any]],
    name: str,
    passed: list[dict[str, Any]],
    fail: list[dict[str, Any]],
) -> None:
    data = results.get(name, {}).get("json")
    findings = data.get("forbidden_field_findings", []) if isinstance(data, dict) else []
    if findings:
        fail.append({"code": f"{name}_forbidden_fields", "count": len(findings)})
    else:
        passed.append({"code": f"{name}_forbidden_fields_ok"})


def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        code = str(item.get("code", ""))
        if code in seen:
            continue
        seen.add(code)
        result.append(item)
    return result


def _preview(text: str) -> str:
    if len(text) <= PREVIEW_LIMIT:
        return text.strip()
    return text[:PREVIEW_LIMIT].strip() + "...[truncated]"


if __name__ == "__main__":
    raise SystemExit(main())
