"""Provisional crystallized record lifecycle sweep.

Manages TTL expiry, cap eviction, and recurrence detection for
resolver-approved provisional records. Follows invalidate-not-delete
pattern - records persist on disk, only canonical_state changes.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from plugins.memory.memory_os.crystallized import CrystallizedMemoryService
from plugins.memory.memory_os.store import MemoryOSStore


def provisional_sweep_manifest() -> dict[str, Any]:
    return {
        "name": "provisional_sweep",
        "kind": "governance",
        "version": "0.1.0",
        "layer": "L3",
        "dependencies": {
            "required": ["memory_os >=0.1.0", "execution_gate"],
        },
        "provides": {
            "commands": ["status", "doctor", "run_once"],
            "schedules": [],
            "reads": ["memory_os.crystallized"],
            "writes": ["local_artifact.provisional_sweep_runs"],
        },
        "defaults": {
            "enabled": True,
            "profile_scope": "per-profile",
        },
    }


class ProvisionalSweepModule:
    """TTL + cap + recurrence lifecycle for provisional crystallized records."""

    def __init__(self, hermes_home: str | Path, *, profile: str) -> None:
        self.hermes_home = Path(hermes_home).expanduser().resolve()
        self.profile = profile

    @property
    def module_root(self) -> Path:
        return self.hermes_home / "system-modules" / "provisional_sweep"

    @property
    def runs_path(self) -> Path:
        return self.module_root / "runs.jsonl"

    def run_once(
        self, *,
        store: MemoryOSStore,
        _store_root: Path | None = None,
    ) -> dict[str, Any]:
        """Run one tick: TTL expiry -> cap eviction -> recurrence detection."""
        service = CrystallizedMemoryService(store)
        records = service.list_provisional_records()
        now = datetime.now(timezone.utc)

        # Resolve max_provisional at call time (C3 / sentinel pattern)
        from plugins.memory.memory_os.knob_overrides import resolve_knob
        from plugins.memory.memory_os.jsonl_io import append_jsonl_locked, build_error_record, write_json_atomic
        max_provisional = resolve_knob("max_provisional", default=30, _store_root=_store_root)

        error_records: list[dict[str, Any]] = []

        # 0. Expiry cliff guard: find near-expiry records for owner digest
        near_expiry = find_expiring_provisional(store, within_hours=48)
        p = _expiring_list_path(store)
        write_json_atomic(p, near_expiry)

        # 1. TTL expiry
        expired = 0
        for r in records:
            expires_str = str(r.get("expires_at") or "").strip()
            if not expires_str:
                continue
            try:
                expires_at = datetime.fromisoformat(expires_str)
            except ValueError:
                continue
            if expires_at <= now:
                try:
                    service.invalidate_provisional_record(
                        r["id"],
                        reason="resolver_ttl_expired",
                        invalidated_by="provisional_sweep",
                    )
                    expired += 1
                except Exception:
                    # C4 fix: was bare "except: pass"
                    error_records.append(
                        build_error_record(
                            component="provisional_sweep",
                            operation="invalidate_provisional_record",
                            error_code="INVALIDATE_FAILED",
                            severity="error",
                            recoverable=True,
                            details={"record_id": r.get("id"), "reason": "resolver_ttl_expired"},
                        )
                    )

        # Re-read after TTL invalidations
        records_after_ttl = service.list_provisional_records()

        # 2. Cap eviction (oldest first, keep max_provisional)
        evicted = 0
        if len(records_after_ttl) > max_provisional:
            sorted_records = sorted(
                records_after_ttl,
                key=lambda r: str(r.get("approved_at") or ""),
            )
            to_evict = sorted_records[: len(sorted_records) - max_provisional]
            for r in to_evict:
                try:
                    service.invalidate_provisional_record(
                        r["id"],
                        reason="resolver_cap_evicted",
                        invalidated_by="provisional_sweep",
                    )
                    evicted += 1
                except Exception:
                    # C4 fix: was bare "except: pass"
                    error_records.append(
                        build_error_record(
                            component="provisional_sweep",
                            operation="invalidate_provisional_record",
                            error_code="INVALIDATE_FAILED",
                            severity="error",
                            recoverable=True,
                            details={"record_id": r.get("id"), "reason": "resolver_cap_evicted"},
                        )
                    )

        # Re-read final state for recurrence detection
        records_after_cap = service.list_provisional_records()

        # 3. Recurrence detection (mark for P5 digest escalation)
        escalated = _detect_recurrence(records_after_cap)

        result = {
            "schema_version": "hermes.provisional_sweep_result.v0",
            "module": "provisional_sweep",
            "profile": self.profile,
            "provisional_total": len(records),
            "expired_count": expired,
            "evicted_count": evicted,
            "escalated_count": len(escalated),
            "escalated_ids": escalated,
            "error_records": error_records,
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_crystallized_approval": False,
        }

        # Record run
        self.module_root.mkdir(parents=True, exist_ok=True)
        runs_record = {
            key: value
            for key, value in result.items()
            if key not in ("escalated_ids",)
        }
        append_jsonl_locked(self.runs_path, runs_record)

        return result

    def status(self) -> dict[str, Any]:
        service = CrystallizedMemoryService(
            _make_store(self.hermes_home, self.profile)
        )
        records = service.list_provisional_records()
        return {
            "schema_version": "hermes.provisional_sweep_status.v0",
            "module": "provisional_sweep",
            "profile": self.profile,
            "provisional_count": len(records),
            "near_expiry_count": sum(
                1 for r in records if _days_until_expiry(r.get("expires_at", "")) <= 1
            ),
        }

    def doctor(self) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        service = CrystallizedMemoryService(
            _make_store(self.hermes_home, self.profile)
        )
        records = service.list_provisional_records()
        from plugins.memory.memory_os.knob_overrides import resolve_knob
        max_provisional = resolve_knob("max_provisional", default=30)
        if len(records) > max_provisional:
            findings.append(
                {
                    "severity": "warning",
                    "code": "provisional_over_cap",
                    "message": f"{len(records)} active provisional records (cap={max_provisional}); sweep may need to run",
                }
            )
        status = "warning" if findings else "ok"
        return {
            "schema_version": "hermes.provisional_sweep_doctor.v0",
            "module": "provisional_sweep",
            "profile": self.profile,
            "status": status,
            "findings": findings,
        }


def _make_store(hermes_home: str | Path, profile: str) -> MemoryOSStore:
    """Create a MemoryOSStore for read-only operations (status/doctor)."""
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    roots = MemoryOSRoots.from_hermes_home(Path(hermes_home), profile=profile)
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def _detect_recurrence(records: list[dict[str, Any]]) -> list[str]:
    """Detect content that has been repeatedly re-approved across cycles."""
    content_counter: Counter = Counter()
    for r in records:
        body = str(r.get("body") or "").strip()
        if body:
            content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
            content_counter[content_hash] += 1

    escalated: list[str] = []
    for r in records:
        body = str(r.get("body") or "").strip()
        if body:
            content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
            if content_counter[content_hash] >= 3:
                escalated.append(r.get("id", ""))
    return escalated


def _days_until_expiry(expires_at: str) -> float:
    """Return days until expiry, negative if already expired."""
    if not expires_at:
        return float("inf")
    try:
        expires_dt = datetime.fromisoformat(expires_at)
        remaining = expires_dt - datetime.now(timezone.utc)
        return remaining.total_seconds() / 86400.0
    except (ValueError, TypeError):
        return float("inf")


def find_expiring_provisional(
    store: MemoryOSStore,
    *,
    within_hours: int = 48,
) -> list[dict[str, Any]]:
    """找 expires_at 在 within_hours 内的 active provisional 记录。

    按 expires_at 升序，最紧迫的在前。
    """
    from plugins.memory.memory_os.crystallized import CrystallizedMemoryService

    service = CrystallizedMemoryService(store)
    records = service.list_provisional_records()
    now = datetime.now(timezone.utc)
    threshold = now + timedelta(hours=within_hours)

    expiring: list[dict[str, Any]] = []
    for r in records:
        expires_str = str(r.get("expires_at") or "").strip()
        if not expires_str:
            continue
        try:
            expires_at = datetime.fromisoformat(expires_str)
        except ValueError:
            continue
        if expires_at <= threshold and expires_at > now:
            recurrence = 0
            try:
                recurrence = int(r.get("recurrence", 0))
            except (ValueError, TypeError):
                pass
            expiring.append({
                **r,
                "days_remaining": max(0, int((expires_at - now).total_seconds() / 86400)),
                "hours_remaining": max(0, int((expires_at - now).total_seconds() / 3600)),
                "recurrence": recurrence,
            })

    expiring.sort(key=lambda r: str(r.get("expires_at", "")))
    return expiring


def _expiring_list_path(store: MemoryOSStore) -> Path:
    """临时文件：临近过期 provisional 列表，供 digest 渲染读取."""
    return store.roots.memory_os_root / "system" / "expiring_provisional.json"
