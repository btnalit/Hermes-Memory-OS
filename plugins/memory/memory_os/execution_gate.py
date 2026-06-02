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


def execution_gate_records_path(roots: MemoryOSRoots) -> Path:
    return roots.memory_os_root / "system" / "execution_gate_envelopes.jsonl"


def read_execution_gate_records(roots: MemoryOSRoots, *, limit: int = 0) -> list[dict[str, Any]]:
    records = _read_jsonl(execution_gate_records_path(roots))
    return records[-max(limit, 0):] if limit else records


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
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
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
        "profile": store.roots.profile or "default",
        "lane_id": lane,
        "trigger_surface": str(trigger_surface or ""),
        "risk_class": str(risk_class or ""),
        "human_approval_required": bool(human_approval_required),
        "why_no_human_approval": str(why_no_human_approval or "")[:240],
        "scope": _bounded_json(scope),
        "boundary": _bounded_json(boundary),
        "boundary_true": boundary_true,
        "precheck": _bounded_json(precheck or {}),
        "evidence_refs": [str(item)[:180] for item in (evidence_refs or [])[:20] if str(item or "").strip()],
        "permit_decision": "blocked" if boundary_true else "allowed",
        "permit_reason": "boundary_true" if boundary_true else "boundary_false",
    }
    _append_jsonl(execution_gate_records_path(store.roots), record)
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
