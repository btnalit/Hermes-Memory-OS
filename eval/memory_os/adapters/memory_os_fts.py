from __future__ import annotations

from eval.memory_os.adapters.common import make_score
from eval.memory_os.runner.fixture_store import synthetic_store
from eval.memory_os.runner.types import Rh31Case, Rh31Document, Rh31Score
from plugins.memory.memory_os.index import MemoryOSIndex


NAME = "memory_os_fts"


def run(cases: list[Rh31Case], corpus: list[Rh31Document]) -> list[Rh31Score]:
    scores: list[Rh31Score] = []
    with synthetic_store(corpus) as store:
        index = MemoryOSIndex(store.roots)
        index.rebuild_from_store(store)
        for case in cases:
            query = " ".join(case.expected_terms) or case.query
            result = index.search(query, limit=5)
            hits = result.get("hits") if isinstance(result.get("hits"), list) else []
            scores.append(
                make_score(
                    adapter=NAME,
                    case=case,
                    passed=bool(hits),
                    failure_class="fts_miss",
                    source_classes=[str(hit.get("source") or hit.get("table") or "indexed") for hit in hits[:3] if isinstance(hit, dict)],
                    details={"mode": result.get("mode"), "hit_count": len(hits)},
                )
            )
    return scores
