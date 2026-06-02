#!/usr/bin/env python3
"""ExecutionGate wrapper for Memory-OS-owned Hermes cron helpers."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "memory-os.execution_gate_envelope.v0"
HELPER_REPORT_SCHEMA_VERSION = "memory-os.helper_execution_report.v0"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a Memory-OS cron helper behind ExecutionGate.")
    parser.add_argument("--registry-key", required=True)
    parser.add_argument("--hermes-home", default=os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
    parser.add_argument("--smoke-mode", choices=("normal", "safe", "render-only", "natural"), default="normal")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run_registry_key(
        str(args.registry_key),
        hermes_home=Path(args.hermes_home).expanduser(),
        smoke_mode=str(args.smoke_mode),
    )


def run_registry_key(registry_key: str, *, hermes_home: Path, smoke_mode: str = "normal") -> int:
    spec = _load_spec(hermes_home, registry_key)
    if not spec:
        sys.stderr.write(f"unknown Memory-OS cron registry key: {registry_key}\n")
        return 2
    scripts_dir = Path(__file__).resolve().parent
    helper = scripts_dir / spec["raw_script"]
    boundary = {
        "actual_send": False,
        "actual_execute": False,
        "actual_identity_write": False,
        "actual_unapproved_crystallized_approval": False,
    }
    permit = _append_permit(
        hermes_home=hermes_home,
        registry_key=registry_key,
        lane_id=spec["lane_id"],
        risk_class=spec["risk_class"],
        raw_script=spec["raw_script"],
        helper_present=helper.is_file(),
        smoke_mode=smoke_mode,
        boundary=boundary,
    )
    if permit["permit_decision"] != "allowed":
        return 2
    if not helper.is_file():
        _append_completion(
            hermes_home=hermes_home,
            envelope_id=permit["execution_gate_envelope_id"],
            lane_id=spec["lane_id"],
            execution_status="helper_missing",
            returncode=2,
            smoke_mode=smoke_mode,
            boundary=boundary,
            helper_report={},
        )
        sys.stderr.write(f"Memory-OS cron helper missing: {helper.name}\n")
        return 2
    report_path = _helper_report_path(hermes_home, str(permit["execution_gate_envelope_id"]))
    env = {
        **os.environ,
        "HERMES_HOME": str(hermes_home),
        "MEMORY_OS_EXECUTION_GATE_ENVELOPE_ID": str(permit["execution_gate_envelope_id"]),
        "MEMORY_OS_EXECUTION_REPORT_PATH": str(report_path),
        "MEMORY_OS_EXECUTION_SMOKE_MODE": smoke_mode,
    }
    completed = subprocess.run(
        [sys.executable, str(helper)],
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )
    helper_report = _read_helper_report(report_path, completed.stdout)
    observed_boundary = helper_report.get("boundary") if isinstance(helper_report.get("boundary"), dict) else boundary
    _append_completion(
        hermes_home=hermes_home,
        envelope_id=permit["execution_gate_envelope_id"],
        lane_id=spec["lane_id"],
        execution_status="ok" if completed.returncode == 0 else "error",
        returncode=completed.returncode,
        smoke_mode=smoke_mode,
        boundary=observed_boundary,
        helper_report=helper_report,
    )
    if completed.stdout:
        sys.stdout.write(completed.stdout)
    if completed.stderr:
        sys.stderr.write(completed.stderr)
    return completed.returncode


def _load_spec(hermes_home: Path, registry_key: str) -> dict[str, Any] | None:
    snapshot_path = hermes_home / "memory-os" / "system" / "memory_os_cron_registry.json"
    if snapshot_path.exists():
        try:
            loaded = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            loaded = {}
        for item in loaded.get("specs", []) if isinstance(loaded.get("specs"), list) else []:
            if isinstance(item, dict) and str(item.get("key") or "") == registry_key:
                return _runner_spec_from_registry_item(item)
    try:
        from plugins.memory.memory_os.cron_registry import memory_os_cron_spec_by_key

        spec = memory_os_cron_spec_by_key(registry_key)
        return _runner_spec_from_registry_item(spec.to_json()) if spec else None
    except Exception:
        return None


def _runner_spec_from_registry_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "raw_script": str(item.get("raw_script") or ""),
        "lane_id": str(item.get("lane_id") or ""),
        "risk_class": str(item.get("helper_kind") or "local_helper"),
        "requires_boundary_report": bool(item.get("requires_boundary_report")),
    }


def _append_permit(
    *,
    hermes_home: Path,
    registry_key: str,
    lane_id: str,
    risk_class: str,
    raw_script: str,
    helper_present: bool,
    smoke_mode: str,
    boundary: dict[str, Any],
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    material = f"{registry_key}|{lane_id}|{now.isoformat()}"
    envelope_id = f"xgate_{now.strftime('%Y%m%dT%H%M%S%fZ')}_{hashlib.sha256(material.encode('utf-8')).hexdigest()[:10]}"
    boundary_true = _any_boundary_true(boundary)
    record = {
        "schema_version": SCHEMA_VERSION,
        "stage": "permit",
        "execution_gate_envelope_id": envelope_id,
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "profile": os.environ.get("HERMES_PROFILE") or "default",
        "lane_id": lane_id,
        "trigger_surface": "hermes_cron",
        "risk_class": risk_class,
        "human_approval_required": False,
        "why_no_human_approval": "Memory-OS-owned cron helper render/report lane; no external send is performed by the helper",
        "scope": {
            "registry_key": registry_key,
            "raw_script": raw_script,
            "helper_present": helper_present,
            "smoke_mode": smoke_mode,
        },
        "boundary": boundary,
        "boundary_true": boundary_true,
        "precheck": {"helper_present": helper_present},
        "permit_decision": "blocked" if boundary_true else "allowed",
        "permit_reason": "boundary_true" if boundary_true else "boundary_false",
    }
    _append_jsonl(_records_path(hermes_home), record)
    return record


def _append_completion(
    *,
    hermes_home: Path,
    envelope_id: str,
    lane_id: str,
    execution_status: str,
    returncode: int,
    smoke_mode: str,
    boundary: dict[str, Any],
    helper_report: dict[str, Any],
) -> None:
    now = datetime.now(timezone.utc)
    observed = helper_report.get("schema_version") == HELPER_REPORT_SCHEMA_VERSION
    _append_jsonl(
        _records_path(hermes_home),
        {
            "schema_version": SCHEMA_VERSION,
            "stage": "completion",
            "execution_gate_envelope_id": envelope_id,
            "created_at": now.isoformat().replace("+00:00", "Z"),
            "profile": os.environ.get("HERMES_PROFILE") or "default",
            "lane_id": lane_id,
            "execution_status": execution_status,
            "postcheck": {
                "returncode": returncode,
                "boundary": boundary,
                "postcheck_boundary_observed": observed,
                "helper_report_schema_version": str(helper_report.get("schema_version") or ""),
                "smoke_mode": smoke_mode,
            },
            "postcheck_boundary_true": _any_boundary_true(boundary),
            "result_summary": {
                "returncode": returncode,
                **(
                    helper_report.get("result_summary")
                    if isinstance(helper_report.get("result_summary"), dict)
                    else {}
                ),
            },
        },
    )


def _records_path(hermes_home: Path) -> Path:
    return hermes_home / "memory-os" / "system" / "execution_gate_envelopes.jsonl"


def _helper_report_path(hermes_home: Path, envelope_id: str) -> Path:
    return hermes_home / "memory-os" / "system" / "execution_gate" / "helper_reports" / f"{envelope_id}.json"


def _read_helper_report(path: Path, stdout: str) -> dict[str, Any]:
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            loaded = {}
        if isinstance(loaded, dict) and loaded.get("schema_version") == HELPER_REPORT_SCHEMA_VERSION:
            return loaded
    stripped = (stdout or "").strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            loaded = json.loads(stripped)
        except json.JSONDecodeError:
            loaded = {}
        if isinstance(loaded, dict) and loaded.get("schema_version") == HELPER_REPORT_SCHEMA_VERSION:
            return loaded
    return {}


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _any_boundary_true(value: Any) -> bool:
    if isinstance(value, bool):
        return value is True
    if isinstance(value, dict):
        return any(_any_boundary_true(item) for item in value.values())
    if isinstance(value, list):
        return any(_any_boundary_true(item) for item in value)
    return False


if __name__ == "__main__":
    raise SystemExit(main())
