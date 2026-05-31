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
