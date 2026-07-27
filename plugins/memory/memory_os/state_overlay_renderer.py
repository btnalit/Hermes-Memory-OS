"""Memory State Overlay markdown renderer.

Renders an overlay JSON dict into bounded markdown suitable for
injection into the prefetch context.  Two modes:

* ``render_state_overlay_md`` — full version (≤ 1800 chars)
* ``render_state_overlay_md_short`` — short version (≤ 600 chars) for casual chat

Every rendered line carries a ``[src: …]`` traceability marker.
Empty sections are either skipped or annotated ``_(insufficient data)_``.
"""

from __future__ import annotations

from typing import Any

# ── Per-section labels (keep short — every char counts) ─────────────
_SECTION_LABELS: dict[str, str] = {
    "identity_snapshot": "Identity",
    "relationship_snapshot": "Relationships",
    "active_projects": "Active",
    "open_threads": "Open threads",
    "recent_events": "Recent",
    "owner_preferences": "Preferences",
    "community_snapshot": "Community",
    "capability_map": "Capabilities",
    "material_index": "Materials",
}

# Sections rendered in the short (casual-chat) version.
_SHORT_SECTIONS = {"active_projects", "open_threads", "owner_preferences", "community_snapshot"}


def render_state_overlay_md(
    overlay: dict[str, Any],
    *,
    max_chars: int = 1800,
) -> str:
    """Render the state overlay as bounded markdown.

    Sections with data are rendered as bullet lists with source refs.
    Empty sections are annotated ``_(insufficient data)_`` if they are
    expected to have data; ``to_be_populated`` sections are skipped.

    Total output ≤ *max_chars*.  If truncation is needed the last line
    is replaced with ``..._(truncated)_``.
    """
    return _render(overlay, max_chars=max_chars, short=False)


def render_state_overlay_md_short(
    overlay: dict[str, Any],
    *,
    max_chars: int = 600,
) -> str:
    """Short overlay for casual-chat contexts.

    Only renders active_projects, open_threads, and owner_preferences.
    Total output ≤ *max_chars*.
    """
    return _render(overlay, max_chars=max_chars, short=True)


# ── Internal ────────────────────────────────────────────────────────


def _render(overlay: dict[str, Any], *, max_chars: int, short: bool) -> str:
    lines: list[str] = []
    header = "### Memory State Overlay"
    lines.append(header)
    char_budget = max_chars - len(header) - 2  # reserve for trailing newlines

    for section_key, label in _SECTION_LABELS.items():
        if short and section_key not in _SHORT_SECTIONS:
            continue
        section = overlay.get(section_key)
        if not isinstance(section, dict):
            continue
        data = section.get("data")
        status = str(section.get("status") or "")
        source = str(section.get("source") or "")

        if isinstance(data, list) and data:
            for entry in data:
                if not isinstance(entry, dict):
                    continue
                text = str(entry.get("text", "")).strip()
                src = str(entry.get("source", source))
                if text:
                    line = f"- [{label}] {text} [src: {src}]"
                    lines.append(line)
        elif status in ("insufficient_data",):
            # Only show insufficient_data for sections that should have data
            if section_key in ("identity_snapshot", "relationship_snapshot",
                               "capability_map", "material_index"):
                continue  # skip placeholders — don't waste budget
            lines.append(f"- [{label}] _(insufficient data)_")
        # to_be_populated sections are silently skipped

    result = "\n".join(lines)
    if len(result) <= max_chars:
        return result

    # Truncate: drop lines from the end until we fit, add truncation marker
    truncated_lines = lines[:]
    while len("\n".join(truncated_lines)) > max_chars - 20 and len(truncated_lines) > 2:
        truncated_lines.pop()
    truncated_lines.append("..._(truncated)_")
    return "\n".join(truncated_lines)
