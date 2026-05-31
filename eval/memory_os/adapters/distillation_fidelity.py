from __future__ import annotations

from tempfile import TemporaryDirectory

from eval.memory_os.adapters.common import make_score
from eval.memory_os.runner.types import Rh31Case, Rh31Document, Rh31Score
from plugins.modules.context.abstraction_distillation import AbstractionDistillationModule


NAME = "distillation_fidelity"


def run(cases: list[Rh31Case], corpus: list[Rh31Document]) -> list[Rh31Score]:
    source = "The live-shadow pipeline runs on 10.20.3.200 before autonomy flips."
    with TemporaryDirectory() as root:
        module = AbstractionDistillationModule(root, profile="eval")
        result = module.distill(source_ref="fixture:1", source_text=source)
        recalled = module.recall_source(result["items"][0]["source_checksum"])
    passed = recalled["text"] == source and all(item["truth_status"] == "candidate_only" for item in result["items"])
    return [
        make_score(
            adapter=NAME,
            case=cases[0],
            passed=passed,
            metric_scope=NAME,
            failure_class="distillation_fidelity_mismatch",
            source_classes=["v7_context"],
            details={"round_trip_exact": recalled["text"] == source, "distillation_count": result["distillation_count"]},
        )
    ]
