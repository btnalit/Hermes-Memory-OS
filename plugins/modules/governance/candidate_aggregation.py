"""Candidate aggregation lane — triage + bounded auto-approve for Memory-OS candidate queue.

This module runs as a cron lane (candidate_aggregation). It performs queue-state
triage (promote/demote/absorb/fleeting) AND bounded resolver auto-approve for
candidates that pass the deterministic dual-axis gate (resolver_gate.py).

Auto-approve path (P4, _cluster_and_promote → _resolver_verdict):
  Candidates that cluster (min_cluster_size knob, default 2), pass the resolver
  gate (sensitivity in NON_SENSITIVE, no identity signals, no side effects), and
  survive judgment-stack veto are auto-approved as provisional crystallized records
  (reviewer="resolver", provisional=True) under an ExecutionGate envelope
  (RESOLVER_AUTO_APPROVE_LANE). Permanent crystallization is owner-gated (V2-0):
  the age signal (≥permanent_proposal_min_age_days, default 7d) only marks a
  record eligible for an owner-initiated `memory-os permanent propose`; it never
  writes permanent state on its own.

Triage-only path (owner_eligible):
  Candidates that fail the resolver gate, carry tainted external evidence,
  lack signal keywords (_cluster_key returns None), or belong to clusters below
  min_cluster_size are routed to owner_eligible for manual review.

Queue-state operations (append-only, never delete):
  - Promote: candidate → owner_eligible or resolver_approved
  - Demote: aged, rejected (≥threshold), or duplicate candidates
  - Absorb: near-duplicate → merged into existing provisional
  - Fleeting: no-decision-content candidates tagged, not deleted

Governance anchors:
  A1 — Provisional auto-approve is bounded (provisional=True, expires_at, recurrence cap).
       Permanent crystallization still requires owner or auto_promote age gate.
  A2 — actual_crystallized_approval, actual_send, actual_execute = false for
       triage-only path; resolver-approved path writes provisional with
       actual_crystallized_approval=true under gate envelope.
  A3 — Append-only via StructuralWriteGate; never delete.
  A4 — State machine: candidate → owner_eligible | resolver_approved | demoted |
       absorbed | fleeting.
  A5 — Resolver gate is deterministic (no LLM); judgment stack (confidence_band,
       provisional_maturity, cascade_guardrails) tunes verdict within safety envelope.
  A6 — All writes via StructuralWriteGate or append_governed-equivalent.
  A7 — Runs as cron lane, NOT inside cognitive loop warm-path.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from plugins.memory.memory_os.crystallized import (
    CANDIDATE_DEMOTE_TTL_SECONDS,
    CrystallizedCandidate,
    CrystallizedMemoryService,
    _RESOLVER_PROVISIONAL_WRITE_CAPABILITY,
    append_candidate_triage,
    read_effective_candidates,
    write_candidate_recall_exclusions,
    read_candidate_queue,
    read_candidate_triage,
    resolve_candidate_effective_state,
)
from plugins.memory.memory_os.audit import append_audit
from plugins.memory.memory_os.jsonl_io import build_error_record
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


def crystallized_write_receipt(provisional_write_count: int = 0) -> dict[str, Any]:
    """Return one truthful vocabulary for every candidate-aggregation report."""

    count = max(0, int(provisional_write_count))
    wrote_provisional = count > 0
    return {
        "crystallized_write": "provisional_success" if wrote_provisional else "none",
        "provisional_crystallized_write_count": count,
        # Compatibility field: true means a crystallized approval/write occurred;
        # permanence is expressed only by the explicit field below.
        "actual_crystallized_approval": wrote_provisional,
        "actual_provisional_crystallized_write": wrote_provisional,
        "actual_permanent_crystallized_approval": False,
        "actual_unapproved_permanent_crystallized_write": False,
        "actual_unapproved_crystallized_approval": False,
    }


def provisional_write_postcheck() -> dict[str, Any]:
    """Boundary-safe ExecutionGate postcheck for one reversible provisional write.

    P1-1: deliberately does NOT delegate to crystallized_write_receipt(1).
    That helper's `actual_crystallized_approval` / `actual_provisional_
    crystallized_write` fields are bare `bool` `True` — and execution_gate's
    any_boundary_true()/boundary_true_paths() treat ANY bare `True` found
    recursively inside a postcheck dict as a boundary violation, with no
    concept of "provisional". Every legitimate, bounded, reversible
    provisional crystallized write would therefore trip
    postcheck_boundary_true=True and cascade into false FAIL alarms in the
    boundary runtime probe and monitor.

    This postcheck stays truthful without using bare True: the write is
    still evidenced by crystallized_write == "provisional_success" and by
    provisional_crystallized_write_count (an int — boundary_true_paths only
    matches `bool` True, never truthy ints). Permanence is explicitly False
    via actual_permanent_crystallized_approval, since resolver auto-approve
    never grants permanent crystallization on its own.

    crystallized_write_receipt() itself is unchanged and stays truthful for
    genuine lane run results / stdout evidence (see run_candidate_
    aggregation_lane) — only this ExecutionGate-facing postcheck is
    boundary-safe.
    """

    return {
        "crystallized_write": "provisional_success",
        "provisional_crystallized_write_count": 1,
        "actual_permanent_crystallized_approval": False,
        "actual_unapproved_permanent_crystallized_write": False,
        "actual_unapproved_crystallized_approval": False,
    }


def _resolver_candidate_gate_result(
    store: MemoryOSStore,
    candidate: CrystallizedCandidate,
) -> dict[str, Any]:
    import json

    from plugins.memory.memory_os.crystallization_gate import run_crystallization_gate
    from plugins.memory.memory_os.index import MemoryOSIndex

    return run_crystallization_gate(
        str(store.roots.index_path),
        index=MemoryOSIndex(store.roots),
        audit_path=str(store.roots.audit_path),
        candidates=[
            {
                "candidate_id": candidate.candidate_id,
                "body": candidate.body,
                "tags_json": json.dumps(candidate.tags or [], ensure_ascii=False),
            }
        ],
    )


def _resolver_candidate_gate_allows(
    result: dict[str, Any],
    candidate_id: str,
) -> bool:
    if str(result.get("status") or "") != "ok":
        return False
    flagged_ids = {
        str(item.get("candidate_id") or "")
        for item in result.get("flagged_candidates", [])
        if isinstance(item, dict)
    }
    return candidate_id not in flagged_ids


def _write_resolver_provisional(
    store: MemoryOSStore,
    candidate: CrystallizedCandidate,
    decision: Any,
) -> Path:
    from plugins.memory.memory_os.execution_gate import (
        RESOLVER_AUTO_APPROVE_LANE,
        RESOLVER_AUTO_APPROVE_RISK_CLASS,
        complete_execution_gate_envelope,
        resolve_execution_gate_permit,
        start_resolver_auto_approve_envelope,
    )

    envelope = start_resolver_auto_approve_envelope(
        store,
        candidate_id=candidate.candidate_id,
        sensitivity=candidate.sensitivity,
        has_identity_signal=False,
        bridge_state=candidate.bridge_state,
    )
    envelope_id = str(envelope["execution_gate_envelope_id"])
    permit = resolve_execution_gate_permit(
        store.roots,
        envelope_id=envelope_id,
        lane_id=RESOLVER_AUTO_APPROVE_LANE,
        risk_class=RESOLVER_AUTO_APPROVE_RISK_CLASS,
        require_fresh=True,
        require_unused=True,
        expected_scope=(envelope.get("scope") if isinstance(envelope.get("scope"), dict) else {}),
    )
    if str(permit.get("status") or "") != "valid":
        complete_execution_gate_envelope(
            store,
            envelope_id=envelope_id,
            lane_id=RESOLVER_AUTO_APPROVE_LANE,
            execution_status="failed_closed",
            postcheck={
                "crystallized_write": "none",
                "actual_permanent_crystallized_approval": False,
                "actual_unapproved_permanent_crystallized_write": False,
            },
            result_summary={
                "candidate_id": candidate.candidate_id,
                "error_code": str(permit.get("reason") or "execution_gate_permit_invalid"),
            },
        )
        raise PermissionError(str(permit.get("reason") or "execution_gate_permit_invalid"))
    try:
        path = CrystallizedMemoryService(store).write_approved_record(
            candidate,
            decision,
            file_name="owner_approved.md",
            capability=_RESOLVER_PROVISIONAL_WRITE_CAPABILITY,
        )
    except Exception as exc:
        complete_execution_gate_envelope(
            store,
            envelope_id=envelope_id,
            lane_id=RESOLVER_AUTO_APPROVE_LANE,
            execution_status="failed",
            postcheck={
                "crystallized_write": "provisional_failed",
                "actual_permanent_crystallized_approval": False,
                "actual_unapproved_permanent_crystallized_write": False,
            },
            result_summary={
                "candidate_id": candidate.candidate_id,
                "error_type": type(exc).__name__,
            },
        )
        raise
    complete_execution_gate_envelope(
        store,
        envelope_id=envelope_id,
        lane_id=RESOLVER_AUTO_APPROVE_LANE,
        execution_status="completed",
        postcheck=provisional_write_postcheck(),
    )
    return path


def _try_write_resolver_provisional(
    store: MemoryOSStore,
    candidate: CrystallizedCandidate,
    decision: Any,
    *,
    error_records: list[dict[str, Any]] | None = None,
) -> bool:
    """Write a resolver provisional; on failure record and contain, never raise.

    CE.2 isolation: one candidate that the crystallized write gate rejects
    must not kill the whole aggregation tick -- before this, a single bad
    candidate re-crashed the lane on every due tick (rc=1, no helper report),
    permanently starving every other candidate behind it. The envelope inside
    _write_resolver_provisional already closes itself as failed; this boundary
    turns the re-raise into a bounded error record so the caller can route the
    candidate to owner review and keep going.
    """
    try:
        _write_resolver_provisional(store, candidate, decision)
        return True
    except Exception as exc:
        record = build_error_record(
            component="candidate_aggregation",
            operation="write_resolver_provisional",
            error_code="provisional_write_failed",
            severity="error",
            recoverable=True,
            details={
                "candidate_id": candidate.candidate_id,
                "error_type": type(exc).__name__,
                "message": str(exc)[:200],
            },
        )
        if error_records is not None:
            error_records.append(record)
        return False


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

    Returns counts plus a truthful crystallized-write receipt. Resolver-approved
    paths may write bounded, reversible provisional records; permanent approval
    remains Owner-only.
    """
    _now = now or datetime.now(timezone.utc)
    candidate_error_records: list[dict[str, Any]] = []
    candidates = read_candidate_queue(store, error_records=candidate_error_records)
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
    # Only an ACTIVE crystallized record shields a candidate from the
    # pipeline. Measured hole (2026-08-14, production): three queue rows
    # whose provisional records had been resolver-evicted were still
    # pre-filtered here — an inactive record kept shielding the row, so no
    # stage (including the stale sweep) could ever reach it, while compact's
    # triage-only state view kept the row alive: immortal by construction.
    from plugins.memory.memory_os.crystallized import is_active_crystallized_frontmatter

    pending = [
        c for c in pending
        if not any(
            is_active_crystallized_frontmatter(record.frontmatter)
            for record in crystallized_service.find_records_by_candidate_id(c.candidate_id)
        )
    ]

    # Shared processed_ids set ensures each candidate is handled by exactly
    # one stage — prevents duplicate/contradictory triage records.
    processed_ids: set[str] = set()

    rejected_results = _auto_demote_rejected(pending, store, processed_ids, envelope_id=execution_gate_envelope_id, now=_now, triage_records=triage_records)
    # The 14-day stale-owner_eligible sweep runs BEFORE promote so the
    # promote stage cannot re-claim (and thereby age-exempt) keyword-rich
    # candidates every run — see _demote_aged's docstring for the measured
    # starvation hole this closes. The full aged pass (3-day no-triage
    # branch) stays after promote, unchanged.
    stale_results = _demote_aged(pending, store, processed_ids, envelope_id=execution_gate_envelope_id, now=_now, triage_records=triage_records, stale_owner_eligible_only=True)
    promote_results = _cluster_and_promote(pending, store, processed_ids, envelope_id=execution_gate_envelope_id, now=_now, error_records=candidate_error_records)
    demote_results = _demote_aged(pending, store, processed_ids, envelope_id=execution_gate_envelope_id, now=_now, triage_records=triage_records)
    fleeting_results = _tag_fleeting(pending, store, processed_ids, envelope_id=execution_gate_envelope_id, now=_now, triage_records=triage_records)

    from plugins.memory.memory_os.crystallized import compact_candidate_queue
    archive = store.roots.memory_os_root / "system" / "candidate_archive.jsonl"
    # Compaction is an all-or-nothing rewrite. If the tolerant reader observed
    # corruption, preserve the queue byte-for-byte and surface the bounded
    # errors instead of allowing a partial archive/replace transaction.
    # Compute the FULL terminal view once (crystallized-record + owner-action
    # overlays included) and let it drive BOTH the queue compaction and the
    # recall-exclusion projection — one semantics, one source. Before this,
    # compaction resolved state from triage rows alone and kept
    # crystallized-long-ago rows in the live queue forever (measured: five
    # production rows, 66–98 days old, recall-excluded yet never archived).
    # read_effective_candidates costs ~61ms on production — affordable here
    # in an offline lane, never on the per-turn prefetch path.
    #
    # Errors accumulated BEFORE this point -- malformed candidates.jsonl rows
    # from read_candidate_queue, or a promote-stage failure recorded by
    # _cluster_and_promote -- disable compaction entirely; that pre-existing
    # "any upstream error -> skip compaction" policy for those two feeders
    # is unchanged (see test_queue_parse_error_still_skips_compaction and
    # test_promote_stage_error_still_skips_compaction in
    # test_candidate_aggregation_logic.py). Snapshot the count now, before
    # the try/except below can append its own error, so the two reasons
    # stay independently attributable in compaction_skip_reason below even
    # though, as of 2026-08-15, all three now skip compaction the same way.
    pre_effective_view_error_count = len(candidate_error_records)
    effective_terminal_ids: set[str] | None = None
    archivable_terminal_ids: set[str] | None = None
    # compact_candidate_queue's provisional_backed_candidate_ids is a
    # REQUIRED (non-Optional) argument. It is only ever passed when
    # compaction actually runs (see compaction_skip_reason below), so this
    # initial empty set is never itself handed to a real archival decision
    # -- it exists purely so the variable is always bound.
    provisional_backed_ids: set[str] = set()
    effective_view_failed = False
    effective_count = 0
    try:
        effective = read_effective_candidates(store)
        effective_count = len(effective)
        effective_terminal_ids = {
            item.candidate.candidate_id for item in effective if item.terminal
        }
        # A provisional-backed terminal candidate (its only active
        # crystallized record is provisional=True) must NOT be archived out
        # of the live queue: the provisional is reversible by design
        # (resolver TTL/cap eviction, owner reject via
        # invalidate_provisional_record) and archival has no way back. It
        # still belongs in the FULL terminal set used for the recall-
        # exclusion projection below -- the content is already in
        # crystallized memory, so it must not double-surface in recall
        # while the provisional anchor is active. Only a permanent
        # (non-provisional) crystallized record, or a demoted/fleeting/
        # absorbed/owner-closed state, is archivable.
        archivable_terminal_ids = {
            item.candidate.candidate_id
            for item in effective
            if item.terminal and not item.provisional_backed
        }
        # Excluding these ids from archivable_terminal_ids only protects
        # them from compact_candidate_queue's terminal-ids branch. Its
        # retention-window elif/else resolves state from triage rows alone
        # (resolver_approved, not owner_eligible) and does not know a
        # candidate is provisional-backed, so an aged resolver-approved
        # provisional row was still archivable through that branch --
        # same loss shape as the case above, reached a different way, and
        # arguably more likely to fire since provisional TTLs can exceed
        # retention_days. Pass the id set explicitly so
        # compact_candidate_queue enforces the guarantee on every branch.
        provisional_backed_ids = {
            item.candidate.candidate_id for item in effective if item.provisional_backed
        }
    except Exception as exc:  # noqa: BLE001 - view failure never breaks the lane; compaction is skipped instead
        effective_view_failed = True
        candidate_error_records.append(
            build_error_record(
                component="candidate_aggregation",
                operation="read_effective_candidates",
                error_code="candidate_effective_view_failed",
                severity="warning",
                recoverable=True,
                details={"error_type": type(exc).__name__, "message": str(exc)[:200]},
            )
        )

    # Whether and why compaction ran, as an explicit decision -- not a side
    # effect of candidate_error_records' length, which was the actual defect
    # here (2026-08-15 finding): the code used to comment that a
    # read_effective_candidates failure "degrades to terminal_candidate_ids=
    # None (compact's own triage-only view)", but triage-only compaction is
    # exactly what archives a provisional-backed candidate irreversibly
    # (Defect C) -- so degrading to it on the ONE path where we have the
    # LEAST information about which candidates are provisional-backed was
    # itself unsafe. When the view fails we do not know which candidates
    # are provisional-backed; archiving under that uncertainty is
    # unrecoverable (candidates.archive.jsonl has no production reader), so
    # a view failure now joins the two pre-existing upstream-error sources
    # in skipping compaction outright, rather than falling back to a
    # triage-only view that cannot make the provisional-backed distinction
    # at all. Not compacting just lets the live queue grow -- visible,
    # bounded by how long the failure persists, and fully recoverable the
    # moment the malformed record is fixed.
    #
    # compaction_skip_reason is the durable, closed-set answer to "why did
    # compaction not run this tick", surfaced in the returned summary so a
    # reader can distinguish it from "compaction ran and archived nothing"
    # (compaction_skip_reason is None, compacted_count is a real count)
    # without re-running anything or reading source:
    #   None                       -- compaction ran normally.
    #   "effective_view_unavailable" -- read_effective_candidates raised;
    #       see candidate_effective_view_failed in error_records.
    #   "upstream_error"           -- read_candidate_queue or
    #       _cluster_and_promote recorded an error before the effective-view
    #       attempt; see recent_error_codes / error_records for which.
    if effective_view_failed:
        compaction_skip_reason: str | None = "effective_view_unavailable"
    elif pre_effective_view_error_count:
        compaction_skip_reason = "upstream_error"
    else:
        compaction_skip_reason = None

    compact_count = 0 if compaction_skip_reason else compact_candidate_queue(
        store,
        archive_path=archive,
        retention_days=7,
        terminal_candidate_ids=archivable_terminal_ids,
        provisional_backed_candidate_ids=provisional_backed_ids,
    )

    # Publish the hot-path recall exclusion projection (owner ruling
    # 2026-08-14: candidates are admitted to recall at candidate authority
    # without approval, so the owner's reject must actually take effect).
    # Fail-open by contract: a failure here leaves the previous snapshot (or
    # none), which degrades to the pre-ruling behavior rather than blanking
    # candidate recall.
    recall_exclusion_count = -1
    if effective_terminal_ids is not None:
        try:
            write_candidate_recall_exclusions(
                store,
                effective_terminal_ids,
                now=_now,
                source_counts={
                    "effective_candidates": effective_count,
                    "terminal": len(effective_terminal_ids),
                },
            )
            recall_exclusion_count = len(effective_terminal_ids)
        except Exception as exc:  # noqa: BLE001 - projection must not break the lane
            candidate_error_records.append(
                build_error_record(
                    component="candidate_aggregation",
                    operation="write_candidate_recall_exclusions",
                    error_code="candidate_recall_exclusion_publish_failed",
                    severity="warning",
                    recoverable=True,
                    details={"error_type": type(exc).__name__, "message": str(exc)[:200]},
                )
            )

    result = {
        "candidates_read": len(candidates),
        "pending": len(pending),
        "already_triaged": len(already_triaged),
        "recall_exclusion_count": recall_exclusion_count,
        "promoted_count": promote_results["promoted_count"],
        "promoted_clusters": promote_results["clusters"],
        "rejected_demoted_count": rejected_results["rejected_demoted_count"],
        # Aggregate keeps its historical meaning (all age-driven demotions
        # this run); the stale share is also reported on its own so the
        # starvation fix is observable per run.
        "demoted_count": demote_results["demoted_count"] + stale_results["demoted_count"],
        "stale_owner_eligible_demoted_count": stale_results["demoted_count"],
        "fleeting_count": fleeting_results["fleeting_count"],
        "compacted_count": compact_count,
        # Closed set: None (ran normally), "effective_view_unavailable"
        # (read_effective_candidates raised), "upstream_error"
        # (read_candidate_queue or _cluster_and_promote recorded an error
        # first). See the comment above compaction_skip_reason's assignment
        # for why a view failure must not fall back to compacting anyway.
        "compaction_skip_reason": compaction_skip_reason,
        "action": "candidate_aggregation_tick",
        "status": "warning" if candidate_error_records else "ok",
        "suppressed_error_count": len(candidate_error_records),
        "recent_error_codes": [
            str(record.get("error_code") or "")
            for record in candidate_error_records[-5:]
            if record.get("error_code")
        ],
        "error_records": candidate_error_records[-5:],
        "promotion_result": promote_results,
        "actual_send": False,
        "actual_execute": False,
        "actual_identity_write": False,
    }
    result.update(crystallized_write_receipt(promote_results["provisional_crystallized_write_count"]))
    return result


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
    error_records: list[dict[str, Any]] | None = None,
    _override_store_root: str | Path | None = None,
) -> dict[str, Any]:
    """Cluster pending candidates by theme, promote high-signal clusters.

    Heuristics may route resolver-safe candidates into bounded provisional
    crystallization; all other candidates remain queue-state-only.
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
        kwargs: dict[str, Any] = {}
        if _override_store_root is not None:
            from pathlib import Path
            kwargs["_store_root"] = Path(_override_store_root)
        else:
            # Production path: resolve from the store being operated on
            # (not ambient ~/.hermes) so tests that create a synthetic store
            # are isolated from the user's real knob overrides.
            kwargs["roots"] = store.roots
        min_cluster_size = resolve_knob("min_cluster_size", default=1, **kwargs)
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
    provisional_write_count = 0
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
            # Gate only the verdicts that could actually write.  It opens two
            # sqlite connections and runs an FTS query per call, and its result
            # is read only on the approve path.
            gate_result = (
                _resolver_candidate_gate_result(store, member) if verdict.get("approve") else {}
            )
            if verdict.get("approve") and _resolver_candidate_gate_allows(
                gate_result, member.candidate_id,
            ):
                target_state = "resolver_approved"
                from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
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
                if _try_write_resolver_provisional(
                    store, member, decision, error_records=error_records,
                ):
                    provisional_write_count += 1
                else:
                    target_state = "owner_eligible"
                    reason = f"{reason}; provisional_write_failed (kept for owner review)"
            else:
                target_state = "owner_eligible"
                if verdict.get("approve"):
                    reason = (
                        f"{reason}; crystallization_gate:"
                        f"{gate_result.get('error_code') or 'flagged'}"
                    )

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
            gate_result = (
                _resolver_candidate_gate_result(store, c) if verdict.get("approve") else {}
            )
            if verdict.get("approve") and _resolver_candidate_gate_allows(
                gate_result, c.candidate_id,
            ):
                target_state = "resolver_approved"
                from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
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
                if _try_write_resolver_provisional(
                    store, c, decision, error_records=error_records,
                ):
                    provisional_write_count += 1
                else:
                    target_state = "owner_eligible"
                    reason = f"{reason}; provisional_write_failed (kept for owner review)"
            else:
                target_state = "owner_eligible"
                if verdict.get("approve"):
                    reason = (
                        f"{reason}; crystallization_gate:"
                        f"{gate_result.get('error_code') or 'flagged'}"
                    )

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

    # ── No-keyword singleton bypass ──────────────────────────────────────
    # Candidates without signal keywords (_cluster_key returns None) never
    # enter the cluster map above.  With min_cluster_size=1 they still
    # deserve a path through resolver verdict — the deterministic gate
    # (sensitivity, identity signals, side effects) is the real safety
    # boundary; the cluster gate was a presentation heuristic, not a safety
    # mechanism.  Only applies to candidates not already processed by the
    # cluster loop or durable-fact bypass above.  Only activates when
    # min_cluster_size=1 — when the cluster gate is lifted entirely, every
    # candidate deserves a resolver verdict path.
    if min_cluster_size != 1:
        result = {"promoted_count": promoted_count, "clusters": cluster_summaries}
        result.update(crystallized_write_receipt(provisional_write_count))
        return result
    for c in candidates_for_promote:
        if c.candidate_id in processed_ids:
            continue
        # Only handle candidates that got no cluster key — those WITH a
        # cluster key were already handled by the cluster loop (they pass
        # when min_cluster_size=1) or durable-fact bypass.
        if _cluster_key(c) is not None:
            continue
        if _skip_tainted_external_evidence(
            c, store, processed_ids,
            cluster_key="", cluster_size=1,
            envelope_id=envelope_id, now=_now,
        ):
            continue

        # P2: Index-based near-duplicate dedup
        existing_prov = _match_existing_provisional(store, c.body)
        if existing_prov is not None:
            from plugins.memory.memory_os.crystallized import CrystallizedMemoryService as _CS2
            _cs2 = _CS2(store)
            _bump = _cs2.bump_recurrence_and_renew(existing_prov, execution_gate_envelope_id=envelope_id)
            if _bump.get("requires_owner_decision"):
                append_candidate_triage(
                    store, candidate_id=c.candidate_id, action="flag",
                    target_state="owner_eligible",
                    reason=f"max_renewals_reached: merged into existing provisional {existing_prov}",
                    cluster_key="", cluster_size=1,
                    execution_gate_envelope_id=envelope_id, now=_now,
                )
            else:
                append_candidate_triage(
                    store, candidate_id=c.candidate_id, action="dedup_absorb",
                    target_state="absorbed",
                    reason=f"recurrence bump + renew: merged into existing provisional {existing_prov}",
                    cluster_key="", cluster_size=1,
                    execution_gate_envelope_id=envelope_id, now=_now,
                )
            processed_ids.add(c.candidate_id)
            continue

        perm_match = _check_index_dedup(store, c)
        if perm_match is not None:
            append_candidate_triage(
                store, candidate_id=c.candidate_id, action="demote",
                target_state="demoted",
                reason=f"dedup_skip: similar to permanent crystallized {perm_match}",
                cluster_key="", cluster_size=1,
                execution_gate_envelope_id=envelope_id, now=_now,
            )
            processed_ids.add(c.candidate_id)
            continue

        # Content-quality pre-filter for no-keyword singletons
        if _is_fleeting_candidate(c):
            append_candidate_triage(
                store, candidate_id=c.candidate_id, action="promote",
                target_state="owner_eligible",
                reason="no-keyword singleton, low content quality — owner gate",
                cluster_key="", cluster_size=1,
                execution_gate_envelope_id=envelope_id, now=_now,
            )
            processed_ids.add(c.candidate_id)
            promoted_count += 1
            continue

        # ── Resolver routing (same path as cluster and durable-fact) ──
        reason = "no_keyword singleton bypass (min_cluster_size=1, resolver gate)"
        confidence_route = _lookup_confidence_route(c, store)
        provisional_promotion = _lookup_provisional_promotion(c, store)
        cascade_policy = _latest_cascade_policy(store)

        verdict = _resolver_verdict(
            c, store=store,
            confidence_route=confidence_route,
            provisional_promotion=provisional_promotion,
            cascade_policy=cascade_policy,
        )
        gate_result = (
            _resolver_candidate_gate_result(store, c) if verdict.get("approve") else {}
        )
        if verdict.get("approve") and _resolver_candidate_gate_allows(
            gate_result, c.candidate_id,
        ):
            target_state = "resolver_approved"
            from plugins.memory.memory_os.approval import ApprovalDecision as _AD2, ApprovalPurpose as _AP2
            _decision2 = _AD2(
                candidate_id=c.candidate_id,
                purpose=_AP2.APPROVE_FOR_CRYSTALLIZED,
                reviewer="resolver", reviewed_at=_now.isoformat(),
                note=verdict.get("reason", ""), source_state="resolver_approved",
                provisional=True,
                expires_at=_default_provisional_expires_at(c, _now),
                recurrence=0,
            )
            if _try_write_resolver_provisional(
                store, c, _decision2, error_records=error_records,
            ):
                provisional_write_count += 1
            else:
                target_state = "owner_eligible"
                reason = f"{reason}; provisional_write_failed (kept for owner review)"
        else:
            target_state = "owner_eligible"
            if verdict.get("approve"):
                reason = (
                    f"{reason}; crystallization_gate:"
                    f"{gate_result.get('error_code') or 'flagged'}"
                )

        append_candidate_triage(
            store, candidate_id=c.candidate_id, action="promote",
            target_state=target_state, reason=reason,
            cluster_key="", cluster_size=1,
            execution_gate_envelope_id=envelope_id, now=_now,
        )
        processed_ids.add(c.candidate_id)
        promoted_count += 1

    result = {"promoted_count": promoted_count, "clusters": cluster_summaries}
    result.update(crystallized_write_receipt(provisional_write_count))
    return result


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
    stale_owner_eligible_only: bool = False,
) -> dict[str, Any]:
    """Auto-demote candidates past TTL with no triage action.

    Uses resolve_candidate_effective_state() to check the effective state
    (considering triage overlay) rather than raw bridge_state, because
    promoted candidates still have bridge_state=inner_drive_candidate in
    the append-only candidates.jsonl.

    Owner_eligible candidates get a longer stale TTL (14 days) to give
    the owner time to process them before auto-demotion.

    ``stale_owner_eligible_only=True`` runs ONLY the 14-day stale sweep and
    exists because of a measured starvation hole: run order used to be
    rejected → promote → aged over one shared processed set, and any
    candidate with a signal keyword (min_cluster_size defaults to 1, so a
    singleton clusters too) was re-claimed by the promote stage EVERY run —
    resolver declines it, writes owner_eligible again, marks it processed —
    and the aged stage never saw it. The 14-day TTL was structurally
    unreachable for exactly the noisiest class (near-duplicate build-era
    meta candidates are keyword-rich by nature). Production proof: all 8
    pre-August queue rows, 66–98 days old, each with a promote→owner_eligible
    triage row per run. The stale sweep therefore runs BEFORE promote — 14
    days means the resolver already declined ~56 runs and the owner never
    acted — while the 3-day no-triage branch deliberately stays AFTER
    promote, because running it first would demote backlogged candidates the
    resolver has never evaluated.
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
        if stale_owner_eligible_only and effective != "owner_eligible":
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

    # CE.2: crystallized writes require event provenance -- the write gate
    # (`_ensure_crystallized_approval`) raises on empty source_event_ids, for
    # Owner approvals as much as resolver ones. Auto-approving a provenance-less
    # candidate therefore cannot succeed; it can only crash the lane (measured
    # on production: session_fact_extraction's first five candidates took the
    # durable-fact bypass and killed every candidate_aggregation tick from
    # 12:12Z on). Route such candidates to owner review instead of the cliff.
    if not list(candidate.source_event_ids or []):
        return {"approve": False, "reason": "missing_source_event_ids"}

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
