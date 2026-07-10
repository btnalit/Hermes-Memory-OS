"""Shared deterministic content guards for owner-review memory surfaces."""

from __future__ import annotations

import re


_RAW_MARKERS = (
    "raw ",
    "raw_",
    "private raw",
    "transcript:",
)

_TRANSCRIPT_MARKERS = (
    "user:",
    "assistant:",
    "用户:",
    "用户：",
    "助手:",
    "助手：",
    "菸草:",
    "菸草：",
    "agentcoco:",
    "agentcoco：",
    "| assistant:",
    "| user:",
)

_SECRET_ASSIGNMENT_PATTERNS = (
    re.compile(r"(?i)\b(?:api[-_\s]?key|token|password|secret)\s*[:=]\s*[^\s;,\)\]}]+"),
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----", re.IGNORECASE),
)


def contains_transcript_marker(value: str) -> bool:
    lowered = str(value or "").lower()
    return any(marker in lowered for marker in _TRANSCRIPT_MARKERS)


def looks_like_raw_review_content(value: str) -> bool:
    lowered = str(value or "").lower()
    return any(marker in lowered for marker in _RAW_MARKERS) or contains_transcript_marker(value)


def contains_secret_assignment(value: str) -> bool:
    text = str(value or "")
    return any(pattern.search(text) for pattern in _SECRET_ASSIGNMENT_PATTERNS)


def permanent_promotion_forbidden_reason_codes(value: str) -> list[str]:
    reasons: list[str] = []
    if looks_like_raw_review_content(value):
        reasons.append("forbidden_raw_transcript")
    if contains_secret_assignment(value):
        reasons.append("forbidden_secret_material")
    return reasons
