"""Override Sweep module — TTL/cap/kill-switch lifecycle for knob overrides.

Mirrors provisional_sweep but operates on knob overrides instead of
crystallized records. No-agent lane: deterministic TTL check + revert.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from plugins.memory.memory_os.audit import append_audit
from plugins.memory.memory_os.jsonl_io import build_error_record
from plugins.memory.memory_os.knob_overrides import (
    list_active_overrides,
    revert_override,
)

MAX_OVERRIDES = 30

def override_sweep_manifest() -> dict[str, Any]:
    return {
        "name": "override_sweep",
        "kind": "governance",
        "version": "0.1.0",
        "layer": "L3",
        "dependencies": {
            "required": ["memory_os >=0.1.0", "execution_gate"],
        },
        "provides": {
            "commands": ["status", "doctor", "run_once"],
            "schedules": [],
            "reads": ["memory_os.knob_overrides"],
            "writes": ["local_artifact.override_sweep_runs"],
        },
        "defaults": {
            "enabled": True,
            "profile_scope": "per-profile",
        },
    }


class OverrideSweepModule:
    """TTL + kill-switch lifecycle for provisional knob overrides."""

    def __init__(self, hermes_home: str | Path, *, profile: str) -> None:
        self.hermes_home = Path(hermes_home).expanduser().resolve()
        self.profile = profile

    @property
    def module_root(self) -> Path:
        return self.hermes_home / "system-modules" / "override_sweep"

    @property
    def runs_path(self) -> Path:
        return self.module_root / "runs.jsonl"

    def run_once(
        self,
        *,
        _store_root: Path | None = None,
        _now: datetime | None = None,
        _kill_switch_enabled: bool = False,
    ) -> dict[str, Any]:
        """Run one tick: TTL expiry -> cap eviction -> kill-switch revert."""
        now = _now or datetime.now(timezone.utc)
        from plugins.memory.memory_os.roots import MemoryOSRoots

        roots = (
            MemoryOSRoots.from_hermes_home(self.hermes_home, profile=self.profile)
            if _store_root is None
            else None
        )
        active = list_active_overrides(roots=roots, _store_root=_store_root, _now=now)

        expired = 0
        evicted = 0
        kill_reverted = 0
        error_records: list[dict[str, Any]] = []

        # 1. Kill switch: revert ALL active overrides
        if _kill_switch_enabled:
            for override in active:
                try:
                    revert_override(
                        override["id"],
                        reason="kill_switch_engaged",
                        roots=roots,
                        _store_root=_store_root,
                    )
                    kill_reverted += 1
                except Exception:
                    error_records.append(
                        build_error_record(
                            component="override_sweep",
                            operation="revert_override",
                            error_code="REVERT_FAILED",
                            severity="error",
                            recoverable=True,
                            details={"override_id": override.get("id"), "reason": "kill_switch_engaged"},
                        )
                    )
            # After kill switch, nothing else to do
            active = []

        if not _kill_switch_enabled:
            # 2. TTL expiry
            for override in active:
                expires_str = str(override.get("expires_at") or "").strip()
                if not expires_str:
                    continue
                try:
                    expires_at = datetime.fromisoformat(expires_str)
                except ValueError:
                    continue
                if expires_at <= now and override.get("state") == "active":
                    try:
                        revert_override(
                            override["id"],
                            reason="resolver_ttl_expired",
                            roots=roots,
                            _store_root=_store_root,
                        )
                        expired += 1
                    except Exception:
                        error_records.append(
                            build_error_record(
                                component="override_sweep",
                                operation="revert_override",
                                error_code="REVERT_FAILED",
                                severity="error",
                                recoverable=True,
                                details={"override_id": override.get("id"), "reason": "resolver_ttl_expired"},
                            )
                        )

            # Re-read after TTL invalidations
            active_after_ttl = list_active_overrides(
                roots=roots, _store_root=_store_root, _now=now
            )

            # 3. Cap eviction (oldest first, keep MAX_OVERRIDES)
            if len(active_after_ttl) > MAX_OVERRIDES:
                sorted_overrides = sorted(
                    active_after_ttl,
                    key=lambda r: str(r.get("ts") or ""),
                )
                to_evict = sorted_overrides[: len(sorted_overrides) - MAX_OVERRIDES]
                for override in to_evict:
                    try:
                        revert_override(
                            override["id"],
                            reason="resolver_cap_evicted",
                            roots=roots,
                            _store_root=_store_root,
                        )
                        evicted += 1
                    except Exception:
                        error_records.append(
                            build_error_record(
                                component="override_sweep",
                                operation="revert_override",
                                error_code="REVERT_FAILED",
                                severity="error",
                                recoverable=True,
                                details={"override_id": override.get("id"), "reason": "resolver_cap_evicted"},
                            )
                        )

        result = {
            "schema_version": "hermes.override_sweep_result.v0",
            "module": "override_sweep",
            "profile": self.profile,
            "active_total": len(active),
            "expired_count": expired,
            "evicted_count": evicted,
            "kill_reverted_count": kill_reverted,
            "revert_fail_count": len(error_records),
            "error_records": error_records,
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_crystallized_approval": False,
        }

        # Record run
        self.module_root.mkdir(parents=True, exist_ok=True)
        runs_record = {key: value for key, value in result.items()}
        from plugins.memory.memory_os.jsonl_io import append_jsonl_locked
        append_jsonl_locked(self.runs_path, runs_record)

        # Audit
        audit_path = Path(self.hermes_home) / "memory-os" / "system" / "write_audit.jsonl"
        append_audit(
            audit_path,
            action="override_sweep_run",
            status="ok",
            target=str(self.module_root),
            details={
                "expired": expired,
                "evicted": evicted,
                "kill_reverted": kill_reverted,
                "profile": self.profile,
            },
        )

        return result

    def status(self) -> dict[str, Any]:
        from plugins.memory.memory_os.roots import MemoryOSRoots

        roots = MemoryOSRoots.from_hermes_home(self.hermes_home, profile=self.profile)
        active = list_active_overrides(roots=roots)
        return {
            "schema_version": "hermes.override_sweep_status.v0",
            "module": "override_sweep",
            "profile": self.profile,
            "active_override_count": len(active),
            "near_expiry_count": sum(
                1 for r in active
                if _days_until_expiry(r.get("expires_at", "")) <= 1
            ),
        }

    def doctor(self) -> dict[str, Any]:
        from plugins.memory.memory_os.roots import MemoryOSRoots

        findings: list[dict[str, Any]] = []
        roots = MemoryOSRoots.from_hermes_home(self.hermes_home, profile=self.profile)
        active = list_active_overrides(roots=roots)
        if len(active) > MAX_OVERRIDES:
            findings.append({
                "severity": "warning",
                "code": "overrides_over_cap",
                "message": f"{len(active)} active overrides (cap={MAX_OVERRIDES}); sweep may need to run",
            })
        status = "warning" if findings else "ok"
        return {
            "schema_version": "hermes.override_sweep_doctor.v0",
            "module": "override_sweep",
            "profile": self.profile,
            "status": status,
            "findings": findings,
        }


def _days_until_expiry(expires_at: str) -> float:
    if not expires_at:
        return float("inf")
    try:
        expires_dt = datetime.fromisoformat(expires_at)
        remaining = expires_dt - datetime.now(timezone.utc)
        return remaining.total_seconds() / 86400.0
    except (ValueError, TypeError):
        return float("inf")
