from __future__ import annotations

from collections import Counter

from eval.memory_os.adapters.common import make_score
from eval.memory_os.data.v7_simulated import load_scenarios
from eval.memory_os.runner.types import Rh31Case, Rh31Document, Rh31Score


NAME = "simulation_coverage"
REQUIRED_DIMENSIONS = {"confab", "double_blind", "cold_start"}


def run(cases: list[Rh31Case], corpus: list[Rh31Document]) -> list[Rh31Score]:
    case = cases[0]
    scenarios = load_scenarios()
    covered = {
        str(dimension)
        for scenario in scenarios
        for dimension in scenario.get("dimensions", [])
    }
    provenance = Counter(str(scenario.get("provenance") or "unknown") for scenario in scenarios)
    missing = sorted(REQUIRED_DIMENSIONS - covered)
    return [
        make_score(
            adapter=NAME,
            case=case,
            passed=not missing and set(provenance) == {"simulated"},
            metric_scope="simulation",
            failure_class="simulation_dimension_missing",
            notes=[f"missing={','.join(missing)}"] if missing else [],
            source_classes=["v7_simulated"],
            details={
                "scenario_count": len(scenarios),
                "covered_dimensions": sorted(covered),
                "provenance_distribution": dict(sorted(provenance.items())),
                "live_behavior_changed": False,
            },
        )
    ]
