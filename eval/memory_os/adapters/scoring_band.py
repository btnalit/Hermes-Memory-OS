from __future__ import annotations

from eval.memory_os.adapters.common import make_score
from eval.memory_os.runner.types import Rh31Case, Rh31Document, Rh31Score
from plugins.modules.governance.confidence_router import ConfidenceRouterModule


NAME = "scoring_band"


def run(cases: list[Rh31Case], corpus: list[Rh31Document]) -> list[Rh31Score]:
    result = ConfidenceRouterModule(".", profile="eval").route_records(
        [
            {"subject_ref": "eval:low", "subject_kind": "candidate", "maturity_score": 0.1, "score_id": "s1"},
            {"subject_ref": "eval:mid", "subject_kind": "candidate", "maturity_score": 0.5, "score_id": "s2"},
            {"subject_ref": "eval:high", "subject_kind": "candidate", "maturity_score": 0.9, "score_id": "s3"},
        ],
        write=False,
    )
    passed = result["band_distribution"] == {"high": 1, "low": 1, "mid": 1}
    return [
        make_score(
            adapter=NAME,
            case=cases[0],
            passed=passed,
            metric_scope=NAME,
            failure_class="scoring_band_mismatch",
            source_classes=["v7_governance"],
            details={"band_distribution": result["band_distribution"], "actual_execute": False},
        )
    ]
