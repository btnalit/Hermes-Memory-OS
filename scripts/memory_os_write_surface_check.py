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
    "plugins/memory/memory_os/jsonl_io.py::_append_line_under_lock::path.open_a::target": "governed_io_primitive",
    "plugins/memory/memory_os/jsonl_io.py::locked_jsonl_file::path.open_a": "governed_io_primitive_lockfile",
    "plugins/memory/memory_os/execution_gate.py::start_execution_gate_envelope::append_jsonl_call::execution_gate_records_path(store.roots)": "execution_gate_permit_ledger",
    "plugins/memory/memory_os/execution_gate.py::complete_execution_gate_envelope::append_jsonl_call::execution_gate_records_path(store.roots)": "execution_gate_completion_ledger",
    "plugins/memory/memory_os/execution_gate.py::rotate_execution_gate_records::path.open_a::rotated_path": "execution_gate_retention_archive",
    "plugins/memory/memory_os/execution_gate.py::_append_jsonl::path.open_a::path": "execution_gate_private_writer",
    "plugins/memory/memory_os/v3_seed_evidence.py::run_v3_seed_evidence_cycle::append_jsonl_locked_call::v3_seed_edges_daily_path(store)": "v3_seed_evidence_daily_observation",
    "plugins/memory/memory_os/v3_seed_evidence.py::run_v3_seed_evidence_cycle::atomic_json_replace_call::v3_seed_evidence_snapshot_path(store)": "v3_seed_evidence_snapshot_observation",
    "plugins/memory/memory_os/v3_wandering.py::record_v3_wandering_run::append_jsonl_locked_call::v3_wandering_runs_path(store)": "v3_wandering_aggregate_run_ledger",
    "plugins/memory/memory_os/v3_body_packet.py::write_body_packet_manifest::governed_append_under_lock_call::target": "v3_body_packet_manifest",
    "plugins/memory/memory_os/v3_body_packet.py::remove_body_manifests::governed_atomic_rewrite_call::target": "v3_body_packet_manifest_retention",
    "plugins/memory/memory_os/wandering_journal.py::query_journal.mutate::governed_atomic_rewrite_call::wandering_journal_path(store)": "v3_private_query_trace",
    "plugins/memory/memory_os/wandering_journal.py::_mutate_journal::governed_atomic_rewrite_call::target": "v3_private_active_journal",
    "plugins/memory/memory_os/v3_retention.py::sweep_pending_expired::governed_atomic_status_call::v3_journal_sweep_status_path(store)": "v3_private_ttl_aggregate_status",
    "plugins/memory/memory_os/legacy_right_brain_retirement.py::retire_legacy_right_brain::atomic_json_replace_call::manifest_path": "legacy_right_brain_retirement_manifest",
    "plugins/memory/memory_os/legacy_right_brain_retirement.py::_recover_pending_retirement::atomic_json_replace_call::manifest_path": "legacy_right_brain_retirement_manifest_recovery",
    "plugins/memory/memory_os/legacy_right_brain_retirement.py::_disable_legacy_config::atomic_json_replace_call::path": "legacy_right_brain_retirement_config_disable",
    "plugins/memory/memory_os/left_brain_advisor.py::run_left_brain_advisor::append_jsonl_call::left_brain_advisor_reports_path(store.roots)": "left_brain_advisor_manual_fallback",
    "plugins/memory/memory_os/left_brain_advisor.py::_append_jsonl::path.open_a::path": "left_brain_advisor_private_manual_writer",
    "plugins/memory/memory_os/memory_projection.py::collect_and_project_signals::append_jsonl_call::memory_projection_records_path(store.roots)": "memory_projection_manual_fallback",
    "plugins/memory/memory_os/memory_projection.py::compact_memory_projection_records::append_jsonl_call::memory_projection_compactions_path(roots)": "memory_projection_compaction_audit",
    "plugins/memory/memory_os/memory_projection.py::_append_jsonl::path.open_a::path": "memory_projection_private_manual_writer",
    "plugins/memory/memory_os/memory_sources.py::append_memory_source_record::path.open_a::path": "memory_sources_existing_surface",
    "plugins/memory/memory_os/memory_sources.py::append_memory_source_feedback_record::path.open_a::path": "owner_feedback_surface",
    "plugins/memory/memory_os/owner_actions.py::_append_owner_review_rendered_digest::append_jsonl_call::path": "owner_review_render_surface",
    "plugins/memory/memory_os/owner_actions.py::_append_feedback::append_jsonl_call::feedback_ledger_path(store.roots)": "owner_feedback_surface",
    "plugins/memory/memory_os/owner_actions.py::_append_speak_ticket_unlocked::append_jsonl_call::speak_permission_tickets_path(store.roots)": "owner_gate_ticket_surface",
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
    "plugins/memory/memory_os/owner_actions.py::_write_right_brain_expression_policy_unlocked::append_jsonl_call::_right_brain_expression_policy_applies_path(store)": "owner_gated_policy_apply",
    "plugins/memory/memory_os/owner_actions.py::_write_proposal_queue_legacy_template_cleanup::append_jsonl_call::_proposal_queue_legacy_template_cleanup_applies_path(store)": "owner_gated_cleanup_apply",
    "plugins/memory/memory_os/owner_actions.py::_append_jsonl::path.open_a::path": "owner_actions_private_writer",
    "plugins/memory/memory_os/owner_actions.py::_rendered_digest_text::append_jsonl_call::store.roots.memory_os_root / 'system' / 'error_records.jsonl'": "owner_digest_error_record",
    "plugins/memory/memory_os/owner_actions.py::_candidate_aggregation_status_block::append_jsonl_call::store.roots.memory_os_root / 'system' / 'error_records.jsonl'": "owner_digest_error_record",
    "plugins/memory/memory_os/prefetch.py::_record_substrate_shadow_recall::path.open_a::path": "report_only_shadow_recall",
    "plugins/memory/memory_os/prefetch.py::_record_graph_layer_shadow::path.open_a::path": "report_only_graph_layer_shadow",
    "plugins/memory/memory_os/state_overlay.py::append_overlay_run::path.open_a::out_path": "state_overlay_run_ledger",
    "scripts/memory_os_entity_index_refresh.py::main::path.open_a::run_path": "entity_index_refresh_run_ledger",
    "plugins/memory/memory_os/permanent_promotion.py::ProposalLedger.create_or_get::append_under_lock_call::target": "permanent_promotion_proposal_ledger",
    "plugins/memory/memory_os/permanent_promotion.py::ProposalLedger.append_terminal::append_under_lock_call::target": "permanent_promotion_proposal_ledger",
    "plugins/memory/memory_os/permanent_promotion.py::ProposalLedger._append_locked::append_under_lock_call::target": "permanent_promotion_proposal_ledger_governed",
    "plugins/memory/memory_os/permanent_promotion.py::TokenLedger.issue::append_under_lock_call::target": "permanent_promotion_token_ledger",
    "plugins/memory/memory_os/permanent_promotion.py::TokenLedger.consume::append_under_lock_call::target": "permanent_promotion_token_ledger",
    "plugins/memory/memory_os/permanent_promotion.py::TokenLedger._append_locked::append_under_lock_call::target": "permanent_promotion_token_ledger_governed",
    "plugins/memory/memory_os/permanent_promotion.py::PermanentPromotionDeliveryLedger._append_locked::append_under_lock_call::target": "permanent_promotion_delivery_ledger_governed",
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
    "scripts/memory_os_right_brain_expression_outcome.py::_scan_outcomes_unlocked::path.open_a::outcomes_path": "right_brain_outcome_report_only",
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

    # ── Generalized append_jsonl_locked / _atomic_write_json detection ──────
    # These call sites were always live write surfaces but were invisible to
    # the scanner while the AST visitor only inspected them inside
    # v3_seed_evidence.py / v3_wandering.py. Generalizing the detection to
    # every scanned file (P2 fix) surfaced them for the first time; each is
    # classified below by what it already, truthfully, does — no behavior
    # changed, only visibility.
    "plugins/memory/memory_os/audit.py::append_audit::append_jsonl_locked_call::_audit_monthly_path(audit_path)": "audit_only",
    "plugins/memory/memory_os/clearance_receipts.py::write_clearance_receipt::append_jsonl_locked_call::path": "clearance_receipt_journal_ledger",
    "plugins/memory/memory_os/clearance_receipts.py::append_corpus_change_event::append_jsonl_locked_call::path": "corpus_change_event_ledger",
    "plugins/memory/memory_os/clearance_receipts.py::invalidate_receipts_by_judge_version::append_jsonl_locked_call::clearance_receipts_path(roots)": "clearance_receipt_invalidation_ledger",
    "plugins/memory/memory_os/clearance_receipts.py::invalidate_receipts_since::append_jsonl_locked_call::clearance_receipts_path(roots)": "clearance_receipt_invalidation_ledger",
    "plugins/memory/memory_os/deployment_runtime_manifest.py::write_deployment_runtime_manifest::atomic_json_replace_call::path": "deployment_runtime_manifest_write",
    "plugins/memory/memory_os/execution_gate.py::_append_jsonl::append_jsonl_locked_call::path": "execution_gate_private_writer",
    "plugins/memory/memory_os/exposure_rollup.py::run_exposure_rollup_cycle::append_jsonl_locked_call::_rollup_path(store)": "exposure_rollup_cycle_ledger",
    "plugins/memory/memory_os/index.py::_write_edge_canonical::append_jsonl_locked_call::edges_path": "graph_edge_canonical",
    "plugins/memory/memory_os/left_brain_advisor.py::_append_jsonl::append_jsonl_locked_call::path": "left_brain_advisor_private_manual_writer",
    "plugins/memory/memory_os/legacy_right_brain_retirement.py::_retire_legacy_right_brain_locked::atomic_json_replace_call::manifest_path": "legacy_right_brain_retirement_manifest",
    "plugins/memory/memory_os/memory_projection.py::_append_jsonl::append_jsonl_locked_call::path": "memory_projection_private_manual_writer",
    "plugins/memory/memory_os/memory_sources.py::append_memory_source_record::append_jsonl_locked_call::path": "memory_sources_existing_surface",
    "plugins/memory/memory_os/owner_actions.py::_append_jsonl::append_jsonl_locked_call::path": "owner_actions_private_writer",
    "plugins/memory/memory_os/permanent_promotion.py::_write_absorption_audit::append_jsonl_locked_call::path": "permanent_promotion_absorption_audit",
    "plugins/memory/memory_os/prefetch.py::_record_substrate_shadow_recall::append_jsonl_locked_call::path": "report_only_shadow_recall",
    "plugins/memory/memory_os/prefetch.py::_record_graph_layer_shadow::append_jsonl_locked_call::path": "report_only_graph_layer_shadow",
    "plugins/memory/memory_os/recall_policy.py::append_recall_observation::append_jsonl_locked_call::recall_observation_path(roots)": "recall_plan_shadow_observation_ledger",
    "plugins/memory/memory_os/session_mirror.py::_append_jsonl::append_jsonl_locked_call::path": "session_mirror_private_writer",
    "plugins/memory/memory_os/state_overlay.py::write_state_overlay::atomic_json_replace_call::out_path": "state_overlay_projection_write",
    "plugins/memory/memory_os/state_overlay.py::_write_overlay_quality::atomic_json_replace_call::out_dir / 'quality.json'": "state_overlay_quality_report",
    "plugins/memory/memory_os/community_shared.py::write_shared_memory::append_jsonl_locked_call::target": "community_shared_projection_sannai_only",
    "plugins/memory/memory_os/community_shared.py::write_newspaper_entry::append_jsonl_locked_call::target": "community_newspaper_trusted_ingress",
    "plugins/memory/memory_os/cognitive_loop.py::CognitiveLoopRunner._community_cycle::atomic_json_replace_call::cursor_path": "community_trigger_dedup_projection_state",
    "plugins/memory/memory_os/execution_gate.py::_write_gate_index::atomic_json_replace_call::_gate_index_path(roots)": "execution_gate_projection_index",
    "plugins/memory/memory_os/partner_create.py::create_partner::atomic_json_replace_call::memory_dir / 'state.json'": "community_partner_private_runtime_state",
    "plugins/memory/memory_os/community_partner_runtime.py::_save_partner_state::atomic_json_replace_call::partner_dir / 'memory' / 'state.json'": "community_partner_private_runtime_state",
    "plugins/memory/memory_os/community_partner_runtime.py::_append_note::open_a::notes_path": "community_partner_private_notes_log",
    "plugins/memory/memory_os/community_partner_runtime.py::run_once::open_a::replies_path": "community_partner_private_replies_log",
    "plugins/memory/memory_os/community_table.py::write_to_table::open_a::table_path": "community_table_bounded_shared_surface",
    "scripts/community_partner_reply.py::_write_table::open_a::table_path": "community_table_bounded_shared_surface",
    "scripts/community_partner_reply.py::<module>::open_a::partner_dir / 'replies.jsonl'": "community_partner_private_replies_log",
    # NOTE: writes the same sannai__{pid}.jsonl target as community_shared.py's
    # write_shared_memory(), but bypasses its actor=="sannai" gate entirely —
    # a direct, ungoverned duplicate write path. See roadmap 11.12 amendment.
    "scripts/community_partner_reply.py::<module>::open_a::shared_path": "community_shared_projection_cron_direct_ungoverned_duplicate",
    "scripts/community_partner_reply.py::<module>::open_a::notes_path": "community_partner_private_notes_log",
    "plugins/memory/memory_os/runtime.py::MemoryOSRuntime._write_state::atomic_json_replace_call::self._state_path": "memory_os_runtime_projection_state",
    "plugins/memory/memory_os/runtime.py::MemoryOSRuntime._write_heartbeat_error_fallback::atomic_json_replace_call::self.store.roots.memory_os_root / 'runtime' / 'heartbeat_error_fallback.json'": "runtime_error_fallback_projection",
    "plugins/memory/memory_os/session_mirror.py::SessionMirror._write_state::atomic_json_replace_call::self.state_path": "session_mirror_projection_state",
    "plugins/modules/governance/provisional_sweep.py::ProvisionalSweepModule.run_once::atomic_json_replace_call::p": "provisional_sweep_projection_report",
    "plugins/memory/memory_os/store.py::MemoryOSStore.append_event::append_jsonl_locked_call::path": "canonical_event_store",
    "plugins/memory/memory_os/store.py::MemoryOSStore.write_working_document::atomic_json_replace_call::path": "working_document_store",
    "plugins/memory/memory_os/store.py::MemoryOSStore._quarantine_malformed_event::append_jsonl_locked_call::quarantine_path": "quarantine_only",
    "plugins/memory/memory_os/structural_write_gate.py::append_governed_jsonl::append_jsonl_locked_call::destination": "structural_write_gate",
    "plugins/memory/memory_os/substrates/ledger.py::SubstrateOperationLedger.append::append_jsonl_locked_call::self.path": "substrate_governance_ledger",
    "plugins/memory/memory_os/substrates/projection.py::ProjectionLedger.append::append_jsonl_locked_call::self.path": "projection_coherence_ledger",
    "plugins/modules/cognition/deep_reflection.py::_append_jsonl::append_jsonl_locked_call::path": "module_private_writer_existing_surface",
    "plugins/modules/cognition/wandering_mind.py::_append_jsonl::append_jsonl_locked_call::path": "module_private_writer_existing_surface",
    "plugins/modules/context/digest_consolidation.py::DigestConsolidationModule.build_daily_digest::atomic_json_replace_call::artifact_path": "digest_consolidation_daily_artifact",
    "plugins/modules/context/digest_consolidation.py::DigestConsolidationModule.build_weekly_consolidation::atomic_json_replace_call::artifact_path": "digest_consolidation_weekly_artifact",
    "plugins/modules/evidence/confabulation.py::_append_jsonl::append_jsonl_locked_call::path": "module_private_writer_existing_surface",
    "plugins/modules/evidence/scoring.py::_append_jsonl::append_jsonl_locked_call::path": "module_private_writer_existing_surface",
    "plugins/modules/expression/expression_draft.py::_append_jsonl::append_jsonl_locked_call::path": "module_private_writer_existing_surface",
    "plugins/modules/governance/candidate_review.py::_append_jsonl::append_jsonl_locked_call::path": "module_private_writer_existing_surface",
    "plugins/modules/governance/cascade_routing_policy.py::_append_jsonl::append_jsonl_locked_call::path": "module_private_writer_existing_surface",
    "plugins/modules/governance/confidence_router.py::_append_jsonl::append_jsonl_locked_call::path": "module_private_writer_existing_surface",
    "plugins/modules/governance/crystallized_revalidator.py::_append_jsonl::append_jsonl_locked_call::path": "module_private_writer_existing_surface",
    "plugins/modules/governance/fact_judge.py::_append_verdict::append_jsonl_locked_call::path": "module_private_writer_existing_surface",
    "plugins/modules/governance/ground_truth_miner.py::_append_jsonl::append_jsonl_locked_call::path": "reversible_labels_private_manual_writer",
    "plugins/modules/governance/judge_calibration.py::_append_jsonl::append_jsonl_locked_call::path": "module_private_writer_existing_surface",
    "plugins/modules/governance/knob_ab_eval.py::KnobABEvalModule.run_once::append_jsonl_locked_call::self.runs_path": "module_report_only_existing_surface",
    "plugins/modules/governance/migration_controller.py::_append_jsonl::append_jsonl_locked_call::path": "module_private_writer_existing_surface",
    "plugins/modules/governance/ops_gate.py::OpsGateModule._append_report::append_jsonl_locked_call::self.reports_path": "ops_gate_report_only",
    "plugins/modules/governance/ops_gate.py::OpsGateModule._append_run::append_jsonl_locked_call::self.runs_path": "ops_gate_report_only",
    "plugins/modules/governance/override_sweep.py::OverrideSweepModule.run_once::append_jsonl_locked_call::self.runs_path": "module_report_only_existing_surface",
    "plugins/modules/governance/provisional.py::_append_jsonl::append_jsonl_locked_call::path": "module_report_only_existing_surface",
    "plugins/modules/governance/provisional_sweep.py::ProvisionalSweepModule.run_once::append_jsonl_locked_call::self.runs_path": "module_report_only_existing_surface",
    "plugins/modules/governance/self_evolution.py::SelfEvolutionGovernorModule._write_report::append_jsonl_locked_call::self.reports_path": "module_report_only_existing_surface",
    "plugins/modules/governance/self_evolution.py::SelfEvolutionGovernorModule._write_agenda_candidate::append_jsonl_locked_call::self.agenda_candidates_path": "self_evolution_agenda_report_only",
    "plugins/modules/governance/shadow_recall.py::_append_jsonl::append_jsonl_locked_call::path": "module_private_writer_existing_surface",
    "scripts/memory_os_candidate_aggregation_lane.py::main::append_jsonl_locked_call::store.roots.memory_os_root / 'system' / 'error_records.jsonl'": "owner_digest_error_record",
    "scripts/memory_os_execution_gate_runner.py::_update_sidecar_index::atomic_json_replace_call::index_path": "cron_execution_gate_sidecar_index",
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
        elif isinstance(node.func, ast.Name) and node.func.id == "append_jsonl_locked":
            # Generalized project-wide (was hardcoded to v3_seed_evidence.py /
            # v3_wandering.py only) — every direct call site to the governed
            # locked-append primitive must be classified, in whichever file
            # it appears.
            kind = "append_jsonl_locked_call"
            target = ast.unparse(node.args[0]) if node.args else ""
        elif isinstance(node.func, ast.Name) and node.func.id in {"_atomic_write_json", "write_json_atomic"}:
            # Every atomic JSON projection/state write must be explicitly
            # classified, including callers of the shared jsonl_io primitive.
            kind = "atomic_json_replace_call"
            target = ast.unparse(node.args[0]) if node.args else ""
        elif self.rel_path in {
            "plugins/memory/memory_os/v3_body_packet.py",
            "plugins/memory/memory_os/wandering_journal.py",
            "plugins/memory/memory_os/v3_retention.py",
        } and isinstance(node.func, ast.Name):
            if node.func.id == "_append_line_under_lock":
                kind = "governed_append_under_lock_call"
                target = ast.unparse(node.args[0]) if node.args else ""
            elif node.func.id == "_rewrite_records_under_lock":
                kind = "governed_atomic_rewrite_call"
                target = ast.unparse(node.args[0]) if node.args else ""
            elif node.func.id == "_write_status":
                kind = "governed_atomic_status_call"
                target = ast.unparse(node.args[0]) if node.args else ""
        elif (
            self.rel_path == "plugins/memory/memory_os/permanent_promotion.py"
            and isinstance(node.func, ast.Name)
            and node.func.id == "_append_line_under_lock"
        ):
            kind = "append_under_lock_call"
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
