"""Bounded report safety helpers for RH-31."""

from __future__ import annotations

import json
import re
from typing import Any


_FORBIDDEN_PATTERNS = (
    re.compile(r"(?i)\bapi[_-]?key\b"),
    re.compile(r"(?i)\btoken\b"),
    re.compile(r"(?i)\bsecret\b"),
    re.compile(r"(?i)\bpassword\b"),
    re.compile(r"(?i)\bcookie\b"),
    re.compile(r"(?i)raw private"),
)


def forbidden_field_count(value: Any) -> int:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return sum(1 for pattern in _FORBIDDEN_PATTERNS if pattern.search(rendered))


def boundary_false() -> dict[str, bool]:
    return {
        "actual_send": False,
        "actual_execute": False,
        "actual_identity_write": False,
        "actual_relationship_write": False,
        "actual_crystallized_approval": False,
        "hindsight_exported": False,
    }
