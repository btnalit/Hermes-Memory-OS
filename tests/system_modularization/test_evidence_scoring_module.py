import json

import pytest

from plugins.memory.memory_os.crystallized import CrystallizedCandidate, append_candidate_queue
from plugins.memory.memory_os.fixtures import build_event, build_sannai_multi_root_fixture
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.schema import EventEnvelope
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.memory.memory_os.working import WorkingMemoryService
from plugins.modules.evidence.scoring import EvidenceScoringModule, evidence_scoring_manifest
from plugins.modules.governance.proposal_queue import ProposalQueueModule
from plugins.system.lifecycle import ModuleLifecycle


def _store(tmp_path, *, profile="main"):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile=profile)
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def _seed_scoring_inputs(tmp_path, store):
    event = EventEnvelope.from_dict(
        {**build_event(seed=1, profile="main"), "summary": "Owner asked for explainable scoring."}
    )
    store.append_event(event)
    WorkingMemoryService(store).add_item(
        "lingering",
        "Keep the scoring explanation traceable.",
        source_event_id=event.id,
        tags=["test"],
    )
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    proposal_queue.create_candidate(
        store=store,
        title="Add scoring report",
        body="Create a dry-run evidence scoring report.",
        source_refs=[f"event:{event.id}"],
    )
    append_candidate_queue(
        store,
        CrystallizedCandidate(
            candidate_id="cand-score-1",
            kind="moment",
            body="Candidate body should not be auto-approved.",
            source_event_ids=[event.id],
            tags=["test"],
            bridge_state="inner_drive_candidate",
        ),
    )
    return proposal_queue


def test_evidence_scoring_manifest_installs_through_lifecycle(tmp_path):
    lifecycle = ModuleLifecycle(
        tmp_path,
        profile="main",
        available_dependencies=("memory_os", "scheduler"),
    )

    status = lifecycle.install(evidence_scoring_manifest())
    enabled = lifecycle.enable("evidence_scoring")

    assert status.installed is True
    assert enabled.enabled is True
    assert enabled.delivery_mode == "no-send"
    assert lifecycle.doctor("evidence_scoring").status == "ok"


def test_evidence_scoring_writes_explainable_scores_for_all_supported_subjects(tmp_path):
    store = _store(tmp_path)
    proposal_queue = _seed_scoring_inputs(tmp_path, store)
    module = EvidenceScoringModule(tmp_path, profile="main")

    result = module.score_all(store=store, proposal_queue=proposal_queue)

    assert result["status"] == "ok"
    assert result["score_count"] == 4
    assert result["working_active_subject_count"] == 1
    assert result["working_expired_skipped_count"] == 0
    assert result["actual_approve"] is False
    assert result["self_evolution_triggered"] is False
    scores = module.read_scores()
    assert {score["subject_kind"] for score in scores} == {
        "event",
        "working",
        "proposal",
        "crystallized_candidate",
    }
    for score in scores:
        assert score["evidence_refs"]
        assert score["explanation_ref"]
        assert score["explanation"]
        assert 0.0 <= score["score"] <= 1.0
        assert score["accepted_without_evidence"] is False
    evidence_ids = {record["evidence_id"] for record in module.read_evidence()}
    assert evidence_ids
    assert all(ref in evidence_ids for score in scores for ref in score["evidence_refs"])
    audit_lines = store.roots.audit_path.read_text(encoding="utf-8").splitlines()
    assert any("evidence_scoring_run_written" in line for line in audit_lines)


def test_evidence_scoring_skips_expired_working_items(tmp_path):
    store = _store(tmp_path)
    event = EventEnvelope.from_dict(
        {**build_event(seed=2, profile="main"), "summary": "Owner discussed stale working cleanup."}
    )
    store.append_event(event)
    active = WorkingMemoryService(store).add_item(
        "lingering",
        "Active working evidence should remain scoreable.",
        source_event_id=event.id,
        tags=["test"],
    )
    expired = WorkingMemoryService(store).add_item(
        "lingering",
        "Expired working evidence should not drive scoring.",
        source_event_id=event.id,
        tags=["test"],
    )
    document = store.read_working_document("lingering")
    for item in document["items"]:
        if item["id"] == expired.id:
            item["status"] = "expired"
    store.write_working_document("lingering", document, audit=False)
    module = EvidenceScoringModule(tmp_path, profile="main")

    result = module.score_all(store=store)
    status = module.status()
    subject_refs = {score["subject_ref"] for score in module.read_scores()}

    assert result["working_active_subject_count"] == 1
    assert result["working_expired_skipped_count"] == 1
    assert f"working:{active.id}" in subject_refs
    assert f"working:{expired.id}" not in subject_refs
    assert status["working_subject_count"] == 1
    assert status["expired_used_in_scoring_count"] == 0


def test_evidence_scoring_rejects_scores_without_evidence_or_explanation(tmp_path):
    module = EvidenceScoringModule(tmp_path, profile="main")

    with pytest.raises(ValueError, match="evidence_refs"):
        module.build_score_record(
            subject_ref="event:missing",
            subject_kind="event",
            score=0.5,
            evidence_refs=[],
            explanation="Has explanation",
        )

    with pytest.raises(ValueError, match="explanation"):
        module.build_score_record(
            subject_ref="event:missing",
            subject_kind="event",
            score=0.5,
            evidence_refs=["evidence:1"],
            explanation="",
        )


def test_evidence_scoring_is_replayable_against_same_fixture(tmp_path):
    store = _store(tmp_path)
    proposal_queue = _seed_scoring_inputs(tmp_path, store)
    module = EvidenceScoringModule(tmp_path, profile="main")

    first = module.score_all(store=store, proposal_queue=proposal_queue)
    first_scores = module.read_scores()
    second = module.score_all(store=store, proposal_queue=proposal_queue)
    second_scores = module.read_scores()

    assert first["score_fingerprints"] == second["score_fingerprints"]
    assert [
        (score["subject_ref"], score["score"], score["evidence_refs"], score["explanation_ref"])
        for score in first_scores
    ] == [
        (score["subject_ref"], score["score"], score["evidence_refs"], score["explanation_ref"])
        for score in second_scores
    ]


def test_evidence_scoring_status_and_doctor_do_not_expose_subject_bodies(tmp_path):
    store = _store(tmp_path)
    proposal_queue = _seed_scoring_inputs(tmp_path, store)
    module = EvidenceScoringModule(tmp_path, profile="main")
    module.score_all(store=store, proposal_queue=proposal_queue)

    status = module.status()
    doctor = module.doctor()

    rendered = json.dumps({"status": status, "doctor": doctor}, ensure_ascii=False)
    assert status["score_count"] == 4
    assert doctor["status"] == "ok"
    assert "Create a dry-run evidence scoring report" not in rendered
    assert "Candidate body should not be auto-approved" not in rendered


def test_evidence_scoring_does_not_touch_sannai_shape_fixture(tmp_path):
    fixture = build_sannai_multi_root_fixture(tmp_path / "fixture")
    soul = fixture.hermes_home / "SOUL.md"
    before = soul.stat().st_mtime_ns
    store = _store(tmp_path / "main", profile="main")
    module = EvidenceScoringModule(tmp_path / "main", profile="main")

    module.score_all(store=store)

    assert soul.stat().st_mtime_ns == before
    assert not (fixture.hermes_home / "system-modules").exists()
