"""Deterministic receipt-driven fate state machine for V3 journal entries."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .store import MemoryOSStore
from .wandering_journal import mutate_thought


def claim_outlet(
    store: MemoryOSStore,
    entry_id: str,
    *,
    expected_requested_fate: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    if expected_requested_fate not in {"share", "propose"}:
        raise ValueError("expected_requested_fate")
    claimed_at = _timestamp(now)

    def update(entry: dict[str, Any]) -> dict[str, Any]:
        if entry.get("fate") != "pending":
            raise ValueError("entry_terminal")
        if entry.get("requested_fate") != expected_requested_fate:
            raise ValueError("requested_fate_mismatch")
        if entry.get("outlet_status") != "queued":
            raise ValueError("not_queued")
        entry["outlet_status"] = "claimed"
        entry["outlet_claimed_at"] = claimed_at
        return entry

    return mutate_thought(store, entry_id, update)


def complete_share(
    store: MemoryOSStore,
    entry_id: str,
    delivery_receipt: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not isinstance(delivery_receipt, dict):
        raise ValueError("delivery_receipt")

    def update(entry: dict[str, Any]) -> dict[str, Any]:
        receipt_id = str(delivery_receipt.get("receipt_id") or "")
        if (
            entry.get("tier") == "claim"
            or entry.get("requested_fate") != "share"
            or entry.get("outlet_status") != "claimed"
            or delivery_receipt.get("delivery_succeeded") is not True
            or str(delivery_receipt.get("entry_id") or "") != str(entry.get("entry_id") or "")
            or not receipt_id
        ):
            raise ValueError("delivery_receipt")
        entry["outlet_status"] = "completed"
        entry["outlet_result"] = "delivered"
        entry["fate"] = "shared"
        entry["fate_at"] = _timestamp(now)
        entry["fate_ref"] = receipt_id
        return entry

    return mutate_thought(store, entry_id, update)


def complete_proposal(
    store: MemoryOSStore,
    entry_id: str,
    candidate_receipt: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not isinstance(candidate_receipt, dict):
        raise ValueError("candidate_receipt")

    def update(entry: dict[str, Any]) -> dict[str, Any]:
        candidate_id = str(candidate_receipt.get("candidate_id") or "")
        receipt_refs = sorted(str(item) for item in candidate_receipt.get("provenance_refs") or [])
        entry_refs = sorted(str(item) for item in entry.get("provenance_refs") or [])
        if (
            entry.get("tier") != "claim"
            or entry.get("requested_fate") != "propose"
            or entry.get("outlet_status") != "claimed"
            or not candidate_id
            or str(candidate_receipt.get("body_hash") or "") != str(entry.get("content_hash") or "")
            or receipt_refs != entry_refs
        ):
            raise ValueError("candidate_receipt")
        entry["outlet_status"] = "completed"
        entry["outlet_result"] = "candidate_created"
        entry["fate"] = "proposed"
        entry["fate_at"] = _timestamp(now)
        entry["fate_ref"] = candidate_id
        return entry

    return mutate_thought(store, entry_id, update)


def close_outlet(
    store: MemoryOSStore,
    entry_id: str,
    *,
    reason_code: str,
) -> dict[str, Any]:
    allowed_reasons = {"silent", "blocked", "provider_error", "schema_error", "write_error", "privacy_gate"}
    if reason_code not in allowed_reasons:
        raise ValueError("reason_code")

    def update(entry: dict[str, Any]) -> dict[str, Any]:
        if entry.get("fate") != "pending" or entry.get("outlet_status") not in {"queued", "claimed"}:
            raise ValueError("outlet_not_open")
        entry["outlet_status"] = "closed"
        entry["outlet_result"] = reason_code
        return entry

    return mutate_thought(store, entry_id, update)


def _timestamp(value: datetime | None) -> str:
    return (value or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
