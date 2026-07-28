"""
Shared natural-row detection for Memory-OS.

Consolidates the pattern of detecting natural (cron-produced) rows
that was previously scattered across exposure_rollup.py, v3_seed_evidence.py,
v3_wandering.py, and monitor_dashboard_snapshot.py.

Natural row semantics:
- natural_cron: produced by a scheduled cron job under an execution-gate envelope
- manual: produced by manual invocation
- legacy_unmarked: rows written before trigger_class provenance existed
"""

from __future__ import annotations

from typing import Any

NATURAL_ROW_SCHEMA_VERSION = "memory-os.natural_row.v1"

NATURAL_CRON_MARKERS: frozenset[str] = frozenset({"natural_cron", "cron"})
MANUAL_MARKERS: frozenset[str] = frozenset({"manual"})


def is_natural(row: dict[str, Any]) -> bool:
    """Return True if the row was produced by a natural cron run.

    Checks trigger_class, provenance, and natural_production fields.
    """
    trigger = str(
        row.get("trigger_class") or row.get("trigger") or row.get("provenance") or ""
    ).strip().lower()
    if trigger in NATURAL_CRON_MARKERS:
        return True
    if trigger:
        # Explicit provenance always outranks compatibility flags.  Conflicting
        # rows fail closed rather than receiving natural credit.
        return False
    # Compatibility path for MemorySources rows that predate trigger_class.
    if row.get("natural_production") is True:
        traffic = str(row.get("traffic_class") or "").strip().lower()
        if traffic == "production":
            return True
    return False


def is_manual(row: dict[str, Any]) -> bool:
    """Return True if the row was produced by manual invocation."""
    trigger = str(
        row.get("trigger_class") or row.get("trigger") or row.get("provenance") or ""
    ).strip().lower()
    return trigger in MANUAL_MARKERS


def is_legacy_unmarked(row: dict[str, Any]) -> bool:
    """Return True if the row has no trigger provenance marker."""
    trigger = str(
        row.get("trigger_class") or row.get("trigger") or row.get("provenance") or ""
    ).strip().lower()
    return not trigger or trigger in ("", "unknown", "none", "legacy")


def classify_row(row: dict[str, Any]) -> str:
    """Classify a row into one of: natural_cron, manual, legacy_unmarked."""
    if is_natural(row):
        return "natural_cron"
    if is_manual(row):
        return "manual"
    return "legacy_unmarked"


def natural_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter a list of rows to only natural-cron rows."""
    return [row for row in rows if is_natural(row)]


def manual_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter to only manual rows."""
    return [row for row in rows if is_manual(row)]


def legacy_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter to only legacy unmarked rows."""
    return [row for row in rows if is_legacy_unmarked(row)]


def latest_natural_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the latest natural-cron row by created_at, or None."""
    natural = natural_rows(rows)
    if not natural:
        return None
    return max(natural, key=lambda r: r.get("created_at") or "")


def natural_row_date_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Count natural rows per date (YYYY-MM-DD)."""
    from collections import Counter
    counts: Counter[str] = Counter()
    for row in natural_rows(rows):
        created = str(row.get("created_at") or "")
        date_part = created[:10] if len(created) >= 10 else ""
        if date_part:
            counts[date_part] += 1
    return dict(counts)


def has_natural_row_for_date(rows: list[dict[str, Any]], date_str: str) -> bool:
    """Check if a natural row exists for a specific date."""
    for row in natural_rows(rows):
        created = str(row.get("created_at") or "")
        if created.startswith(date_str):
            return True
    return False


def natural_row_count(rows: list[dict[str, Any]]) -> int:
    """Return the total count of natural rows."""
    return len(natural_rows(rows))


def latest_natural_row_date(rows: list[dict[str, Any]]) -> str:
    """Return the date of the latest natural row, or empty string."""
    latest = latest_natural_row(rows)
    if latest is None:
        return ""
    created = str(latest.get("created_at") or "")
    return created[:10] if len(created) >= 10 else ""