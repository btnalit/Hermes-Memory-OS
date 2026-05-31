from __future__ import annotations

from eval.memory_os.adapters.common import make_score
from eval.memory_os.runner.types import Rh31Case, Rh31Document, Rh31Score
from plugins.modules.evidence.confabulation import ConfabulationDetectorModule


NAME = "confabulation_detection"


def run(cases: list[Rh31Case], corpus: list[Rh31Document]) -> list[Rh31Score]:
    records = [
        {
            "subject_ref": "eval:thin_inference",
            "maturity_score": 0.91,
            "evidence_profile": {
                "derivation": "inference",
                "coverage": {"source_diversity": 1, "recurrence": 0},
                "provenance": "observed",
            },
        },
        {
            "subject_ref": "eval:owner_assertion",
            "maturity_score": 0.96,
            "evidence_profile": {
                "derivation": "owner_assertion",
                "coverage": {"source_diversity": 3, "recurrence": 4},
                "provenance": "observed",
            },
        },
    ]
    result = ConfabulationDetectorModule(".", profile="eval").evaluate_records(records, write=False)
    flags = result["flags"]
    passed = len(flags) == 1 and flags[0]["subject_ref"] == "eval:thin_inference"
    return [
        make_score(
            adapter=NAME,
            case=cases[0],
            passed=passed,
            metric_scope="governance",
            failure_class="confabulation_detection_miss",
            source_classes=["v7_governance"],
            details={
                "record_count": result["record_count"],
                "flag_count": result["flag_count"],
                "flagged_subject_refs": [flag["subject_ref"] for flag in flags],
                "live_behavior_changed": False,
            },
        )
    ]
