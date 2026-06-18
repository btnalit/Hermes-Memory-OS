"""Append-only execution permit envelopes for automatic Memory-OS lanes."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .roots import MemoryOSRoots
from .store import MemoryOSStore


EXECUTION_GATE_SCHEMA_VERSION = "memory-os.execution_gate_envelope.v0"
DEFAULT_PERMIT_TTL_SECONDS = 900

# ── Lane registry ─────────────────────────────────────────────────
RESOLVER_AUTO_APPROVE_LANE = "resolver_auto_approve"
RESOLVER_AUTO_APPROVE_RISK_CLASS = "reversible_llm_auto_approval"


def execution_gate_records_path(roots: MemoryOSRoots) -> Path:
    return roots.memory_os_root / "system" / "execution_gate_envelopes.jsonl"


def _gate_index_path(roots: MemoryOSRoots) -> Path:
    """Sidecar index for O(1) envelope_id -> state lookup."""
    return roots.memory_os_root / "system" / "execution_gate_index.json"


def _read_gate_index(roots: MemoryOSRoots) -> dict[str, dict[str, Any]]:
    """Read the gate index. Returns empty dict if missing or corrupt."""
    path = _gate_index_path(roots)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _write_gate_index(roots: MemoryOSRoots, index: dict[str, dict[str, Any]]) -> None:
    """Atomically write the gate index."""
    path = _gate_index_path(roots)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(path)


def _update_gate_index(
    roots: MemoryOSRoots,
    envelope_id: str,
    stage: str,
    record: dict[str, Any],
) -> None:
    """Update the sidecar index after appending an envelope record.

    Atomicity contract: caller MUST append the JSONL record BEFORE calling this.
    If this update crashes, the next resolve will detect the index miss and
    fall back to a full scan, which rebuilds the missing index entries.
    """
    index = _read_gate_index(roots)
    entry = index.get(envelope_id, {})
    entry["envelope_id"] = envelope_id
    if stage == "permit":
        entry.update({
            "permit_decision": record.get("permit_decision"),
            "lane_id": record.get("lane_id"),
            "risk_class": record.get("risk_class"),
            "scope_hash": record.get("scope_hash"),
            "permit_created_at": record.get("created_at"),
            "permit_expires_at": record.get("expires_at"),
            "boundary_true": record.get("boundary_true", False),
        })
    elif stage == "completion":
        # Map record's execution_status -> index completion_status
        entry["completion_status"] = record.get("execution_status") or record.get("completion_status")
        entry["completed_at"] = record.get("created_at")
    index[envelope_id] = entry
    _write_gate_index(roots, index)


def _rebuild_gate_index_from_records(
    roots: MemoryOSRoots,
    records: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Rebuild the entire gate index from raw envelope records.

    Used as crash-recovery: if index miss detected during resolve,
    do a full scan and rebuild all index entries.
    """
    index: dict[str, dict[str, Any]] = {}
    for record in records:
        eid = str(record.get("execution_gate_envelope_id") or "")
        if not eid:
            continue
        stage = str(record.get("stage") or "")
        entry = index.get(eid, {})
        entry["envelope_id"] = eid
        if stage == "permit":
            entry.update({
                "permit_decision": record.get("permit_decision"),
                "lane_id": record.get("lane_id"),
                "risk_class": record.get("risk_class"),
                "scope_hash": record.get("scope_hash"),
                "permit_created_at": record.get("created_at"),
                "permit_expires_at": record.get("expires_at"),
                "boundary_true": record.get("boundary_true", False),
            })
        elif stage == "completion":
            # Map record's execution_status -> index completion_status
            entry["completion_status"] = record.get("execution_status") or record.get("completion_status")
            entry["completed_at"] = record.get("created_at")
        index[eid] = entry
    _write_gate_index(roots, index)
    return index


def read_execution_gate_records(roots: MemoryOSRoots, *, limit: int = 0) -> list[dict[str, Any]]:
    records = _read_jsonl(execution_gate_records_path(roots))
    return records[-max(limit, 0):] if limit else records


def _validate_index_entry(
    index_entry: dict[str, Any],
    target: str,
    lane_id: str,
    risk_class: str,
    require_fresh: bool,
    require_unused: bool,
    expected_scope: dict[str, Any] | None,
    expected_scope_hash: str,
    now: datetime | None,
) -> dict[str, Any] | None:
    """Validate a permit from an index entry.

    Returns a _permit_resolution(...) dict on failure, or None on success
    (meaning the entry passed all checks and caller should return valid).
    On success, callers should build the valid resolution themselves using
    the index_entry data.
    """
    if lane_id and str(index_entry.get("lane_id") or "") != lane_id:
        return _permit_resolution(
            status="invalid",
            reason="execution_gate_lane_mismatch",
            envelope_id=target,
            lane_id=lane_id,
            risk_class=risk_class,
            permit=index_entry,
        )
    if risk_class and str(index_entry.get("risk_class") or "") != risk_class:
        return _permit_resolution(
            status="invalid",
            reason="execution_gate_risk_class_mismatch",
            envelope_id=target,
            lane_id=lane_id,
            risk_class=risk_class,
            permit=index_entry,
        )
    if str(index_entry.get("permit_decision") or "") != "allowed":
        return _permit_resolution(
            status="invalid",
            reason="execution_gate_permit_not_allowed",
            envelope_id=target,
            lane_id=lane_id,
            risk_class=risk_class,
            permit=index_entry,
        )
    if index_entry.get("boundary_true") is True:
        return _permit_resolution(
            status="invalid",
            reason="execution_gate_boundary_true",
            envelope_id=target,
            lane_id=lane_id,
            risk_class=risk_class,
            permit=index_entry,
            completion_count=1 if index_entry.get("completion_status") else 0,
        )
    expiry = _expiry_status(index_entry.get("permit_expires_at"), now=now, require_present=require_fresh)
    if expiry != "valid":
        return _permit_resolution(
            status="invalid",
            reason=f"execution_gate_permit_{expiry}",
            envelope_id=target,
            lane_id=lane_id,
            risk_class=risk_class,
            permit=index_entry,
            completion_count=1 if index_entry.get("completion_status") else 0,
        )
    if require_unused and index_entry.get("completion_status"):
        return _permit_resolution(
            status="invalid",
            reason="execution_gate_permit_already_completed",
            envelope_id=target,
            lane_id=lane_id,
            risk_class=risk_class,
            permit=index_entry,
            completion_count=1,
        )
    expected_hash = str(expected_scope_hash or "").strip()
    if expected_scope is not None:
        expected_hash = execution_gate_scope_hash(expected_scope)
    if expected_hash:
        permit_scope_hash = str(index_entry.get("scope_hash") or "").strip()
        if permit_scope_hash != expected_hash:
            return _permit_resolution(
                status="invalid",
                reason="execution_gate_scope_mismatch",
                envelope_id=target,
                lane_id=lane_id,
                risk_class=risk_class,
                permit=index_entry,
                completion_count=1 if index_entry.get("completion_status") else 0,
                scope_match=False,
            )
    # All checks passed — return None to signal valid
    return None


def resolve_execution_gate_permit(
    roots: MemoryOSRoots,
    *,
    envelope_id: str,
    lane_id: str = "",
    risk_class: str = "",
    require_fresh: bool = False,
    require_unused: bool = False,
    expected_scope: dict[str, Any] | None = None,
    expected_scope_hash: str = "",
    limit: int = 0,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Resolve whether an execution-gate permit is valid for a caller.

    This is intentionally stricter than checking that an envelope id exists:
    callers can require lane/risk match and get a machine-readable rejection
    reason when the permit is missing, blocked, expired, or ambiguous.
    """

    target = str(envelope_id or "").strip()
    if not target or not target.startswith("xgate_"):
        return _permit_resolution(
            status="invalid",
            reason="execution_gate_envelope_id_invalid",
            envelope_id=target,
            lane_id=lane_id,
            risk_class=risk_class,
        )

    # Fast path: O(1) index lookup
    idx = _read_gate_index(roots)
    index_entry = idx.get(target)
    if index_entry is not None and index_entry.get("permit_decision") is not None:
        failed = _validate_index_entry(
            index_entry, target, lane_id, risk_class,
            require_fresh, require_unused, expected_scope, expected_scope_hash, now,
        )
        if failed is not None:
            return failed
        # All checks passed — build valid resolution from index entry
        completion_count = 1 if index_entry.get("completion_status") else 0
        expected_hash = str(expected_scope_hash or "").strip()
        if expected_scope is not None:
            expected_hash = execution_gate_scope_hash(expected_scope)
        return _permit_resolution(
            status="valid",
            reason="",
            envelope_id=target,
            lane_id=str(index_entry.get("lane_id") or ""),
            risk_class=str(index_entry.get("risk_class") or ""),
            permit=index_entry,
            completion_count=completion_count,
            scope_match=True if expected_hash else None,
        )

    # Index miss — fall back to full scan (limit=0 = no window)
    records = read_execution_gate_records(roots, limit=0)
    permits = [
        record
        for record in records
        if record.get("stage") == "permit" and str(record.get("execution_gate_envelope_id") or "") == target
    ]
    completions = [
        record
        for record in records
        if record.get("stage") == "completion" and str(record.get("execution_gate_envelope_id") or "") == target
    ]
    if not permits:
        _rebuild_gate_index_from_records(roots, records)
        return _permit_resolution(
            status="invalid",
            reason="execution_gate_permit_not_found",
            envelope_id=target,
            lane_id=lane_id,
            risk_class=risk_class,
        )
    if len(permits) > 1:
        _rebuild_gate_index_from_records(roots, records)
        return _permit_resolution(
            status="invalid",
            reason="execution_gate_permit_conflict",
            envelope_id=target,
            lane_id=lane_id,
            risk_class=risk_class,
            permit_count=len(permits),
        )
    permit = permits[0]
    if lane_id and str(permit.get("lane_id") or "") != lane_id:
        _rebuild_gate_index_from_records(roots, records)
        return _permit_resolution(
            status="invalid",
            reason="execution_gate_lane_mismatch",
            envelope_id=target,
            lane_id=lane_id,
            risk_class=risk_class,
            permit=permit,
        )
    if risk_class and str(permit.get("risk_class") or "") != risk_class:
        _rebuild_gate_index_from_records(roots, records)
        return _permit_resolution(
            status="invalid",
            reason="execution_gate_risk_class_mismatch",
            envelope_id=target,
            lane_id=lane_id,
            risk_class=risk_class,
            permit=permit,
        )
    if str(permit.get("permit_decision") or "") != "allowed":
        _rebuild_gate_index_from_records(roots, records)
        return _permit_resolution(
            status="invalid",
            reason="execution_gate_permit_not_allowed",
            envelope_id=target,
            lane_id=lane_id,
            risk_class=risk_class,
            permit=permit,
        )
    if permit.get("boundary_true") is True or any_boundary_true(permit.get("boundary")):
        _rebuild_gate_index_from_records(roots, records)
        return _permit_resolution(
            status="invalid",
            reason="execution_gate_boundary_true",
            envelope_id=target,
            lane_id=lane_id,
            risk_class=risk_class,
            permit=permit,
            completion_count=len(completions),
        )
    expiry = _expiry_status(permit.get("expires_at"), now=now, require_present=require_fresh)
    if expiry != "valid":
        _rebuild_gate_index_from_records(roots, records)
        return _permit_resolution(
            status="invalid",
            reason=f"execution_gate_permit_{expiry}",
            envelope_id=target,
            lane_id=lane_id,
            risk_class=risk_class,
            permit=permit,
            completion_count=len(completions),
        )
    if require_unused and completions:
        _rebuild_gate_index_from_records(roots, records)
        return _permit_resolution(
            status="invalid",
            reason="execution_gate_permit_already_completed",
            envelope_id=target,
            lane_id=lane_id,
            risk_class=risk_class,
            permit=permit,
            completion_count=len(completions),
        )
    expected_hash = str(expected_scope_hash or "").strip()
    if expected_scope is not None:
        expected_hash = execution_gate_scope_hash(expected_scope)
    if expected_hash:
        permit_scope_hash = str(permit.get("scope_hash") or "").strip()
        if not permit_scope_hash:
            permit_scope_hash = execution_gate_scope_hash(permit.get("scope") if isinstance(permit.get("scope"), dict) else {})
        if permit_scope_hash != expected_hash:
            _rebuild_gate_index_from_records(roots, records)
            return _permit_resolution(
                status="invalid",
                reason="execution_gate_scope_mismatch",
                envelope_id=target,
                lane_id=lane_id,
                risk_class=risk_class,
                permit=permit,
                completion_count=len(completions),
                scope_match=False,
            )
    result = _permit_resolution(
        status="valid",
        reason="",
        envelope_id=target,
        lane_id=str(permit.get("lane_id") or ""),
        risk_class=str(permit.get("risk_class") or ""),
        permit=permit,
        completion_count=len(completions),
        scope_match=True if expected_hash else None,
    )
    _rebuild_gate_index_from_records(roots, records)
    return result


def execution_gate_scope_hash(scope: dict[str, Any] | None) -> str:
    encoded = json.dumps(scope or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def any_boundary_true(value: Any) -> bool:
    """Return true when any boundary-shaped object contains a boolean true."""
    return bool(boundary_true_paths(value))


def boundary_true_paths(value: Any, *, prefix: str = "") -> list[str]:
    if isinstance(value, bool):
        return [prefix or "$"] if value is True else []
    if isinstance(value, dict):
        paths: list[str] = []
        for key, item in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            paths.extend(boundary_true_paths(item, prefix=child_prefix))
        return paths
    if isinstance(value, list):
        paths = []
        for index, item in enumerate(value):
            child_prefix = f"{prefix}[{index}]" if prefix else f"[{index}]"
            paths.extend(boundary_true_paths(item, prefix=child_prefix))
        return paths
    return []


def start_execution_gate_envelope(
    store: MemoryOSStore,
    *,
    lane_id: str,
    trigger_surface: str,
    risk_class: str,
    human_approval_required: bool,
    why_no_human_approval: str,
    scope: dict[str, Any],
    boundary: dict[str, Any],
    precheck: dict[str, Any] | None = None,
    evidence_refs: list[str] | None = None,
    ttl_seconds: int = DEFAULT_PERMIT_TTL_SECONDS,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=max(int(ttl_seconds or 0), 1))
    boundary_true = any_boundary_true(boundary)
    lane = str(lane_id or "unknown")
    material = json.dumps(
        {
            "lane_id": lane,
            "trigger_surface": trigger_surface,
            "scope": scope,
            "boundary": boundary,
            "ts": now.isoformat(),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    envelope_id = f"xgate_{now.strftime('%Y%m%dT%H%M%S%fZ')}_{hashlib.sha256(material.encode('utf-8')).hexdigest()[:10]}"
    record = {
        "schema_version": EXECUTION_GATE_SCHEMA_VERSION,
        "stage": "permit",
        "execution_gate_envelope_id": envelope_id,
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
        "profile": store.roots.profile or "default",
        "lane_id": lane,
        "trigger_surface": str(trigger_surface or ""),
        "risk_class": str(risk_class or ""),
        "human_approval_required": bool(human_approval_required),
        "why_no_human_approval": str(why_no_human_approval or "")[:240],
        "scope": _bounded_json(scope),
        "scope_hash": execution_gate_scope_hash(scope),
        "boundary": _bounded_json(boundary),
        "boundary_true": boundary_true,
        "precheck": _bounded_json(precheck or {}),
        "evidence_refs": [str(item)[:180] for item in (evidence_refs or [])[:20] if str(item or "").strip()],
        "permit_decision": "blocked" if boundary_true else "allowed",
        "permit_reason": "boundary_true" if boundary_true else "boundary_false",
    }
    _append_jsonl(execution_gate_records_path(store.roots), record)
    _update_gate_index(store.roots, envelope_id, "permit", record)
    return record


def complete_execution_gate_envelope(
    store: MemoryOSStore,
    *,
    envelope_id: str,
    lane_id: str,
    execution_status: str,
    postcheck: dict[str, Any] | None = None,
    result_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    record = {
        "schema_version": EXECUTION_GATE_SCHEMA_VERSION,
        "stage": "completion",
        "execution_gate_envelope_id": str(envelope_id or ""),
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "profile": store.roots.profile or "default",
        "lane_id": str(lane_id or ""),
        "execution_status": str(execution_status or ""),
        "postcheck": _bounded_json(postcheck or {}),
        "postcheck_boundary_true": any_boundary_true(postcheck or {}),
        "result_summary": _bounded_json(result_summary or {}),
    }
    _append_jsonl(execution_gate_records_path(store.roots), record)
    _update_gate_index(store.roots, envelope_id, "completion", record)
    return record


def execution_gate_summary(roots: MemoryOSRoots) -> dict[str, Any]:
    records = read_execution_gate_records(roots)
    permits = [record for record in records if record.get("stage") == "permit"]
    completions = [record for record in records if record.get("stage") == "completion"]
    latest = permits[-1] if permits else {}
    lane_counts: dict[str, int] = {}
    for record in permits:
        lane = str(record.get("lane_id") or "unknown")
        lane_counts[lane] = lane_counts.get(lane, 0) + 1
    return {
        "schema_version": "memory-os.execution_gate_summary.v0",
        "envelope_count": len(permits),
        "completion_count": len(completions),
        "boundary_true_count": sum(1 for record in permits if record.get("boundary_true") is True),
        "latest_envelope_id": str(latest.get("execution_gate_envelope_id") or ""),
        "latest_lane_id": str(latest.get("lane_id") or ""),
        "latest_permit_decision": str(latest.get("permit_decision") or ""),
        "lane_counts": lane_counts,
        "retention": execution_gate_retention_status(roots),
    }


def execution_gate_retention_status(roots: MemoryOSRoots) -> dict[str, Any]:
    path = execution_gate_records_path(roots)
    rotated_dir = roots.memory_os_root / "system" / "execution_gate"
    return {
        "schema_version": "memory-os.execution_gate_retention.v0",
        "active_path": str(path),
        "active_size_bytes": path.stat().st_size if path.exists() else 0,
        "rotated_file_count": len(list(rotated_dir.glob("envelopes-*.jsonl"))) if rotated_dir.exists() else 0,
        "lock_path": str(rotated_dir / "rotation.lock"),
    }


def start_resolver_auto_approve_envelope(
    store: MemoryOSStore,
    *,
    candidate_id: str,
    sensitivity: str,
    has_identity_signal: bool,
    bridge_state: str,
    evidence_refs: list[str] | None = None,
    ttl_seconds: int = DEFAULT_PERMIT_TTL_SECONDS,
) -> dict[str, Any]:
    """Start an ExecutionGate permit envelope for resolver auto-approval.

    Wraps start_execution_gate_envelope with resolver-specific defaults.
    boundary is empty (all False) because the reversibility and identity
    gates were already checked by resolver_gate BEFORE this envelope opens.
    """
    return start_execution_gate_envelope(
        store,
        lane_id=RESOLVER_AUTO_APPROVE_LANE,
        trigger_surface="resolver_gate.resolver_eligible",
        risk_class=RESOLVER_AUTO_APPROVE_RISK_CLASS,
        human_approval_required=False,
        why_no_human_approval=(
            "resolver_gate: candidate passed deterministic dual-axis gate "
            "(reversible + non-identity-adjacent + no side effects)"
        ),
        scope={
            "candidate_id": str(candidate_id),
            "sensitivity": str(sensitivity),
            "has_identity_signal": bool(has_identity_signal),
            "bridge_state": str(bridge_state),
            "operation": "resolver_approved_crystallized_write",
        },
        boundary={},
        evidence_refs=evidence_refs or [],
        ttl_seconds=ttl_seconds,
    )


def rotate_execution_gate_records(
    roots: MemoryOSRoots,
    *,
    max_records: int = 20000,
    max_age_days: int = 14,
    now: datetime | None = None,
) -> dict[str, Any]:
    current_now = now or datetime.now(timezone.utc)
    path = execution_gate_records_path(roots)
    records = read_execution_gate_records(roots)
    cutoff = current_now - timedelta(days=max_age_days)
    recent_indexes = {
        index
        for index, record in enumerate(records)
        if _record_created_at(record) and _record_created_at(record) >= cutoff
    }
    latest_start = max(len(records) - max(max_records, 0), 0)
    latest_indexes = set(range(latest_start, len(records)))
    keep_indexes = recent_indexes | latest_indexes
    kept = [record for index, record in enumerate(records) if index in keep_indexes]
    rotated = [record for index, record in enumerate(records) if index not in keep_indexes]
    lock_path = roots.memory_os_root / "system" / "execution_gate" / "rotation.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return {
            "schema_version": "memory-os.execution_gate_rotation.v0",
            "status": "locked",
            "before_count": len(records),
            "after_count": len(records),
            "rotated_count": 0,
        }
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(current_now.isoformat())
        if rotated:
            rotated_path = lock_path.parent / f"envelopes-{current_now.strftime('%Y%m%d')}.jsonl"
            with rotated_path.open("a", encoding="utf-8") as handle:
                for record in rotated:
                    handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        path.parent.mkdir(parents=True, exist_ok=True)
        with tmp_path.open("w", encoding="utf-8") as handle:
            for record in kept:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        os.replace(tmp_path, path)
    finally:
        try:
            lock_path.unlink()
        except OSError:
            pass
    return {
        "schema_version": "memory-os.execution_gate_rotation.v0",
        "status": "ok",
        "before_count": len(records),
        "after_count": len(kept),
        "rotated_count": len(rotated),
        "active_size_bytes": path.stat().st_size if path.exists() else 0,
    }


def _record_created_at(record: dict[str, Any]) -> datetime | None:
    raw = str(record.get("created_at") or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _expiry_status(value: Any, *, now: datetime | None = None, require_present: bool = False) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "expiry_missing" if require_present else "valid"
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return "expiry_invalid"
    if parsed.tzinfo is None:
        return "expiry_invalid"
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if parsed.astimezone(timezone.utc) <= current:
        return "expired"
    return "valid"


def _permit_resolution(
    *,
    status: str,
    reason: str,
    envelope_id: str,
    lane_id: str,
    risk_class: str,
    permit: dict[str, Any] | None = None,
    permit_count: int = 0,
    completion_count: int = 0,
    scope_match: bool | None = None,
) -> dict[str, Any]:
    record = permit or {}
    expiry_status = "missing" if permit and not str(record.get("expires_at") or "").strip() else _expiry_status(record.get("expires_at"), require_present=False)
    return {
        "schema_version": "memory-os.execution_gate_permit_resolution.v0",
        "status": status,
        "reason": reason,
        "execution_gate_envelope_id": envelope_id,
        "lane_id": str(lane_id or record.get("lane_id") or ""),
        "risk_class": str(risk_class or record.get("risk_class") or ""),
        "permit_decision": str(record.get("permit_decision") or ""),
        "boundary_true": record.get("boundary_true") is True or any_boundary_true(record.get("boundary")),
        "permit_count": permit_count or (1 if permit else 0),
        "completion_count": completion_count,
        "permit_created_at": str(record.get("created_at") or ""),
        "expires_at": str(record.get("expires_at") or ""),
        "expires_at_status": expiry_status,
        "scope_hash": str(record.get("scope_hash") or ""),
        "scope_match": scope_match,
        "unused_before_apply": completion_count == 0,
        "consumed_after_apply": completion_count > 0,
    }


def _bounded_json(value: Any) -> Any:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    if len(encoded) <= 4000:
        return json.loads(encoded)
    return {"truncated": True, "sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(), "char_count": len(encoded)}


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


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
