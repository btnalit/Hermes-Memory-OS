"""Report-only Ops-Gate module for portable Hermes deployments."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from plugins.memory.memory_os.audit import append_audit
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.system.scheduler import ScheduleCoordinator


BLOCKED_ACTION_KINDS = {
    "config_write",
    "filesystem_delete",
    "gateway_restart",
    "hindsight_export",
    "identity_write",
    "mailbox_send",
    "production_write",
    "service_restart",
    "telegram_send",
}


def ops_gate_manifest() -> dict[str, Any]:
    """Return the v0.1 Ops-Gate module manifest."""

    return {
        "name": "ops_gate",
        "kind": "governance",
        "version": "0.1.0",
        "layer": "L3",
        "dependencies": {
            "required": ["memory_os >=0.1.0", "scheduler"],
            "optional": ["proposal_queue", "evidence_scoring"],
        },
        "provides": {
            "commands": ["status", "doctor", "run-once"],
            "schedules": ["ops_gate_audit"],
            "reads": ["memory_os.events.summary", "module_health"],
            "writes": ["memory_os.audit", "local_artifact.ops_gate_report"],
        },
        "defaults": {
            "enabled": False,
            "delivery_mode": "no-send",
            "profile_scope": "per-profile",
        },
        "memory_os_compat": {
            "min_version": "0.1.0",
            "max_version": "0.2.x",
            "schema_versions": {
                "event": ["memory-os.event.v0"],
                "working": ["memory-os.working.v0"],
                "crystallized": ["memory-os.crystallized.v0"],
            },
        },
    }


class OpsGateModule:
    """Evaluate proposed operational actions without executing them."""

    lock_resource_id = "ops_gate.runtime"

    def __init__(self, hermes_home: str | Path, *, profile: str, execution_mode: str = "report-only") -> None:
        self.hermes_home = Path(hermes_home).expanduser().resolve()
        self.profile = profile
        self.execution_mode = execution_mode

    @property
    def module_root(self) -> Path:
        return self.hermes_home / "system-modules" / "ops_gate"

    @property
    def reports_path(self) -> Path:
        return self.module_root / "reports.jsonl"

    @property
    def runs_path(self) -> Path:
        return self.module_root / "runs.jsonl"

    @property
    def lock_root(self) -> Path:
        return self.hermes_home / "system-modules" / "locks"

    def status(self) -> dict[str, Any]:
        reports = self.read_reports()
        runs = self.read_runs()
        last_report = reports[-1] if reports else {}
        last_run = runs[-1] if runs else {}
        decisions = list(last_report.get("decisions", [])) if isinstance(last_report.get("decisions", []), list) else []
        blocked_count = sum(1 for decision in decisions if decision.get("decision") == "blocked")
        return {
            "schema_version": "hermes.ops_gate_status.v0",
            "module": "ops_gate",
            "profile": self.profile,
            "execution_mode": self.execution_mode,
            "report_count": len(reports),
            "run_report_count": len(runs),
            "skipped_run_count": sum(
                1
                for run in runs
                if isinstance(run, dict) and (run.get("skipped") is True or run.get("cadence_skipped") is True)
            ),
            "latest_cadence_skipped": bool(last_run.get("cadence_skipped") is True),
            "latest_skip_reason": str(last_run.get("reason") or ""),
            "last_report_status": str(last_report.get("status", "missing")),
            "blocked_decision_count": blocked_count,
            "actual_execute": False,
        }

    def doctor(self) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        if self.execution_mode != "report-only":
            findings.append(
                {
                    "severity": "error",
                    "code": "execution_mode_not_report_only",
                    "message": "Ops-Gate v0.1 only supports report-only mode",
                }
            )
        status = self.status()
        if status["blocked_decision_count"]:
            findings.append(
                {
                    "severity": "warning",
                    "code": "blocked_actions_present",
                    "message": f"{status['blocked_decision_count']} blocked action(s) in the latest report",
                }
            )
        if status["report_count"] == 0 and status["run_report_count"] == 0:
            findings.append(
                {
                    "severity": "warning",
                    "code": "no_ops_gate_reports",
                    "message": "No Ops-Gate report has been written yet",
                }
            )

        if any(finding["severity"] == "error" for finding in findings):
            report_status = "error"
        elif findings:
            report_status = "warning"
        else:
            report_status = "ok"
        return {
            "schema_version": "hermes.ops_gate_doctor.v0",
            "module": "ops_gate",
            "profile": self.profile,
            "status": report_status,
            "findings": findings,
        }

    def run_once(
        self,
        *,
        store: MemoryOSStore,
        proposed_actions: list[dict[str, Any]] | None = None,
        coordinator: ScheduleCoordinator | None = None,
        lock_ttl_seconds: int = 300,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        schedule = coordinator or ScheduleCoordinator(self.lock_root)
        owner = f"ops_gate:{self.profile}"
        lock = schedule.acquire_lock(
            self.lock_resource_id,
            owner=owner,
            ttl_seconds=lock_ttl_seconds,
            now=now,
        )
        if not lock.acquired:
            return {
                "schema_version": "hermes.ops_gate_result.v0",
                "module": "ops_gate",
                "profile": self.profile,
                "status": "deferred",
                "reason": "lock_held",
                "decision_count": 0,
                "lock_contention_count": lock.lock_contention_count,
                "actual_execute": False,
            }

        try:
            return self._run_locked(store=store, proposed_actions=proposed_actions or [], now=now)
        finally:
            schedule.release_lock(self.lock_resource_id, owner=owner)

    def read_reports(self) -> list[dict[str, Any]]:
        if not self.reports_path.exists():
            return []
        reports: list[dict[str, Any]] = []
        for line in self.reports_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                parsed = json.loads(line)
                if isinstance(parsed, dict):
                    reports.append(parsed)
        return reports

    def read_runs(self) -> list[dict[str, Any]]:
        if not self.runs_path.exists():
            return []
        runs: list[dict[str, Any]] = []
        for line in self.runs_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                parsed = json.loads(line)
                if isinstance(parsed, dict):
                    runs.append(parsed)
        return runs

    def _run_locked(
        self,
        *,
        store: MemoryOSStore,
        proposed_actions: list[dict[str, Any]],
        now: datetime | None,
    ) -> dict[str, Any]:
        store.initialize()
        if not proposed_actions:
            run = {
                "schema_version": "hermes.ops_gate_run.v0",
                "run_id": _new_run_id(now),
                "ts": _timestamp(now),
                "module": "ops_gate",
                "profile": self.profile,
                "status": "ok",
                "skipped": True,
                "cadence_skipped": True,
                "reason": "no_pending_proposed_actions",
                "decision_count": 0,
                "execution_mode": self.execution_mode,
                "actual_execute": False,
            }
            self._append_run(run)
            append_audit(
                store.roots.audit_path,
                action="ops_gate_run_skipped",
                status="ok",
                target=str(self.runs_path),
                details={
                    "run_id": run["run_id"],
                    "reason": run["reason"],
                    "decision_count": 0,
                    "execution_mode": self.execution_mode,
                    "actual_execute": False,
                },
            )
            return {
                "schema_version": "hermes.ops_gate_result.v0",
                "module": "ops_gate",
                "profile": self.profile,
                "status": "ok",
                "skipped": True,
                "cadence_skipped": True,
                "reason": "no_pending_proposed_actions",
                "run_id": run["run_id"],
                "execution_mode": self.execution_mode,
                "actual_execute": False,
                "decision_count": 0,
                "decisions": [],
                "run_path": str(self.runs_path),
            }
        decisions = [self._evaluate_action(action) for action in proposed_actions]
        status = "warning" if any(decision["decision"] == "blocked" for decision in decisions) else "ok"
        report = {
            "schema_version": "hermes.ops_gate_report.v0",
            "report_id": _new_report_id(now),
            "ts": _timestamp(now),
            "module": "ops_gate",
            "profile": self.profile,
            "status": status,
            "execution_mode": self.execution_mode,
            "actual_execute": False,
            "decision_count": len(decisions),
            "decisions": decisions,
            "event_count": len([event for event in store.read_events() if event.profile == self.profile]),
        }
        self._append_report(report)
        append_audit(
            store.roots.audit_path,
            action="ops_gate_report_written",
            status=status,
            target=str(self.reports_path),
            details={
                "report_id": report["report_id"],
                "decision_count": report["decision_count"],
                "blocked_decision_count": sum(1 for decision in decisions if decision["decision"] == "blocked"),
                "execution_mode": self.execution_mode,
                "actual_execute": False,
            },
        )
        return {
            "schema_version": "hermes.ops_gate_result.v0",
            "module": "ops_gate",
            "profile": self.profile,
            "status": status,
            "report_id": report["report_id"],
            "execution_mode": self.execution_mode,
            "actual_execute": False,
            "decision_count": len(decisions),
            "decisions": decisions,
            "report_path": str(self.reports_path),
        }

    def _evaluate_action(self, action: dict[str, Any]) -> dict[str, Any]:
        action_id = str(action.get("id", ""))
        kind = str(action.get("kind", ""))
        target = str(action.get("target", ""))
        blocked = kind in BLOCKED_ACTION_KINDS or _looks_like_production_target(target)
        return {
            "schema_version": "hermes.ops_gate_decision.v0",
            "action_id": action_id,
            "kind": kind,
            "target": target,
            "decision": "blocked" if blocked else "would_allow",
            "reason": "production_action_blocked" if blocked else "report_only_allowed",
            "actual_execute": False,
        }

    def _append_report(self, report: dict[str, Any]) -> None:
        self.reports_path.parent.mkdir(parents=True, exist_ok=True)
        with self.reports_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(report, ensure_ascii=False, sort_keys=True))
            handle.write("\n")

    def _append_run(self, run: dict[str, Any]) -> None:
        self.runs_path.parent.mkdir(parents=True, exist_ok=True)
        with self.runs_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(run, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def _looks_like_production_target(target: str) -> bool:
    lowered = target.lower()
    return any(marker in lowered for marker in ("10.20.2.88", "/vol1/.hermes", "/root/.hermes", "gateway.service"))


def _timestamp(value: datetime | None) -> str:
    return (value or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()


def _new_report_id(value: datetime | None) -> str:
    now = (value or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return f"opsr_{now.strftime('%Y%m%dT%H%M%S%fZ')}_{uuid4().hex[:10]}"


def _new_run_id(value: datetime | None) -> str:
    now = (value or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return f"opsrun_{now.strftime('%Y%m%dT%H%M%S%fZ')}_{uuid4().hex[:10]}"
