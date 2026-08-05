"""Dry-run retention planning for Memory-OS metadata ledgers and reports."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .ids import new_audit_id
from .memory_sources import memory_sources_feedback_path, memory_sources_path
from .roots import MemoryOSRoots


@dataclass(frozen=True)
class MetadataRetentionPolicy:
    memory_sources_retention_days: int | None = 30
    feedback_retention_days: int | None = 30
    suggestion_retention_days: int | None = 30
    shadow_retention_days: int | None = 30
    eval_report_retention_days: int | None = 30
    eval_report_keep_latest: int = 20
    suggestion_report_retention_days: int | None = 30
    suggestion_report_keep_latest: int = 20


def metadata_retention_plan(
    roots: MemoryOSRoots,
    *,
    now: datetime | None = None,
    policy: MetadataRetentionPolicy | None = None,
    eval_report_root: str | Path | None = None,
    suggestion_report_root: str | Path | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    active_policy = policy or MetadataRetentionPolicy()
    actions: list[dict[str, Any]] = []
    ledgers = [
        _ledger_plan(
            ledger="memory_sources",
            path=memory_sources_path(roots),
            retention_days=active_policy.memory_sources_retention_days,
            now=current,
            actions=actions,
        ),
        _ledger_plan(
            ledger="memory_sources_feedback",
            path=memory_sources_feedback_path(roots),
            retention_days=active_policy.feedback_retention_days,
            now=current,
            actions=actions,
        ),
        _ledger_plan(
            ledger="consolidation_suggestions",
            path=roots.memory_os_root / "system" / "consolidation_suggestions.jsonl",
            retention_days=active_policy.suggestion_retention_days,
            now=current,
            actions=actions,
        ),
        _ledger_plan(
            ledger="graph_layer_shadow",
            path=roots.memory_os_root / "system" / "graph_layer_shadow.jsonl",
            retention_days=active_policy.shadow_retention_days,
            now=current,
            actions=actions,
        ),
        _ledger_plan(
            ledger="substrate_recall_shadow",
            path=roots.memory_os_root / "system" / "substrate_recall_shadow.jsonl",
            retention_days=active_policy.shadow_retention_days,
            now=current,
            actions=actions,
        ),
        # Continuity freshness disclosure — the third report-only ledger written
        # from the prefetch path, so it gets the same shadow retention as the two
        # above. Registering it here is not optional bookkeeping: an unregistered
        # ledger is invisible to retention planning and grows without bound while
        # its siblings are swept.
        _ledger_plan(
            ledger="continuity_freshness",
            path=roots.memory_os_root / "system" / "continuity_freshness.jsonl",
            retention_days=active_policy.shadow_retention_days,
            now=current,
            actions=actions,
        ),
        # session_fact_extraction's two bookkeeping ledgers. Registering them is
        # the same non-optional step as above, and the growth is not theoretical:
        # an appended-to session mints a NEW fingerprint by design, so an active
        # session adds a row per tick and the whole file is read every run.
        # Both use `created_at` so _record_created_at() can actually age them --
        # see backlog item 9 for the two sibling ledgers that cannot.
        _ledger_plan(
            ledger="session_fact_extraction_processed_sessions",
            path=(
                roots.memory_os_root / "system-modules" / "session_fact_extraction"
                / "processed_sessions.jsonl"
            ),
            retention_days=active_policy.shadow_retention_days,
            now=current,
            actions=actions,
        ),
        _ledger_plan(
            ledger="session_fact_extraction_runs",
            path=(
                roots.memory_os_root / "system-modules" / "session_fact_extraction"
                / "runs.jsonl"
            ),
            retention_days=active_policy.shadow_retention_days,
            now=current,
            actions=actions,
        ),
    ]
    report_roots = [
        _report_root_plan(
            report_class="rh31_eval_reports",
            root=Path(eval_report_root) if eval_report_root else Path("eval") / "reports" / "memory-os-rh31",
            retention_days=active_policy.eval_report_retention_days,
            keep_latest=active_policy.eval_report_keep_latest,
            now=current,
            actions=actions,
        ),
        _report_root_plan(
            report_class="rh32_suggestion_reports",
            root=Path(suggestion_report_root)
            if suggestion_report_root
            else Path("eval") / "reports" / "memory-os-rh32-suggestions",
            retention_days=active_policy.suggestion_report_retention_days,
            keep_latest=active_policy.suggestion_report_keep_latest,
            now=current,
            actions=actions,
        ),
    ]
    return {
        "schema_version": "memory-os.metadata_retention_plan.v0",
        "created_at": current.isoformat(),
        "dry_run": True,
        "policy": {
            "memory_sources_retention_days": active_policy.memory_sources_retention_days,
            "feedback_retention_days": active_policy.feedback_retention_days,
            "suggestion_retention_days": active_policy.suggestion_retention_days,
            "shadow_retention_days": active_policy.shadow_retention_days,
            "eval_report_retention_days": active_policy.eval_report_retention_days,
            "eval_report_keep_latest": max(int(active_policy.eval_report_keep_latest), 0),
            "suggestion_report_retention_days": active_policy.suggestion_report_retention_days,
            "suggestion_report_keep_latest": max(int(active_policy.suggestion_report_keep_latest), 0),
        },
        "ledgers": ledgers,
        "report_roots": report_roots,
        "actions": actions,
        "canonical_paths_touched": [],
    }


def _ledger_plan(
    *,
    ledger: str,
    path: Path,
    retention_days: int | None,
    now: datetime,
    actions: list[dict[str, Any]],
) -> dict[str, Any]:
    summary = {
        "ledger": ledger,
        "path": str(path),
        "exists": path.exists(),
        "retention_days": retention_days,
        "total_records": 0,
        "retained_records": 0,
        "archive_candidate_records": 0,
    }
    if retention_days is None or not path.exists():
        return summary
    stale_records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        summary["total_records"] += 1
        created_at = _record_created_at(record)
        if created_at is None or _age_days(created_at, now=now) < retention_days:
            summary["retained_records"] += 1
            continue
        stale_records.append(
            {
                "line_number": line_number,
                "record_id": _safe_record_id(record),
                "created_at": created_at.isoformat(),
                "age_days": _age_days(created_at, now=now),
            }
        )
    summary["archive_candidate_records"] = len(stale_records)
    if stale_records:
        actions.append(
            {
                "id": new_audit_id(now, unique=uuid4().hex[:8]).replace("audit_", "retention_action_", 1),
                "kind": "archive_metadata_jsonl_records",
                "ledger": ledger,
                "target": str(path),
                "record_count": len(stale_records),
                "records": stale_records[:50],
                "archive_before_prune": True,
                "reason": f"records_older_than_{retention_days}_days",
            }
        )
    return summary


def _report_root_plan(
    *,
    report_class: str,
    root: Path,
    retention_days: int | None,
    keep_latest: int,
    now: datetime,
    actions: list[dict[str, Any]],
) -> dict[str, Any]:
    summary = {
        "report_class": report_class,
        "root": str(root),
        "exists": root.exists(),
        "retention_days": retention_days,
        "keep_latest": max(int(keep_latest), 0),
        "candidate_count": 0,
        "archive_candidate_count": 0,
    }
    if retention_days is None or not root.exists():
        return summary
    candidates = [path for path in root.iterdir() if path.is_dir()]
    candidates.sort(key=lambda path: (path.stat().st_mtime, path.name), reverse=True)
    summary["candidate_count"] = len(candidates)
    keep_count = max(int(keep_latest), 0)
    for index, path in enumerate(candidates):
        if index < keep_count:
            continue
        age_days = _path_age_days(path, now=now)
        if retention_days != 0 and age_days < retention_days:
            continue
        summary["archive_candidate_count"] += 1
        actions.append(
            {
                "id": new_audit_id(now, unique=uuid4().hex[:8]).replace("audit_", "retention_action_", 1),
                "kind": "archive_report_dir",
                "report_class": report_class,
                "target": str(path),
                "age_days": age_days,
                "archive_before_prune": True,
                "reason": "outside_keep_latest_and_older_than_retention",
            }
        )
    return summary


def _record_created_at(record: dict[str, Any]) -> datetime | None:
    value = record.get("created_at") or record.get("ts") or record.get("timestamp")
    if not value:
        return None
    try:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).astimezone(timezone.utc)
    except ValueError:
        return None


def _safe_record_id(record: dict[str, Any]) -> str:
    for key in ("record_id", "feedback_id", "suggestion_id", "run_id", "id"):
        value = str(record.get(key) or "").strip()
        if value:
            return value[:120]
    return ""


def _age_days(created_at: datetime, *, now: datetime) -> float:
    return max(0.0, (now - created_at.astimezone(timezone.utc)).total_seconds() / 86400.0)


def _path_age_days(path: Path, *, now: datetime) -> float:
    mtime = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    return max(0.0, (now - mtime).total_seconds() / 86400.0)
