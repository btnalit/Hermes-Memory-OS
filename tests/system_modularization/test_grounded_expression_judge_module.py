from plugins.modules.expression.grounded_expression_judge import GroundedExpressionJudge


def test_grounded_expression_judge_escalates_double_blind():
    verdict = GroundedExpressionJudge().judge(
        right_brain_claim={"text": "This feels like a stable preference.", "grounded": False},
        left_brain_map={"coverage": "thin", "confabulation_flagged": True},
    )

    assert verdict["decision"] == "unresolvable"
    assert verdict["owner_escalation_required"] is True
    assert verdict["audit_action"] == "cross_check_unresolvable_escalated"
    assert verdict["actual_send"] is False
    assert verdict["delivery_gated"] is False


def test_grounded_expression_judge_warns_without_left_map_substrate():
    verdict = GroundedExpressionJudge(hindsight_adapter_enabled=False).judge(
        right_brain_claim={"text": "Maybe this is true.", "grounded": False},
        left_brain_map={},
    )

    assert verdict["status"] == "warning"
    assert verdict["code"] == "left_map_substrate_unavailable"
    assert verdict["delivery_authority_blocked"] is True
    assert verdict["actual_send"] is False


def test_grounded_expression_judge_run_once_writes_advisory_shadow_verdict(tmp_path):
    module = GroundedExpressionJudge(tmp_path, profile="main")

    verdict = module.run_once(
        right_brain_result={"output": "Maybe this is a stable preference."},
        confabulation_result={"flag_count": 0},
        evidence_result={"evidence_count": 2},
    )

    assert verdict["decision"] == "advisory_ok"
    assert verdict["actual_send"] is False
    assert verdict["policy_live_applied"] is False
    status = module.status()
    assert status["status"] == "ok"
    assert status["verdict_count"] == 1
