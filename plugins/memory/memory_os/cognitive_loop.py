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
from plugins.memory.memory_os.execution_gate import start_execution_gate_envelope
from plugins.memory.memory_os.runtime import MemoryOSRuntime
from plugins.memory.memory_os.signal_source_registry import signal_source_specs
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
            ("confidence_router", self._confidence_router),
            ("candidate_review", self._candidate_review),
            ("judge_calibration", self._judge_calibration),
            ("shadow_recall", self._shadow_recall),
            ("provisional", self._provisional),
            ("cascade_routing_policy", self._cascade_routing_policy),
            ("imagination_loop", self._imagination_loop),
            ("confabulation_detector", self._confabulation_detector),
            ("ground_truth_miner", self._ground_truth_miner),
            ("crystallized_revalidator", self._crystallized_revalidator),
            ("migration_controller", self._migration_controller),
            ("abstraction_distillation", self._abstraction_distillation),
            ("grounded_expression_judge", self._grounded_expression_judge),
            ("self_evolution", self._self_evolution),
            ("left_brain_pipeline_check", self._left_brain_pipeline_check),
            ("host_capability_probe", self._host_capability_probe),
            ("signal_collection", self._signal_collection),
            ("memory_projection", self._memory_projection),
            ("left_brain_advisor", self._left_brain_advisor),
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
        both_skipped = bool(daily.get("skipped") is True and weekly.get("skipped") is True)
        result = {
            "schema_version": "memory-os.cognitive_loop.digest_consolidation.v0",
            "module": "digest_consolidation",
            "status": "skipped" if both_skipped else "ok",
            "daily": _bounded(daily),
            "weekly": _bounded(weekly),
            "actual_send": False,
            "actual_approve": False,
        }
        if both_skipped:
            result.update(
                {
                    "skipped": True,
                    "cadence_skipped": True,
                    "reason": "unchanged_daily_and_weekly_digest",
                }
            )
        return result

    def _wandering_mind(self, context: dict[str, Any]) -> dict[str, Any]:
        from plugins.modules.cognition.wandering_mind import WanderingMindModule
        from plugins.modules.expression.expression_draft import ExpressionDraftModule
        from plugins.modules.expression.speak_gate import SpeakGateModule

        result = WanderingMindModule(self.hermes_home, profile=self.profile).run_once(
            store=self.store,
            min_events=1,
        )
        if result.get("cadence_skipped") is True or result.get("skipped") is True:
            return {
                **result,
                "expression_draft_skipped": True,
                "expression_draft_skip_reason": str(result.get("reason") or "wandering_mind_skipped"),
                "speak_gate_skipped": True,
                "speak_gate_skip_reason": str(result.get("reason") or "wandering_mind_skipped"),
            }
        if "output" not in result:
            return result

        draft_module = ExpressionDraftModule(self.hermes_home, profile=self.profile)
        output_text = str(result.get("output") or "")
        source_refs = [str(result.get("output_ref") or "wandering_mind")] if result.get("output_ref") else []
        draft = draft_module.create_draft(
            store=self.store,
            source_module="wandering_mind",
            text_preview=output_text,
            source_refs=source_refs,
            feeling_tags=["wandering"],
            risk_flags=[],
            silence_reason=str(result.get("reason") or "") if output_text.strip() == "[SILENT]" else None,
        )
        speak_gate = SpeakGateModule(self.hermes_home, profile=self.profile, delivery_mode="would-send")
        decision = speak_gate.evaluate_expression_draft(
            draft,
            channel="origin",
            delivery_tier="test_host_observation",
        )
        return {
            **result,
            "expression_draft_created": True,
            "expression_draft": _bounded(draft),
            "speak_gate_evaluated": True,
            "speak_gate_decision": decision,
            "speak_gate_actual_send": bool(decision.get("actual_send") is True),
        }

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

    def _confidence_router(self, context: dict[str, Any]) -> dict[str, Any]:
        from plugins.modules.evidence.scoring import EvidenceScoringModule
        from plugins.modules.governance.confidence_router import ConfidenceRouterModule

        evidence = context.get("evidence_scoring_instance") or EvidenceScoringModule(
            self.hermes_home,
            profile=self.profile,
        )
        context["evidence_scoring_instance"] = evidence
        result = ConfidenceRouterModule(self.hermes_home, profile=self.profile).route_all(scoring=evidence)
        context["confidence_router_result"] = result
        return result

    def _candidate_review(self, context: dict[str, Any]) -> dict[str, Any]:
        from plugins.modules.governance.candidate_review import CandidateReviewModule, FeaturePreRouter
        from plugins.modules.governance.confidence_router import ConfidenceRouterModule

        routes = ConfidenceRouterModule(self.hermes_home, profile=self.profile).read_routes()
        preroute = FeaturePreRouter().route(routes)
        review = CandidateReviewModule(self.hermes_home, profile=self.profile).review(preroute["items"])
        context["candidate_review_result"] = review
        return {
            "schema_version": "memory-os.cognitive_loop.candidate_review.v0",
            "module": "candidate_review",
            "status": review.get("status", "ok"),
            "preroute_count": int(preroute.get("item_count") or 0),
            "decision_count": int(review.get("decision_count") or 0),
            "candidate_review_live_applied": bool(review.get("candidate_review_live_applied")),
            "actual_send": False,
            "actual_execute": False,
            "canonical_state_changed": False,
        }

    def _judge_calibration(self, context: dict[str, Any]) -> dict[str, Any]:
        from plugins.modules.governance.judge_calibration import JudgeCalibrationMonitor

        review = context.get("candidate_review_result") if isinstance(context.get("candidate_review_result"), dict) else {}
        decisions = [
            {
                "case_id": str(item.get("subject_ref") or item.get("decision_id") or ""),
                "verdict": str(item.get("decision") or ""),
            }
            for item in review.get("decisions", [])
            if isinstance(item, dict)
        ]
        result = JudgeCalibrationMonitor(self.hermes_home, profile=self.profile).evaluate(
            decisions=decisions,
            canaries=[{"case_id": "canary_fast_discard", "expected": "discard", "verdict": "discard"}],
        )
        context["judge_calibration_result"] = result
        return result

    def _shadow_recall(self, context: dict[str, Any]) -> dict[str, Any]:
        from plugins.modules.governance.shadow_recall import ShadowRecallModule

        review = context.get("candidate_review_result") if isinstance(context.get("candidate_review_result"), dict) else {}
        discards = [
            {
                "subject_ref": str(item.get("subject_ref") or ""),
                "text": str(item.get("subject_ref") or item.get("decision_id") or ""),
                "route_intent": "auto_discard_candidate",
            }
            for item in review.get("decisions", [])
            if isinstance(item, dict) and str(item.get("decision") or "") == "downgrade"
        ]
        module = ShadowRecallModule(self.hermes_home, profile=self.profile)
        recorded = module.record_discards(discards)
        evaluated = module.evaluate_recall_misses([])
        result = {
            "schema_version": "memory-os.cognitive_loop.shadow_recall.v0",
            "module": "shadow_recall",
            "status": "ok",
            "fingerprint_count": int(recorded.get("fingerprint_count") or 0),
            "miss_hit_count": int(evaluated.get("miss_hit_count") or 0),
            "auto_discard_live_applied": False,
            "actual_send": False,
            "actual_execute": False,
            "canonical_state_changed": False,
        }
        context["shadow_recall_result"] = result
        return result

    def _provisional(self, context: dict[str, Any]) -> dict[str, Any]:
        from plugins.modules.governance.provisional import ProvisionalModule

        review = context.get("candidate_review_result") if isinstance(context.get("candidate_review_result"), dict) else {}
        candidates = [
            {
                "subject_ref": str(item.get("subject_ref") or ""),
                "decision": "keep",
                "maturity_score": 0.9,
                "source_refs": [str(item.get("decision_id") or "")],
            }
            for item in review.get("decisions", [])
            if isinstance(item, dict) and str(item.get("decision") or "") == "keep"
        ]
        module = ProvisionalModule(self.hermes_home, profile=self.profile)
        written = module.write_provisional(candidates)
        promotion = module.evaluate_promotions()
        result = {
            "schema_version": "memory-os.cognitive_loop.provisional.v0",
            "module": "provisional",
            "status": "ok",
            "provisional_count": int(written.get("provisional_count") or 0),
            "would_promote_count": int(promotion.get("would_promote_count") or 0),
            "auto_promote_live_applied": False,
            "actual_send": False,
            "actual_execute": False,
            "actual_crystallized_approval": False,
            "canonical_state_changed": False,
        }
        context["provisional_result"] = result
        return result

    def _cascade_routing_policy(self, context: dict[str, Any]) -> dict[str, Any]:
        from plugins.modules.governance.cascade_routing_policy import CascadeRoutingPolicyModule

        confidence = context.get("confidence_router_result") if isinstance(context.get("confidence_router_result"), dict) else {}
        distribution = confidence.get("band_distribution") if isinstance(confidence.get("band_distribution"), dict) else {}
        band_metrics = {
            str(band): {"n": int(count or 0), "error_rate": 0.0}
            for band, count in distribution.items()
        } or {"low": {"n": 0, "error_rate": 0.0}}
        result = CascadeRoutingPolicyModule(self.hermes_home, profile=self.profile).propose_policy(
            band_metrics=band_metrics,
            guardrails={"aa_passed": True, "honesty_passed": True, "min_n": 30},
        )
        context["cascade_routing_policy_result"] = result
        return result

    def _imagination_loop(self, context: dict[str, Any]) -> dict[str, Any]:
        from plugins.modules.cognition.imagination_loop import ImaginationLoopModule

        result = ImaginationLoopModule(self.hermes_home, profile=self.profile).run_once()
        context["imagination_loop_result"] = result
        return result

    def _confabulation_detector(self, context: dict[str, Any]) -> dict[str, Any]:
        from plugins.modules.evidence.confabulation import ConfabulationDetectorModule
        from plugins.modules.evidence.scoring import EvidenceScoringModule

        evidence = context.get("evidence_scoring_instance") or EvidenceScoringModule(
            self.hermes_home,
            profile=self.profile,
        )
        context["evidence_scoring_instance"] = evidence
        result = ConfabulationDetectorModule(self.hermes_home, profile=self.profile).run_once(scoring=evidence)
        context["confabulation_detector_result"] = result
        return result

    def _ground_truth_miner(self, context: dict[str, Any]) -> dict[str, Any]:
        from plugins.modules.governance.ground_truth_miner import (
            REVERSIBLE_LABELS_LANE_ID,
            REVERSIBLE_LABELS_RISK_CLASS,
            GroundTruthMinerModule,
            reversible_labels_scope,
        )

        scope = reversible_labels_scope(self.profile)
        permit = start_execution_gate_envelope(
            self.store,
            lane_id=REVERSIBLE_LABELS_LANE_ID,
            trigger_surface="cognitive_loop",
            risk_class=REVERSIBLE_LABELS_RISK_CLASS,
            human_approval_required=False,
            why_no_human_approval="retractable TTL/source-scoped labels only; no apply/send/policy/canonical/route-score writes",
            scope=scope,
            boundary=dict(BOUNDARIES),
        )
        result = GroundTruthMinerModule(self.hermes_home, profile=self.profile).run_once(
            store=self.store,
            execution_envelope_id=str(permit.get("execution_gate_envelope_id") or ""),
            expected_scope=scope,
        )
        context["ground_truth_miner_result"] = result
        return result

    def _crystallized_revalidator(self, context: dict[str, Any]) -> dict[str, Any]:
        from plugins.modules.governance.crystallized_revalidator import CrystallizedRevalidatorModule

        result = CrystallizedRevalidatorModule(self.hermes_home, profile=self.profile).run_once(store=self.store)
        context["crystallized_revalidator_result"] = result
        return result

    def _migration_controller(self, context: dict[str, Any]) -> dict[str, Any]:
        from plugins.modules.governance.migration_controller import MigrationControllerModule

        ground_truth = context.get("ground_truth_miner_result") if isinstance(context.get("ground_truth_miner_result"), dict) else {}
        evidence_scoring = (
            context.get("evidence_scoring_result")
            if isinstance(context.get("evidence_scoring_result"), dict)
            else context.get("evidence_scoring")
            if isinstance(context.get("evidence_scoring"), dict)
            else {}
        )
        imagination = context.get("imagination_loop_result") if isinstance(context.get("imagination_loop_result"), dict) else {}
        owner_feedback_count = int(evidence_scoring.get("expression_feedback_subject_count") or 0) + int(
            evidence_scoring.get("memory_sources_feedback_subject_count") or 0
        )
        result = MigrationControllerModule(self.hermes_home, profile=self.profile).evaluate(
            signals={
                "owner_label_count": int(
                    ground_truth.get("total_label_count")
                    or ground_truth.get("active_label_count")
                    or ground_truth.get("label_count")
                    or 0
                ),
                "owner_feedback_count": owner_feedback_count,
                "simulation_preheated": int(imagination.get("scenario_count") or 0) > 0,
                "confidence_router_green": True,
            }
        )
        context["migration_controller_result"] = result
        return result

    def _abstraction_distillation(self, context: dict[str, Any]) -> dict[str, Any]:
        from plugins.modules.context.abstraction_distillation import AbstractionDistillationModule

        events = sorted(self.store.read_events(), key=lambda event: event.ts)
        if not events:
            return {
                "schema_version": "memory-os.cognitive_loop.abstraction_distillation.v0",
                "module": "abstraction_distillation",
                "status": "warning",
                "reason": "no_events",
                "distillation_count": 0,
                "distillation_live_applied": False,
                "actual_send": False,
                "actual_execute": False,
            }
        event = events[-1]
        result = AbstractionDistillationModule(self.hermes_home, profile=self.profile).distill(
            source_ref=f"event:{event.id}",
            source_text=event.summary,
        )
        context["abstraction_distillation_result"] = result
        return result

    def _grounded_expression_judge(self, context: dict[str, Any]) -> dict[str, Any]:
        from plugins.modules.expression.grounded_expression_judge import GroundedExpressionJudge

        result = GroundedExpressionJudge(self.hermes_home, profile=self.profile).run_once(
            right_brain_result=context.get("wandering_mind") if isinstance(context.get("wandering_mind"), dict) else {},
            confabulation_result=(
                context.get("confabulation_detector_result")
                if isinstance(context.get("confabulation_detector_result"), dict)
                else {}
            ),
            evidence_result=context.get("evidence_scoring") if isinstance(context.get("evidence_scoring"), dict) else {},
        )
        context["grounded_expression_judge_result"] = result
        return result

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

    def _left_brain_pipeline_check(self, context: dict[str, Any]) -> dict[str, Any]:
        from plugins.modules.governance.pipeline_checker import LeftBrainPipelineCheckModule

        return LeftBrainPipelineCheckModule(self.hermes_home, profile=self.profile).run_once(
            store=self.store,
            write=True,
        )

    def _host_capability_probe(self, context: dict[str, Any]) -> dict[str, Any]:
        from plugins.memory.memory_os.host_capability_probe import probe_host_capabilities

        result = probe_host_capabilities(self.store.roots)
        context["host_capability_probe_result"] = result
        return result

    def _signal_collection(self, context: dict[str, Any]) -> dict[str, Any]:
        from plugins.memory.memory_os.signal_collectors import collect_signal_sources

        capabilities = context.get("host_capability_probe_result")
        if not isinstance(capabilities, dict):
            return {
                "schema_version": "memory-os.cognitive_loop.signal_collection.v0",
                "status": "skipped_dependency_failed",
                "reason": "host_capability_probe_missing",
                "raw_body_included": False,
                "actual_send": False,
                "actual_execute": False,
            }
        result = collect_signal_sources(
            self.store.roots,
            host_capabilities=capabilities,
            trigger_type="cognitive_loop",
        )
        context["signal_collection_result"] = result
        return result

    def _memory_projection(self, context: dict[str, Any]) -> dict[str, Any]:
        from plugins.memory.memory_os.memory_projection import collect_and_project_signals

        capabilities = context.get("host_capability_probe_result")
        if not isinstance(capabilities, dict):
            return {
                "schema_version": "memory-os.cognitive_loop.memory_projection.v0",
                "status": "skipped_dependency_failed",
                "reason": "host_capability_probe_missing",
                "raw_body_included": False,
                "actual_send": False,
                "actual_execute": False,
            }
        scope = {"source_count": len(signal_source_specs()), "profile": self.profile}
        permit = start_execution_gate_envelope(
            self.store,
            lane_id="memory_projection_collect",
            trigger_surface="cognitive_loop",
            risk_class="governance_projection",
            human_approval_required=False,
            why_no_human_approval="read-only signal projection; no apply/send/policy/canonical writes",
            scope=scope,
            boundary=dict(BOUNDARIES),
        )
        result = collect_and_project_signals(
            self.store,
            host_capabilities=capabilities,
            trigger_type="cognitive_loop",
            execution_envelope_id=str(permit.get("execution_gate_envelope_id") or ""),
            expected_scope=scope,
        )
        context["memory_projection_result"] = result
        return result

    def _left_brain_advisor(self, context: dict[str, Any]) -> dict[str, Any]:
        from plugins.memory.memory_os.left_brain_advisor import run_left_brain_advisor

        scope = {"projection_count": int((context.get("memory_projection_result") or {}).get("summary", {}).get("projection_count") or 0), "profile": self.profile}
        permit = start_execution_gate_envelope(
            self.store,
            lane_id="left_brain_advisor_report",
            trigger_surface="cognitive_loop",
            risk_class="governance_projection",
            human_approval_required=False,
            why_no_human_approval="report-only left-brain advisor; no apply/send/policy/canonical writes",
            scope=scope,
            boundary=dict(BOUNDARIES),
        )
        result = run_left_brain_advisor(
            self.store,
            write=True,
            trigger_type="cognitive_loop",
            execution_envelope_id=str(permit.get("execution_gate_envelope_id") or ""),
            expected_scope=scope,
        )
        context["left_brain_advisor_result"] = result
        return result

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
            handle.write(json.dumps(_bounded_report(report), ensure_ascii=False, sort_keys=True))
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
    if status in {"ok", "warning", "error", "deferred", "skipped", "skipped_dependency_failed"}:
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


def _bounded_report(report: dict[str, Any]) -> dict[str, Any]:
    bounded = _bounded(report)
    steps = report.get("steps") if isinstance(report.get("steps"), list) else []
    if steps:
        bounded["steps"] = [_bounded(step) for step in steps]
        bounded["step_summary"] = {
            "step_count": len(steps),
            "omitted_step_count": 0,
            "tail_step_statuses": {
                str(step.get("step") or ""): str(step.get("status") or "")
                for step in steps
                if isinstance(step, dict)
                and str(step.get("step") or "")
                in {
                    "left_brain_pipeline_check",
                    "host_capability_probe",
                    "signal_collection",
                    "memory_projection",
                    "left_brain_advisor",
                    "governance_feedback",
                    "deep_reflection",
                    "heartbeat_post",
                    "doctor_boundary_report",
                }
            },
        }
    return bounded


def _clip(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[:limit] + "...[truncated]"


def _crystallized_record_count(store: MemoryOSStore) -> int:
    if not store.roots.crystallized_root.exists():
        return 0
    return len([path for path in store.roots.crystallized_root.glob("*.md") if path.is_file()])
