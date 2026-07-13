"""TTL hard-deletion and reverse manifest retention for private V3 thoughts."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .execution_gate import complete_execution_gate_envelope, start_execution_gate_envelope
from .store import MemoryOSStore
from .v3_body_packet import remove_body_manifests
from .wandering_journal import _mutate_journal


def v3_journal_sweep_status_path(store: MemoryOSStore) -> Path:
    return store.roots.memory_os_root / "system" / "v3_journal_sweep_status.json"


def sweep_pending_expired(
    store: MemoryOSStore,
    *,
    now: datetime | None = None,
    execution_gate_envelope_id: str = "",
) -> dict[str, str]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    envelope_id = str(execution_gate_envelope_id or "").strip()
    internal_envelope = not envelope_id
    if internal_envelope:
        permit = start_execution_gate_envelope(
            store,
            lane_id="v3_journal_ttl_sweep",
            trigger_surface="memory_os_local_helper",
            risk_class="private_ttl_hard_delete",
            human_approval_required=False,
            why_no_human_approval="owner-configured TTL annihilation of pending private thoughts",
            scope={"write_surface": "v3_wandering_journal", "operation": "pending_ttl_sweep"},
            boundary={
                "owner_delivery_attempted": False,
                "external_action_executed": False,
                "actual_identity_write": False,
                "actual_unapproved_crystallized_approval": False,
            },
            precheck={"ttl_policy_present": True},
            evidence_refs=[],
        )
        envelope_id = str(permit["execution_gate_envelope_id"])

    removed_snapshots: set[str] = set()

    def mutate(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], None]:
        kept: list[dict[str, Any]] = []
        for item in records:
            if item.get("record_type") != "thought" or item.get("fate") != "pending":
                kept.append(item)
                continue
            expires_at = _parse_datetime(item.get("expires_at"))
            if expires_at is None or expires_at > current:
                kept.append(item)
                continue
            snapshot_id = str(item.get("body_snapshot_id") or "")
            if snapshot_id:
                removed_snapshots.add(snapshot_id)
        remaining_snapshots = {
            str(item.get("body_snapshot_id") or "")
            for item in kept
            if item.get("record_type") == "thought" and item.get("body_snapshot_id")
        }
        removed_snapshots.difference_update(remaining_snapshots)
        return kept, None

    try:
        _mutate_journal(store, mutate)
        remove_body_manifests(store, removed_snapshots)
        _write_status(v3_journal_sweep_status_path(store), "ok")
        if internal_envelope:
            complete_execution_gate_envelope(
                store,
                envelope_id=envelope_id,
                lane_id="v3_journal_ttl_sweep",
                execution_status="completed",
                postcheck={"boundary_true": False},
                result_summary={"cycle_status": "ok"},
            )
        return {"cycle_status": "ok"}
    except Exception as exc:
        _write_status(v3_journal_sweep_status_path(store), "error")
        if internal_envelope:
            complete_execution_gate_envelope(
                store,
                envelope_id=envelope_id,
                lane_id="v3_journal_ttl_sweep",
                execution_status="failed",
                postcheck={"boundary_true": False},
                result_summary={"cycle_status": "error", "error_code": type(exc).__name__},
            )
        raise


def _parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _write_status(path: Path, status: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    payload = json.dumps({"cycle_status": status}, ensure_ascii=False, separators=(",", ":"))
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()
