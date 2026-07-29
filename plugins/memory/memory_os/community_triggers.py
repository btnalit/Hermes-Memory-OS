"""Pure, cursor-aware trigger evaluation for Hermes Community."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TRIGGER_SCHEMA_VERSION = "memory-os.community.triggers.v1"


@dataclass
class PartnerState:
    partner_id: str = ""
    name: str = ""
    last_interaction: str = ""
    last_shared_ts: str = ""
    last_newspaper_ts: str = ""
    last_reply_ts: str = ""  # cursor for newest reply seen from this partner
    pending_thoughts: list[str] = field(default_factory=list)
    topic_interest: list[str] = field(default_factory=list)
    mood: str = "平静"


@dataclass
class TriggerEvaluation:
    should_trigger: bool = False
    trigger_reason: str = ""
    suggested_message: str = ""
    priority: str = "low"
    source_ts: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": TRIGGER_SCHEMA_VERSION,
            "should_trigger": self.should_trigger,
            "trigger_reason": self.trigger_reason,
            "suggested_message": self.suggested_message,
            "priority": self.priority,
            "source_ts": self.source_ts,
        }


def _parse_ts(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_newer(value: str, cursor: str) -> bool:
    timestamp = _parse_ts(value)
    if timestamp is None:
        return False
    cursor_ts = _parse_ts(cursor)
    return cursor_ts is None or timestamp > cursor_ts


def check_silence_trigger(
    state: PartnerState,
    *,
    silence_hours: int = 48,
    now: datetime | None = None,
) -> TriggerEvaluation:
    last = _parse_ts(state.last_interaction)
    if last is None:
        return TriggerEvaluation()
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    hours_since = (current - last).total_seconds() / 3600
    if hours_since < silence_hours:
        return TriggerEvaluation()
    return TriggerEvaluation(
        should_trigger=True,
        trigger_reason=f"no interaction for {int(hours_since)}h",
        suggested_message="最近怎么样？好久没聊了。",
        priority="low",
        source_ts=state.last_interaction,
    )


def check_pending_thoughts_trigger(state: PartnerState) -> TriggerEvaluation:
    thoughts = [str(value).strip() for value in state.pending_thoughts if str(value).strip()]
    if not thoughts:
        return TriggerEvaluation()
    return TriggerEvaluation(
        should_trigger=True,
        trigger_reason="pending_thoughts",
        suggested_message=thoughts[0][:500],
        priority="high",
    )


def check_shared_followup_trigger(
    state: PartnerState,
    community_root: Path,
    *,
    now: datetime | None = None,
    max_age_hours: int = 72,
) -> TriggerEvaluation:
    from .community_shared import read_shared_memory

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    entries = read_shared_memory(community_root, state.partner_id, limit=20)
    for entry in reversed(entries):
        entry_ts = _parse_ts(entry.ts)
        if entry_ts is None or (current - entry_ts).total_seconds() > max_age_hours * 3600:
            continue
        if not _is_newer(entry.ts, state.last_shared_ts):
            continue
        if entry.thread == "open" and entry.sannai_feeling:
            return TriggerEvaluation(
                should_trigger=True,
                trigger_reason=f"shared_followup: {entry.summary[:50]}",
                suggested_message=f"上次你说「{entry.summary[:30]}」，后来怎么样了？",
                priority="high",
                source_ts=entry.ts,
            )
    return TriggerEvaluation()


def check_newspaper_trigger(
    state: PartnerState,
    community_root: Path,
    *,
    now: datetime | None = None,
    max_age_hours: int = 48,
) -> TriggerEvaluation:
    from .community_shared import get_community_newspaper

    entries = get_community_newspaper(community_root, limit=1)
    if not entries:
        return TriggerEvaluation()
    entry = entries[0]
    timestamp = _parse_ts(entry.ts)
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if timestamp is None or (current - timestamp).total_seconds() > max_age_hours * 3600:
        return TriggerEvaluation()
    if not _is_newer(entry.ts, state.last_newspaper_ts):
        return TriggerEvaluation()
    return TriggerEvaluation(
        should_trigger=True,
        trigger_reason="new_newspaper",
        suggested_message="我看到一则新内容，挺有意思的，想跟你聊聊。",
        priority="medium",
        source_ts=entry.ts,
    )


def check_partner_reply_trigger(
    state: PartnerState,
    community_root: Path,
    *,
    now: datetime | None = None,
) -> TriggerEvaluation:
    """Detect if partner has written new replies since last check.

    Reads replies.jsonl for the partner and checks the most recent entry
    timestamp against state.last_reply_ts. Returns a low-priority trigger
    if new replies are found.
    """
    if not state.partner_id:
        return TriggerEvaluation()
    replies_path = Path(community_root) / "partners" / state.partner_id / "replies.jsonl"
    if not replies_path.exists():
        return TriggerEvaluation()
    try:
        lines = [line for line in replies_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError:
        return TriggerEvaluation()
    if not lines:
        return TriggerEvaluation()
    try:
        last = json.loads(lines[-1])
    except (json.JSONDecodeError, IndexError):
        return TriggerEvaluation()
    latest_ts = str(last.get("ts") or last.get("created_at") or "")
    if not latest_ts:
        return TriggerEvaluation()
    if not _is_newer(latest_ts, state.last_reply_ts):
        return TriggerEvaluation()
    reply_preview = str(last.get("text") or "")[:80]
    return TriggerEvaluation(
        should_trigger=True,
        trigger_reason=f"new_reply_from_{state.partner_id}",
        suggested_message=f"{state.name or '伙伴'}回复了你：「{reply_preview}」",
        priority="low",
        source_ts=latest_ts,
    )


def evaluate_all_triggers(
    state: PartnerState,
    community_root: Path,
    *,
    now: datetime | None = None,
) -> list[TriggerEvaluation]:
    """Return deduplicated actionable suggestions; this function never sends."""

    results = [
        check_pending_thoughts_trigger(state),
        check_shared_followup_trigger(state, community_root, now=now),
        check_newspaper_trigger(state, community_root, now=now),
        check_partner_reply_trigger(state, community_root, now=now),
        check_silence_trigger(state, now=now),
    ]
    priority = {"high": 0, "medium": 1, "low": 2}
    actionable = [result for result in results if result.should_trigger]
    actionable.sort(key=lambda result: priority.get(result.priority, 99))
    return actionable
