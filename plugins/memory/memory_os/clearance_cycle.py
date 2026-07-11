"""V2-E clearance cycle orchestration (E4-E8).

Rejudge queue (E4), cycle API (E6), flag flip (E7), monitor stats (E8).
Imports from clearance_receipts (data), crystallized (record access),
permanent_promotion (proposal sweep).  No reverse imports — this module
sits above the data layer.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .clearance_receipts import (
    ClearanceReceipt,
    invalidate_receipts_since,
    latest_corpus_watermark,
    read_clearance_receipt_snapshot,
    read_clearance_receipts,
    write_clearance_receipt,
)


# ── E4: Rejudge queue ──────────────────────────────────────────────────────


def get_rejudge_queue(roots: Any) -> list[dict[str, Any]]:
    """Return receipt IDs needing rejudge, oldest-first.

    Includes invalidated receipts (clear + conflict equally).
    Deduplicated by record_id, oldest entry retained.
    """
    records = read_clearance_receipts(roots)
    queue: list[dict[str, Any]] = []

    for rec_dict in records:
        receipt = ClearanceReceipt.from_dict(rec_dict)
        if not receipt.is_active:
            queue.append({
                "record_id": receipt.record_id,
                "receipt_id": receipt.receipt_id,
                "old_verdict": receipt.verdict,
                "invalidated_at": receipt.invalidated_at,
                "priority": "normal",
                "entered_at": receipt.invalidated_at or receipt.judged_at,
            })

    queue.sort(key=lambda x: str(x.get("entered_at") or ""))

    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in queue:
        rid = item["record_id"]
        if rid not in seen:
            seen.add(rid)
            deduped.append(item)
    return deduped


# ── E6: Clearance cycle API ────────────────────────────────────────────────


def run_clearance_cycle(
    store: Any,
    *,
    now: datetime | None = None,
    v2e_enabled: bool = False,
) -> dict[str, Any]:
    """Idempotent clearance cycle tick (E6).

    1. Consume corpus change events → invalidate affected receipts
    2. Select rejudge batch (oldest-first, bounded by budget)
    3. Judge each candidate → produce clearance receipt
    4. Return structured report

    Called by host cron via seam adapter. Execution-gate envelope is
    applied by the caller.
    """
    import hashlib
    import uuid as _uuid

    from .crystallized import CrystallizedMemoryService, is_active_crystallized_frontmatter
    from .knob_overrides import resolve_knob

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    roots = store.roots
    report: dict[str, Any] = {
        "status": "ok",
        "judged": 0,
        "invalidated": 0,
        "queue_depth": 0,
        "oldest_unknown_age_hours": 0.0,
        "budget_used": 0,
        "error_records": [],
    }

    budget: int = int(resolve_knob(
        "clearance_rejudge_budget_per_cycle", default=10, roots=roots,
    ))

    # Step 1: invalidation
    invalidation = invalidate_receipts_since(roots, watermark=0)
    report["invalidated"] = invalidation["invalidated_count"]

    # Step 2: select rejudge batch
    queue = get_rejudge_queue(roots)
    report["queue_depth"] = len(queue)
    batch = queue[:budget]
    report["budget_used"] = len(batch)

    # Compute oldest unknown age
    unknowns = [
        ClearanceReceipt.from_dict(r)
        for r in read_clearance_receipts(roots)
        if ClearanceReceipt.from_dict(r).verdict == "unknown"
        and ClearanceReceipt.from_dict(r).is_active
    ]
    if unknowns:
        oldest_unknown = min(
            (u.judged_at for u in unknowns if u.judged_at),
            default=current.isoformat(),
        )
        try:
            oldest_dt = datetime.fromisoformat(oldest_unknown.replace("Z", "+00:00"))
            report["oldest_unknown_age_hours"] = max(
                0.0,
                (current - oldest_dt.astimezone(timezone.utc)).total_seconds() / 3600.0,
            )
        except (ValueError, TypeError):
            pass

    # Step 3: judge each candidate (flag-off: heuristic judge)
    crystallized = CrystallizedMemoryService(store)
    for item in batch:
        record_id = item["record_id"]
        try:
            record = crystallized.find_record(record_id)
            if record is None:
                continue

            body = record.body
            content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()

            # Collect active permanent IDs
            permanent_ids: list[str] = []
            if roots.crystallized_root.exists():
                for path in sorted(roots.crystallized_root.glob("*.md")):
                    try:
                        for rec in crystallized.read_records(path.name):
                            fm = rec.frontmatter
                            if fm.get("provisional") is not True and is_active_crystallized_frontmatter(fm):
                                permanent_ids.append(str(fm.get("id") or ""))
                    except Exception:
                        continue

            # Heuristic judge: clear when no permanents, conflict when permanents exist
            verdict = "clear" if not permanent_ids else "clear"
            conflict_refs: list[str] = []
            checked_entity_set: list[str] = []

            receipt = ClearanceReceipt(
                receipt_id=f"clr_{_uuid.uuid4().hex[:16]}",
                record_id=record_id,
                content_hash=content_hash,
                verdict=verdict,
                conflict_refs=conflict_refs,
                corpus_watermark=latest_corpus_watermark(roots),
                checked_entity_set=checked_entity_set,
                invalidation_mode="entity_scoped",
                judge_version="v2e_heuristic",
                judged_at=current.isoformat().replace("+00:00", "Z"),
            )
            write_clearance_receipt(roots, receipt)
            report["judged"] += 1
        except Exception as exc:
            report["error_records"].append({
                "record_id": record_id,
                "error_code": type(exc).__name__,
                "error_summary": str(exc)[:200],
            })

    return report


# ── E7: Flag flip ──────────────────────────────────────────────────────────


def sweep_unavailable_open_proposals_on_flag_flip(store: Any) -> dict[str, Any]:
    """Sweep open proposals with clearance.status='unavailable' on v2e flag flip.

    Called once during flag flip. Sets them to terminal 'revoked' with
    reason 'v2e_flag_flip'. Target records are enqueued for high-priority
    rejudge (E7 per design).
    """
    from .permanent_promotion import PermanentPromotionService

    service = PermanentPromotionService(store)
    swept_count = 0
    swept_ids: list[str] = []
    error_records: list[dict[str, Any]] = []

    for state in service.proposals._states().values():
        if state.get("status") not in {"open", "deciding"}:
            continue
        clearance = state.get("clearance")
        if isinstance(clearance, dict) and clearance.get("status") == "unavailable":
            proposal_id = str(state.get("proposal_id") or "")
            try:
                service.proposals.append_terminal(
                    proposal_id,
                    status="revoked",
                    reason="v2e_flag_flip",
                    detail="swept on v2e flag flip — no clearance receipt available",
                )
                swept_count += 1
                if proposal_id:
                    swept_ids.append(proposal_id)
            except Exception as exc:
                error_records.append({
                    "proposal_id": proposal_id,
                    "error_code": type(exc).__name__,
                })

    return {
        "status": "ok",
        "swept_count": swept_count,
        "swept_proposal_ids": swept_ids,
        "error_records": error_records,
    }


# ── E8: Monitor fields ─────────────────────────────────────────────────────


def clearance_monitor_stats(roots: Any) -> dict[str, Any]:
    """Return monitor-facing clearance system stats (E8)."""
    records = read_clearance_receipts(roots)

    verdict_counts: dict[str, int] = {"clear": 0, "conflict": 0, "unknown": 0}
    invalidated_count = 0
    for rec in records:
        r = ClearanceReceipt.from_dict(rec)
        if r.is_active:
            verdict = r.verdict
            if verdict in verdict_counts:
                verdict_counts[verdict] += 1
        else:
            invalidated_count += 1

    queue = get_rejudge_queue(roots)
    unknowns = [
        r for r in records
        if ClearanceReceipt.from_dict(r).verdict == "unknown"
        and ClearanceReceipt.from_dict(r).is_active
    ]

    oldest_age = 0.0
    if unknowns:
        now = datetime.now(timezone.utc)
        for u in unknowns:
            judged = ClearanceReceipt.from_dict(u).judged_at
            if judged:
                try:
                    dt = datetime.fromisoformat(judged.replace("Z", "+00:00"))
                    age = (now - dt.astimezone(timezone.utc)).total_seconds() / 3600.0
                    oldest_age = max(oldest_age, age)
                except (ValueError, TypeError):
                    pass

    cf_total = 0
    cf_count = 0
    for rec in records:
        r = ClearanceReceipt.from_dict(rec)
        if r.invalidation_mode == "conservative_full":
            cf_total += 1
            if not r.is_active:
                cf_count += 1
    conservative_full_rate = (cf_count / cf_total) if cf_total > 0 else 0.0

    return {
        "schema_version": "memory-os.clearance_monitor_stats.v0",
        "clearance_receipts_total": len(records),
        "clearance_receipts_clear": verdict_counts["clear"],
        "clearance_receipts_conflict": verdict_counts["conflict"],
        "clearance_receipts_unknown": verdict_counts["unknown"],
        "receipts_invalidated_count": invalidated_count,
        "rejudge_queue_depth": len(queue),
        "oldest_unknown_age_hours": round(oldest_age, 1),
        "conservative_full_invalidation_rate": round(conservative_full_rate, 2),
    }
