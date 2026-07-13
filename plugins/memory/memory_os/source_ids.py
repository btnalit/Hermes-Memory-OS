"""Canonical bounded source-ID policy shared by routing and attribution."""
from __future__ import annotations

import re
from typing import Any

SYNTHETIC_GUARD_IDS = {
    "guard:recall_clarification",
    "guard:foreground_control",
    "guard:candidate_boundary",
}

_ALLOWED_SOURCE_ID_PATTERNS = (
    re.compile(r"^event:[A-Za-z0-9_.:-]+$"),
    re.compile(r"^working:[A-Za-z0-9_.:-]+$"),
    re.compile(r"^candidate:[A-Za-z0-9_.:-]+$"),
    re.compile(r"^crystallized:[A-Za-z0-9_.:-]+$"),
    re.compile(r"^digest:[A-Za-z0-9_.:-]+$"),
    re.compile(r"^reflection_card:[A-Za-z0-9_.:-]+$"),
    re.compile(r"^governance_feedback:[A-Za-z0-9_.:-]+$"),
    re.compile(r"^proposal:[A-Za-z0-9_.:-]+$"),
    re.compile(r"^foreground_task:[A-Za-z0-9_.:-]+$"),
)


def filter_safe_source_id_values(raw_ids: Any) -> list[str]:
    if isinstance(raw_ids, str):
        raw_ids = [raw_ids]
    if not isinstance(raw_ids, (list, tuple, set)):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in raw_ids:
        value = str(item).strip()
        if not value or value in seen:
            continue
        if value in SYNTHETIC_GUARD_IDS or any(pattern.match(value) for pattern in _ALLOWED_SOURCE_ID_PATTERNS):
            seen.add(value)
            result.append(value)
    return result
