"""Append-only governance projections over read-only host signals."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .execution_gate import complete_execution_gate_envelope, resolve_execution_gate_permit
from .signal_collectors import collect_signal_sources
from .store import MemoryOSStore
from .roots import MemoryOSRoots


MEMORY_PROJECTION_SCHEMA_VERSION = "memory-os.memory_projection.v0"
MEMORY_PROJECTION_RECORD_SCHEMA_VERSION = "memory-os.memory_projection_record.v0"
PROJECTION_LANE_ID = "memory_projection_collect"
PROJECTION_RISK_CLASS = "governance_projection"


def memory_projection_records_path(roots: MemoryOSRoots) -> Path:
    return roots.memory_os_root / "system" / "memory_projections.jsonl"


def memory_projection_summary_path(roots: MemoryOSRoots) -> Path:
    return roots.memory_os_root / "system" / "memory_projection_summary.json"


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
    records = _projection_records_from_collection(
        store.roots,
        collection,
        execution_envelope_id=execution_envelope_id if automatic else "",
        live_closure_eligible=automatic,
    )
    for record in records:
        _append_jsonl(memory_projection_records_path(store.roots), record)
    summary = _write_projection_summary(store.roots)
    if automatic:
        complete_execution_gate_envelope(
            store,
            envelope_id=execution_envelope_id,
            lane_id=PROJECTION_LANE_ID,
            execution_status="ok" if not _any_true({"collection": collection, "records": records}) else "boundary_true",
            postcheck={
                "boundary": _false_boundary(),
                "written_count": len(records),
                "payload_schema_violation_count": int(collection.get("payload_schema_violation_count") or 0),
            },
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
        "live_closure_eligible": automatic,
        "summary": summary,
        "raw_body_included": False,
        "boundary": _false_boundary(),
    }


def memory_projection_status(roots: MemoryOSRoots) -> dict[str, Any]:
    records = _read_jsonl(memory_projection_records_path(roots))
    latest = records[-1] if records else {}
    return {
        "schema_version": "memory-os.memory_projection_status.v0",
        "status": "ok" if records else "missing",
        "projection_count": len(records),
        "latest_projection_id": str(latest.get("projection_id") or ""),
        "latest_source_key": str(latest.get("source_key") or ""),
        "latest_created_at": str(latest.get("created_at") or ""),
        "boundary_true_count": sum(1 for record in records if _any_true(record.get("boundary"))),
        "raw_body_included": any(record.get("raw_body_included") is True for record in records),
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
        projection_id = _projection_id(signal)
        records.append(
            {
                "schema_version": MEMORY_PROJECTION_RECORD_SCHEMA_VERSION,
                "projection_id": projection_id,
                "created_at": now,
                "host_id": str(signal.get("host_id") or collection.get("host_id") or ""),
                "hermes_home_ref": str(signal.get("hermes_home_ref") or roots.hermes_home),
                "profile_id": str(signal.get("profile_id") or roots.profile or "default"),
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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return status


def _projection_id(signal: dict[str, Any]) -> str:
    material = json.dumps(
        {
            "source_key": signal.get("source_key"),
            "source_hash": signal.get("source_hash"),
            "created_at": signal.get("created_at"),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return "mproj_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]


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
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
        handle.write("\n")


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
