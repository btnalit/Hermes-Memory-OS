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


def probe_host_capabilities(
    roots: MemoryOSRoots,
    *,
    hermes_bin: str = "hermes",
    include_hermes_version: bool = True,
) -> dict[str, Any]:
    """Return safe capability metadata without raw bodies or secret values."""

    now = datetime.now(timezone.utc)
    config = _safe_config_shape(load_config(roots.hermes_home))
    deployment_manifest = read_deployment_runtime_manifest(roots)
    capabilities = {
        "memory_os_core": _path_capability(roots.memory_os_root),
        "deployment_runtime_manifest": _deployment_manifest_capability(deployment_manifest),
        "execution_gate": _execution_gate_capability(roots),
        "session_mirror": _path_capability(roots.memory_os_root / "system" / "session_mirror_state.json"),
        "owner_channel": _owner_channel_capability(roots),
        "memory_sources": _path_capability(roots.memory_os_root / "system" / "memory_sources.jsonl"),
        "hermes_cron": _hermes_cron_capability(roots, hermes_bin=hermes_bin),
        "hindsight": _hindsight_capability(roots, config),
        "mailbox": _first_path_capability(roots.hermes_home, ("mailbox", "system/mailbox")),
        "wandering_mind": _path_capability(roots.hermes_home / "system-modules" / "wandering_mind"),
        "skills": _first_path_capability(roots.hermes_home, ("skills", "plugins/skills")),
        "mcp": _first_path_capability(roots.hermes_home, ("mcp", "mcp_servers.json", "config/mcp.json")),
        "profile": _first_path_capability(roots.hermes_home, ("profiles", "config.json")),
        "kanban": _first_path_capability(roots.hermes_home, ("kanban", "tasks", "system/kanban")),
        "tools": _first_path_capability(roots.hermes_home, ("tools", "plugins", "tool_registry.json")),
        "logs": _first_path_capability(roots.hermes_home, ("logs", "gateway.log", "system/logs")),
        "gateway": _gateway_capability(hermes_bin) if include_hermes_version else {"status": "not_probed"},
    }
    report = {
        "schema_version": HOST_CAPABILITY_PROBE_SCHEMA_VERSION,
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "host_id": _host_id(),
        "platform": platform.system().lower(),
        "profile_id": roots.profile or "default",
        "hermes_home_ref": str(roots.hermes_home),
        "memory_os_root_ref": str(roots.memory_os_root),
        "config_shape": config,
        "deployment_runtime_manifest": deployment_manifest,
        "capabilities": capabilities,
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
    return {
        "status": "present" if (roots.hermes_home / "cron" / "jobs.json").exists() else "missing",
        "job_count": len(jobs),
        "memory_os_expected_count": int(classification.get("memory_os_owned_expected_count") or 0),
        "memory_os_wrapped_count": int(classification.get("memory_os_owned_wrapped_count") or 0),
        "memory_os_naked_count": int(classification.get("memory_os_owned_naked_count") or 0),
        "raw_body_included": False,
    }


def _hindsight_capability(roots: MemoryOSRoots, config_shape: dict[str, Any]) -> dict[str, Any]:
    provider_config = roots.hermes_home / "hindsight" / "config.json"
    substrate = config_shape.get("substrate_providers.hindsight") if isinstance(config_shape, dict) else {}
    configured = provider_config.exists() or bool(substrate)
    return {
        "status": "configured" if configured else "missing",
        "provider_config_present": provider_config.exists(),
        "memory_os_substrate_config_present": bool(substrate),
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
