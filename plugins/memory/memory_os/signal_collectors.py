"""Read-only signal collectors for Memory-OS left-brain projection."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .execution_gate import execution_gate_records_path
from .owner_actions import owner_actions_path
from .roots import MemoryOSRoots
from .session_mirror import session_mirror_apply_records_path
from .signal_source_registry import (
    SignalSourceSpec,
    evaluate_signal_source_requirements,
    signal_source_specs,
)


SIGNAL_COLLECTION_SCHEMA_VERSION = "memory-os.signal_collection.v0"
FORBIDDEN_PAYLOAD_KEYS = {"raw_body", "body", "content", "transcript", "private_body", "raw_transcript"}


def collect_signal_sources(
    roots: MemoryOSRoots,
    *,
    host_capabilities: dict[str, Any],
    trigger_type: str,
    execution_envelope_id: str = "",
    manual_run_ref: str = "",
    collector_overrides: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    specs = signal_source_specs()
    requirement_report = evaluate_signal_source_requirements(specs, host_capabilities)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    records: list[dict[str, Any]] = []
    overrides = collector_overrides or {}
    for spec in specs:
        payload = dict(overrides[spec.source_key]) if spec.source_key in overrides else _collect_payload(roots, spec, host_capabilities)
        violation = _payload_schema_violation(spec, payload)
        source_hash = _source_hash(spec.source_key, payload)
        record = {
            "schema_version": "memory-os.signal_record.v0",
            "created_at": now,
            "host_id": str(host_capabilities.get("host_id") or ""),
            "hermes_home_ref": str(host_capabilities.get("hermes_home_ref") or roots.hermes_home),
            "profile_id": roots.profile or "default",
            "source_key": spec.source_key,
            "payload_schema": spec.payload_schema,
            "projection_policy": "metadata_only",
            "retention_class": spec.retention_class,
            "allowed_outputs": list(spec.allowed_outputs),
            "trigger_type": str(trigger_type or ""),
            "execution_envelope_id": str(execution_envelope_id or ""),
            "manual_run_ref": str(manual_run_ref or ""),
            "payload": payload if not violation else {},
            "payload_schema_violation": violation,
            "status": "blocked" if violation else str(payload.get("status") or "ok"),
            "source_hash": source_hash,
            "raw_body_included": False,
            "boundary": _false_boundary(),
        }
        records.append(record)
    violation_count = sum(1 for record in records if record["payload_schema_violation"])
    return {
        "schema_version": SIGNAL_COLLECTION_SCHEMA_VERSION,
        "created_at": now,
        "status": "error" if violation_count else ("warning" if requirement_report["required_missing_count"] else "ok"),
        "host_id": str(host_capabilities.get("host_id") or ""),
        "profile_id": roots.profile or "default",
        "trigger_type": str(trigger_type or ""),
        "execution_envelope_id": str(execution_envelope_id or ""),
        "manual_run_ref": str(manual_run_ref or ""),
        "record_count": len(records),
        "payload_schema_violation_count": violation_count,
        "required_missing_count": int(requirement_report.get("required_missing_count") or 0),
        "records": records,
        "raw_body_included": False,
        "boundary": _false_boundary(),
    }


def _collect_payload(roots: MemoryOSRoots, spec: SignalSourceSpec, host_capabilities: dict[str, Any]) -> dict[str, Any]:
    capability = _capability(host_capabilities, spec.host_capability_key)
    base = {
        "status": "ok" if _present(capability) else "missing",
        "capability_status": str(capability.get("status") or "missing"),
        "available": _present(capability),
        "freshness_seconds": capability.get("freshness_seconds"),
        "record_count": 0,
        "latest_status": "",
        "boundary_true_count": 0,
        "raw_body_included": False,
    }
    if spec.source_key == "execution_gate_envelopes":
        records = _read_jsonl(execution_gate_records_path(roots))
        return {
            **base,
            "status": "ok" if records else base["status"],
            "record_count": len(records),
            "latest_status": str(records[-1].get("permit_decision") or records[-1].get("execution_status") or "")
            if records
            else "",
            "boundary_true_count": sum(1 for item in records if item.get("boundary_true") is True or item.get("postcheck_boundary_true") is True),
        }
    if spec.source_key == "session_mirror_apply":
        records = _read_jsonl(session_mirror_apply_records_path(roots))
        return {
            **base,
            "status": "ok" if records else base["status"],
            "record_count": len(records),
            "apply_count": len(records),
            "latest_apply_status": str(records[-1].get("status") or "") if records else "",
            "latest_status": str(records[-1].get("status") or "") if records else "",
            "boundary_true_count": sum(1 for item in records if _any_true(item.get("boundary"))),
        }
    if spec.source_key == "owner_actions":
        records = _read_jsonl(owner_actions_path(roots))
        return {
            **base,
            "status": "ok" if records else base["status"],
            "record_count": len(records),
            "owner_action_count": len(records),
            "action_required_count": 0,
            "latest_status": str(records[-1].get("result") or "") if records else "",
        }
    if spec.source_key == "hermes_cron_jobs":
        jobs = _safe_jobs(roots.hermes_home / "cron" / "jobs.json")
        return {
            **base,
            "status": "ok" if jobs else base["status"],
            "record_count": len(jobs),
            "expected_count": 7,
            "wrapped_count": sum(1 for job in jobs if str(job.get("script") or "").startswith("memory_os_cron_")),
        }
    if spec.source_key == "memory_sources_feedback":
        path = roots.memory_os_root / "system" / "memory_sources_feedback.jsonl"
        records = _read_jsonl(path)
        return {**base, "status": "ok" if records else base["status"], "record_count": len(records), "feedback_count": len(records)}
    if spec.source_key == "runtime_logs":
        log_dir = roots.hermes_home / "logs"
        files = [item for item in log_dir.glob("*") if item.is_file()] if log_dir.exists() else []
        return {**base, "status": "ok" if files else base["status"], "record_count": len(files), "log_file_count": len(files)}
    if spec.source_key == "skills_inventory":
        path = roots.hermes_home / "skills"
        count = len([item for item in path.glob("*") if item.is_dir()]) if path.exists() else 0
        return {**base, "status": "ok" if count else base["status"], "record_count": count, "skill_count": count}
    if spec.source_key == "mcp_server_health":
        paths = [roots.hermes_home / "mcp", roots.hermes_home / "mcp_servers.json", roots.hermes_home / "config" / "mcp.json"]
        present = [path for path in paths if path.exists()]
        return {**base, "status": "ok" if present else base["status"], "record_count": len(present), "server_count": len(present), "healthy_count": 0}
    if spec.source_key == "wandering_mind_state":
        path = roots.hermes_home / "system-modules" / "wandering_mind"
        files = list(path.glob("*")) if path.exists() else []
        return {**base, "status": "ok" if files else base["status"], "record_count": len(files), "journal_count": len(files)}
    if spec.source_key == "hindsight_provider_stats":
        paths = [roots.hermes_home / "hindsight" / "config.json", roots.memory_os_root / "system" / "substrate_operations.jsonl"]
        present = [path for path in paths if path.exists()]
        return {**base, "status": "ok" if present else base["status"], "record_count": len(present), "retain_count": 0, "recall_count": 0, "pollution_indicator_count": 0}
    if spec.source_key == "profile_config":
        return {**base, "profile_id": roots.profile or "default"}
    if spec.source_key == "kanban_state":
        path = roots.hermes_home / "kanban"
        files = list(path.glob("*")) if path.exists() else []
        return {**base, "status": "ok" if files else base["status"], "record_count": len(files), "card_count": len(files)}
    if spec.source_key == "tool_registry":
        path = roots.hermes_home / "tools"
        files = list(path.glob("*")) if path.exists() else []
        return {**base, "status": "ok" if files else base["status"], "record_count": len(files), "tool_count": len(files)}
    return base


def _payload_schema_violation(spec: SignalSourceSpec, payload: dict[str, Any]) -> bool:
    allowed = set(spec.allowed_payload_fields)
    keys = set(payload)
    if keys & FORBIDDEN_PAYLOAD_KEYS:
        return True
    return bool(keys - allowed)


def _capability(host_capabilities: dict[str, Any], key: str) -> dict[str, Any]:
    capabilities = host_capabilities.get("capabilities") if isinstance(host_capabilities.get("capabilities"), dict) else {}
    value = capabilities.get(key) if isinstance(capabilities, dict) else {}
    return value if isinstance(value, dict) else {}


def _present(capability: dict[str, Any]) -> bool:
    return str(capability.get("status") or "") in {"present", "configured", "running", "ok", "healthy"}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            records.append(parsed)
    return records


def _safe_jobs(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    jobs = loaded.get("jobs", loaded) if isinstance(loaded, dict) else loaded
    return [item for item in jobs if isinstance(item, dict)] if isinstance(jobs, list) else []


def _source_hash(source_key: str, payload: dict[str, Any]) -> str:
    material = json.dumps({"source_key": source_key, "payload": payload}, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _any_true(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, dict):
        return any(_any_true(item) for item in value.values())
    if isinstance(value, list):
        return any(_any_true(item) for item in value)
    return False


def _false_boundary() -> dict[str, bool]:
    return {
        "actual_send": False,
        "actual_execute": False,
        "actual_identity_write": False,
        "actual_relationship_write": False,
        "actual_crystallized_approval": False,
        "actual_policy_write": False,
        "actual_route_score_write": False,
        "hindsight_write": False,
    }
