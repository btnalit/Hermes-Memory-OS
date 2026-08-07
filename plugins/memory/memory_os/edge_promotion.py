"""Edge promotion lane — the backlog AUTO-ACTIVATION channel (R2).

History: W3 built this as a candidate→owner_eligible review pipeline (E1
closed the dead-middle-stage defect).  The owner then ruled (2026-08-06):
「动态图谱应该是动态去更新关系的…不需要人工介入」— the graph is a derived
advisory projection; per-edge review is the wrong governance model.  R1 made
every proposer emit ``active`` directly; this lane's remaining job is the
BACKLOG: legacy ``candidate`` / ``owner_eligible`` edges are auto-activated
in weight order, bounded per run (a one-shot flood would pour the legacy
refines hairball into the injection pool), while the TTL sweep forgets the
stale tail (G3 invalidate-not-delete).  Wrong edges are demoted by the
weight-feedback loop (edge_weight_feedback), not by owner review;
``reject_edge`` stays available as an owner correction tool.

Runs as a cognitive-loop step (not a cron lane — no registry snapshot to
regenerate).

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
# with prefetch.GRAPH_INJECTION_EDGE_STATE (R2 词表双向守卫).
# owner_eligible is a LEGACY state (no producer since R1); this channel
# drains it alongside candidate.
PROMOTION_SOURCE_STATES = ("candidate", "owner_eligible")
PROMOTION_TARGET_STATE = "active"

# Per-run bounds: 25/run × 4 runs/day + TTL 100/run drains the ~1300-edge
# legacy backlog within days while the weight order keeps the best edges
# entering the injection pool first.
PROMOTE_PER_RUN = 25
CANDIDATE_TTL_DAYS = 30
TTL_MAX_PER_RUN = 100


def run_edge_promotion(
    index_path: str,
    *,
    index: object | None = None,
    audit_path: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Auto-activate top backlog edges and TTL-invalidate the stale tail (R2).

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
    _source_placeholders = ",".join("?" * len(PROMOTION_SOURCE_STATES))
    try:
        try:
            candidate_count = int(conn.execute(
                f"select count(*) from memory_edges where state in ({_source_placeholders})",
                PROMOTION_SOURCE_STATES,
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
            # ── 1. Auto-activate top backlog edges (weight order) ──────
            rows = conn.execute(
                f"select edge_id from memory_edges where state in ({_source_placeholders})"
                " order by weight desc, created_at asc, edge_id asc limit ?",
                (*PROMOTION_SOURCE_STATES, PROMOTE_PER_RUN),
            ).fetchall()
            for (edge_id,) in rows:
                result = transition_edge_state(
                    conn, str(edge_id), PROMOTION_TARGET_STATE, roots=roots,
                )
                if result and result.get("state") == PROMOTION_TARGET_STATE:
                    promoted += 1
                else:
                    failed += 1

            # ── 2. TTL sweep on the remaining backlog tail ─────────────
            cutoff = (current - timedelta(days=CANDIDATE_TTL_DAYS)).isoformat()
            stale = conn.execute(
                f"select edge_id from memory_edges where state in ({_source_placeholders})"
                " and created_at < ? order by created_at asc limit ?",
                (*PROMOTION_SOURCE_STATES, cutoff, TTL_MAX_PER_RUN),
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
