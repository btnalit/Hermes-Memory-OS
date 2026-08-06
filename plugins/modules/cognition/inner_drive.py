"""Runtime Inner Drive module over canonical Memory-OS events."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from plugins.memory.memory_os.audit import append_audit
from plugins.memory.memory_os.crystallized import append_candidate_queue, read_candidate_queue
from plugins.memory.memory_os.inner_drive import (
    InnerDriveEngine,
    select_events_for_inner_drive,
    DEFAULT_SOURCE_CLASS_CAP,
)
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.memory.memory_os.working import ALLOWED_WORKING_KINDS
from plugins.system.scheduler import ScheduleCoordinator


def inner_drive_manifest() -> dict[str, Any]:
    """Return the v0.1 Inner Drive runtime module manifest."""

    return {
        "name": "inner_drive",
        "kind": "cognition",
        "version": "0.1.0",
        "layer": "L2",
        "dependencies": {
            "required": ["memory_os >=0.1.0", "scheduler"],
            "optional": ["proposal_queue"],
        },
        "provides": {
            "commands": ["status", "doctor", "run-once"],
            "schedules": ["inner_drive_heartbeat"],
            "reads": ["memory_os.events.summary", "memory_os.working"],
            "writes": [
                "memory_os.working",
                "memory_os.crystallized_candidates",
                "memory_os.audit",
                "local_artifact.inner_drive_state",
            ],
        },
        "defaults": {
            "enabled": False,
            "delivery_mode": "no-send",
            "profile_scope": "per-profile",
        },
        "memory_os_compat": {
            "min_version": "0.1.0",
            "max_version": "0.2.x",
            "schema_versions": {
                "event": ["memory-os.event.v0"],
                "working": ["memory-os.working.v0"],
                "crystallized": ["memory-os.crystallized.v0"],
            },
        },
    }


class InnerDriveRuntimeModule:
    """Advance profile-local Memory-OS events into working state and candidates."""

    lock_resource_id = "inner_drive.runtime"

    def __init__(self, hermes_home: str | Path, *, profile: str) -> None:
        self.hermes_home = Path(hermes_home).expanduser().resolve()
        self.profile = profile

    @property
    def module_root(self) -> Path:
        return self.hermes_home / "system-modules" / "inner_drive"

    @property
    def state_path(self) -> Path:
        return self.module_root / "state.json"

    @property
    def lock_root(self) -> Path:
        return self.hermes_home / "system-modules" / "locks"

    def status(self, *, store: MemoryOSStore | None = None) -> dict[str, Any]:
        state = self._read_state()
        event_count = len(store.read_events()) if store is not None else 0
        return {
            "schema_version": "hermes.inner_drive_status.v0",
            "module": "inner_drive",
            "profile": self.profile,
            "delivery_mode": "no-send",
            "state_path": str(self.state_path),
            "event_count": event_count,
            "processed_event_count": len(state.get("processed_event_ids", [])),
            "actual_send": False,
        }

    def doctor(self, *, store: MemoryOSStore | None = None, min_events: int = 1) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        event_count = 0
        if store is None:
            findings.append(
                {
                    "severity": "warning",
                    "code": "memory_os_store_not_provided",
                    "message": "Inner Drive doctor needs a MemoryOSStore for event checks",
                }
            )
        else:
            event_count = len(_profile_events(store, self.profile))
            if event_count == 0:
                findings.append(
                    {
                        "severity": "warning",
                        "code": "no_memory_os_events",
                        "message": "No Memory-OS events are available for Inner Drive",
                    }
                )
            elif event_count < min_events:
                findings.append(
                    {
                        "severity": "warning",
                        "code": "insufficient_events",
                        "message": f"Only {event_count} events available; Inner Drive will run degraded",
                    }
                )

        return {
            "schema_version": "hermes.inner_drive_doctor.v0",
            "module": "inner_drive",
            "profile": self.profile,
            "status": "warning" if findings else "ok",
            "event_count": event_count,
            "findings": findings,
        }

    def run_once(
        self,
        *,
        store: MemoryOSStore,
        coordinator: ScheduleCoordinator | None = None,
        max_events: int = 100,
        max_events_per_source_class: int | dict[str, int] = DEFAULT_SOURCE_CLASS_CAP,
        min_events: int = 1,
        lock_ttl_seconds: int = 300,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Run one tick of inner-drive processing (module-bus test host).

        NOT deprecated dead code, and not the production path either:
        production is MemoryOSRuntime.heartbeat() driving InnerDriveEngine
        directly (runtime.py). This entry point is the test host for the
        plugins/system module-bus/lifecycle contract — the system_modularization
        suite (dedicated file + integrated trace test) exercises it as the
        canonical example module. Deleting it deletes that contract's test
        surface; new production code should still use
        MemoryOSRuntime.heartbeat().
        """
        if max_events <= 0:
            raise ValueError("max_events must be positive")
        schedule = coordinator or ScheduleCoordinator(self.lock_root)
        owner = f"inner_drive:{self.profile}"
        lock = schedule.acquire_lock(
            self.lock_resource_id,
            owner=owner,
            ttl_seconds=lock_ttl_seconds,
            now=now,
        )
        if not lock.acquired:
            return {
                "schema_version": "hermes.inner_drive_result.v0",
                "module": "inner_drive",
                "profile": self.profile,
                "status": "deferred",
                "reason": "lock_held",
                "processed_event_count": 0,
                "lock_contention_count": lock.lock_contention_count,
                "actual_send": False,
            }

        try:
            return self._run_locked(
                store=store,
                max_events=max_events,
                max_events_per_source_class=max_events_per_source_class,
                min_events=min_events,
                now=now,
            )
        finally:
            schedule.release_lock(self.lock_resource_id, owner=owner)

    def _run_locked(
        self,
        *,
        store: MemoryOSStore,
        max_events: int,
        max_events_per_source_class: int | dict[str, int],
        min_events: int,
        now: datetime | None,
    ) -> dict[str, Any]:
        store.initialize()
        state = self._read_state()
        already_processed_ids = {str(event_id) for event_id in state.get("processed_event_ids", [])}
        processed_ids = set(already_processed_ids)
        events = sorted(_profile_events(store, self.profile), key=lambda event: event.ts)
        pending, cap_deferred = select_events_for_inner_drive(
            events,
            processed_ids,
            max_events=max_events,
            max_events_per_source_class=max_events_per_source_class,
        )

        engine = InnerDriveEngine(store)
        processed_now: list[str] = []
        policy_skipped_now: list[str] = []
        source_class_counts: dict[str, int] = {}
        candidate_created_count = 0
        working_created_count = 0
        for event in pending:
            result = engine.process_event(event)
            source_class = result.decision.source_class
            source_class_counts[source_class] = source_class_counts.get(source_class, 0) + 1
            if result.working_item is not None:
                working_created_count += 1
            if result.candidate is not None:
                append_candidate_queue(store, result.candidate)
                candidate_created_count += 1
            if result.working_item is None and result.candidate is None:
                policy_skipped_now.append(event.id)
            processed_ids.add(event.id)
            processed_now.append(event.id)

        degraded = len(events) < min_events
        status = "warning" if degraded else "ok"
        timestamp = _timestamp(now)
        self._write_state(
            {
                "schema_version": "hermes.inner_drive_state.v0",
                "profile": self.profile,
                "last_run_at": timestamp,
                "processed_event_ids": sorted(processed_ids),
            }
        )
        report = {
            "schema_version": "hermes.inner_drive_result.v0",
            "module": "inner_drive",
            "profile": self.profile,
            "status": status,
            "processed_event_count": len(processed_now),
            "processed_event_ids": processed_now,
            "policy_skipped_event_count": len(policy_skipped_now),
            "policy_skipped_event_ids": policy_skipped_now,
            "cap_deferred_event_count": len(cap_deferred),
            "cap_deferred_event_ids": [event.id for event in cap_deferred],
            "source_class_counts": source_class_counts,
            "working_created_count": working_created_count,
            "candidate_created_count": candidate_created_count,
            "already_processed_event_count": len([event for event in events if event.id in already_processed_ids]),
            "total_event_count": len(events),
            "working_item_count": _working_item_count(store),
            "candidate_count": len(read_candidate_queue(store)),
            "degraded": degraded,
            "actual_send": False,
            "state_path": str(self.state_path),
        }
        if degraded:
            report["reason"] = "insufficient_events"
        append_audit(
            store.roots.audit_path,
            action="inner_drive_module_run",
            status=status,
            target=str(self.module_root),
            details=report,
        )
        return report

    def _read_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"schema_version": "hermes.inner_drive_state.v0", "profile": self.profile, "processed_event_ids": []}
        parsed = json.loads(self.state_path.read_text(encoding="utf-8"))
        return dict(parsed) if isinstance(parsed, dict) else {}

    def _write_state(self, state: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _profile_events(store: MemoryOSStore, profile: str):
    return [event for event in store.read_events() if event.profile == profile]


def _working_item_count(store: MemoryOSStore) -> int:
    count = 0
    for kind in sorted(ALLOWED_WORKING_KINDS):
        path = store.roots.working_root / f"{kind}.json"
        if not path.exists():
            continue
        document = json.loads(path.read_text(encoding="utf-8"))
        count += len(document.get("items", []))
    return count


def _timestamp(value: datetime | None) -> str:
    return (value or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
