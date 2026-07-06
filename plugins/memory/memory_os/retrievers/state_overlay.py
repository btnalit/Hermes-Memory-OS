"""State Overlay retriever — reads the overlay projection directly."""

from __future__ import annotations

import json
from typing import Any, TYPE_CHECKING

from plugins.memory.memory_os.recall_types import RecallObject, RecallType

if TYPE_CHECKING:
    from plugins.memory.memory_os.store import MemoryOSStore


class StateOverlayRetriever:
    """Retrieve the current memory state overlay.

    Reads ``system/state_overlay/current.json`` if it exists, falling
    back to building a fresh overlay from available sources via
    :func:`~plugins.memory.memory_os.state_overlay.build_state_overlay`.
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

        if overlay is None:
            overlay = build_state_overlay(
                store, roots,
                current_task_anchor=current_task_anchor,
                session_id=session_id,
            )

        objects: list[RecallObject] = []
        for section_key in (
            "active_projects", "open_threads", "recent_events",
            "owner_preferences", "identity_snapshot", "relationship_snapshot",
        ):
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
                        metadata={"section": section_key},
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
