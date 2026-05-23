"""Test-host no-send cognitive loop scheduler for Memory-OS."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Callable
from uuid import uuid4

from plugins.memory.memory_os.audit import append_audit
from plugins.memory.memory_os.crystallized import read_candidate_queue
from plugins.memory.memory_os.runtime import MemoryOSRuntime
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.system.scheduler import ScheduleCoordinator


BOUNDARIES = {
    "actual_send": False,
    "actual_execute": False,
    "actual_identity_write": False,
    "actual_relationship_write": False,
    "actual_crystallized_approval": False,
    "hindsight_exported": False,
}
BOUNDARY_KEYS = tuple(BOUNDARIES)


class CognitiveLoopRunner:
    """Run the full Memory-OS test-host cognition loop without send/execute."""

    lock_resource_id = "memory_os.cognitive_loop"

    def __init__(self, store: MemoryOSStore) -> None:
        self.store = store
        self.profile = store.roots.profile or "default"
        self.hermes_home = store.roots.hermes_home
        self.module_root = self.hermes_home / "system-modules" / "cognitive_loop"
        self.reports_path = self.module_root / "reports.jsonl"
        self.lock_root = self.hermes_home / "system-modules" / "locks"

    def run_once(
        self,
        *,
        apply: bool = False,
        test_host: bool = False,
        max_events: int = 100,
    ) -> dict[str, Any]:
        self.store.initialize()
        if apply and not test_host:
            return self._error_result(code="test_host_required", apply=apply, test_host=test_host)

        cycle_id = f"cloop_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}_{uuid4().hex[:10]}"
        coordinator = ScheduleCoordinator(self.lock_root)
        owner = f"cognitive_loop:{self.profile}:{cycle_id}"
        lock = coordinator.acquire_lock(
            self.lock_resource_id,
            owner=owner,
            ttl_seconds=60 * 60,
        )
        if not lock.acquired:
            return {
                "schema_version": "memory-os.cognitive_loop.v0",
                "cycle_id": cycle_id,
                "profile": self.profile,
                "status": "warning",
                "code": "lock_held",
                "apply": apply,
                "test_host": test_host,
                "steps": [],
                "boundaries": dict(BOUNDARIES),
                "lock_contention_count": lock.lock_contention_count,
            }

        started_at = datetime.now(timezone.utc)
        context: dict[str, Any] = {}
        steps: list[dict[str, Any]] = []
        try:
            for name, fn in self._step_functions(max_events=max_events, apply=apply):
                steps.append(self._run_step(name, fn, context))
            boundary_state = _boundary_state(steps)
            status = self._cycle_status(steps, boundary_state)
            result = {
                "schema_version": "memory-os.cognitive_loop.v0",
                "cycle_id": cycle_id,
                "profile": self.profile,
                "status": status,
                "apply": apply,
                "test_host": test_host,
                "started_at": started_at.isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "duration_ms": int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000),
                "steps": steps,
                "boundaries": boundary_state,
                "report_path": str(self.reports_path),
            }
            self._append_report(result)
            append_audit(
                self.store.roots.audit_path,
                action="cognitive_loop_cycle_completed",
                status=status,
                target=str(self.reports_path),
                details={
                    "cycle_id": cycle_id,
                    "step_count": len(steps),
                    "error_step_count": sum(1 for step in steps if step.get("status") == "error"),
                    **boundary_state,
                },
            )
            return result
        finally:
            coordinator.release_lock(self.lock_resource_id, owner=owner)

    def status(self) -> dict[str, Any]:
        reports = self.read_reports(limit=50)
        last = reports[-1] if reports else {}
        return {
            "schema_version": "memory-os.cognitive_loop_status.v0",
            "module": "cognitive_loop",
            "profile": self.profile,
            "report_count": len(reports),
            "last_status": str(last.get("status", "missing")),
            "last_cycle_id": str(last.get("cycle_id", "")),
            "last_finished_at": str(last.get("finished_at", "")),
            "boundaries": dict(BOUNDARIES),
            "report_path": str(self.reports_path),
        }

    def doctor(self) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        last = self.read_reports(limit=1)
        if not last:
            findings.append(
                {
                    "severity": "warning",
                    "code": "no_cognitive_loop_reports",
                    "message": "No cognitive loop cycle has run yet.",
                }
            )
        elif last[-1].get("status") == "error":
            findings.append(
                {
                    "severity": "error",
                    "code": "last_cognitive_loop_cycle_error",
                    "message": "The latest cognitive loop cycle ended in error.",
                }
            )
        status = "error" if any(item["severity"] == "error" for item in findings) else "warning" if findings else "ok"
        return {
            "schema_version": "memory-os.cognitive_loop_doctor.v0",
            "module": "cognitive_loop",
            "profile": self.profile,
            "status": status,
            "findings": findings,
            "boundaries": dict(BOUNDARIES),
        }

    def read_reports(self, *, limit: int = 20) -> list[dict[str, Any]]:
        if not self.reports_path.exists():
            return []
        reports: list[dict[str, Any]] = []
        for line in self.reports_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                reports.append(parsed)
        return reports[-max(limit, 0):]

    def _step_functions(
        self,
        *,
        max_events: int,
        apply: bool,
    ) -> list[tuple[str, Callable[[dict[str, Any]], dict[str, Any]]]]:
        return [
            ("heartbeat_pre", lambda context: self._heartbeat(max_events=max_events)),
            ("household_digest", self._household_digest),
            ("digest_consolidation", self._digest_consolidation),
            ("wandering_mind", self._wandering_mind),
            ("ops_gate", self._ops_gate),
            ("evidence_scoring", self._evidence_scoring),
            ("self_evolution", self._self_evolution),
            ("governance_feedback", lambda context: self._governance_feedback(context, apply=apply)),
            ("deep_reflection", lambda context: self._deep_reflection(context, apply=apply)),
            ("heartbeat_post", lambda context: self._heartbeat(max_events=max_events)),
            ("doctor_boundary_report", self._doctor_boundary_report),
        ]

    def _run_step(
        self,
        name: str,
        fn: Callable[[dict[str, Any]], dict[str, Any]],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        started = perf_counter()
        try:
            result = fn(context)
            context[name] = result
            status = _step_status(result)
            return {
                "step": name,
                "status": status,
                "duration_ms": int((perf_counter() - started) * 1000),
                "result": _bounded(result),
            }
        except Exception as exc:
            error = {
                "step": name,
                "status": "error",
                "duration_ms": int((perf_counter() - started) * 1000),
                "error": _clip(str(exc), 300),
            }
            context[name] = error
            return error

    def _heartbeat(self, *, max_events: int) -> dict[str, Any]:
        return MemoryOSRuntime(self.store).heartbeat(max_events=max_events)

    def _household_digest(self, context: dict[str, Any]) -> dict[str, Any]:
        from plugins.modules.context.household_digest import HouseholdDigestModule

        return HouseholdDigestModule(self.hermes_home, profile=self.profile).build_digest(
            store=self.store,
            min_events=1,
        )

    def _digest_consolidation(self, context: dict[str, Any]) -> dict[str, Any]:
        from plugins.modules.context.digest_consolidation import DigestConsolidationModule
        from plugins.modules.governance.proposal_queue import ProposalQueueModule

        module = DigestConsolidationModule(self.hermes_home, profile=self.profile)
        proposal_queue = ProposalQueueModule(self.hermes_home, profile=self.profile)
        today = date.today().isoformat()
        iso = date.today().isocalendar()
        week = f"{iso.year}-W{iso.week:02d}"
        daily = module.build_daily_digest(store=self.store, target_date=today, dry_run=False)
        weekly = module.build_weekly_consolidation(
            store=self.store,
            target_week=week,
            proposal_queue=proposal_queue,
            dry_run=False,
        )
        return {
            "schema_version": "memory-os.cognitive_loop.digest_consolidation.v0",
            "module": "digest_consolidation",
            "status": "ok",
            "daily": _bounded(daily),
            "weekly": _bounded(weekly),
            "actual_send": False,
            "actual_approve": False,
        }

    def _wandering_mind(self, context: dict[str, Any]) -> dict[str, Any]:
        from plugins.modules.cognition.wandering_mind import WanderingMindModule

        return WanderingMindModule(self.hermes_home, profile=self.profile).run_once(
            store=self.store,
            min_events=1,
        )

    def _ops_gate(self, context: dict[str, Any]) -> dict[str, Any]:
        from plugins.modules.governance.ops_gate import OpsGateModule

        return OpsGateModule(self.hermes_home, profile=self.profile).run_once(
            store=self.store,
            proposed_actions=[],
        )

    def _evidence_scoring(self, context: dict[str, Any]) -> dict[str, Any]:
        from plugins.modules.evidence.scoring import EvidenceScoringModule
        from plugins.modules.governance.proposal_queue import ProposalQueueModule

        evidence = EvidenceScoringModule(self.hermes_home, profile=self.profile)
        proposal_queue = ProposalQueueModule(self.hermes_home, profile=self.profile)
        context["evidence_scoring_instance"] = evidence
        context["proposal_queue_instance"] = proposal_queue
        return evidence.score_all(store=self.store, proposal_queue=proposal_queue)

    def _self_evolution(self, context: dict[str, Any]) -> dict[str, Any]:
        from plugins.modules.evidence.scoring import EvidenceScoringModule
        from plugins.modules.governance.ops_gate import OpsGateModule
        from plugins.modules.governance.proposal_queue import ProposalQueueModule
        from plugins.modules.governance.self_evolution import SelfEvolutionGovernorModule

        ops_gate = OpsGateModule(self.hermes_home, profile=self.profile)
        proposal_queue = context.get("proposal_queue_instance") or ProposalQueueModule(
            self.hermes_home,
            profile=self.profile,
        )
        evidence = context.get("evidence_scoring_instance") or EvidenceScoringModule(
            self.hermes_home,
            profile=self.profile,
        )
        governor = SelfEvolutionGovernorModule(self.hermes_home, profile=self.profile)
        context["ops_gate_instance"] = ops_gate
        context["proposal_queue_instance"] = proposal_queue
        context["evidence_scoring_instance"] = evidence
        context["self_evolution_instance"] = governor
        return governor.run_once(
            store=self.store,
            ops_gate=ops_gate,
            proposal_queue=proposal_queue,
            evidence_scoring=evidence,
        )

    def _governance_feedback(self, context: dict[str, Any], *, apply: bool) -> dict[str, Any]:
        from plugins.modules.evidence.scoring import EvidenceScoringModule
        from plugins.modules.governance.feedback_bridge import GovernanceFeedbackBridgeModule
        from plugins.modules.governance.ops_gate import OpsGateModule
        from plugins.modules.governance.proposal_queue import ProposalQueueModule
        from plugins.modules.governance.self_evolution import SelfEvolutionGovernorModule

        evidence = context.get("evidence_scoring_instance") or EvidenceScoringModule(
            self.hermes_home,
            profile=self.profile,
        )
        ops_gate = context.get("ops_gate_instance") or OpsGateModule(self.hermes_home, profile=self.profile)
        proposal_queue = context.get("proposal_queue_instance") or ProposalQueueModule(
            self.hermes_home,
            profile=self.profile,
        )
        governor = context.get("self_evolution_instance") or SelfEvolutionGovernorModule(
            self.hermes_home,
            profile=self.profile,
        )
        return GovernanceFeedbackBridgeModule(self.hermes_home, profile=self.profile).run_once(
            store=self.store,
            dry_run=not apply,
            evidence=evidence,
            ops_gate=ops_gate,
            proposal_queue=proposal_queue,
            self_evolution=governor,
        )

    def _deep_reflection(self, context: dict[str, Any], *, apply: bool) -> dict[str, Any]:
        from plugins.modules.cognition.deep_reflection import DeepReflectionModule
        from plugins.modules.governance.proposal_queue import ProposalQueueModule

        proposal_queue = context.get("proposal_queue_instance") or ProposalQueueModule(
            self.hermes_home,
            profile=self.profile,
        )
        return DeepReflectionModule(self.hermes_home, profile=self.profile).run_once(
            store=self.store,
            dry_run=not apply,
            proposal_queue=proposal_queue,
        )

    def _doctor_boundary_report(self, context: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": "memory-os.cognitive_loop.boundary_report.v0",
            "status": "ok",
            "event_count": len(self.store.read_events()),
            "candidate_count": len(read_candidate_queue(self.store)),
            "crystallized_record_count": _crystallized_record_count(self.store),
            "boundaries": dict(BOUNDARIES),
        }

    def _error_result(self, *, code: str, apply: bool, test_host: bool) -> dict[str, Any]:
        return {
            "schema_version": "memory-os.cognitive_loop.v0",
            "status": "error",
            "code": code,
            "profile": self.profile,
            "apply": apply,
            "test_host": test_host,
            "steps": [],
            "boundaries": dict(BOUNDARIES),
        }

    def _append_report(self, report: dict[str, Any]) -> None:
        self.reports_path.parent.mkdir(parents=True, exist_ok=True)
        with self.reports_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(_bounded(report), ensure_ascii=False, sort_keys=True))
            handle.write("\n")

    @staticmethod
    def _cycle_status(steps: list[dict[str, Any]], boundaries: dict[str, bool]) -> str:
        if any(boundaries.values()):
            return "error"
        if any(step.get("status") == "error" and step.get("step") == "doctor_boundary_report" for step in steps):
            return "error"
        if any(step.get("status") == "error" for step in steps):
            return "warning"
        if any(step.get("status") in {"warning", "skipped_dependency_failed"} for step in steps):
            return "warning"
        return "ok"


def _step_status(result: dict[str, Any]) -> str:
    status = str(result.get("status", "") or "").lower()
    if status in {"ok", "warning", "error", "deferred", "skipped_dependency_failed"}:
        return "warning" if status == "deferred" else status
    if result.get("output") == "[SILENT]" or result.get("reason"):
        return "warning"
    return "ok"


def _boundary_state(steps: list[dict[str, Any]]) -> dict[str, bool]:
    state = dict(BOUNDARIES)
    for step in steps:
        result = step.get("result", {})
        if not isinstance(result, dict):
            continue
        for key in BOUNDARY_KEYS:
            if _contains_true_boundary(result, key):
                state[key] = True
    return state


def _contains_true_boundary(payload: Any, key: str) -> bool:
    if isinstance(payload, dict):
        if payload.get(key) is True:
            return True
        return any(_contains_true_boundary(value, key) for value in payload.values())
    if isinstance(payload, list):
        return any(_contains_true_boundary(value, key) for value in payload)
    return False


def _bounded(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {
            str(key): _bounded(value)
            for key, value in payload.items()
            if str(key) not in {"raw_body", "body", "content", "transcript", "private_body", "raw_transcript"}
        }
    if isinstance(payload, list):
        return [_bounded(value) for value in payload[:20]]
    if isinstance(payload, str):
        return _clip(payload, 500)
    return payload


def _clip(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[:limit] + "...[truncated]"


def _crystallized_record_count(store: MemoryOSStore) -> int:
    if not store.roots.crystallized_root.exists():
        return 0
    return len([path for path in store.roots.crystallized_root.glob("*.md") if path.is_file()])
