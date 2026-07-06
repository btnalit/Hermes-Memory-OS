"""Memory State Overlay schema — file-first projection, never canonical.

The overlay is a derived projection of current memory state meant
for prefetch injection. It does NOT write to canonical paths
(crystallized/, events/, working/). Empty sections are marked
with ``status="insufficient_data"`` rather than fabricated.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any

STATE_OVERLAY_SCHEMA_VERSION = "memory-os.state_overlay.v1"


@dataclass
class OverlayEntry:
    """A single entry in an overlay section."""

    text: str
    source: str = ""       # e.g. "crystallized:pref-001"
    source_kind: str = ""  # e.g. "crystallized", "last_session", "task_anchor"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OverlaySection:
    """One section of the state overlay."""

    data: list[OverlayEntry] = field(default_factory=list)
    source: str = ""
    status: str = ""  # "ok" | "insufficient_data" | "to_be_populated" | "error"

    def to_dict(self) -> dict[str, Any]:
        return {
            "data": [e.to_dict() for e in self.data],
            "source": self.source,
            "status": self.status or ("ok" if self.data else "insufficient_data"),
        }


@dataclass
class StateOverlay:
    """Full state overlay projection.

    Sections are grouped by data source and intentionally kept small
    (sannai's 10 files total ~10 KB).  Sections without available data
    are kept in the schema but marked ``insufficient_data`` — they serve
    as placeholders for future crystallized memory accumulation.
    """

    schema_version: str = STATE_OVERLAY_SCHEMA_VERSION
    generated_at: str = ""
    profile: str = ""

    identity_snapshot: OverlaySection = field(default_factory=lambda: OverlaySection(
        source="crystallized (kind=identity)",
    ))
    relationship_snapshot: OverlaySection = field(default_factory=lambda: OverlaySection(
        source="crystallized (kind=relationship)",
    ))
    active_projects: OverlaySection = field(default_factory=lambda: OverlaySection(
        source="active_task_anchor.jsonl (status=active)",
    ))
    open_threads: OverlaySection = field(default_factory=lambda: OverlaySection(
        source="last_session_anchor.jsonl (recent, cross-session)",
    ))
    recent_events: OverlaySection = field(default_factory=lambda: OverlaySection(
        source="last_session_anchor.jsonl + events/*.jsonl (72h window)",
    ))
    owner_preferences: OverlaySection = field(default_factory=lambda: OverlaySection(
        source="crystallized (kind=preference)",
    ))
    capability_map: OverlaySection = field(default_factory=lambda: OverlaySection(
        source="TBD",
    ))
    material_index: OverlaySection = field(default_factory=lambda: OverlaySection(
        source="TBD",
    ))
    risk_notes: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)

    @classmethod
    def create(cls, *, profile: str = "") -> "StateOverlay":
        return cls(
            generated_at=datetime.now(timezone.utc).isoformat(),
            profile=profile,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "profile": self.profile,
            "identity_snapshot": self.identity_snapshot.to_dict(),
            "relationship_snapshot": self.relationship_snapshot.to_dict(),
            "active_projects": self.active_projects.to_dict(),
            "open_threads": self.open_threads.to_dict(),
            "recent_events": self.recent_events.to_dict(),
            "owner_preferences": self.owner_preferences.to_dict(),
            "capability_map": self.capability_map.to_dict(),
            "material_index": self.material_index.to_dict(),
            "risk_notes": list(self.risk_notes),
            "evidence_refs": list(self.evidence_refs),
        }
