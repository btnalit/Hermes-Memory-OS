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
    assert any(finding["code"] == "feature_score_live_applied" for finding in report["findings"])


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
        },
    )

    report = LeftBrainPipelineCheckModule(tmp_path, profile="main").run_once(store=store)
    status = LeftBrainPipelineCheckModule(tmp_path, profile="main").status()

    assert report["status"] == "ok"
    assert report["proposal_quality"]["owner_actionable_proposal_count"] == 1
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
