from __future__ import annotations

from tempfile import TemporaryDirectory

from eval.memory_os.adapters.common import make_score
from eval.memory_os.runner.types import Rh31Case, Rh31Document, Rh31Score
from plugins.modules.governance.shadow_recall import ShadowRecallModule


NAME = "shadow_recall"


def run(cases: list[Rh31Case], corpus: list[Rh31Document]) -> list[Rh31Score]:
    with TemporaryDirectory() as root:
        module = ShadowRecallModule(root, profile="eval")
        module.record_discards([{"subject_ref": "discarded", "text": "rare failure signature"}])
        result = module.evaluate_recall_misses([{"query": "failure", "text": "rare failure signature"}])
    passed = result["miss_hit_count"] == 1 and result["auto_discard_live_applied"] is False
    return [
        make_score(
            adapter=NAME,
            case=cases[0],
            passed=passed,
            metric_scope=NAME,
            failure_class="shadow_recall_miss",
            source_classes=["v7_governance"],
            details=result,
        )
    ]
