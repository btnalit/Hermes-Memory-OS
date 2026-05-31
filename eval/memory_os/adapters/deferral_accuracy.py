from __future__ import annotations

from tempfile import TemporaryDirectory

from eval.memory_os.adapters.common import make_score
from eval.memory_os.runner.types import Rh31Case, Rh31Document, Rh31Score
from plugins.modules.governance.cascade_routing_policy import CascadeRoutingPolicyModule


NAME = "deferral_accuracy"


def run(cases: list[Rh31Case], corpus: list[Rh31Document]) -> list[Rh31Score]:
    with TemporaryDirectory() as root:
        result = CascadeRoutingPolicyModule(root, profile="eval").propose_policy(
            band_metrics={"low": {"n": 50, "error_rate": 0.01}, "mid": {"n": 5, "error_rate": 0.2}},
            guardrails={"aa_passed": True, "honesty_passed": True, "min_n": 30},
        )
    passed = result["policy"]["low"]["automation_candidate"] is True and result["policy"]["mid"][
        "automation_candidate"
    ] is False
    return [
        make_score(
            adapter=NAME,
            case=cases[0],
            passed=passed,
            metric_scope=NAME,
            failure_class="deferral_accuracy_mismatch",
            source_classes=["v7_governance"],
            details={"policy": result["policy"], "route_strategy_live_applied": result["route_strategy_live_applied"]},
        )
    ]
