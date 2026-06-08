"""Candidate aggregation lane — triage logic for Memory-OS candidate queue.

This module implements queue-state-only operations for the candidate_aggregation
56-lane. It never crystallizes, never auto-approves, never modifies candidates.jsonl.
All triage actions are appended to candidate_triage.jsonl (append-only).

TASK ANCHOR compliance (see 56-lanes/candidate_aggregation/TASK_ANCHOR.md):
  A1 — No auto-crystallize. Any -> crystallized only via owner_actions.
  A2 — actual_crystallized_approval, actual_send, actual_execute, etc. = false.
  A3 — Append-only, never delete.
  A4 — Queue state only: candidate <-> owner_eligible <-> demoted <-> fleeting.
  A5 — Heuristics drive presentation (-> owner_eligible), never crystallization.
  A6 — All writes via StructuralWriteGate or direct append_governed-equivalent.
  A7 — Runs within existing cognitive_loop / ExecutionGate / monitor framework.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from plugins.memory.memory_os.crystallized import (
    CANDIDATE_DEMOTE_TTL_SECONDS,
    CrystallizedCandidate,
    CrystallizedMemoryService,
    append_candidate_triage,
    read_candidate_queue,
    read_candidate_triage,
)
from plugins.memory.memory_os.store import MemoryOSStore

# ── Keyword sets (heuristics, not crystallization rules) ────────────────

# Chinese keywords that suggest a substantive preference/rule/boundary
_ZH_SIGNAL_KEYWORDS: frozenset[str] = frozenset({
    "鐵律", "鐵則",
    "規則", "规则",
    "不要", "別", "别",
    "偏好", "偏愛",
    "喜歡", "喜欢", "不喜歡", "不喜欢",
    "記住", "记住",
    "以後", "以后", "從此",
    "每次", "总是",
    "習慣", "习惯",
    "要求", "务必", "必須", "必须",
    "希望", "不希望",
    "禁忌",
    "重點", "重点",
    "記住我", "记住我",
    "永遠", "永远",
})

# English counterparts
_EN_SIGNAL_KEYWORDS: frozenset[str] = frozenset({
    "always", "never", "rule", "preference", "prefer",
    "important", "remember", "boundary", "must", "mustn't",
    "require", "requirement", "habit", "routine",
    "forbid", "forbidden", "don't", "do not",
    "critical", "crucial", "essential",
})

_ALL_SIGNAL_KEYWORDS = _ZH_SIGNAL_KEYWORDS | _EN_SIGNAL_KEYWORDS

# Chat/acknowledgment patterns — no substantive decision content
_CHAT_PATTERNS: frozenset[str] = frozenset({
    "好的", "明白", "ok", "got it", "了解", "是的",
    "嗯", "好的明白", "理解了", "收到", "好", "可以",
    "知道了", "没问题", "行", "謝謝", "谢谢",
    "okay", "ok", "sure", "got it", "understood", "thanks",
})

# Minimum body length to be considered substantive
_MIN_SUBSTANTIVE_CHARS = 15


# ── Public lane API ─────────────────────────────────────────────────────


def run_candidate_aggregation_lane(
    store: MemoryOSStore,
    *,
    now: datetime | None = None,
    execution_gate_envelope_id: str = "",
) -> dict[str, Any]:
    """Run one tick of the candidate_aggregation lane.

    Steps:
      1. Read all candidates (with triage overrides).
      2. Cluster and promote high-signal candidates -> owner_eligible.
      3. Age-out demote candidates past TTL.
      4. Tag fleeting (no-decision-content) candidates.
      5. Compact archived candidates.
      6. Return summary.

    Returns a dict with counts for monitor integration.
    Never crystallizes. All writes are queue-state-only.
    """
    _now = now or datetime.now(timezone.utc)
    candidates = read_candidate_queue(store)
    triage_records = read_candidate_triage(store)

    # Build a set of already-triaged candidate_ids so we don't re-triage
    already_triaged: set[str] = set()
    for rec in triage_records:
        cid = rec.get("candidate_id")
        if cid:
            already_triaged.add(cid)

    pending = [c for c in candidates if c.candidate_id not in already_triaged]

    # Dedup against crystallized: skip candidates whose content is already
    # in owner_approved.md (or any crystallized .md file). Prevents duplicate
    # promotion of already-crystallized memories.
    crystallized_service = CrystallizedMemoryService(store)
    pending = [
        c for c in pending
        if not crystallized_service.find_records_by_candidate_id(c.candidate_id)
    ]

    promote_results = _cluster_and_promote(pending, store, envelope_id=execution_gate_envelope_id, now=_now)
    demote_results = _demote_aged(pending, store, envelope_id=execution_gate_envelope_id, now=_now)
    fleeting_results = _tag_fleeting(pending, store, envelope_id=execution_gate_envelope_id, now=_now)

    compact_count = 0
    if promote_results["promoted_count"] + demote_results["demoted_count"] > 0:
        from plugins.memory.memory_os.crystallized import compact_candidate_queue
        archive = store.roots.memory_os_root / "system" / "candidate_archive.jsonl"
        compact_count = compact_candidate_queue(store, archive_path=archive, retention_days=7)

    return {
        "candidates_read": len(candidates),
        "pending": len(pending),
        "already_triaged": len(already_triaged),
        "promoted_count": promote_results["promoted_count"],
        "promoted_clusters": promote_results["clusters"],
        "demoted_count": demote_results["demoted_count"],
        "fleeting_count": fleeting_results["fleeting_count"],
        "compacted_count": compact_count,
        "action": "candidate_aggregation_tick",
        "actual_crystallized_approval": False,
        "actual_send": False,
        "actual_execute": False,
        "actual_identity_write": False,
    }


# ── Cluster + promote ───────────────────────────────────────────────────


def _cluster_and_promote(
    candidates: list[CrystallizedCandidate],
    store: MemoryOSStore,
    *,
    envelope_id: str = "",
    now: datetime | None = None,
    min_cluster_size: int = 2,
) -> dict[str, Any]:
    """Cluster pending candidates by theme, promote high-signal clusters.

    Heuristics only — never crystallizes. Only promotes to owner_eligible.
    Cluster criteria: shared keyword matches, same kind, shared source_event_ids.
    """
    _now = now or datetime.now(timezone.utc)
    candidates_for_promote = [
        c for c in candidates
        if c.bridge_state in ("", "inner_drive_candidate")
    ]

    # Build cluster map: cluster_key -> list of candidates
    clusters: dict[str, list[CrystallizedCandidate]] = {}
    for c in candidates_for_promote:
        key = _cluster_key(c)
        if key:
            clusters.setdefault(key, []).append(c)

    # Promote clusters that meet the threshold
    promoted_count = 0
    cluster_summaries: list[dict[str, Any]] = []
    for cluster_key, members in clusters.items():
        if len(members) < min_cluster_size:
            continue
        # Cap promotion per cluster to prevent flooding owner review
        max_promote_per_cluster = 20
        promote_batch = members[:max_promote_per_cluster]
        if len(members) > max_promote_per_cluster:
            # The remaining members get tagged as demoted since they're
            # redundant with the promoted batch (same cluster, same signal)
            for overflow in members[max_promote_per_cluster:]:
                append_candidate_triage(
                    store,
                    candidate_id=overflow.candidate_id,
                    action="demote",
                    target_state="demoted",
                    reason=f"redundant with cluster {cluster_key} (capped at {max_promote_per_cluster})",
                    cluster_key=cluster_key,
                    execution_gate_envelope_id=envelope_id,
                    now=_now,
                )

        # Extract matched keywords for the reason
        matched_keywords = _matched_keywords(members)
        reason = (
            f"cluster match (size={len(members)}, "
            f"keywords={matched_keywords!r}, "
            f"cluster_key={cluster_key})"
        )
        for member in promote_batch:
            append_candidate_triage(
                store,
                candidate_id=member.candidate_id,
                action="promote",
                target_state="owner_eligible",
                reason=reason,
                cluster_key=cluster_key,
                execution_gate_envelope_id=envelope_id,
                now=_now,
            )
            promoted_count += 1
        cluster_summaries.append({
            "cluster_key": cluster_key,
            "size": len(members),
            "keywords": matched_keywords,
        })

    return {"promoted_count": promoted_count, "clusters": cluster_summaries}


# ── Age-out demote ──────────────────────────────────────────────────────


def _demote_aged(
    candidates: list[CrystallizedCandidate],
    store: MemoryOSStore,
    *,
    envelope_id: str = "",
    now: datetime | None = None,
    ttl_seconds: int = CANDIDATE_DEMOTE_TTL_SECONDS,
) -> dict[str, Any]:
    """Auto-demote candidates past TTL with no triage action."""
    _now = now or datetime.now(timezone.utc)
    demoted_count = 0

    for c in candidates:
        if c.bridge_state in ("owner_eligible", "demoted", "fleeting"):
            continue
        age = _candidate_age_seconds(c.created_at, _now)
        if age > ttl_seconds:
            append_candidate_triage(
                store,
                candidate_id=c.candidate_id,
                action="demote",
                target_state="demoted",
                reason=f"aged out (age={age:.0f}s > ttl={ttl_seconds}s, no triage)",
                execution_gate_envelope_id=envelope_id,
                now=_now,
            )
            demoted_count += 1

    return {"demoted_count": demoted_count}


# ── Tag fleeting ────────────────────────────────────────────────────────


def _tag_fleeting(
    candidates: list[CrystallizedCandidate],
    store: MemoryOSStore,
    *,
    envelope_id: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Tag no-decision-content candidates as fleeting."""
    _now = now or datetime.now(timezone.utc)
    fleeting_count = 0

    for c in candidates:
        if c.bridge_state in ("owner_eligible", "demoted", "fleeting"):
            continue
        if _is_fleeting_candidate(c):
            append_candidate_triage(
                store,
                candidate_id=c.candidate_id,
                action="fleeting",
                target_state="fleeting",
                reason="no decision content (chat/acknowledgment only)",
                execution_gate_envelope_id=envelope_id,
                now=_now,
            )
            fleeting_count += 1

    return {"fleeting_count": fleeting_count}


# ── Heuristics ──────────────────────────────────────────────────────────


def _is_fleeting_candidate(candidate: CrystallizedCandidate) -> bool:
    """Return True if the candidate has no substantive decision content."""
    body = (candidate.body or "").strip()
    kind = (candidate.kind or "").strip().lower()

    # Substantive kinds are never fleeting
    if kind in {"rule", "preference", "boundary", "behavior", "pattern", "requirement"}:
        return False

    # Too short to be substantive
    if not body or len(body) < _MIN_SUBSTANTIVE_CHARS:
        return True

    # Pure chat patterns
    body_lower = body.lower().strip()
    if body_lower in _CHAT_PATTERNS:
        return True

    # Inner-drive boilerplate: "Remembered from event ..." — synthetic self-test
    if body_lower.startswith("remembered from event") and kind == "moment":
        return True

    # Generic boilerplate without specific user content
    if body_lower.startswith("memory_os_") and kind == "moment":
        return True

    # No signal keywords at all
    if not _has_signal_keyword(body):
        return True

    return False


def _has_signal_keyword(text: str) -> bool:
    """Check if text contains any signal keyword."""
    lower = text.lower()
    for kw in _ALL_SIGNAL_KEYWORDS:
        if kw.lower() in lower:
            return True
    return False


def _matched_keywords(candidates: list[CrystallizedCandidate]) -> list[str]:
    """Return list of unique signal keywords found across candidates."""
    matched: set[str] = set()
    for c in candidates:
        body = (c.body or "").lower()
        for kw in _ALL_SIGNAL_KEYWORDS:
            if kw.lower() in body:
                matched.add(kw)
    return sorted(matched)


def _cluster_key(candidate: CrystallizedCandidate) -> str | None:
    """Derive a cluster key from a candidate's body and kind.

    Returns None if no signal keyword is found (cannot cluster).
    """
    body = (candidate.body or "").strip()
    kind = (candidate.kind or "").strip().lower()

    if not _has_signal_keyword(body):
        return None

    matched = _matched_keywords([candidate])
    if not matched:
        return None

    # Use the first matched keyword as the primary cluster dimension
    primary = matched[0]
    return f"{kind}:{primary}"


def _candidate_age_seconds(created_at: str, now: datetime) -> float:
    """Parse a candidate's created_at timestamp and return age in seconds."""
    if not created_at:
        return float("inf")
    try:
        parsed = datetime.fromisoformat(created_at)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return (now - parsed).total_seconds()
    except (ValueError, TypeError):
        return float("inf")


# ── Write gate for inner_drive ──────────────────────────────────────────


def should_persist_candidate(candidate: CrystallizedCandidate) -> bool:
    """Return False for candidates with no substantive decision content.

    This is the pre-write gate called by inner_drive before appending.
    Candidates that fail this gate are either not persisted or tagged fleeting.
    A1/A5: this is a write-end gate, not a crystallization rule.
    """
    body = (candidate.body or "").strip()
    kind = (candidate.kind or "").strip().lower()

    # Substantive kinds always pass
    if kind in {"rule", "preference", "boundary", "behavior", "pattern", "requirement"}:
        return True

    # Empty or too-short bodies are not worth persisting
    if not body or len(body) < _MIN_SUBSTANTIVE_CHARS:
        return False

    # Pure chat patterns — no decision content
    body_lower = body.lower().strip()
    if body_lower in _CHAT_PATTERNS:
        return False

    # Inner-drive boilerplate: "Remembered from event ..." — synthetic self-test
    if body_lower.startswith("remembered from event") and kind == "moment":
        return False

    # Generic boilerplate without specific user content
    if body_lower.startswith("memory_os_") and kind == "moment":
        return False

    # No signal keywords — likely chat
    if not _has_signal_keyword(body):
        return False

    return True
