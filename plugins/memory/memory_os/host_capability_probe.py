"""Read-only host capability probe for Memory-OS signal weaving."""

from __future__ import annotations

import hashlib
import json
import platform
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import load_config
from .cron_registry import memory_os_cron_specs
from .deployment_runtime_manifest import read_deployment_runtime_manifest
from .execution_gate import execution_gate_records_path, execution_gate_summary
from .hermes_cron_adapter import HermesCronAdapter
from .owner_actions import resolve_owner_review_channel
from .roots import MemoryOSRoots
from .store import MemoryOSStore


HOST_CAPABILITY_PROBE_SCHEMA_VERSION = "memory-os.host_capability_probe.v2"
HOST_CAPABILITY_ALLOWED_STATUSES = {"available", "missing", "disabled", "unknown", "migration_needed"}
HOST_CAPABILITY_REQUIRED_FIELDS = {
    "capability_key",
    "owner_system",
    "status",
    "probe_method",
    "confidence",
    "source_scope_ref",
    "observed_at",
    "freshness_status",
    "adapter_required",
    "migration_hint",
}
HOST_CAPABILITY_REQUIRED_KEYS = {
    "deployment_runtime_manifest",
    "hermes_version",
    "hermes_home_schema",
    "profile_layout",
    "active_runtime",
    "memory_os_plugin",
    "cron",
    "owner_channel",
    "memory_provider",
    "hindsight",
    "hindsight_write_origin",
    "mailbox",
    "wandering_mind",
    "skills",
    "tools",
    "mcp",
    "gateway",
    "logs",
    "execution_gate",
    "structural_write_gate",
}

_CAPABILITY_OWNERS = {
    "deployment_runtime_manifest": ("memory-os", "deployment_runtime_manifest"),
    "hermes_version": ("hermes", "hermes_version_command"),
    "hermes_home_schema": ("hermes", "path_probe"),
    "profile_layout": ("hermes", "path_probe"),
    "active_runtime": ("memory-os", "deployment_runtime_manifest"),
    "memory_os_plugin": ("memory-os", "path_probe"),
    "cron": ("hermes", "hermes_cron_adapter"),
    "owner_channel": ("hermes", "owner_channel_resolver"),
    "memory_provider": ("hermes", "config_shape"),
    "hindsight": ("hindsight", "config_shape"),
    "hindsight_write_origin": ("memory-os", "metadata_counter"),
    "mailbox": ("hermes", "path_probe"),
    "wandering_mind": ("hermes", "path_probe"),
    "skills": ("hermes", "path_probe"),
    "tools": ("hermes", "path_probe"),
    "mcp": ("hermes", "path_probe"),
    "gateway": ("hermes", "hermes_version_command"),
    "logs": ("hermes", "path_probe"),
    "execution_gate": ("memory-os", "execution_gate_summary"),
    "structural_write_gate": ("memory-os", "runtime_contract_static"),
    "memory_os_core": ("memory-os", "path_probe"),
    "hermes_cron": ("hermes", "hermes_cron_adapter"),
    "profile": ("hermes", "path_probe"),
    "kanban": ("hermes", "path_probe"),
    "memory_sources": ("memory-os", "path_probe"),
    "session_mirror": ("memory-os", "path_probe"),
}


def probe_host_capabilities(
    roots: MemoryOSRoots,
    *,
    hermes_bin: str = "hermes",
    include_hermes_version: bool = True,
) -> dict[str, Any]:
    """Return safe capability metadata without raw bodies or secret values."""

    now = datetime.now(timezone.utc)
    observed_at = now.isoformat().replace("+00:00", "Z")
    config = _safe_config_shape(load_config(roots.hermes_home))
    deployment_manifest = read_deployment_runtime_manifest(roots)
    hermes_version = _gateway_capability(hermes_bin) if include_hermes_version else {"status": "disabled"}
    cron_capability = _hermes_cron_capability(roots, hermes_bin=hermes_bin)
    raw_capabilities = {
        "deployment_runtime_manifest": _deployment_manifest_capability(deployment_manifest),
        "hermes_version": hermes_version,
        "hermes_home_schema": _path_capability(roots.hermes_home),
        "profile_layout": _first_path_capability(roots.hermes_home, ("profiles", "config.json")),
        "active_runtime": _active_runtime_capability(deployment_manifest),
        "memory_os_plugin": _path_capability(roots.memory_os_root),
        "cron": cron_capability,
        "owner_channel": _owner_channel_capability(roots),
        "memory_provider": _memory_provider_capability(config),
        "hindsight": _hindsight_capability(roots, config),
        "hindsight_write_origin": _hindsight_write_origin_capability(roots),
        "mailbox": _first_path_capability(roots.hermes_home, ("mailbox", "system/mailbox")),
        "wandering_mind": _path_capability(roots.hermes_home / "system-modules" / "wandering_mind"),
        "skills": _first_path_capability(roots.hermes_home, ("skills", "plugins/skills")),
        "tools": _first_path_capability(roots.hermes_home, ("tools", "plugins", "tool_registry.json")),
        "mcp": _first_path_capability(roots.hermes_home, ("mcp", "mcp_servers.json", "config/mcp.json")),
        "gateway": hermes_version,
        "logs": _first_path_capability(roots.hermes_home, ("logs", "gateway.log", "system/logs")),
        "execution_gate": _execution_gate_capability(roots),
        "structural_write_gate": _structural_write_gate_capability(),
        # Legacy compatibility keys consumed by 53 collectors and older monitor fixtures.
        "memory_os_core": _path_capability(roots.memory_os_root),
        "session_mirror": _path_capability(roots.memory_os_root / "system" / "session_mirror_state.json"),
        "memory_sources": _path_capability(roots.memory_os_root / "system" / "memory_sources.jsonl"),
        "hermes_cron": cron_capability,
        "profile": _first_path_capability(roots.hermes_home, ("profiles", "config.json")),
        "kanban": _first_path_capability(roots.hermes_home, ("kanban", "tasks", "system/kanban")),
    }
    capabilities = _normalize_capabilities(raw_capabilities, observed_at=observed_at)
    report = {
        "schema_version": HOST_CAPABILITY_PROBE_SCHEMA_VERSION,
        "created_at": observed_at,
        "host_id": _host_id(),
        "platform": platform.system().lower(),
        "profile_id": roots.profile or "default",
        "hermes_home_ref": str(roots.hermes_home),
        "memory_os_root_ref": str(roots.memory_os_root),
        "config_shape": config,
        "deployment_runtime_manifest": deployment_manifest,
        "capabilities": capabilities,
        "capability_contract": _capability_contract(capabilities),
        "raw_body_included": False,
        "secret_values_included": False,
    }
    report["capability_snapshot_id"] = _snapshot_id(report)
    return report


def _deployment_manifest_capability(manifest: dict[str, Any]) -> dict[str, Any]:
    status = str(manifest.get("status") or "missing")
    return {
        "status": status,
        "schema_version": str(manifest.get("schema_version") or ""),
        "path_ref": str(manifest.get("path_ref") or ""),
        "deployed_head": str(manifest.get("deployed_head") or ""),
        "deployed_at": str(manifest.get("deployed_at") or ""),
        "active_runtime_path": str(manifest.get("active_runtime_path") or ""),
        "active_runtime_version": str(manifest.get("active_runtime_version") or ""),
        "install_profile": str(manifest.get("install_profile") or ""),
        "freshness_status": "present" if status == "present" else status,
        "raw_body_included": False,
    }


def _active_runtime_capability(manifest: dict[str, Any]) -> dict[str, Any]:
    runtime_path = str(manifest.get("active_runtime_path") or "")
    runtime_version = str(manifest.get("active_runtime_version") or "")
    status = "present" if runtime_path or runtime_version else str(manifest.get("status") or "missing")
    return {
        "status": status,
        "active_runtime_path": runtime_path,
        "active_runtime_version": runtime_version,
        "deployed_head": str(manifest.get("deployed_head") or ""),
        "deployed_at": str(manifest.get("deployed_at") or ""),
        "freshness_status": "present" if status == "present" else status,
        "raw_body_included": False,
    }


def _path_capability(path: Path) -> dict[str, Any]:
    exists = path.exists()
    return {
        "status": "present" if exists else "missing",
        "path_ref": str(path),
        "is_dir": path.is_dir() if exists else False,
        "is_file": path.is_file() if exists else False,
        "freshness_seconds": _freshness_seconds(path) if exists else None,
    }


def _first_path_capability(home: Path, candidates: tuple[str, ...]) -> dict[str, Any]:
    for candidate in candidates:
        path = home / candidate
        if path.exists():
            report = _path_capability(path)
            report["candidate"] = candidate
            return report
    return {"status": "missing", "candidates": list(candidates)}


def _execution_gate_capability(roots: MemoryOSRoots) -> dict[str, Any]:
    path = execution_gate_records_path(roots)
    capability = _path_capability(path)
    summary = execution_gate_summary(roots)
    return {
        **capability,
        "status": "present" if path.exists() else "missing",
        "envelope_count": int(summary.get("envelope_count") or 0),
        "boundary_true_count": int(summary.get("boundary_true_count") or 0),
    }


def _owner_channel_capability(roots: MemoryOSRoots) -> dict[str, Any]:
    try:
        channel = resolve_owner_review_channel(MemoryOSStore(roots))
    except Exception as exc:
        return {"status": "missing", "reason": f"owner_channel_probe_error:{str(exc)[:80]}"}
    status = str(channel.get("status") or "missing")
    return {
        "status": "configured" if status == "selected" else status,
        "reason": str(channel.get("reason") or ""),
        "channel": str(channel.get("channel") or ""),
        "configured_by_owner": bool(channel.get("configured_by_owner")),
        "raw_body_included": False,
    }


def _hermes_cron_capability(roots: MemoryOSRoots, *, hermes_bin: str) -> dict[str, Any]:
    adapter = HermesCronAdapter(hermes_home=roots.hermes_home, hermes_bin=hermes_bin)
    jobs = adapter.read_jobs()
    classification = adapter.classify_jobs(memory_os_cron_specs())
    cron_probe = adapter.probe_capabilities()
    return {
        "status": "present" if (roots.hermes_home / "cron" / "jobs.json").exists() else "missing",
        "job_count": len(jobs),
        "jobs_schema": cron_probe.jobs_schema,
        "adapter_status": cron_probe.status,
        "supports_script": cron_probe.supports_script,
        "supports_no_agent": cron_probe.supports_no_agent,
        "supports_edit": cron_probe.supports_edit,
        "memory_os_expected_count": int(classification.get("memory_os_owned_expected_count") or 0),
        "memory_os_wrapped_count": int(classification.get("memory_os_owned_wrapped_count") or 0),
        "memory_os_naked_count": int(classification.get("memory_os_owned_naked_count") or 0),
        "raw_body_included": False,
    }


def _memory_provider_capability(config_shape: dict[str, Any]) -> dict[str, Any]:
    provider = str(config_shape.get("memory.provider") or "")
    return {
        "status": "configured" if provider else "missing",
        "provider": provider,
        "raw_body_included": False,
    }


def _hindsight_capability(roots: MemoryOSRoots, config_shape: dict[str, Any]) -> dict[str, Any]:
    provider_config = roots.hermes_home / "hindsight" / "config.json"
    substrate = config_shape.get("substrate_providers.hindsight") if isinstance(config_shape, dict) else {}
    substrate_enabled = bool(substrate.get("enabled")) if isinstance(substrate, dict) else False
    configured = provider_config.exists() or substrate_enabled
    status = "configured" if configured else "disabled" if substrate else "missing"
    return {
        "status": status,
        "provider_config_present": provider_config.exists(),
        "memory_os_substrate_config_present": bool(substrate),
        "memory_os_substrate_enabled": substrate_enabled,
        "raw_body_included": False,
    }


def _hindsight_write_origin_capability(roots: MemoryOSRoots) -> dict[str, Any]:
    records = _read_jsonl_bounded(roots.memory_os_root / "system" / "substrate_operations.jsonl", limit=500)
    hindsight_records = [
        record
        for record in records
        if str(record.get("provider") or record.get("substrate") or "").lower() == "hindsight"
        or str(record.get("provider_key") or "").lower() == "hindsight"
    ]
    write_origin_counts: dict[str, int] = {}
    for record in hindsight_records:
        origin = str(record.get("write_origin") or record.get("source") or record.get("operation") or "unknown")
        write_origin_counts[origin] = write_origin_counts.get(origin, 0) + 1
    return {
        "status": "present" if hindsight_records else "missing",
        "record_count": len(hindsight_records),
        "write_origin_counts": write_origin_counts,
        "raw_body_included": False,
    }


def _structural_write_gate_capability() -> dict[str, Any]:
    return {
        "status": "migration_needed",
        "contract": "automatic writes require valid execution_gate_envelope_id at write surface",
        "migration_hint": "introduce structural_write_gate.py append_governed_jsonl before 56 lane expansion",
        "raw_body_included": False,
    }


def _gateway_capability(hermes_bin: str) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            [hermes_bin, "--version"],
            check=False,
            text=True,
            capture_output=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "missing", "reason": str(exc)[:120], "version_available": False}
    text = f"{completed.stdout}\n{completed.stderr}".strip()
    return {
        "status": "present" if completed.returncode == 0 else "warning",
        "version_available": completed.returncode == 0,
        "version_preview": text[:180],
    }


def _normalize_capabilities(raw: dict[str, dict[str, Any]], *, observed_at: str) -> dict[str, dict[str, Any]]:
    return {
        key: _normalize_capability(key, value if isinstance(value, dict) else {}, observed_at=observed_at)
        for key, value in raw.items()
    }


def _normalize_capability(key: str, value: dict[str, Any], *, observed_at: str) -> dict[str, Any]:
    owner_system, probe_method = _CAPABILITY_OWNERS.get(key, ("memory-os", "metadata_probe"))
    status = _normalize_status(value.get("status"))
    source_scope_ref = _source_scope_ref(key, value)
    normalized = {
        "capability_key": key,
        "owner_system": owner_system,
        "status": status,
        "probe_method": probe_method,
        "confidence": _confidence(status, value),
        "source_scope_ref": source_scope_ref,
        "observed_at": observed_at,
        "freshness_status": str(value.get("freshness_status") or _freshness_status(status, value)),
        "adapter_required": bool(value.get("adapter_required") or _adapter_required(key, value)),
        "migration_hint": str(value.get("migration_hint") or _migration_hint(status, value)),
        "raw_body_included": False,
        "secret_values_included": False,
    }
    for field_key, field_value in value.items():
        if field_key in {"capability_key", "owner_system", "probe_method", "confidence", "source_scope_ref", "observed_at"}:
            continue
        if field_key in {"raw_body_included", "secret_values_included"}:
            continue
        normalized[field_key] = field_value
    normalized["status"] = status
    return normalized


def _normalize_status(status: Any) -> str:
    text = str(status or "").strip().lower()
    if text in {"present", "configured", "selected", "ok", "healthy", "running"}:
        return "available"
    if text in {"missing", "not_found", "not_configured", "configured_missing"}:
        return "missing"
    if text in {"disabled", "not_probed", "dry_run_only"}:
        return "disabled"
    if text in {"warning", "invalid", "incompatible"}:
        return "migration_needed"
    if text in HOST_CAPABILITY_ALLOWED_STATUSES:
        return text
    return "unknown"


def _freshness_status(status: str, value: dict[str, Any]) -> str:
    if value.get("freshness_seconds") is not None:
        return "present"
    if status == "available":
        return "present"
    return status


def _confidence(status: str, value: dict[str, Any]) -> str:
    if status == "unknown":
        return "low"
    if value.get("reason") or value.get("adapter_status") == "incompatible":
        return "medium"
    return "high"


def _adapter_required(key: str, value: dict[str, Any]) -> bool:
    if key in {"cron", "hermes_cron"}:
        return True
    return bool(value.get("adapter_status") == "incompatible")


def _migration_hint(status: str, value: dict[str, Any]) -> str:
    if status == "migration_needed":
        return str(value.get("reason") or value.get("adapter_status") or "capability_requires_migration")
    return ""


def _source_scope_ref(key: str, value: dict[str, Any]) -> str:
    path_ref = str(value.get("path_ref") or "")
    if path_ref:
        return path_ref
    candidates = value.get("candidates")
    if isinstance(candidates, list) and candidates:
        return f"{key}:{','.join(str(item) for item in candidates)}"
    return f"{key}:runtime"


def _capability_contract(capabilities: dict[str, dict[str, Any]]) -> dict[str, Any]:
    missing_required_keys = sorted(key for key in HOST_CAPABILITY_REQUIRED_KEYS if key not in capabilities)
    incomplete: list[dict[str, Any]] = []
    invalid_status: list[dict[str, Any]] = []
    for key, capability in capabilities.items():
        missing_fields = sorted(field for field in HOST_CAPABILITY_REQUIRED_FIELDS if field not in capability)
        if missing_fields:
            incomplete.append({"capability_key": key, "missing_fields": missing_fields})
        if str(capability.get("status") or "") not in HOST_CAPABILITY_ALLOWED_STATUSES:
            invalid_status.append({"capability_key": key, "status": capability.get("status")})
    return {
        "schema_version": "memory-os.host_capability_contract.v0",
        "required_capability_count": len(HOST_CAPABILITY_REQUIRED_KEYS),
        "capability_count": len(capabilities),
        "missing_required_capability_keys": missing_required_keys,
        "incomplete_capability_count": len(incomplete),
        "incomplete_capabilities": incomplete[:20],
        "invalid_status_count": len(invalid_status),
        "invalid_status_capabilities": invalid_status[:20],
        "contract_status": "ok" if not missing_required_keys and not incomplete and not invalid_status else "error",
    }


def _read_jsonl_bounded(path: Path, *, limit: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines[-limit:]:
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            records.append(parsed)
    return records


def _safe_config_shape(config: dict[str, Any]) -> dict[str, Any]:
    substrate_root = config.get("substrate_providers") if isinstance(config.get("substrate_providers"), dict) else {}
    hindsight = substrate_root.get("hindsight") if isinstance(substrate_root.get("hindsight"), dict) else {}
    owner_review = config.get("owner_review") if isinstance(config.get("owner_review"), dict) else {}
    memory = config.get("memory") if isinstance(config.get("memory"), dict) else {}
    return {
        "memory.provider": str(memory.get("provider") or ""),
        "owner_review.configured": bool(owner_review),
        "owner_review.enabled": bool(owner_review.get("enabled")) if owner_review else False,
        "substrate_providers.hindsight": {
            "enabled": bool(hindsight.get("enabled")),
            "retain_enabled": bool(hindsight.get("retain_enabled")),
            "recall_mode": str(hindsight.get("recall_mode") or ""),
            "reflect_enabled": bool(hindsight.get("reflect_enabled")),
        }
        if hindsight
        else {},
    }


def _freshness_seconds(path: Path) -> int | None:
    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None
    return max(int((datetime.now(timezone.utc) - mtime).total_seconds()), 0)


def _host_id() -> str:
    return socket.gethostname() or platform.node() or "unknown"


def _snapshot_id(report: dict[str, Any]) -> str:
    material = {
        "host_id": report.get("host_id"),
        "profile_id": report.get("profile_id"),
        "hermes_home_ref": report.get("hermes_home_ref"),
        "capabilities": {
            key: {
                "status": value.get("status") if isinstance(value, dict) else "unknown",
                "path_ref": value.get("path_ref") if isinstance(value, dict) else "",
            }
            for key, value in (report.get("capabilities") or {}).items()
        },
    }
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True)
    return "hcap_" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]
