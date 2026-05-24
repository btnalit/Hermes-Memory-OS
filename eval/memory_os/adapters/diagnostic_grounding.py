from __future__ import annotations

from eval.memory_os.adapters.common import headings_from_context, make_score
from eval.memory_os.runner.fixture_store import synthetic_store
from eval.memory_os.runner.types import Rh31Case, Rh31Document, Rh31Score
from plugins.memory.memory_os.index import MemoryOSIndex
from plugins.memory.memory_os.prefetch import build_prefetch


NAME = "diagnostic_grounding"


def run(cases: list[Rh31Case], corpus: list[Rh31Document]) -> list[Rh31Score]:
    scores: list[Rh31Score] = []
    diagnostic_cases = [case for case in cases if case.family == "diagnostic"]
    with synthetic_store(corpus) as store:
        index = MemoryOSIndex(store.roots)
        index.rebuild_from_store(store)
        for case in diagnostic_cases:
            context = build_prefetch(
                case.query,
                budget_chars=1800,
                store=store,
                index=index,
                runtime_facts={"provider": "memory_os", "prefetch_mode": "indexed", "index_health": "healthy"},
                context_router_config={"enabled": True, "mode": "apply", "apply_routes": ["all"]},
            )
            headings = headings_from_context(context)
            scores.append(
                make_score(
                    adapter=NAME,
                    case=case,
                    passed="Diagnostic Grounding" in headings,
                    failure_class="diagnostic_grounding_miss",
                    actual_route="diagnostic_current_status",
                    actual_headings=headings,
                    source_classes=["diagnostic"],
                    details={"char_count": len(context)},
                )
            )
    return scores
