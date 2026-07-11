"""Hermes-owned capability observations assembled into Memory-OS schema."""

from __future__ import annotations

import subprocess
from typing import Any

from plugins.memory.memory_os.cron_registry import memory_os_cron_specs
from plugins.memory.memory_os.host_capability_probe import (
    HOST_CAPABILITY_ALLOWED_STATUSES,
    HOST_CAPABILITY_REQUIRED_FIELDS,
    HOST_CAPABILITY_REQUIRED_KEYS,
    probe_host_capabilities as assemble_capability_report,
)
from plugins.memory.memory_os.roots import MemoryOSRoots

from .cron_adapter import HermesCronAdapter
from .owner_channel_adapter import resolve_owner_review_channel


def probe_host_capabilities(
    roots: MemoryOSRoots,
    *,
    hermes_bin: str = "hermes",
    include_hermes_version: bool = True,
) -> dict[str, Any]:
    """Collect host observations outside core, then use the core report schema."""

    hermes_version = _gateway_capability(hermes_bin) if include_hermes_version else {"status": "disabled"}
    observations = {
        "hermes_version": hermes_version,
        "cron": _hermes_cron_capability(roots, hermes_bin=hermes_bin),
        "owner_channel": _owner_channel_capability(roots),
    }
    report = assemble_capability_report(
        roots,
        hermes_bin=hermes_bin,
        include_hermes_version=include_hermes_version,
        host_observations=observations,
    )
    report["host_observation_owner"] = "hermes_memory_os_seam"
    return report


def _owner_channel_capability(roots: MemoryOSRoots) -> dict[str, Any]:
    try:
        channel = resolve_owner_review_channel(
            hermes_home=roots.hermes_home,
            profile=roots.profile or "default",
        )
    except Exception as exc:
        return {"status": "missing", "reason": f"owner_channel_probe_error:{type(exc).__name__}"}
    status = str(channel.get("status") or "missing")
    return {
        "status": "configured" if status == "selected" else status,
        "observation_owner": "hermes_memory_os_seam",
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
        return {"status": "missing", "reason": type(exc).__name__, "version_available": False}
    output = f"{completed.stdout}\n{completed.stderr}".strip()
    return {
        "status": "present" if completed.returncode == 0 else "warning",
        "version_available": completed.returncode == 0,
        "version_preview": output[:180],
    }
