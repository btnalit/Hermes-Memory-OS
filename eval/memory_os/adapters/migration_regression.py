from __future__ import annotations

from tempfile import TemporaryDirectory

from eval.memory_os.adapters.common import make_score
from eval.memory_os.runner.types import Rh31Case, Rh31Document, Rh31Score
from plugins.modules.governance.migration_controller import MigrationControllerModule


NAME = "migration_regression"


def run(cases: list[Rh31Case], corpus: list[Rh31Document]) -> list[Rh31Score]:
    with TemporaryDirectory() as root:
        result = MigrationControllerModule(root, profile="eval", label_floor=5).evaluate(
            signals={"owner_label_count": 1, "simulation_preheated": True}
        )
    passed = result["regime"] == "cold_start" and result["automation_allowed"] is False
    return [
        make_score(
            adapter=NAME,
            case=cases[0],
            passed=passed,
            metric_scope=NAME,
            failure_class="migration_regression_mismatch",
            source_classes=["v7_governance"],
            details=result,
        )
    ]
