from __future__ import annotations

from eval.memory_os.adapters.common import headings_from_context, make_score
from eval.memory_os.runner.fixture_store import synthetic_store
from eval.memory_os.runner.types import Rh31Case, Rh31Document, Rh31Score
from plugins.memory.memory_os.index import MemoryOSIndex
from plugins.memory.memory_os.prefetch import build_prefetch


NAME = "context_projection"


def run(cases: list[Rh31Case], corpus: list[Rh31Document]) -> list[Rh31Score]:
    scores: list[Rh31Score] = []
    with synthetic_store(corpus) as store:
        index = MemoryOSIndex(store.roots)
        index.rebuild_from_store(store)
        for case in cases:
            context = build_prefetch(
                case.query,
                budget_chars=2400,
                store=store,
                index=index,
                runtime_facts={"provider": "memory_os", "prefetch_mode": "indexed"},
                current_task_anchor="### Memory-OS Current Task Anchor\n- current task: install ComfyUI plugins.",
                context_router_config={"enabled": True, "mode": "apply", "apply_routes": ["all"]},
                low_clue_recall_config={"enabled": True, "llm_judge": {"enabled": False, "mode": "none"}},
            )
            headings = headings_from_context(context)
            expected = case.expected_heading
            passed = not expected or expected in headings
            scores.append(
                make_score(
                    adapter=NAME,
                    case=case,
                    passed=passed,
                    failure_class="projection_miss",
                    actual_route=_route_from_heading(headings),
                    actual_headings=headings,
                    source_classes=["context_projection"],
                    details={"char_count": len(context)},
                )
            )
    return scores


def _route_from_heading(headings: list[str]) -> str:
    if "Recall Clarification Guard" in headings:
        return "ambiguous_recall"
    if "Diagnostic Grounding" in headings:
        return "diagnostic_current_status"
    if "Current Foreground Task" in headings:
        return "active_task"
    return "unknown"
