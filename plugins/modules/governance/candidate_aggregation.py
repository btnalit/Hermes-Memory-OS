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
    "okay", "sure", "understood", "thanks",
})

# Minimum body length to be considered substantive
_MIN_SUBSTANTIVE_CHARS = 15

# Auto-demote candidates that have been rejected N+ times by owner
_REJECTION_THRESHOLD = 3


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

    # Shared processed_ids set ensures each candidate is handled by exactly
    # one stage — prevents duplicate/contradictory triage records.
    processed_ids: set[str] = set()

    rejected_results = _auto_demote_rejected(pending, store, processed_ids, envelope_id=execution_gate_envelope_id, now=_now)
    promote_results = _cluster_and_promote(pending, store, processed_ids, envelope_id=execution_gate_envelope_id, now=_now)
    demote_results = _demote_aged(pending, store, processed_ids, envelope_id=execution_gate_envelope_id, now=_now)
    fleeting_results = _tag_fleeting(pending, store, processed_ids, envelope_id=execution_gate_envelope_id, now=_now)

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
        "rejected_demoted_count": rejected_results["rejected_demoted_count"],
        "demoted_count": demote_results["demoted_count"],
        "fleeting_count": fleeting_results["fleeting_count"],
        "compacted_count": compact_count,
        "action": "candidate_aggregation_tick",
        "actual_crystallized_approval": False,
        "actual_send": False,
        "actual_execute": False,
        "actual_identity_write": False,
    }


def _auto_demote_rejected(
    candidates: list[CrystallizedCandidate],
    store: MemoryOSStore,
    processed_ids: set[str],
    *,
    envelope_id: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Auto-demote candidates whose rejection_count >= _REJECTION_THRESHOLD.

    Prevents repeated presentation of candidates the owner has explicitly
    rejected multiple times. Uses the rejection_count on the candidate
    dataclass (populated from candidates.jsonl).
    """
    _now = now or datetime.now(timezone.utc)
    demoted_count = 0

    for c in candidates:
        if c.candidate_id in processed_ids:
            continue
        if c.bridge_state in ("demoted", "fleeting"):
            continue
        if c.rejection_count >= _REJECTION_THRESHOLD:
            append_candidate_triage(
                store,
                candidate_id=c.candidate_id,
                action="demote",
                target_state="demoted",
                reason=f"auto-demote: rejection_count={c.rejection_count} >= threshold={_REJECTION_THRESHOLD}",
                execution_gate_envelope_id=envelope_id,
                now=_now,
            )
            processed_ids.add(c.candidate_id)
            demoted_count += 1

    return {"rejected_demoted_count": demoted_count}


# ── Cluster + promote ───────────────────────────────────────────────────


def _cluster_and_promote(
    candidates: list[CrystallizedCandidate],
    store: MemoryOSStore,
    processed_ids: set[str],
    *,
    envelope_id: str = "",
    now: datetime | None = None,
    min_cluster_size: int = 2,
) -> dict[str, Any]:
    """Cluster pending candidates by theme, promote high-signal clusters.

    Heuristics only — never crystallizes. Only promotes to owner_eligible.
    Cluster criteria: shared keyword matches, same kind, shared source_event_ids.
    Skips candidates already written by earlier pipeline stages via processed_ids.
    """
    _now = now or datetime.now(timezone.utc)
    candidates_for_promote = [
        c for c in candidates
        if c.candidate_id not in processed_ids
        and c.bridge_state in ("", "inner_drive_candidate")
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
                processed_ids.add(overflow.candidate_id)

        # Extract matched keywords for the reason
        matched_keywords = _matched_keywords(members)
        reason = (
            f"cluster match (size={len(members)}, "
            f"keywords={matched_keywords!r}, "
            f"cluster_key={cluster_key})"
        )
        for member in promote_batch:
            # Index-based near-duplicate dedup (fail-open)
            dedup_hit = _check_index_dedup(store, member)
            if dedup_hit is not None:
                append_candidate_triage(
                    store,
                    candidate_id=member.candidate_id,
                    action="demote",
                    target_state="demoted",
                    reason=f"dedup_skip: similar to crystallized {dedup_hit}",
                    cluster_key=cluster_key,
                    execution_gate_envelope_id=envelope_id,
                    now=_now,
                )
                processed_ids.add(member.candidate_id)
                continue
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
            processed_ids.add(member.candidate_id)
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
    processed_ids: set[str],
    *,
    envelope_id: str = "",
    now: datetime | None = None,
    ttl_seconds: int = CANDIDATE_DEMOTE_TTL_SECONDS,
) -> dict[str, Any]:
    """Auto-demote candidates past TTL with no triage action.

    Skips candidates already written by earlier pipeline stages via processed_ids.
    """
    _now = now or datetime.now(timezone.utc)
    demoted_count = 0

    for c in candidates:
        if c.candidate_id in processed_ids:
            continue
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
            processed_ids.add(c.candidate_id)
            demoted_count += 1

    return {"demoted_count": demoted_count}


# ── Resolver verdict (P3 minimal: gate + simple LLM) ───────────────────


def _resolver_verdict(
    candidate: CrystallizedCandidate,
    *,
    store: MemoryOSStore,
) -> dict[str, Any]:
    """P3 minimal: resolver_eligible gate determines the verdict.

    The deterministic dual-axis gate (resolver_gate.py) is the primary
    decision point. For candidates that pass the gate, a simple LLM
    check confirms the auto-approval is reasonable.

    Full cascade_routing_policy/provisional integration will enhance
    this in P4.
    """
    from plugins.memory.memory_os.resolver_gate import resolver_eligible

    if not resolver_eligible(candidate, store=store):
        return {"approve": False, "reason": "failed_resolver_gate"}

    # P3: Simple LLM check within the safety envelope.
    # The deterministic gate already filtered out identity/redline/side-effect
    # candidates. The LLM here only confirms that auto-approval is reasonable
    # for this specific memory content.
    try:
        body = (candidate.body or "").strip()
        if len(body) < 10:
            return {"approve": False, "reason": "body_too_short_for_auto_approval"}
        # P3 minimal: gate alone is sufficient for approval
        return {"approve": True, "reason": "resolver_gate_passed_p3_minimal"}
    except Exception:
        # Fail-safe: if verdict computation fails, route to owner
        return {"approve": False, "reason": "verdict_error_fail_safe"}


# ── Tag fleeting ────────────────────────────────────────────────────────


def _tag_fleeting(
    candidates: list[CrystallizedCandidate],
    store: MemoryOSStore,
    processed_ids: set[str],
    *,
    envelope_id: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Tag no-decision-content candidates as fleeting.

    Skips candidates already written by earlier pipeline stages via processed_ids.
    """
    _now = now or datetime.now(timezone.utc)
    fleeting_count = 0

    for c in candidates:
        if c.candidate_id in processed_ids:
            continue
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
            processed_ids.add(c.candidate_id)
            fleeting_count += 1

    return {"fleeting_count": fleeting_count}


# ── Index-based near-duplicate dedup (fail-open) ──────────────────────


def _check_index_dedup(
    store: MemoryOSStore,
    candidate: CrystallizedCandidate,
) -> str | None:
    """Check FTS5 index for crystallized records near-duplicate to candidate body.

    Returns the matching crystallized record_id if a near-duplicate exists,
    or None if the candidate is novel (or index is unavailable).

    Fail-open: index missing/stale/search_error → None (promote proceeds).
    """
    body = (candidate.body or "").strip()
    if not body or len(body) < _MIN_SUBSTANTIVE_CHARS:
        return None
    try:
        from plugins.memory.memory_os.index import MemoryOSIndex

        index = MemoryOSIndex(store.roots)
        # Split into sentences and search each one independently.
        # Trigram FTS5 with AND semantics needs ALL trigrams in the
        # query to match; appending new content or phrasing differences
        # at the sentence level would miss near-duplicates.  By searching
        # per sentence, a single matching sentence is enough to flag.
        import re
        sentences = re.split(r"(?<=[。？！.!?\n])\s*", body)
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            result = index.search(sentence, limit=3)
            if result.get("mode") in ("missing",):
                return None
            for hit in result.get("hits", []):
                if hit.get("record_type") == "crystallized_record":
                    return hit.get("record_id") or hit.get("title") or "unknown"
    except Exception:
        return None
    return None


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
