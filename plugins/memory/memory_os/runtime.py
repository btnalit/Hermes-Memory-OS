"""Runtime heartbeat for deployed Memory-OS profiles."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .audit import append_audit
from .crystallized import append_candidate_queue, read_candidate_queue
from .index import MemoryOSIndex
from .inner_drive import InnerDriveEngine
from .store import MemoryOSStore
from .working import ALLOWED_WORKING_KINDS, WorkingMemoryService


class MemoryOSRuntime:
    """Advance canonical events into working memory and approval candidates."""

    def __init__(self, store: MemoryOSStore) -> None:
        self.store = store

    def heartbeat(self, *, max_events: int = 100) -> dict[str, Any]:
        if max_events <= 0:
            raise ValueError("max_events must be positive")
        self.store.initialize()
        state = self._read_state()
        processed_ids = set(state.get("processed_event_ids", []))
        events = sorted(self.store.read_events(), key=lambda event: event.ts)
        pending = [event for event in events if event.id not in processed_ids][:max_events]
        engine = InnerDriveEngine(self.store)
        processed_now: list[str] = []
        for event in pending:
            result = engine.process_event(event)
            append_candidate_queue(self.store, result.candidate)
            processed_ids.add(event.id)
            processed_now.append(event.id)

        working = WorkingMemoryService(self.store)
        decayed_documents: list[str] = []
        for kind in sorted(ALLOWED_WORKING_KINDS):
            before = working.read_document(kind)
            if before.get("items"):
                working.decay_items(kind)
                decayed_documents.append(kind)

        now = datetime.now(timezone.utc).isoformat()
        self._write_state(
            {
                "schema_version": "memory-os.runtime_state.v0",
                "last_heartbeat_at": now,
                "processed_event_ids": sorted(processed_ids),
            }
        )
        index_counts = MemoryOSIndex(self.store.roots).sync_from_store(self.store)
        report = {
            "schema_version": "memory-os.heartbeat.v0",
            "processed_event_count": len(processed_now),
            "processed_event_ids": processed_now,
            "already_processed_event_count": len(events) - len(pending),
            "total_event_count": len(events),
            "working_item_count": _working_item_count(self.store),
            "candidate_count": len(read_candidate_queue(self.store.roots)),
            "crystallized_record_count": _crystallized_record_count(self.store),
            "index_counts": index_counts,
            "decayed_documents": decayed_documents,
            "runtime_state_path": str(self._state_path),
        }
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
