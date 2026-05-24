from __future__ import annotations

from eval.memory_os.adapters.common import make_score, matching_documents
from eval.memory_os.runner.types import Rh31Case, Rh31Document, Rh31Score


NAME = "grep"


def run(cases: list[Rh31Case], corpus: list[Rh31Document]) -> list[Rh31Score]:
    scores: list[Rh31Score] = []
    for case in cases:
        matches = matching_documents(case, corpus)
        scores.append(
            make_score(
                adapter=NAME,
                case=case,
                passed=bool(matches),
                failure_class="lexical_miss",
                source_classes=[document.source_class for document in matches[:3]],
                details={"match_count": len(matches)},
            )
        )
    return scores
