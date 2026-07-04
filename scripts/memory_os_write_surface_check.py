#!/usr/bin/env python3
"""Static inventory for direct Memory-OS JSONL append surfaces."""

from __future__ import annotations

import argparse
import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


WRITE_SURFACE_SCHEMA_VERSION = "memory-os.write_surface_check.v0"


ALLOWED_WRITE_SURFACES: dict[str, str] = {
    "plugins/memory/memory_os/__init__.py::MemoryOSProvider._write_deferred_current_task_anchor::path.open_a::path": "legacy_manual_task_anchor",
    "plugins/memory/memory_os/__init__.py::MemoryOSProvider._write_active_task_anchor::path.open_a::path": "working_state_anchor_persistence",
    "plugins/memory/memory_os/__init__.py::MemoryOSProvider._supersede_active_anchors::path.open_a::path": "working_state_anchor_persistence",
    "plugins/memory/memory_os/__init__.py::MemoryOSProvider.on_session_end::path.open_a::path": "working_state_anchor_persistence",
    "plugins/memory/memory_os/audit.py::append_audit::path.open_a::audit_path": "audit_only",
    "plugins/memory/memory_os/cleanup.py::_archive_event_action::path.open_a::archive_path": "retention_archive",
    "plugins/memory/memory_os/cognitive_loop.py::CognitiveLoopRunner._append_report::path.open_a::self.reports_path": "cycle_report",
    "plugins/memory/memory_os/crystallized.py::append_candidate_queue::path.open_a::path": "candidate_queue_existing_surface",
    "plugins/memory/memory_os/jsonl_io.py::append_jsonl::path.open_a::target": "shared_jsonl_io_contract",
    # Governed IO primitives — classification follows caller (structural_write_gate or owner action)
    "plugins/memory/memory_os/jsonl_io.py::append_jsonl_locked::path.open_a::target": "governed_io_primitive",
    "plugins/memory/memory_os/jsonl_io.py::append_jsonl_lines_locked::path.open_a::target": "governed_io_primitive",
    "plugins/memory/memory_os/jsonl_io.py::locked_jsonl_file::path.open_a": "governed_io_primitive_lockfile",
    "plugins/memory/memory_os/execution_gate.py::start_execution_gate_envelope::append_jsonl_call::execution_gate_records_path(store.roots)": "execution_gate_permit_ledger",
    "plugins/memory/memory_os/execution_gate.py::complete_execution_gate_envelope::append_jsonl_call::execution_gate_records_path(store.roots)": "execution_gate_completion_ledger",
    "plugins/memory/memory_os/execution_gate.py::rotate_execution_gate_records::path.open_a::rotated_path": "execution_gate_retention_archive",
    "plugins/memory/memory_os/execution_gate.py::_append_jsonl::path.open_a::path": "execution_gate_private_writer",
    "plugins/memory/memory_os/left_brain_advisor.py::run_left_brain_advisor::append_jsonl_call::left_brain_advisor_reports_path(store.roots)": "left_brain_advisor_manual_fallback",
    "plugins/memory/memory_os/left_brain_advisor.py::_append_jsonl::path.open_a::path": "left_brain_advisor_private_manual_writer",
    "plugins/memory/memory_os/memory_projection.py::collect_and_project_signals::append_jsonl_call::memory_projection_records_path(store.roots)": "memory_projection_manual_fallback",
    "plugins/memory/memory_os/memory_projection.py::compact_memory_projection_records::append_jsonl_call::memory_projection_compactions_path(roots)": "memory_projection_compaction_audit",
    "plugins/memory/memory_os/memory_projection.py::_append_jsonl::path.open_a::path": "memory_projection_private_manual_writer",
    "plugins/memory/memory_os/memory_sources.py::append_memory_source_record::path.open_a::path": "memory_sources_existing_surface",
    "plugins/memory/memory_os/memory_sources.py::append_memory_source_feedback_record::path.open_a::path": "owner_feedback_surface",
    "plugins/memory/memory_os/owner_actions.py::_append_owner_review_rendered_digest::append_jsonl_call::path": "owner_review_render_surface",
    "plugins/memory/memory_os/owner_actions.py::_append_feedback::append_jsonl_call::feedback_ledger_path(store.roots)": "owner_feedback_surface",
    "plugins/memory/memory_os/owner_actions.py::_append_speak_ticket::append_jsonl_call::speak_permission_tickets_path(store.roots)": "owner_gate_ticket_surface",
    "plugins/memory/memory_os/owner_actions.py::_append_expression_feedback::append_jsonl_call::expression_feedback_ledger_path(store.roots)": "owner_feedback_surface",
    "plugins/memory/memory_os/owner_actions.py::_append_hindsight_curation_decision::append_jsonl_call::hindsight_curation_decisions_path(store.roots)": "owner_hindsight_curation_ledger",
    "plugins/memory/memory_os/owner_actions.py::_append_action_specific_ledger::append_jsonl_call::crystallization_approvals_path(store.roots)": "owner_action_specific_ledger",
    "plugins/memory/memory_os/owner_actions.py::_append_action_specific_ledger::append_jsonl_call::proposal_action_ledger_path(store.roots)": "owner_action_specific_ledger",
    "plugins/memory/memory_os/owner_actions.py::_append_action_specific_ledger::append_jsonl_call::path": "owner_action_specific_ledger",
    "plugins/memory/memory_os/owner_actions.py::_append_owner_action::append_jsonl_call::path": "owner_action_ledger",
    "plugins/memory/memory_os/owner_actions.py::_append_owner_review_delivery::append_jsonl_call::path": "owner_delivery_ledger",
    "plugins/memory/memory_os/owner_actions.py::_write_approved_proposal_execution_ticket::append_jsonl_call::approved_proposal_execution_tickets_path(store.roots)": "owner_approved_execution_ticket",
    "plugins/memory/memory_os/owner_actions.py::_write_deep_reflection_policy::append_jsonl_call::deep_reflection_policy_applies_path(store.roots)": "owner_gated_policy_apply",
    "plugins/memory/memory_os/owner_actions.py::_write_memory_sources_policy::append_jsonl_call::memory_sources_policy_applies_path(store.roots)": "owner_gated_policy_apply",
    "plugins/memory/memory_os/owner_actions.py::_write_right_brain_expression_policy::append_jsonl_call::_right_brain_expression_policy_applies_path(store)": "owner_gated_policy_apply",
    "plugins/memory/memory_os/owner_actions.py::_write_proposal_queue_legacy_template_cleanup::append_jsonl_call::_proposal_queue_legacy_template_cleanup_applies_path(store)": "owner_gated_cleanup_apply",
    "plugins/memory/memory_os/owner_actions.py::_append_jsonl::path.open_a::path": "owner_actions_private_writer",
    "plugins/memory/memory_os/owner_actions.py::_rendered_digest_text::append_jsonl_call::store.roots.memory_os_root / 'system' / 'error_records.jsonl'": "owner_digest_error_record",
    "plugins/memory/memory_os/prefetch.py::_record_substrate_shadow_recall::path.open_a::path": "report_only_shadow_recall",
    "plugins/memory/memory_os/prefetch.py::_record_graph_layer_shadow::path.open_a::path": "report_only_graph_layer_shadow",
    "plugins/memory/memory_os/session_mirror.py::SessionMirror._append_apply_record::append_jsonl_call::session_mirror_apply_records_path(self.store.roots)": "session_mirror_governed_apply_ledger",
    "plugins/memory/memory_os/session_mirror.py::_append_jsonl::path.open_a::path": "session_mirror_private_writer",
    "plugins/memory/memory_os/shadow_journal.py::ShadowJournalIngestion._quarantine_malformed::path.open_a::quarantine_path": "quarantine_only",
    "plugins/memory/memory_os/store.py::MemoryOSStore.append_event::path.open_a::path": "canonical_event_store",
    "plugins/memory/memory_os/index.py::_write_edge_canonical::append_jsonl_call::edges_path": "graph_edge_canonical",
    "plugins/memory/memory_os/store.py::MemoryOSStore.append_crystallized_record::path.open_a::path": "owner_gated_crystallized_store",
    "plugins/memory/memory_os/store.py::MemoryOSStore._quarantine_malformed_event::path.open_a::quarantine_path": "quarantine_only",
    "plugins/memory/memory_os/structural_write_gate.py::append_governed_jsonl::path.open_a::destination": "structural_write_gate",
    "plugins/memory/memory_os/substrates/ledger.py::SubstrateOperationLedger.append::path.open_a::self.path": "substrate_governance_ledger",
    "plugins/memory/memory_os/substrates/projection.py::ProjectionLedger.append::path.open_a::self.path": "projection_coherence_ledger",
    "scripts/memory_os_execution_gate_runner.py::_append_permit::append_jsonl_call::_records_path(hermes_home)": "cron_execution_gate_permit_ledger",
    "scripts/memory_os_execution_gate_runner.py::_append_completion::append_jsonl_call::_records_path(hermes_home)": "cron_execution_gate_completion_ledger",
    "scripts/memory_os_execution_gate_runner.py::_append_jsonl::path.open_a::path": "cron_execution_gate_private_writer",
    "scripts/memory_os_module_cadence_report.py::build_cadence_report::path.open_a::path": "monitor_report_surface",
    "scripts/memory_os_right_brain_expression.py::_record_request::path.open_a::path": "right_brain_request_report_only",
    "scripts/memory_os_right_brain_expression_outcome.py::scan_outcomes::path.open_a::outcomes_path": "right_brain_outcome_report_only",
    "plugins/modules/cognition/deep_reflection.py::DeepReflectionModule.run_once::append_jsonl_call::self.reports_path": "module_report_only_existing_surface",
    "plugins/modules/cognition/deep_reflection.py::DeepReflectionModule.build_injection_cards::append_jsonl_call::self.module_root / 'injection' / 'history.jsonl'": "module_report_only_existing_surface",
    "plugins/modules/cognition/deep_reflection.py::DeepReflectionModule.update_working_memory::append_jsonl_call::self.module_root / 'working_updates.jsonl'": "module_shadow_state_existing_surface",
    "plugins/modules/cognition/deep_reflection.py::DeepReflectionModule.emit_optional_outputs::append_jsonl_call::self.module_root / 'optional_outputs.jsonl'": "module_report_only_existing_surface",
    "plugins/modules/cognition/deep_reflection.py::DeepReflectionModule._append_wandering_seed::append_jsonl_call::self.wandering_seeds_path": "right_brain_seed_report_only",
    "plugins/modules/cognition/deep_reflection.py::_append_jsonl::path.open_a::path": "module_private_writer_existing_surface",
    "plugins/modules/cognition/imagination_loop.py::ImaginationLoopModule.run_once::append_jsonl_call::self.runs_path": "module_report_only_existing_surface",
    "plugins/modules/cognition/imagination_loop.py::_append_jsonl::path.open_a::path": "module_private_writer_existing_surface",
    "plugins/modules/cognition/wandering_mind.py::WanderingMindModule._append_output::append_jsonl_call::self.outputs_path": "right_brain_output_report_only",
    "plugins/modules/cognition/wandering_mind.py::WanderingMindModule._record_would_send::append_jsonl_call::self.would_send_path": "right_brain_would_send_report_only",
    "plugins/modules/cognition/wandering_mind.py::_append_jsonl::path.open_a::path": "module_private_writer_existing_surface",
    "plugins/modules/context/abstraction_distillation.py::_append_many_jsonl::path.open_a::path": "module_report_only_existing_surface",
    "plugins/modules/context/symbolic_offloader.py::SymbolicOffloaderModule.offload_entries::append_jsonl_call::self.reports_path": "optional_audit_level_report_only",
    "plugins/modules/context/symbolic_offloader.py::_append_jsonl::path.open_a::path": "module_private_writer_existing_surface",
    "plugins/modules/evidence/confabulation.py::ConfabulationDetectorModule.evaluate_records::append_jsonl_call::self.runs_path": "module_report_only_existing_surface",
    "plugins/modules/evidence/confabulation.py::_append_jsonl::path.open_a::path": "module_private_writer_existing_surface",
    "plugins/modules/evidence/scoring.py::EvidenceScoringModule.score_all::append_jsonl_call::self.runs_path": "module_report_only_existing_surface",
    "plugins/modules/evidence/scoring.py::_append_jsonl::path.open_a::path": "module_private_writer_existing_surface",
    "plugins/modules/expression/expression_draft.py::ExpressionDraftModule.create_draft::append_jsonl_call::self.drafts_path": "right_brain_draft_report_only",
    "plugins/modules/expression/expression_draft.py::_append_jsonl::path.open_a::path": "module_private_writer_existing_surface",
    "plugins/modules/expression/grounded_expression_judge.py::GroundedExpressionJudge._write_verdict::path.open_a::self.verdicts_path": "module_report_only_existing_surface",
    "plugins/modules/expression/speak_gate.py::SpeakGateModule._record_would_send::path.open_a::self.would_send_path": "right_brain_would_send_report_only",
    "plugins/modules/expression/speak_gate.py::SpeakGateModule._deliver_to_owner::path.open_a::deliveries_path": "owner_send_delivery_ledger",
    "plugins/modules/governance/candidate_review.py::CandidateReviewModule.review::append_jsonl_call::self.runs_path": "module_report_only_existing_surface",
    "plugins/modules/governance/candidate_review.py::_append_jsonl::path.open_a::path": "module_private_writer_existing_surface",
    "plugins/modules/governance/cascade_routing_policy.py::CascadeRoutingPolicyModule.propose_policy::append_jsonl_call::self.proposals_path": "route_score_proposal_report_only",
    "plugins/modules/governance/cascade_routing_policy.py::_append_jsonl::path.open_a::path": "module_private_writer_existing_surface",
    "plugins/modules/governance/confidence_router.py::ConfidenceRouterModule.route_records::append_jsonl_call::self.runs_path": "module_report_only_existing_surface",
    "plugins/modules/governance/confidence_router.py::_append_jsonl::path.open_a::path": "module_private_writer_existing_surface",
    "plugins/modules/governance/crystallized_revalidator.py::CrystallizedRevalidatorModule.evaluate::append_jsonl_call::self.runs_path": "module_report_only_existing_surface",
    "plugins/modules/governance/crystallized_revalidator.py::_append_jsonl::path.open_a::path": "module_private_writer_existing_surface",
    "plugins/modules/governance/fact_judge.py::_append_verdict::path.open_a::path": "module_private_writer_existing_surface",
    "plugins/modules/governance/ground_truth_miner.py::GroundTruthMinerModule.mine::append_jsonl_call::self.labels_path": "reversible_labels_manual_fallback",
    "plugins/modules/governance/ground_truth_miner.py::GroundTruthMinerModule.mine::append_jsonl_call::self.runs_path": "reversible_labels_manual_fallback",
    "plugins/modules/governance/ground_truth_miner.py::GroundTruthMinerModule.retract_label::append_jsonl_call::self.labels_path": "reversible_labels_owner_retraction",
    "plugins/modules/governance/ground_truth_miner.py::GroundTruthMinerModule.retract_label::append_jsonl_call::self.runs_path": "reversible_labels_owner_retraction",
    "plugins/modules/governance/ground_truth_miner.py::_append_jsonl::path.open_a::path": "reversible_labels_private_manual_writer",
    "plugins/modules/governance/judge_calibration.py::JudgeCalibrationMonitor.evaluate::append_jsonl_call::self.runs_path": "module_report_only_existing_surface",
    "plugins/modules/governance/judge_calibration.py::_append_jsonl::path.open_a::path": "module_private_writer_existing_surface",
    "plugins/modules/governance/migration_controller.py::MigrationControllerModule.evaluate::append_jsonl_call::self.runs_path": "module_report_only_existing_surface",
    "plugins/modules/governance/migration_controller.py::_append_jsonl::path.open_a::path": "module_private_writer_existing_surface",
    "plugins/modules/governance/ops_gate.py::OpsGateModule._append_report::path.open_a::self.reports_path": "ops_gate_report_only",
    "plugins/modules/governance/ops_gate.py::OpsGateModule._append_run::path.open_a::self.runs_path": "ops_gate_report_only",
    "plugins/modules/governance/provisional.py::ProvisionalModule.write_provisional::append_jsonl_call::self.runs_path": "module_report_only_existing_surface",
    "plugins/modules/governance/provisional.py::ProvisionalModule.evaluate_promotions::append_jsonl_call::self.runs_path": "module_report_only_existing_surface",
    "plugins/modules/governance/provisional.py::_append_jsonl::path.open_a::path": "module_private_writer_existing_surface",
    "plugins/modules/governance/provisional_sweep.py::ProvisionalSweepModule.run_once::path.open_a::self.runs_path": "module_report_only_existing_surface",
    "plugins/modules/governance/self_evolution.py::SelfEvolutionGovernorModule._write_report::path.open_a::self.reports_path": "module_report_only_existing_surface",
    "plugins/modules/governance/self_evolution.py::SelfEvolutionGovernorModule._write_agenda_candidate::path.open_a::self.agenda_candidates_path": "self_evolution_agenda_report_only",
    "plugins/modules/governance/shadow_recall.py::ShadowRecallModule.record_discards::append_jsonl_call::self.runs_path": "module_report_only_existing_surface",
    "plugins/modules/governance/shadow_recall.py::ShadowRecallModule.evaluate_recall_misses::append_jsonl_call::self.runs_path": "module_report_only_existing_surface",
    "plugins/modules/governance/shadow_recall.py::_append_jsonl::path.open_a::path": "module_private_writer_existing_surface",
    "plugins/modules/messaging/mailbox.py::MailboxNoSendModule.record_would_send::path.open_a::self.would_send_path": "mailbox_would_send_report_only",
    "plugins/memory/memory_os/knob_overrides.py::register_override::path.open_a::store_path": "knob_override_store",
    "plugins/memory/memory_os/knob_overrides.py::revert_override::path.open_a::store_path": "knob_override_store",
    "plugins/memory/memory_os/knob_overrides.py::confirm_override::path.open_a::store_path": "knob_override_store",
    "plugins/modules/governance/override_sweep.py::OverrideSweepModule.run_once::path.open_a::self.runs_path": "module_report_only_existing_surface",
    "plugins/modules/governance/knob_ab_eval.py::KnobABEvalModule.run_once::path.open_a::self.runs_path": "module_report_only_existing_surface",
}


@dataclass(frozen=True)
class WriteSurface:
    key: str
    rel_path: str
    qualname: str
    kind: str
    target: str
    line: int


def run_write_surface_check(repo_root: Path) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    surfaces = _scan_write_surfaces(root)
    unclassified = [surface for surface in surfaces if surface.key not in ALLOWED_WRITE_SURFACES]
    allowed = [
        {
            "key": surface.key,
            "classification": ALLOWED_WRITE_SURFACES[surface.key],
            "line": surface.line,
        }
        for surface in surfaces
        if surface.key in ALLOWED_WRITE_SURFACES
    ]
    return {
        "schema_version": WRITE_SURFACE_SCHEMA_VERSION,
        "status": "pass" if not unclassified else "fail",
        "surface_count": len(surfaces),
        "allowed_count": len(allowed),
        "unclassified_count": len(unclassified),
        "unclassified": [surface.__dict__ for surface in unclassified],
        "allowed_classification_counts": _classification_counts(allowed),
    }


def _scan_write_surfaces(root: Path) -> list[WriteSurface]:
    paths = [
        *sorted((root / "plugins" / "memory" / "memory_os").rglob("*.py")),
        *sorted((root / "plugins" / "modules").rglob("*.py")),
        *sorted((root / "scripts").glob("*.py")),
    ]
    surfaces: list[WriteSurface] = []
    for path in paths:
        rel_path = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        visitor = _WriteSurfaceVisitor(rel_path)
        visitor.visit(tree)
        surfaces.extend(visitor.surfaces)
    return surfaces


def _classification_counts(allowed: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in allowed:
        classification = str(item.get("classification") or "unknown")
        counts[classification] = counts.get(classification, 0) + 1
    return counts


class _WriteSurfaceVisitor(ast.NodeVisitor):
    def __init__(self, rel_path: str) -> None:
        self.rel_path = rel_path
        self.stack: list[str] = []
        self.surfaces: list[WriteSurface] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_Call(self, node: ast.Call) -> Any:
        kind = ""
        target = ""
        if isinstance(node.func, ast.Attribute) and node.func.attr == "open":
            if node.args and _constant_value(node.args[0]) == "a":
                kind = "path.open_a"
                target = ast.unparse(node.func.value)
        elif isinstance(node.func, ast.Name) and node.func.id == "open":
            if len(node.args) > 1 and _constant_value(node.args[1]) == "a":
                kind = "open_a"
                target = ast.unparse(node.args[0])
        elif isinstance(node.func, ast.Name) and node.func.id in {"_append_jsonl", "append_jsonl"}:
            kind = "append_jsonl_call"
            target = ast.unparse(node.args[0]) if node.args else ""
        if kind:
            qualname = ".".join(self.stack) or "<module>"
            key = f"{self.rel_path}::{qualname}::{kind}::{target}"
            self.surfaces.append(
                WriteSurface(
                    key=key,
                    rel_path=self.rel_path,
                    qualname=qualname,
                    kind=kind,
                    target=target,
                    line=int(getattr(node, "lineno", 0) or 0),
                )
            )
        self.generic_visit(node)


def _constant_value(node: ast.AST) -> Any:
    return node.value if isinstance(node, ast.Constant) else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output", choices=("json", "summary"), default="json")
    args = parser.parse_args(argv)
    report = run_write_surface_check(Path(args.repo_root))
    if args.output == "summary":
        print(
            "write_surface_check "
            f"status={report['status']} "
            f"surface_count={report['surface_count']} "
            f"unclassified_count={report['unclassified_count']}"
        )
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
