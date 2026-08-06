"""Append-only governance projections over read-only host signals."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .execution_gate import any_boundary_true, complete_execution_gate_envelope, resolve_execution_gate_permit
from .jsonl_io import append_jsonl_locked, read_jsonl_result, write_json_atomic
from .signal_collectors import collect_signal_sources
from .signal_source_registry import signal_source_specs
from .store import MemoryOSStore
from .roots import MemoryOSRoots
from .structural_write_gate import append_governed_jsonl


MEMORY_PROJECTION_SCHEMA_VERSION = "memory-os.memory_projection.v0"
MEMORY_PROJECTION_RECORD_SCHEMA_VERSION = "memory-os.memory_projection_record.v0"
MEMORY_PROJECTION_COMPACTION_SCHEMA_VERSION = "memory-os.memory_projection_compaction.v0"
PROJECTION_LANE_ID = "memory_projection_collect"
PROJECTION_RISK_CLASS = "governance_projection"


def memory_projection_records_path(roots: MemoryOSRoots) -> Path:
    return roots.memory_os_root / "system" / "memory_projections.jsonl"


def memory_projection_summary_path(roots: MemoryOSRoots) -> Path:
    return roots.memory_os_root / "system" / "memory_projection_summary.json"


def memory_projection_compactions_path(roots: MemoryOSRoots) -> Path:
    return roots.memory_os_root / "system" / "memory_projection_compactions.jsonl"


def compact_memory_projection_records(
    roots: MemoryOSRoots,
    *,
    keep_latest_status_per_source: int = 3,
    apply: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    started = now or datetime.now(timezone.utc)
    records = _read_jsonl(memory_projection_records_path(roots))
    keep_latest = max(int(keep_latest_status_per_source), 0)
    short_lived_by_scope: dict[str, list[int]] = {}
    retention_class_counts: dict[str, int] = {}
    for index, record in enumerate(records):
        retention_class = str(record.get("retention_class") or "unknown")
        retention_class_counts[retention_class] = retention_class_counts.get(retention_class, 0) + 1
        if retention_class == "short_lived_status" and not _projection_safety_preserved(record):
            short_lived_by_scope.setdefault(_status_compaction_scope(record), []).append(index)

    keep_indices: set[int] = set()
    for index, record in enumerate(records):
        if str(record.get("retention_class") or "") != "short_lived_status":
            keep_indices.add(index)
        if _projection_safety_preserved(record):
            keep_indices.add(index)
    for indices in short_lived_by_scope.values():
        keep_indices.update(indices[-keep_latest:] if keep_latest else [])

    kept = [record for index, record in enumerate(records) if index in keep_indices]
    archived = [record for index, record in enumerate(records) if index not in keep_indices]
    compaction_id = "mproj_compact_" + hashlib.sha256(
        f"{started.isoformat()}:{len(records)}:{len(archived)}".encode("utf-8")
    ).hexdigest()[:20]
    archive_rel = ""
    if apply and archived:
        archive_path = roots.memory_os_root / "archive" / "memory_projection" / f"{compaction_id}.jsonl"
        _write_jsonl_atomic(archive_path, archived)
        archive_rel = str(archive_path.relative_to(roots.memory_os_root)).replace("\\", "/")
        _write_jsonl_atomic(memory_projection_records_path(roots), kept)
    completed = datetime.now(timezone.utc)
    report = {
        "schema_version": MEMORY_PROJECTION_COMPACTION_SCHEMA_VERSION,
        "compaction_id": compaction_id,
        "status": "ok",
        "dry_run": not apply,
        "started_at": started.isoformat().replace("+00:00", "Z"),
        "completed_at": completed.isoformat().replace("+00:00", "Z"),
        "input_count": len(records),
        "output_count": len(kept),
        "archived_count": len(archived),
        "archive_path": archive_rel,
        "keep_latest_status_per_source": keep_latest,
        "retention_class_counts": retention_class_counts,
        "boundary_true_preserved_count": sum(1 for record in kept if any_boundary_true(record.get("boundary"))),
        "raw_body_included_preserved_count": sum(1 for record in kept if record.get("raw_body_included") is True),
        "boundary_true_archived_count": sum(1 for record in archived if any_boundary_true(record.get("boundary"))),
        "raw_body_included_archived_count": sum(1 for record in archived if record.get("raw_body_included") is True),
        "boundary": _false_boundary(),
        "raw_body_included": False,
    }
    if apply:
        _append_jsonl(memory_projection_compactions_path(roots), report)
    return report


def memory_projection_retention_status(roots: MemoryOSRoots) -> dict[str, Any]:
    records = _read_jsonl(memory_projection_compactions_path(roots))
    latest = records[-1] if records else {}
    return {
        "schema_version": "memory-os.memory_projection_retention_status.v0",
        "status": "ok" if records else "missing",
        "compaction_count": len(records),
        "latest_compaction_id": str(latest.get("compaction_id") or ""),
        "latest_dry_run": latest.get("dry_run"),
        "latest_input_count": int(latest.get("input_count") or 0),
        "latest_output_count": int(latest.get("output_count") or 0),
        "latest_archived_count": int(latest.get("archived_count") or 0),
        "latest_archive_path": str(latest.get("archive_path") or ""),
        "latest_boundary_true_archived_count": int(latest.get("boundary_true_archived_count") or 0),
        "latest_raw_body_included_archived_count": int(latest.get("raw_body_included_archived_count") or 0),
        "latest_boundary_true_preserved_count": int(latest.get("boundary_true_preserved_count") or 0),
        "latest_raw_body_included_preserved_count": int(latest.get("raw_body_included_preserved_count") or 0),
        "raw_body_included": any(record.get("raw_body_included") is True for record in records),
        "boundary_true_count": sum(1 for record in records if any_boundary_true(record.get("boundary"))),
    }


def collect_and_project_signals(
    store: MemoryOSStore,
    *,
    host_capabilities: dict[str, Any],
    trigger_type: str,
    execution_envelope_id: str = "",
    expected_scope: dict[str, Any] | None = None,
    manual_run_ref: str = "",
    collector_overrides: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    store.initialize()
    automatic = str(trigger_type or "") not in {"manual_cli", "manual_test"}
    resolution = {"status": "not_required", "reason": "manual_cli_not_live_closure"}
    if automatic:
        resolution = resolve_execution_gate_permit(
            store.roots,
            envelope_id=execution_envelope_id,
            lane_id=PROJECTION_LANE_ID,
            risk_class=PROJECTION_RISK_CLASS,
            require_fresh=True,
            require_unused=True,
            expected_scope=expected_scope,
        )
        if resolution.get("status") != "valid":
            return {
                "schema_version": MEMORY_PROJECTION_SCHEMA_VERSION,
                "status": "blocked",
                "reason": str(resolution.get("reason") or "execution_gate_invalid"),
                "trigger_type": trigger_type,
                "execution_gate_resolution": resolution,
                "written_count": 0,
                "raw_body_included": False,
                "boundary": _false_boundary(),
            }
    collection = collect_signal_sources(
        store.roots,
        host_capabilities=host_capabilities,
        trigger_type=trigger_type,
        execution_envelope_id=execution_envelope_id if automatic else "",
        manual_run_ref=manual_run_ref,
        collector_overrides=collector_overrides,
    )
    candidate_records = _projection_records_from_collection(
        store.roots,
        collection,
        execution_envelope_id=execution_envelope_id if automatic else "",
        live_closure_eligible=automatic,
    )
    existing_dedup_keys = _existing_dedup_keys(store.roots)
    records = [record for record in candidate_records if record.get("dedup_key") not in existing_dedup_keys]
    duplicate_skipped_count = len(candidate_records) - len(records)
    for record in records:
        if automatic:
            append_governed_jsonl(
                store,
                memory_projection_records_path(store.roots),
                record,
                write_owner="automatic",
                lane_id=PROJECTION_LANE_ID,
                risk_class=PROJECTION_RISK_CLASS,
                execution_gate_envelope_id=execution_envelope_id,
                scope_hash=str(resolution.get("scope_hash") or ""),
            )
        else:
            _append_jsonl(memory_projection_records_path(store.roots), record)
    summary = _write_projection_summary(store.roots)
    if automatic:
        postcheck = {
            "boundary": _false_boundary(),
            "written_count": len(records),
            "duplicate_skipped_count": duplicate_skipped_count,
            "payload_schema_violation_count": int(collection.get("payload_schema_violation_count") or 0),
        }
        complete_execution_gate_envelope(
            store,
            envelope_id=execution_envelope_id,
            lane_id=PROJECTION_LANE_ID,
            execution_status="ok" if not any_boundary_true(postcheck["boundary"]) else "boundary_true",
            postcheck=postcheck,
            result_summary={"projection_count": int(summary.get("projection_count") or 0)},
        )
    return {
        "schema_version": MEMORY_PROJECTION_SCHEMA_VERSION,
        "status": "warning" if collection.get("status") == "warning" else "ok",
        "trigger_type": trigger_type,
        "execution_gate_resolution": resolution,
        "collection_status": collection.get("status"),
        "record_count": int(collection.get("record_count") or 0),
        "written_count": len(records),
        "duplicate_skipped_count": duplicate_skipped_count,
        "live_closure_eligible": automatic,
        "summary": summary,
        "raw_body_included": False,
        "boundary": _false_boundary(),
    }


def memory_projection_status(roots: MemoryOSRoots) -> dict[str, Any]:
    records_result = read_jsonl_result(
        memory_projection_records_path(roots),
        component="memory_projection",
        operation="status_read_records",
    )
    records = records_result.records
    latest = records[-1] if records else {}
    dedup_aware_records = [record for record in records if record.get("dedup_key")]
    source_key_counts: dict[str, int] = {}
    source_payload_fields: dict[str, set[str]] = {}
    for record in records:
        source_key = str(record.get("source_key") or "")
        if source_key:
            source_key_counts[source_key] = source_key_counts.get(source_key, 0) + 1
            payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
            source_payload_fields.setdefault(source_key, set()).update(str(key) for key in payload)
    registered_source_keys = sorted(spec.source_key for spec in signal_source_specs())
    projected_source_keys = sorted(source_key_counts)
    registered_source_missing_keys = [key for key in registered_source_keys if key not in source_key_counts]
    scoped_source_hashes = [
        f"{record.get('source_scope_ref')}:{record.get('source_hash')}"
        for record in dedup_aware_records
        if record.get("source_scope_ref") and record.get("source_hash")
    ]
    dedup_keys = [str(record.get("dedup_key") or "") for record in dedup_aware_records if record.get("dedup_key")]
    return {
        "schema_version": "memory-os.memory_projection_status.v0",
        "status": "ok" if records else "missing",
        "projection_count": len(records),
        "latest_projection_id": str(latest.get("projection_id") or ""),
        "latest_source_key": str(latest.get("source_key") or ""),
        "latest_created_at": str(latest.get("created_at") or ""),
        "registered_source_count": len(registered_source_keys),
        "unique_source_count": len(projected_source_keys),
        "source_key_counts": source_key_counts,
        "source_payload_fields": {key: sorted(values) for key, values in sorted(source_payload_fields.items())},
        "projected_source_keys": projected_source_keys,
        "registered_source_missing_count": len(registered_source_missing_keys),
        "registered_source_missing_keys": registered_source_missing_keys,
        "boundary_true_count": sum(1 for record in records if any_boundary_true(record.get("boundary"))),
        "source_scope_missing_count": sum(1 for record in dedup_aware_records if not record.get("source_scope_ref")),
        "legacy_without_source_scope_count": sum(1 for record in records if not record.get("dedup_key") and not record.get("source_scope_ref")),
        "duplicate_source_hash_count": len(scoped_source_hashes) - len(set(scoped_source_hashes)),
        "duplicate_dedup_key_count": len(dedup_keys) - len(set(dedup_keys)),
        "raw_body_included": any(record.get("raw_body_included") is True for record in records),
        "suppressed_error_count": records_result.suppressed_error_count,
        "recent_error_codes": records_result.recent_error_codes[-5:],
    }


def _projection_records_from_collection(
    roots: MemoryOSRoots,
    collection: dict[str, Any],
    *,
    execution_envelope_id: str,
    live_closure_eligible: bool,
) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    records: list[dict[str, Any]] = []
    for signal in collection.get("records", []) if isinstance(collection.get("records"), list) else []:
        if not isinstance(signal, dict) or signal.get("status") == "blocked":
            continue
        payload = signal.get("payload") if isinstance(signal.get("payload"), dict) else {}
        source_scope_ref = _source_scope_ref(roots, collection, signal)
        dedup_key = _projection_dedup_key(signal, source_scope_ref)
        projection_id = _projection_id(dedup_key)
        records.append(
            {
                "schema_version": MEMORY_PROJECTION_RECORD_SCHEMA_VERSION,
                "projection_id": projection_id,
                "dedup_key": dedup_key,
                "created_at": now,
                "host_id": str(signal.get("host_id") or collection.get("host_id") or ""),
                "hermes_home_ref": str(signal.get("hermes_home_ref") or roots.hermes_home),
                "profile_id": str(signal.get("profile_id") or roots.profile or "default"),
                "source_scope_ref": source_scope_ref,
                "source_key": str(signal.get("source_key") or ""),
                "source_hash": str(signal.get("source_hash") or ""),
                "projection_type": _projection_type(signal),
                "semantic_facets": _semantic_facets(signal),
                "retention_class": str(signal.get("retention_class") or "short_lived_status"),
                "payload_schema": str(signal.get("payload_schema") or ""),
                "payload": payload,
                "execution_envelope_id": execution_envelope_id,
                "trigger_type": str(collection.get("trigger_type") or ""),
                "manual_run_ref": str(collection.get("manual_run_ref") or ""),
                "live_closure_eligible": live_closure_eligible,
                "raw_body_included": False,
                "boundary": _false_boundary(),
            }
        )
    return records


def _write_projection_summary(roots: MemoryOSRoots) -> dict[str, Any]:
    status = memory_projection_status(roots)
    path = memory_projection_summary_path(roots)
    write_json_atomic(path, status)
    return status


def _existing_dedup_keys(roots: MemoryOSRoots) -> set[str]:
    keys: set[str] = set()
    for record in _read_jsonl(memory_projection_records_path(roots)):
        key = _dedup_key_for_existing_record(record)
        if key:
            keys.add(key)
    return keys


def _dedup_key_for_existing_record(record: dict[str, Any]) -> str:
    if record.get("dedup_key"):
        return str(record.get("dedup_key") or "")
    source_key = str(record.get("source_key") or "")
    source_hash = str(record.get("source_hash") or "")
    if not source_key or not source_hash:
        return ""
    source_scope_ref = str(record.get("source_scope_ref") or "") or _legacy_source_scope_ref(record)
    return _projection_dedup_key({"source_key": source_key, "source_hash": source_hash}, source_scope_ref)


def _legacy_source_scope_ref(record: dict[str, Any]) -> str:
    material = {
        "host_id": str(record.get("host_id") or ""),
        "hermes_home_ref": str(record.get("hermes_home_ref") or ""),
        "profile_id": str(record.get("profile_id") or "default"),
        "source_key": str(record.get("source_key") or ""),
    }
    digest = hashlib.sha256(json.dumps(material, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return f"scope_{digest}"


def _source_scope_ref(roots: MemoryOSRoots, collection: dict[str, Any], signal: dict[str, Any]) -> str:
    material = {
        "host_id": str(signal.get("host_id") or collection.get("host_id") or ""),
        "hermes_home_ref": str(signal.get("hermes_home_ref") or roots.hermes_home),
        "profile_id": str(signal.get("profile_id") or roots.profile or "default"),
        "source_key": str(signal.get("source_key") or ""),
    }
    digest = hashlib.sha256(json.dumps(material, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return f"scope_{digest}"


def _projection_dedup_key(signal: dict[str, Any], source_scope_ref: str) -> str:
    material = json.dumps(
        {
            "source_scope_ref": source_scope_ref,
            "source_key": signal.get("source_key"),
            "source_hash": signal.get("source_hash"),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return "mproj_dedup_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def _projection_id(dedup_key: str) -> str:
    return "mproj_" + hashlib.sha256(str(dedup_key).encode("utf-8")).hexdigest()[:20]


def _projection_type(signal: dict[str, Any]) -> str:
    source_key = str(signal.get("source_key") or "")
    if source_key in {"owner_actions", "memory_sources_feedback"}:
        return "governance_signal"
    if source_key in {"execution_gate_envelopes", "session_mirror_apply", "hermes_cron_jobs"}:
        return "operational_signal"
    return "signal_observation"


def _semantic_facets(signal: dict[str, Any]) -> list[str]:
    facets = ["left_brain_signal", str(signal.get("source_key") or "unknown")]
    projection_policy = str(signal.get("projection_policy") or "")
    if projection_policy:
        facets.append(projection_policy)
    return facets


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    append_jsonl_locked(path, record, durable=True)


def _write_jsonl_atomic(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.{hashlib.sha256(str(datetime.now(timezone.utc).timestamp()).encode('utf-8')).hexdigest()[:12]}.tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
                handle.write("\n")
        tmp_path.replace(path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


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


def _projection_safety_preserved(record: dict[str, Any]) -> bool:
    return any_boundary_true(record.get("boundary")) or record.get("raw_body_included") is True


def _status_compaction_scope(record: dict[str, Any]) -> str:
    return ":".join(
        [
            str(record.get("source_scope_ref") or ""),
            str(record.get("source_key") or ""),
        ]
    )
