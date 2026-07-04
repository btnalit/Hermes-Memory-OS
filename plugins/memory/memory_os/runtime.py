"""Runtime heartbeat for deployed Memory-OS profiles."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .audit import append_audit
from .crystallized import append_candidate_queue, read_candidate_queue
from .execution_gate import complete_execution_gate_envelope, start_execution_gate_envelope
from .event_stats import build_event_stats, write_event_stats
from .index import MemoryOSIndex
from .inner_drive import InnerDriveEngine, select_events_for_inner_drive
from .jsonl_io import build_error_record, write_json_atomic
from .session_mirror import auto_apply_graduated_session_mirror
from .store import MemoryOSStore
from .working import ALLOWED_WORKING_KINDS, WorkingMemoryService

RECENT_PROCESSED_EVENT_IDS_LIMIT = 2000


def _dedupe_preserve_order(ids: list[str]) -> list[str]:
    """Deduplicate while preserving most-recent-first insertion order."""
    seen: set[str] = set()
    result: list[str] = []
    for eid in reversed(ids):
        if eid not in seen:
            seen.add(eid)
            result.append(eid)
    result.reverse()
    return result


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
        # Windowed read: recent_processed_event_ids first, fall back to legacy processed_event_ids
        recent_ids = state.get("recent_processed_event_ids")
        if recent_ids is None:
            recent_ids = state.get("processed_event_ids", [])
        already_processed_ids = {str(event_id) for event_id in recent_ids}
        processed_ids = set(already_processed_ids)
        runtime_gate = start_execution_gate_envelope(
            self.store,
            lane_id="runtime_heartbeat_core",
            trigger_surface="runtime_heartbeat",
            risk_class="deterministic_maintenance",
            human_approval_required=False,
            why_no_human_approval="deterministic heartbeat maintenance; no external send or owner-boundary action",
            scope={"max_events": max_events, "max_events_per_source_class": max_events_per_source_class},
            boundary={
                "actual_send": False,
                "actual_execute": False,
                "actual_identity_write": False,
                "actual_unapproved_crystallized_approval": False,
            },
            precheck={"already_processed_event_count": len(already_processed_ids)},
        )
        session_mirror_auto_apply = auto_apply_graduated_session_mirror(self.store)
        events = sorted(self.store.read_events(), key=lambda event: event.ts)
        # Write event_stats cache for O(1) status/monitor reads
        try:
            event_dicts = [e.to_dict() for e in events]
            stats = build_event_stats(event_dicts)
            stats.events_root = str(self.store.roots.events_root)
            write_event_stats(self.store.roots, stats)
        except Exception:
            pass  # stats are best-effort; never fail heartbeat for stats
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
        pruned_total = 0
        for kind in sorted(ALLOWED_WORKING_KINDS):
            before = working.read_document(kind)
            if before.get("items"):
                working.decay_items(kind, now=current, audit_write=False)
                pruned_total += working.prune_expired_items(kind, now=current, audit_write=False)
                decayed_documents.append(kind)

        latest_processed_event_id = processed_now[-1] if processed_now else str(state.get("last_processed_event_id") or "")
        current_ts = current.isoformat()
        # Windowed ID tracking — preserve insertion order, never sorted() by id
        prev_recent = list(state.get("recent_processed_event_ids") or state.get("processed_event_ids", []))
        windowed_ids = _dedupe_preserve_order(prev_recent + processed_now)[-RECENT_PROCESSED_EVENT_IDS_LIMIT:]
        self._write_state(
            {
                "schema_version": "memory-os.runtime_state.v0",
                "last_attempt_at": current_ts,
                "last_heartbeat_at": current_ts,
                "processed_event_count": len(processed_ids),
                "processed_event_count_total": state.get("processed_event_count_total", 0) + len(processed_now),
                "last_processed_event_id": latest_processed_event_id,
                "last_processed_event_ts": current_ts,
                "recent_processed_event_ids": windowed_ids,
                "recent_processed_event_ids_limit": RECENT_PROCESSED_EVENT_IDS_LIMIT,
                "processed_event_ids_compacted": True,
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
            "pruned_working_items": pruned_total,
            "runtime_state_path": str(self._state_path),
            "session_mirror_auto_apply": _bounded_session_mirror_auto_apply(session_mirror_auto_apply),
            "session_mirror_auto_apply_written_event_ids_count": int(
                session_mirror_auto_apply.get("written_event_ids_count") or 0
            ),
            "runtime_heartbeat_core_execution_gate_envelope_id": str(
                runtime_gate.get("execution_gate_envelope_id") or ""
            ),
        }
        complete_execution_gate_envelope(
            self.store,
            envelope_id=str(runtime_gate.get("execution_gate_envelope_id") or ""),
            lane_id="runtime_heartbeat_core",
            execution_status="ok",
            postcheck={
                "processed_event_count": len(processed_now),
                "working_created_count": working_created_count,
                "candidate_created_count": candidate_created_count,
                "boundary": {
                    "actual_send": False,
                    "actual_execute": False,
                    "actual_identity_write": False,
                    "actual_unapproved_crystallized_approval": False,
                },
            },
            result_summary={
                "processed_event_count": len(processed_now),
                "session_mirror_auto_apply_written_event_ids_count": int(
                    session_mirror_auto_apply.get("written_event_ids_count") or 0
                ),
            },
        )
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
            return {
                "schema_version": "memory-os.runtime_state.v0",
                "recent_processed_event_ids": [],
                "processed_event_count_total": 0,
            }
        state = json.loads(self._state_path.read_text(encoding="utf-8"))
        # Legacy migration: if old-format processed_event_ids exists but recent_ doesn't
        if "recent_processed_event_ids" not in state:
            legacy_ids = state.get("processed_event_ids", [])
            state["recent_processed_event_ids"] = (
                _dedupe_preserve_order(legacy_ids)[-RECENT_PROCESSED_EVENT_IDS_LIMIT:]
            )
            state["processed_event_count_total"] = state.get("processed_event_count", len(legacy_ids))
            state["processed_event_ids_compacted"] = True
        state.setdefault("recent_processed_event_ids_limit", RECENT_PROCESSED_EVENT_IDS_LIMIT)
        state.setdefault("processed_event_count_total", state.get("processed_event_count", 0))
        return state

    def _write_state(self, state: dict[str, Any]) -> None:
        write_json_atomic(self._state_path, state)

    def _write_attempt_state(self, current: datetime) -> None:
        state = self._read_state()
        state["last_attempt_at"] = current.isoformat()
        self._write_state(state)

    def _write_error_state(self, current: datetime, exc: Exception, error_record: dict[str, Any]) -> None:
        state = self._read_state()
        state["last_attempt_at"] = current.isoformat()
        state["last_error"] = {"type": type(exc).__name__, "message": str(exc)[:200]}
        state["last_error_record"] = error_record
        previous_count = int(state.get("suppressed_error_count") or 0)
        state["suppressed_error_count"] = previous_count + 1
        recent_codes = [
            str(code)
            for code in (
                state.get("recent_error_codes")
                if isinstance(state.get("recent_error_codes"), list)
                else []
            )
            if str(code)
        ]
        recent_codes.append(str(error_record.get("error_code") or "runtime_error"))
        state["recent_error_codes"] = recent_codes[-5:]
        self._write_state(state)

    def _record_heartbeat_error(self, current: datetime, exc: Exception) -> None:
        error_record = build_error_record(
            component="runtime",
            operation="heartbeat",
            error_code="runtime_heartbeat_error",
            severity="error",
            recoverable=True,
            path=self._state_path,
            details={"error_type": type(exc).__name__, "message": str(exc)[:200]},
        )
        details = {"error_type": type(exc).__name__, "message": str(exc)[:200], "error_record": error_record}
        try:
            self._write_error_state(current, exc, error_record)
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


def _bounded_session_mirror_auto_apply(report: dict[str, Any]) -> dict[str, Any]:
    policy = report.get("policy") if isinstance(report.get("policy"), dict) else {}
    auto_policy = report.get("auto_apply_policy") if isinstance(report.get("auto_apply_policy"), dict) else {}
    active_policy = auto_policy or policy
    return {
        "schema_version": str(report.get("schema_version") or ""),
        "status": str(report.get("status") or ""),
        "reason": str(report.get("reason") or ""),
        "written_event_ids_count": int(report.get("written_event_ids_count") or 0),
        "selected_session_count": int(report.get("selected_session_count") or 0),
        "raw_private_body_printed": bool(report.get("raw_private_body_printed")),
        "policy_status": str(active_policy.get("status") or ""),
        "approval_ref": str(active_policy.get("approval_ref") or ""),
        "approval_source": str(active_policy.get("approval_source") or ""),
        "owner_channel_bound": bool(active_policy.get("owner_channel_bound")),
        "stable_scope_id": str(active_policy.get("stable_scope_id") or ""),
        "max_sessions_per_run": int(active_policy.get("max_sessions_per_run") or 0),
        "platform_allowlist": [
            str(item)
            for item in (
                active_policy.get("platform_allowlist")
                if isinstance(active_policy.get("platform_allowlist"), list)
                else []
            )
        ][:10],
        "boundary": report.get("boundary") if isinstance(report.get("boundary"), dict) else {},
        "execution_gate_envelope_id": str(report.get("execution_gate_envelope_id") or ""),
    }


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
            "session_mirror_auto_apply_written_event_ids_count",
        )
    )
