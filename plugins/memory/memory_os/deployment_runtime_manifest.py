"""Deployment/runtime manifest for freshness evidence."""

from __future__ import annotations

import json
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .roots import MemoryOSRoots


DEPLOYMENT_RUNTIME_MANIFEST_SCHEMA_VERSION = "memory-os.deployment_runtime_manifest.v0"


def deployment_runtime_manifest_path(roots: MemoryOSRoots) -> Path:
    return roots.memory_os_root / "system" / "deployment_runtime_manifest.json"


def read_deployment_runtime_manifest(roots: MemoryOSRoots) -> dict[str, Any]:
    path = deployment_runtime_manifest_path(roots)
    if not path.exists():
        return {
            "schema_version": DEPLOYMENT_RUNTIME_MANIFEST_SCHEMA_VERSION,
            "status": "missing",
            "path_ref": str(path),
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "schema_version": DEPLOYMENT_RUNTIME_MANIFEST_SCHEMA_VERSION,
            "status": "invalid",
            "path_ref": str(path),
            "reason": str(exc)[:160],
        }
    if not isinstance(data, dict):
        return {
            "schema_version": DEPLOYMENT_RUNTIME_MANIFEST_SCHEMA_VERSION,
            "status": "invalid",
            "path_ref": str(path),
            "reason": "manifest_not_object",
        }
    return {"status": "present", "path_ref": str(path), **data}


def write_deployment_runtime_manifest(
    roots: MemoryOSRoots,
    *,
    deployed_head: str,
    deployed_at: str = "",
    active_runtime_path: str,
    active_runtime_version: str,
    install_profile: str,
    deploy_tool_version: str,
    source_repo_head: str,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    manifest = {
        "schema_version": DEPLOYMENT_RUNTIME_MANIFEST_SCHEMA_VERSION,
        "status": "present",
        "created_at": now,
        "deployed_at": deployed_at or now,
        "host_id": socket.gethostname(),
        "hermes_home_ref": str(roots.hermes_home),
        "profile_id": roots.profile or "default",
        "deployed_head": str(deployed_head or ""),
        "active_runtime_path": str(active_runtime_path or ""),
        "active_runtime_version": str(active_runtime_version or ""),
        "install_profile": str(install_profile or ""),
        "deploy_tool_version": str(deploy_tool_version or ""),
        "source_repo_head": str(source_repo_head or ""),
        "raw_body_included": False,
        "secret_values_included": False,
    }
    path = deployment_runtime_manifest_path(roots)
    _atomic_write_json(path, manifest)
    return manifest


def freshness_against_manifest(
    manifest: dict[str, Any],
    *,
    artifact_created_at: str,
    cycle_started_at: str = "",
    input_changed: bool = True,
    max_cycle_age_seconds: int = 900,
) -> dict[str, Any]:
    deployed_at = _parse_utc(str(manifest.get("deployed_at") or ""))
    artifact_at = _parse_utc(str(artifact_created_at or ""))
    cycle_at = _parse_utc(str(cycle_started_at or ""))
    now = datetime.now(timezone.utc)

    fresh_after_deploy = bool(deployed_at and artifact_at and artifact_at >= deployed_at)
    fresh_after_cycle = bool(cycle_at and artifact_at and artifact_at >= cycle_at)
    cycle_fresh = bool(cycle_at and (now - cycle_at).total_seconds() <= max_cycle_age_seconds)

    if not input_changed and cycle_fresh:
        artifact_status = "idle"
        idle_status = "healthy"
    else:
        artifact_status = "pass" if fresh_after_deploy and (not cycle_at or fresh_after_cycle) else "fail"
        idle_status = "not_idle"

    return {
        "schema_version": "memory-os.freshness_evidence.v0",
        "deployed_at": str(manifest.get("deployed_at") or ""),
        "deployed_head": str(manifest.get("deployed_head") or ""),
        "artifact_created_at": str(artifact_created_at or ""),
        "cycle_started_at": str(cycle_started_at or ""),
        "fresh_after_deploy": fresh_after_deploy,
        "fresh_after_cycle": fresh_after_cycle,
        "cycle_freshness_status": "pass" if cycle_fresh else "fail",
        "artifact_freshness_status": artifact_status,
        "idle_status": idle_status,
    }


def _parse_utc(value: str) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
    try:
        tmp_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
