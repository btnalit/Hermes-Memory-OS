"""Runtime heartbeat for deployed Memory-OS profiles."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .audit import append_audit
from .crystallized import append_candidate_queue, read_candidate_queue
from .index import MemoryOSIndex
from .inner_drive import InnerDriveEngine, select_events_for_inner_drive
from .store import MemoryOSStore
from .working import ALLOWED_WORKING_KINDS, WorkingMemoryService


class MemoryOSRuntime:
    """Advance canonical events into working memory and approval candidates."""

    def __init__(self, store: MemoryOSStore) -> None:
        self.store = store

    def heartbeat(
        self,
        *,
        max_events: int = 100,
        max_events_per_source_class: int | dict[str, int] = 20,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if max_events <= 0:
            raise ValueError("max_events must be positive")
        self.store.initialize()
        current = now or datetime.now(timezone.utc)
        try:
            self._write_attempt_state(current)
            state = self._read_state()
            return self._heartbeat_checked(
                max_events=max_events,
                max_events_per_source_class=max_events_per_source_class,
                current=current,
                state=state,
            )
        except Exception as exc:
            self._record_heartbeat_error(current, exc)
            raise

    def _heartbeat_checked(
        self,
        *,
        max_events: int,
        max_events_per_source_class: int | dict[str, int],
        current: datetime,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        already_processed_ids = {str(event_id) for event_id in state.get("processed_event_ids", [])}
        processed_ids = set(already_processed_ids)
        events = sorted(self.store.read_events(), key=lambda event: event.ts)
        pending, cap_deferred = select_events_for_inner_drive(
            events,
            processed_ids,
            max_events=max_events,
            max_events_per_source_class=max_events_per_source_class,
        )
        engine = InnerDriveEngine(self.store)
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
                append_candidate_queue(self.store, result.candidate)
                candidate_created_count += 1
            if result.working_item is None and result.candidate is None:
                policy_skipped_now.append(event.id)
            processed_ids.add(event.id)
            processed_now.append(event.id)

        working = WorkingMemoryService(self.store)
        decayed_documents: list[str] = []
        for kind in sorted(ALLOWED_WORKING_KINDS):
            before = working.read_document(kind)
            if before.get("items"):
                working.decay_items(kind, now=current, audit_write=False)
                decayed_documents.append(kind)

        latest_processed_event_id = processed_now[-1] if processed_now else str(state.get("last_processed_event_id") or "")
        current_ts = current.isoformat()
        self._write_state(
            {
                "schema_version": "memory-os.runtime_state.v0",
                "last_attempt_at": current_ts,
                "last_heartbeat_at": current_ts,
                "processed_event_count": len(processed_ids),
                "last_processed_event_id": latest_processed_event_id,
                "processed_event_ids": sorted(processed_ids),
            }
        )
        index_counts = MemoryOSIndex(self.store.roots).sync_from_store(self.store)
        report = {
            "schema_version": "memory-os.heartbeat.v0",
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
            "working_item_count": _working_item_count(self.store),
            "candidate_count": len(read_candidate_queue(self.store.roots)),
            "crystallized_record_count": _crystallized_record_count(self.store),
            "index_counts": index_counts,
            "decayed_documents": decayed_documents,
            "runtime_state_path": str(self._state_path),
        }
        if _heartbeat_has_meaningful_audit(report):
            append_audit(
                self.store.roots.audit_path,
                action="runtime_heartbeat",
                status="ok",
                target=str(self.store.roots.memory_os_root),
                details=report,
            )
        return report

    @property
    def _state_path(self) -> Path:
        return self.store.roots.memory_os_root / "runtime" / "heartbeat_state.json"

    def _read_state(self) -> dict[str, Any]:
        if not self._state_path.exists():
            return {"schema_version": "memory-os.runtime_state.v0", "processed_event_ids": []}
        return json.loads(self._state_path.read_text(encoding="utf-8"))

    def _write_state(self, state: dict[str, Any]) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _write_attempt_state(self, current: datetime) -> None:
        state = self._read_state()
        state["last_attempt_at"] = current.isoformat()
        self._write_state(state)

    def _write_error_state(self, current: datetime, exc: Exception) -> None:
        state = self._read_state()
        state["last_attempt_at"] = current.isoformat()
        state["last_error"] = {"type": type(exc).__name__, "message": str(exc)[:200]}
        self._write_state(state)

    def _record_heartbeat_error(self, current: datetime, exc: Exception) -> None:
        details = {"error_type": type(exc).__name__, "message": str(exc)[:200]}
        try:
            self._write_error_state(current, exc)
        except Exception as state_exc:
            details["state_error_type"] = type(state_exc).__name__
            details["state_error_message"] = str(state_exc)[:200]
        try:
            append_audit(
                self.store.roots.audit_path,
                action="heartbeat_error_summary",
                status="error",
                target=str(self.store.roots.memory_os_root),
                details=details,
            )
        except Exception:
            pass


def _working_item_count(store: MemoryOSStore) -> int:
    count = 0
    for path in sorted(store.roots.working_root.glob("*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        count += len(document.get("items", []))
    return count


def _crystallized_record_count(store: MemoryOSStore) -> int:
    count = 0
    for path in sorted(store.roots.crystallized_root.glob("*.md")):
        count += sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip() == "---") // 2
    return count


def _heartbeat_has_meaningful_audit(report: dict[str, Any]) -> bool:
    return any(
        int(report.get(key, 0) or 0) > 0
        for key in (
            "processed_event_count",
            "policy_skipped_event_count",
            "cap_deferred_event_count",
            "working_created_count",
            "candidate_created_count",
        )
    )
