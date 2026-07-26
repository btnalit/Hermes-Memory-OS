"""
Main session approval loop — integrates review/approval/reject/defer into
the Hermes main conversation session.

Architecture
============
The approval loop surfaces pending review items as part of the system
prompt, not as raw CLI output.  The owner interacts with review items
directly in the conversation, and the session_approval module provides
the structured block that gets injected into the system prompt.

This module connects the existing owner_actions.py machinery to the
Hermes main session flow, ensuring that review, feedback, and approval
all happen through the main conversation channel.
"""

from __future__ import annotations

from typing import Any

from .owner_actions import (
    ALLOWED_FEEDBACK_RATINGS,
    owner_review_surface_report,
    parse_owner_review_reply,
)
from .store import MemoryOSStore
from .timeutil import now_utc, format_utc

SESSION_APPROVAL_SCHEMA_VERSION = "memory-os.session_approval.v1"


def build_session_review_block(
    store: MemoryOSStore,
    *,
    profile: str = "default",
) -> str:
    """Build a review block for the main session system prompt.

    Returns a human-readable block that surfaces pending review items
    in the main session, not as raw CLI output.
    """
    try:
        surface = owner_review_surface_report(
            store,
            operation="overview",
        )
    except Exception:
        return ""

    if not isinstance(surface, dict):
        return ""

    lines: list[str] = []
    actions = surface.get("action_required", []) or []
    suggestions = surface.get("review_suggested", []) or []

    if not actions and not suggestions:
        return ""

    lines.append("")
    lines.append("## Memory-OS Review")

    if actions:
        lines.append("")
        lines.append("**需要处理：**")
        for item in actions[:3]:
            token = (item.get("token") or item.get("id") or "")
            summary = (item.get("summary") or item.get("description") or "")
            lines.append(f"- `{token}`: {summary}")

    if suggestions:
        lines.append("")
        lines.append("**建议查看：**")
        for item in suggestions[:3]:
            token = (item.get("token") or item.get("id") or "")
            summary = (item.get("summary") or item.get("description") or "")
            lines.append(f"- `{token}`: {summary}")

    if actions or suggestions:
        lines.append("")
        lines.append("使用 `memory_os_review_reply` 处理或用 `memory_os_review_surface` 查看详情。")

    return "\n".join(lines)


def build_session_feedback_block(
    store: MemoryOSStore,
    *,
    profile: str = "default",
) -> str:
    """Build a feedback block for the main session.

    Surfaces expression feedback or memory sources feedback that can
    be processed directly in the session.
    """
    try:
        surface = owner_review_surface_report(
            store,
            operation="memory_sources_feedback_context",
        )
    except Exception:
        return ""

    if not isinstance(surface, dict):
        return ""

    lines: list[str] = []
    items = surface.get("feedback", []) or surface.get("items", []) or []

    if not items:
        return ""

    lines.append("")
    lines.append("## 反馈收集")

    for item in items[:2]:
        token = (item.get("token") or item.get("id") or "")
        summary = (item.get("summary") or item.get("description") or "")
        lines.append(f"- `{token}`: {summary}")
        ratings = item.get("ratings", [])
        if ratings:
            lines.append(f"  可选评价: {', '.join(ratings[:5])}")

    return "\n".join(lines)


def has_pending_approval_actions(store: MemoryOSStore) -> bool:
    """Check if there are any pending approval actions.

    Returns True if the owner has unfinished review items.
    """
    try:
        surface = owner_review_surface_report(store, operation="overview")
        if not isinstance(surface, dict):
            return False
        actions = surface.get("action_required", []) or []
        return len(actions) > 0
    except Exception:
        return False


def get_digest_summary(store: MemoryOSStore) -> dict[str, Any]:
    """Get a summary of the current digest state.

    Returns counts of pending, approved, rejected, and deferred items.
    """
    try:
        surface = owner_review_surface_report(store, operation="overview")
    except Exception:
        return {
            "schema_version": SESSION_APPROVAL_SCHEMA_VERSION,
            "has_pending": False,
            "action_required_count": 0,
            "review_suggested_count": 0,
        }

    if not isinstance(surface, dict):
        return {
            "schema_version": SESSION_APPROVAL_SCHEMA_VERSION,
            "has_pending": False,
            "action_required_count": 0,
            "review_suggested_count": 0,
        }

    actions = surface.get("action_required", []) or []
    suggestions = surface.get("review_suggested", []) or []

    return {
        "schema_version": SESSION_APPROVAL_SCHEMA_VERSION,
        "has_pending": len(actions) > 0,
        "action_required_count": len(actions),
        "review_suggested_count": len(suggestions),
    }