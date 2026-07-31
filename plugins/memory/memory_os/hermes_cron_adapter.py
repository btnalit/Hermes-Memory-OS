"""Hermes cron adapter for Memory-OS-owned scheduled jobs."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from .cron_registry import (
    LEGACY_PER_LANE_CRON_JOBS,
    LEGACY_PER_LANE_CRON_JOB_NAMES,
    LEGACY_PER_LANE_CRON_SCRIPT_NAMES,
    MemoryOSCronSpec,
    RETIRED_MEMORY_OS_CRON_SCRIPT_NAMES,
    RETIRED_MEMORY_OS_CRON_SCRIPTS,
    memory_os_cron_specs,
)

# Reverse of LEGACY_PER_LANE_CRON_JOBS (script -> canonical legacy job name),
# used when a legacy per-lane job is identified by its script but its "name"
# field was not the canonical one (e.g. renamed on the host).
_LEGACY_PER_LANE_SCRIPT_TO_NAME = {script: name for name, script in LEGACY_PER_LANE_CRON_JOBS.items()}


@dataclass(frozen=True)
class HermesCronCapabilities:
    supports_script: bool
    supports_no_agent: bool
    supports_edit: bool
    jobs_schema: str
    status: str
    findings: Sequence[dict[str, Any]]


@dataclass(frozen=True)
class HermesCronDesiredJob:
    spec: MemoryOSCronSpec
    schedule: str
    deliver: str
    prompt: str
    wrapper_script: str
    no_agent: bool


@dataclass(frozen=True)
class HermesCronUpsertPlan:
    status: str
    command: list[str]
    migration_fields: Sequence[str]
    reason: str
    previous_job: dict[str, Any]


class HermesCronAdapter:
    def __init__(self, *, hermes_home: Path, hermes_bin: str = "hermes") -> None:
        self.hermes_home = Path(hermes_home)
        self.hermes_bin = str(hermes_bin or "hermes")

    def read_jobs(self) -> list[dict[str, Any]]:
        return read_jobs_from_hermes_home(self.hermes_home)

    def classify_jobs(self, specs: Iterable[MemoryOSCronSpec]) -> dict[str, Any]:
        return classify_hermes_cron_jobs(self.read_jobs(), specs)

    def probe_capabilities(self) -> HermesCronCapabilities:
        return probe_hermes_cron_capabilities(self.hermes_bin)

    def desired_job(self, spec: MemoryOSCronSpec, *, schedule: str, deliver: str, prompt: str) -> HermesCronDesiredJob:
        return HermesCronDesiredJob(
            spec=spec,
            schedule=str(schedule or ""),
            deliver=str(deliver or ""),
            prompt=str(prompt or ""),
            wrapper_script=spec.wrapper_script,
            no_agent=bool(spec.no_agent),
        )

    def plan_upsert(self, desired: HermesCronDesiredJob, *, existing_job: dict[str, Any] | None) -> HermesCronUpsertPlan:
        return plan_hermes_cron_job_upsert(self.hermes_bin, desired, existing_job=existing_job)


def read_jobs_from_hermes_home(hermes_home: Path) -> list[dict[str, Any]]:
    jobs_path = Path(hermes_home) / "cron" / "jobs.json"
    if not jobs_path.exists():
        return []
    try:
        loaded = json.loads(jobs_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    jobs = loaded.get("jobs", loaded) if isinstance(loaded, dict) else loaded
    return [dict(item) for item in jobs if isinstance(item, dict)] if isinstance(jobs, list) else []


def classify_hermes_cron_jobs(jobs: Iterable[dict[str, Any]], specs: Iterable[MemoryOSCronSpec]) -> dict[str, Any]:
    specs_by_name = {spec.name: spec for spec in specs}
    known_specs_by_name = {spec.name: spec for spec in memory_os_cron_specs()}
    known_specs_by_wrapper = {spec.wrapper_script: spec for spec in memory_os_cron_specs()}
    known_specs_by_raw = {spec.raw_script: spec for spec in memory_os_cron_specs()}
    retired_scripts = set(RETIRED_MEMORY_OS_CRON_SCRIPT_NAMES)
    wrapped: list[dict[str, Any]] = []
    naked: list[dict[str, Any]] = []
    known_optional: list[dict[str, Any]] = []
    retired_legacy: list[dict[str, Any]] = []
    unregistered_like: list[dict[str, Any]] = []
    hermes_host_owned: list[dict[str, Any]] = []
    external_unmanaged: list[dict[str, Any]] = []
    unclassified: list[dict[str, Any]] = []
    for job in jobs:
        name = str(job.get("name") or "")
        script = str(job.get("script") or "")
        safe = {
            "name": name,
            "script": script,
            "enabled": bool(job.get("enabled")),
            "deliver": str(job.get("deliver") or ""),
            "no_agent": bool(job.get("no_agent")),
        }
        spec = specs_by_name.get(name)
        if spec:
            if script == spec.wrapper_script:
                wrapped.append(safe)
            else:
                naked.append(safe)
            continue
        retired_name = name if name in RETIRED_MEMORY_OS_CRON_SCRIPTS else ""
        retired_script = script in retired_scripts
        if retired_name or retired_script:
            safe["retirement_reason"] = "legacy_right_brain_retired"
            retired_legacy.append(safe)
            continue
        # Pre-consolidation per-lane jobs (memory-os-<lane> running
        # memory_os_cron_<lane>_gate.py) are superseded, not unregistered --
        # see the LEGACY_PER_LANE_CRON_JOBS comment block in cron_registry.py.
        # This MUST be checked before the known_spec lookup below: one legacy
        # wrapper script name, memory_os_hindsight_health_probe.py, happens to
        # also be the tick_evidence group's hindsight_health_probe *raw_script*,
        # so known_specs_by_raw would otherwise match it first and tag it with
        # the generic "not_in_active_installed_snapshot" reason instead of the
        # more precise "superseded_by_group_tick" one. This can never swallow
        # an active group job: the specs_by_name-by-name branch above already
        # resolves any job whose Hermes job name is a live group name, and no
        # active group's name or wrapper_script collides with the legacy
        # per-lane tables (the coincidence above is confined to a raw_script,
        # which is never a Hermes job's own "script" field for an active job).
        if name in LEGACY_PER_LANE_CRON_JOB_NAMES or script in LEGACY_PER_LANE_CRON_SCRIPT_NAMES:
            registry_key = name if name in LEGACY_PER_LANE_CRON_JOB_NAMES else _LEGACY_PER_LANE_SCRIPT_TO_NAME.get(script, "")
            safe["known_registry_key"] = registry_key
            safe["known_optional_reason"] = "superseded_by_group_tick"
            known_optional.append(safe)
            continue
        known_spec = known_specs_by_name.get(name) or known_specs_by_wrapper.get(script) or known_specs_by_raw.get(script)
        if known_spec:
            safe["known_registry_key"] = known_spec.key
            safe["known_optional_reason"] = "not_in_active_installed_snapshot"
            known_optional.append(safe)
            continue
        if name.startswith("memory-os-") or script.startswith("memory_os_"):
            unregistered_like.append(safe)
            continue
        if name.startswith("hermes-") or script.startswith("hermes_"):
            hermes_host_owned.append(safe)
            continue
        if name or script:
            external_unmanaged.append(safe)
        else:
            unclassified.append(safe)
    return {
        "schema_version": "memory-os.execution_gate_cron_summary.v0",
        "status": "ok",
        "active_registry_job_count": len(specs_by_name),
        "memory_os_owned_expected_count": len(specs_by_name),
        "memory_os_owned_wrapped_count": len(wrapped),
        "memory_os_owned_naked_count": len(naked),
        "enabled_memory_os_job_count": _enabled_count(wrapped)
        + _enabled_count(naked)
        + _enabled_count(known_optional)
        + _enabled_count(unregistered_like),
        "memory_os_known_optional_count": len(known_optional),
        "enabled_known_optional_outside_active_registry_count": _enabled_count(known_optional),
        "memory_os_retired_legacy_count": len(retired_legacy),
        "enabled_retired_legacy_count": _enabled_count(retired_legacy),
        "memory_os_like_unregistered_count": len(unregistered_like),
        "hermes_host_owned_count": len(hermes_host_owned),
        "external_unmanaged_count": len(external_unmanaged),
        "unclassified_count": len(unclassified),
        "wrapped_jobs": wrapped,
        "naked_jobs": naked,
        "known_optional_jobs": known_optional,
        "retired_legacy_jobs": retired_legacy,
        "enabled_known_optional_outside_active_registry_jobs": [job for job in known_optional if job.get("enabled") is True],
        "unregistered_like_jobs": unregistered_like,
        "external_unmanaged_jobs": external_unmanaged,
    }


def _enabled_count(jobs: Iterable[dict[str, Any]]) -> int:
    return sum(1 for job in jobs if job.get("enabled") is True)


def probe_hermes_cron_capabilities(hermes_bin: str) -> HermesCronCapabilities:
    findings: list[dict[str, Any]] = []
    supports_script = False
    supports_no_agent = False
    supports_edit = False
    try:
        completed = subprocess.run(
            [hermes_bin, "cron", "create", "--help"],
            check=False,
            text=True,
            capture_output=True,
            timeout=5,
        )
        help_text = f"{completed.stdout}\n{completed.stderr}"
        supports_script = "--script" in help_text
        supports_no_agent = "--no-agent" in help_text
    except (OSError, subprocess.TimeoutExpired) as exc:
        findings.append({"code": "hermes_cron_create_help_unavailable", "error": str(exc)[:200]})
    try:
        completed = subprocess.run(
            [hermes_bin, "cron", "edit", "--help"],
            check=False,
            text=True,
            capture_output=True,
            timeout=5,
        )
        supports_edit = completed.returncode == 0 or "cron edit" in f"{completed.stdout}\n{completed.stderr}"
    except (OSError, subprocess.TimeoutExpired) as exc:
        findings.append({"code": "hermes_cron_edit_help_unavailable", "error": str(exc)[:200]})
    if not supports_script:
        findings.append({"code": "hermes_cron_script_unsupported"})
    if not supports_no_agent:
        findings.append({"code": "hermes_cron_no_agent_unsupported"})
    status = "ok" if supports_script and supports_no_agent else "incompatible"
    return HermesCronCapabilities(
        supports_script=supports_script,
        supports_no_agent=supports_no_agent,
        supports_edit=supports_edit,
        jobs_schema="jobs.json:list-or-dict-jobs",
        status=status,
        findings=tuple(findings),
    )


def plan_hermes_cron_job_upsert(
    hermes_bin: str,
    desired: HermesCronDesiredJob,
    *,
    existing_job: dict[str, Any] | None,
) -> HermesCronUpsertPlan:
    if not existing_job:
        command = [
            hermes_bin,
            "cron",
            "create",
            "--name",
            desired.spec.name,
            "--deliver",
            desired.deliver,
            "--script",
            desired.wrapper_script,
        ]
        if desired.no_agent:
            command.append("--no-agent")
        command.append(desired.schedule)
        if desired.prompt:
            command.append(desired.prompt)
        return HermesCronUpsertPlan("create", command, ("create",), "missing", {})

    job_id = str(existing_job.get("id") or existing_job.get("job_id") or "")
    if not job_id:
        return HermesCronUpsertPlan("blocked", [], (), "existing_job_id_missing", dict(existing_job))
    command = [hermes_bin, "cron", "edit"]
    migration_fields: list[str] = []
    existing_schedule = _cron_schedule_display(existing_job)
    if desired.schedule and existing_schedule and existing_schedule != desired.schedule:
        command.extend(["--schedule", desired.schedule])
        migration_fields.append("schedule")
    if str(existing_job.get("prompt") or "") != desired.prompt:
        command.extend(["--prompt", desired.prompt])
        migration_fields.append("prompt")
    if desired.deliver and str(existing_job.get("deliver") or "") != desired.deliver:
        command.extend(["--deliver", desired.deliver])
        migration_fields.append("deliver")
    if desired.wrapper_script and str(existing_job.get("script") or "") != desired.wrapper_script:
        command.extend(["--script", desired.wrapper_script])
        migration_fields.append("wrapper_script")
    if bool(existing_job.get("no_agent")) != desired.no_agent:
        command.append("--no-agent" if desired.no_agent else "--agent")
        migration_fields.append("no_agent")
    if not migration_fields:
        return HermesCronUpsertPlan("noop", [], (), "already_configured", dict(existing_job))
    command.append(job_id)
    return HermesCronUpsertPlan("edit", command, tuple(migration_fields), "drift", dict(existing_job))


def _cron_schedule_display(job: dict[str, Any]) -> str:
    if str(job.get("schedule_display") or ""):
        return str(job.get("schedule_display") or "")
    schedule = job.get("schedule")
    if isinstance(schedule, dict):
        return str(schedule.get("expr") or schedule.get("display") or "")
    return str(schedule or "")
