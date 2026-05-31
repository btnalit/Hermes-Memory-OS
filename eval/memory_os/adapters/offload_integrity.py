from __future__ import annotations

from tempfile import TemporaryDirectory

from eval.memory_os.adapters.common import make_score
from eval.memory_os.runner.types import Rh31Case, Rh31Document, Rh31Score
from plugins.modules.context.symbolic_offloader import SymbolicOffloaderModule


NAME = "offload_integrity"


def run(cases: list[Rh31Case], corpus: list[Rh31Document]) -> list[Rh31Score]:
    original = "offload integrity fixture\nline two must round trip exactly\n"
    with TemporaryDirectory() as root:
        module = SymbolicOffloaderModule(root, profile="eval")
        result = module.offload_entries(
            task_id="eval-task",
            entries=[
                {
                    "node_id": "001-N3",
                    "title": "fixture",
                    "text": original,
                }
            ],
        )
        recalled = module.recall_node("eval-task", "001-N3")

    round_trip_exact = recalled["text"] == original
    passed = (
        round_trip_exact
        and recalled["checksum"] == result["nodes"][0]["original_sha256"]
        and result["actual_execute"] is False
        and result["canonical_state_changed"] is False
    )
    return [
        make_score(
            adapter=NAME,
            case=cases[0],
            passed=passed,
            metric_scope="offload_integrity",
            failure_class="offload_integrity_mismatch",
            source_classes=["v7_context"],
            details={
                "round_trip_exact": round_trip_exact,
                "node_id": "001-N3",
                "checksum_match": recalled["checksum"] == result["nodes"][0]["original_sha256"],
                "actual_execute": result["actual_execute"],
                "canonical_state_changed": result["canonical_state_changed"],
            },
        )
    ]
