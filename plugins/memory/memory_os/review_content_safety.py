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
    # ── B7: forbidden_permanent sensitivity class ─────────────────────
    if _contains_credential_pattern(value):
        reasons.append("forbidden_permanent_sensitive")
    return reasons


# ── B7: Channel attestation contract ──────────────────────────────────────

CHANNEL_ATTESTATION_SCHEMA_VERSION = "memory-os.channel_attestation.v0"


def validate_channel_attestation(
    attestation: dict[str, Any] | None,
) -> dict[str, Any]:
    """Validate a channel attestation against the Memory-OS contract.

    Default-deny (owner ruling #4): missing or invalid attestation →
    ``channel_class="unknown"`` → ``summary_only``.
    """
    if not isinstance(attestation, dict):
        return {"channel_class": "unknown", "owner_verified": False, "valid": False}
    if attestation.get("schema_version") != CHANNEL_ATTESTATION_SCHEMA_VERSION:
        return {"channel_class": "unknown", "owner_verified": False, "valid": False}
    channel_class = str(attestation.get("channel_class") or "unknown")
    owner_verified = bool(attestation.get("owner_verified"))
    if channel_class not in {"dm", "group", "unknown"}:
        return {"channel_class": "unknown", "owner_verified": False, "valid": False}

    # Check expiry
    expiry = str(attestation.get("expiry") or "")
    if expiry:
        try:
            from datetime import datetime
            expiry_dt = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
            if expiry_dt < datetime.now(expiry_dt.tzinfo):
                return {"channel_class": channel_class, "owner_verified": owner_verified, "valid": False, "reason": "expired"}
        except (ValueError, TypeError):
            pass

    valid = channel_class == "dm" and owner_verified
    return {
        "channel_class": channel_class,
        "owner_verified": owner_verified,
        "valid": valid,
    }


def classify_sensitivity(
    body: str,
    *,
    attestation: dict[str, Any] | None = None,
    sensitivity_policy_enabled: bool = False,
) -> str:
    """Classify content sensitivity: allow | summary_only | forbidden_permanent.

    When *sensitivity_policy_enabled* is False, always returns "allow"
    (backward compatible — no behavior change).
    """
    if not sensitivity_policy_enabled:
        return "allow"

    # Forbidden permanent: credentials, API keys, tokens, certs, ID numbers
    if _contains_credential_pattern(body):
        return "forbidden_permanent"

    # Summary only when channel attestation is missing or invalid
    channel_result = validate_channel_attestation(attestation)
    if not channel_result["valid"]:
        return "summary_only"

    return "allow"


def _contains_credential_pattern(value: str) -> bool:
    """Detect credential-like patterns in body text (B7)."""
    import re
    patterns = [
        r'sk-[A-Za-z0-9]{20,}',           # API keys (OpenAI-style)
        r'Bearer\s+[A-Za-z0-9_\-\.]{20,}', # Bearer tokens
        r'password\s*[:=]\s*\S+',          # password assignment
        r'secret\s*[:=]\s*\S+',            # secret key assignment
        r'api[_-]?key\s*[:=]\s*\S+',       # API key assignment
        r'token\s*[:=]\s*[A-Za-z0-9_\-]{16,}', # explicit token
        r'\b\d{6}\b.*\b\d{4}\b.*\b\d{4}\b.*\b\d{4}\b',  # 16-digit card-like
    ]
    for pattern in patterns:
        if re.search(pattern, value, re.IGNORECASE):
            return True
    return False
