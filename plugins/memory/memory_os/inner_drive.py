"""Minimal inner-drive surface for Memory-OS integration validation."""

from __future__ import annotations

from dataclasses import dataclass

from .audit import append_audit
from .crystallized import CrystallizedCandidate
from .schema import EventEnvelope, WorkingItem
from .store import MemoryOSStore
from .working import WorkingMemoryService


@dataclass(frozen=True)
class InnerDriveProcessResult:
    working_item: WorkingItem
    candidate: CrystallizedCandidate


class InnerDriveEngine:
    """Process canonical events into working memory and crystallized candidates.

    This v0 surface is intentionally synchronous and small. Autonomous
    scheduling, exploration, and production Sannai personality behavior are
    outside Slice 16.
    """

    def __init__(self, store: MemoryOSStore) -> None:
        self.store = store
        self.working = WorkingMemoryService(store)

    def process_event(
        self,
        event: EventEnvelope,
        *,
        candidate_sensitivity: str = "private",
    ) -> InnerDriveProcessResult:
        working_item = self.working.add_item(
            "lingering",
            event.summary,
            source_event_id=event.id,
            tags=["inner-drive", event.kind],
            weight=0.6,
        )
        candidate = CrystallizedCandidate(
            candidate_id=f"cand_{event.id}",
            kind="moment",
            body=f"Remembered from event {event.id}: {event.summary}",
            source_event_ids=[event.id],
            sensitivity=candidate_sensitivity,
            tags=["inner-drive", event.kind],
            bridge_state="inner_drive_candidate",
        )
        append_audit(
            self.store.roots.audit_path,
            action="crystallized_candidate_generated",
            status="ok",
            target="inner-drive",
            details={
                "candidate_id": candidate.candidate_id,
                "source_event_ids": list(candidate.source_event_ids),
                "working_item_id": working_item.id,
            },
        )
        return InnerDriveProcessResult(working_item=working_item, candidate=candidate)
