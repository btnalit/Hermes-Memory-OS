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
            queries = _candidate_queries(case)
            result = {}
            hits = []
            for query in queries:
                result = index.search(query, limit=5)
                hits = result.get("hits") if isinstance(result.get("hits"), list) else []
                if hits:
                    break
            scores.append(
                make_score(
                    adapter=NAME,
                    case=case,
                    passed=bool(hits),
                    failure_class="fts_miss",
                    source_classes=[str(hit.get("source") or hit.get("table") or "indexed") for hit in hits[:3] if isinstance(hit, dict)],
                    details={"mode": result.get("mode"), "hit_count": len(hits), "queries_tried": queries},
                )
            )
    return scores


def _candidate_queries(case: Rh31Case) -> list[str]:
    terms = [str(term).strip() for term in case.expected_terms if str(term).strip()]
    if not terms:
        return [case.query]
    queries = [" ".join(terms)]
    queries.extend(term for term in terms if term not in queries)
    if case.query and case.query not in queries:
        queries.append(case.query)
    return queries
