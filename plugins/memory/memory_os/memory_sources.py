"""Memory Sources attribution ledger for live Memory-OS prefetch builds."""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .audit import append_audit
from .context_router import ContextSection
from .roots import MemoryOSRoots


SCHEMA_VERSION = "memory-os.memory_sources.v0"
LAST_SCHEMA_VERSION = "memory-os.memory_sources_last.v0"
HISTORY_SCHEMA_VERSION = "memory-os.memory_sources_history.v0"
STATS_SCHEMA_VERSION = "memory-os.memory_sources_stats.v0"
FEEDBACK_SCHEMA_VERSION = "memory-os.memory_sources_feedback.v0"
FEEDBACK_HISTORY_SCHEMA_VERSION = "memory-os.memory_sources_feedback_history.v0"
POLICY_SCHEMA_VERSION = "memory-os.memory_sources_policy.v0"
POLICY_APPLY_SCHEMA_VERSION = "memory-os.memory_sources_policy_apply.v0"

ALLOWED_FEEDBACK_RATINGS = {
    "useful",
    "irrelevant",
    "too_mechanistic",
    "missing_context",
    "overconfident",
    "needs_specific_recall",
    "clarification_selected",
    "clarification_rejected",
    "missing_candidate",
}

GUARD_RECALL_CLARIFICATION = "guard:recall_clarification"
GUARD_FOREGROUND_CONTROL = "guard:foreground_control"
GUARD_CANDIDATE_BOUNDARY = "guard:candidate_boundary"
SYNTHETIC_GUARD_IDS = {
    GUARD_RECALL_CLARIFICATION,
    GUARD_FOREGROUND_CONTROL,
    GUARD_CANDIDATE_BOUNDARY,
}

_ALLOWED_SOURCE_ID_PATTERNS = (
    re.compile(r"^event:[A-Za-z0-9_.:-]+$"),
    re.compile(r"^working:[A-Za-z0-9_.:-]+$"),
    re.compile(r"^candidate:[A-Za-z0-9_.:-]+$"),
    re.compile(r"^crystallized:[A-Za-z0-9_.:-]+$"),
    re.compile(r"^digest:[A-Za-z0-9_.:-]+$"),
    re.compile(r"^reflection_card:[A-Za-z0-9_.:-]+$"),
    re.compile(r"^governance_feedback:[A-Za-z0-9_.:-]+$"),
    re.compile(r"^proposal:[A-Za-z0-9_.:-]+$"),
    re.compile(r"^foreground_task:[A-Za-z0-9_.:-]+$"),
)

_FORBIDDEN_FIELD_NAMES = {
    "raw_prompt",
    "prompt",
    "query",
    "user_text",
    "assistant_text",
    "raw_body",
    "body",
    "content",
    "transcript",
    "private_body",
    "raw_transcript",
    "section_body",
    "preview",
    "file_path",
    "path",
    "cookie",
    "token",
    "secret",
    "credential",
}


def memory_sources_path(roots: MemoryOSRoots) -> Path:
    return roots.memory_os_root / "system" / "memory_sources.jsonl"


def memory_sources_feedback_path(roots: MemoryOSRoots) -> Path:
    return roots.memory_os_root / "system" / "memory_sources_feedback.jsonl"


def memory_sources_policy_path(roots: MemoryOSRoots) -> Path:
    return roots.hermes_home / "system-modules" / "memory_sources" / "policy.json"


def memory_sources_policy_applies_path(roots: MemoryOSRoots) -> Path:
    return roots.hermes_home / "system-modules" / "memory_sources" / "policy_applies.jsonl"


def read_memory_sources_policy(roots: MemoryOSRoots) -> dict[str, Any]:
    path = memory_sources_policy_path(roots)
    if not path.exists():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    if parsed.get("schema_version") != POLICY_SCHEMA_VERSION:
        return {}
    return parsed


def read_memory_sources_policy_apply_records(roots: MemoryOSRoots, *, limit: int = 20) -> list[dict[str, Any]]:
    path = memory_sources_policy_applies_path(roots)
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    if limit <= 0:
        return []
    return records[-limit:]


def normalize_memory_sources_config(config: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(config, dict):
        return {
            "enabled": False,
            "mode": "metadata_only",
            "retention_days": 30,
            "record_live_prefetch": True,
            "record_dry_run": False,
        }
    try:
        retention_days = int(config.get("retention_days") or 30)
    except (TypeError, ValueError):
        retention_days = 30
    return {
        "enabled": bool(config.get("enabled")),
        "mode": str(config.get("mode") or "metadata_only"),
        "retention_days": retention_days,
        "record_live_prefetch": bool(config.get("record_live_prefetch", True)),
        "record_dry_run": bool(config.get("record_dry_run", False)),
    }


def memory_sources_enabled(config: dict[str, Any] | None) -> bool:
    normalized = normalize_memory_sources_config(config)
    return bool(normalized.get("enabled")) and str(normalized.get("mode")) == "metadata_only"


def append_memory_source_record(roots: MemoryOSRoots, record: dict[str, Any]) -> Path:
    path = memory_sources_path(roots)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
        handle.write("\n")
    return path


def append_memory_source_feedback_record(roots: MemoryOSRoots, record: dict[str, Any]) -> Path:
    path = memory_sources_feedback_path(roots)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
        handle.write("\n")
    return path


def build_memory_source_record(
    *,
    roots: MemoryOSRoots,
    route_report: dict[str, Any],
    selected_sections: list[ContextSection],
    context_router_config: dict[str, Any],
    router_applied: bool,
    prefetch_mode: str,
    boundary: dict[str, bool] | None = None,
) -> dict[str, Any]:
    created_at = datetime.now(timezone.utc)
    route_available = bool(route_report.get("route"))
    route = str(route_report.get("route") or "unknown")
    route_reason_codes = [str(item) for item in route_report.get("route_reason_codes") or []]
    if not route_available:
        route_reason_codes.append("route_unavailable")
    router_mode = str(context_router_config.get("mode") or "disabled")
    if not router_applied and router_mode == "dry_run":
        route_reason_codes = _dedupe(route_reason_codes + ["router_dry_run_fallback"])
    selected_report = _selected_report(
        selected_sections,
        selected_entries=list(route_report.get("selected_sections") or []),
    )
    policy = read_memory_sources_policy(roots)
    policy_ref = _policy_ref(policy)
    return {
        "schema_version": SCHEMA_VERSION,
        "record_id": _new_record_id(created_at),
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
        "profile": roots.profile or "default",
        "query_class": route,
        "route": route,
        "route_reason_codes": route_reason_codes,
        "prefetch_mode": prefetch_mode,
        "context_router_mode": router_mode,
        "context_router_routes_applied": _context_router_routes_applied(context_router_config),
        "router_applied": bool(router_applied),
        "selected": selected_report,
        "dropped": _dropped_report(list(route_report.get("dropped_sections") or [])),
        "policy_ref": policy_ref,
        "policy_version": int(policy_ref.get("policy_version") or 0),
        "selected_chars_total": sum(int(item.get("chars", 0)) for item in selected_report),
        "dropped_count_total": len(route_report.get("dropped_sections") or []),
        "boundary": _boundary(boundary),
    }


def filter_safe_source_ids(section: ContextSection) -> list[str]:
    metadata = section.metadata if isinstance(section.metadata, dict) else {}
    raw_ids = metadata.get("source_ids") or []
    if isinstance(raw_ids, str):
        raw_ids = [raw_ids]
    result: list[str] = []
    for item in raw_ids:
        value = str(item).strip()
        if not value:
            continue
        if value in SYNTHETIC_GUARD_IDS or any(pattern.match(value) for pattern in _ALLOWED_SOURCE_ID_PATTERNS):
            result.append(value)
    return _dedupe(result)


def read_memory_source_records(roots: MemoryOSRoots, *, limit: int = 20) -> list[dict[str, Any]]:
    path = memory_sources_path(roots)
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    if limit <= 0:
        return []
    return records[-limit:]


def read_memory_source_feedback_records(roots: MemoryOSRoots, *, limit: int = 20) -> list[dict[str, Any]]:
    path = memory_sources_feedback_path(roots)
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    if limit <= 0:
        return []
    return records[-limit:]


def memory_sources_last_report(roots: MemoryOSRoots) -> dict[str, Any]:
    records = read_memory_source_records(roots, limit=1)
    return {
        "schema_version": LAST_SCHEMA_VERSION,
        "profile": roots.profile or "default",
        "status": "ok" if records else "warning",
        "code": "" if records else "memory_sources_empty",
        "record": records[0] if records else None,
    }


def memory_sources_feedback_last_report(
    roots: MemoryOSRoots,
    *,
    rating: str,
    note: str = "",
) -> dict[str, Any]:
    normalized_rating = _normalize_feedback_rating(rating)
    if normalized_rating not in ALLOWED_FEEDBACK_RATINGS:
        return {
            "schema_version": FEEDBACK_SCHEMA_VERSION,
            "profile": roots.profile or "default",
            "status": "error",
            "code": "invalid_rating",
            "allowed_ratings": sorted(ALLOWED_FEEDBACK_RATINGS),
        }
    source_records = read_memory_source_records(roots, limit=1)
    if not source_records:
        return {
            "schema_version": FEEDBACK_SCHEMA_VERSION,
            "profile": roots.profile or "default",
            "status": "error",
            "code": "memory_sources_empty",
            "message": "No Memory Sources attribution record exists for this profile.",
        }
    source = source_records[-1]
    created_at = datetime.now(timezone.utc)
    record = {
        "schema_version": FEEDBACK_SCHEMA_VERSION,
        "feedback_id": _new_feedback_id(created_at),
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
        "profile": roots.profile or "default",
        "memory_source_record_id": str(source.get("record_id") or ""),
        "memory_source_created_at": str(source.get("created_at") or ""),
        "route": str(source.get("route") or "unknown"),
        "query_class": str(source.get("query_class") or "unknown"),
        "rating": normalized_rating,
        "note": _bounded_note(note),
    }
    append_memory_source_feedback_record(roots, record)
    append_audit(
        roots.audit_path,
        action="memory_sources_feedback_recorded",
        status="ok",
        target=str(memory_sources_feedback_path(roots)),
        details={
            "feedback_id": record["feedback_id"],
            "memory_source_record_id": record["memory_source_record_id"],
            "rating": record["rating"],
            "route": record["route"],
        },
    )
    return {
        "schema_version": FEEDBACK_SCHEMA_VERSION,
        "profile": roots.profile or "default",
        "status": "ok",
        "record": record,
    }


def memory_sources_feedback_history_report(roots: MemoryOSRoots, *, limit: int) -> dict[str, Any]:
    safe_limit = max(int(limit), 0)
    records = read_memory_source_feedback_records(roots, limit=safe_limit)
    return {
        "schema_version": FEEDBACK_HISTORY_SCHEMA_VERSION,
        "profile": roots.profile or "default",
        "limit": safe_limit,
        "record_count": len(records),
        "records": records,
    }


def memory_sources_history_report(roots: MemoryOSRoots, *, limit: int) -> dict[str, Any]:
    safe_limit = max(int(limit), 0)
    records = read_memory_source_records(roots, limit=safe_limit)
    return {
        "schema_version": HISTORY_SCHEMA_VERSION,
        "profile": roots.profile or "default",
        "limit": safe_limit,
        "record_count": len(records),
        "records": records,
    }


def memory_sources_stats_report(roots: MemoryOSRoots, *, hours: int) -> dict[str, Any]:
    path = memory_sources_path(roots)
    feedback_path = memory_sources_feedback_path(roots)
    policy = read_memory_sources_policy(roots)
    policy_applies = read_memory_sources_policy_apply_records(roots, limit=1_000_000)
    records = _records_since(read_memory_source_records(roots, limit=1_000_000), hours=max(int(hours), 0))
    feedback_records = _records_since(
        read_memory_source_feedback_records(roots, limit=1_000_000),
        hours=max(int(hours), 0),
    )
    selected_source_classes: Counter[str] = Counter()
    dropped_reasons: Counter[str] = Counter()
    route_distribution: Counter[str] = Counter()
    query_class_distribution: Counter[str] = Counter()
    feedback_rating_distribution: Counter[str] = Counter()
    selected_chars: list[int] = []
    boundary_true_count = 0
    forbidden_findings: list[dict[str, Any]] = []
    for record in records:
        route_distribution[str(record.get("route") or "unknown")] += 1
        query_class_distribution[str(record.get("query_class") or "unknown")] += 1
        selected_chars.append(int(record.get("selected_chars_total") or 0))
        for section in record.get("selected", []) if isinstance(record.get("selected"), list) else []:
            if isinstance(section, dict):
                selected_source_classes[str(section.get("source_class") or "unknown")] += 1
        for section in record.get("dropped", []) if isinstance(record.get("dropped"), list) else []:
            if isinstance(section, dict):
                for reason in section.get("reason_codes", []) if isinstance(section.get("reason_codes"), list) else []:
                    dropped_reasons[str(reason)] += 1
        boundary = record.get("boundary") if isinstance(record.get("boundary"), dict) else {}
        if any(value is True for value in boundary.values()):
            boundary_true_count += 1
        forbidden_findings.extend(_forbidden_field_findings(record))
    for record in feedback_records:
        feedback_rating_distribution[str(record.get("rating") or "unknown")] += 1
    return {
        "schema_version": STATS_SCHEMA_VERSION,
        "profile": roots.profile or "default",
        "hours": max(int(hours), 0),
        "ledger_path": str(path),
        "ledger_exists": path.exists(),
        "file_size_bytes": path.stat().st_size if path.exists() else 0,
        "feedback_ledger_path": str(feedback_path),
        "feedback_ledger_exists": feedback_path.exists(),
        "feedback_file_size_bytes": feedback_path.stat().st_size if feedback_path.exists() else 0,
        "policy_path": str(memory_sources_policy_path(roots)),
        "policy_present": bool(policy),
        "policy_version": int(policy.get("policy_version") or 0) if policy else 0,
        "latest_policy_apply_id": str(policy_applies[-1].get("apply_id") or "") if policy_applies else "",
        "policy_apply_count": len(policy_applies),
        "policy_actual_execute_count": sum(1 for record in policy_applies if bool(record.get("actual_execute"))),
        "policy_raw_body_included_count": sum(1 for record in policy_applies if bool(record.get("raw_body_included"))),
        "record_count": len(records),
        "feedback_count": len(feedback_records),
        "oldest_created_at": str(records[0].get("created_at", "")) if records else "",
        "newest_created_at": str(records[-1].get("created_at", "")) if records else "",
        "feedback_oldest_created_at": str(feedback_records[0].get("created_at", "")) if feedback_records else "",
        "feedback_newest_created_at": str(feedback_records[-1].get("created_at", "")) if feedback_records else "",
        "route_distribution": dict(route_distribution),
        "query_class_distribution": dict(query_class_distribution),
        "feedback_rating_distribution": dict(feedback_rating_distribution),
        "selected_source_class_distribution": dict(selected_source_classes),
        "dropped_reason_code_distribution": dict(dropped_reasons),
        "avg_selected_chars": round(sum(selected_chars) / len(selected_chars), 3) if selected_chars else 0.0,
        "max_selected_chars": max(selected_chars) if selected_chars else 0,
        "boundary_true_count": boundary_true_count,
        "forbidden_field_findings": forbidden_findings,
    }


def _new_record_id(created_at: datetime) -> str:
    return f"msrc_{created_at.strftime('%Y%m%dT%H%M%S%fZ')}_{uuid4().hex[:8]}"


def _new_feedback_id(created_at: datetime) -> str:
    return f"msfb_{created_at.strftime('%Y%m%dT%H%M%S%fZ')}_{uuid4().hex[:8]}"


def _normalize_feedback_rating(rating: str) -> str:
    return str(rating or "").strip().lower().replace("-", "_")


def _bounded_note(note: str, *, limit: int = 500) -> str:
    value = str(note or "").strip()
    if len(value) <= limit:
        return value
    return value[:limit]


def _selected_report(
    selected_sections: list[ContextSection],
    *,
    selected_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    entries_by_name: dict[str, list[dict[str, Any]]] = {}
    for entry in selected_entries:
        name = str(entry.get("section") or "")
        entries_by_name.setdefault(name, []).append(entry)
    result: list[dict[str, Any]] = []
    for section in selected_sections:
        entry = (entries_by_name.get(section.section) or [{}]).pop(0)
        result.append(
            {
                "heading": section.section,
                "source_class": section.source_class,
                "source_ids": filter_safe_source_ids(section),
                "chars": section.char_cost,
                "score": entry.get("score"),
                "reason_codes": [str(item) for item in entry.get("reason_codes", [])],
            }
        )
    return result


def _dropped_report(dropped_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for entry in dropped_entries:
        if not isinstance(entry, dict):
            continue
        result.append(
            {
                "heading": str(entry.get("section") or ""),
                "source_class": str(entry.get("source_class") or "unknown"),
                "count": 1,
                "chars": int(entry.get("char_cost") or 0),
                "score": entry.get("score"),
                "reason_codes": [str(item) for item in entry.get("reason_codes", [])],
            }
        )
    return result


def _context_router_routes_applied(config: dict[str, Any]) -> list[str]:
    if str(config.get("mode") or "") != "apply":
        return []
    return [str(item) for item in config.get("apply_routes", []) if str(item)]


def _boundary(boundary: dict[str, bool] | None) -> dict[str, bool]:
    source = boundary or {}
    return {
        "actual_send": bool(source.get("actual_send", False)),
        "actual_execute": bool(source.get("actual_execute", False)),
        "actual_identity_write": bool(source.get("actual_identity_write", False)),
        "actual_relationship_write": bool(source.get("actual_relationship_write", False)),
        "actual_crystallized_approval": bool(source.get("actual_crystallized_approval", False)),
        "hindsight_exported": bool(source.get("hindsight_exported", False)),
    }


def _records_since(records: list[dict[str, Any]], *, hours: int) -> list[dict[str, Any]]:
    if hours <= 0:
        return records
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    result: list[dict[str, Any]] = []
    for record in records:
        try:
            created_at = datetime.fromisoformat(str(record.get("created_at", "")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if created_at >= cutoff:
            result.append(record)
    return result


def _forbidden_field_findings(record: Any, *, path: str = "$") -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if isinstance(record, dict):
        for key, value in record.items():
            if str(key) in _FORBIDDEN_FIELD_NAMES:
                findings.append({"path": f"{path}.{key}", "field": str(key)})
                continue
            findings.extend(_forbidden_field_findings(value, path=f"{path}.{key}"))
    elif isinstance(record, list):
        for index, item in enumerate(record):
            findings.extend(_forbidden_field_findings(item, path=f"{path}[{index}]"))
    return findings


def _policy_ref(policy: dict[str, Any]) -> dict[str, Any]:
    if not policy or policy.get("schema_version") != POLICY_SCHEMA_VERSION:
        return {}
    return {
        "policy_id": str(policy.get("policy_id") or ""),
        "policy_version": int(policy.get("policy_version") or 0),
        "applied_from_proposal_id": str(policy.get("applied_from_proposal_id") or ""),
        "runtime_target": str(policy.get("runtime_target") or ""),
    }


def _dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        normalized = item.strip()
        if normalized and normalized not in seen:
            result.append(normalized)
            seen.add(normalized)
    return result
