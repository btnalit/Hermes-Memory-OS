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

DESIGN INTENT: This module runs as a cron lane (56-lanes/candidate_aggregation),
NOT inside the cognitive loop's 40-step warm-path. The cognitive loop focuses on
perception and judgment; candidate aggregation is a separate governance rhythm
that operates on the accumulated queue. See TASK_ANCHOR.md for lane contracts.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from plugins.memory.memory_os.crystallized import (
    CANDIDATE_DEMOTE_TTL_SECONDS,
    CrystallizedCandidate,
    CrystallizedMemoryService,
    append_candidate_triage,
    read_candidate_queue,
    read_candidate_triage,
    resolve_candidate_effective_state,
)
from plugins.memory.memory_os.audit import append_audit
from plugins.memory.memory_os.store import MemoryOSStore

# V3a: knob override resolution (imported here; resolve_knob called at runtime)


def candidate_aggregation_manifest() -> dict[str, Any]:
    """Return the v0.1 Candidate Aggregation module manifest."""
    return {
        "name": "candidate_aggregation",
        "kind": "governance",
        "version": "0.1.0",
        "layer": "L3",
        "dependencies": {
            "required": ["memory_os >=0.1.0", "execution_gate", "fact_judge"],
        },
        "provides": {
            "commands": ["run_candidate_aggregation_lane"],
            "schedules": ["candidate_aggregation"],
            "reads": [
                "memory_os.crystallized.candidates",
                "memory_os.crystallized.triage",
            ],
            "writes": ["memory_os.crystallized.triage"],
            "consumed_by": ["owner_actions", "monitor"],
        },
        "defaults": {
            "enabled": True,
            "profile_scope": "per-profile",
        },
    }


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

# Auto-created provisional crystallized records should not all share the same
# lifetime: moment records are high-context/low-half-life and otherwise inflate
# future recall/digest surfaces. Owner-specified expires_at is not touched here;
# this helper only supplies defaults for resolver-created provisionals.
_PROVISIONAL_TTL_DAYS_BY_KIND: dict[str, int] = {
    "moment": 3,
}
_DEFAULT_PROVISIONAL_TTL_DAYS = 7

# Terminal triage states — candidates in these states are permanently excluded
# from the pending set and skipped by all pipeline stages.
_TERMINAL_STATES = ("demoted", "fleeting", "absorbed")


def _default_provisional_expires_at(candidate: CrystallizedCandidate, now: datetime) -> str:
    """Return the default resolver-created provisional expiry for a candidate.

    This is deliberately a creation-time policy, not a write_approved_record()
    cap: explicit owner/reviewer expires_at values must remain authoritative.
    """
    kind = str(candidate.kind or "").strip().lower()
    ttl_days = _PROVISIONAL_TTL_DAYS_BY_KIND.get(kind, _DEFAULT_PROVISIONAL_TTL_DAYS)
    return (now + timedelta(days=ttl_days)).isoformat()


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

    # Build a set of terminally-triaged candidate_ids.
    # Only exclude candidates whose latest triage was a terminal state
    # (demoted, fleeting, absorbed). Promoted candidates remain in pending
    # so _demote_aged can re-evaluate stale owner_eligible ones.
    # triage_records is newest-first (read_candidate_triage reverses),
    # so the first record seen for a cid is the latest action.
    # Uses a separate seen_cids accumulator so that older terminal records
    # for a cid don't sneak past when the latest action is non-terminal.
    already_triaged: set[str] = set()
    seen_cids: set[str] = set()
    for rec in triage_records:
        cid = rec.get("candidate_id")
        if cid and cid not in seen_cids:
            seen_cids.add(cid)
            if rec.get("target_state") in _TERMINAL_STATES:
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

    rejected_results = _auto_demote_rejected(pending, store, processed_ids, envelope_id=execution_gate_envelope_id, now=_now, triage_records=triage_records)
    promote_results = _cluster_and_promote(pending, store, processed_ids, envelope_id=execution_gate_envelope_id, now=_now)
    demote_results = _demote_aged(pending, store, processed_ids, envelope_id=execution_gate_envelope_id, now=_now, triage_records=triage_records)
    fleeting_results = _tag_fleeting(pending, store, processed_ids, envelope_id=execution_gate_envelope_id, now=_now, triage_records=triage_records)

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
    triage_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Auto-demote candidates whose rejection_count >= _REJECTION_THRESHOLD.

    Prevents repeated presentation of candidates the owner has explicitly
    rejected multiple times. Uses the rejection_count on the candidate
    dataclass (populated from candidates.jsonl).

    Uses resolve_candidate_effective_state() for the skip guard so that
    promoted candidates (whose raw bridge_state is still
    inner_drive_candidate in the append-only candidates.jsonl) are
    correctly identified and skipped.
    """
    _now = now or datetime.now(timezone.utc)
    demoted_count = 0
    _triage = triage_records if triage_records is not None else []

    for c in candidates:
        if c.candidate_id in processed_ids:
            continue
        effective = resolve_candidate_effective_state(c, _triage)
        if effective in _TERMINAL_STATES:
            continue
        if effective == "owner_eligible":
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

def _skip_tainted_external_evidence(
    candidate: CrystallizedCandidate,
    store: MemoryOSStore,
    processed_ids: set[str],
    *,
    cluster_key: str = "",
    cluster_size: int = 0,
    envelope_id: str = "",
    now: datetime | None = None,
) -> bool:
    """Fail-closed auto path guard: tainted candidates need explicit owner ack."""
    from plugins.memory.memory_os.provenance import candidate_external_ref, is_tainted

    if not is_tainted(candidate, store=store):
        return False
    append_candidate_triage(
        store,
        candidate_id=candidate.candidate_id,
        action="promote",
        target_state="owner_eligible",
        reason="external_evidence_tainted_blocked",
        cluster_key=cluster_key,
        cluster_size=cluster_size,
        execution_gate_envelope_id=envelope_id,
        now=now,
    )
    append_audit(
        store.roots.audit_path,
        action="external_evidence_auto_crystallization_blocked",
        status="blocked",
        target=candidate.candidate_id,
        details={
            "reason": "external_evidence_tainted_blocked",
            "external_ref": candidate_external_ref(candidate, store=store) or "",
            "cluster_key": cluster_key,
            "cluster_size": cluster_size,
        },
    )
    processed_ids.add(candidate.candidate_id)
    return True


def _cluster_and_promote(
    candidates: list[CrystallizedCandidate],
    store: MemoryOSStore,
    processed_ids: set[str],
    *,
    envelope_id: str = "",
    now: datetime | None = None,
    min_cluster_size: int | None = None,
    _override_store_root: str | Path | None = None,
) -> dict[str, Any]:
    """Cluster pending candidates by theme, promote high-signal clusters.

    Heuristics only — never crystallizes. Only promotes to owner_eligible.
    Cluster criteria: shared keyword matches, same kind, shared source_event_ids.
    Skips candidates already written by earlier pipeline stages via processed_ids.

    V3a: min_cluster_size is resolved at call time via resolve_knob() when
    the caller doesn't pass an explicit value. Never put resolve_knob() in
    the default parameter — Python evaluates defaults at import time.
    _override_store_root is test-only; production callers omit it.
    """
    _now = now or datetime.now(timezone.utc)
    # Resolve min_cluster_size at call time (not import time)
    if min_cluster_size is None:
        from plugins.memory.memory_os.knob_overrides import resolve_knob
        kwargs = {}
        if _override_store_root is not None:
            from pathlib import Path
            kwargs["_store_root"] = Path(_override_store_root)
        min_cluster_size = resolve_knob("min_cluster_size", default=2, **kwargs)
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
                    cluster_size=len(members),
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
        # P2 fix: track already-bumped record_ids within this pipeline run
        # to prevent cluster recurrence inflation (N members matching the
        # same provisional → N bumps in one tick instead of 1).
        bumped_record_ids: set[str] = set()
        for member in promote_batch:
            if _skip_tainted_external_evidence(
                member,
                store,
                processed_ids,
                cluster_key=cluster_key,
                cluster_size=len(members),
                envelope_id=envelope_id,
                now=_now,
            ):
                continue
            # P2: Index-based near-duplicate dedup — bump+renew existing provisional
            existing_prov = _match_existing_provisional(store, member.body)
            if existing_prov is not None:
                if existing_prov in bumped_record_ids:
                    # Already bumped by a prior cluster member — absorb silently
                    append_candidate_triage(
                        store,
                        candidate_id=member.candidate_id,
                        action="dedup_absorb",
                        target_state="absorbed",
                        reason=f"bump via cluster: already bumped {existing_prov} this tick",
                        cluster_key=cluster_key,
                        cluster_size=len(members),
                        execution_gate_envelope_id=envelope_id,
                        now=_now,
                    )
                    processed_ids.add(member.candidate_id)
                    continue
                bumped_record_ids.add(existing_prov)
                from plugins.memory.memory_os.crystallized import CrystallizedMemoryService
                crystallized_service = CrystallizedMemoryService(store)
                bump_result = crystallized_service.bump_recurrence_and_renew(
                    existing_prov,
                    execution_gate_envelope_id=envelope_id,
                )
                if bump_result.get("requires_owner_decision"):
                    append_candidate_triage(
                        store,
                        candidate_id=member.candidate_id,
                        action="flag",
                        target_state="owner_eligible",
                        reason=f"max_renewals_reached via cluster: merged into {existing_prov}",
                        cluster_key=cluster_key,
                        cluster_size=len(members),
                        execution_gate_envelope_id=envelope_id,
                        now=_now,
                    )
                else:
                    append_candidate_triage(
                        store,
                        candidate_id=member.candidate_id,
                        action="dedup_absorb",
                        target_state="absorbed",
                        reason=f"bump via cluster: merged into existing provisional {existing_prov}",
                        cluster_key=cluster_key,
                        cluster_size=len(members),
                        execution_gate_envelope_id=envelope_id,
                        now=_now,
                    )
                processed_ids.add(member.candidate_id)
                continue
            # P2 fix: fallback to full-index dedup (catches permanent records
            # that _match_existing_provisional ignores — old _check_index_dedup
            # covered ALL crystallized records, not just provisional).
            perm_match = _check_index_dedup(store, member)
            if perm_match is not None:
                append_candidate_triage(
                    store,
                    candidate_id=member.candidate_id,
                    action="demote",
                    target_state="demoted",
                    reason=f"dedup_skip: similar to permanent crystallized {perm_match}",
                    cluster_key=cluster_key,
                    cluster_size=len(members),
                    execution_gate_envelope_id=envelope_id,
                    now=_now,
                )
                processed_ids.add(member.candidate_id)
                continue

            # ── Resolver routing (P4: lookup judgment stack, then verdict) ──
            confidence_route = _lookup_confidence_route(member, store)
            provisional_promotion = _lookup_provisional_promotion(member, store)
            cascade_policy = _latest_cascade_policy(store)

            verdict = _resolver_verdict(
                member,
                store=store,
                confidence_route=confidence_route,
                provisional_promotion=provisional_promotion,
                cascade_policy=cascade_policy,
            )
            if verdict.get("approve"):
                target_state = "resolver_approved"
                from plugins.memory.memory_os.execution_gate import (
                    start_resolver_auto_approve_envelope,
                    complete_execution_gate_envelope,
                    RESOLVER_AUTO_APPROVE_LANE,
                )
                from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
                from plugins.memory.memory_os.crystallized import CrystallizedMemoryService

                crystallized_service = CrystallizedMemoryService(store)
                envelope = start_resolver_auto_approve_envelope(
                    store,
                    candidate_id=member.candidate_id,
                    sensitivity=member.sensitivity,
                    has_identity_signal=False,
                    bridge_state=member.bridge_state,
                )
                decision = ApprovalDecision(
                    candidate_id=member.candidate_id,
                    purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
                    reviewer="resolver",
                    reviewed_at=_now.isoformat(),
                    note=verdict.get("reason", ""),
                    source_state="resolver_approved",
                    provisional=True,
                    expires_at=_default_provisional_expires_at(member, _now),
                    recurrence=0,
                )
                crystallized_service.write_approved_record(
                    member, decision, file_name="owner_approved.md",
                )
                complete_execution_gate_envelope(
                    store,
                    envelope_id=envelope["execution_gate_envelope_id"],
                    lane_id=RESOLVER_AUTO_APPROVE_LANE,
                    execution_status="completed",
                    postcheck={"crystallized_write": "success"},
                )
            else:
                target_state = "owner_eligible"

            append_candidate_triage(
                store,
                candidate_id=member.candidate_id,
                action="promote",
                target_state=target_state,
                reason=reason,
                cluster_key=cluster_key,
                cluster_size=len(members),
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

    # ── Durable-fact single-item bypass ─────────────────────────────────
    # Candidates marked durable_fact=True by the fact_judge lane get a
    # single-item channel through resolver verdict, bypassing the size≥2
    # cluster gate. Only applies to singleton candidates not already
    # processed by the cluster loop above.
    durable_verdicts: dict[str, bool] = {}
    try:
        from plugins.modules.governance.fact_judge import read_fact_judge_verdicts
        durable_verdicts = read_fact_judge_verdicts(store)
    except Exception as exc:
        # Fail-open: if verdicts can't be read, no bypass (safe default).
        # Secondary try/except guards against audit write failure on the
        # error-recovery path — the lane must not crash because of audit IO.
        try:
            append_audit(
                store.roots.audit_path,
                action="candidate_aggregation_fact_judge_read_failed",
                status="warning",
                target="fact_judge_verdicts",
                details={"error": str(exc)},
            )
        except Exception:
            pass

    if durable_verdicts:
        for c in candidates_for_promote:
            if c.candidate_id in processed_ids:
                continue
            if not durable_verdicts.get(c.candidate_id):
                continue
            if _skip_tainted_external_evidence(
                c,
                store,
                processed_ids,
                cluster_key="",
                cluster_size=1,
                envelope_id=envelope_id,
                now=_now,
            ):
                continue

            # P2: Index-based near-duplicate dedup — bump+renew existing provisional
            existing_prov = _match_existing_provisional(store, c.body)
            if existing_prov is not None:
                from plugins.memory.memory_os.crystallized import CrystallizedMemoryService
                crystallized_service = CrystallizedMemoryService(store)
                result = crystallized_service.bump_recurrence_and_renew(
                    existing_prov,
                    execution_gate_envelope_id=envelope_id,
                )
                if result.get("requires_owner_decision"):
                    append_candidate_triage(
                        store,
                        candidate_id=c.candidate_id,
                        action="flag",
                        target_state="owner_eligible",
                        reason=f"max_renewals_reached: merged into existing provisional {existing_prov}",
                        cluster_key="",
                        cluster_size=1,
                        execution_gate_envelope_id=envelope_id,
                        now=_now,
                    )
                else:
                    append_candidate_triage(
                        store,
                        candidate_id=c.candidate_id,
                        action="dedup_absorb",
                        target_state="absorbed",
                        reason=f"recurrence bump + renew: merged into existing provisional {existing_prov}",
                        cluster_key="",
                        cluster_size=1,
                        execution_gate_envelope_id=envelope_id,
                        now=_now,
                    )
                processed_ids.add(c.candidate_id)
                continue

            # P2 fix: fallback to full-index dedup (catches permanent records
            # that _match_existing_provisional ignores).
            perm_match = _check_index_dedup(store, c)
            if perm_match is not None:
                append_candidate_triage(
                    store,
                    candidate_id=c.candidate_id,
                    action="demote",
                    target_state="demoted",
                    reason=f"dedup_skip: similar to permanent crystallized {perm_match}",
                    cluster_key="",
                    cluster_size=1,
                    execution_gate_envelope_id=envelope_id,
                    now=_now,
                )
                processed_ids.add(c.candidate_id)
                continue

            # ── Resolver routing (reuses W1 path, same as cluster path) ──
            reason = "durable_fact singleton bypass (judge marked durable_fact=True)"
            confidence_route = _lookup_confidence_route(c, store)
            provisional_promotion = _lookup_provisional_promotion(c, store)
            cascade_policy = _latest_cascade_policy(store)

            verdict = _resolver_verdict(
                c,
                store=store,
                confidence_route=confidence_route,
                provisional_promotion=provisional_promotion,
                cascade_policy=cascade_policy,
            )
            if verdict.get("approve"):
                target_state = "resolver_approved"
                from plugins.memory.memory_os.execution_gate import (
                    start_resolver_auto_approve_envelope,
                    complete_execution_gate_envelope,
                    RESOLVER_AUTO_APPROVE_LANE,
                )
                from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
                from plugins.memory.memory_os.crystallized import CrystallizedMemoryService

                crystallized_service = CrystallizedMemoryService(store)
                envelope = start_resolver_auto_approve_envelope(
                    store,
                    candidate_id=c.candidate_id,
                    sensitivity=c.sensitivity,
                    has_identity_signal=False,
                    bridge_state=c.bridge_state,
                )
                decision = ApprovalDecision(
                    candidate_id=c.candidate_id,
                    purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
                    reviewer="resolver",
                    reviewed_at=_now.isoformat(),
                    note=verdict.get("reason", ""),
                    source_state="resolver_approved",
                    provisional=True,
                    expires_at=_default_provisional_expires_at(c, _now),
                    recurrence=0,
                )
                crystallized_service.write_approved_record(
                    c, decision, file_name="owner_approved.md",
                )
                complete_execution_gate_envelope(
                    store,
                    envelope_id=envelope["execution_gate_envelope_id"],
                    lane_id=RESOLVER_AUTO_APPROVE_LANE,
                    execution_status="completed",
                    postcheck={"crystallized_write": "success"},
                )
            else:
                target_state = "owner_eligible"

            append_candidate_triage(
                store,
                candidate_id=c.candidate_id,
                action="promote",
                target_state=target_state,
                reason=reason,
                cluster_key="",
                cluster_size=1,
                execution_gate_envelope_id=envelope_id,
                now=_now,
            )
            processed_ids.add(c.candidate_id)
            promoted_count += 1

    return {"promoted_count": promoted_count, "clusters": cluster_summaries}


# ── Age-out demote ──────────────────────────────────────────────────────


_OWNER_ELIGIBLE_STALE_TTL_SECONDS = 14 * 86400  # 14 days


def _demote_aged(
    candidates: list[CrystallizedCandidate],
    store: MemoryOSStore,
    processed_ids: set[str],
    *,
    envelope_id: str = "",
    now: datetime | None = None,
    ttl_seconds: int = CANDIDATE_DEMOTE_TTL_SECONDS,
    triage_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Auto-demote candidates past TTL with no triage action.

    Uses resolve_candidate_effective_state() to check the effective state
    (considering triage overlay) rather than raw bridge_state, because
    promoted candidates still have bridge_state=inner_drive_candidate in
    the append-only candidates.jsonl.

    Owner_eligible candidates get a longer stale TTL (14 days) to give
    the owner time to process them before auto-demotion.
    """
    _now = now or datetime.now(timezone.utc)
    demoted_count = 0
    _triage = triage_records if triage_records is not None else []

    for c in candidates:
        if c.candidate_id in processed_ids:
            continue
        effective = resolve_candidate_effective_state(c, _triage)
        if effective in _TERMINAL_STATES:
            continue
        age = _candidate_age_seconds(c.created_at, _now)

        if effective == "owner_eligible":
            # Guard against missing/invalid created_at (returns inf), which
            # would otherwise trigger immediate demotion for legacy candidates.
            if age != float("inf") and age > _OWNER_ELIGIBLE_STALE_TTL_SECONDS:
                append_candidate_triage(
                    store,
                    candidate_id=c.candidate_id,
                    action="demote",
                    target_state="demoted",
                    reason=(
                        f"stale owner_eligible (age={age:.0f}s > "
                        f"stale_ttl={_OWNER_ELIGIBLE_STALE_TTL_SECONDS}s)"
                    ),
                    execution_gate_envelope_id=envelope_id,
                    now=_now,
                )
                processed_ids.add(c.candidate_id)
                demoted_count += 1
            continue

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


# ── Judgment stack lookups (P4: un-orphan confidence_router/provisional/cascade) ──


def _lookup_confidence_route(
    candidate: CrystallizedCandidate, store: MemoryOSStore
) -> dict[str, Any] | None:
    """Look up confidence_router route for a candidate.

    Reads from system-modules/confidence_router/routing.jsonl.
    Returns the matching route dict or None if not found / module not yet run.
    """
    routes_path = store.roots.hermes_home / "system-modules" / "confidence_router" / "routing.jsonl"
    if not routes_path.exists():
        return None
    try:
        for line in routes_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            route = json.loads(line)
            if isinstance(route, dict) and route.get("subject_ref") == candidate.candidate_id:
                return route
    except Exception:
        return None
    return None


def _lookup_provisional_promotion(
    candidate: CrystallizedCandidate, store: MemoryOSStore
) -> dict[str, Any] | None:
    """Look up provisional module promotion record for a candidate.

    Reads from system-modules/provisional/records.jsonl.
    Returns the matching record dict or None if not found / module not yet run.
    """
    records_path = store.roots.hermes_home / "system-modules" / "provisional" / "records.jsonl"
    if not records_path.exists():
        return None
    try:
        for line in records_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            if isinstance(record, dict) and record.get("subject_ref") == candidate.candidate_id:
                return record
    except Exception:
        return None
    return None


def _latest_cascade_policy(store: MemoryOSStore) -> dict[str, Any] | None:
    """Read the latest cascade_routing_policy proposal.

    Reads from system-modules/cascade_routing_policy/policy_proposals.jsonl.
    Returns the most recent proposal or None if the module has not yet run.
    """
    proposals_path = store.roots.hermes_home / "system-modules" / "cascade_routing_policy" / "policy_proposals.jsonl"
    if not proposals_path.exists():
        return None
    try:
        proposals = [
            json.loads(line) for line in proposals_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return proposals[-1] if proposals else None
    except Exception:
        return None


# ── Resolver verdict (P4: gate + judgment stack signals) ───────────────────


def _resolver_verdict(
    candidate: CrystallizedCandidate,
    *,
    store: MemoryOSStore,
    confidence_route: dict[str, Any] | None = None,
    provisional_promotion: dict[str, Any] | None = None,
    cascade_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """P4: gate-first verdict enriched by judgment stack signals.

    The deterministic dual-axis gate (resolver_gate.py) is the primary
    decision point. Within the safety envelope, confidence_router band,
    provisional module promotion, and cascade_routing_policy guardrails
    tune the final verdict.

    When judgment stack data is missing, falls back to P3 gate-only
    behavior (default approve for gate-passing candidates).
    """
    from plugins.memory.memory_os.resolver_gate import resolver_eligible

    if not resolver_eligible(candidate, store=store):
        return {"approve": False, "reason": "failed_resolver_gate"}

    # ── Collect judgment stack signals ──
    signals: list[str] = []
    confidence_band = str(confidence_route.get("band") or "") if confidence_route else ""
    provisional_maturity = float(provisional_promotion.get("maturity_score") or 0.0) if provisional_promotion else 0.0
    guardrails_ok = True
    if cascade_policy and isinstance(cascade_policy, dict):
        guardrails_ok = bool(cascade_policy.get("guardrails_passed", True))

    if confidence_band == "high":
        signals.append("confidence_high")
    elif confidence_band == "low":
        signals.append("confidence_low")

    if provisional_maturity >= 0.9:
        signals.append("provisional_mature")

    if not guardrails_ok:
        signals.append("cascade_guardrails_failed")

    # ── Verdict: veto when negative signals outweigh positive ──
    veto_signals = sum(1 for s in signals if s in ("confidence_low", "cascade_guardrails_failed"))
    approve_signals = sum(1 for s in signals if s in ("confidence_high", "provisional_mature"))

    if veto_signals > approve_signals:
        return {"approve": False, "reason": f"verdict_veto: {', '.join(signals)}"}

    # Default approve: gate already filtered non-reversible/identity candidates.
    # Missing judgment stack data → fall back to gate-only behavior (P3 compat).
    return {
        "approve": True,
        "reason": f"resolver_approved: {', '.join(signals)}" if signals else "resolver_gate_passed",
    }


# ── Tag fleeting ────────────────────────────────────────────────────────


def _tag_fleeting(
    candidates: list[CrystallizedCandidate],
    store: MemoryOSStore,
    processed_ids: set[str],
    *,
    envelope_id: str = "",
    now: datetime | None = None,
    triage_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Tag no-decision-content candidates as fleeting.

    Uses resolve_candidate_effective_state() for the skip guard so that
    promoted candidates (whose raw bridge_state is still
    inner_drive_candidate in the append-only candidates.jsonl) are
    correctly identified and skipped.
    """
    _now = now or datetime.now(timezone.utc)
    fleeting_count = 0
    _triage = triage_records if triage_records is not None else []

    for c in candidates:
        if c.candidate_id in processed_ids:
            continue
        effective = resolve_candidate_effective_state(c, _triage)
        if effective in _TERMINAL_STATES:
            continue
        if effective == "owner_eligible":
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


def _match_existing_provisional(
    store: MemoryOSStore,
    body: str,
    *,
    index: object | None = None,
) -> str | None:
    """FTS5 查是否已有高相似的 active provisional crystallized 记录。

    命中返回 record_id，否则 None。
    Fail-open: index 不可用时返回 None（走新建路径）。
    只在 provisional=True 的记录中匹配，不碰 permanent。

    P2 fix: 拆分句子逐句搜索（FTS5 trigram AND 语义下，整段搜索
    会漏掉多句正文中仅部分匹配的情况）。同时预建 provisional ID 集合
    替代逐 hit 调用 find_record（避免 N+1 全量 .md 扫描）。
    """
    if not body or len(body.strip()) < _MIN_SUBSTANTIVE_CHARS:
        return None
    try:
        from plugins.memory.memory_os.index import MemoryOSIndex
        from plugins.memory.memory_os.crystallized import CrystallizedMemoryService

        # Pre-build provisional record ID set (one scan instead of N+1)
        crystallized_service = CrystallizedMemoryService(store)
        provisional_ids: set[str] = {
            r["id"] for r in crystallized_service.list_provisional_records()
            if r.get("id")
        }
        if not provisional_ids:
            return None

        idx = index or MemoryOSIndex(store.roots)
        # Split into sentences and search each independently.
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
            result = idx.search(sentence, limit=3)
            if result.get("mode") in ("missing",):
                continue
            for hit in result.get("hits", []):
                if hit.get("record_type") != "crystallized_record":
                    continue
                record_id = hit.get("record_id")
                if not record_id:
                    continue
                if record_id in provisional_ids:
                    return record_id
    except Exception:
        return None
    return None


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
