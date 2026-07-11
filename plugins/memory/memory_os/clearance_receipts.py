"""V2-E clearance receipt journal and corpus change event ledger.

Receipts (clear/conflict/unknown) are produced by the clearance judge and
consumed by the permanent-promotion producer (E5). Corpus change events
are emitted by crystallized write paths and consumed by the invalidation
engine (E3).

Design: living-memory-v2e-clearance-design.md §2
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ── Schema versions ─────────────────────────────────────────────────────────

CLEARANCE_RECEIPT_SCHEMA_VERSION = "memory-os.clearance_receipt.v0"
CORPUS_CHANGE_EVENT_SCHEMA_VERSION = "memory-os.corpus_change_event.v0"


# ── Path helpers ────────────────────────────────────────────────────────────


def clearance_receipts_path(roots: Any) -> Path:
    """Path to the append-only clearance receipt journal."""
    return roots.memory_os_root / "system" / "clearance_receipts.jsonl"


def clearance_receipt_snapshot_path(roots: Any) -> Path:
    """Path to the derived receipt snapshot."""
    return roots.memory_os_root / "system" / "clearance_receipt_snapshot.json"


def corpus_change_events_path(roots: Any) -> Path:
    """Path to the append-only corpus change event journal."""
    return roots.memory_os_root / "system" / "corpus_change_events.jsonl"


# ── Data classes ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ClearanceReceipt:
    """A clearance verdict for one candidate against the current permanent corpus."""

    receipt_id: str
    record_id: str
    content_hash: str
    verdict: str  # "clear" | "conflict" | "unknown"
    conflict_refs: list[str] = field(default_factory=list)
    corpus_watermark: int = 0
    checked_entity_set: list[str] = field(default_factory=list)
    invalidation_mode: str = "entity_scoped"  # "entity_scoped" | "conservative_full"
    judge_version: str = ""
    judged_at: str = ""
    invalidated_at: str | None = None
    invalidated_by: str | None = None

    @property
    def is_active(self) -> bool:
        return self.invalidated_at is None

    @property
    def idempotency_key(self) -> str:
        parts = [self.content_hash, str(self.corpus_watermark), self.judge_version]
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CLEARANCE_RECEIPT_SCHEMA_VERSION,
            "receipt_id": self.receipt_id,
            "candidate_ref": {
                "record_id": self.record_id,
                "content_hash": self.content_hash,
            },
            "verdict": self.verdict,
            "conflict_refs": list(self.conflict_refs),
            "corpus_watermark": self.corpus_watermark,
            "checked_entity_set": list(self.checked_entity_set),
            "invalidation_mode": self.invalidation_mode,
            "judge_version": self.judge_version,
            "judged_at": self.judged_at,
            "invalidated_at": self.invalidated_at,
            "invalidated_by": self.invalidated_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ClearanceReceipt":
        candidate_ref = data.get("candidate_ref") if isinstance(data.get("candidate_ref"), dict) else {}
        return cls(
            receipt_id=str(data.get("receipt_id") or ""),
            record_id=str(candidate_ref.get("record_id") or ""),
            content_hash=str(candidate_ref.get("content_hash") or ""),
            verdict=str(data.get("verdict") or "unknown"),
            conflict_refs=list(data.get("conflict_refs") or []),
            corpus_watermark=int(data.get("corpus_watermark") or 0),
            checked_entity_set=list(data.get("checked_entity_set") or []),
            invalidation_mode=str(data.get("invalidation_mode") or "entity_scoped"),
            judge_version=str(data.get("judge_version") or ""),
            judged_at=str(data.get("judged_at") or ""),
            invalidated_at=data.get("invalidated_at"),
            invalidated_by=data.get("invalidated_by"),
        )


@dataclass(frozen=True)
class CorpusChangeEvent:
    """Emitted on every canonical permanent state transition."""

    event_id: int
    change_type: str  # add | update | supersede | retire | revoke
    record_id: str
    entity_set: list[str] = field(default_factory=list)
    watermark_after: int = 0
    at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CORPUS_CHANGE_EVENT_SCHEMA_VERSION,
            "event_id": self.event_id,
            "change_type": self.change_type,
            "record_id": self.record_id,
            "entity_set": list(self.entity_set),
            "watermark_after": self.watermark_after,
            "at": self.at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CorpusChangeEvent":
        return cls(
            event_id=int(data.get("event_id") or 0),
            change_type=str(data.get("change_type") or ""),
            record_id=str(data.get("record_id") or ""),
            entity_set=list(data.get("entity_set") or []),
            watermark_after=int(data.get("watermark_after") or 0),
            at=str(data.get("at") or ""),
        )


# ── Receipt journal ─────────────────────────────────────────────────────────


def read_clearance_receipts(roots: Any) -> list[dict[str, Any]]:
    """Read all clearance receipts from the journal."""
    path = clearance_receipts_path(roots)
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


def write_clearance_receipt(
    roots: Any,
    receipt: ClearanceReceipt,
    *,
    write_context: Any | None = None,
) -> dict[str, Any]:
    """Append a clearance receipt to the journal (idempotent).

    Checks the idempotency key before writing — an existing active receipt
    with the same key suppresses the write.
    """
    from .jsonl_io import append_jsonl_locked, read_jsonl

    path = clearance_receipts_path(roots)
    receipt_dict = receipt.to_dict()
    idemp_key = receipt.idempotency_key

    # Check for existing active receipt with same idempotency key
    existing = read_jsonl(str(path))
    for existing_rec in existing:
        existing_receipt = ClearanceReceipt.from_dict(existing_rec)
        if existing_receipt.idempotency_key == idemp_key and existing_receipt.is_active:
            return {"status": "idempotent", "receipt_id": existing_receipt.receipt_id, "written": False}

    append_jsonl_locked(path, receipt_dict)
    return {"status": "ok", "receipt_id": receipt.receipt_id, "written": True}


# ── Receipt snapshot ────────────────────────────────────────────────────────


def rebuild_clearance_receipt_snapshot(roots: Any) -> dict[str, Any]:
    """Derive the receipt snapshot from the journal (lock+tmp+os.replace)."""
    records = read_clearance_receipts(roots)
    snapshot_path = clearance_receipt_snapshot_path(roots)

    receipts_by_id: dict[str, dict[str, Any]] = {}
    active_count = 0
    verdict_counts: dict[str, int] = {"clear": 0, "conflict": 0, "unknown": 0}
    for rec in records:
        receipt = ClearanceReceipt.from_dict(rec)
        receipts_by_id[receipt.receipt_id] = rec
        if receipt.is_active:
            active_count += 1
            verdict = receipt.verdict
            if verdict in verdict_counts:
                verdict_counts[verdict] += 1

    snapshot: dict[str, Any] = {
        "schema_version": "memory-os.clearance_receipt_snapshot.v0",
        "built_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "total_receipts": len(records),
        "active_receipts": active_count,
        "verdict_distribution": verdict_counts,
        "latest_watermark": max(
            (int(r.get("corpus_watermark") or 0) for r in records), default=0,
        ),
        "receipts": receipts_by_id,
    }

    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = __import__("tempfile").mkstemp(
        dir=str(snapshot_path.parent), prefix="receipt_snapshot_",
    )
    try:
        os.write(tmp_fd, json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"))
        os.fsync(tmp_fd)
        os.close(tmp_fd)
        os.replace(tmp_path, str(snapshot_path))
    finally:
        try:
            os.close(tmp_fd)
        except OSError:
            pass
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    return snapshot


def read_clearance_receipt_snapshot(roots: Any) -> dict[str, Any] | None:
    """Read the current receipt snapshot, if it exists."""
    snapshot_path = clearance_receipt_snapshot_path(roots)
    if not snapshot_path.exists():
        return None
    try:
        return json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


# ── Corpus change event journal ─────────────────────────────────────────────


def read_corpus_change_events(roots: Any) -> list[dict[str, Any]]:
    """Read all corpus change events from the journal."""
    path = corpus_change_events_path(roots)
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


def append_corpus_change_event(
    roots: Any,
    change_type: str,
    record_id: str,
    *,
    entity_set: list[str] | None = None,
) -> dict[str, Any]:
    """Emit a corpus change event (called from crystallized write paths).

    The event_id is determined by reading the last event and incrementing
    (monotonic within the journal lock).
    """
    from .jsonl_io import append_jsonl_locked, read_jsonl

    path = corpus_change_events_path(roots)
    existing = read_jsonl(str(path))
    last_id = max((int(e.get("event_id") or 0) for e in existing), default=0)
    event_id = last_id + 1

    event = CorpusChangeEvent(
        event_id=event_id,
        change_type=change_type,
        record_id=record_id,
        entity_set=list(entity_set or []),
        watermark_after=event_id,
        at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )

    append_jsonl_locked(path, event.to_dict())
    return {"status": "ok", "event_id": event_id, "written": True}


def latest_corpus_watermark(roots: Any) -> int:
    """Return the current corpus watermark (latest event_id, 0 if empty)."""
    events = read_corpus_change_events(roots)
    return max((int(e.get("event_id") or 0) for e in events), default=0)
