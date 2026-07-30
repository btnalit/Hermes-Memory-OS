"""Read-only signal collectors for Memory-OS left-brain projection."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .execution_gate import execution_gate_records_path
from .read_model_paths import owner_actions_path, session_mirror_apply_records_path
from .roots import MemoryOSRoots
from .signal_source_registry import (
    SignalSourceSpec,
    evaluate_signal_source_requirements,
    signal_source_specs,
)
from .substrates.ledger import derive_substrate_monitor_fields
from .substrates.projection import derive_projection_coherence


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
        cron_summary = _cron_output_summary(roots.hermes_home / "cron" / "output", jobs)
        memory_os_job_count = sum(1 for job in jobs if _is_memory_os_cron_job(job))
        external_job_count = max(len(jobs) - memory_os_job_count, 0)
        status = "warning" if cron_summary["failure_count"] else "ok" if jobs else base["status"]
        return {
            **base,
            "status": status,
            "record_count": len(jobs),
            "job_count": len(jobs),
            "expected_count": 7,
            "wrapped_count": sum(1 for job in jobs if str(job.get("script") or "").startswith("memory_os_cron_")),
            "memory_os_job_count": memory_os_job_count,
            "external_job_count": external_job_count,
            **cron_summary,
        }
    if spec.source_key == "memory_sources_feedback":
        path = roots.memory_os_root / "system" / "memory_sources_feedback.jsonl"
        records = _read_jsonl(path)
        return {**base, "status": "ok" if records else base["status"], "record_count": len(records), "feedback_count": len(records)}
    if spec.source_key == "cognitive_loop_status":
        return _cognitive_loop_payload(roots, base)
    if spec.source_key == "gateway_runtime_status":
        return _gateway_runtime_payload(roots, base, capability)
    if spec.source_key == "proposal_queue_pressure":
        return _proposal_queue_payload(roots, base)
    if spec.source_key == "candidate_queue_pressure":
        return _candidate_queue_payload(roots, base)
    if spec.source_key == "owner_review_pressure":
        return _owner_review_pressure_payload(roots, base)
    if spec.source_key == "host_capability_contract":
        return _host_capability_contract_payload(base, host_capabilities)
    if spec.source_key == "runtime_logs":
        return _runtime_log_payload(roots, base)
    if spec.source_key == "skills_inventory":
        return _skills_inventory_payload(roots, base)
    if spec.source_key == "mcp_server_health":
        return _mcp_payload(roots, base)

    if spec.source_key == "hindsight_provider_stats":
        return _hindsight_payload(roots, base, capability)
    if spec.source_key == "hindsight_governance_signals":
        return _hindsight_governance_payload(roots, base, capability)
    if spec.source_key == "mailbox_status":
        return _mailbox_payload(roots, base)
    if spec.source_key == "profile_config":
        return _profile_config_payload(roots, base)
    if spec.source_key == "kanban_state":
        return _kanban_payload(roots, base)
    if spec.source_key == "tool_registry":
        return _tool_registry_payload(roots, base)
    if spec.source_key == "hermes_session_index":
        return _hermes_session_index_payload(roots, base)
    if spec.source_key == "hindsight_bank_inventory":
        return _hindsight_bank_inventory_payload(roots, base)
    if spec.source_key == "mailbox_delivery_trace":
        return _mailbox_delivery_trace_payload(roots, base)

    if spec.source_key == "mcp_tool_inventory":
        return _mcp_tool_inventory_payload(roots, base)
    return base


def _skills_inventory_payload(roots: MemoryOSRoots, base: dict[str, Any]) -> dict[str, Any]:
    roots_to_scan = [roots.hermes_home / "skills", roots.hermes_home / "plugins" / "skills"]
    children: list[Path] = []
    for root in roots_to_scan:
        children.extend(_safe_tree_children(root, limit=300))
    skill_dirs = [item for item in children if item.is_dir()]
    skill_files = [item for item in children if item.is_file()]
    manifest_names = {"skill.json", "plugin.json", "manifest.json", "skill.md"}
    manifest_count = sum(1 for item in skill_files if item.name.lower() in manifest_names)
    markdown_count = sum(1 for item in skill_files if item.suffix.lower() in {".md", ".markdown"})
    skill_count = len(skill_dirs) + manifest_count
    record_count = len(children)
    return {
        **base,
        "status": "ok" if record_count else base["status"],
        "available": bool(record_count) or base["available"],
        "record_count": record_count,
        "skill_count": skill_count,
        "skill_directory_count": len(skill_dirs),
        "skill_file_count": len(skill_files),
        "skill_manifest_count": manifest_count,
        "skill_markdown_count": markdown_count,
        "latest_skill_age_seconds": _latest_age_seconds(children),
    }


def _profile_config_payload(roots: MemoryOSRoots, base: dict[str, Any]) -> dict[str, Any]:
    config_paths = _profile_config_paths(roots)
    profiles_dir = roots.hermes_home / "profiles"
    profile_dirs = [item for item in _safe_children(profiles_dir) if item.is_dir()]
    text = "\n".join(_safe_text_lower(path) for path in config_paths)
    channel_terms = ("telegram", "wechat", "weixin", "slack", "discord", "signal", "matrix", "whatsapp")
    channel_config_count = sum(1 for term in channel_terms if term in text)
    config_exists = bool(config_paths)
    return {
        **base,
        "status": "ok" if config_exists or roots.profile else base["status"],
        "available": bool(config_exists or roots.profile) or base["available"],
        "record_count": len(config_paths) + len(profile_dirs),
        "profile_id": roots.profile or "default",
        "config_exists": config_exists,
        "config_file_count": len(config_paths),
        "profile_count": len(profile_dirs),
        "active_profile_id": roots.profile or "default",
        "memory_provider_configured": "memory.provider" in text or ("memory" in text and "provider" in text),
        "hindsight_provider_configured": "hindsight" in text,
        "channel_config_count": channel_config_count,
        "model_config_present": "model" in text or "llm" in text,
        "config_age_seconds": _latest_age_seconds(config_paths + ([profiles_dir] if profiles_dir.exists() else [])),
    }


def _kanban_payload(roots: MemoryOSRoots, base: dict[str, Any]) -> dict[str, Any]:
    roots_to_scan = [
        roots.hermes_home / "kanban",
        roots.hermes_home / "tasks",
        roots.hermes_home / "system" / "kanban",
    ]
    files: list[Path] = []
    dirs: list[Path] = []
    for root in roots_to_scan:
        children = _safe_tree_children(root, limit=500)
        files.extend(item for item in children if item.is_file())
        dirs.extend(item for item in children if item.is_dir())
    done_terms = ("done", "closed", "complete", "completed", "archive", "archived")
    open_terms = ("open", "todo", "doing", "in-progress", "pending", "backlog")
    done_count = sum(1 for item in files if any(term in item.name.lower() for term in done_terms))
    open_count = sum(1 for item in files if any(term in item.name.lower() for term in open_terms))
    card_count = len(files)
    return {
        **base,
        "status": "ok" if files or dirs else base["status"],
        "available": bool(files or dirs) or base["available"],
        "record_count": card_count + len(dirs),
        "card_count": card_count,
        "column_count": len(dirs),
        "open_card_count": open_count,
        "done_card_count": done_count,
        "latest_card_age_seconds": _latest_age_seconds(files + dirs),
    }


def _tool_registry_payload(roots: MemoryOSRoots, base: dict[str, Any]) -> dict[str, Any]:
    roots_to_scan = [
        roots.hermes_home / "tools",
        roots.hermes_home / "plugins",
        roots.hermes_home / "mcp",
    ]
    children: list[Path] = []
    for root in roots_to_scan:
        children.extend(_safe_tree_children(root, limit=500))
    files = [item for item in children if item.is_file()]
    dirs = [item for item in children if item.is_dir()]
    manifest_names = {"tool_registry.json", "tools.json", "plugin.json", "manifest.json", "mcp_servers.json"}
    manifest_count = sum(1 for item in files if item.name.lower() in manifest_names)
    mcp_count = sum(1 for item in children if "mcp" in item.name.lower())
    return {
        **base,
        "status": "ok" if children else base["status"],
        "available": bool(children) or base["available"],
        "record_count": len(children),
        "tool_count": len(files) + len(dirs),
        "plugin_count": sum(1 for item in children if "plugin" in item.name.lower()),
        "mcp_tool_count": mcp_count,
        "tool_manifest_count": manifest_count,
        "tool_config_exists": manifest_count > 0,
        "latest_tool_age_seconds": _latest_age_seconds(children),
    }


def _hermes_session_index_payload(roots: MemoryOSRoots, base: dict[str, Any]) -> dict[str, Any]:
    session_roots = [
        roots.hermes_home / "sessions",
        roots.hermes_home / "conversations",
        roots.memory_os_root / "events",
    ]
    files: list[Path] = []
    for root in session_roots:
        files.extend(item for item in _safe_tree_children(root, limit=1_000) if item.is_file())
    session_files = [
        item for item in files if item.suffix.lower() in {".json", ".jsonl", ".md", ".txt"}
    ]
    conversation_files = [
        item for item in session_files if "conversation" in item.name.lower() or "chat" in item.name.lower()
    ]
    event_records = _memory_os_event_records(roots, limit=1_000)
    session_event_count = 0
    recent_session_event_count = 0
    platforms: set[str] = set()
    for index, record in enumerate(event_records):
        safe_ref = record.get("safe_ref") if isinstance(record.get("safe_ref"), dict) else {}
        if safe_ref.get("session_id"):
            session_event_count += 1
            platform = str(safe_ref.get("platform") or record.get("source") or "")
            if platform:
                platforms.add(platform[:80])
            if index >= max(0, len(event_records) - 250):
                recent_session_event_count += 1
    return {
        **base,
        "status": "ok" if session_files or event_records else base["status"],
        "available": bool(session_files or event_records) or base["available"],
        "record_count": len(session_files) + len(event_records),
        "session_file_count": len(session_files),
        "conversation_file_count": len(conversation_files),
        "session_event_count": session_event_count,
        "recent_session_event_count": recent_session_event_count,
        "platform_count": len(platforms),
        "latest_session_age_seconds": _latest_age_seconds(session_files),
    }


def _hindsight_bank_inventory_payload(roots: MemoryOSRoots, base: dict[str, Any]) -> dict[str, Any]:
    bank_roots = [
        roots.hermes_home / "hindsight",
        roots.hermes_home / ".hindsight",
        roots.hermes_home / "memory" / "hindsight",
    ]
    children: list[Path] = []
    for root in bank_roots:
        children.extend(_safe_tree_children(root, limit=1_000))
    files = [item for item in children if item.is_file()]
    dirs = [item for item in children if item.is_dir()]
    strategy_names = {"strategy.json", "config.json", "settings.json", "bank.json", "provider.json"}
    strategy_count = sum(1 for item in files if item.name.lower() in strategy_names)
    operation_records = _read_jsonl(roots.memory_os_root / "system" / "substrate_operations.jsonl")
    provider_records = [record for record in operation_records if _hindsight_record(record)]
    return {
        **base,
        "status": "ok" if children or provider_records else base["status"],
        "available": bool(children or provider_records) or base["available"],
        "record_count": len(children) + len(provider_records),
        "bank_directory_count": len(dirs),
        "bank_file_count": len(files),
        "strategy_file_count": strategy_count,
        "latest_bank_age_seconds": _latest_age_seconds(files + dirs),
        "substrate_operation_count": len(provider_records),
        "memory_os_config_present": bool(provider_records),
        "raw_payload_file_count": 0,
    }


def _mailbox_delivery_trace_payload(roots: MemoryOSRoots, base: dict[str, Any]) -> dict[str, Any]:
    delivery_records = _read_jsonl(roots.memory_os_root / "system" / "owner_review_deliveries.jsonl")
    output_files = _safe_tree_children(roots.hermes_home / "cron" / "output", limit=1_000)
    failures = [
        record
        for record in delivery_records
        if str(record.get("result") or record.get("status") or "") in {"error", "failed", "skipped"}
    ]
    cooldown_markers = [
        roots.hermes_home / "system-modules" / "mailbox" / "cooldown.json",
        roots.hermes_home / "system-modules" / "mailbox" / "cooldown.lock",
        roots.hermes_home / "mailbox" / "cooldown.json",
        roots.hermes_home / "mailbox" / "cooldown.lock",
    ]
    return {
        **base,
        "status": "ok" if delivery_records or output_files else base["status"],
        "available": bool(delivery_records or output_files) or base["available"],
        "record_count": len(delivery_records) + len(output_files),
        "delivery_record_count": len(delivery_records),
        "owner_channel_delivery_count": sum(
            1 for record in delivery_records if str(record.get("owner_id") or record.get("channel") or "")
        ),
        "failed_delivery_count": len(failures),
        "latest_delivery_at": _latest_record_time(delivery_records),
        "latest_failure_at": _latest_record_time(failures),
        "cron_output_file_count": sum(1 for item in output_files if item.is_file()),
        "cooldown_marker_count": sum(1 for item in cooldown_markers if item.exists()),
    }



def _mcp_tool_inventory_payload(roots: MemoryOSRoots, base: dict[str, Any]) -> dict[str, Any]:
    config_paths = [roots.hermes_home / "mcp_servers.json", roots.hermes_home / "config" / "mcp.json"]
    config_files = [path for path in config_paths if path.is_file()]
    servers: list[Any] = []
    server_names: set[str] = set()
    for path in config_files:
        loaded = _safe_json_dict(path)
        for key in ("mcpServers", "servers", "mcp_servers"):
            value = loaded.get(key)
            if isinstance(value, dict):
                server_names.update(str(name)[:80] for name in value)
                servers.extend(value.values())
            elif isinstance(value, list):
                servers.extend(value)
    directory_children = _safe_tree_children(roots.hermes_home / "mcp", limit=500)
    stdio_count = 0
    http_count = 0
    disabled_count = 0
    tool_candidate_count = 0
    for server in servers:
        if not isinstance(server, dict):
            continue
        transport = str(server.get("transport") or server.get("type") or "").lower()
        command = str(server.get("command") or "")
        url = str(server.get("url") or "")
        if command or transport == "stdio":
            stdio_count += 1
        if url.startswith(("http://", "https://")) or transport in {"http", "sse", "streamable-http"}:
            http_count += 1
        if server.get("enabled") is False or str(server.get("status") or "").lower() in {"disabled", "off"}:
            disabled_count += 1
        tools = server.get("tools")
        if isinstance(tools, list):
            tool_candidate_count += len(tools)
    return {
        **base,
        "status": "ok" if config_files or directory_children else base["status"],
        "available": bool(config_files or directory_children) or base["available"],
        "record_count": len(config_files) + len(directory_children) + len(servers),
        "server_name_count": len(server_names) or len(servers),
        "stdio_server_count": stdio_count,
        "http_server_count": http_count,
        "disabled_server_count": disabled_count,
        "tool_candidate_count": tool_candidate_count + sum(1 for item in directory_children if item.is_file()),
        "config_file_count": len(config_files),
        "latest_config_age_seconds": _latest_age_seconds(config_files + directory_children),
    }


def _host_capability_contract_payload(base: dict[str, Any], host_capabilities: dict[str, Any]) -> dict[str, Any]:
    capabilities = host_capabilities.get("capabilities") if isinstance(host_capabilities.get("capabilities"), dict) else {}
    contract = (
        host_capabilities.get("capability_contract")
        if isinstance(host_capabilities.get("capability_contract"), dict)
        else {}
    )
    status_counts: dict[str, int] = {}
    migration_needed_keys: list[str] = []
    adapter_required_count = 0
    adapter_missing_count = 0
    capability_items = capabilities.items() if isinstance(capabilities, dict) else ()
    for key, value in capability_items:
        if not isinstance(value, dict):
            continue
        status = str(value.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        if status == "migration_needed":
            migration_needed_keys.append(str(key)[:80])
        if value.get("adapter_required") is True:
            adapter_required_count += 1
            if status in {"missing", "migration_needed", "unknown"}:
                adapter_missing_count += 1
    memory_provider = capabilities.get("memory_provider") if isinstance(capabilities.get("memory_provider"), dict) else {}
    deployment = capabilities.get("deployment_runtime_manifest") if isinstance(capabilities.get("deployment_runtime_manifest"), dict) else {}
    active_runtime = capabilities.get("active_runtime") if isinstance(capabilities.get("active_runtime"), dict) else {}
    hermes_version = capabilities.get("hermes_version") if isinstance(capabilities.get("hermes_version"), dict) else {}
    payload_status = "ok" if str(contract.get("contract_status") or "") == "ok" else "warning"
    return {
        **base,
        "status": payload_status,
        "available": True,
        "record_count": len(capabilities) if isinstance(capabilities, dict) else 0,
        "capability_count": len(capabilities) if isinstance(capabilities, dict) else 0,
        "required_capability_count": int(contract.get("required_capability_count") or 0),
        "missing_required_capability_count": len(contract.get("missing_required_capability_keys") or []),
        "incomplete_capability_count": int(contract.get("incomplete_capability_count") or 0),
        "invalid_status_count": int(contract.get("invalid_status_count") or 0),
        "contract_status": str(contract.get("contract_status") or "unknown"),
        "available_capability_count": sum(status_counts.get(key, 0) for key in ("available", "present", "configured", "running", "ok", "healthy")),
        "missing_capability_count": status_counts.get("missing", 0),
        "disabled_capability_count": status_counts.get("disabled", 0),
        "migration_needed_count": status_counts.get("migration_needed", 0),
        "migration_needed_keys": sorted(migration_needed_keys)[:20],
        "adapter_required_count": adapter_required_count,
        "adapter_missing_count": adapter_missing_count,
        "owner_channel_status": _capability_status_value(capabilities, "owner_channel"),
        "memory_provider_status": _capability_status_value(capabilities, "memory_provider"),
        "memory_provider_name": str(memory_provider.get("provider") or "")[:80],
        "hindsight_status": _capability_status_value(capabilities, "hindsight"),
        "structural_write_gate_status": _capability_status_value(capabilities, "structural_write_gate"),
        "execution_gate_status": _capability_status_value(capabilities, "execution_gate"),
        "cron_status": _capability_status_value(capabilities, "cron"),
        "deployment_status": str(deployment.get("status") or ""),
        "deployed_head_present": bool(deployment.get("deployed_head")),
        "active_runtime_version_present": bool(active_runtime.get("active_runtime_version")),
        "hermes_version_available": bool(hermes_version.get("version_available")),
    }


def _hindsight_payload(roots: MemoryOSRoots, base: dict[str, Any], capability: dict[str, Any]) -> dict[str, Any]:
    operation_records = _read_jsonl(roots.memory_os_root / "system" / "substrate_operations.jsonl")
    provider_records = [record for record in operation_records if _hindsight_record(record)]
    monitor_fields = derive_substrate_monitor_fields(operation_records, provider="hindsight")
    projection_records = _read_jsonl(roots.memory_os_root / "system" / "projection_ledger.jsonl")
    coherence = derive_projection_coherence(projection_records, provider="hindsight")
    operation_count = len(provider_records)
    configured = _present(capability) or bool(capability.get("memory_os_substrate_config_present"))
    projection_stale_count = int(coherence.get("projection_stale_count") or 0)
    raw_retained_count = int(monitor_fields.get("raw_retained_count") or 0)
    return {
        **base,
        "status": "ok" if configured or operation_count else base["status"],
        "available": configured or base["available"],
        "record_count": operation_count,
        "configured": bool(configured),
        "retain_enabled": bool(capability.get("retain_enabled") or capability.get("memory_os_substrate_enabled")),
        "recall_mode": str(capability.get("recall_mode") or ""),
        "reflect_enabled": bool(capability.get("reflect_enabled")),
        "operation_count": operation_count,
        "retain_count": int(monitor_fields.get("retain_count") or 0),
        "recall_count": int(monitor_fields.get("recall_count") or 0),
        "invalidate_count": int(monitor_fields.get("retract_count") or 0),
        "reflect_count": int(monitor_fields.get("reflect_count") or 0),
        "raw_retained_count": raw_retained_count,
        "no_raw_retained": bool(monitor_fields.get("no_raw_retained", True)),
        "projection_stale_count": projection_stale_count,
        "active_projection_count": int(coherence.get("active_projection_count") or 0),
        "recall_llm_triggered": bool(monitor_fields.get("recall_llm_triggered")),
        "reflect_hot_path_count": int(monitor_fields.get("reflect_hot_path_count") or 0),
        "latest_operation_at": _latest_record_time(provider_records),
        "pollution_indicator_count": raw_retained_count + projection_stale_count,
    }


def _hindsight_governance_payload(
    roots: MemoryOSRoots,
    base: dict[str, Any],
    capability: dict[str, Any],
) -> dict[str, Any]:
    operation_records = _read_jsonl(roots.memory_os_root / "system" / "substrate_operations.jsonl")
    provider_records = [record for record in operation_records if _hindsight_record(record)]
    monitor_fields = derive_substrate_monitor_fields(operation_records, provider="hindsight")
    projection_records = _read_jsonl(roots.memory_os_root / "system" / "projection_ledger.jsonl")
    coherence = derive_projection_coherence(projection_records, provider="hindsight")
    raw_retained_count = int(monitor_fields.get("raw_retained_count") or 0)
    projection_stale_count = int(coherence.get("projection_stale_count") or 0)
    duplicate_indicator_count = _duplicate_projection_indicator_count(projection_records)
    authoritative_claim_count = sum(1 for record in provider_records if record.get("advisory_only") is False)
    pollution_indicator_count = raw_retained_count + projection_stale_count + duplicate_indicator_count
    retain_review_suggested_count = max(raw_retained_count, 0)
    reject_review_suggested_count = max(raw_retained_count + duplicate_indicator_count, 0)
    demote_review_suggested_count = max(projection_stale_count, 0)
    curation_review_suggested_count = pollution_indicator_count
    curation_decisions = _read_jsonl(roots.memory_os_root / "system" / "hindsight_curation_decisions.jsonl")
    retain_decision_count = sum(1 for record in curation_decisions if str(record.get("curation_decision") or "") == "retain")
    reject_decision_count = sum(1 for record in curation_decisions if str(record.get("curation_decision") or "") == "reject")
    demote_decision_count = sum(1 for record in curation_decisions if str(record.get("curation_decision") or "") == "demote")
    configured = _present(capability) or bool(capability.get("memory_os_substrate_config_present")) or bool(provider_records)
    return {
        **base,
        "status": "warning" if pollution_indicator_count or authoritative_claim_count else "ok" if configured else base["status"],
        "available": configured or base["available"],
        "record_count": len(provider_records) + len(projection_records) + len(curation_decisions),
        "suggestion_count": (
            retain_review_suggested_count
            + reject_review_suggested_count
            + demote_review_suggested_count
            + (1 if curation_review_suggested_count else 0)
        ),
        "retain_review_suggested_count": retain_review_suggested_count,
        "reject_review_suggested_count": reject_review_suggested_count,
        "demote_review_suggested_count": demote_review_suggested_count,
        "curation_review_suggested_count": curation_review_suggested_count,
        "curation_decision_count": len(curation_decisions),
        "retain_decision_count": retain_decision_count,
        "reject_decision_count": reject_decision_count,
        "demote_decision_count": demote_decision_count,
        "raw_retained_count": raw_retained_count,
        "projection_stale_count": projection_stale_count,
        "pollution_indicator_count": pollution_indicator_count,
        "duplicate_indicator_count": duplicate_indicator_count,
        "advisory_only": authoritative_claim_count == 0,
        "authoritative_claim_count": authoritative_claim_count,
        "raw_body_included": False,
        "boundary_true_count": 0,
    }


def _cognitive_loop_payload(roots: MemoryOSRoots, base: dict[str, Any]) -> dict[str, Any]:
    records = _read_jsonl(roots.hermes_home / "system-modules" / "cognitive_loop" / "reports.jsonl")
    latest = records[-1] if records else {}
    steps = latest.get("steps") if isinstance(latest.get("steps"), list) else []
    step_names = {str(step.get("step") or "") for step in steps if isinstance(step, dict)}
    required_steps = {
        "left_brain_pipeline_check",
        "host_capability_probe",
        "signal_collection",
        "memory_projection",
        "left_brain_advisor",
        "governance_feedback",
        "deep_reflection",
        "heartbeat_post",
        "doctor_boundary_report",
    }
    return {
        **base,
        "status": "ok" if records else base["status"],
        "available": bool(records) or base["available"],
        "record_count": len(records),
        "report_count": len(records),
        "latest_cycle_id": str(latest.get("cycle_id") or ""),
        "latest_finished_at": str(latest.get("finished_at") or ""),
        "latest_status": str(latest.get("status") or "") if latest else "",
        "step_count": int(latest.get("step_count") or len(steps)),
        "error_step_count": sum(1 for step in steps if isinstance(step, dict) and str(step.get("status") or "") == "error"),
        "warning_step_count": sum(1 for step in steps if isinstance(step, dict) and str(step.get("status") or "") == "warning"),
        "required_step_missing_count": len(required_steps - step_names) if records else 0,
        "boundary_true_count": 1 if _any_true(latest.get("boundary_state") or latest.get("boundaries")) else 0,
    }


def _gateway_runtime_payload(roots: MemoryOSRoots, base: dict[str, Any], capability: dict[str, Any]) -> dict[str, Any]:
    heartbeat = _safe_json_dict(roots.memory_os_root / "runtime" / "heartbeat_state.json")
    gateway_logs = [
        path
        for path in _runtime_log_files(roots)
        if path.name.lower() == "gateway.log" or "gateway" in path.name.lower()
    ]
    last_heartbeat_at = str(
        heartbeat.get("last_heartbeat_at")
        or heartbeat.get("last_run_at")
        or heartbeat.get("updated_at")
        or heartbeat.get("created_at")
        or ""
    )
    gateway_version = capability.get("version") or capability.get("hermes_version") or capability.get("build")
    return {
        **base,
        "status": "ok" if heartbeat or gateway_logs or _present(capability) else base["status"],
        "available": bool(heartbeat or gateway_logs or _present(capability)) or base["available"],
        "record_count": (1 if heartbeat else 0) + len(gateway_logs),
        "heartbeat_state_exists": bool(heartbeat),
        "last_heartbeat_at": last_heartbeat_at[:80],
        "heartbeat_age_seconds": _age_seconds_from_iso(last_heartbeat_at),
        "processed_event_count": int(
            heartbeat.get("processed_event_count")
            or heartbeat.get("event_count")
            or heartbeat.get("processed_count")
            or 0
        ),
        "gateway_capability_status": str(capability.get("status") or "missing"),
        "gateway_version_available": bool(gateway_version),
        "gateway_log_exists": bool(gateway_logs),
        "gateway_log_age_seconds": _latest_age_seconds(gateway_logs),
    }


def _proposal_queue_payload(roots: MemoryOSRoots, base: dict[str, Any]) -> dict[str, Any]:
    items = _proposal_queue_items(roots)
    state_counts = _count_by_key(items, "state")
    followup_counts = _count_by_key(items, "followup_state")
    return {
        **base,
        "status": "ok" if items else base["status"],
        "available": bool(items) or base["available"],
        "record_count": len(items),
        "proposal_count": len(items),
        "state_candidate_count": int(state_counts.get("candidate") or 0),
        "approved_for_proposal_count": int(state_counts.get("approved_for_proposal") or 0),
        "awaiting_ops_gate_count": int(followup_counts.get("awaiting_ops_gate") or 0),
        "ops_gate_reviewed_count": int(followup_counts.get("ops_gate_reviewed") or 0),
        "execution_ticket_count": sum(1 for item in items if item.get("execution_ticket")),
        "actual_execute_count": sum(1 for item in items if item.get("actual_execute") is True),
        "crystallized_approval_granted_count": sum(1 for item in items if item.get("crystallized_approved") is True),
    }


def _candidate_queue_payload(roots: MemoryOSRoots, base: dict[str, Any]) -> dict[str, Any]:
    from .crystallized import read_effective_candidates
    from .store import MemoryOSStore

    records = _candidate_queue_records(roots)
    views = read_effective_candidates(MemoryOSStore(roots))
    effective_pending = [view for view in views if not view.terminal]
    owner_agenda = [view for view in views if view.owner_review_eligible]
    kind_values = {str(record.get("kind") or record.get("candidate_kind") or "") for record in records}
    bridge_states = {
        str(record.get("bridge_state") or record.get("candidate_bridge_state") or "")
        for record in records
        if record.get("bridge_state") or record.get("candidate_bridge_state")
    }
    return {
        **base,
        "status": "ok" if records else base["status"],
        "available": bool(records) or base["available"],
        "record_count": len(records),
        "raw_candidate_count": len(records),
        "candidate_count": len(records),
        "effective_pending_candidate_count": len(effective_pending),
        "active_candidate_count": len(effective_pending),
        "owner_agenda_candidate_count": len(owner_agenda),
        "suppressed_terminal_candidate_count": sum(1 for view in views if view.terminal),
        "suppressed_noneligible_candidate_count": sum(
            1 for view in views if not view.terminal and not view.owner_review_eligible
        ),
        "fleeting_candidate_count": sum(1 for view in views if view.effective_state == "fleeting"),
        "private_candidate_count": sum(1 for record in records if record.get("visibility") == "private" or record.get("is_private") is True),
        "public_candidate_count": sum(1 for record in records if record.get("visibility") == "public" or record.get("is_private") is False),
        "latest_candidate_at": _latest_record_time(records),
        "kind_count": len({value for value in kind_values if value}),
        "source_event_ref_count": sum(1 for record in records if record.get("source_event_ref") or record.get("source_event_id")),
        "bridge_state_count": len(bridge_states),
    }


def _owner_review_pressure_payload(roots: MemoryOSRoots, base: dict[str, Any]) -> dict[str, Any]:
    owner_actions = _read_jsonl(owner_actions_path(roots))
    proposal_items = _proposal_queue_items(roots)
    candidate_records = _candidate_queue_records(roots)
    from .crystallized import read_effective_candidates
    from .store import MemoryOSStore
    candidate_views = read_effective_candidates(MemoryOSStore(roots))
    advisor_records = _read_jsonl(roots.hermes_home / "system-modules" / "left_brain_advisor" / "reports.jsonl")
    findings: list[dict[str, Any]] = []
    for record in advisor_records:
        record_findings = record.get("findings") if isinstance(record.get("findings"), list) else []
        findings.extend(item for item in record_findings if isinstance(item, dict))
    pending_proposals = [
        item
        for item in proposal_items
        if str(item.get("state") or "") in {"candidate", "approved_for_proposal"}
        or str(item.get("followup_state") or "") in {"awaiting_ops_gate", "ops_gate_reviewed"}
    ]
    pending_candidates = [
        view.candidate
        for view in candidate_views
        if view.owner_review_eligible
    ]
    action_required = sum(1 for item in findings if str(item.get("owner_burden_class") or "") == "action_required")
    review_suggested = sum(1 for item in findings if str(item.get("owner_burden_class") or "") == "review_suggested")
    fyi = sum(1 for item in findings if str(item.get("owner_burden_class") or "") == "fyi")
    return {
        **base,
        "status": "ok" if owner_actions or proposal_items or candidate_records or findings else base["status"],
        "available": bool(owner_actions or proposal_items or candidate_records or findings) or base["available"],
        "record_count": len(owner_actions) + len(proposal_items) + len(candidate_records) + len(findings),
        "owner_action_count": len(owner_actions),
        "action_required_estimate_count": action_required,
        "review_suggested_estimate_count": review_suggested,
        "fyi_estimate_count": fyi,
        "advisor_finding_count": len(findings),
        "owner_visible_finding_count": sum(1 for item in findings if item.get("owner_visible") is not False),
        "pending_candidate_count": len(pending_candidates),
        "pending_proposal_count": len(pending_proposals),
        "overflow_estimate_count": max(action_required + review_suggested - 3, 0),
        "duplicate_action_count": sum(1 for record in owner_actions if str(record.get("result") or "") == "duplicate"),
        "error_action_count": sum(1 for record in owner_actions if str(record.get("result") or record.get("status") or "") in {"error", "failed"}),
    }


_MAILBOX_AGENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _configured_mailbox_root(hermes_home: Path) -> Path | None:
    """Resolve a per-agent mailbox root from config.yaml.

    Reads ``platforms.mailbox.extra.root`` and ``platforms.mailbox.extra.agent_id``
    from ``<hermes_home>/config.yaml``. Both fields must be present and valid
    (``agent_id`` must match ``[A-Za-z0-9_-]{1,64}``) for a configured root to
    be returned; a relative ``root`` is resolved against ``hermes_home``. The
    returned path is the bare per-agent directory (``<root>/agents/<agent_id>``)
    -- callers append their own ``inbox``/``outbox`` suffixes, mirroring how the
    hardcoded fallback roots are also bare directories.

    Returns ``None`` -- never raises -- when config.yaml is absent, unreadable,
    malformed, or the mailbox/extra fields are missing or invalid, so callers
    can fall back to their existing hardcoded probe unchanged.
    """
    config_path = hermes_home / "config.yaml"
    if not config_path.is_file():
        return None
    try:
        import yaml

        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(loaded, dict):
        return None
    platforms = loaded.get("platforms")
    mailbox_cfg = platforms.get("mailbox") if isinstance(platforms, dict) else None
    extra = mailbox_cfg.get("extra") if isinstance(mailbox_cfg, dict) else None
    if not isinstance(extra, dict):
        return None
    raw_root = extra.get("root")
    agent_id = extra.get("agent_id")
    if not isinstance(raw_root, str) or not raw_root.strip():
        return None
    if not isinstance(agent_id, str) or not _MAILBOX_AGENT_ID_PATTERN.fullmatch(agent_id):
        return None
    root_path = Path(raw_root.strip())
    if not root_path.is_absolute():
        root_path = hermes_home / root_path
    return root_path / "agents" / agent_id


def _mailbox_payload(roots: MemoryOSRoots, base: dict[str, Any]) -> dict[str, Any]:
    configured_root = _configured_mailbox_root(roots.hermes_home)
    if configured_root is not None and configured_root.exists():
        root = configured_root
    else:
        root = _first_existing_path(roots.hermes_home, ("mailbox", "system/mailbox"))
    inbox = root / "inbox" if root else roots.hermes_home / "mailbox" / "inbox"
    outbox = root / "outbox" if root else roots.hermes_home / "mailbox" / "outbox"
    would_send_records = _read_jsonl(roots.hermes_home / "system-modules" / "mailbox" / "would_send.jsonl")
    if root:
        would_send_records += _read_jsonl(root / "would_send.jsonl")
    inbox_count = _safe_file_count(inbox)
    outbox_count = _safe_file_count(outbox)
    mailbox_exists = root is not None
    return {
        **base,
        "status": "ok" if mailbox_exists or would_send_records else base["status"],
        "available": mailbox_exists or base["available"],
        "record_count": inbox_count + outbox_count + len(would_send_records),
        "mailbox_exists": mailbox_exists,
        "inbox_exists": inbox.exists(),
        "outbox_exists": outbox.exists(),
        "inbox_count": inbox_count,
        "outbox_count": outbox_count,
        "would_send_count": len(would_send_records),
        "latest_would_send_at": _latest_record_time(would_send_records),
        "backlog_count": inbox_count,
        "cooldown_active": _mailbox_cooldown_active(roots, root),
        "actual_send_count": _actual_send_count(would_send_records),
    }



def _mcp_payload(roots: MemoryOSRoots, base: dict[str, Any]) -> dict[str, Any]:
    config_paths = [roots.hermes_home / "mcp_servers.json", roots.hermes_home / "config" / "mcp.json"]
    config_files = [path for path in config_paths if path.is_file()]
    directory = roots.hermes_home / "mcp"
    directory_server_count = _safe_child_count(directory)
    parsed_counts = [_mcp_config_counts(path) for path in config_files]
    configured_server_count = sum(item["server_count"] for item in parsed_counts)
    healthy_count = sum(item["healthy_count"] for item in parsed_counts)
    failed_server_count = sum(item["failed_server_count"] for item in parsed_counts)
    server_count = configured_server_count + directory_server_count
    latest_config_age = _latest_age_seconds(config_files + ([directory] if directory.exists() else []))
    return {
        **base,
        "status": "ok" if config_files or directory.exists() else base["status"],
        "available": bool(config_files or directory.exists()) or base["available"],
        "record_count": server_count or len(config_files),
        "config_file_count": len(config_files),
        "configured_server_count": configured_server_count,
        "directory_server_count": directory_server_count,
        "server_count": server_count,
        "healthy_count": healthy_count,
        "failed_server_count": failed_server_count,
        "latest_config_age_seconds": latest_config_age,
    }


def _runtime_log_payload(roots: MemoryOSRoots, base: dict[str, Any]) -> dict[str, Any]:
    files = _runtime_log_files(roots)
    latest = max(files, key=lambda path: path.stat().st_mtime, default=None)
    error_log = _first_named_file(files, {"error.log", "errors.log"})
    gateway_log = _first_named_file(files, {"gateway.log"})
    return {
        **base,
        "status": "ok" if files else base["status"],
        "available": bool(files) or base["available"],
        "record_count": len(files),
        "log_file_count": len(files),
        "latest_log_age_seconds": _latest_age_seconds(files),
        "latest_log_file": latest.name[:80] if latest else "",
        "latest_log_mtime": _mtime_iso(latest) if latest else "",
        "error_log_exists": error_log is not None,
        "error_log_size_bytes": _safe_size(error_log),
        "gateway_log_exists": gateway_log is not None,
        "gateway_log_size_bytes": _safe_size(gateway_log),
        "rotated_log_count": sum(1 for path in files if ".log." in path.name or path.suffix not in {"", ".log"}),
    }


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
    return str(capability.get("status") or "") in {"available", "present", "configured", "running", "ok", "healthy"}


def _capability_status_value(capabilities: dict[str, Any], key: str) -> str:
    value = capabilities.get(key) if isinstance(capabilities, dict) else {}
    return str(value.get("status") or "missing") if isinstance(value, dict) else "missing"


def _hindsight_record(record: dict[str, Any]) -> bool:
    return (
        str(record.get("provider") or record.get("substrate") or "").lower() == "hindsight"
        or str(record.get("provider_key") or "").lower() == "hindsight"
    )


def _duplicate_projection_indicator_count(records: list[dict[str, Any]]) -> int:
    seen: set[str] = set()
    duplicates = 0
    for record in records:
        if str(record.get("provider") or record.get("provider_key") or "").lower() not in {"", "hindsight"}:
            continue
        key = str(
            record.get("dedup_key")
            or record.get("source_ref")
            or record.get("source_record_ref")
            or record.get("source_ref_version")
            or (
                f"{record.get('source_record_ref')}:{record.get('source_version')}"
                if record.get("source_record_ref") and record.get("source_version")
                else ""
            )
            or record.get("projection_ref")
            or ""
        )
        if not key:
            continue
        if key in seen:
            duplicates += 1
        seen.add(key)
    return duplicates


def _first_existing_path(root: Path, candidates: tuple[str, ...]) -> Path | None:
    for candidate in candidates:
        path = root / candidate
        if path.exists():
            return path
    return None


def _safe_file_count(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return 1
    try:
        return len([item for item in path.iterdir() if item.is_file()])
    except OSError:
        return 0


def _safe_child_count(path: Path) -> int:
    if not path.exists() or path.is_file():
        return 0
    try:
        return len([item for item in path.iterdir() if item.is_file() or item.is_dir()])
    except OSError:
        return 0


def _safe_children(path: Path) -> list[Path]:
    if not path.exists() or path.is_file():
        return []
    try:
        return [item for item in path.iterdir() if item.is_file() or item.is_dir()]
    except OSError:
        return []


def _safe_tree_children(path: Path, *, limit: int) -> list[Path]:
    if not path.exists() or path.is_file():
        return []
    children: list[Path] = []
    try:
        for item in path.rglob("*"):
            if item.is_file() or item.is_dir():
                children.append(item)
            if len(children) >= limit:
                break
    except OSError:
        return children
    return children


def _safe_json_dict(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _safe_text_lower(path: Path, *, limit: int = 65_536) -> str:
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:limit].lower()
    except OSError:
        return ""


def _profile_config_paths(roots: MemoryOSRoots) -> list[Path]:
    candidates = [
        roots.hermes_home / "config.json",
        roots.hermes_home / "config.yaml",
        roots.hermes_home / "config.yml",
        roots.hermes_home / "settings.json",
    ]
    if roots.profile:
        candidates.extend(
            [
                roots.hermes_home / "profiles" / roots.profile / "config.json",
                roots.hermes_home / "profiles" / roots.profile / "config.yaml",
                roots.hermes_home / "profiles" / roots.profile / "config.yml",
            ]
        )
    return [path for path in candidates if path.is_file()]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL file, return list of parsed dicts."""
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def _read_candidate_triage_records(roots: MemoryOSRoots) -> list[dict[str, Any]]:
    """Read candidate_triage.jsonl, newest first."""
    path = roots.memory_os_root / "crystallized" / "candidate_triage.jsonl"
    records = _read_jsonl(path)
    records.reverse()  # newest first
    return records


def _candidate_effective_state(
    candidate: dict[str, Any],
    triage_records: list[dict[str, Any]],
) -> str:
    """Resolve effective state for a raw candidate dict (JSONL line)."""
    cid = str(candidate.get("candidate_id") or "")
    if not cid:
        return ""
    for rec in triage_records:
        if str(rec.get("candidate_id") or "") == cid:
            return str(rec.get("target_state") or "")
    return str(candidate.get("bridge_state") or "")


def _active_candidate_count(
    records: list[dict[str, Any]],
    triage_records: list[dict[str, Any]],
) -> int:
    """Return count of candidates NOT tagged as fleeting."""
    return sum(
        1 for c in records
        if _candidate_effective_state(c, triage_records) != "fleeting"
    )


def _safe_jobs(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    jobs = loaded.get("jobs", loaded) if isinstance(loaded, dict) else loaded
    return [item for item in jobs if isinstance(item, dict)] if isinstance(jobs, list) else []


def _proposal_queue_items(roots: MemoryOSRoots) -> list[dict[str, Any]]:
    loaded = _safe_json_dict(roots.hermes_home / "system-modules" / "proposal_queue" / "queue.json")
    value = loaded.get("items") or loaded.get("proposals") or loaded.get("queue")
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [item for item in value.values() if isinstance(item, dict)]
    return []


def _candidate_queue_records(roots: MemoryOSRoots) -> list[dict[str, Any]]:
    return _read_jsonl(roots.memory_os_root / "crystallized" / "candidates.jsonl")


def _memory_os_event_records(roots: MemoryOSRoots, *, limit: int) -> list[dict[str, Any]]:
    event_root = roots.memory_os_root / "events"
    if not event_root.exists():
        return []
    records: list[dict[str, Any]] = []
    try:
        paths = sorted(event_root.glob("*/*.jsonl"))
    except OSError:
        return []
    for path in paths[-max(int(limit), 1):]:
        for record in _read_jsonl(path):
            safe_ref = record.get("safe_ref") if isinstance(record.get("safe_ref"), dict) else {}
            records.append(
                {
                    "created_at": str(record.get("created_at") or record.get("ts") or ""),
                    "source": str(record.get("source") or ""),
                    "kind": str(record.get("kind") or ""),
                    "safe_ref": {
                        "session_id": str(safe_ref.get("session_id") or ""),
                        "platform": str(safe_ref.get("platform") or ""),
                    },
                }
            )
            if len(records) >= max(int(limit), 1):
                return records
    return records


def _count_by_key(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(key) or "")
        if value:
            counts[value] = counts.get(value, 0) + 1
    return counts


def _latest_record_time(records: list[dict[str, Any]]) -> str:
    for record in reversed(records):
        for key in ("created_at", "observed_at", "completed_at", "run_time", "timestamp", "ts"):
            value = record.get(key)
            if value:
                return str(value)[:80]
    return ""


def _latest_status(records: list[dict[str, Any]]) -> str:
    for record in reversed(records):
        value = record.get("status") or record.get("latest_status")
        if value:
            return str(value)
    return ""


def _latest_reason(records: list[dict[str, Any]]) -> str:
    for record in reversed(records):
        value = record.get("reason") or record.get("latest_reason") or record.get("skip_reason")
        if value:
            return str(value)
    return ""


def _status_count(records: list[dict[str, Any]], status: str) -> int:
    return sum(1 for record in records if str(record.get("status") or record.get("latest_status") or "") == status)


def _actual_send_count(records: list[dict[str, Any]]) -> int:
    count = 0
    for record in records:
        boundary = record.get("boundary") if isinstance(record.get("boundary"), dict) else {}
        if record.get("actual_send") is True or _any_true(boundary.get("actual_send")):
            count += 1
    return count


def _mailbox_cooldown_active(roots: MemoryOSRoots, root: Path | None) -> bool:
    candidates = [
        roots.hermes_home / "system-modules" / "mailbox" / "cooldown.json",
        roots.hermes_home / "system-modules" / "mailbox" / "cooldown.lock",
    ]
    if root:
        candidates.extend([root / "cooldown.json", root / "cooldown.lock"])
    return any(path.exists() for path in candidates)


def _mcp_config_counts(path: Path) -> dict[str, int]:
    loaded = _safe_json_dict(path)
    servers = _mcp_server_values(loaded)
    healthy_count = 0
    failed_count = 0
    for server in servers:
        if not isinstance(server, dict):
            continue
        status = str(server.get("status") or server.get("health") or "").lower()
        if status in {"ok", "healthy", "running", "available"}:
            healthy_count += 1
        if status in {"error", "failed", "unhealthy", "timeout"}:
            failed_count += 1
    return {"server_count": len(servers), "healthy_count": healthy_count, "failed_server_count": failed_count}


def _mcp_server_values(loaded: dict[str, Any]) -> list[Any]:
    for key in ("mcpServers", "servers", "mcp_servers"):
        value = loaded.get(key)
        if isinstance(value, dict):
            return list(value.values())
        if isinstance(value, list):
            return value
    if loaded and all(isinstance(value, dict) for value in loaded.values()):
        return list(loaded.values())
    return []


def _runtime_log_files(roots: MemoryOSRoots) -> list[Path]:
    candidates = [roots.hermes_home / "logs", roots.hermes_home / "system" / "logs"]
    files: dict[str, Path] = {}
    for root in candidates:
        if root.is_dir():
            try:
                for item in root.rglob("*"):
                    if item.is_file():
                        files[str(item.resolve())] = item
            except OSError:
                continue
    for root_file in (roots.hermes_home / "gateway.log", roots.hermes_home / "errors.log", roots.hermes_home / "error.log"):
        if root_file.is_file():
            files[str(root_file.resolve())] = root_file
    return list(files.values())


def _first_named_file(files: list[Path], names: set[str]) -> Path | None:
    lowered = {name.lower() for name in names}
    for path in sorted(files, key=lambda item: item.stat().st_mtime, reverse=True):
        if path.name.lower() in lowered:
            return path
    return None


def _latest_age_seconds(paths: list[Path]) -> int | None:
    present = [path for path in paths if path.exists()]
    if not present:
        return None
    latest = max(present, key=lambda path: path.stat().st_mtime)
    try:
        mtime = datetime.fromtimestamp(latest.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None
    return max(int((datetime.now(timezone.utc) - mtime).total_seconds()), 0)


def _age_seconds_from_iso(value: str) -> int | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(int((datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()), 0)


def _mtime_iso(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except OSError:
        return ""


def _safe_size(path: Path | None) -> int:
    if path is None:
        return 0
    try:
        return int(path.stat().st_size)
    except OSError:
        return 0


def _cron_output_summary(output_root: Path, jobs: list[dict[str, Any]]) -> dict[str, Any]:
    jobs_by_id = {str(job.get("id") or ""): job for job in jobs if job.get("id")}
    entries = _cron_output_entries(output_root, jobs_by_id)
    failures = [entry for entry in entries if entry["status"] == "failure"]
    external_failures = [entry for entry in failures if entry["owner_system"] != "memory-os"]
    latest_success = next((entry for entry in entries if entry["status"] == "success"), {})
    latest_failure = failures[0] if failures else {}
    return {
        "latest_success_at": str(latest_success.get("run_time") or ""),
        "latest_failure_at": str(latest_failure.get("run_time") or ""),
        "latest_failure_job": str(latest_failure.get("job_name") or ""),
        "latest_failure_reason": str(latest_failure.get("reason") or ""),
        "latest_failure_deliver": bool(latest_failure.get("deliver")) if latest_failure else False,
        "latest_failure_owner_system": str(latest_failure.get("owner_system") or ""),
        "failure_count": len(failures),
        "external_failure_count": len(external_failures),
        "timeout_failure_count": sum(1 for entry in failures if entry.get("timeout") is True),
        "external_failure_jobs": [
            {
                "job_name": entry["job_name"],
                "job_id": entry["job_id"],
                "owner_system": entry["owner_system"],
                "deliver": entry["deliver"],
                "run_time": entry["run_time"],
                "reason": entry["reason"],
            }
            for entry in external_failures[:10]
        ],
    }


def _cron_output_entries(output_root: Path, jobs_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    if not output_root.exists():
        return []
    files = sorted((item for item in output_root.rglob("*.md") if item.is_file()), key=lambda item: item.stat().st_mtime, reverse=True)
    entries: list[dict[str, Any]] = []
    for path in files[:200]:
        parsed = _parse_cron_output_file(path)
        job = jobs_by_id.get(parsed["job_id"], {})
        if not parsed["job_name"]:
            parsed["job_name"] = str(job.get("name") or path.parent.name)
        parsed["deliver"] = bool(job.get("deliver"))
        parsed["owner_system"] = "memory-os" if _is_memory_os_cron_job(job) or parsed["job_name"].startswith("memory-os-") else "hermes"
        entries.append(parsed)
    return entries


def _parse_cron_output_file(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")[:8192]
    except OSError:
        text = ""
    lower = text.lower()
    status_line = _markdown_field(text, "Status")
    failed = "failed" in status_line.lower() or "script timed out" in lower or "timed out after" in lower
    timeout = "timed out" in lower
    return {
        "job_name": _cron_job_title(text),
        "job_id": _markdown_field(text, "Job ID") or path.parent.name,
        "run_time": _markdown_field(text, "Run Time") or _run_time_from_filename(path),
        "status": "failure" if failed else "success",
        "timeout": timeout,
        "reason": _cron_failure_reason(text, timeout=timeout, failed=failed),
        "deliver": False,
        "owner_system": "hermes",
    }


def _cron_job_title(text: str) -> str:
    for line in text.splitlines()[:8]:
        stripped = line.strip()
        if stripped.lower().startswith("# cron job:"):
            return stripped.split(":", 1)[1].strip()
    return ""


def _markdown_field(text: str, field: str) -> str:
    needle = f"**{field}:**"
    for line in text.splitlines()[:12]:
        stripped = line.strip()
        if stripped.lower().startswith(needle.lower()):
            return stripped[len(needle):].strip()
    return ""


def _cron_failure_reason(text: str, *, timeout: bool, failed: bool) -> str:
    if timeout:
        for line in text.splitlines():
            if "timed out" in line.lower():
                return _bounded_reason(line)
        return "script timed out"
    if failed:
        return "script failed"
    return ""


def _bounded_reason(line: str) -> str:
    cleaned = str(line or "").strip()
    if ":" in cleaned:
        left, _right = cleaned.split(":", 1)
        cleaned = left.strip()
    return cleaned[:180]


def _run_time_from_filename(path: Path) -> str:
    return path.stem.replace("_", " ")


def _is_memory_os_cron_job(job: dict[str, Any]) -> bool:
    name = str(job.get("name") or "")
    script = str(job.get("script") or "")
    return name.startswith("memory-os-") or script.startswith("memory_os_cron_")


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
