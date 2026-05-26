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


def test_evidence_scoring_v2_replaces_hash_scores_as_primary_signal(tmp_path):
    store = _store(tmp_path)
    proposal_queue = _seed_scoring_inputs(tmp_path, store)
    module = EvidenceScoringModule(tmp_path, profile="main")

    result = module.score_all(store=store, proposal_queue=proposal_queue)

    primary_scores = module.read_scores()
    feature_scores = module.read_feature_scores()
    assert result["score_mode"] == "feature_maturity_v2"
    assert result["feature_score_mode"] == "primary"
    assert result["feature_score_count"] == result["score_count"] == 4
    assert result["hash_score_legacy_count"] == 0
    assert result["legacy_hash_comparison_count"] == 4
    assert result["feature_score_live_applied"] is False
    assert module.feature_scores_path.exists()
    assert len(feature_scores) == len(primary_scores)
    assert {record["subject_ref"] for record in feature_scores} == {
        record["subject_ref"] for record in primary_scores
    }
    assert {record["schema_version"] for record in feature_scores} == {"hermes.evidence_feature_score.v0"}
    feature_by_ref = {record["subject_ref"]: record for record in feature_scores}
    for record in feature_scores:
        assert record["mode"] == "primary"
        assert record["live_applied"] is False
        assert record["actual_approve"] is False
        assert record["actual_execute"] is False
        assert 0.0 <= record["feature_score"] <= 1.0
        assert 0.0 <= record["legacy_hash_score"] <= 1.0
        assert isinstance(record["score_delta"], float)
        assert set(record["features"]) >= {
            "subject_kind_weight",
            "source_status_weight",
            "summary_length_bucket",
            "proposal_state_weight",
        }
        rendered = json.dumps(record, ensure_ascii=False)
        assert "Create a dry-run evidence scoring report" not in rendered
        assert "Candidate body should not be auto-approved" not in rendered
    assert {score["schema_version"] for score in primary_scores} == {"hermes.evidence_score.v0"}
    for score in primary_scores:
        feature = feature_by_ref[score["subject_ref"]]
        assert score["score_source"] == "feature_maturity_v2"
        assert score["score"] == feature["maturity_score"]
        assert score["legacy_hash_score"] == feature["legacy_hash_score"]


def test_evidence_scoring_reports_prototype_aligned_maturity_dimensions(tmp_path):
    store = _store(tmp_path)
    proposal_queue = _seed_scoring_inputs(tmp_path, store)
    module = EvidenceScoringModule(tmp_path, profile="main")

    result = module.score_all(store=store, proposal_queue=proposal_queue)

    feature_scores = module.read_feature_scores()
    required_dimensions = {
        "evidence_strength",
        "recurrence",
        "actionability",
        "source_diversity",
        "owner_feedback",
        "risk",
        "freshness_decay",
        "duplicate_backlog",
        "gate_state",
    }
    assert result["prototype_aligned_score_count"] == len(feature_scores) == 4
    assert result["maturity_dimension_keys"] == sorted(required_dimensions)
    assert result["maturity_live_applied"] is False
    for record in feature_scores:
        assert record["prototype_alignment"]["source"] == "10.20.2.88:self_evolution_daily_pipeline"
        assert record["prototype_alignment"]["mode"] == "adapted_primary"
        assert set(record["maturity_dimensions"]) == required_dimensions
        assert 0.0 <= record["maturity_score"] <= 1.0
        assert record["feature_score"] == record["maturity_score"]
        assert record["maturity_live_applied"] is False
        for dimension in record["maturity_dimensions"].values():
            assert set(dimension) >= {"score", "signals"}
            assert 0.0 <= dimension["score"] <= 1.0
            assert isinstance(dimension["signals"], dict)
        rendered = json.dumps(record, ensure_ascii=False)
        assert "Create a dry-run evidence scoring report" not in rendered
        assert "Candidate body should not be auto-approved" not in rendered


def test_evidence_scoring_preserves_expression_feedback_rating(tmp_path):
    store = _store(tmp_path)
    feedback_path = store.roots.memory_os_root / "system" / "expression_feedback_ledger.jsonl"
    feedback_path.parent.mkdir(parents=True, exist_ok=True)
    feedback_path.write_text(
        json.dumps(
            {
                "schema_version": "memory-os.expression_feedback.v0",
                "feedback_id": "efb_rating_001",
                "created_at": "2026-05-26T00:00:00Z",
                "draft_id": "expr_rating_001",
                "action_type": "too_mechanical",
                "raw_body_included": False,
                "live_policy_changed": False,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    module = EvidenceScoringModule(tmp_path, profile="main")

    result = module.score_all(store=store)

    assert result["expression_feedback_subject_count"] == 1
    evidence = [record for record in module.read_evidence() if record["subject_kind"] == "expression_feedback"][0]
    feature = [record for record in module.read_feature_scores() if record["subject_kind"] == "expression_feedback"][0]
    assert evidence["feedback_rating"] == "too_mechanical"
    assert "rating=too_mechanical" in evidence["summary"]
    assert "target=expr_rating_001" in evidence["summary"]
    assert feature["maturity_dimensions"]["owner_feedback"]["signals"]["feedback_rating"] == "too_mechanical"
    assert feature["maturity_dimensions"]["risk"]["signals"]["risk_level"] > 0.2


def test_evidence_scoring_preserves_expression_feedback_outcome_context(tmp_path):
    store = _store(tmp_path)
    feedback_path = store.roots.memory_os_root / "system" / "expression_feedback_ledger.jsonl"
    feedback_path.parent.mkdir(parents=True, exist_ok=True)
    feedback_path.write_text(
        json.dumps(
            {
                "schema_version": "memory-os.expression_feedback.v0",
                "feedback_id": "efb_linked_001",
                "created_at": "2026-05-26T00:00:00Z",
                "target_id": "expr_linked_001",
                "outcome_id": "rbout_linked_001",
                "request_id": "rbreq_linked_001",
                "policy_version": 3,
                "rating": "off_voice",
                "raw_body_included": False,
                "live_policy_changed": False,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    module = EvidenceScoringModule(tmp_path, profile="main")

    result = module.score_all(store=store)

    assert result["expression_feedback_subject_count"] == 1
    assert result["expression_feedback_linked_subject_count"] == 1
    assert result["expression_feedback_unlinked_subject_count"] == 0
    evidence = [record for record in module.read_evidence() if record["subject_kind"] == "expression_feedback"][0]
    feature = [record for record in module.read_feature_scores() if record["subject_kind"] == "expression_feedback"][0]
    assert evidence["feedback_rating"] == "off_voice"
    assert evidence["outcome_id"] == "rbout_linked_001"
    assert evidence["request_id"] == "rbreq_linked_001"
    assert evidence["policy_version"] == "3"
    signals = feature["maturity_dimensions"]["owner_feedback"]["signals"]
    assert signals["linked_outcome"] is True
    assert signals["outcome_id"] == "rbout_linked_001"
    assert signals["policy_version"] == "3"


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


def test_evidence_scoring_status_uses_status_at_scoring_time(tmp_path):
    store = _store(tmp_path)
    event = EventEnvelope.from_dict(
        {**build_event(seed=3, profile="main"), "summary": "Owner discussed status at scoring time."}
    )
    store.append_event(event)
    active = WorkingMemoryService(store).add_item(
        "lingering",
        "This item was active when scoring ran.",
        source_event_id=event.id,
        tags=["test"],
    )
    module = EvidenceScoringModule(tmp_path, profile="main")

    module.score_all(store=store)
    document = store.read_working_document("lingering")
    for item in document["items"]:
        if item["id"] == active.id:
            item["status"] = "expired"
    store.write_working_document("lingering", document, audit=False)
    status = module.status()
    evidence = [record for record in module.read_evidence() if record["subject_ref"] == f"working:{active.id}"][0]

    assert evidence["source_status"] == "active"
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


def test_evidence_scoring_skips_unchanged_input_after_first_run(tmp_path):
    store = _store(tmp_path)
    proposal_queue = _seed_scoring_inputs(tmp_path, store)
    module = EvidenceScoringModule(tmp_path, profile="main")

    first = module.score_all(store=store, proposal_queue=proposal_queue)
    second = module.score_all(store=store, proposal_queue=proposal_queue)

    assert first["skipped"] is False
    assert first["generated_score_count"] == 4
    assert second["skipped"] is True
    assert second["cadence_skipped"] is True
    assert second["reason"] == "unchanged_input_fingerprint"
    assert second["generated_score_count"] == 0
    assert second["score_count"] == first["score_count"]
    assert second["score_fingerprints"] == first["score_fingerprints"]
    run_reports = [
        json.loads(line)
        for line in module.runs_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [report["skipped"] for report in run_reports] == [False, True]
    audit_lines = store.roots.audit_path.read_text(encoding="utf-8").splitlines()
    assert any("evidence_scoring_run_skipped" in line for line in audit_lines)

    store.append_event(
        EventEnvelope.from_dict(
            {
                **build_event(seed=66, profile="main"),
                "summary": "A new event should break the EvidenceScoring cadence skip.",
            }
        )
    )
    third = module.score_all(store=store, proposal_queue=proposal_queue)

    assert third["skipped"] is False
    assert third["cadence_skipped"] is False
    assert third["generated_score_count"] == third["score_count"] == first["score_count"] + 1
    assert third["input_fingerprint"] != first["input_fingerprint"]


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
