"""Structural write gate for automatic Memory-OS JSONL writes."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .execution_gate import any_boundary_true, resolve_execution_gate_permit
from .store import MemoryOSStore, StoreError


STRUCTURAL_WRITE_GATE_SCHEMA_VERSION = "memory-os.structural_write_gate.v0"


def append_governed_jsonl(
    store: MemoryOSStore,
    path: Path,
    record: dict[str, Any],
    *,
    write_owner: str,
    lane_id: str,
    risk_class: str,
    execution_gate_envelope_id: str,
    scope_hash: str,
    allow_owner_action_without_envelope: bool = False,
) -> Path:
    """Append one JSONL record after validating the write-surface governance.

    Automatic lanes must carry a fresh, unused ExecutionGate permit matching
    lane/risk/scope. Owner-action writes can opt into a separate owner-gated
    path, but this helper does not silently treat missing envelopes as valid.
    """

    owner = str(write_owner or "").strip()
    destination = Path(path)
    _assert_memory_os_path(store, destination)
    payload = dict(record)

    if owner == "owner_action" and allow_owner_action_without_envelope:
        governance = _governance_record(
            write_owner=owner,
            lane_id=lane_id,
            risk_class=risk_class,
            execution_gate_envelope_id="",
            scope_hash=scope_hash,
            permit_status="not_required",
            permit_reason="owner_action_gate",
            boundary_true=any_boundary_true(payload.get("boundary")),
        )
    else:
        resolution = resolve_execution_gate_permit(
            store.roots,
            envelope_id=execution_gate_envelope_id,
            lane_id=lane_id,
            risk_class=risk_class,
            require_fresh=True,
            require_unused=True,
            expected_scope_hash=scope_hash,
        )
        if resolution.get("status") != "valid":
            raise StoreError(str(resolution.get("reason") or "execution_gate_invalid"))
        boundary_true = any_boundary_true(payload.get("boundary"))
        if boundary_true:
            raise StoreError("structural_write_boundary_true")
        governance = _governance_record(
            write_owner=owner or "automatic",
            lane_id=lane_id,
            risk_class=risk_class,
            execution_gate_envelope_id=execution_gate_envelope_id,
            scope_hash=scope_hash,
            permit_status=str(resolution.get("status") or ""),
            permit_reason=str(resolution.get("reason") or ""),
            boundary_true=False,
        )

    payload["structural_write_governance"] = governance
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    return destination


def structural_write_gate_status() -> dict[str, Any]:
    return {
        "schema_version": STRUCTURAL_WRITE_GATE_SCHEMA_VERSION,
        "status": "available",
        "append_governed_jsonl_available": True,
        "contract": "automatic JSONL writes require a valid ExecutionGate permit at write surface",
        "raw_body_included": False,
    }


def _assert_memory_os_path(store: MemoryOSStore, path: Path) -> None:
    memory_os_root = store.roots.memory_os_root.resolve()
    system_modules_root = (store.roots.hermes_home / "system-modules").resolve()
    target = Path(path).resolve()
    allowed = (
        target == memory_os_root
        or memory_os_root in target.parents
        or target == system_modules_root
        or system_modules_root in target.parents
    )
    if not allowed:
        raise StoreError("structural_write_path_outside_allowed_roots")


def _governance_record(
    *,
    write_owner: str,
    lane_id: str,
    risk_class: str,
    execution_gate_envelope_id: str,
    scope_hash: str,
    permit_status: str,
    permit_reason: str,
    boundary_true: bool,
) -> dict[str, Any]:
    return {
        "schema_version": STRUCTURAL_WRITE_GATE_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "write_owner": str(write_owner or ""),
        "lane_id": str(lane_id or ""),
        "risk_class": str(risk_class or ""),
        "execution_gate_envelope_id": str(execution_gate_envelope_id or ""),
        "scope_hash": str(scope_hash or ""),
        "permit_status": str(permit_status or ""),
        "permit_reason": str(permit_reason or ""),
        "boundary_true": bool(boundary_true),
        "raw_body_included": False,
    }
