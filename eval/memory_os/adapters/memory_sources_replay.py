from __future__ import annotations

from eval.memory_os.adapters.common import make_score
from eval.memory_os.runner.fixture_store import synthetic_store
from eval.memory_os.runner.types import Rh31Case, Rh31Document, Rh31Score
from plugins.memory.memory_os.index import MemoryOSIndex
from plugins.memory.memory_os.memory_sources import memory_sources_stats_report
from plugins.memory.memory_os.prefetch import build_prefetch


NAME = "memory_sources_replay"


def run(cases: list[Rh31Case], corpus: list[Rh31Document]) -> list[Rh31Score]:
    scores: list[Rh31Score] = []
    with synthetic_store(corpus) as store:
        index = MemoryOSIndex(store.roots)
        index.rebuild_from_store(store)
        replayed_case_ids: list[str] = []
        for case in cases:
            build_prefetch(
                case.query,
                budget_chars=2400,
                store=store,
                index=index,
                context_router_config={"enabled": True, "mode": "apply", "apply_routes": ["all"]},
                memory_sources_config={"enabled": True},
                low_clue_recall_config={"enabled": True, "llm_judge": {"enabled": False, "mode": "none"}},
            )
            replayed_case_ids.append(case.case_id)
        stats = memory_sources_stats_report(store.roots, hours=24)
        source_distribution = stats.get("selected_source_class_distribution")
        source_classes = sorted(source_distribution) if isinstance(source_distribution, dict) else []
        forbidden = len(stats.get("forbidden_field_findings") or [])
        boundary_true = int(stats.get("boundary_true_count") or 0)
        for case in cases:
            scores.append(
                make_score(
                    adapter=NAME,
                    case=case,
                    passed=forbidden == 0 and boundary_true == 0,
                    failure_class="memory_sources_forbidden_field",
                    source_classes=source_classes,
                    details={
                        "record_count": stats.get("record_count"),
                        "replayed_case_count": len(replayed_case_ids),
                        "replayed_case_ids": replayed_case_ids,
                        "boundary_true_count": boundary_true,
                        "forbidden_field_count": forbidden,
                    },
                )
            )
    return scores
