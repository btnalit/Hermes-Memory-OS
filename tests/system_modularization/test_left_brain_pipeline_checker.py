from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.modules.evidence.scoring import EvidenceScoringModule
from plugins.modules.governance.pipeline_checker import LeftBrainPipelineCheckModule
from plugins.modules.governance.proposal_queue import ProposalQueueModule


def _store(tmp_path, *, profile="main"):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile=profile)
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def test_left_brain_pipeline_checker_reports_approved_followup_without_execution(tmp_path):
    store = _store(tmp_path)
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    candidate = proposal_queue.create_candidate(store=store, title="Follow up", body="Report-only follow-up.")
    proposal_queue.transition(
        store=store,
        candidate_id=candidate["candidate_id"],
        decision="approve",
        reviewer="owner",
    )
    EvidenceScoringModule(tmp_path, profile="main").score_all(store=store, proposal_queue=proposal_queue)

    report = LeftBrainPipelineCheckModule(tmp_path, profile="main").run_once(store=store)

    assert report["schema_version"] == "hermes.memory_os.left_brain_pipeline_check.v0"
    assert report["status"] in {"ok", "warn"}
    assert report["approved_followup"]["approved_for_proposal_count"] == 1
    assert report["approved_followup"]["awaiting_ops_gate_count"] == 1
    assert report["execution_boundary"]["execution_ticket_count"] == 0
    assert report["execution_boundary"]["actual_execute"] is False


def test_left_brain_pipeline_checker_skips_rewriting_unchanged_report(tmp_path):
    store = _store(tmp_path)
    module = LeftBrainPipelineCheckModule(tmp_path, profile="main")

    first = module.run_once(store=store, write=True)
    persisted = module.report_path.read_text(encoding="utf-8")
    second = module.run_once(store=store, write=True)

    assert first["status"] == "ok"
    assert second["status"] == "ok"
    assert second["skipped"] is True
    assert second["cadence_skipped"] is True
    assert second["reason"] == "unchanged_pipeline_report"
    assert module.report_path.read_text(encoding="utf-8") == persisted


def test_left_brain_pipeline_checker_detects_live_feature_scoring_as_fail(tmp_path):
    store = _store(tmp_path)
    evidence = EvidenceScoringModule(tmp_path, profile="main")
    evidence.feature_scores_path.parent.mkdir(parents=True, exist_ok=True)
    evidence.feature_scores_path.write_text(
        '{"schema_version":"hermes.evidence_feature_score.v0","live_applied":true}\n',
        encoding="utf-8",
    )

    report = LeftBrainPipelineCheckModule(tmp_path, profile="main").run_once(store=store)

    assert report["status"] == "fail"
    finding = next(finding for finding in report["findings"] if finding["code"] == "feature_score_live_applied")
    assert finding["count"] == 1
    assert "live-shadow" in finding["message"]


def test_left_brain_pipeline_checker_warns_on_active_concrete_duplicate_proposals(tmp_path):
    store = _store(tmp_path)
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    for _ in range(2):
        proposal_queue.create_candidate(
            store=store,
            title="调整右脑表达策略：too_mechanical 反馈",
            body="具体改动: tune policy\n证据: owner feedback\n验收标准: monitor\n后续状态: report-only",
            kind="expression_policy",
            proposal_class="expression_policy:too_mechanical",
            dedupe_key="expression_policy:too_mechanical",
        )

    report = LeftBrainPipelineCheckModule(tmp_path, profile="main").run_once(store=store)

    assert report["status"] == "warn"
    assert report["duplicate_unresolved"]["active_duplicate_group_count"] == 1
    assert report["duplicate_unresolved"]["active_duplicate_candidate_count"] == 2
    assert any(finding["code"] == "duplicate_unresolved_proposals" for finding in report["findings"])


def test_left_brain_pipeline_checker_does_not_warn_for_legacy_template_duplicates(tmp_path):
    store = _store(tmp_path)
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    for _ in range(2):
        proposal_queue.create_candidate(
            store=store,
            title="Self-Evolution dry-run proposal",
            body="Use the highest feature-maturity evidence signal to prepare a reviewed governance improvement.",
            source_refs=["feature_score:legacy"],
            kind="self_evolution",
        )

    report = LeftBrainPipelineCheckModule(tmp_path, profile="main").run_once(store=store)

    assert report["status"] == "ok"
    assert report["duplicate_unresolved"]["active_duplicate_group_count"] == 0
    assert report["duplicate_unresolved"]["legacy_template_duplicate_group_count"] == 1
    assert not any(finding["code"] == "duplicate_unresolved_proposals" for finding in report["findings"])


def test_left_brain_pipeline_checker_tracks_followup_duplicates_without_owner_action_warn(tmp_path):
    store = _store(tmp_path)
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    for _ in range(2):
        candidate = proposal_queue.create_candidate(
            store=store,
            title="调整右脑表达策略：too_mechanical 反馈",
            body="具体改动: tune policy\n证据: owner feedback\n验收标准: monitor\n后续状态: report-only",
            kind="expression_policy",
            proposal_class="expression_policy:too_mechanical",
            dedupe_key="expression_policy:too_mechanical",
        )
        proposal_queue.transition(
            store=store,
            candidate_id=candidate["candidate_id"],
            decision="approve",
            reviewer="owner",
        )

    report = LeftBrainPipelineCheckModule(tmp_path, profile="main").run_once(store=store)

    assert report["status"] == "ok"
    assert report["duplicate_unresolved"]["active_duplicate_group_count"] == 0
    assert report["duplicate_unresolved"]["followup_duplicate_group_count"] == 1
    assert report["approved_followup"]["approved_for_proposal_count"] == 2


def test_left_brain_pipeline_checker_accepts_mature_expression_policy_proposal(tmp_path):
    store = _store(tmp_path)
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    proposal_queue.create_candidate(
        store=store,
        title="调整右脑表达策略：too_mechanical 反馈",
        body=(
            "具体改动: tune expression policy\n"
            "证据: linked outcome rbout_1\n"
            "验收标准: monitor shows owner feedback improved\n"
            "后续状态: explicit apply only"
        ),
        kind="expression_policy",
        proposal_class="expression_policy:too_mechanical",
        dedupe_key="expression_policy:too_mechanical",
        proposal_quality={
            "quality_gate": "linked_expression_feedback",
            "feedback_rating": "too_mechanical",
            "feedback_count": 1,
            "linked_outcome_count": 1,
            "runtime_target": "expression_policy",
            "direct_apply_allowed": False,
            "generic_executor_allowed": False,
            "agenda_candidate_id": "agc_expression_1",
            "agenda_maturity_gate": "linked_expression_feedback",
            "agenda_promotion_status": "promoted_to_proposal",
        },
    )

    report = LeftBrainPipelineCheckModule(tmp_path, profile="main").run_once(store=store)
    status = LeftBrainPipelineCheckModule(tmp_path, profile="main").status()

    assert report["status"] == "ok"
    assert report["proposal_quality"]["owner_actionable_proposal_count"] == 1
    assert report["proposal_quality"]["agenda_trace_missing_count"] == 0
    assert report["proposal_quality"]["expression_policy_quality_ready_count"] == 1
    assert report["proposal_quality"]["expression_policy_quality_blocked_count"] == 0
    assert not any(finding["code"] == "expression_policy_proposal_quality_gap" for finding in report["findings"])
    assert status["expression_policy_quality_ready_count"] == 1


def test_left_brain_pipeline_checker_warns_on_unmature_expression_policy_proposal(tmp_path):
    store = _store(tmp_path)
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    proposal_queue.create_candidate(
        store=store,
        title="调整右脑表达策略：too_mechanical 反馈",
        body="具体改动: tune expression policy\n证据: owner feedback\n验收标准: monitor\n后续状态: explicit apply",
        kind="expression_policy",
        proposal_class="expression_policy:too_mechanical",
        dedupe_key="expression_policy:too_mechanical",
        proposal_quality={
            "quality_gate": "linked_expression_feedback",
            "feedback_rating": "too_mechanical",
            "feedback_count": 1,
            "linked_outcome_count": 0,
            "runtime_target": "expression_policy",
            "direct_apply_allowed": False,
            "generic_executor_allowed": False,
        },
    )

    report = LeftBrainPipelineCheckModule(tmp_path, profile="main").run_once(store=store)

    assert report["status"] == "warn"
    assert report["proposal_quality"]["expression_policy_quality_ready_count"] == 0
    assert report["proposal_quality"]["expression_policy_quality_blocked_count"] == 1
    assert report["proposal_quality"]["expression_policy_unlinked_quality_count"] == 1
    assert any(finding["code"] == "expression_policy_proposal_quality_gap" for finding in report["findings"])


def test_left_brain_pipeline_checker_warns_when_owner_actionable_proposal_lacks_agenda_trace(tmp_path):
    store = _store(tmp_path)
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    proposal_queue.create_candidate(
        store=store,
        title="调整右脑表达策略：too_mechanical 反馈",
        body=(
            "具体改动: tune expression policy\n"
            "证据: linked outcome rbout_1\n"
            "验收标准: monitor shows owner feedback improved\n"
            "后续状态: explicit apply only"
        ),
        kind="expression_policy",
        proposal_class="expression_policy:too_mechanical",
        dedupe_key="expression_policy:too_mechanical",
        proposal_quality={
            "quality_gate": "linked_expression_feedback",
            "feedback_rating": "too_mechanical",
            "feedback_count": 1,
            "linked_outcome_count": 1,
            "runtime_target": "expression_policy",
            "direct_apply_allowed": False,
            "generic_executor_allowed": False,
        },
    )

    report = LeftBrainPipelineCheckModule(tmp_path, profile="main").run_once(store=store)

    assert report["status"] == "warn"
    assert report["proposal_quality"]["agenda_trace_missing_count"] == 1
    assert any(finding["code"] == "proposal_agenda_trace_missing" for finding in report["findings"])


def test_left_brain_pipeline_checker_accepts_mature_memory_sources_policy_proposal(tmp_path):
    store = _store(tmp_path)
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    proposal_queue.create_candidate(
        store=store,
        title="调整记忆来源/召回策略：missing_context 反馈",
        body=(
            "具体改动: review low-clue source policy\n"
            "证据: linked MemorySources feedback msrc_1\n"
            "验收标准: monitor shows candidate coverage\n"
            "后续状态: explicit apply only"
        ),
        kind="memory_sources_policy",
        proposal_class="memory_sources_policy:missing_context",
        dedupe_key="memory_sources_policy:missing_context:casual_continuity:low_clue_recall",
        proposal_quality={
            "quality_gate": "linked_corrective_memory_sources_feedback",
            "feedback_rating": "missing_context",
            "feedback_count": 1,
            "linked_memory_source_count": 1,
            "memory_source_record_refs": ["msrc_1"],
            "routes": ["casual_continuity"],
            "query_classes": ["low_clue_recall"],
            "runtime_target": "context_retrieval_policy_review",
            "direct_apply_allowed": False,
            "generic_executor_allowed": False,
            "selected_equals_successful_use": False,
            "agenda_candidate_id": "agc_memory_sources_1",
            "agenda_maturity_gate": "linked_corrective_memory_sources_feedback",
            "agenda_promotion_status": "promoted_to_proposal",
        },
    )

    report = LeftBrainPipelineCheckModule(tmp_path, profile="main").run_once(store=store)
    status = LeftBrainPipelineCheckModule(tmp_path, profile="main").status()

    assert report["status"] == "ok"
    assert report["proposal_quality"]["agenda_trace_missing_count"] == 0
    assert report["proposal_quality"]["memory_sources_policy_quality_ready_count"] == 1
    assert report["proposal_quality"]["memory_sources_policy_quality_blocked_count"] == 0
    assert not any(finding["code"] == "memory_sources_policy_proposal_quality_gap" for finding in report["findings"])
    assert status["memory_sources_policy_quality_ready_count"] == 1


def test_left_brain_pipeline_checker_warns_on_unmature_memory_sources_policy_proposal(tmp_path):
    store = _store(tmp_path)
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    proposal_queue.create_candidate(
        store=store,
        title="调整记忆来源/召回策略：missing_context 反馈",
        body="具体改动: review source policy\n证据: owner feedback\n验收标准: monitor\n后续状态: explicit apply",
        kind="memory_sources_policy",
        proposal_class="memory_sources_policy:missing_context",
        dedupe_key="memory_sources_policy:missing_context:casual_continuity:low_clue_recall",
        proposal_quality={
            "quality_gate": "linked_corrective_memory_sources_feedback",
            "feedback_rating": "missing_context",
            "feedback_count": 1,
            "linked_memory_source_count": 0,
            "runtime_target": "context_retrieval_policy_review",
            "direct_apply_allowed": False,
            "generic_executor_allowed": False,
            "selected_equals_successful_use": False,
        },
    )

    report = LeftBrainPipelineCheckModule(tmp_path, profile="main").run_once(store=store)

    assert report["status"] == "warn"
    assert report["proposal_quality"]["memory_sources_policy_quality_ready_count"] == 0
    assert report["proposal_quality"]["memory_sources_policy_quality_blocked_count"] == 1
    assert report["proposal_quality"]["memory_sources_policy_unlinked_quality_count"] == 1
    assert any(finding["code"] == "memory_sources_policy_proposal_quality_gap" for finding in report["findings"])
