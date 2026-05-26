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
