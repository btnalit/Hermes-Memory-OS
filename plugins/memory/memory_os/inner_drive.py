"""Minimal inner-drive surface for Memory-OS integration validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .audit import append_audit
from .crystallized import CrystallizedCandidate
from .schema import EventEnvelope, WorkingItem
from .store import MemoryOSStore
from .working import WorkingMemoryService


DEFAULT_SOURCE_CLASS_CAP = 20
SELF_ACTIVITY_MAX_FRACTION = 0.15  # V2d: self_activity events ≤15% of selected batch


@dataclass(frozen=True)
class InnerDriveEventDecision:
    source_class: str
    drive_policy: str
    working_kind: str = ""
    working_weight: float = 0.0
    candidate_allowed: bool = False
    skip_reason: str = ""


@dataclass(frozen=True)
class InnerDriveProcessResult:
    working_item: WorkingItem | None
    candidate: CrystallizedCandidate | None
    decision: InnerDriveEventDecision


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
        decision = classify_event_for_inner_drive(event)
        working_item = None
        candidate = None
        if decision.working_kind:
            working_item = self.working.add_item(
                decision.working_kind,
                event.summary,
                source_event_id=event.id,
                tags=["inner-drive", event.kind, decision.source_class, decision.drive_policy],
                weight=decision.working_weight,
            )
        if decision.candidate_allowed:
            candidate = CrystallizedCandidate(
                candidate_id=f"cand_{event.id}",
                kind="moment",
                body=f"Remembered from event {event.id}: {event.summary}",
                source_event_ids=[event.id],
                sensitivity=candidate_sensitivity,
                tags=["inner-drive", event.kind, decision.source_class],
                bridge_state="inner_drive_candidate",
            )
        append_audit(
            self.store.roots.audit_path,
            action="crystallized_candidate_generated" if candidate else "inner_drive_event_processed",
            status="ok",
            target="inner-drive",
            details={
                "event_id": event.id,
                "source_class": decision.source_class,
                "drive_policy": decision.drive_policy,
                "candidate_id": candidate.candidate_id if candidate else "",
                "working_item_id": working_item.id if working_item else "",
                "skip_reason": decision.skip_reason,
            },
        )
        return InnerDriveProcessResult(working_item=working_item, candidate=candidate, decision=decision)


def classify_event_for_inner_drive(event: EventEnvelope) -> InnerDriveEventDecision:
    safe_ref = dict(event.safe_ref or {})
    kind = event.kind
    source_class = _source_class(event)
    explicit_policy = str(safe_ref.get("drive_policy") or "").strip()
    candidate_explicit = safe_ref.get("candidate_allowed")

    if kind == "conversation_turn":
        return InnerDriveEventDecision(
            source_class=source_class,
            drive_policy=explicit_policy or "eligible",
            working_kind="lingering",
            working_weight=0.6,
            candidate_allowed=_candidate_allowed(candidate_explicit, default=True),
        )
    if kind == "memory_write":
        return InnerDriveEventDecision(
            source_class=source_class,
            drive_policy=explicit_policy or "eligible",
            working_kind="lingering",
            working_weight=0.45,
            candidate_allowed=_candidate_allowed(candidate_explicit, default=True),
        )
    if kind == "conversation_turn_mirrored" and safe_ref.get("body_policy") == "bounded_summary":
        return InnerDriveEventDecision(
            source_class=source_class,
            drive_policy=explicit_policy or "eligible",
            working_kind="lingering",
            working_weight=0.3,
            candidate_allowed=_candidate_allowed(candidate_explicit, default=False),
        )
    if kind == "journal_card_observed":
        return InnerDriveEventDecision(
            source_class=source_class,
            drive_policy=explicit_policy or "low_weight",
            working_kind="attention",
            working_weight=0.25,
            candidate_allowed=_candidate_allowed(candidate_explicit, default=False),
        )
    if explicit_policy == "low_weight":
        return InnerDriveEventDecision(
            source_class=source_class,
            drive_policy="low_weight",
            working_kind="attention",
            working_weight=0.2,
            candidate_allowed=_candidate_allowed(candidate_explicit, default=False),
        )
    if kind in {"cron_job_run", "session_observed"} or explicit_policy in {"index_only", "evidence_only", "candidate_surface", "ignore"}:
        return InnerDriveEventDecision(
            source_class=source_class,
            drive_policy=explicit_policy or "index_only",
            candidate_allowed=False,
            skip_reason=explicit_policy or "index_only",
        )
    if kind in {"runtime_heartbeat", "module_audit", "index_event"}:
        return InnerDriveEventDecision(source_class=source_class, drive_policy="ignore", skip_reason="runtime_event")
    return InnerDriveEventDecision(source_class=source_class, drive_policy="index_only", skip_reason="unknown_event_kind")


def select_events_for_inner_drive(
    events: list[EventEnvelope],
    processed_ids: set[str],
    *,
    max_events: int,
    max_events_per_source_class: int | dict[str, int] = DEFAULT_SOURCE_CLASS_CAP,
) -> tuple[list[EventEnvelope], list[EventEnvelope]]:
    selected: list[EventEnvelope] = []
    deferred: list[EventEnvelope] = []
    source_counts: dict[str, int] = {}
    for event in events:
        if event.id in processed_ids:
            continue
        source_class = classify_event_for_inner_drive(event).source_class
        cap = _source_cap(max_events_per_source_class, source_class)
        if source_counts.get(source_class, 0) >= cap:
            deferred.append(event)
            continue
        # V2d: self_activity fraction gate — prevent self_activity from
        # drowning out external events. Once self_activity exceeds
        # SELF_ACTIVITY_MAX_FRACTION of the selected batch, defer remaining
        # self_activity events (oldest-first, since events are sorted by ts).
        if source_class == "self_activity" and len(selected) > 0:
            sa_count = source_counts.get("self_activity", 0)
            sa_max = max(1, int(len(selected) * SELF_ACTIVITY_MAX_FRACTION))
            if sa_count >= sa_max:
                deferred.append(event)
                continue
        selected.append(event)
        source_counts[source_class] = source_counts.get(source_class, 0) + 1
        if len(selected) >= max_events:
            break
    return selected, deferred


def _source_cap(value: int | dict[str, int], source_class: str) -> int:
    if isinstance(value, dict):
        return int(value.get(source_class, value.get("*", DEFAULT_SOURCE_CLASS_CAP)))
    return int(value)


def _candidate_allowed(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    return default


def _source_class(event: EventEnvelope) -> str:
    safe_ref = dict(event.safe_ref or {})
    source = event.source.lower()
    kind = event.kind.lower()
    tags = {str(tag).lower() for tag in event.tags}
    source_module = str(safe_ref.get("source_module", "")).lower()
    source_class = str(safe_ref.get("source_class", "")).lower()
    platform = str(safe_ref.get("platform", "")).lower()
    if source_class == "self_activity":
        return "self_activity"          # V2.2: recognize self_activity before source_module checks
    if source_module == "cron_mirror" or source == "cron" or "cron" in tags or platform == "cron":
        return "cron"
    if source_module == "state_source_mirror" or source_class.startswith("state:") or source == "state_source_mirror":
        return "state_source"
    if source_module == "session_mirror" or source == "session_mirror":
        return "session"
    if platform == "mailbox" or source == "mailbox" or "mailbox" in tags:
        return "mailbox"
    if platform in {"room", "family", "household"} or source in {"room", "family", "household"}:
        return "room_family"
    if source_module in {"ops_gate", "proposal_queue", "evidence_scoring", "self_evolution"}:
        return "governance"
    if any(marker in kind for marker in ("proposal", "governance", "evidence", "ops_gate", "self_evolution")):
        return "governance"
    if kind in {"conversation_turn", "memory_write", "conversation_turn_mirrored"}:
        return "foreground"
    return "other"
