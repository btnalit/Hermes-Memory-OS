"""
Continuity freshness and stale degradation for Memory-OS.

Defines structured freshness policy for current task, open threads,
recent decisions, and capability maps.  Each continuity object carries
a freshness timestamp and a stale_after duration; when the age exceeds
stale_after, the object is considered stale and should not be surfaced
as current context.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

CONTINUITY_SCHEMA_VERSION = "memory-os.continuity.v1"


class FreshnessGrade(str):
    """Freshness grades for continuity objects."""

    FRESH = "fresh"
    AGING = "aging"
    STALE = "stale"
    UNKNOWN = "unknown"


DEFAULT_STALE_AFTER: dict[str, int] = {
    "current_task": 3600,       # 1 hour
    "open_thread": 7200,        # 2 hours
    "recent_decision": 43200,   # 12 hours
    "capability_map": 86400,    # 24 hours
}


def default_stale_after(kind: str) -> int:
    return DEFAULT_STALE_AFTER.get(kind, 3600)


@dataclass
class ContinuityObject:
    """A continuity object with freshness tracking."""

    kind: str
    object_id: str
    summary: str = ""
    created_at: str = ""
    updated_at: str = ""
    stale_after_seconds: int = 3600
    revision: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def age_seconds(self, now: datetime | None = None) -> float | None:
        ref = now or datetime.now(timezone.utc)
        if not self.updated_at:
            return None
        try:
            from .timeutil import parse_utc
            updated = parse_utc(self.updated_at)
            if updated is None:
                return None
            return (ref - updated).total_seconds()
        except (ValueError, TypeError):
            return None

    def freshness_grade(self, now: datetime | None = None) -> str:
        age = self.age_seconds(now)
        if age is None:
            return FreshnessGrade.UNKNOWN
        if age < 0:
            return FreshnessGrade.FRESH
        if age < self.stale_after_seconds * 0.75:
            return FreshnessGrade.FRESH
        if age < self.stale_after_seconds:
            return FreshnessGrade.AGING
        return FreshnessGrade.STALE

    def is_stale(self, now: datetime | None = None) -> bool:
        return self.freshness_grade(now) == FreshnessGrade.STALE

    def is_fresh(self, now: datetime | None = None) -> bool:
        return self.freshness_grade(now) == FreshnessGrade.FRESH

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CONTINUITY_SCHEMA_VERSION,
            "kind": self.kind,
            "object_id": self.object_id,
            "summary": self.summary[:80],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "stale_after_seconds": self.stale_after_seconds,
            "revision": self.revision,
            "freshness_grade": self.freshness_grade(),
            "is_stale": self.is_stale(),
        }


@dataclass
class ContinuityState:
    """Aggregate continuity state for a session."""

    current_task: ContinuityObject | None = None
    open_threads: list[ContinuityObject] = field(default_factory=list)
    recent_decisions: list[ContinuityObject] = field(default_factory=list)
    capability_map: ContinuityObject | None = None

    def active_open_threads(self, now: datetime | None = None) -> list[ContinuityObject]:
        """Return open threads that are not stale."""
        return [t for t in self.open_threads if not t.is_stale(now)]

    def stale_open_threads(self, now: datetime | None = None) -> list[ContinuityObject]:
        return [t for t in self.open_threads if t.is_stale(now)]

    def current_task_is_stale(self, now: datetime | None = None) -> bool:
        if self.current_task is None:
            return True
        return self.current_task.is_stale(now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CONTINUITY_SCHEMA_VERSION,
            "current_task": self.current_task.to_dict() if self.current_task else None,
            "active_open_threads": len(self.active_open_threads()),
            "stale_open_threads": len(self.stale_open_threads()),
            "recent_decisions": len(self.recent_decisions),
            "has_capability_map": self.capability_map is not None,
        }