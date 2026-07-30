"""Memory State Overlay schema — file-first projection, never canonical.

The overlay is a derived projection of current memory state meant
for prefetch injection. It does NOT write to canonical paths
(crystallized/, events/, working/). Empty sections are marked
with ``status="insufficient_data"`` rather than fabricated.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict, fields
from datetime import datetime, timezone
from typing import Any, get_type_hints

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
        source="not_wired: provider interface defined but no data source connected — known architectural placeholder, not a runtime failure",
    ))
    material_index: OverlaySection = field(default_factory=lambda: OverlaySection(
        source="not_wired: provider interface defined but no data source connected — known architectural placeholder, not a runtime failure",
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
        result: dict[str, Any] = {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "profile": self.profile,
        }
        for name in OVERLAY_SECTION_FIELDS:
            result[name] = getattr(self, name).to_dict()
        result["risk_notes"] = list(self.risk_notes)
        result["evidence_refs"] = list(self.evidence_refs)
        return result


def _compute_overlay_section_fields() -> tuple[str, ...]:
    """Derive the ordered list of ``StateOverlay`` fields typed ``OverlaySection``.

    This is the single source of truth for "what overlay sections exist".
    Every other site that needs to enumerate sections — the renderer's
    labels/short-list, prefetch's has-data check, the refresh script's
    section counter, and the retriever's section tuple — must derive from
    this constant instead of hand-maintaining its own copy.

    That hand-maintenance is exactly what caused a real drift bug: when
    ``community_snapshot`` was removed from this dataclass, several other
    hardcoded copies elsewhere in the codebase were never updated, and the
    section silently vanished from those consumers for its entire lifetime
    without anyone noticing.

    Order matches declaration order in :class:`StateOverlay`, which matches
    the historical explicit key order used by ``to_dict()``.
    """
    hints = get_type_hints(StateOverlay)
    return tuple(
        f.name for f in fields(StateOverlay)
        if hints.get(f.name) is OverlaySection
    )


OVERLAY_SECTION_FIELDS: tuple[str, ...] = _compute_overlay_section_fields()
