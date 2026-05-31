from __future__ import annotations

from tempfile import TemporaryDirectory

from eval.memory_os.adapters.common import make_score
from eval.memory_os.runner.types import Rh31Case, Rh31Document, Rh31Score
from plugins.modules.governance.candidate_review import CandidateReviewModule, FeaturePreRouter


NAME = "review_accuracy"


def run(cases: list[Rh31Case], corpus: list[Rh31Document]) -> list[Rh31Score]:
    items = FeaturePreRouter().route(
        [
            {"subject_ref": "low", "band": "low", "maturity_score": 0.2},
            {"subject_ref": "mid", "band": "mid", "maturity_score": 0.5},
            {"subject_ref": "high", "band": "high", "maturity_score": 0.9},
        ]
    )["items"]
    with TemporaryDirectory() as root:
        result = CandidateReviewModule(root, profile="eval").review(items)
    decisions = {item["subject_ref"]: item["decision"] for item in result["decisions"]}
    passed = decisions == {"low": "downgrade", "mid": "recollect", "high": "keep"}
    return [
        make_score(
            adapter=NAME,
            case=cases[0],
            passed=passed,
            metric_scope=NAME,
            failure_class="review_accuracy_mismatch",
            source_classes=["v7_governance"],
            details={"decisions": decisions, "candidate_review_live_applied": result["candidate_review_live_applied"]},
        )
    ]
