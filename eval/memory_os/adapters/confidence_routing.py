from __future__ import annotations

from eval.memory_os.adapters.common import make_score
from eval.memory_os.runner.types import Rh31Case, Rh31Document, Rh31Score
from plugins.modules.governance.confidence_router import ConfidenceRouterModule


NAME = "confidence_routing"


def run(cases: list[Rh31Case], corpus: list[Rh31Document]) -> list[Rh31Score]:
    result = ConfidenceRouterModule(".", profile="eval").route_records(
        [
            {"subject_ref": "eval:low", "subject_kind": "working", "maturity_score": 0.2, "score_id": "s1"},
            {
                "subject_ref": "eval:mid",
                "subject_kind": "crystallized_candidate",
                "maturity_score": 0.6,
                "score_id": "s2",
            },
            {
                "subject_ref": "eval:high",
                "subject_kind": "crystallized_candidate",
                "maturity_score": 0.9,
                "score_id": "s3",
            },
        ],
        write=False,
    )
    passed = result["band_distribution"] == {"high": 1, "low": 1, "mid": 1} and not result["route_live_applied"]
    return [
        make_score(
            adapter=NAME,
            case=cases[0],
            passed=passed,
            metric_scope="governance",
            failure_class="confidence_routing_band_miss",
            source_classes=["v7_governance"],
            details={
                "band_distribution": result["band_distribution"],
                "route_live_applied": result["route_live_applied"],
                "live_behavior_changed": False,
            },
        )
    ]
