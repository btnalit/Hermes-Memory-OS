from __future__ import annotations

from eval.memory_os.adapters.common import make_score
from eval.memory_os.runner.types import Rh31Case, Rh31Document, Rh31Score
from plugins.modules.governance.crystallized_revalidator import CrystallizedRevalidatorModule


NAME = "crystallized_regression"


def run(cases: list[Rh31Case], corpus: list[Rh31Document]) -> list[Rh31Score]:
    result = CrystallizedRevalidatorModule(".", profile="eval").evaluate(
        records=[{"record_id": "cr_eval_1", "subject_ref": "crystallized:cr_eval_1"}],
        observations=[
            {
                "source_ref": "event:later_observed",
                "contradicts_record_id": "cr_eval_1",
                "evidence_profile": {"derivation": "direct_observation", "provenance": "observed"},
            }
        ],
        write=False,
    )
    passed = result["flag_count"] == 1 and result["flags"][0]["action"] == "would_demote"
    return [
        make_score(
            adapter=NAME,
            case=cases[0],
            passed=passed,
            metric_scope="governance",
            failure_class="crystallized_regression_miss",
            source_classes=["v7_governance"],
            details={
                "flag_count": result["flag_count"],
                "actual_crystallized_approval": result["actual_crystallized_approval"],
                "live_behavior_changed": False,
            },
        )
    ]
