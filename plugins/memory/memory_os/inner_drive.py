"""Minimal inner-drive surface for Memory-OS integration validation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .audit import append_audit
from .crystallized import CrystallizedCandidate
from .schema import EventEnvelope, WorkingItem
from .store import MemoryOSStore
from .working import WorkingMemoryService


DEFAULT_SOURCE_CLASS_CAP = 20
SELF_ACTIVITY_MAX_FRACTION = 0.15  # V2d: self_activity events ≤15% of selected batch

# ── Source Gate: deterministic fragment detection ────────────────────────
# Layer A: exact substring markers (extends fact_judge._TRANSIENT_MARKERS).
# Layer B: sentence-structure regex patterns for process fragments.
# Both layers are environment-agnostic — no deployment-specific assumptions.

# Markers are split by script for correct matching strategy:
# - CJK markers use substring matching (safe: CJK chars don't embed in words)
# - Latin markers use word-boundary regex (prevents "hi" matching "architecture")
#
# CJK markers are further split into two tiers:
# - Tier 1 (strong): specific process/command phrases — flag unconditionally
# - Tier 2 (weak): generic confirmations that appear as discourse connectors
#   in substantive replies — only flag if segment is very short (< 30 chars)

_SOURCE_GATE_CJK_STRONG_MARKERS: frozenset[str] = frozenset({
    # Specific process / command phrases
    "更新部署看看", "部署看看", "验证结果如何", "检查一下",
    "试试看", "感觉一下", "感受一下", "体验一下",
    "好不好", "行不行", "对不对", "可不可以",
    "查一下", "看一下", "搜一下", "找一下",
    "帮我查", "帮我找", "帮我搜索", "帮我看看",
    "打开看看", "打开页面", "打开文件", "打开项目",
    "运行一下", "跑一下", "测一下", "编译一下",
    "部署一下", "提交一下", "推送一下", "拉一下代码",
    "稍等", "等一下", "马上", "待会",
    "这个是什么", "这是什么", "怎么用", "怎么操作",
    "天气", "今天",
})

_SOURCE_GATE_CJK_WEAK_MARKERS: frozenset[str] = frozenset({
    # Generic confirmations — only flag in very short segments
    "谢谢", "收到", "再见", "好的", "明白了", "知道了", "不用谢",
    "继续", "嗯", "好的", "可以",
})

# Max segment length for weak CJK markers — above this, the marker
# is treated as a discourse connector (e.g. "好的" at start of reply).
_SOURCE_GATE_WEAK_MARKER_MAX_LEN = 30

_SOURCE_GATE_LATIN_MARKERS: frozenset[str] = frozenset({
    "hello", "thanks", "show me",
    "hi", "bye", "ok",
    "show", "check", "run", "build", "test", "deploy",
    "push", "pull", "commit", "merge", "rebase",
    "look at", "take a look", "let me see",
    "wait", "hold on", "one sec", "just a moment",
    "what is", "how to", "tell me about",
})

# Pre-compiled word-boundary patterns for Latin markers
_SOURCE_GATE_LATIN_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(r"\b" + re.escape(m) + r"\b", re.IGNORECASE)
    for m in _SOURCE_GATE_LATIN_MARKERS
)

# Layer B: compiled regex patterns for sentence-structure fragment detection.
# These catch process/navigation/confirmation patterns that substring
# matching alone would miss.
_SOURCE_GATE_FRAGMENT_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p)
    for p in [
        # Pure info requests
        r"看看.*(状态|情况|部署|日志|进度|结果|输出)",
        r"查一下.*",
        r"搜一下.*",
        # Process confirmations
        r"(试试|试一下|感觉一下|感受一下|体验一下).*",
        r".*(好不好|行不行|对不对|可不可以|能不能行)\s*$",
        r".*(可以吗|行吗|对吗|好吗|怎么样)\s*$",
        # Navigation / commands
        r"打开.*(看看|页面|文件|项目|应用)",
        r"帮我.*(查|找|搜索|看看|打开|运行|部署|测试)",
        # Ultra-short: single-character or very short inputs
        r"^[嗯好行可哦噢]$",
        r"^(继续|稍等|等一下|马上|待会|好了|完了|搞定)$",
        # English short commands (word-anchored)
        r"^(show|check|run|build|test|deploy)(\s+me)?(\s+the\b)?\s*\w*\s*$",
        r"^(push|pull|commit|merge|rebase)(\s+\w+)?$",
        r"^(what is|how to|tell me about|look at|take a look)\s.*$",
        r"^(wait|hold on|one sec|just a moment|got it|okay|ok|sure|thanks|thank you)\s*$",
    ]
)

_SOURCE_GATE_SKIP_REASON = "source_gate:obvious_fragment"


def _is_obvious_fragment(summary: str) -> bool:
    """Deterministic fragment detection — pure function, no I/O/LLM.

    Returns True if the summary looks like an obvious fragment that should
    not enter the candidate queue. False = pass through to downstream gates.

    Two-layer detection:
      Layer A — substring (CJK) / word-boundary (Latin) marker match
      Layer B — regex sentence-structure match

    The _turn_summary format is "User: <clip180> | Assistant: <clip180>".
    We extract both segments and check each independently — if EITHER
    segment is a fragment, the whole turn is treated as a fragment.

    Length guard for CJK markers: segments longer than
    _SOURCE_GATE_MAX_FRAGMENT_SEGMENT_LEN chars are assumed to contain
    substantive content — a marker hit there is just a discourse connector.

    Fail-safe: ambiguous cases return False (allow through).
    """
    if not summary or not summary.strip():
        return False  # empty summary = don't block (fail-safe)

    # Extract User / Assistant segments from _turn_summary format
    user_segment = ""
    assistant_segment = ""
    m = re.match(r"User:\s*(.*?)\s*\|\s*Assistant:\s*(.*)", summary, re.DOTALL)
    if m:
        user_segment = m.group(1).strip()
        assistant_segment = m.group(2).strip()
    else:
        # Degenerate format — treat whole summary as a single segment
        user_segment = summary.strip()

    segments = [s for s in (user_segment, assistant_segment) if s]

    for segment in segments:
        seg_lower = segment.lower()
        seg_len = len(segment)

        # Layer A (CJK): substring match, two-tier.
        # Tier 1 (strong): specific process phrases — flag unconditionally.
        for marker in _SOURCE_GATE_CJK_STRONG_MARKERS:
            if len(marker) >= 2 and marker in segment:
                return True
        # Tier 2 (weak): generic confirmations — only flag in very short
        # segments where the marker IS the message, not a discourse prefix.
        if seg_len <= _SOURCE_GATE_WEAK_MARKER_MAX_LEN:
            for marker in _SOURCE_GATE_CJK_WEAK_MARKERS:
                if len(marker) >= 2 and marker in segment:
                    return True

        # Layer A (Latin): word-boundary regex match.
        # Prevents "hi" matching inside "architecture" or "wait" inside "await".
        for pattern in _SOURCE_GATE_LATIN_PATTERNS:
            if pattern.search(seg_lower):
                return True

        # Layer B: regex sentence-structure
        for pattern in _SOURCE_GATE_FRAGMENT_PATTERNS:
            if pattern.search(seg_lower):
                return True

    return False


@dataclass(frozen=True)
class InnerDriveEventDecision:
    source_class: str
    drive_policy: str
    working_kind: str = ""
    working_weight: float = 0.0
    candidate_allowed: bool = False
    skip_reason: str = ""


@dataclass(frozen=True)
class InnerDriveProcessResult:
    working_item: WorkingItem | None
    candidate: CrystallizedCandidate | None
    decision: InnerDriveEventDecision


class InnerDriveEngine:
    """Process canonical events into working memory and crystallized candidates.

    This v0 surface is intentionally synchronous and small. Autonomous
    scheduling, exploration, and production Sannai personality behavior are
    outside Slice 16.
    """

    def __init__(self, store: MemoryOSStore) -> None:
        self.store = store
        self.working = WorkingMemoryService(store)

    def process_event(
        self,
        event: EventEnvelope,
        *,
        candidate_sensitivity: str = "private",
    ) -> InnerDriveProcessResult:
        decision = classify_event_for_inner_drive(event)
        working_item = None
        candidate = None
        if decision.working_kind:
            working_item = self.working.add_item(
                decision.working_kind,
                event.summary,
                source_event_id=event.id,
                tags=["inner-drive", event.kind, decision.source_class, decision.drive_policy],
                weight=decision.working_weight,
            )
        if decision.candidate_allowed:
            candidate = CrystallizedCandidate(
                candidate_id=f"cand_{event.id}",
                kind="moment",
                body=f"Remembered from event {event.id}: {event.summary}",
                source_event_ids=[event.id],
                sensitivity=candidate_sensitivity,
                tags=["inner-drive", event.kind, decision.source_class],
                bridge_state="inner_drive_candidate",
            )
        append_audit(
            self.store.roots.audit_path,
            action="crystallized_candidate_generated" if candidate else "inner_drive_event_processed",
            status="ok",
            target="inner-drive",
            details={
                "event_id": event.id,
                "source_class": decision.source_class,
                "drive_policy": decision.drive_policy,
                "candidate_id": candidate.candidate_id if candidate else "",
                "working_item_id": working_item.id if working_item else "",
                "skip_reason": decision.skip_reason,
            },
        )
        return InnerDriveProcessResult(working_item=working_item, candidate=candidate, decision=decision)


def classify_event_for_inner_drive(event: EventEnvelope) -> InnerDriveEventDecision:
    safe_ref = dict(event.safe_ref or {})
    kind = event.kind
    source_class = _source_class(event)
    explicit_policy = str(safe_ref.get("drive_policy") or "").strip()
    candidate_explicit = safe_ref.get("candidate_allowed")

    if kind == "conversation_turn":
        # Source gate: default flipped from True to content-based.
        # candidate_explicit (bool) still overrides — preserves explicit control.
        if isinstance(candidate_explicit, bool):
            allowed = candidate_explicit
        else:
            allowed = not _is_obvious_fragment(event.summary)
        return InnerDriveEventDecision(
            source_class=source_class,
            drive_policy=explicit_policy or "eligible",
            working_kind="lingering",
            working_weight=0.6,
            candidate_allowed=allowed,
            skip_reason="" if allowed else _SOURCE_GATE_SKIP_REASON,
        )
    if kind == "memory_write":
        return InnerDriveEventDecision(
            source_class=source_class,
            drive_policy=explicit_policy or "eligible",
            working_kind="lingering",
            working_weight=0.45,
            candidate_allowed=_candidate_allowed(candidate_explicit, default=True),
        )
    if kind == "conversation_turn_mirrored" and safe_ref.get("body_policy") == "bounded_summary":
        return InnerDriveEventDecision(
            source_class=source_class,
            drive_policy=explicit_policy or "eligible",
            working_kind="lingering",
            working_weight=0.3,
            candidate_allowed=_candidate_allowed(candidate_explicit, default=False),
        )
    if kind == "journal_card_observed":
        return InnerDriveEventDecision(
            source_class=source_class,
            drive_policy=explicit_policy or "low_weight",
            working_kind="attention",
            working_weight=0.25,
            candidate_allowed=_candidate_allowed(candidate_explicit, default=False),
        )
    if explicit_policy == "low_weight":
        return InnerDriveEventDecision(
            source_class=source_class,
            drive_policy="low_weight",
            working_kind="attention",
            working_weight=0.2,
            candidate_allowed=_candidate_allowed(candidate_explicit, default=False),
        )
    if kind in {"cron_job_run", "session_observed"} or explicit_policy in {"index_only", "evidence_only", "candidate_surface", "ignore"}:
        return InnerDriveEventDecision(
            source_class=source_class,
            drive_policy=explicit_policy or "index_only",
            candidate_allowed=False,
            skip_reason=explicit_policy or "index_only",
        )
    if kind in {"runtime_heartbeat", "module_audit", "index_event"}:
        return InnerDriveEventDecision(source_class=source_class, drive_policy="ignore", skip_reason="runtime_event")
    return InnerDriveEventDecision(source_class=source_class, drive_policy="index_only", skip_reason="unknown_event_kind")


def select_events_for_inner_drive(
    events: list[EventEnvelope],
    processed_ids: set[str],
    *,
    max_events: int,
    max_events_per_source_class: int | dict[str, int] = DEFAULT_SOURCE_CLASS_CAP,
) -> tuple[list[EventEnvelope], list[EventEnvelope]]:
    selected: list[EventEnvelope] = []
    deferred: list[EventEnvelope] = []
    source_counts: dict[str, int] = {}
    for event in events:
        if event.id in processed_ids:
            continue
        source_class = classify_event_for_inner_drive(event).source_class
        cap = _source_cap(max_events_per_source_class, source_class)
        if source_counts.get(source_class, 0) >= cap:
            deferred.append(event)
            continue
        # V2d: self_activity fraction gate — prevent self_activity from
        # drowning out external events. Once self_activity exceeds
        # SELF_ACTIVITY_MAX_FRACTION of the selected batch, defer remaining
        # self_activity events (oldest-first, since events are sorted by ts).
        if source_class == "self_activity" and len(selected) > 0:
            sa_count = source_counts.get("self_activity", 0)
            sa_max = max(1, int(len(selected) * SELF_ACTIVITY_MAX_FRACTION))
            if sa_count >= sa_max:
                deferred.append(event)
                continue
        selected.append(event)
        source_counts[source_class] = source_counts.get(source_class, 0) + 1
        if len(selected) >= max_events:
            break
    return selected, deferred


def _source_cap(value: int | dict[str, int], source_class: str) -> int:
    if isinstance(value, dict):
        return int(value.get(source_class, value.get("*", DEFAULT_SOURCE_CLASS_CAP)))
    return int(value)


def _candidate_allowed(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    return default


def _source_class(event: EventEnvelope) -> str:
    safe_ref = dict(event.safe_ref or {})
    source = event.source.lower()
    kind = event.kind.lower()
    tags = {str(tag).lower() for tag in event.tags}
    source_module = str(safe_ref.get("source_module", "")).lower()
    source_class = str(safe_ref.get("source_class", "")).lower()
    platform = str(safe_ref.get("platform", "")).lower()
    if source_class == "self_activity":
        return "self_activity"          # V2.2: recognize self_activity before source_module checks
    if source_module == "cron_mirror" or source == "cron" or "cron" in tags or platform == "cron":
        return "cron"
    if source_module == "state_source_mirror" or source_class.startswith("state:") or source == "state_source_mirror":
        return "state_source"
    if source_module == "session_mirror" or source == "session_mirror":
        return "session"
    if platform == "mailbox" or source == "mailbox" or "mailbox" in tags:
        return "mailbox"
    if platform in {"room", "family", "household"} or source in {"room", "family", "household"}:
        return "room_family"
    if source_module in {"ops_gate", "proposal_queue", "evidence_scoring", "self_evolution"}:
        return "governance"
    if any(marker in kind for marker in ("proposal", "governance", "evidence", "ops_gate", "self_evolution")):
        return "governance"
    if kind in {"conversation_turn", "memory_write", "conversation_turn_mirrored"}:
        return "foreground"
    return "other"
