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

from .state_overlay_schema import OVERLAY_SECTION_FIELDS

# ── Per-section labels (keep short — every char counts) ─────────────
#
# This dict must have an entry for *every* section in OVERLAY_SECTION_FIELDS
# (the single source of truth in state_overlay_schema.py). Labels are
# human-readable display strings and cannot be auto-generated, so this is a
# deliberate, explicit mapping — but it is validated exhaustively below so
# that adding a section to the StateOverlay dataclass and forgetting to add
# a label here fails loudly at import time instead of silently rendering
# that section as blank (this is exactly how `community_snapshot` silently
# dropped out of several consumers previously).
_SECTION_LABELS: dict[str, str] = {
    "identity_snapshot": "Identity",
    "relationship_snapshot": "Relationships",
    "active_projects": "Active",
    "open_threads": "Open threads",
    "recent_events": "Recent",
    "owner_preferences": "Preferences",
    "capability_map": "Capabilities",
    "material_index": "Materials",
}

# Sections rendered in the short (casual-chat) version. A deliberate subset
# of OVERLAY_SECTION_FIELDS — validated (not exhaustively covered, since it
# IS a subset) to at least reject typos/unknown section names below.
_SHORT_SECTIONS = {"active_projects", "open_threads", "owner_preferences"}

# Sections that are known-empty architectural placeholders (no data source
# wired yet, e.g. capability_map/material_index) or expected to often be
# empty by nature (identity/relationship crystallized memory). For these we
# skip the "_(insufficient data)_" marker line entirely rather than waste
# render budget on a marker for something with no near-term prospect of
# populating. Every other section is assumed to eventually carry data, so an
# empty one is worth surfacing to the reader as insufficient rather than
# silently omitted. Also a deliberate subset of OVERLAY_SECTION_FIELDS.
_PLACEHOLDER_SECTIONS = {
    "identity_snapshot", "relationship_snapshot",
    "capability_map", "material_index",
}


def _assert_labels_cover_all_sections(
    section_fields: tuple[str, ...] = OVERLAY_SECTION_FIELDS,
) -> None:
    """Raise loudly if any overlay section has no display label.

    Called at module import time against the real derived section list.
    Exposed with an overridable *section_fields* argument so tests can
    exercise the failure path directly (by passing an extended/synthetic
    tuple) without needing to mutate the StateOverlay dataclass itself.
    """
    missing = set(section_fields) - set(_SECTION_LABELS)
    if missing:
        raise RuntimeError(
            "state_overlay_renderer: no display label for overlay "
            f"section(s) {sorted(missing)} — add an entry to _SECTION_LABELS "
            "in plugins/memory/memory_os/state_overlay_renderer.py."
        )


def _assert_subset_known(name: str, subset: set[str]) -> None:
    """Raise loudly if a declared subset references an unknown section name."""
    unknown = subset - set(OVERLAY_SECTION_FIELDS)
    if unknown:
        raise RuntimeError(
            f"state_overlay_renderer: {name} references unknown overlay "
            f"section(s) {sorted(unknown)} — check for typos or a removed "
            "section in plugins/memory/memory_os/state_overlay_renderer.py."
        )


_assert_labels_cover_all_sections()
_assert_subset_known("_SHORT_SECTIONS", _SHORT_SECTIONS)
_assert_subset_known("_PLACEHOLDER_SECTIONS", _PLACEHOLDER_SECTIONS)


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
            if section_key in _PLACEHOLDER_SECTIONS:
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
