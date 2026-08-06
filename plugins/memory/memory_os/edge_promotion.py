"""Edge promotion lane — the candidate→owner_eligible governance channel (W3/E1).

Before this module existed the edge state machine had a dead middle stage:
all three proposers wrote ``candidate`` (llm auto-active types excepted), the
owner digest rendered only ``owner_eligible``, and NOTHING transitioned an
edge between the two — 2118 production candidates accumulated with no outlet
and the owner never saw a single edge review item.

Runs as a cognitive-loop step (not a cron lane — no registry snapshot to
regenerate).  Per run, bounded:

  1. promote the top ``PROMOTE_PER_RUN`` candidates (weight desc, created_at
     asc) to ``owner_eligible`` — durable via W0's canonical write-back;
  2. TTL: invalidate up to ``TTL_MAX_PER_RUN`` candidates older than
     ``CANDIDATE_TTL_DAYS`` (the un-promoted tail must not grow forever —
     mirrors the candidate queue's auto-demote pattern, G3 invalidate-not-
     delete).

Completion Is Not Output: the result always carries a closed ``outcome``
(``promoted`` / ``no_candidates`` / ``error``) plus production counters, so a
reader can tell "no eligible input" from "processing failed" without re-running.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from .audit import append_audit

# Governance vocabulary — pinned by the bidirectional guard test together
# with owner_actions.EDGE_REVIEW_DIGEST_STATE and
# prefetch.GRAPH_INJECTION_EDGE_STATE (W3 词表双向守卫).
PROMOTION_SOURCE_STATE = "candidate"
PROMOTION_TARGET_STATE = "owner_eligible"

# Per-run bounds: the digest shows top-10, so promoting 10 per cognitive-loop
# cycle (6h cadence → ≤40/day) keeps the owner queue readable.
PROMOTE_PER_RUN = 10
CANDIDATE_TTL_DAYS = 30
TTL_MAX_PER_RUN = 100


def run_edge_promotion(
    index_path: str,
    *,
    index: object | None = None,
    audit_path: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Promote top candidates and TTL-invalidate the stale tail.

    Returns a summary dict with closed outcome + production counters.
    """
    from .index import transition_edge_state

    start_time = datetime.now(timezone.utc)
    current = (now or start_time).astimezone(timezone.utc)

    roots = getattr(index, "roots", None)
    if roots is None:
        return {
            "status": "error",
            "outcome": "error",
            "error": "index_with_roots_required",
            "promoted_count": 0,
            "ttl_invalidated_count": 0,
        }

    try:
        conn = sqlite3.connect(index_path)
    except sqlite3.Error:
        return {
            "status": "error",
            "outcome": "error",
            "error": f"cannot_open_index: {index_path}",
            "promoted_count": 0,
            "ttl_invalidated_count": 0,
        }

    promoted = 0
    ttl_invalidated = 0
    failed = 0
    candidate_count = 0
    try:
        try:
            candidate_count = int(conn.execute(
                "select count(*) from memory_edges where state = ?",
                (PROMOTION_SOURCE_STATE,),
            ).fetchone()[0])
        except sqlite3.Error:
            return {
                "status": "error",
                "outcome": "error",
                "error": "cannot_read_memory_edges",
                "promoted_count": 0,
                "ttl_invalidated_count": 0,
            }

        if candidate_count:
            # ── 1. Promote top candidates ──────────────────────────────
            rows = conn.execute(
                "select edge_id from memory_edges where state = ?"
                " order by weight desc, created_at asc, edge_id asc limit ?",
                (PROMOTION_SOURCE_STATE, PROMOTE_PER_RUN),
            ).fetchall()
            for (edge_id,) in rows:
                result = transition_edge_state(
                    conn, str(edge_id), PROMOTION_TARGET_STATE, roots=roots,
                )
                if result and result.get("state") == PROMOTION_TARGET_STATE:
                    promoted += 1
                else:
                    failed += 1

            # ── 2. TTL sweep on the remaining candidate tail ───────────
            cutoff = (current - timedelta(days=CANDIDATE_TTL_DAYS)).isoformat()
            stale = conn.execute(
                "select edge_id from memory_edges where state = ?"
                " and created_at < ? order by created_at asc limit ?",
                (PROMOTION_SOURCE_STATE, cutoff, TTL_MAX_PER_RUN),
            ).fetchall()
            for (edge_id,) in stale:
                result = transition_edge_state(
                    conn, str(edge_id), "invalidated", roots=roots,
                )
                if result and result.get("state") == "invalidated":
                    ttl_invalidated += 1
                else:
                    failed += 1
    finally:
        conn.close()

    if candidate_count == 0:
        outcome = "no_candidates"
    elif failed and not promoted and not ttl_invalidated:
        outcome = "error"
    else:
        outcome = "promoted"

    elapsed_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
    summary = {
        "status": "ok" if outcome != "error" else "error",
        "outcome": outcome,
        "candidate_count": candidate_count,
        "promoted_count": promoted,
        "ttl_invalidated_count": ttl_invalidated,
        "failed_count": failed,
        "duration_ms": elapsed_ms,
        "begin_at": start_time.isoformat(),
    }

    if audit_path:
        from pathlib import Path
        append_audit(
            Path(audit_path),
            action="edge_promotion_run",
            status=summary["status"],
            target=str(index_path),
            details=summary,
        )

    return summary
