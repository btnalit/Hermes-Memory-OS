"""State Overlay retriever — reads the overlay projection directly."""

from __future__ import annotations

import json
from typing import Any, TYPE_CHECKING

from plugins.memory.memory_os.recall_types import RecallObject, RecallType
from plugins.memory.memory_os.state_overlay_schema import OVERLAY_SECTION_FIELDS

if TYPE_CHECKING:
    from plugins.memory.memory_os.store import MemoryOSStore


# Sections this retriever surfaces, in priority order (most useful first;
# preserves the historical iteration order so tie-break behavior between
# equal-score entries is unchanged). Deliberately excludes capability_map
# and material_index: state_overlay_schema marks both "not_wired" — no data
# source is connected, so their status is never "ok" and surfacing them
# here would only ever be a no-op.
#
# This subset must be declared explicitly and exhaustively against
# OVERLAY_SECTION_FIELDS (the single source of truth in
# state_overlay_schema.py) — validated below so that a newly added
# StateOverlay section either lands in _RETRIEVABLE_SECTIONS or
# _NOT_RETRIEVABLE_SECTIONS explicitly, and can never silently drop out of
# recall the way `community_snapshot` previously did.
_RETRIEVABLE_SECTIONS: tuple[str, ...] = (
    "active_projects", "open_threads", "recent_events",
    "owner_preferences", "identity_snapshot", "relationship_snapshot",
)
_NOT_RETRIEVABLE_SECTIONS: frozenset[str] = frozenset({
    "capability_map", "material_index",
})


def _assert_sections_classified(
    section_fields: tuple[str, ...] = OVERLAY_SECTION_FIELDS,
) -> None:
    """Raise loudly if any overlay section is neither retrievable nor
    explicitly marked not-retrievable.

    Called at module import time against the real derived section list.
    Exposed with an overridable *section_fields* argument so tests can
    exercise the failure path directly (via an extended/synthetic tuple)
    without needing to mutate the StateOverlay dataclass itself.
    """
    unclassified = (
        set(section_fields) - set(_RETRIEVABLE_SECTIONS) - _NOT_RETRIEVABLE_SECTIONS
    )
    if unclassified:
        raise RuntimeError(
            "StateOverlayRetriever: overlay section(s) "
            f"{sorted(unclassified)} are not classified as retrievable or "
            "not-retrievable — add each new StateOverlay section to "
            "_RETRIEVABLE_SECTIONS or _NOT_RETRIEVABLE_SECTIONS in "
            "plugins/memory/memory_os/retrievers/state_overlay.py."
        )


_assert_sections_classified()


class StateOverlayRetriever:
    """Retrieve the current memory state overlay.

    Reads ``system/state_overlay/current.json`` if it exists (no freshness
    check — the cache is the cron lane's 30-minute projection), falling
    back to building a fresh overlay only when the cache is missing or
    unparseable.  W7 (S3): a live ``current_task_anchor`` in *scope*
    overrides the cached active_projects section — same helper and same
    semantics as prefetch's fast path, so the two cannot drift.
    """

    @property
    def recall_type(self) -> RecallType:
        return RecallType.STATE_OVERLAY

    def retrieve(
        self,
        store: "MemoryOSStore",
        query: str,
        *,
        top_k: int = 10,
        scope: dict[str, Any] | None = None,
    ) -> list[RecallObject]:
        from plugins.memory.memory_os.state_overlay import build_state_overlay

        roots = store.roots
        current_task_anchor = str((scope or {}).get("current_task_anchor", ""))
        session_id = str((scope or {}).get("session_id", ""))

        # Try cached overlay first
        cached_path = roots.memory_os_root / "system" / "state_overlay" / "current.json"
        overlay: dict[str, Any] | None = None
        if cached_path.exists():
            try:
                overlay = json.loads(cached_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        if overlay is not None and current_task_anchor.strip():
            from plugins.memory.memory_os.state_overlay import (
                override_active_projects_with_live_anchor,
            )

            try:
                override_active_projects_with_live_anchor(overlay, current_task_anchor)
            except Exception:
                pass  # fail-open — cache path must keep working

        if overlay is None:
            overlay = build_state_overlay(
                store, roots,
                current_task_anchor=current_task_anchor,
                session_id=session_id,
            )

        objects: list[RecallObject] = []
        overlay_task_revision = str(overlay.get("task_revision") or "")
        for section_key in _RETRIEVABLE_SECTIONS:
            section = overlay.get(section_key)
            if not isinstance(section, dict):
                continue
            if section.get("status") != "ok":
                continue
            for entry in section.get("data", []):
                if not isinstance(entry, dict):
                    continue
                text = str(entry.get("text", "")).strip()
                if text:
                    objects.append(RecallObject(
                        recall_type=RecallType.STATE_OVERLAY.value,
                        content=text,
                        score=0.8,
                        source_ref=str(entry.get("source", "")),
                        metadata={"section": section_key, "task_revision": overlay_task_revision},
                        authority_class="state_projection",
                        task_revision=overlay_task_revision,
                    ))

        # Simple relevance: query term overlap
        q_lower = query.lower()
        for obj in objects:
            if q_lower and any(word in obj.content.lower() for word in q_lower.split()):
                obj.score = min(1.0, obj.score + 0.15)

        objects.sort(key=lambda o: o.score, reverse=True)
        return objects[:top_k]

    def format_context(
        self,
        objects: list[RecallObject],
        *,
        budget: int = 800,
    ) -> str:
        if not objects:
            return ""
        lines = ["### Memory State Overlay (recall)"]
        for obj in objects:
            line = f"- {obj.content}"
            if obj.source_ref:
                line += f" [src: {obj.source_ref}]"
            lines.append(line)
        return "\n".join(lines)
