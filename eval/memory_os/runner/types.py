"""Shared types for the RH-31 report-only eval harness."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Rh31Case:
    case_id: str
    query: str
    expected_class: str
    expected_terms: tuple[str, ...] = ()
    expected_heading: str = ""
    family: str = "general"
    weight: float = 1.0


@dataclass(frozen=True)
class Rh31Document:
    doc_id: str
    text: str
    source_class: str
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class Rh31Score:
    adapter: str
    case_id: str
    status: str
    metric_scope: str
    expected_class: str
    actual_route: str = ""
    actual_headings: tuple[str, ...] = ()
    failure_class: str | None = None
    boundary_true: bool = False
    forbidden_field_count: int = 0
    live_behavior_changed: bool = False
    notes: tuple[str, ...] = ()
    source_classes: tuple[str, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter": self.adapter,
            "case_id": self.case_id,
            "status": self.status,
            "metric_scope": self.metric_scope,
            "expected_class": self.expected_class,
            "actual_route": self.actual_route,
            "actual_headings": list(self.actual_headings),
            "failure_class": self.failure_class,
            "boundary_true": self.boundary_true,
            "forbidden_field_count": self.forbidden_field_count,
            "live_behavior_changed": self.live_behavior_changed,
            "notes": list(self.notes),
            "source_classes": list(self.source_classes),
            "details": dict(self.details),
        }
