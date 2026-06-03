"""Report-only left-brain advisor over Memory-OS projections."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .execution_gate import complete_execution_gate_envelope, resolve_execution_gate_permit
from .memory_projection import memory_projection_records_path
from .roots import MemoryOSRoots
from .store import MemoryOSStore
from .structural_write_gate import append_governed_jsonl


LEFT_BRAIN_ADVISOR_SCHEMA_VERSION = "memory-os.left_brain_advisor.v0"
ADVISOR_LANE_ID = "left_brain_advisor_report"
ADVISOR_RISK_CLASS = "governance_projection"


def left_brain_advisor_reports_path(roots: MemoryOSRoots) -> Path:
    return roots.hermes_home / "system-modules" / "left_brain_advisor" / "reports.jsonl"


def read_left_brain_advisor_reports(roots: MemoryOSRoots, *, limit: int = 0) -> list[dict[str, Any]]:
    records = _read_jsonl(left_brain_advisor_reports_path(roots))
    return records[-max(limit, 0):] if limit else records


def left_brain_advisor_status(roots: MemoryOSRoots) -> dict[str, Any]:
    reports = read_left_brain_advisor_reports(roots)
    latest = reports[-1] if reports else {}
    governance = (
        latest.get("structural_write_governance")
        if isinstance(latest.get("structural_write_governance"), dict)
        else {}
    )
    return {
        "schema_version": "memory-os.left_brain_advisor_status.v0",
        "status": str(latest.get("status") or "missing"),
        "report_count": len(reports),
        "latest_report_id": str(latest.get("report_id") or ""),
        "latest_created_at": str(latest.get("created_at") or ""),
        "latest_live_closure_eligible": bool(latest.get("live_closure_eligible")) if latest else False,
        "latest_structural_write_governance_present": bool(governance),
        "latest_structural_write_permit_status": str(governance.get("permit_status") or ""),
        "latest_structural_write_lane_id": str(governance.get("lane_id") or ""),
        "latest_structural_write_risk_class": str(governance.get("risk_class") or ""),
        "latest_structural_write_boundary_true": governance.get("boundary_true") is True,
        "finding_count": int(latest.get("finding_count") or 0),
        "owner_visible_finding_count": int(latest.get("owner_visible_finding_count") or 0),
        "boundary_true_count": int(latest.get("boundary_true_count") or 0),
        "raw_body_included": bool(latest.get("raw_body_included")) if latest else False,
    }


def run_left_brain_advisor(
    store: MemoryOSStore,
    *,
    write: bool = True,
    max_findings: int = 20,
    trigger_type: str = "manual_cli",
    execution_envelope_id: str = "",
    expected_scope: dict[str, Any] | None = None,
    manual_run_ref: str = "",
) -> dict[str, Any]:
    automatic = str(trigger_type or "") not in {"manual_cli", "manual_test"}
    resolution = {"status": "not_required", "reason": "manual_cli_not_live_closure"}
    if automatic:
        resolution = resolve_execution_gate_permit(
            store.roots,
            envelope_id=execution_envelope_id,
            lane_id=ADVISOR_LANE_ID,
            risk_class=ADVISOR_RISK_CLASS,
            require_fresh=True,
            require_unused=True,
            expected_scope=expected_scope,
        )
        if resolution.get("status") != "valid":
            return {
                "schema_version": LEFT_BRAIN_ADVISOR_SCHEMA_VERSION,
                "status": "blocked",
                "reason": str(resolution.get("reason") or "execution_gate_invalid"),
                "trigger_type": str(trigger_type or ""),
                "execution_gate_resolution": resolution,
                "finding_count": 0,
                "owner_visible_finding_count": 0,
                "boundary_true_count": 0,
                "raw_body_included": False,
                "boundary": _false_boundary(),
            }
    projections = _read_jsonl(memory_projection_records_path(store.roots))
    boundary_true_count = sum(1 for record in projections if _any_true(record.get("boundary")))
    if boundary_true_count:
        return _base_report(
            store,
            status="blocked",
            projections=projections,
            findings=[],
            boundary_true_count=boundary_true_count,
            trigger_type=trigger_type,
            execution_envelope_id=execution_envelope_id if automatic else "",
            manual_run_ref=manual_run_ref,
            execution_gate_resolution=resolution,
        )
    findings = _build_findings(projections, max_findings=max_findings)
    status = "warning" if findings else "ok"
    report = _base_report(
        store,
        status=status,
        projections=projections,
        findings=findings,
        boundary_true_count=0,
        trigger_type=trigger_type,
        execution_envelope_id=execution_envelope_id if automatic else "",
        manual_run_ref=manual_run_ref,
        execution_gate_resolution=resolution,
    )
    if write:
        if automatic:
            append_governed_jsonl(
                store,
                left_brain_advisor_reports_path(store.roots),
                report,
                write_owner="automatic",
                lane_id=ADVISOR_LANE_ID,
                risk_class=ADVISOR_RISK_CLASS,
                execution_gate_envelope_id=execution_envelope_id,
                scope_hash=str(resolution.get("scope_hash") or ""),
            )
        else:
            _append_jsonl(left_brain_advisor_reports_path(store.roots), report)
    if automatic:
        complete_execution_gate_envelope(
            store,
            envelope_id=execution_envelope_id,
            lane_id=ADVISOR_LANE_ID,
            execution_status=str(report.get("status") or "ok"),
            postcheck={"boundary": _false_boundary(), "finding_count": len(findings)},
            result_summary={"report_id": report["report_id"], "finding_count": len(findings)},
        )
    return report


def _base_report(
    store: MemoryOSStore,
    *,
    status: str,
    projections: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    boundary_true_count: int,
    trigger_type: str = "manual_cli",
    execution_envelope_id: str = "",
    manual_run_ref: str = "",
    execution_gate_resolution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    material = json.dumps(
        {"ts": now.isoformat(), "projection_count": len(projections), "finding_count": len(findings)},
        ensure_ascii=False,
        sort_keys=True,
    )
    report_id = f"lbadvisor_{now.strftime('%Y%m%dT%H%M%S%fZ')}_{hashlib.sha256(material.encode('utf-8')).hexdigest()[:8]}"
    return {
        "schema_version": LEFT_BRAIN_ADVISOR_SCHEMA_VERSION,
        "report_id": report_id,
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "profile": store.roots.profile or "default",
        "status": status,
        "trigger_type": str(trigger_type or ""),
        "execution_envelope_id": str(execution_envelope_id or ""),
        "manual_run_ref": str(manual_run_ref or ""),
        "live_closure_eligible": str(trigger_type or "") not in {"manual_cli", "manual_test"},
        "execution_gate_resolution": execution_gate_resolution or {"status": "not_required"},
        "projection_count": len(projections),
        "finding_count": len(findings),
        "owner_visible_finding_count": sum(1 for finding in findings if finding.get("owner_visible")),
        "boundary_true_count": boundary_true_count,
        "findings": findings,
        "raw_body_included": False,
        "actual_execute": False,
        "actual_send": False,
        "actual_policy_write": False,
        "actual_crystallized_approval": False,
        "actual_identity_write": False,
        "actual_relationship_write": False,
        "actual_route_score_write": False,
        "hindsight_write": False,
        "boundary": _false_boundary(),
    }


def _build_findings(projections: list[dict[str, Any]], *, max_findings: int) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    seen_dedup_keys: set[str] = set()
    for projection in projections:
        source_key = str(projection.get("source_key") or "")
        payload = projection.get("payload") if isinstance(projection.get("payload"), dict) else {}
        status = str(payload.get("status") or "").lower()
        available = payload.get("available")
        if source_key == "hermes_cron_jobs" and int(payload.get("external_failure_count") or 0) > 0:
            _append_finding_once(
                findings,
                seen_dedup_keys,
                _finding(source_key, projection, status="external_cron_failure"),
            )
        if source_key == "hindsight_provider_stats":
            if int(payload.get("projection_stale_count") or 0) > 0:
                _append_finding_once(
                    findings,
                    seen_dedup_keys,
                    _finding(source_key, projection, status="hindsight_projection_stale"),
                )
            if int(payload.get("raw_retained_count") or 0) > 0:
                _append_finding_once(
                    findings,
                    seen_dedup_keys,
                    _finding(source_key, projection, status="hindsight_raw_retain_detected"),
                )
            if int(payload.get("pollution_indicator_count") or 0) > 0:
                _append_finding_once(
                    findings,
                    seen_dedup_keys,
                    _finding(source_key, projection, status="hindsight_pollution_indicator"),
                )
        if status in {"missing", "error", "blocked"}:
            _append_finding_once(findings, seen_dedup_keys, _finding(source_key, projection, status=status or "missing"))
        elif available is False:
            _append_finding_once(findings, seen_dedup_keys, _finding(source_key, projection, status="availability_missing"))
        if int(payload.get("boundary_true_count") or 0) > 0:
            _append_finding_once(findings, seen_dedup_keys, _finding(source_key, projection, status="boundary_true_count"))
        if len(findings) >= max(max_findings, 0):
            break
    return findings


def _append_finding_once(findings: list[dict[str, Any]], seen_dedup_keys: set[str], finding: dict[str, Any]) -> None:
    dedup_key = str(finding.get("dedup_key") or finding.get("finding_id") or "")
    if dedup_key in seen_dedup_keys:
        return
    seen_dedup_keys.add(dedup_key)
    findings.append(finding)


def _finding(source_key: str, projection: dict[str, Any], *, status: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    payload = projection.get("payload") if isinstance(projection.get("payload"), dict) else {}
    dedup_key = _finding_dedup_key(source_key, projection, status)
    finding_id = "lbf_" + hashlib.sha256(
        json.dumps(
            {
                "source_key": source_key,
                "dedup_key": dedup_key,
                "status": status,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:16]
    title = f"Signal source needs review: {source_key}"
    summary = f"{source_key} projection reported status={status}."
    reason = "LeftBrainAdvisor report-only diagnosis from MemoryProjection metadata."
    confidence = 0.72
    if source_key == "hermes_cron_jobs" and status == "external_cron_failure":
        job = str(payload.get("latest_failure_job") or "external Hermes cron job")
        failure_reason = str(payload.get("latest_failure_reason") or "external cron failure")
        title = f"Hermes cron external failure: {job}"
        summary = f"{job} reported {failure_reason}."
        reason = "Repeated external Hermes cron failure observed via read-only cron output projection; Memory-OS does not rerun, modify, or own the job."
        confidence = 0.86
    elif source_key == "hindsight_provider_stats" and status == "hindsight_projection_stale":
        stale_count = int(payload.get("projection_stale_count") or 0)
        title = "Hindsight projection stale facts need review"
        summary = f"Hindsight projection ledger reports stale projection count={stale_count}."
        reason = "Memory-OS observed derived Hindsight projection coherence metadata; this is a review-only curation suggestion and does not write, delete, or promote Hindsight facts."
        confidence = 0.84
    elif source_key == "hindsight_provider_stats" and status == "hindsight_raw_retain_detected":
        raw_count = int(payload.get("raw_retained_count") or 0)
        title = "Hindsight raw retain boundary needs review"
        summary = f"Hindsight substrate ledger reports raw retained count={raw_count}."
        reason = "Raw-retain indicators should be investigated through governed curation; Memory-OS does not import raw payload or change Hindsight ownership."
        confidence = 0.9
    elif source_key == "hindsight_provider_stats" and status == "hindsight_pollution_indicator":
        pollution_count = int(payload.get("pollution_indicator_count") or 0)
        title = "Hindsight pollution indicators need review"
        summary = f"Hindsight metadata reports pollution indicator count={pollution_count}."
        reason = "Pollution/stale/duplicate indicators are surfaced as bounded governance suggestions only; Hindsight remains advisory and non-authoritative."
        confidence = 0.82
    return {
        "schema_version": "memory-os.left_brain_advisor_finding.v0",
        "finding_id": finding_id,
        "dedup_key": dedup_key,
        "confidence": confidence,
        "owner_burden_class": "review_suggested",
        "expires_at": (now + timedelta(days=7)).isoformat().replace("+00:00", "Z"),
        "allowed_action_type": "review_only",
        "target_type": "left_brain_advisor_finding",
        "target_id": finding_id,
        "source_module": "left_brain_advisor",
        "priority": "review_suggested",
        "owner_visible": True,
        "actions_suppressed": True,
        "title": title,
        "summary": summary,
        "reason": reason,
        "suggested_action": "review-only; no automatic apply",
        "projection_id": str(projection.get("projection_id") or ""),
        "source_key": source_key,
        "safe_source_ids": [str(projection.get("projection_id") or "")] if projection.get("projection_id") else [],
        "raw_body_included": False,
        "actual_execute": False,
        "actual_send": False,
        "actual_policy_write": False,
        "actual_crystallized_approval": False,
        "actual_identity_write": False,
        "actual_relationship_write": False,
        "actual_route_score_write": False,
        "hindsight_write": False,
    }


def _finding_dedup_key(source_key: str, projection: dict[str, Any], status: str) -> str:
    payload = projection.get("payload") if isinstance(projection.get("payload"), dict) else {}
    if source_key == "hermes_cron_jobs" and status == "external_cron_failure":
        material = {
            "source_key": source_key,
            "status": status,
            "source_scope_ref": projection.get("source_scope_ref"),
            "latest_failure_job": payload.get("latest_failure_job"),
            "latest_failure_reason": payload.get("latest_failure_reason"),
        }
        return "lbf_dedup_" + hashlib.sha256(
            json.dumps(material, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:24]
    if source_key == "hindsight_provider_stats" and status.startswith("hindsight_"):
        material = {
            "source_key": source_key,
            "status": status,
            "source_scope_ref": projection.get("source_scope_ref"),
            "recall_mode": payload.get("recall_mode"),
            "raw_retained_count": payload.get("raw_retained_count"),
            "projection_stale_count": payload.get("projection_stale_count"),
            "pollution_indicator_count": payload.get("pollution_indicator_count"),
        }
        return "lbf_dedup_" + hashlib.sha256(
            json.dumps(material, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:24]
    material = {
        "source_key": source_key,
        "status": status,
        "source_hash": projection.get("source_hash"),
        "source_scope_ref": projection.get("source_scope_ref"),
        "projection_id": "" if projection.get("source_hash") else projection.get("projection_id"),
    }
    return "lbf_dedup_" + hashlib.sha256(json.dumps(material, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:24]


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
        handle.write("\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            records.append(parsed)
    return records


def _any_true(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, dict):
        return any(_any_true(item) for item in value.values())
    if isinstance(value, list):
        return any(_any_true(item) for item in value)
    return False


def _false_boundary() -> dict[str, bool]:
    return {
        "actual_send": False,
        "actual_execute": False,
        "actual_identity_write": False,
        "actual_relationship_write": False,
        "actual_crystallized_approval": False,
        "actual_policy_write": False,
        "actual_route_score_write": False,
        "hindsight_write": False,
    }
