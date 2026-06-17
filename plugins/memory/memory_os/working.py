"""Working-memory state service for Memory-OS."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from math import pow
from typing import Any

from .audit import append_audit
from .ids import new_working_id
from .schema import WORKING_SCHEMA_VERSION, WORKING_SCHEMA_VERSION_V0, WorkingItem
from .store import MemoryOSStore


ALLOWED_WORKING_KINDS = {"lingering", "emotional", "curiosity", "attention"}

# ── Per-kind decay + cap parameters ──────────────────────────────────────
# Each working memory kind has its own half-life, expire threshold, and max
# item cap.  The cap bounds storage without forcing faster forgetting:
# when add_item exceeds max_items, the lowest-weight items are evicted.
# Decay uses per-kind half-life + expire_below instead of one-size-fits-all.
#
# Rationale:
#   emotional  — slow decay (48h), low threshold: emotional salience persists
#   curiosity  — medium decay (24h): topic curiosity fades over a day
#   lingering  — medium decay (18h): the most-produced kind; cap=50 as backstop
#   attention  — fast decay (6h): momentary focus, naturally transient

WORKING_KIND_PARAMS: dict[str, dict[str, float]] = {
    "lingering":  {"half_life_hours": 18.0, "max_items": 50, "expire_below": 0.10},
    "emotional":  {"half_life_hours": 48.0, "max_items": 30, "expire_below": 0.05},
    "curiosity":  {"half_life_hours": 24.0, "max_items": 30, "expire_below": 0.08},
    "attention":  {"half_life_hours": 6.0,  "max_items": 20, "expire_below": 0.10},
}

# ── Prune defaults ───────────────────────────────────────────────────────
# Items expired longer than this are eligible for removal.  72h grace period
# keeps expired items visible in owner-facing surfaces (digests, prefetch)
# long enough to observe the expiry before removal.  Cap (§add_item) is the
# primary storage bound; prune is the deep-clean backstop.

DEFAULT_PRUNE_MIN_AGE_HOURS: float = 72.0


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
        params = WORKING_KIND_PARAMS.get(kind, {})
        max_items = int(params.get("max_items", 50))
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
            last_decayed_at="",
            expired_at="",
        )
        document = self.read_document(kind)
        document["items"].append(asdict(item))

        # ── Top-N cap: evict lowest-weight items when over max_items ─────
        if len(document["items"]) > max_items:
            # Sort by weight ascending (lowest first), tiebreak by created_at
            sorted_items = sorted(
                document["items"],
                key=lambda i: (i.get("weight", 0.0), i.get("created_at", "")),
            )
            overflow_count = len(sorted_items) - max_items
            evicted = sorted_items[:overflow_count]
            for evicted_raw in evicted:
                evicted_item = _item_from_dict(evicted_raw)
                self._audit(
                    "working_item_evicted",
                    "ok",
                    {
                        "item_id": evicted_item.id,
                        "kind": kind,
                        "reason": "cap_overflow",
                        "weight": evicted_item.weight,
                        "max_items": max_items,
                    },
                )
            document["items"] = sorted_items[overflow_count:]

        document["updated_at"] = timestamp
        document["schema_version"] = WORKING_SCHEMA_VERSION
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
        doc_version = document.get("schema_version", "")
        if doc_version not in (WORKING_SCHEMA_VERSION, WORKING_SCHEMA_VERSION_V0, ""):
            raise WorkingMemoryError(f"Unsupported working schema: {doc_version}")
        if not isinstance(document.get("items"), list):
            raise WorkingMemoryError(f"Working document items must be a list: {kind}")
        # ── v0 → v1 migration: fill missing fields on read ──────────────
        if doc_version in (WORKING_SCHEMA_VERSION_V0, ""):
            for raw_item in document["items"]:
                raw_item.setdefault("last_decayed_at", "")
                raw_item.setdefault("expired_at", "")
            document["schema_version"] = WORKING_SCHEMA_VERSION
        return document

    def decay_items(
        self,
        kind: str,
        *,
        now: datetime | None = None,
        half_life_hours: float | None = None,
        expire_below: float | None = None,
        audit_write: bool = True,
    ) -> list[WorkingItem]:
        self._validate_kind(kind)
        params = WORKING_KIND_PARAMS.get(kind, {})
        effective_half_life = half_life_hours if half_life_hours is not None else float(params.get("half_life_hours", 18.0))
        effective_expire_below = expire_below if expire_below is not None else float(params.get("expire_below", 0.10))
        if effective_half_life <= 0:
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
            # ── Decay from last_decayed_at (v1), fallback to updated_at (v0 compat) ──
            decay_base_str = item.last_decayed_at or item.updated_at or item.created_at
            decay_base = datetime.fromisoformat(decay_base_str)
            elapsed_hours = max(0.0, (current - decay_base).total_seconds() / 3600.0)
            decayed_weight = item.weight * pow(0.5, elapsed_hours / effective_half_life)
            new_status = "expired" if decayed_weight < effective_expire_below else "active"
            # ── Set expired_at on first expiry; never change it after ────
            new_expired_at = item.expired_at
            if new_status == "expired" and not item.expired_at:
                new_expired_at = current_ts
            updated = WorkingItem(
                id=item.id,
                kind=item.kind,
                status=new_status,
                created_at=item.created_at,
                updated_at=item.updated_at,          # ← NOT touched: preserves content recency
                text=item.text,
                source_event_id=item.source_event_id,
                tags=list(item.tags),
                weight=decayed_weight,
                last_decayed_at=current_ts,           # ← decay bookkeeping on its own field
                expired_at=new_expired_at,
            )
            if new_status == "expired" and item.status != "expired":
                self._audit("working_item_expired", "ok", {"item_id": item.id, "kind": kind})
            updated_items.append(updated)
            changed = True
        if changed:
            document["schema_version"] = WORKING_SCHEMA_VERSION
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

        Only touches items with ``status == "expired"`` whose ``expired_at``
        (or ``updated_at`` as v0 fallback) is at least *min_age_hours* in the
        past.  The grace period keeps expired items visible in owner-facing
        surfaces (digests, prefetch) long enough to observe the expiry before
        removal.

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
            # ── Grace from expired_at (v1), fallback updated_at (v0 compat) ──
            expiry_base_str = item.expired_at or item.updated_at
            try:
                expiry_dt = datetime.fromisoformat(expiry_base_str)
            except (ValueError, TypeError):
                # Malformed timestamp — keep the item rather than risk data loss.
                kept.append(raw_item)
                continue
            age_hours = (current - expiry_dt).total_seconds() / 3600.0
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
        last_decayed_at=str(data.get("last_decayed_at", "")),
        expired_at=str(data.get("expired_at", "")),
    )
