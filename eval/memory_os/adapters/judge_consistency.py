from __future__ import annotations

from tempfile import TemporaryDirectory

from eval.memory_os.adapters.common import make_score
from eval.memory_os.runner.types import Rh31Case, Rh31Document, Rh31Score
from plugins.modules.governance.judge_calibration import JudgeCalibrationMonitor


NAME = "judge_consistency"


def run(cases: list[Rh31Case], corpus: list[Rh31Document]) -> list[Rh31Score]:
    with TemporaryDirectory() as root:
        result = JudgeCalibrationMonitor(root, profile="eval").evaluate(
            decisions=[
                {"case_id": "c1", "verdict": "keep"},
                {"case_id": "c1", "verdict": "keep"},
            ],
            canaries=[{"case_id": "canary", "expected": "discard", "verdict": "discard"}],
        )
    passed = result["consistency_rate"] == 1.0 and result["canary_passed"] is True
    return [
        make_score(
            adapter=NAME,
            case=cases[0],
            passed=passed,
            metric_scope=NAME,
            failure_class="judge_consistency_drift",
            source_classes=["v7_governance"],
            details=result,
        )
    ]
