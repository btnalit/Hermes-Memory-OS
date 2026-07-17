#!/usr/bin/env python3
"""Fast read-only boundary and runtime gate probe for Memory-OS."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from plugins.memory.memory_os.execution_gate import read_execution_gate_records
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.structural_write_gate import structural_write_gate_status
from scripts.memory_os_host_profile import resolve_host_runtime_profile


SCHEMA_VERSION = "memory-os.boundary_runtime_probe.v0"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Probe Memory-OS high-risk boundary counters and runtime gate health.")
    parser.add_argument("--host", default="", help="SSH host alias for running this probe on a deployed target.")
    parser.add_argument("--remote-repo-root", default="")
    parser.add_argument("--python-bin", default="python3")
    parser.add_argument("--hermes-home", default="/root/.hermes")
    parser.add_argument("--profile", default="")
    parser.add_argument("--output", choices=("json",), default="json")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        host_profile = resolve_host_runtime_profile(
            host=str(args.host),
            remote_repo_root=str(args.remote_repo_root),
            hermes_home=str(args.hermes_home),
            python_bin=str(args.python_bin),
        )
    except ValueError as exc:
        parser.error(str(exc))
    if args.host:
        return run_remote_probe(
            remote_probe_command(
                host=str(args.host),
                remote_repo_root=host_profile.remote_repo_root,
                hermes_home=host_profile.hermes_home,
                profile=str(args.profile or ""),
                python_bin=host_profile.python_bin,
            )
        )
    report = probe_boundary_runtime(
        hermes_home=Path(args.hermes_home).expanduser(),
        profile=str(args.profile or ""),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.get("status") in {"ok", "warning"} else 1


def remote_probe_command(
    *,
    host: str,
    remote_repo_root: str,
    hermes_home: str,
    profile: str,
    python_bin: str,
) -> list[str]:
    script = Path(remote_repo_root) / "scripts" / "memory_os_boundary_runtime_probe.py"
    remote_argv = [
        python_bin,
        str(script).replace("\\", "/"),
        "--hermes-home",
        hermes_home,
        "--output",
        "json",
    ]
    if profile:
        remote_argv.extend(["--profile", profile])
    return ["ssh", host, shlex.join(remote_argv)]


def run_remote_probe(command: list[str]) -> int:
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, file=sys.stderr, end="")
    return completed.returncode


def probe_boundary_runtime(*, hermes_home: Path, profile: str = "") -> dict[str, Any]:
    roots = MemoryOSRoots.from_hermes_home(hermes_home, profile=profile or None)
    owner_actions = _read_jsonl(roots.memory_os_root / "system" / "owner_actions.jsonl")
    curation_decisions = _read_jsonl(roots.memory_os_root / "system" / "hindsight_curation_decisions.jsonl")
    reversible_labels = _read_jsonl(roots.hermes_home / "system-modules" / "reversible_labels" / "labels.jsonl")
    gate = _execution_gate_fast_summary(roots)
    structural = structural_write_gate_status()
    counters = _boundary_counters(
        owner_actions=owner_actions,
        curation_decisions=curation_decisions,
        reversible_labels=reversible_labels,
        gate=gate,
    )
    findings = _findings(counters=counters, gate=gate, structural=structural)
    status = "fail" if any(item["severity"] == "fail" for item in findings) else "warning" if findings else "ok"
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "hermes_home": str(roots.hermes_home),
        "profile": roots.profile or "default",
        "permanent_boundary_counters": counters,
        "execution_gate": gate,
        "structural_write_gate": structural,
        "findings": findings,
    }


def _boundary_counters(
    *,
    owner_actions: list[dict[str, Any]],
    curation_decisions: list[dict[str, Any]],
    reversible_labels: list[dict[str, Any]],
    gate: dict[str, Any],
) -> dict[str, int]:
    return {
        "unapproved_or_automatic_crystallized_write_count": sum(
            1 for record in owner_actions if _truthy_path(record, "boundary", "actual_unapproved_crystallized_approval")
        ),
        "owner_approved_crystallized_write_count": sum(
            1 for record in owner_actions if _truthy_path(record, "owner_effect", "owner_approved_crystallized_write")
        ),
        "actual_hindsight_write_count": sum(1 for record in curation_decisions if bool(record.get("actual_hindsight_write"))),
        "actual_hindsight_delete_count": sum(1 for record in curation_decisions if bool(record.get("actual_hindsight_delete"))),
        "actual_hindsight_demote_count": sum(1 for record in curation_decisions if bool(record.get("actual_hindsight_demote"))),
        "actual_route_score_write_count": sum(
            1
            for record in [*curation_decisions, *reversible_labels]
            if bool(record.get("actual_route_score_write"))
            or _truthy_path(record, "boundary", "actual_route_score_write")
        ),
        "actual_identity_relationship_write_count": sum(
            1
            for record in owner_actions
            if _truthy_path(record, "boundary", "actual_identity_write")
            or _truthy_path(record, "boundary", "actual_relationship_write")
        ),
        "actual_external_send_count": sum(
            1
            for record in [*owner_actions, *curation_decisions]
            if bool(record.get("actual_send")) or _truthy_path(record, "boundary", "actual_send")
        ),
        "unbounded_autonomous_action_count": sum(
            1 for record in owner_actions if _truthy_path(record, "boundary", "unbounded_autonomous_action")
        ),
        "execution_gate_permit_boundary_true_count": int(gate.get("permit_boundary_true_count") or 0),
        "execution_gate_completion_boundary_true_count": int(gate.get("completion_postcheck_boundary_true_count") or 0),
    }


def _execution_gate_fast_summary(roots: MemoryOSRoots) -> dict[str, Any]:
    records = read_execution_gate_records(roots, limit=5000)
    permits = [record for record in records if record.get("stage") == "permit"]
    completions = [record for record in records if record.get("stage") == "completion"]
    latest_permit = permits[-1] if permits else {}
    latest_completion = completions[-1] if completions else {}
    return {
        "schema_version": "memory-os.execution_gate_fast_summary.v0",
        "record_count": len(records),
        "permit_count": len(permits),
        "completion_count": len(completions),
        "permit_boundary_true_count": sum(
            1 for record in permits if record.get("boundary_true") is True or _any_true(record.get("boundary"))
        ),
        "completion_postcheck_boundary_true_count": sum(
            1 for record in completions if _postcheck_boundary_true(record)
        ),
        "latest_envelope_id": str(latest_permit.get("execution_gate_envelope_id") or ""),
        "latest_lane_id": str(latest_permit.get("lane_id") or ""),
        "latest_permit_decision": str(latest_permit.get("permit_decision") or ""),
        "latest_completion_lane_id": str(latest_completion.get("lane_id") or ""),
        "latest_completion_status": str(latest_completion.get("execution_status") or ""),
    }


def _findings(*, counters: dict[str, int], gate: dict[str, Any], structural: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    fail_keys = {
        "unapproved_or_automatic_crystallized_write_count",
        "actual_hindsight_write_count",
        "actual_hindsight_delete_count",
        "actual_hindsight_demote_count",
        "actual_route_score_write_count",
        "actual_identity_relationship_write_count",
        "actual_external_send_count",
        "unbounded_autonomous_action_count",
        "execution_gate_permit_boundary_true_count",
        "execution_gate_completion_boundary_true_count",
    }
    for key in sorted(fail_keys):
        value = int(counters.get(key) or 0)
        if value > 0:
            findings.append({"severity": "fail", "code": f"boundary_counter_nonzero:{key}", "value": value})
    if structural.get("status") != "available" or structural.get("append_governed_jsonl_available") is not True:
        findings.append({"severity": "fail", "code": "structural_write_gate_unavailable"})
    if int(gate.get("permit_count") or 0) == 0:
        findings.append({"severity": "warn", "code": "execution_gate_permit_records_missing"})
    if int(gate.get("completion_count") or 0) == 0:
        findings.append({"severity": "warn", "code": "execution_gate_completion_records_missing"})
    return findings


def _truthy_path(record: dict[str, Any], *keys: str) -> bool:
    value: Any = record
    for key in keys:
        if not isinstance(value, dict):
            return False
        value = value.get(key)
    return value is True


def _any_true(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, dict):
        return any(_any_true(item) for item in value.values())
    if isinstance(value, list):
        return any(_any_true(item) for item in value)
    return False


_BOUNDARY_KEYS = {
    "actual_send",
    "actual_execute",
    "actual_identity_write",
    "actual_relationship_write",
    "actual_unapproved_crystallized_approval",
    "actual_crystallized_approval",
    "actual_policy_write",
    "actual_route_score_write",
    "actual_hindsight_write",
    "actual_hindsight_delete",
    "actual_hindsight_demote",
    "hindsight_write",
    "hindsight_delete",
    "hindsight_demote",
    "unbounded_autonomous_action",
}


def _provisional_write_exempt(postcheck: dict[str, Any]) -> bool:
    """P1-1: historical-shape exemption for legacy provisional-write postchecks.

    Before the P1-1 fix, `provisional_write_postcheck()` in
    candidate_aggregation.py returned a bare `actual_crystallized_approval:
    True` for every bounded, reversible provisional crystallized write
    (permanence was always separately False). That is not a boundary
    violation -- it is evidence of a legitimate, ExecutionGate-wrapped
    provisional write -- but records already written to disk in that old
    shape must not start FAILing once `_postcheck_boundary_true` is fixed
    for new records.

    Exempt ONLY when there is no permanent approval recorded alongside it
    AND provisional evidence is present. A record with
    actual_permanent_crystallized_approval=True is NEVER exempt -- permanent
    crystallization completing through an automatic postcheck remains a
    real violation.
    """
    if postcheck.get("actual_permanent_crystallized_approval") is True:
        return False
    if postcheck.get("actual_provisional_crystallized_write") is True:
        return True
    try:
        if int(postcheck.get("provisional_crystallized_write_count") or 0) >= 1:
            return True
    except (TypeError, ValueError):
        pass
    return postcheck.get("crystallized_write") == "provisional_success"


def _postcheck_boundary_true(record: dict[str, Any]) -> bool:
    postcheck = record.get("postcheck")
    if not isinstance(postcheck, dict):
        return record.get("postcheck_boundary_true") is True
    if _any_true(postcheck.get("boundary")) or _any_true(postcheck.get("boundaries")):
        return True
    for key in _BOUNDARY_KEYS:
        if postcheck.get(key) is not True:
            continue
        if key == "actual_crystallized_approval" and _provisional_write_exempt(postcheck):
            continue
        return True
    return False


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                records.append(item)
    except OSError:
        return []
    return records


if __name__ == "__main__":
    raise SystemExit(main())
