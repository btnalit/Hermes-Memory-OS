"""Deterministic structural edge proposer for crystallized↔crystallized relationships.

Runs as a cognitive-loop step. Reads active crystallized records from the
index, applies deterministic heuristics, and writes LIVE edges
(state=active, proposed_by=structural) — R1 (owner 决策 2026-08-06):动态
图谱全自动,边是派生投影,错误的边由权重反馈闭环动态淘汰,不占用
owner 审批带宽。

Relation vocabulary (W1/E2): structural similarity can prove that two
records are RELATED, never HOW they relate semantically — so this proposer
emits ``co_occurs`` (shared provenance, body similarity, temporal proximity)
plus ``depends_on`` only for an explicit record-id reference (a hard
structural fact, not a similarity guess).  ``refines`` and ``contradicts``
are reserved for the LLM proposer, which actually reads the content.

PR-G1 (owner-ruled 2026-09-23) adds one more deterministic label: ``updates``
(newer record → older record, direction by ``created_at``) fires only for a
near-verbatim restatement — Dice ≥ θ_high (0.85, well above the 0.30
co_occurs floor) AND the same ``kind`` (kind guard). It is not a similarity
guess about semantic *change*: 0.50–0.85 ("changed my mind" paraphrases) is
reserved for a future LLM label. See ``run_structural_updates_backfill`` for
the bounded pass that upgrades pre-existing co_occurs pairs that would now
qualify (otherwise old duplicates never get re-examined once a structural
edge already exists for that pair).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from .audit import append_audit
from .edge_weights import birth_weight
from .jsonl_io import build_error_record, write_json_atomic
from .timeutil import ensure_utc_aware


# Dice coefficient threshold for body-text similarity — above this the pair
# is considered structurally related (co_occurs).
_DICE_THRESHOLD = 0.30

# θ_high (PR-G1, owner-ruled 2026-09-23): above this AND same-kind, a pair is
# a near-verbatim restatement — deterministic `updates`, not co_occurs. The
# 0.50–0.85 band is reserved for a future LLM label (paraphrase-level
# "changed my mind" detection); the deterministic proposer never claims it.
_DICE_THRESHOLD_UPDATES = 0.85

# Temporal proximity for co_occurs / loose refines (seconds).
_TEMPORAL_WINDOW_SECONDS = 3600

# Max crystallized pairs to examine per cycle (guard out-degree explosion).
_MAX_PAIRS = 200


# ── Body-text helpers ──────────────────────────────────────────────────────


def _dice_coefficient(a: str, b: str) -> float:
    """Dice coefficient for two strings based on bigram overlap."""
    bigrams_a = {a[i:i+2] for i in range(len(a) - 1)}
    bigrams_b = {b[i:i+2] for i in range(len(b) - 1)}
    if not bigrams_a or not bigrams_b:
        return 0.0
    intersection = bigrams_a & bigrams_b
    return 2.0 * len(intersection) / (len(bigrams_a) + len(bigrams_b))


def _contains_record_ref(body: str, record_id: str) -> bool:
    """Check if body text contains a reference to the given record_id."""
    return record_id in body


def _parse_iso(ts: str) -> datetime | None:
    """Parse an ISO timestamp string, best-effort.

    Naive (no-offset) timestamps parse without error but, if left naive,
    raise TypeError when subtracted from another parsed value of differing
    awareness in `_detect_relation`'s temporal-proximity check (two
    crystallized records whose `created_at` differ in naive/aware-ness).
    Normalize to UTC here, same as knob_overrides._is_expired, so every
    value this helper returns is safely comparable.
    """
    if not ts:
        return None
    try:
        parsed = datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None
    return ensure_utc_aware(parsed)


def _detect_relation(
    record_a: dict[str, Any],
    record_b: dict[str, Any],
) -> list[dict[str, Any]]:
    """Apply deterministic heuristics to a pair of crystallized records.

    Returns a list of candidate edge dicts (may be empty).
    Each edge dict has the keys expected by write_governed_edge().
    """
    edges: list[dict[str, Any]] = []

    rid_a = str(record_a.get("id", ""))
    rid_b = str(record_b.get("id", ""))
    if not rid_a or not rid_b:
        return []
    if rid_a == rid_b:
        return []

    body_a = str(record_a.get("body", "") or record_a.get("summary", ""))
    body_b = str(record_b.get("body", "") or record_b.get("summary", ""))
    kind_a = str(record_a.get("kind", ""))
    kind_b = str(record_b.get("kind", ""))

    # ── updates: near-verbatim restatement, same kind (PR-G1) ───────────
    # Checked BEFORE every co_occurs-producing branch below (shared_events,
    # depends_on, body-similarity, temporal): write_governed_edge's boundary
    # dedup treats a structural link between two records as ONE fact
    # regardless of relation label ("structural dedups per unordered PAIR"),
    # so whichever relation this function returns first is the one that
    # survives — before this check, co_occurs always won by construction,
    # which is exactly the bug PR-G1 fixes (production measured 313 pairs on
    # main / 29 on sannai of near-verbatim crystallized duplicates that were
    # only ever labelled co_occurs). `updates` requires a materially higher
    # similarity bar (θ_high=0.85 vs the co_occurs floor of 0.30) AND the
    # same `kind` (kind guard — a preference and a fact can be textually
    # near-identical without one superseding the other), AND a determinable
    # direction (both `created_at` values parse and differ — see
    # `_parse_iso`). When any of those fail, this pair falls through to the
    # ordinary checks below unchanged (a ≥0.85 dice pair is still ≥0.30, so
    # it is not lost — merely not labelled as a version relationship).
    # This also precedes depends_on on purpose: prefetch's latest-wins
    # suppression keys on relation_type == "updates" alone, so a newer record
    # that cites the older one's id (the strongest supersession evidence)
    # would otherwise lose latest-wins by being labelled depends_on.
    dice = _dice_coefficient(body_a, body_b)
    if dice >= _DICE_THRESHOLD_UPDATES and kind_a and kind_a == kind_b:
        ts_a = _parse_iso(str(record_a.get("created_at", "")))
        ts_b = _parse_iso(str(record_b.get("created_at", "")))
        if ts_a and ts_b and ts_a != ts_b:
            newer_id, older_id = (rid_a, rid_b) if ts_a > ts_b else (rid_b, rid_a)
            return [{
                "from_record_type": "crystallized_record",
                "from_record_id": newer_id,
                "to_record_type": "crystallized_record",
                "to_record_id": older_id,
                "relation_type": "updates",
                "weight": birth_weight("structural", "updates_restatement"),
                "source_event_id": None,
                "proposed_by": "structural",
                "state": "active",
            }]

    tags_a = record_a.get("tags_json", []) or []
    tags_b = record_b.get("tags_json", []) or []
    if isinstance(tags_a, str):
        try:
            tags_a = json.loads(tags_a)
        except (json.JSONDecodeError, TypeError):
            tags_a = [tags_a] if tags_a else []
    if isinstance(tags_b, str):
        try:
            tags_b = json.loads(tags_b)
        except (json.JSONDecodeError, TypeError):
            tags_b = [tags_b] if tags_b else []
    tags_a = list(tags_a)
    tags_b = list(tags_b)

    source_events_a = record_a.get("source_event_ids_json", []) or []
    source_events_b = record_b.get("source_event_ids_json", []) or []
    if isinstance(source_events_a, str):
        try:
            source_events_a = json.loads(source_events_a)
        except (json.JSONDecodeError, TypeError):
            source_events_a = [source_events_a] if source_events_a else []
    if isinstance(source_events_b, str):
        try:
            source_events_b = json.loads(source_events_b)
        except (json.JSONDecodeError, TypeError):
            source_events_b = [source_events_b] if source_events_b else []
    source_events_a = list(source_events_a)
    source_events_b = list(source_events_b)

    # ── Shared source_event → co_occurs (shared provenance is
    # co-occurrence, not refinement — semantic labels are the LLM's job) ──
    shared_events = set(source_events_a) & set(source_events_b)
    if shared_events:
        shared_event = next(iter(shared_events)) if shared_events else ""
        edges.append({
            "from_record_type": "crystallized_record",
            "from_record_id": rid_a,
            "to_record_type": "crystallized_record",
            "to_record_id": rid_b,
            "relation_type": "co_occurs",
            "weight": birth_weight("structural", "shared_source_event"),
            "source_event_id": shared_event,
            "proposed_by": "structural",
            "state": "active",
        })

    # ── depends_on: one body explicitly references the other's ID ──
    if _contains_record_ref(body_a, rid_b) or _contains_record_ref(body_b, rid_a):
        from_id = rid_a if _contains_record_ref(body_a, rid_b) else rid_b
        to_id = rid_b if _contains_record_ref(body_a, rid_b) else rid_a
        edges.append({
            "from_record_type": "crystallized_record",
            "from_record_id": from_id,
            "to_record_type": "crystallized_record",
            "to_record_id": to_id,
            "relation_type": "depends_on",
            "weight": birth_weight("structural", "explicit_reference"),
            "source_event_id": None,
            "proposed_by": "structural",
            "state": "active",
        })

    # ── Body similarity → co_occurs (W1/E2: token overlap proves
    # relatedness, not refinement/contradiction — those need the LLM).
    # `dice` was already computed above for the updates check; a pair that
    # cleared θ_high but fell through (kind mismatch / no direction) is
    # still ≥ _DICE_THRESHOLD here, so it still gets co_occurs. ──
    if dice >= _DICE_THRESHOLD:
        rtype = "co_occurs"
        # Only write if we haven't already via source_event or depends_on
        has_same = any(
            e["relation_type"] == rtype
            and e["from_record_id"] == rid_a
            and e["to_record_id"] == rid_b
            for e in edges
        )
        if not has_same:
            edges.append({
                "from_record_type": "crystallized_record",
                "from_record_id": rid_a,
                "to_record_type": "crystallized_record",
                "to_record_id": rid_b,
                "relation_type": rtype,
                "weight": birth_weight("structural", "body_similarity"),
                "source_event_id": None,
                "proposed_by": "structural",
                "state": "active",
            })

    # ── Temporal proximity → co_occurs ──
    ts_a = _parse_iso(str(record_a.get("created_at", "")))
    ts_b = _parse_iso(str(record_b.get("created_at", "")))
    if ts_a and ts_b:
        delta = abs((ts_a - ts_b).total_seconds())
        if 0 < delta < _TEMPORAL_WINDOW_SECONDS and not edges:
            edges.append({
                "from_record_type": "crystallized_record",
                "from_record_id": rid_a,
                "to_record_type": "crystallized_record",
                "to_record_id": rid_b,
                "relation_type": "co_occurs",
                "weight": birth_weight("structural", "temporal_proximity"),
                "source_event_id": None,
                "proposed_by": "structural",
                "state": "active",
            })

    return edges


def _order_records_unedged_first(
    records: list[dict[str, Any]],
    index_path: str,
    *,
    proposed_by: str = "structural",
) -> list[dict[str, Any]]:
    """Stable partition: records without a non-invalidated edge from this
    proposer class first.

    Coverage is judged per proposer (``proposed_by``) — an llm edge on a
    record must not push it behind the head records the structural reorder
    exists to starve out, and vice versa.  Fail-open: on any query error the
    input order is returned.
    """
    edged: set[str] = set()
    try:
        conn = sqlite3.connect(index_path)
        try:
            rows = conn.execute(
                "select from_record_id, to_record_id from memory_edges"
                " where state != 'invalidated' and proposed_by = ?",
                (proposed_by,),
            ).fetchall()
        finally:
            conn.close()
        for a, b in rows:
            edged.add(str(a))
            edged.add(str(b))
    except sqlite3.Error:
        return records
    unedged = [r for r in records if str(r.get("id", "")) not in edged]
    rest = [r for r in records if str(r.get("id", "")) in edged]
    return unedged + rest


# Bounded per-run cap for the updates backfill pass — mirrors G0's
# ORPHAN_CASCADE_MAX_PER_RUN pattern (edge_weight_feedback.py) so a large
# pre-existing backlog converges over several cron cycles instead of
# scanning/rewriting unboundedly in one run.
UPDATES_BACKFILL_MAX_PER_RUN = 200
UPDATES_BACKFILL_STATE_FILENAME = "structural_updates_backfill_state.json"
# Closed set for `backfill_outcome` (Completion Is Not Output): the two
# *_failed values are the runs the monitor grades even when no count moved.
UPDATES_BACKFILL_OUTCOMES = frozenset({"completed", "no_roots", "scan_failed", "resolve_failed"})


def _backfill_state_path(roots: Any):
    return roots.memory_os_root / "system" / UPDATES_BACKFILL_STATE_FILENAME


def _load_backfill_cursor(roots: Any) -> tuple[str, str]:
    try:
        data = json.loads(_backfill_state_path(roots).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "", ""
    if not isinstance(data, dict):
        return "", ""
    return str(data.get("cursor_created_at") or ""), str(data.get("cursor_edge_id") or "")


def run_structural_updates_backfill(
    index_path: str,
    *,
    index: object | None = None,
    max_per_run: int = UPDATES_BACKFILL_MAX_PER_RUN,
) -> dict[str, Any]:
    """Bounded, idempotent upgrade of pre-existing ``co_occurs`` pairs that
    now qualify as ``updates`` (PR-G1, owner-ruled 2026-09-23).

    Why this exists: ``write_governed_edge``'s boundary dedup allows at most
    one active structural edge per unordered pair — "a structural link
    between two records is one fact regardless of relation label". Once a
    pair already carries a ``co_occurs`` edge from a prior cycle, the main
    proposer pass above will never re-examine it: the pair is "edged" and
    ``_order_records_unedged_first`` pushes it toward the tail, which the
    per-cycle ``max_pairs`` budget rarely reaches for a large corpus.
    Without this backfill, every pair written BEFORE PR-G1 shipped would
    stay ``co_occurs`` forever, no matter how many cycles run afterward
    (production measured 313 qualifying pairs on main, 29 on sannai).

    For a bounded batch of active, structural, ``co_occurs`` edges: resolve
    both endpoints' kind/body/created_at from the same
    ``crystallized_records`` + ``memory_fts`` projection the main pass reads
    above (this is a scoring read, not the orphan cascade's existence/
    liveness judgment — G0's "canonical files are the only authority for
    invalidation" rule governs that different, fail-closed decision). If the
    pair now qualifies (``_detect_relation`` returns an ``updates`` edge for
    it), the old ``co_occurs`` edge is invalidated and the new ``updates``
    edge is written. Idempotent by construction: once converted, the pair's
    relation_type is no longer ``co_occurs``, so it naturally drops out of
    this function's own candidate query on the next run.

    A pair that does NOT qualify stays ``co_occurs`` forever, so a plain
    ``order by created_at limit N`` would re-scan the same oldest N
    non-qualifying edges every cycle and never reach anything newer --
    co_occurs is ~85% of production's active edges, far more than one
    batch. A durable keyset cursor over (created_at, edge_id)
    (``system/structural_updates_backfill_state.json``) advances past every
    scanned edge, qualifying or not; edges born after the cursor are picked
    up as the scan reaches them.

    The cursor assumes ``created_at`` grows with insertion order (one writer
    per profile, ``write_governed_edge`` stamps it at write time). An edge
    written with a ``created_at`` behind the cursor — clock skew, or a repair
    that reconstructs timestamps — is never revisited; deleting the state
    file restarts the scan from the beginning.
    """
    from .index import transition_edge_state as _transition_edge_state
    from .index import write_governed_edge as _write_governed_edge

    start_time = datetime.now(timezone.utc)
    roots = getattr(index, "roots", None)
    if roots is None:
        # No durable-write authority available (see write_governed_edge's
        # roots contract) — a no-op-shaped skip, not an error: callers that
        # pass index=None get exactly this from the main pass too.
        return {
            "backfill_scanned_count": 0,
            "backfill_upgraded_count": 0,
            "backfill_skipped_count": 0,
            "backfill_failed_count": 0,
            "backfill_pass_complete": False,
            "backfill_outcome": "no_roots",
            "backfill_duration_ms": 0,
            "backfill_error_records": [],
        }

    cursor_created_at, cursor_edge_id = _load_backfill_cursor(roots)
    conn = sqlite3.connect(index_path)
    conn.row_factory = sqlite3.Row
    error_records: list[dict[str, Any]] = []
    try:
        candidates = conn.execute(
            "select edge_id, from_record_id, to_record_id, coalesce(created_at, '') as created_at"
            " from memory_edges"
            " where state = 'active' and proposed_by = 'structural'"
            " and relation_type = 'co_occurs'"
            " and (coalesce(created_at, '') > ? or (coalesce(created_at, '') = ? and edge_id > ?))"
            " order by coalesce(created_at, ''), edge_id limit ?",
            (cursor_created_at, cursor_created_at, cursor_edge_id, max_per_run),
        ).fetchall()
    except sqlite3.Error as exc:
        conn.close()
        return {
            "backfill_scanned_count": 0,
            "backfill_upgraded_count": 0,
            "backfill_skipped_count": 0,
            "backfill_failed_count": 0,
            "backfill_pass_complete": False,
            # Nothing could be scanned, so there is no count to put in
            # backfill_failed_count; without this code the run reads exactly
            # like an idle one (scanned=0).
            "backfill_outcome": "scan_failed",
            "backfill_duration_ms": int(
                (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
            ),
            "backfill_error_records": [
                build_error_record(
                    component="structural_edge_proposer",
                    operation="updates_backfill_scan",
                    error_code="sqlite_read_failed",
                    severity="warning",
                    recoverable=True,
                    details={"error_type": type(exc).__name__},
                )
            ],
        }

    scanned = len(candidates)
    upgraded = 0
    # skipped = the pair does not qualify (or an endpoint is gone): benign.
    # failed = the pair qualified but the upgrade did not complete — kept
    # apart because the second failure branch below can leave a pair with no
    # active structural edge at all, which must never read as a benign skip.
    skipped = 0
    failed = 0

    referenced_ids: set[str] = set()
    for row in candidates:
        referenced_ids.add(str(row["from_record_id"]))
        referenced_ids.add(str(row["to_record_id"]))

    records_by_id: dict[str, dict[str, Any]] = {}
    if referenced_ids:
        placeholders = ",".join("?" * len(referenced_ids))
        try:
            rows = conn.execute(
                f"select * from crystallized_records where id in ({placeholders})",
                tuple(referenced_ids),
            ).fetchall()
            for r in rows:
                records_by_id[str(r["id"])] = dict(r)
            for rid, rec in records_by_id.items():
                body_row = conn.execute(
                    "select text from memory_fts where record_type = 'crystallized_record'"
                    " and record_id = ?",
                    (rid,),
                ).fetchone()
                if body_row:
                    rec["body"] = str(body_row["text"])
        except sqlite3.Error as exc:
            conn.close()
            # Nothing was mutated and the cursor is not advanced, so the same
            # batch is retried next run — but it is a failure, not a skip.
            return {
                "backfill_scanned_count": scanned,
                "backfill_upgraded_count": 0,
                "backfill_skipped_count": 0,
                "backfill_failed_count": scanned,
                "backfill_pass_complete": False,
                "backfill_outcome": "resolve_failed",
                "backfill_duration_ms": int(
                    (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
                ),
                "backfill_error_records": [
                    build_error_record(
                        component="structural_edge_proposer",
                        operation="updates_backfill_resolve_records",
                        error_code="sqlite_read_failed",
                        severity="warning",
                        recoverable=True,
                        details={"error_type": type(exc).__name__},
                    )
                ],
            }

    for row in candidates:
        edge_id = str(row["edge_id"])
        rid_a = str(row["from_record_id"])
        rid_b = str(row["to_record_id"])
        record_a = records_by_id.get(rid_a)
        record_b = records_by_id.get(rid_b)
        if record_a is None or record_b is None:
            # Endpoint no longer in crystallized_records at all — not this
            # lane's job (the orphan cascade in edge_weight_feedback.py owns
            # that fail-closed invalidation decision).
            skipped += 1
            continue
        candidate_edges = _detect_relation({**record_a, "id": rid_a}, {**record_b, "id": rid_b})
        updates_edge = next(
            (e for e in candidate_edges if e["relation_type"] == "updates"), None
        )
        if updates_edge is None:
            skipped += 1
            continue
        # Invalidate the old co_occurs edge BEFORE writing the new one: the
        # write boundary's structural pair-dedup only allows a write when no
        # non-invalidated structural edge already exists for this unordered
        # pair (see write_governed_edge's W1 dedup authority comment).
        pair_details = {"edge_id": edge_id, "from_record_id": rid_a, "to_record_id": rid_b}
        invalidated = _transition_edge_state(
            conn, edge_id, "invalidated", roots=roots,
            reason="superseded_by_update_detection",
        )
        if not invalidated or invalidated.get("state") != "invalidated":
            # `{}` covers two durable outcomes: the canonical append failed
            # (nothing changed, but the cursor still moves past this edge, so
            # the pair stays co_occurs until a later pass), or the canonical
            # row landed and only the projection update failed (the next
            # index_sync invalidates it with no `updates` edge written).
            failed += 1
            error_records.append(build_error_record(
                component="structural_edge_proposer",
                operation="updates_backfill_invalidate",
                error_code="edge_transition_failed",
                severity="warning",
                recoverable=True,
                details=pair_details,
            ))
            continue
        written = _write_governed_edge(conn, roots, **updates_edge)
        if written and not written.get("skipped_duplicate") and written.get("edge_id"):
            upgraded += 1
        elif written.get("skipped_duplicate"):
            # A second non-invalidated structural edge (a pre-E2 duplicate)
            # still links the pair, so it is not left unlinked.
            skipped += 1
        else:
            # Invalidation is a one-way door (EDGE_STATE_TRANSITIONS
            # ["invalidated"] is empty) and the pair dedup forbids writing the
            # replacement first, so this cannot be made atomic. The pair may
            # now have NO active structural edge; the ids in details are what
            # lets an operator find it.
            failed += 1
            error_records.append(build_error_record(
                component="structural_edge_proposer",
                operation="updates_backfill_write",
                error_code="edge_write_failed",
                severity="error",
                recoverable=False,
                details=pair_details,
            ))

    conn.close()
    if candidates:
        last = candidates[-1]
        try:
            write_json_atomic(_backfill_state_path(roots), {
                "schema_version": "memory-os.structural_updates_backfill_state.v0",
                "cursor_created_at": str(last["created_at"]),
                "cursor_edge_id": str(last["edge_id"]),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
        except OSError as exc:
            error_records.append(build_error_record(
                component="structural_edge_proposer",
                operation="updates_backfill_cursor_write",
                error_code="state_write_failed",
                severity="warning",
                recoverable=True,
                details={"error_type": type(exc).__name__},
            ))
    return {
        "backfill_scanned_count": scanned,
        "backfill_upgraded_count": upgraded,
        "backfill_skipped_count": skipped,
        "backfill_failed_count": failed,
        "backfill_pass_complete": scanned < max_per_run,
        "backfill_outcome": "completed",
        "backfill_duration_ms": int(
            (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
        ),
        "backfill_error_records": error_records,
    }


# ── Proposer runner ────────────────────────────────────────────────────────


def run_structural_proposer(
    index_path: str,
    *,
    index: object | None = None,
    audit_path: str | None = None,
    max_pairs: int = _MAX_PAIRS,
) -> dict[str, Any]:
    """Read crystallized records and propose edges between them.

    Args:
        index_path: Path to the index DB.
        index: Optional MemoryOSIndex instance (for writing edges).
               If None, creates a fresh one (needs roots).
        audit_path: Optional audit path.

    Returns a summary dict with counts of proposed edges.
    """
    start_time = datetime.now(timezone.utc)

    # Read active crystallized records from the index.
    conn = sqlite3.connect(index_path)
    conn.row_factory = sqlite3.Row
    try:
        records_raw = conn.execute(
            "select * from crystallized_records order by created_at"
        ).fetchall()
    except sqlite3.Error:
        return {"status": "error", "error": "cannot_read_crystallized_records"}
    finally:
        conn.close()

    records: list[dict[str, Any]] = [dict(r) for r in records_raw]
    if len(records) < 2:
        return {
            "status": "skipped",
            "reason": f"need ≥2 crystallized records, got {len(records)}",
            "proposed_count": 0,
            "pair_count": 0,
        }

    # Enrich records with body text from FTS5 index (crystallized_records
    # table has no body column — it comes from the FTS projection).
    conn2 = sqlite3.connect(index_path)
    conn2.row_factory = sqlite3.Row
    try:
        for rec in records:
            rid = str(rec.get("id", ""))
            if not rid:
                continue
            row = conn2.execute(
                "select text from memory_fts where record_type = 'crystallized_record' and record_id = ?",
                (rid,),
            ).fetchone()
            if row:
                rec["body"] = str(row["text"])
    except sqlite3.Error:
        pass  # fail-open — body enrichment is best-effort
    finally:
        conn2.close()

    # Build all unordered pairs.
    pairs = 0
    proposed = 0
    boundary_dedup_skipped = 0
    write_failed = 0
    dedup_keys: set[str] = set()

    # ── W1/E3 pair de-bias: unedged records first ──────────────────────
    # The old created_at-ascending order let the oldest ~20 records consume
    # the entire max_pairs budget every run (production: top-5 hubs were all
    # same-day records carrying 189–275 edges each) while newer records never
    # got a single structural edge.  Records without any non-invalidated
    # structural edge are examined first; within each group the created_at
    # order is preserved (stable).  Dedup itself now lives at the write
    # boundary (index.write_governed_edge) — the previous query_edges
    # pre-check here was capped at limit=1000 and silently defeated once the
    # backlog crossed that cap.
    records = _order_records_unedged_first(records, index_path)

    for i in range(len(records)):
        if pairs >= max_pairs:
            break
        for j in range(i + 1, len(records)):
            if pairs >= max_pairs:
                break
            pairs += 1
            candidates = _detect_relation(records[i], records[j])
            for candidate in candidates:
                dedup_key = (
                    f"{candidate['from_record_id']}:"
                    f"{candidate['to_record_id']}:"
                    f"{candidate['relation_type']}"
                )
                if dedup_key in dedup_keys:
                    continue
                dedup_keys.add(dedup_key)
                if index and hasattr(index, "write_governed_edge"):
                    result = index.write_governed_edge(**candidate)
                    if result.get("skipped_duplicate"):
                        boundary_dedup_skipped += 1
                    elif result:
                        proposed += 1
                    else:
                        write_failed += 1

    elapsed_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)

    # ── PR-G1 bounded backfill: upgrade pre-existing co_occurs pairs that
    # now qualify as `updates`. Runs every cycle (bounded, idempotent — see
    # run_structural_updates_backfill's docstring) because the pair-scanning
    # loop above can never reach an already-edged pair on its own. ────────
    backfill_result = run_structural_updates_backfill(index_path, index=index)

    summary = {
        "status": "ok",
        "record_count": len(records),
        "pair_count": pairs,
        "proposed_count": proposed,
        "dedup_skipped": boundary_dedup_skipped,
        "write_failed_count": write_failed,
        "duration_ms": elapsed_ms,
        "begin_at": start_time.isoformat(),
        # Spread, not hand-listed: the hand list dropped backfill_pass_complete,
        # so every consumer read the wrapper's False default.
        **backfill_result,
    }

    if audit_path:
        from pathlib import Path
        append_audit(
            Path(audit_path),
            action="structural_edge_proposer_run",
            status="ok",
            target=str(index_path),
            details=summary,
        )

    return summary
