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
    unknown_reason: str = ""  # C3: "candidate_unindexed" | "judge_unavailable" | "judge_verdict" | ""

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
            "unknown_reason": self.unknown_reason,
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
            unknown_reason=str(data.get("unknown_reason") or ""),
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
    """Read all clearance receipts from the journal.

    Deduplicates by receipt_id — later entries supersede earlier ones
    (journal is append-only; invalidation appends updated copies).
    """
    path = clearance_receipts_path(roots)
    if not path.exists():
        return []
    by_id: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
            rid = str(record.get("receipt_id") or "")
            if rid:
                by_id[rid] = record  # later entry wins
        except json.JSONDecodeError:
            continue
    return list(by_id.values())


def write_clearance_receipt(
    roots: Any,
    receipt: ClearanceReceipt,
    *,
    write_context: Any | None = None,
) -> dict[str, Any]:
    """Append a clearance receipt to the journal (idempotent).

    Checks the idempotency key before writing — an existing active receipt
    with the same key suppresses the write, UNLESS that receipt's record_id
    has been invalidated by a newer journal entry (rejudge path).
    """
    from .jsonl_io import append_jsonl_locked, read_jsonl

    path = clearance_receipts_path(roots)
    receipt_dict = receipt.to_dict()
    idemp_key = receipt.idempotency_key

    # Build the set of record_ids that have been invalidated —
    # these supersede any older "active" receipt for the same record_id.
    existing = read_jsonl(str(path))
    invalidated_record_ids: set[str] = set()
    for existing_rec in existing:
        er = ClearanceReceipt.from_dict(existing_rec)
        if er.invalidated_at is not None:
            invalidated_record_ids.add(er.record_id)

    # Check for existing active receipt with same idempotency key
    for existing_rec in existing:
        existing_receipt = ClearanceReceipt.from_dict(existing_rec)
        if existing_receipt.idempotency_key == idemp_key and existing_receipt.is_active:
            # If this record_id has been invalidated since, the original
            # active receipt is superseded — allow the new receipt.
            if existing_receipt.record_id in invalidated_record_ids:
                continue
            return {"status": "idempotent", "receipt_id": existing_receipt.receipt_id, "written": False}

    append_jsonl_locked(path, receipt_dict)
    return {"status": "ok", "receipt_id": receipt.receipt_id, "written": True}


# ── Receipt snapshot ────────────────────────────────────────────────────────


def rebuild_clearance_receipt_snapshot(roots: Any) -> dict[str, Any]:
    """Derive the effective receipt snapshot from the append-only journal."""
    records = read_clearance_receipts(roots)
    ledger_path = clearance_receipts_path(roots)
    snapshot_path = clearance_receipt_snapshot_path(roots)
    ledger_bytes = ledger_path.read_bytes() if ledger_path.exists() else b""
    raw_rows = sum(1 for line in ledger_bytes.splitlines() if line.strip())

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

    latest_source_at = max(
        (
            str(record.get("invalidated_at") or record.get("judged_at") or "")
            for record in records
        ),
        default="",
    )
    snapshot: dict[str, Any] = {
        "schema_version": "memory-os.clearance_receipt_snapshot.v1",
        "built_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "total_receipts": len(records),  # compatibility alias: effective logical receipts
        "effective_receipts": len(records),
        "raw_ledger_rows": raw_rows,
        "active_receipts": active_count,
        "verdict_distribution": verdict_counts,
        "latest_watermark": max(
            (int(r.get("corpus_watermark") or 0) for r in records), default=0,
        ),
        "latest_source_at": latest_source_at,
        "source_ledger_sha256": hashlib.sha256(ledger_bytes).hexdigest(),
        "source_ledger_size_bytes": len(ledger_bytes),
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


def clearance_snapshot_freshness(roots: Any, *, for_activation: bool = False) -> dict[str, Any]:
    """Compare a derived snapshot with its authoritative append-only ledger."""

    snapshot = read_clearance_receipt_snapshot(roots)
    if not isinstance(snapshot, dict):
        return {
            "status": "missing",
            "severity": "FAIL" if for_activation else "WARN",
            "reason": "snapshot_missing",
            "would_gate_activation": bool(for_activation),
        }
    ledger_path = clearance_receipts_path(roots)
    ledger_bytes = ledger_path.read_bytes() if ledger_path.exists() else b""
    actual_hash = hashlib.sha256(ledger_bytes).hexdigest()
    actual_size = len(ledger_bytes)
    actual_effective = read_clearance_receipts(roots)
    actual_watermark = max(
        (int(record.get("corpus_watermark") or 0) for record in actual_effective),
        default=0,
    )
    reasons: list[str] = []
    if str(snapshot.get("source_ledger_sha256") or "") != actual_hash:
        reasons.append("ledger_hash_mismatch")
    if int(snapshot.get("source_ledger_size_bytes") or 0) != actual_size:
        reasons.append("ledger_size_mismatch")
    if int(snapshot.get("effective_receipts") or snapshot.get("total_receipts") or 0) != len(actual_effective):
        reasons.append("ledger_effective_count_mismatch")
    if int(snapshot.get("latest_watermark") or 0) != actual_watermark:
        reasons.append("ledger_watermark_mismatch")
    stale = bool(reasons)
    return {
        "status": "stale" if stale else "fresh",
        "severity": ("FAIL" if for_activation else "WARN") if stale else "OK",
        "reason": ",".join(reasons) if reasons else "ledger_snapshot_match",
        "would_gate_activation": bool(for_activation and stale),
        "snapshot_built_at": str(snapshot.get("built_at") or ""),
        "snapshot_watermark": int(snapshot.get("latest_watermark") or 0),
        "ledger_watermark": actual_watermark,
        "snapshot_effective_receipts": int(snapshot.get("effective_receipts") or snapshot.get("total_receipts") or 0),
        "ledger_effective_receipts": len(actual_effective),
    }


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


# ── E3.5: Bulk invalidation by judge version (escape hatch) ────────────────


def invalidate_receipts_by_judge_version(
    roots: Any,
    judge_version: str,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Invalidate all active receipts produced by a specific judge version.

    Escape hatch for recalling receipts from a known-bad judge (e.g., the
    v2e_heuristic stub that always returned ``clear``).  Marked receipts
    enter the rejudge queue for the next clearance cycle.

    Returns a structured report.  Idempotent — running twice produces the
    same set of invalidated receipts.
    """
    from .jsonl_io import append_jsonl_locked

    records = read_clearance_receipts(roots)
    invalidated_count = 0
    invalidated_receipt_ids: list[str] = []

    for rec_dict in records:
        receipt = ClearanceReceipt.from_dict(rec_dict)
        if not receipt.is_active:
            continue
        if receipt.judge_version != judge_version:
            continue

        if dry_run:
            invalidated_count += 1
            invalidated_receipt_ids.append(receipt.receipt_id)
            continue

        invalidated = receipt.to_dict()
        invalidated["invalidated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        invalidated["invalidated_by"] = f"judge_version_recall:{judge_version}"
        append_jsonl_locked(clearance_receipts_path(roots), invalidated)
        invalidated_count += 1
        invalidated_receipt_ids.append(receipt.receipt_id)

    return {
        "status": "ok",
        "dry_run": dry_run,
        "judge_version": judge_version,
        "invalidated_count": invalidated_count,
        "invalidated_receipt_ids": invalidated_receipt_ids,
    }


# ── E3: Invalidation engine ────────────────────────────────────────────────


def invalidate_receipts_since(
    roots: Any,
    *,
    watermark: int = 0,
) -> dict[str, Any]:
    """Invalidate receipts affected by corpus changes since *watermark*.

    For each active receipt:
    - If the receipt is ``conservative_full`` → always invalidated (any change).
    - If any event entity_set is empty → conservative_full for entity_scoped receipts.
    - If event entity_set ∩ receipt checked_entity_set is non-empty → invalidated.
    - Otherwise preserved.

    Returns a structured report. Invalidation appends updated receipt records
    (marked with ``invalidated_at`` / ``invalidated_by``) to the journal.
    The original record is not deleted.
    """
    from .jsonl_io import append_jsonl_locked

    events = read_corpus_change_events(roots)
    new_events = [e for e in events if int(e.get("event_id") or 0) > watermark]
    if not new_events:
        return {"status": "ok", "invalidated_count": 0, "events_since_watermark": 0}

    # Collect affected entity sets from new events
    all_event_entities: set[str] = set()
    has_unattributable_event = False
    affected_record_ids: set[str] = set()
    for event in new_events:
        entity_set = list(event.get("entity_set") or [])
        if entity_set:
            all_event_entities.update(entity_set)
        else:
            has_unattributable_event = True
        rid = str(event.get("record_id") or "")
        if rid:
            affected_record_ids.add(rid)

    invalidated_count = 0
    records = read_clearance_receipts(roots)

    for rec_dict in records:
        receipt = ClearanceReceipt.from_dict(rec_dict)
        if not receipt.is_active:
            continue

        should_invalidate = False
        invalidation_mode = "entity_scoped"

        if receipt.invalidation_mode == "conservative_full":
            should_invalidate = True
            invalidation_mode = "conservative_full"
        elif has_unattributable_event:
            should_invalidate = True
            invalidation_mode = "conservative_full"
        elif all_event_entities:
            receipt_entities = set(receipt.checked_entity_set)
            if receipt_entities & all_event_entities:
                should_invalidate = True
                invalidation_mode = "entity_scoped"
            elif affected_record_ids:
                # Check if receipt's conflict_refs overlap with affected records
                receipt_conflict_refs = set(receipt.conflict_refs)
                if receipt_conflict_refs & affected_record_ids:
                    should_invalidate = True
                    invalidation_mode = "entity_scoped"

        if should_invalidate:
            invalidated = receipt.to_dict()
            from datetime import timezone as _tz

            invalidated["invalidated_at"] = datetime.now(_tz.utc).isoformat().replace("+00:00", "Z")
            invalidated["invalidated_by"] = invalidation_mode
            append_jsonl_locked(clearance_receipts_path(roots), invalidated)
            invalidated_count += 1

    return {
        "status": "ok",
        "invalidated_count": invalidated_count,
        "events_since_watermark": len(new_events),
        "affected_entity_count": len(all_event_entities),
        "has_unattributable_event": has_unattributable_event,
    }
