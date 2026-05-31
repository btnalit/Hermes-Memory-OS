import json

from plugins.modules.expression.grounded_expression_judge import GroundedExpressionJudge


def test_grounded_expression_judge_escalates_double_blind():
    verdict = GroundedExpressionJudge().judge(
        right_brain_claim={"text": "This feels like a stable preference.", "grounded": False},
        left_brain_map={"coverage": "thin", "confabulation_flagged": True},
    )

    assert verdict["decision"] == "unresolvable"
    assert verdict["verdict_class"] == "unresolvable"
    assert verdict["owner_escalation_required"] is True
    assert verdict["audit_action"] == "cross_check_unresolvable_escalated"
    assert verdict["actual_send"] is False
    assert verdict["delivery_gated"] is False
    assert verdict["delivery_affected"] is False
    assert verdict["left_map_snapshot_version"]


def test_grounded_expression_judge_defaults_hindsight_off_and_warns_without_left_map_substrate():
    verdict = GroundedExpressionJudge().judge(
        right_brain_claim={"text": "Maybe this is true.", "grounded": False},
        left_brain_map={},
    )

    assert verdict["status"] == "warning"
    assert verdict["code"] == "left_map_substrate_unavailable"
    assert verdict["verdict_class"] == "unresolvable"
    assert verdict["delivery_authority_blocked"] is True
    assert verdict["actual_send"] is False


def test_grounded_expression_judge_does_not_accept_boolean_only_alternate_left_map():
    verdict = GroundedExpressionJudge(alternate_left_map_substrate=True).judge(
        right_brain_claim={"text": "Maybe this is true.", "grounded": False},
        left_brain_map={},
    )

    assert verdict["status"] == "warning"
    assert verdict["code"] == "left_map_substrate_unavailable"
    assert verdict["delivery_authority_blocked"] is True


def test_grounded_expression_judge_run_once_writes_advisory_shadow_verdict(tmp_path):
    module = GroundedExpressionJudge(tmp_path, profile="main")

    verdict = module.run_once(
        right_brain_result={"output": "Maybe this is a stable preference."},
        confabulation_result={"flag_count": 0},
        evidence_result={"evidence_count": 2},
    )

    assert verdict["decision"] == "advisory_ok"
    assert verdict["verdict_class"] == "grounded"
    assert verdict["left_map_coverage"] == "covered"
    assert verdict["left_map_coverage_floor_met"] is True
    assert verdict["left_map_snapshot_version"]
    assert verdict["delivery_affected"] is False
    assert verdict["actual_send"] is False
    assert verdict["policy_live_applied"] is False
    status = module.status()
    assert status["status"] == "ok"
    assert status["verdict_count"] == 1
    assert status["hindsight_adapter_enabled"] is False
    assert status["verdict_distribution"] == {
        "grounded": 1,
        "confabulation": 0,
        "blind_spot": 0,
        "unresolvable": 0,
    }
    assert status["left_map_coverage_floor_met_count"] == 1
    assert status["latest_left_map_snapshot_version"] == verdict["left_map_snapshot_version"]
    assert status["delivery_affected"] is False


def test_grounded_expression_judge_skips_silent_without_expression_artifact(tmp_path):
    module = GroundedExpressionJudge(tmp_path, profile="main")

    verdict = module.run_once(
        right_brain_result={"output": "[SILENT]", "reason": "unchanged_right_brain_signal"},
        confabulation_result={"flag_count": 0},
        evidence_result={"evidence_count": 2},
    )

    assert verdict["status"] == "skipped"
    assert verdict["decision"] == "no_expression_to_judge"
    assert not module.verdicts_path.exists()


def test_grounded_expression_judge_uses_real_wandering_output_as_targeted_canary(tmp_path):
    outputs_path = tmp_path / "system-modules" / "wandering_mind" / "outputs.jsonl"
    outputs_path.parent.mkdir(parents=True)
    outputs_path.write_text(
        json.dumps(
            {
                "schema_version": "hermes.wandering_mind_output.v0",
                "id": "wout_real",
                "source_event_id": "evt_real",
                "output_ref": "local://wandering_mind/wout_real",
                "output": "A real right-brain expression without explicit source refs.",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    feature_scores_path = tmp_path / "system-modules" / "evidence_scoring" / "feature_scores.jsonl"
    feature_scores_path.parent.mkdir(parents=True)
    feature_scores_path.write_text(
        json.dumps(
            {
                "schema_version": "hermes.evidence_feature_score.v0",
                "subject_ref": "event:evt_real",
                "source_ref": "memory_os:event:evt_real",
                "maturity_score": 0.4,
                "evidence_profile": {
                    "derivation": "direct_observation",
                    "coverage": {"source_diversity": 1, "recurrence": 0},
                },
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    module = GroundedExpressionJudge(tmp_path, profile="main")

    verdict = module.run_once(
        right_brain_result={"output": "[SILENT]", "reason": "unchanged_right_brain_signal"},
        confabulation_result={"flag_count": 0, "flags": []},
        evidence_result={"evidence_count": 999, "feature_scores_path": str(feature_scores_path)},
    )

    assert verdict["verdict_class"] == "blind_spot"
    assert verdict["decision"] == "blind_spot"
    assert verdict["right_brain_grounded"] is False
    assert verdict["left_map_coverage"] == "thin"
    assert verdict["left_map_evidence_count"] == 1
    assert verdict["left_map_lookup_ref_count"] >= 2
    assert verdict["right_brain_artifact_ref"] == "local://wandering_mind/wout_real"
    assert verdict["actual_send"] is False
    assert verdict["delivery_affected"] is False


def test_grounded_expression_judge_status_tracks_verdict_distribution_and_substrate_quality(tmp_path):
    module = GroundedExpressionJudge(tmp_path, profile="main")
    module.judge(
        right_brain_claim={"text": "Stable and sourced.", "grounded": True},
        left_brain_map={"coverage": "covered", "evidence_count": 3, "confabulation_flag_count": 0},
    )
    module.judge(
        right_brain_claim={"text": "Contradicts a flagged left-map record.", "grounded": False},
        left_brain_map={"coverage": "covered", "evidence_count": 3, "confabulation_flag_count": 1},
    )
    module.judge(
        right_brain_claim={"text": "Thin left-map disagreement.", "grounded": False},
        left_brain_map={"coverage": "thin", "evidence_count": 1, "confabulation_flag_count": 0},
    )
    module.judge(
        right_brain_claim={"text": "No substrate.", "grounded": False},
        left_brain_map={},
    )

    status = module.status()

    assert status["verdict_distribution"] == {
        "grounded": 1,
        "confabulation": 1,
        "blind_spot": 1,
        "unresolvable": 1,
    }
    assert status["left_map_coverage_floor_met_count"] == 2
    assert status["verdict_distribution_degenerate"] is False
    assert status["substrate_unavailable_blocker_cleared"] is True
