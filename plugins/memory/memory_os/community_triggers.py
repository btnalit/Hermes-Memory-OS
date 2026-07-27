"""
Active partner triggers for Hermes Community.

Defines when partners should actively reach out to Sannai,
not just wait for mailbox messages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
import json

TRIGGER_SCHEMA_VERSION = "memory-os.community.triggers.v1"


@dataclass
class PartnerState:
    """Current state of a partner, used for trigger evaluation."""

    partner_id: str = ""
    name: str = ""
    last_interaction: str = ""
    pending_thoughts: list[str] = field(default_factory=list)
    topic_interest: list[str] = field(default_factory=list)
    mood: str = "平静"


@dataclass
class TriggerEvaluation:
    """Result of evaluating whether a partner should reach out."""

    should_trigger: bool = False
    trigger_reason: str = ""
    suggested_message: str = ""
    priority: str = "low"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": TRIGGER_SCHEMA_VERSION,
            "should_trigger": self.should_trigger,
            "trigger_reason": self.trigger_reason,
            "suggested_message": self.suggested_message,
            "priority": self.priority,
        }


def check_silence_trigger(
    state: PartnerState,
    *,
    silence_hours: int = 48,
    now: datetime | None = None,
) -> TriggerEvaluation:
    """Trigger if no interaction for N hours."""
    if not state.last_interaction:
        return TriggerEvaluation()

    now = now or datetime.now(timezone.utc)
    try:
        last = datetime.fromisoformat(state.last_interaction)
        hours_since = (now - last).total_seconds() / 3600
    except (ValueError, TypeError):
        return TriggerEvaluation()

    if hours_since >= silence_hours:
        return TriggerEvaluation(
            should_trigger=True,
            trigger_reason=f"no interaction for {int(hours_since)}h",
            suggested_message=f"最近怎么样？好久没聊了。",
            priority="low",
        )

    return TriggerEvaluation()


def check_pending_thoughts_trigger(
    state: PartnerState,
) -> TriggerEvaluation:
    """Trigger if partner has pending thoughts."""
    if not state.pending_thoughts:
        return TriggerEvaluation()

    thought = state.pending_thoughts[0]
    return TriggerEvaluation(
        should_trigger=True,
        trigger_reason="pending_thoughts",
        suggested_message=thought,
        priority="high",
    )


def check_shared_followup_trigger(
    state: PartnerState,
    community_root: Path,
    *,
    now: datetime | None = None,
) -> TriggerEvaluation:
    """Trigger if partner's shared memory has recent updates."""
    from .community_shared import read_shared_memory

    entries = read_shared_memory(community_root, state.partner_id, limit=5)
    if not entries:
        return TriggerEvaluation()

    now = now or datetime.now(timezone.utc)
    for entry in entries:
        if entry.thread == "closed":
            continue
        try:
            entry_ts = datetime.fromisoformat(entry.ts)
            hours_ago = (now - entry_ts).total_seconds() / 3600
        except (ValueError, TypeError):
            continue

        # If there's an open thread from Sannai with something interesting
        if entry.thread == "open" and entry.sannai_feeling:
            return TriggerEvaluation(
                should_trigger=True,
                trigger_reason=f"shared_followup: {entry.summary[:50]}",
                suggested_message=f"上次你说「{entry.summary[:30]}」，后来怎么样了？",
                priority="high",
            )

    return TriggerEvaluation()


def check_newspaper_trigger(
    state: PartnerState,
    community_root: Path,
) -> TriggerEvaluation:
    """Trigger if there's a new newspaper entry the partner might want to discuss."""
    from .community_shared import get_community_newspaper

    entries = get_community_newspaper(community_root, limit=1)
    if not entries:
        return TriggerEvaluation()

    entry = entries[0]
    return TriggerEvaluation(
        should_trigger=True,
        trigger_reason="new_newspaper",
        suggested_message=f"我看到一篇文章，挺有意思的，想跟你聊聊。",
        priority="medium",
    )


def evaluate_all_triggers(
    state: PartnerState,
    community_root: Path,
    *,
    now: datetime | None = None,
) -> list[TriggerEvaluation]:
    """Evaluate all triggers and return actionable ones."""
    results: list[TriggerEvaluation] = []

    # Check in priority order
    results.append(check_pending_thoughts_trigger(state))
    results.append(check_shared_followup_trigger(state, community_root, now=now))
    results.append(check_newspaper_trigger(state, community_root))
    results.append(check_silence_trigger(state, now=now))

    # Filter to only actionable triggers
    return [r for r in results if r.should_trigger]