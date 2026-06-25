import json
from datetime import datetime, timezone

from plugins.memory.memory_os.fixtures import build_event, build_sannai_multi_root_fixture
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.schema import EventEnvelope
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.memory.memory_os.owner_actions import render_owner_review_digest
from plugins.modules.evidence.scoring import EvidenceScoringModule
from plugins.modules.governance.ops_gate import OpsGateModule
from plugins.modules.governance.proposal_queue import ProposalQueueModule
from plugins.modules.governance.self_evolution import SelfEvolutionGovernorModule, self_evolution_manifest
from plugins.system.lifecycle import ModuleLifecycle


def _store(tmp_path, *, profile="main"):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile=profile)
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def _seed_evidence(tmp_path, store):
    event = EventEnvelope.from_dict(
        {**build_event(seed=1, profile="main"), "summary": "The test host needs a safer dry-run workflow."}
    )
    store.append_event(event)
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    evidence = EvidenceScoringModule(tmp_path, profile="main")
    evidence.score_all(store=store, proposal_queue=proposal_queue)
    return proposal_queue, evidence


def test_self_evolution_manifest_requires_governance_dependencies(tmp_path):
    lifecycle = ModuleLifecycle(
        tmp_path,
        profile="main",
        available_dependencies=("memory_os", "scheduler", "ops_gate", "proposal_queue", "evidence_scoring"),
    )

    status = lifecycle.install(self_evolution_manifest())
    enabled = lifecycle.enable("self_evolution")

    assert status.installed is True
    assert enabled.enabled is True
    assert enabled.delivery_mode == "no-send"
    assert lifecycle.doctor("self_evolution").status == "ok"


def test_self_evolution_dry_run_writes_digest_and_proposal_through_queue(tmp_path):
    store = _store(tmp_path)
    proposal_queue, evidence = _seed_evidence(tmp_path, store)
    ops_gate = OpsGateModule(tmp_path, profile="main")
    module = SelfEvolutionGovernorModule(tmp_path, profile="main")

    result = module.run_once(
        store=store,
        ops_gate=ops_gate,
        proposal_queue=proposal_queue,
        evidence_scoring=evidence,
    )

    assert result["status"] == "ok"
    assert result["execution_mode"] == "dry-run"
    assert result["direct_self_modify"] is False
    assert result["actual_execute"] is False
    assert result["proposal_created"] is True
    assert result["agenda_candidate_status"] == "promoted_to_proposal"
    assert result["agenda_promotion_allowed"] is True
    queue = proposal_queue.read_queue()
    assert len(queue["items"]) == 1
    proposal = queue["items"][0]
    assert proposal["kind"] == "self_evolution"
    assert proposal["state"] == "candidate"
    assert proposal["crystallized_approved"] is False
    assert proposal["proposal_class"].startswith("self_evolution:")
    assert proposal["dedupe_key"].startswith(proposal["proposal_class"])
    assert proposal["proposal_quality"]["trigger_rule"] == "feature_maturity_top_signal"
    assert proposal["proposal_quality"]["evidence_ref_count"] >= 1
    assert proposal["proposal_quality"]["agenda_candidate_id"].startswith("agc_")
    assert proposal["proposal_quality"]["agenda_promotion_status"] == "promoted_to_proposal"
    assert proposal["proposal_quality"]["agenda_maturity_gate"] == "feature_maturity_top_signal"
    assert proposal["title"] != "Self-Evolution dry-run proposal"
    assert "具体改动:" in proposal["body"]
    assert "证据:" in proposal["body"]
    assert "验收标准:" in proposal["body"]
    assert "后续状态:" in proposal["body"]
    assert "Use the highest feature-maturity evidence signal" not in proposal["body"]
    assert all(ref.startswith("feature_score:") for ref in proposal["source_refs"])
    digest = module.digest_path.read_text(encoding="utf-8")
    assert "The test host needs a safer dry-run workflow." in digest
    assert "maturity_score=" in digest
    assert "hard-coded focus" not in digest
    audit_lines = store.roots.audit_path.read_text(encoding="utf-8").splitlines()
    assert any("self_evolution_dry_run_written" in line for line in audit_lines)
    agenda_candidates = module.read_agenda_candidates()
    assert len(agenda_candidates) == 1
    assert agenda_candidates[0]["status"] == "promoted_to_proposal"
    assert agenda_candidates[0]["promotion_allowed"] is True
    assert agenda_candidates[0]["proposal_id"] == proposal["candidate_id"]


def test_self_evolution_does_not_create_proposal_without_scores(tmp_path):
    store = _store(tmp_path)
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    evidence = EvidenceScoringModule(tmp_path, profile="main")
    ops_gate = OpsGateModule(tmp_path, profile="main")
    module = SelfEvolutionGovernorModule(tmp_path, profile="main")

    result = module.run_once(
        store=store,
        ops_gate=ops_gate,
        proposal_queue=proposal_queue,
        evidence_scoring=evidence,
    )

    assert result["status"] == "warning"
    assert result["proposal_created"] is False
    assert proposal_queue.read_queue()["items"] == []


def test_self_evolution_routes_action_through_ops_gate_report_only(tmp_path):
    store = _store(tmp_path)
    proposal_queue, evidence = _seed_evidence(tmp_path, store)
    ops_gate = OpsGateModule(tmp_path, profile="main")
    module = SelfEvolutionGovernorModule(tmp_path, profile="main")

    result = module.run_once(
        store=store,
        ops_gate=ops_gate,
        proposal_queue=proposal_queue,
        evidence_scoring=evidence,
    )

    assert result["ops_gate_decision"]["decision"] == "would_allow"
    assert result["ops_gate_decision"]["actual_execute"] is False
    assert ops_gate.read_reports()[0]["actual_execute"] is False


def test_self_evolution_skips_duplicate_unresolved_proposal(tmp_path):
    store = _store(tmp_path)
    proposal_queue, evidence = _seed_evidence(tmp_path, store)
    ops_gate = OpsGateModule(tmp_path, profile="main")
    module = SelfEvolutionGovernorModule(tmp_path, profile="main")

    first = module.run_once(
        store=store,
        ops_gate=ops_gate,
        proposal_queue=proposal_queue,
        evidence_scoring=evidence,
    )
    second = module.run_once(
        store=store,
        ops_gate=ops_gate,
        proposal_queue=proposal_queue,
        evidence_scoring=evidence,
    )
    status = module.status()
    queue = proposal_queue.read_queue()

    assert first["proposal_created"] is True
    assert second["proposal_created"] is False
    assert second["novelty_skipped"] is True
    assert second["reason"] == "duplicate_unresolved_proposal"
    assert second["existing_proposal_id"] == first["proposal_id"]
    assert len(queue["items"]) == 1
    assert status["proposal_count"] == 1
    assert status["novelty_skipped_count"] == 1
    assert status["duplicate_unresolved_proposal_count"] == 1
    assert len(ops_gate.read_reports()) == 8  # proposal_create + knob-tune x7


def test_self_evolution_cadence_skips_same_day_same_signal_after_closed_proposal(tmp_path):
    store = _store(tmp_path)
    proposal_queue, evidence = _seed_evidence(tmp_path, store)
    ops_gate = OpsGateModule(tmp_path, profile="main")
    module = SelfEvolutionGovernorModule(tmp_path, profile="main")

    first = module.run_once(
        store=store,
        ops_gate=ops_gate,
        proposal_queue=proposal_queue,
        evidence_scoring=evidence,
    )
    proposal_queue.transition(
        store=store,
        candidate_id=first["proposal_id"],
        decision="reject",
        reviewer="owner",
    )
    second = module.run_once(
        store=store,
        ops_gate=ops_gate,
        proposal_queue=proposal_queue,
        evidence_scoring=evidence,
    )
    status = module.status()

    assert first["proposal_created"] is True
    assert second["proposal_created"] is False
    assert second["skipped"] is True
    assert second["cadence_skipped"] is True
    assert second["reason"] == "cadence_same_day_same_signal"
    assert second["cadence_input_fingerprint"] == first["cadence_input_fingerprint"]
    assert len(proposal_queue.read_queue()["items"]) == 1
    assert len(ops_gate.read_reports()) == 8  # proposal_create + knob-tune x7
    assert status["proposal_count"] == 1
    assert status["cadence_skipped_count"] == 1
    assert status["same_signal_skipped_count"] == 1


def test_self_evolution_cadence_skips_same_day_expression_policy_history(tmp_path):
    store = _store(tmp_path)
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    old = proposal_queue.create_candidate(
        store=store,
        title="调整右脑表达策略：too_mechanical 反馈",
        body="具体改动: 已处理\n证据: owner feedback\n验收标准: monitor\n后续状态: applied",
        source_refs=["feature_score:older"],
        kind="expression_policy",
    )
    queue = proposal_queue.read_queue()
    for item in queue["items"]:
        if item["candidate_id"] == old["candidate_id"]:
            item["state"] = "approved_for_proposal"
            item["followup_state"] = "applied_expression_policy"
            item["execution_decision_state"] = "owner_applied_expression_policy"
    proposal_queue._write_queue(queue)
    feedback_path = store.roots.memory_os_root / "system" / "expression_feedback_ledger.jsonl"
    feedback_path.parent.mkdir(parents=True, exist_ok=True)
    feedback_path.write_text(
        json.dumps(
            {
                "schema_version": "hermes.memory_os.expression_feedback.v0",
                "feedback_id": "efb_existing",
                "profile": "main",
                "target_type": "expression",
                "target_id": "expr_existing",
                "rating": "too_mechanical",
                "source_module": "owner_action",
                "live_policy_changed": False,
                "raw_body_included": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    evidence = EvidenceScoringModule(tmp_path, profile="main")
    evidence.score_all(store=store, proposal_queue=proposal_queue)
    module = SelfEvolutionGovernorModule(tmp_path, profile="main")

    result = module.run_once(
        store=store,
        ops_gate=OpsGateModule(tmp_path, profile="main"),
        proposal_queue=proposal_queue,
        evidence_scoring=evidence,
    )

    assert result["proposal_created"] is False
    assert result["cadence_skipped"] is True
    assert result["reason"] == "cadence_same_day_same_signal"
    assert result["previous_proposal_id"] == old["candidate_id"]
    assert len(proposal_queue.read_queue()["items"]) == 1


def test_self_evolution_legacy_template_proposal_does_not_block_concrete_proposal(tmp_path):
    store = _store(tmp_path)
    proposal_queue, evidence = _seed_evidence(tmp_path, store)
    proposal_queue.create_candidate(
        store=store,
        title="Self-Evolution dry-run proposal",
        body="Use the highest feature-maturity evidence signal to prepare a reviewed governance improvement.",
        source_refs=["feature_score:legacy"],
        kind="self_evolution",
    )
    module = SelfEvolutionGovernorModule(tmp_path, profile="main")

    result = module.run_once(
        store=store,
        ops_gate=OpsGateModule(tmp_path, profile="main"),
        proposal_queue=proposal_queue,
        evidence_scoring=evidence,
    )

    assert result["proposal_created"] is True
    queue = proposal_queue.read_queue()
    assert len(queue["items"]) == 2
    new_proposal = queue["items"][-1]
    assert new_proposal["title"] != "Self-Evolution dry-run proposal"
    assert "具体改动:" in new_proposal["body"]


def test_self_evolution_creates_expression_policy_proposal_from_expression_feedback(tmp_path):
    store = _store(tmp_path)
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    feedback_path = store.roots.memory_os_root / "system" / "expression_feedback_ledger.jsonl"
    feedback_path.parent.mkdir(parents=True, exist_ok=True)
    feedback_path.write_text(
        json.dumps(
            {
                "schema_version": "hermes.memory_os.expression_feedback.v0",
                "feedback_id": "efb_1",
                "profile": "main",
                "target_type": "expression",
                "target_id": "expr_1",
                "outcome_id": "rbout_1",
                "request_id": "rbreq_1",
                "policy_version": 1,
                "rating": "too_mechanical",
                "source_module": "owner_action",
                "live_policy_changed": False,
                "raw_body_included": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    evidence = EvidenceScoringModule(tmp_path, profile="main")
    evidence.score_all(store=store, proposal_queue=proposal_queue)
    module = SelfEvolutionGovernorModule(tmp_path, profile="main")

    result = module.run_once(
        store=store,
        ops_gate=OpsGateModule(tmp_path, profile="main"),
        proposal_queue=proposal_queue,
        evidence_scoring=evidence,
    )

    assert result["proposal_created"] is True
    assert result["agenda_candidate_status"] == "promoted_to_proposal"
    proposal = proposal_queue.read_queue()["items"][0]
    assert proposal["kind"] == "expression_policy"
    assert proposal["proposal_class"] == "expression_policy:too_mechanical"
    assert proposal["dedupe_key"] == "expression_policy:too_mechanical"
    assert proposal["proposal_quality"]["trigger_rule"] == "expression_feedback_policy"
    assert proposal["proposal_quality"]["quality_gate"] == "linked_expression_feedback"
    assert proposal["proposal_quality"]["feedback_rating"] == "too_mechanical"
    assert proposal["proposal_quality"]["feedback_count"] == 1
    assert proposal["proposal_quality"]["linked_outcome_count"] == 1
    assert proposal["proposal_quality"]["unlinked_feedback_count"] == 0
    assert proposal["proposal_quality"]["outcome_refs"] == ["rbout_1"]
    assert proposal["proposal_quality"]["policy_versions"] == ["1"]
    assert proposal["proposal_quality"]["agenda_candidate_id"].startswith("agc_")
    assert proposal["proposal_quality"]["agenda_promotion_status"] == "promoted_to_proposal"
    assert proposal["proposal_quality"]["agenda_maturity_gate"] == "linked_expression_feedback"
    assert proposal["proposal_quality"]["direct_apply_allowed"] is False
    assert proposal["proposal_quality"]["generic_executor_allowed"] is False
    assert "调整右脑表达策略" in proposal["title"]
    assert "具体改动:" in proposal["body"]
    assert "证据:" in proposal["body"]
    assert "owner 标记右脑表达 too_mechanical" in proposal["body"]
    assert "linked_outcome_count=1" in proposal["body"]
    assert "outcomes=rbout_1" in proposal["body"]
    assert "policy_versions=1" in proposal["body"]
    assert "验收标准:" in proposal["body"]
    assert "后续状态:" in proposal["body"]
    assert proposal["actual_execute"] is False


def test_self_evolution_creates_memory_sources_policy_proposal_from_corrective_feedback(tmp_path):
    store = _store(tmp_path)
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    feedback_path = store.roots.memory_os_root / "system" / "memory_sources_feedback.jsonl"
    feedback_path.parent.mkdir(parents=True, exist_ok=True)
    feedback_path.write_text(
        json.dumps(
            {
                "schema_version": "memory-os.memory_sources_feedback.v0",
                "feedback_id": "msfb_policy_1",
                "created_at": "2026-05-27T00:00:00Z",
                "profile": "main",
                "memory_source_record_id": "msrc_policy_1",
                "route": "casual_continuity",
                "query_class": "low_clue_recall",
                "rating": "missing_context",
                "note": "candidate list missed the useful source",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    evidence = EvidenceScoringModule(tmp_path, profile="main")
    evidence.score_all(store=store, proposal_queue=proposal_queue)
    module = SelfEvolutionGovernorModule(tmp_path, profile="main")

    result = module.run_once(
        store=store,
        ops_gate=OpsGateModule(tmp_path, profile="main"),
        proposal_queue=proposal_queue,
        evidence_scoring=evidence,
    )

    assert result["proposal_created"] is True
    assert result["agenda_candidate_status"] == "promoted_to_proposal"
    proposal = proposal_queue.read_queue()["items"][0]
    assert proposal["kind"] == "memory_sources_policy"
    assert proposal["proposal_class"] == "memory_sources_policy:missing_context"
    assert proposal["dedupe_key"] == "memory_sources_policy:missing_context:casual_continuity:low_clue_recall"
    assert proposal["proposal_quality"]["trigger_rule"] == "memory_sources_feedback_policy"
    assert proposal["proposal_quality"]["quality_gate"] == "linked_corrective_memory_sources_feedback"
    assert proposal["proposal_quality"]["feedback_rating"] == "missing_context"
    assert proposal["proposal_quality"]["linked_memory_source_count"] == 1
    assert proposal["proposal_quality"]["memory_source_record_refs"] == ["msrc_policy_1"]
    assert proposal["proposal_quality"]["runtime_target"] == "context_retrieval_policy_review"
    assert proposal["proposal_quality"]["agenda_candidate_id"].startswith("agc_")
    assert proposal["proposal_quality"]["agenda_promotion_status"] == "promoted_to_proposal"
    assert proposal["proposal_quality"]["agenda_maturity_gate"] == "linked_corrective_memory_sources_feedback"
    assert proposal["proposal_quality"]["selected_equals_successful_use"] is False
    assert "调整记忆来源/召回策略" in proposal["title"]
    assert "selected 当 successful_use" in proposal["body"]
    assert "generic executor forbidden" in proposal["body"]
    assert proposal["actual_execute"] is False


def test_self_evolution_prioritizes_top_memory_sources_signal_over_stale_expression_feedback(tmp_path):
    store = _store(tmp_path)
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")

    class MixedFeedbackEvidence:
        def read_feature_scores(self):
            return [
                {
                    "feature_score_id": "feature_memory",
                    "subject_kind": "memory_sources_feedback",
                    "subject_ref": "memory_sources_feedback:msfb_new",
                    "evidence_refs": ["ev_mem"],
                    "maturity_score": 0.91,
                    "summary": "MemorySources missing_context owner feedback.",
                },
                {
                    "feature_score_id": "feature_expression",
                    "subject_kind": "expression_feedback",
                    "subject_ref": "expression_feedback:efb_old",
                    "evidence_refs": ["ev_expr"],
                    "maturity_score": 0.74,
                    "summary": "Older expression feedback.",
                },
            ]

        def read_scores(self):
            return []

        def read_evidence(self):
            return [
                {
                    "evidence_id": "ev_mem",
                    "subject_kind": "memory_sources_feedback",
                    "subject_ref": "memory_sources_feedback:msfb_new",
                    "feedback_rating": "missing_context",
                    "memory_source_record_id": "msrc_new",
                    "route": "candidate_review",
                    "query_class": "candidate_review",
                    "summary": "Owner said the selected sources missed key context.",
                },
                {
                    "evidence_id": "ev_expr",
                    "subject_kind": "expression_feedback",
                    "subject_ref": "expression_feedback:efb_old",
                    "feedback_rating": "too_mechanical",
                    "outcome_id": "rbout_old",
                    "request_id": "rbreq_old",
                    "policy_version": 1,
                    "summary": "Older expression feedback should not steal the top signal.",
                },
            ]

    module = SelfEvolutionGovernorModule(tmp_path, profile="main")

    result = module.run_once(
        store=store,
        ops_gate=OpsGateModule(tmp_path, profile="main"),
        proposal_queue=proposal_queue,
        evidence_scoring=MixedFeedbackEvidence(),
    )

    assert result["proposal_created"] is True
    assert result["proposal_class"] == "memory_sources_policy:missing_context"
    assert result["agenda_candidate_status"] == "promoted_to_proposal"
    proposal = proposal_queue.read_queue()["items"][0]
    assert proposal["kind"] == "memory_sources_policy"
    assert proposal["dedupe_key"] == "memory_sources_policy:missing_context:candidate_review:candidate_review"
    assert proposal["proposal_quality"]["trigger_rule"] == "memory_sources_feedback_policy"
    assert proposal["proposal_quality"]["memory_source_record_refs"] == ["msrc_new"]


def test_self_evolution_promotes_next_actionable_signal_when_top_signal_already_processed(tmp_path):
    store = _store(tmp_path)
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    now = datetime.now(timezone.utc).isoformat()
    memory_processed = proposal_queue.create_candidate(
        store=store,
        title="调整记忆来源/召回策略：missing_context 反馈",
        body="具体改动: tune retrieval\n证据: owner feedback\n验收标准: monitor\n后续状态: apply gate",
        source_refs=["feature_score:memory"],
        kind="memory_sources_policy",
        proposal_class="memory_sources_policy:missing_context",
        dedupe_key="memory_sources_policy:missing_context:candidate_review:candidate_review",
    )
    mechanical_processed = proposal_queue.create_candidate(
        store=store,
        title="调整右脑表达策略：too_mechanical 反馈",
        body="具体改动: tune expression\n证据: owner feedback\n验收标准: monitor\n后续状态: apply gate",
        source_refs=["feature_score:mechanical"],
        kind="expression_policy",
        proposal_class="expression_policy:too_mechanical",
        dedupe_key="expression_policy:too_mechanical",
    )
    queue = proposal_queue.read_queue()
    for item in queue["items"]:
        if item["candidate_id"] == memory_processed["candidate_id"]:
            item["state"] = "approved_for_proposal"
            item["followup_state"] = "applied_memory_sources_policy"
            item["updated_at"] = now
        if item["candidate_id"] == mechanical_processed["candidate_id"]:
            item["state"] = "owner_declined"
            item["followup_state"] = "closed"
            item["updated_at"] = now
    proposal_queue._write_queue(queue)

    class MixedProcessedEvidence:
        def read_feature_scores(self):
            return [
                {
                    "feature_score_id": "feature_memory",
                    "subject_kind": "memory_sources_feedback",
                    "subject_ref": "memory_sources_feedback:msfb_new",
                    "evidence_refs": ["ev_mem"],
                    "maturity_score": 0.91,
                },
                {
                    "feature_score_id": "feature_mechanical",
                    "subject_kind": "expression_feedback",
                    "subject_ref": "expression_feedback:efb_mechanical",
                    "evidence_refs": ["ev_mech"],
                    "maturity_score": 0.86,
                },
                {
                    "feature_score_id": "feature_frequency",
                    "subject_kind": "expression_feedback",
                    "subject_ref": "expression_feedback:efb_frequency",
                    "evidence_refs": ["ev_freq"],
                    "maturity_score": 0.84,
                },
            ]

        def read_scores(self):
            return []

        def read_evidence(self):
            return [
                {
                    "evidence_id": "ev_mem",
                    "subject_kind": "memory_sources_feedback",
                    "feedback_rating": "missing_context",
                    "memory_source_record_id": "msrc_new",
                    "route": "candidate_review",
                    "query_class": "candidate_review",
                },
                {
                    "evidence_id": "ev_mech",
                    "subject_kind": "expression_feedback",
                    "feedback_rating": "too_mechanical",
                    "outcome_id": "rbout_old",
                    "request_id": "rbreq_old",
                    "policy_version": 1,
                },
                {
                    "evidence_id": "ev_freq",
                    "subject_kind": "expression_feedback",
                    "feedback_rating": "too_frequent",
                    "outcome_id": "rbout_current",
                    "request_id": "rbreq_current",
                    "policy_version": 1,
                },
            ]

    module = SelfEvolutionGovernorModule(tmp_path, profile="main")

    result = module.run_once(
        store=store,
        ops_gate=OpsGateModule(tmp_path, profile="main"),
        proposal_queue=proposal_queue,
        evidence_scoring=MixedProcessedEvidence(),
    )

    assert result["proposal_created"] is True
    assert result["proposal_class"] == "expression_policy:too_frequent"
    assert result["agenda_candidate_status"] == "promoted_to_proposal"
    proposal = proposal_queue.read_queue()["items"][-1]
    assert proposal["kind"] == "expression_policy"
    assert proposal["proposal_quality"]["feedback_rating"] == "too_frequent"
    assert proposal["proposal_quality"]["linked_outcome_count"] == 1
    assert "owner 标记右脑表达 too_frequent" in proposal["body"]


def test_self_evolution_rejects_useful_memory_sources_feedback_as_report_only(tmp_path):
    store = _store(tmp_path)
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    feedback_path = store.roots.memory_os_root / "system" / "memory_sources_feedback.jsonl"
    feedback_path.parent.mkdir(parents=True, exist_ok=True)
    feedback_path.write_text(
        json.dumps(
            {
                "schema_version": "memory-os.memory_sources_feedback.v0",
                "feedback_id": "msfb_useful",
                "created_at": "2026-05-27T00:00:00Z",
                "profile": "main",
                "memory_source_record_id": "msrc_useful",
                "route": "casual_continuity",
                "query_class": "low_clue_recall",
                "rating": "useful",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    evidence = EvidenceScoringModule(tmp_path, profile="main")
    evidence.score_all(store=store, proposal_queue=proposal_queue)
    ops_gate = OpsGateModule(tmp_path, profile="main")
    module = SelfEvolutionGovernorModule(tmp_path, profile="main")

    result = module.run_once(
        store=store,
        ops_gate=ops_gate,
        proposal_queue=proposal_queue,
        evidence_scoring=evidence,
    )

    assert result["proposal_created"] is False
    assert result["proposal_quality_gate_failed"] is True
    assert result["agenda_candidate_status"] == "blocked_quality_gate"
    assert result["agenda_promotion_allowed"] is False
    assert result["quality_gate_reason"] == "memory_sources_feedback_requires_corrective_rating"
    assert proposal_queue.read_queue()["items"] == []
    assert ops_gate.read_reports() == []
    agenda_candidates = module.read_agenda_candidates()
    assert agenda_candidates[-1]["status"] == "blocked_quality_gate"
    assert agenda_candidates[-1]["reason"] == "memory_sources_feedback_requires_corrective_rating"


def test_self_evolution_rejects_unlinked_expression_feedback_as_low_quality_proposal_input(tmp_path):
    store = _store(tmp_path)
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    feedback_path = store.roots.memory_os_root / "system" / "expression_feedback_ledger.jsonl"
    feedback_path.parent.mkdir(parents=True, exist_ok=True)
    feedback_path.write_text(
        json.dumps(
            {
                "schema_version": "hermes.memory_os.expression_feedback.v0",
                "feedback_id": "efb_unlinked",
                "profile": "main",
                "target_type": "expression",
                "target_id": "expr_unlinked",
                "rating": "too_mechanical",
                "source_module": "owner_action",
                "live_policy_changed": False,
                "raw_body_included": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    evidence = EvidenceScoringModule(tmp_path, profile="main")
    evidence.score_all(store=store, proposal_queue=proposal_queue)
    ops_gate = OpsGateModule(tmp_path, profile="main")
    module = SelfEvolutionGovernorModule(tmp_path, profile="main")

    result = module.run_once(
        store=store,
        ops_gate=ops_gate,
        proposal_queue=proposal_queue,
        evidence_scoring=evidence,
    )

    assert result["proposal_created"] is False
    assert result["skipped"] is True
    assert result["proposal_quality_gate_failed"] is True
    assert result["reason"] == "proposal_quality_gate_failed"
    assert result["quality_gate_reason"] == "expression_feedback_requires_linked_outcome"
    assert result["agenda_candidate_status"] == "blocked_quality_gate"
    assert result["agenda_promotion_allowed"] is False
    assert result["proposal_class"] == "expression_policy:too_mechanical"
    assert proposal_queue.read_queue()["items"] == []
    assert ops_gate.read_reports() == []
    agenda_candidates = module.read_agenda_candidates()
    assert agenda_candidates[-1]["status"] == "blocked_quality_gate"
    assert agenda_candidates[-1]["promotion_allowed"] is False
    second = module.run_once(
        store=store,
        ops_gate=ops_gate,
        proposal_queue=proposal_queue,
        evidence_scoring=evidence,
    )
    assert second["proposal_created"] is False
    assert second["cadence_skipped"] is True
    assert second["reason"] == "cadence_same_day_same_signal"
    assert second["agenda_candidate_status"] == "skipped_same_day_same_signal"


def test_self_evolution_skips_unresolved_expression_policy_by_class(tmp_path):
    store = _store(tmp_path)
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    proposal_queue.create_candidate(
        store=store,
        title="调整右脑表达策略：too_mechanical 反馈",
        body="具体改动: tune policy\n证据: owner feedback\n验收标准: monitor\n后续状态: report-only",
        source_refs=["feature_score:older"],
        kind="expression_policy",
        proposal_class="expression_policy:too_mechanical",
        dedupe_key="expression_policy:too_mechanical",
    )
    feedback_path = store.roots.memory_os_root / "system" / "expression_feedback_ledger.jsonl"
    feedback_path.parent.mkdir(parents=True, exist_ok=True)
    feedback_path.write_text(
        json.dumps(
            {
                "schema_version": "hermes.memory_os.expression_feedback.v0",
                "feedback_id": "efb_2",
                "profile": "main",
                "target_type": "expression",
                "target_id": "expr_2",
                "outcome_id": "rbout_2",
                "request_id": "rbreq_2",
                "policy_version": 1,
                "rating": "too_mechanical",
                "source_module": "owner_action",
                "live_policy_changed": False,
                "raw_body_included": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    evidence = EvidenceScoringModule(tmp_path, profile="main")
    evidence.score_all(store=store, proposal_queue=proposal_queue)
    module = SelfEvolutionGovernorModule(tmp_path, profile="main")

    result = module.run_once(
        store=store,
        ops_gate=OpsGateModule(tmp_path, profile="main"),
        proposal_queue=proposal_queue,
        evidence_scoring=evidence,
    )

    assert result["proposal_created"] is False
    assert result["novelty_skipped"] is True
    assert result["reason"] == "duplicate_unresolved_proposal"
    assert result["agenda_candidate_status"] == "blocked_duplicate_unresolved"
    assert result["agenda_promotion_allowed"] is False
    assert result["proposal_class"] == "expression_policy:too_mechanical"
    assert len(proposal_queue.read_queue()["items"]) == 1


def test_self_evolution_concrete_proposal_is_owner_agenda_eligible(tmp_path):
    store = _store(tmp_path)
    proposal_queue, evidence = _seed_evidence(tmp_path, store)
    module = SelfEvolutionGovernorModule(tmp_path, profile="main")

    module.run_once(
        store=store,
        ops_gate=OpsGateModule(tmp_path, profile="main"),
        proposal_queue=proposal_queue,
        evidence_scoring=evidence,
    )

    rendered = render_owner_review_digest(store, digest_mode="agenda")

    assert len(rendered["sections"]["action_required"]) == 1
    assert rendered["counts"]["action_required_shown"] == 1
    assert "具体改动:" in rendered["text"]
    assert "验收标准:" in rendered["text"]
    assert "memory approve oa_" in rendered["text"]
    assert "Self-Evolution dry-run proposal" not in rendered["text"]


def test_self_evolution_doctor_reports_missing_dependencies_and_stale_digest(tmp_path):
    module = SelfEvolutionGovernorModule(tmp_path, profile="main")

    missing = module.doctor()
    stale = module.doctor(
        ops_gate=OpsGateModule(tmp_path, profile="main"),
        proposal_queue=ProposalQueueModule(tmp_path, profile="main"),
        evidence_scoring=EvidenceScoringModule(tmp_path, profile="main"),
    )

    assert missing["status"] == "error"
    assert missing["findings"][0]["code"] == "missing_required_runtime_dependency"
    assert stale["status"] == "warning"
    assert stale["findings"][0]["code"] == "runtime_digest_missing"


def test_self_evolution_status_does_not_expose_proposal_body(tmp_path):
    store = _store(tmp_path)
    proposal_queue, evidence = _seed_evidence(tmp_path, store)
    module = SelfEvolutionGovernorModule(tmp_path, profile="main")
    module.run_once(
        store=store,
        ops_gate=OpsGateModule(tmp_path, profile="main"),
        proposal_queue=proposal_queue,
        evidence_scoring=evidence,
    )

    status = module.status()

    rendered = json.dumps(status, ensure_ascii=False)
    assert status["proposal_count"] == 1
    assert "Use the highest evidence signal" not in rendered


def test_self_evolution_does_not_touch_sannai_shape_fixture(tmp_path):
    fixture = build_sannai_multi_root_fixture(tmp_path / "fixture")
    soul = fixture.hermes_home / "SOUL.md"
    before = soul.stat().st_mtime_ns
    store = _store(tmp_path / "main", profile="main")
    proposal_queue, evidence = _seed_evidence(tmp_path / "main", store)
    module = SelfEvolutionGovernorModule(tmp_path / "main", profile="main")

    module.run_once(
        store=store,
        ops_gate=OpsGateModule(tmp_path / "main", profile="main"),
        proposal_queue=proposal_queue,
        evidence_scoring=evidence,
    )

    assert soul.stat().st_mtime_ns == before
    assert not (fixture.hermes_home / "system-modules").exists()
