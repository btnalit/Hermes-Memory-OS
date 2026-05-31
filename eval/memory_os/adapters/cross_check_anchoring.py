from __future__ import annotations

from eval.memory_os.adapters.common import make_score
from eval.memory_os.runner.types import Rh31Case, Rh31Document, Rh31Score
from plugins.modules.expression.grounded_expression_judge import GroundedExpressionJudge


NAME = "cross_check_anchoring"


def run(cases: list[Rh31Case], corpus: list[Rh31Document]) -> list[Rh31Score]:
    verdict = GroundedExpressionJudge().judge(
        right_brain_claim={"text": "This feels like a stable preference.", "grounded": False},
        left_brain_map={"coverage": "thin", "confabulation_flagged": True},
    )
    passed = verdict["decision"] == "unresolvable" and verdict["actual_send"] is False
    return [
        make_score(
            adapter=NAME,
            case=cases[0],
            passed=passed,
            metric_scope="expression",
            failure_class="cross_check_anchoring_miss",
            source_classes=["v7_expression"],
            details={
                "decision": verdict["decision"],
                "owner_escalation_required": verdict["owner_escalation_required"],
                "delivery_gated": verdict["delivery_gated"],
                "live_behavior_changed": False,
            },
        )
    ]
