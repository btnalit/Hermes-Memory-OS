"""Working-memory state service for Memory-OS."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from math import pow
from typing import Any

from .audit import append_audit
from .ids import new_working_id
from .schema import WORKING_SCHEMA_VERSION, WorkingItem
from .store import MemoryOSStore


ALLOWED_WORKING_KINDS = {"lingering", "emotional", "curiosity", "attention"}

# ── Decay defaults ───────────────────────────────────────────────────────
# Tuned to prevent unbounded accumulation: half-life reduced from 24h → 12h,
# expire threshold raised from 0.2 → 0.25 so low-weight items expire faster.
# Combined with prune_expired_items(), this keeps working-memory documents
# bounded without losing the signal that decay provides.

DEFAULT_HALF_LIFE_HOURS: float = 12.0
DEFAULT_EXPIRE_BELOW: float = 0.25

# ── Prune defaults ───────────────────────────────────────────────────────
# Items that have been expired for longer than this are eligible for removal.
# 24h grace period ensures audit records are written before the item is gone.

DEFAULT_PRUNE_MIN_AGE_HOURS: float = 24.0


class WorkingMemoryError(ValueError):
    """Raised when a working-memory operation is invalid."""


class WorkingMemoryService:
    """Manage profile-local working-memory documents."""

    def __init__(self, store: MemoryOSStore) -> None:
        self.store = store

    def add_item(
        self,
        kind: str,
        text: str,
        *,
        source_event_id: str = "",
        tags: list[str] | None = None,
        weight: float = 1.0,
        now: datetime | None = None,
    ) -> WorkingItem:
        self._validate_kind(kind)
        timestamp = _timestamp(now)
        item = WorkingItem(
            id=new_working_id(_datetime(now)),
            kind=kind,
            status="active",
            created_at=timestamp,
            updated_at=timestamp,
            text=str(text),
            source_event_id=source_event_id,
            tags=list(tags or []),
            weight=float(weight),
        )
        document = self.read_document(kind)
        document["updated_at"] = timestamp
        document["items"].append(asdict(item))
        self.store.write_working_document(kind, document)
        self._audit("working_item_added", "ok", {"item_id": item.id, "kind": kind})
        return item

    def read_document(self, kind: str) -> dict[str, Any]:
        self._validate_kind(kind)
        path = self.store.roots.working_root / f"{kind}.json"
        if not path.exists():
            return {
                "schema_version": WORKING_SCHEMA_VERSION,
                "updated_at": "",
                "items": [],
            }
        document = self.store.read_working_document(kind)
        if document.get("schema_version") != WORKING_SCHEMA_VERSION:
            raise WorkingMemoryError(f"Unsupported working schema: {document.get('schema_version')}")
        if not isinstance(document.get("items"), list):
            raise WorkingMemoryError(f"Working document items must be a list: {kind}")
        return document

    def decay_items(
        self,
        kind: str,
        *,
        now: datetime | None = None,
        half_life_hours: float = DEFAULT_HALF_LIFE_HOURS,
        expire_below: float = DEFAULT_EXPIRE_BELOW,
        audit_write: bool = True,
    ) -> list[WorkingItem]:
        self._validate_kind(kind)
        if half_life_hours <= 0:
            raise WorkingMemoryError("half_life_hours must be positive")
        current = _datetime(now)
        current_ts = current.isoformat()
        document = self.read_document(kind)
        updated_items: list[WorkingItem] = []
        changed = False
        for raw_item in document["items"]:
            item = _item_from_dict(raw_item)
            if item.status != "active":
                updated_items.append(item)
                continue
            elapsed_hours = max(0.0, (current - datetime.fromisoformat(item.updated_at)).total_seconds() / 3600.0)
            decayed_weight = item.weight * pow(0.5, elapsed_hours / half_life_hours)
            status = "expired" if decayed_weight < expire_below else "active"
            updated = WorkingItem(
                id=item.id,
                kind=item.kind,
                status=status,
                created_at=item.created_at,
                updated_at=current_ts,
                text=item.text,
                source_event_id=item.source_event_id,
                tags=list(item.tags),
                weight=decayed_weight,
            )
            if status == "expired" and item.status != "expired":
                self._audit("working_item_expired", "ok", {"item_id": item.id, "kind": kind})
            updated_items.append(updated)
            changed = True
        if changed:
            document["updated_at"] = current_ts
            document["items"] = [asdict(item) for item in updated_items]
            self.store.write_working_document(kind, document, audit=audit_write)
        return updated_items

    def prune_expired_items(
        self,
        kind: str,
        *,
        now: datetime | None = None,
        min_age_hours: float = DEFAULT_PRUNE_MIN_AGE_HOURS,
        audit_write: bool = True,
    ) -> int:
        """Remove expired items that have been expired for longer than min_age_hours.

        Only touches items with ``status == "expired"`` whose ``updated_at`` is
        at least *min_age_hours* in the past.  The grace period ensures audit
        records (written at the moment of expiry) are flushed before the item
        is deleted.

        Returns the number of pruned items.
        """
        self._validate_kind(kind)
        if min_age_hours < 0:
            raise WorkingMemoryError("min_age_hours must be non-negative")
        current = _datetime(now)
        document = self.read_document(kind)
        original_count = len(document["items"])
        if original_count == 0:
            return 0

        kept: list[dict[str, Any]] = []
        pruned = 0
        for raw_item in document["items"]:
            item = _item_from_dict(raw_item)
            if item.status != "expired":
                kept.append(raw_item)
                continue
            # Compute age since the item was marked expired (updated_at).
            try:
                updated_dt = datetime.fromisoformat(item.updated_at)
            except (ValueError, TypeError):
                # Malformed timestamp — keep the item rather than risk data loss.
                kept.append(raw_item)
                continue
            age_hours = (current - updated_dt).total_seconds() / 3600.0
            if age_hours >= min_age_hours:
                self._audit(
                    "working_item_pruned",
                    "ok",
                    {"item_id": item.id, "kind": kind, "age_hours": round(age_hours, 1)},
                )
                pruned += 1
            else:
                kept.append(raw_item)

        if pruned > 0:
            document["updated_at"] = current.isoformat()
            document["items"] = kept
            self.store.write_working_document(kind, document, audit=audit_write)
        return pruned

    def status_summary(self) -> str:
        lines: list[str] = []
        for kind in sorted(ALLOWED_WORKING_KINDS):
            document = self.read_document(kind)
            items = [_item_from_dict(item) for item in document["items"]]
            if not items:
                continue
            active = [item for item in items if item.status == "active"]
            expired = [item for item in items if item.status == "expired"]
            top_weight = max((item.weight for item in items), default=0.0)
            lines.append(
                f"{kind}: {len(active)} active, {len(expired)} expired, top weight {top_weight:.3f}"
            )
        return "\n".join(lines)

    def trace_working_item(self, item_id: str) -> dict[str, Any]:
        for kind in sorted(ALLOWED_WORKING_KINDS):
            document = self.read_document(kind)
            for raw_item in document["items"]:
                item = _item_from_dict(raw_item)
                if item.id == item_id:
                    return {
                        "found": True,
                        "document": kind,
                        "item": asdict(item),
                        "audit_actions": self._audit_actions_for(item_id),
                    }
        return {"found": False, "document": "", "item": None, "audit_actions": self._audit_actions_for(item_id)}

    def _validate_kind(self, kind: str) -> None:
        if kind not in ALLOWED_WORKING_KINDS:
            raise WorkingMemoryError(f"Unsupported working memory kind: {kind}")

    def _audit(self, action: str, status: str, details: dict[str, Any]) -> None:
        append_audit(
            self.store.roots.audit_path,
            action=action,
            status=status,
            target="working-memory",
            details=details,
        )

    def _audit_actions_for(self, item_id: str) -> list[str]:
        path = self.store.roots.audit_path
        if not path.exists():
            return []
        actions: list[str] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("details", {}).get("item_id") == item_id:
                actions.append(str(record.get("action", "")))
        return actions


def _datetime(value: datetime | None) -> datetime:
    return (value or datetime.now(timezone.utc)).astimezone(timezone.utc)


def _timestamp(value: datetime | None) -> str:
    return _datetime(value).isoformat()


def _item_from_dict(data: dict[str, Any]) -> WorkingItem:
    return WorkingItem(
        id=str(data["id"]),
        kind=str(data["kind"]),
        status=str(data["status"]),
        created_at=str(data["created_at"]),
        updated_at=str(data["updated_at"]),
        text=str(data["text"]),
        source_event_id=str(data.get("source_event_id", "")),
        tags=[str(tag) for tag in data.get("tags", [])],
        weight=float(data.get("weight", 0.0)),
    )
