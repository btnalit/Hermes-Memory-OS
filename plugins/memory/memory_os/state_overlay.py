"""Memory State Overlay builder — reads canonical sources, writes projection only.

All outputs go to ``$HERMES_HOME/memory-os/system/state_overlay/``.
Never writes to crystallized/, events/, or working/ — the overlay is a
derived projection, not a source of truth.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TYPE_CHECKING

from .state_overlay_schema import (
    StateOverlay,
    OverlayEntry,
    STATE_OVERLAY_SCHEMA_VERSION,
)
from .store import MemoryOSStore

if TYPE_CHECKING:
    from .roots import MemoryOSRoots


_NOISE_LINE_MARKERS = (
    "CONTEXT COMPACTION",
    "CONTEXT COMPACT",
    "COMPACTION SUMMARY BELOW",
    "PRIOR CONTEXT",
    "END OF PRIOR CONTEXT",
    "System note:",
    "recalled memory context, NOT new user input",
    "Earlier turns were compacted",
    "Earlier turns were compacted into",
    "The user sent a text document:",
    "Its content has been included below",
    "The file is also saved at:",
    "file is also saved at:",
    "<memory-context>",
    "</memory-context>",
)

_INLINE_NOISE_BLOCK_RE = re.compile(
    r"\[(?:PRIOR CONTEXT|END OF PRIOR CONTEXT|CONTEXT COMPACTION|CONTEXT COMPACT)[^\]]*\]",
    re.IGNORECASE,
)

_COMPACTION_RESIDUE_RE = re.compile(
    r"(?:Earlier turns were compacted[^\n]*|Earli\.\.\.[^\n]*)",
    re.IGNORECASE,
)


def build_state_overlay(
    store: MemoryOSStore,
    roots: "MemoryOSRoots",
    *,
    current_task_anchor: str = "",
    session_id: str = "",
    max_recent_sessions: int = 3,
    max_recent_events: int = 5,
) -> dict[str, Any]:
    """Build a state overlay dict from available memory sources.

    Only fills sections where data exists. Empty/unknown sections are
    marked with ``status="insufficient_data"`` or ``"to_be_populated"``.

    When *session_id* is provided, last-session anchors belonging to
    the current session are excluded to avoid duplicating foreground
    task context already present in other prefetch sections.

    Never writes to canonical paths — this is a read-and-return builder.
    """
    overlay = StateOverlay.create(profile=roots.profile)

    # ── active_projects: from current task anchor ──────────────────
    task_text = _clean_overlay_text(current_task_anchor)
    if task_text:
        # Extract the first meaningful line (skip markdown headers)
        lines = task_text.split("\n")
        first_line = ""
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                first_line = stripped
                break
        if not first_line:
            first_line = lines[0].strip().lstrip("#").strip()
        if first_line:
            overlay.active_projects.data.append(
                OverlayEntry(
                    text=first_line[:200],
                    source="task_anchor:current",
                    source_kind="task_anchor",
                )
            )
            overlay.active_projects.status = "ok"

    # ── open_threads + recent_events: from last session anchors ────
    lsa_path = roots.memory_os_root / "system" / "last_session_anchor.jsonl"
    last_sessions = _read_last_session_anchors(
        lsa_path, limit=max_recent_sessions, exclude_session_id=session_id,
    )

    for i, session in enumerate(last_sessions):
        foreground = _clean_overlay_text(session.get("foreground_summary", ""))
        session_id = str(session.get("session_id", ""))[:12]
        if foreground:
            if i == 0:
                # Latest session → recent event (most recent context)
                overlay.recent_events.data.append(
                    OverlayEntry(
                        text=foreground[:200],
                        source=f"last_session:{session_id}",
                        source_kind="last_session",
                    )
                )
            # All recent sessions → open threads
            overlay.open_threads.data.append(
                OverlayEntry(
                    text=foreground[:200],
                    source=f"last_session:{session_id}",
                    source_kind="last_session",
                )
            )

    if overlay.open_threads.data:
        overlay.open_threads.status = "ok"

    # ── recent_events: also from event_stats summaries ─────────────
    event_stats_path = roots.memory_os_root / "system" / "event_stats.json"
    if event_stats_path.exists():
        try:
            es = json.loads(event_stats_path.read_text(encoding="utf-8"))
            summaries = es.get("recent_event_summaries", [])
            if isinstance(summaries, list):
                added = 0
                for s in summaries:
                    if not isinstance(s, dict):
                        continue
                    summary = _clean_overlay_text(s.get("summary", ""))
                    if summary and added < max_recent_events:
                        overlay.recent_events.data.append(
                            OverlayEntry(
                                text=summary[:200],
                                source=f"event_stats:{s.get('kind', 'event')}",
                                source_kind="event",
                            )
                        )
                        added += 1
        except (json.JSONDecodeError, OSError):
            pass  # fail-open

    if overlay.recent_events.data:
        overlay.recent_events.status = "ok"
    else:
        overlay.recent_events.status = "insufficient_data"

    # ── owner_preferences: from crystallized kind=preference ───────
    pref_entries = _read_preference_crystallized(roots.crystallized_root)
    for text, ref_id in pref_entries:
        text = _clean_overlay_text(text)
        if not text:
            continue
        overlay.owner_preferences.data.append(
            OverlayEntry(
                text=text[:200],
                source=f"crystallized:{ref_id}",
                source_kind="crystallized",
            )
        )
    if overlay.owner_preferences.data:
        overlay.owner_preferences.status = "ok"

    return overlay.to_dict()


def write_state_overlay(roots: "MemoryOSRoots", overlay: dict[str, Any]) -> Path:
    """Write ``current.json`` to the state overlay directory.

    Returns the written path.  The directory is created if missing.
    This is a projection write — it does NOT touch canonical paths.
    """
    out_dir = roots.memory_os_root / "system" / "state_overlay"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "current.json"
    _atomic_write_json(out_path, overlay)
    return out_path


def append_overlay_run(roots: "MemoryOSRoots", run: dict[str, Any]) -> Path:
    """Append one run record to ``runs.jsonl``.

    Returns the path.  Fail-open: OS/IO errors are caught and logged,
    never raised to the caller.
    """
    out_dir = roots.memory_os_root / "system" / "state_overlay"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "runs.jsonl"
    record = {
        "schema_version": "memory-os.state_overlay_run.v0",
        "ts": datetime.now(timezone.utc).isoformat(),
        **run,
    }
    try:
        with out_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError:
        pass  # fail-open — run record loss must not break the system
    return out_path


# ── Internal helpers ─────────────────────────────────────────────────


def _clean_overlay_text(value: Any, *, max_chars: int = 500) -> str:
    """Return dialogue-facing overlay text with infrastructure boilerplate removed.

    State Overlay is fed by session anchors, compaction summaries, uploaded
    document notices, and event summaries.  Those sources often contain system
    scaffolding that is useful for storage/debugging but harmful when mirrored
    into model context.  This cleaner is intentionally deterministic and
    conservative: it removes known Hermes boilerplate lines/blocks, preserves
    ordinary user/task content, and returns an empty string when nothing useful
    remains.
    """
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = _INLINE_NOISE_BLOCK_RE.sub("", text)
    text = _COMPACTION_RESIDUE_RE.sub("", text)
    cleaned_lines: list[str] = []
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        if any(marker in line for marker in _NOISE_LINE_MARKERS):
            continue
        if line.startswith("[") and line.endswith("]") and "document" in line.lower():
            continue
        cleaned_lines.append(line)
    cleaned = " ".join(cleaned_lines)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:max_chars]


def _read_last_session_anchors(
    path: Path, *, limit: int = 3, exclude_session_id: str = "",
    max_lines: int = 500,
) -> list[dict[str, Any]]:
    """Read the most recent session anchors from the JSONL file.

    Returns up to *limit* anchors sorted by ``ended_at`` descending.
    When *exclude_session_id* is non-empty, anchors belonging to that
    session are skipped to avoid duplicating foreground task context.

    *max_lines* caps the number of lines read from the file to avoid
    unbounded I/O on long-running deployments.  Since the file is
    append-only, the most recent entries (which we care about) are at
    the end; 500 lines covers months of normal session cadence.

    Fail-open: missing file, parse errors → empty list.
    """
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    all_lines = path.read_text(encoding="utf-8").splitlines()
    # Only process the tail — the file is append-only so recent
    # sessions (which we sort for) are at the end.
    for line in all_lines[-max_lines:]:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        if not record.get("foreground_summary"):
            continue
        if exclude_session_id and str(record.get("session_id", "")) == exclude_session_id:
            continue
        records.append(record)
    # Sort by ended_at descending and take the most recent
    def _sort_key(r: dict[str, Any]) -> str:
        return str(r.get("ended_at", ""))
    records.sort(key=_sort_key, reverse=True)
    return records[:limit]


def _read_preference_crystallized(
    crystallized_root: Path,
) -> list[tuple[str, str]]:
    """Extract preference-type entries from crystallized markdown files.

    Returns list of (text, ref_id) tuples.  Looks for frontmatter
    ``kind: preference`` in ``*.md`` files.

    Fail-open: missing directory, parse errors → empty list.
    """
    if not crystallized_root.exists():
        return []
    entries: list[tuple[str, str]] = []
    for md_path in sorted(crystallized_root.glob("*.md")):
        try:
            text = md_path.read_text(encoding="utf-8")
        except OSError:
            continue
        # Only check frontmatter for kind: preference — body substring
        # match would produce false positives from citations or code blocks.
        frontmatter_text = ""
        body = ""
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                frontmatter_text = parts[1]
                body = parts[2].strip()
            else:
                body = text.strip()
        else:
            body = text.strip()

        if "kind: preference" not in frontmatter_text and 'kind: "preference"' not in frontmatter_text:
            continue
        if body:
            # Use first non-empty line as summary
            first_line = body.split("\n")[0].strip()
            ref_id = md_path.stem
            entries.append((first_line, ref_id))
    return entries


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Write JSON atomically via temp file + rename."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)
