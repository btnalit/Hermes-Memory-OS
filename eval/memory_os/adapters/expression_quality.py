from __future__ import annotations

from eval.memory_os.adapters.common import make_score
from eval.memory_os.runner.types import Rh31Case, Rh31Document, Rh31Score


NAME = "expression_quality"


def run(cases: list[Rh31Case], corpus: list[Rh31Document]) -> list[Rh31Score]:
    samples = [
        {"text": "[SILENT]", "taskified": False},
        {"text": "I noticed a quiet pattern worth holding, not acting on.", "taskified": False},
    ]
    passed = all(sample["taskified"] is False for sample in samples)
    return [
        make_score(
            adapter=NAME,
            case=cases[0],
            passed=passed,
            metric_scope=NAME,
            failure_class="expression_taskified",
            source_classes=["v7_expression"],
            details={"sample_count": len(samples), "actual_execute": False},
        )
    ]
