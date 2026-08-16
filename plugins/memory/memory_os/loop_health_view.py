"""Loop Health View — a read-only projection over existing lane evidence.

Groups the registered cron lanes into the production loops the owner
reasons about (memory, cognition, graph, self-evolution, expression, …) and
rolls up each loop's state from the per-lane last-run evidence
(``system/lane_last_run/<lane_id>.json``, see lane_last_run.py).

Deliberate constraints:

* **Projection only.** This module writes nothing, owns no ledger, and adds
  no authority — it reads artifacts other lanes already produce.  Deleting
  it loses nothing but a view.
* **Standard evidence only (phase 1).** Lanes whose evidence lives in a
  dedicated richer artifact (exposure_rollup's snapshot, v3_wandering's runs
  ledger, …, per cron_registry.LANE_LAST_RUN_EVIDENCE) are listed with
  ``evidence: "dedicated_artifact"`` and do not influence the loop state —
  the row tells the reader where to look instead of pretending to know.
* **Freshness comes from the lane's own cadence** (due_interval_minutes),
  never from a group's cron expression — deriving it from the schedule
  collapses a weekly lane sharing a daily tick into a permanently-stale one.

Loop states (closed set):

* ``attention``   — some member's last run reported status=error
* ``active``      — no errors, and at least one fresh ok run
* ``idle``        — evidence exists but only skips / stale runs
* ``no_evidence`` — no member has standard evidence on disk yet
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .cron_registry import LANE_LAST_RUN_EVIDENCE, MEMORY_OS_CRON_LANES
from .lane_last_run import read_lane_last_run
from .timeutil import ensure_utc_aware

LOOP_HEALTH_VIEW_SCHEMA_VERSION = "memory-os.loop_health_view.v0"

# Every registered lane appears in exactly one loop; a guard test pins this
# partition against MEMORY_OS_CRON_LANES in both directions so a new lane
# must be placed (or the table consciously extended) at birth.
LOOP_MEMBERS: dict[str, tuple[str, ...]] = {
    "memory": (
        "event_stats_refresh",
        "index_sync",
        "candidate_aggregation",
        "fact_judge",
        "session_fact_extraction",
        "working_cleanup",
        "state_source_mirror",
        "exposure_rollup",
    ),
    "cognition": (
        "clearance_cycle",
        "l3_probe_verification",
        "state_overlay_refresh",
        "entity_index_refresh",
    ),
    "graph": (
        "v3_wandering",
        "v3_seed_evidence",
        "v3_journal_sweep",
    ),
    "self_evolution": (
        "proposal_followups_opsgate",
        "module_cadence_report",
    ),
    "expression": (
        "expression_feedback_request",
    ),
    "owner_review": (
        "owner_review_digest_render",
        "memory_sources_feedback_request",
    ),
    "substrate": (
        "hindsight_health_probe",
        "hindsight_advisory_digest",
    ),
    "observability": (
        "full_monitor_refresh",
    ),
}

# A lane is "fresh" while its evidence is younger than N times its cadence:
# one missed tick should not flip a loop to idle, three should.
_FRESHNESS_CADENCE_MULTIPLIER = 3


def _parse_recorded_at(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return ensure_utc_aware(parsed)


def build_loop_health_view(
    hermes_home: str | Path,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Compute the projection. Read-only; safe to call from any surface."""
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    cadence_by_lane = {lane.lane_id: int(lane.due_interval_minutes or 0) for lane in MEMORY_OS_CRON_LANES}

    loops: list[dict[str, Any]] = []
    for loop_name, member_ids in LOOP_MEMBERS.items():
        members: list[dict[str, Any]] = []
        has_error = False
        has_fresh_ok = False
        has_any_standard_evidence = False
        for lane_id in member_ids:
            evidence_kind = LANE_LAST_RUN_EVIDENCE.get(lane_id, "lane_last_run")
            row: dict[str, Any] = {"lane_id": lane_id, "evidence": evidence_kind}
            if evidence_kind != "lane_last_run":
                row["status"] = "see_dedicated_artifact"
                members.append(row)
                continue
            record = read_lane_last_run(hermes_home, lane_id)
            if record is None:
                row["status"] = "no_evidence"
                members.append(row)
                continue
            has_any_standard_evidence = True
            status = str(record.get("status") or "")
            row["status"] = status
            row["reason"] = str(record.get("reason") or "")
            row["recorded_at"] = str(record.get("recorded_at") or "")
            recorded_at = _parse_recorded_at(row["recorded_at"])
            cadence_minutes = cadence_by_lane.get(lane_id) or 0
            if recorded_at is not None:
                age_minutes = max(0, int((moment - recorded_at).total_seconds() // 60))
                row["age_minutes"] = age_minutes
                if cadence_minutes > 0:
                    row["stale"] = age_minutes > cadence_minutes * _FRESHNESS_CADENCE_MULTIPLIER
            if status == "error":
                has_error = True
            elif status == "ok" and row.get("stale") is not True:
                has_fresh_ok = True
            members.append(row)
        if has_error:
            state = "attention"
        elif has_fresh_ok:
            state = "active"
        elif has_any_standard_evidence:
            state = "idle"
        else:
            state = "no_evidence"
        loops.append({"loop": loop_name, "state": state, "members": members})

    return {
        "schema_version": LOOP_HEALTH_VIEW_SCHEMA_VERSION,
        "generated_at": moment.isoformat().replace("+00:00", "Z"),
        "loops": loops,
        "raw_body_included": False,
    }


def render_loop_health_summary(view: dict[str, Any]) -> str:
    """Compact human-readable rendering for CLI / owner surfaces."""
    lines = [f"Loop Health View ({view.get('generated_at', '')})"]
    for loop in view.get("loops", []):
        members = loop.get("members", [])
        annotated = []
        for member in members:
            status = str(member.get("status") or "")
            reason = str(member.get("reason") or "")
            label = f"{member.get('lane_id')}={status}"
            if reason:
                label += f"({reason})"
            annotated.append(label)
        lines.append(f"[{loop.get('state', ''):>11}] {loop.get('loop', '')}: " + ", ".join(annotated))
    return "\n".join(lines)
