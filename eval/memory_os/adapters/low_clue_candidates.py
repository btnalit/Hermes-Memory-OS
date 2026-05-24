from __future__ import annotations

from eval.memory_os.adapters.common import make_score
from eval.memory_os.runner.fixture_store import synthetic_store
from eval.memory_os.runner.types import Rh31Case, Rh31Document, Rh31Score
from plugins.memory.memory_os.low_clue_recall import build_low_clue_recall_report


NAME = "low_clue_candidates"


def run(cases: list[Rh31Case], corpus: list[Rh31Document]) -> list[Rh31Score]:
    scores: list[Rh31Score] = []
    low_clue_cases = [case for case in cases if case.family == "low_clue"]
    with synthetic_store(corpus) as store:
        for case in low_clue_cases:
            report = build_low_clue_recall_report(
                case.query,
                store=store,
                limit=4,
                config={"enabled": True, "llm_judge": {"enabled": False, "mode": "none"}},
            )
            decision = str(report.get("decision") or "")
            if case.expected_class == "should_clarify":
                passed = decision in {"ask_choice", "confirm_one", "ask_keyword"}
            else:
                passed = decision in {"direct_resume", "confirm_one", "ask_choice"}
            candidates = report.get("candidates") if isinstance(report.get("candidates"), list) else []
            scores.append(
                make_score(
                    adapter=NAME,
                    case=case,
                    passed=passed,
                    failure_class="low_clue_overcommit",
                    actual_route="ambiguous_recall",
                    source_classes=[str(item.get("source_class") or "unknown") for item in candidates[:4] if isinstance(item, dict)],
                    details={"decision": decision, "candidate_count": len(candidates)},
                )
            )
    return scores
