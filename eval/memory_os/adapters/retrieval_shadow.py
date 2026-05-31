from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any

from eval.memory_os.adapters.common import make_score
from eval.memory_os.runner.safety import forbidden_field_count
from eval.memory_os.runner.types import Rh31Case, Rh31Document, Rh31Score


NAME = "retrieval_shadow"
SCHEMA_VERSION = "memory-os.retrieval_shadow_eval.v0"
DEFAULT_CASES_PATH = Path(__file__).resolve().parents[1] / "data" / "retrieval_shadow_cases.jsonl"
RRF_K = 60
_ALLOWED_SOURCE_ID_PATTERNS = (
    re.compile(r"^event:[A-Za-z0-9_.:-]+$"),
    re.compile(r"^working:[A-Za-z0-9_.:-]+$"),
    re.compile(r"^candidate:[A-Za-z0-9_.:-]+$"),
    re.compile(r"^crystallized:[A-Za-z0-9_.:-]+$"),
    re.compile(r"^digest:[A-Za-z0-9_.:-]+$"),
    re.compile(r"^reflection_card:[A-Za-z0-9_.:-]+$"),
    re.compile(r"^governance_feedback:[A-Za-z0-9_.:-]+$"),
    re.compile(r"^proposal:[A-Za-z0-9_.:-]+$"),
    re.compile(r"^foreground_task:[A-Za-z0-9_.:-]+$"),
)


def build_retrieval_shadow_report(
    cases_path: str | Path | None = None,
    *,
    hermes_home: str | Path | None = None,
    memory_sources_limit: int = 200,
) -> dict[str, Any]:
    rows = _load_rows(Path(cases_path) if cases_path is not None else DEFAULT_CASES_PATH)
    details: list[dict[str, Any]] = []
    source_distribution: Counter[str] = Counter()
    lexical_hit_count = 0
    hybrid_hit_count = 0
    semantic_gap_count = 0
    rrf_rank_count = 0

    for row in rows:
        expected_ref = str(row.get("expected_source_ref") or "")
        lexical = _normalize_candidates(row.get("lexical_candidates"))
        hybrid = _normalize_candidates(row.get("hybrid_candidates"))
        source_class = str(row.get("source_class") or "unknown")
        if source_class:
            source_distribution[source_class] += 1
        lexical_refs = {item["source_ref"] for item in lexical}
        hybrid_refs = {item["source_ref"] for item in hybrid}
        lexical_hit = bool(expected_ref and expected_ref in lexical_refs)
        hybrid_hit = bool(expected_ref and expected_ref in hybrid_refs)
        rrf_ranked = bool(expected_ref and _rrf_rank(lexical, hybrid).get(expected_ref, 0.0) > 0)
        lexical_hit_count += int(lexical_hit)
        hybrid_hit_count += int(hybrid_hit)
        semantic_gap_count += int(hybrid_hit and not lexical_hit)
        rrf_rank_count += int(rrf_ranked)
        details.append(
            {
                "case_id": str(row.get("case_id") or ""),
                "expected_source_ref": expected_ref,
                "source_class": source_class,
                "lexical_hit": lexical_hit,
                "hybrid_hit": hybrid_hit,
                "rrf_ranked": rrf_ranked,
            }
        )

    boundaries = {
        "actual_send": False,
        "actual_execute": False,
        "actual_identity_write": False,
        "actual_crystallized_approval": False,
    }
    report = {
        "schema_version": SCHEMA_VERSION,
        "run_count": 1,
        "case_count": len(rows),
        "lexical_baseline_hit_count": lexical_hit_count,
        "hybrid_would_retrieve_count": hybrid_hit_count,
        "semantic_gap_count": semantic_gap_count,
        "rrf_would_rank_count": rrf_rank_count,
        "source_class_distribution": dict(sorted(source_distribution.items())),
        "case_results": details,
        "route_live_applied": False,
        "score_live_applied": False,
        "canonical_state_changed": False,
        "boundaries": boundaries,
    }
    report.update(_live_memory_sources_shadow(hermes_home=hermes_home, limit=memory_sources_limit))
    report["boundary_true_count"] = sum(1 for value in boundaries.values() if value)
    report["forbidden_field_count"] = forbidden_field_count(report)
    return report


def run(cases: list[Rh31Case], corpus: list[Rh31Document]) -> list[Rh31Score]:
    report = build_retrieval_shadow_report()
    case = cases[0] if cases else Rh31Case(case_id="retrieval_shadow_summary", query="", expected_class="retrieval_shadow")
    passed = (
        report["semantic_gap_count"] >= 1
        and report["hybrid_would_retrieve_count"] >= 1
        and report["rrf_would_rank_count"] >= 1
        and report["boundary_true_count"] == 0
        and report["forbidden_field_count"] == 0
        and report["route_live_applied"] is False
        and report["score_live_applied"] is False
        and report["canonical_state_changed"] is False
    )
    return [
        make_score(
            adapter=NAME,
            case=Rh31Case(
                case_id="retrieval_shadow_summary",
                query=case.query,
                expected_class="retrieval_shadow",
                family="retrieval_shadow",
            ),
            passed=passed,
            metric_scope="retrieval_shadow",
            failure_class="retrieval_shadow_contract_gap",
            source_classes=sorted(report["source_class_distribution"]),
            details=report,
        )
    ]


def _load_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parsed = json.loads(line)
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows


def _live_memory_sources_shadow(*, hermes_home: str | Path | None, limit: int) -> dict[str, Any]:
    records = _read_live_memory_source_records(hermes_home=hermes_home, limit=limit)
    route_distribution: Counter[str] = Counter()
    query_class_distribution: Counter[str] = Counter()
    selected_source_classes: Counter[str] = Counter()
    dropped_source_classes: Counter[str] = Counter()
    safe_source_refs: set[str] = set()
    source_selection_miss_count = 0
    diversification_gap_count = 0
    low_coverage_count = 0
    would_rank_count = 0

    for record in records:
        route_distribution[str(record.get("route") or "unknown")] += 1
        query_class_distribution[str(record.get("query_class") or "unknown")] += 1
        selected = _safe_sections(record.get("selected"))
        dropped = _safe_sections(record.get("dropped"))
        selected_classes: set[str] = set()
        dropped_classes: set[str] = set()
        for section in selected:
            source_class = str(section.get("source_class") or "unknown")
            selected_classes.add(source_class)
            selected_source_classes[source_class] += 1
            for source_id in section.get("source_ids") if isinstance(section.get("source_ids"), list) else []:
                value = str(source_id or "")
                if _safe_source_id(value):
                    safe_source_refs.add(value)
        for section in dropped:
            source_class = str(section.get("source_class") or "unknown")
            dropped_classes.add(source_class)
            dropped_source_classes[source_class] += 1
        selected_chars = _non_negative_int(record.get("selected_chars_total"))
        if not selected and dropped:
            source_selection_miss_count += 1
        if dropped_classes and (not selected_classes or bool(dropped_classes - selected_classes)):
            diversification_gap_count += 1
        if selected_chars <= 0 or not selected:
            low_coverage_count += 1
        if selected or dropped:
            would_rank_count += 1

    return {
        "live_input_source": "memory_sources_metadata",
        "live_input_available": bool(records),
        "live_memory_sources_record_count": len(records),
        "live_bounded_source_ref_count": len(safe_source_refs),
        "live_route_distribution": dict(sorted(route_distribution.items())),
        "live_query_class_distribution": dict(sorted(query_class_distribution.items())),
        "live_selected_source_class_distribution": dict(sorted(selected_source_classes.items())),
        "live_dropped_source_class_distribution": dict(sorted(dropped_source_classes.items())),
        "live_shadow_source_selection_miss_count": source_selection_miss_count,
        "live_shadow_diversification_gap_count": diversification_gap_count,
        "live_shadow_low_coverage_count": low_coverage_count,
        "live_shadow_would_rank_count": would_rank_count,
        "live_route_live_applied": False,
        "live_score_live_applied": False,
        "live_canonical_state_changed": False,
    }


def _read_live_memory_source_records(*, hermes_home: str | Path | None, limit: int) -> list[dict[str, Any]]:
    path = _memory_sources_path(hermes_home)
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            records.append(parsed)
    safe_limit = max(int(limit), 0)
    if safe_limit <= 0:
        return []
    return records[-safe_limit:]


def _memory_sources_path(hermes_home: str | Path | None) -> Path:
    if hermes_home is None:
        hermes_home = os.environ.get("HERMES_HOME") or Path.home() / ".hermes"
    return Path(hermes_home).expanduser() / "memory-os" / "system" / "memory_sources.jsonl"


def _safe_sections(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _safe_source_id(value: str) -> bool:
    return any(pattern.match(value) for pattern in _ALLOWED_SOURCE_ID_PATTERNS)


def _normalize_candidates(value: Any) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return candidates
    for index, item in enumerate(value, start=1):
        if isinstance(item, str):
            source_ref = item
            source_class = "unknown"
            rank = index
        elif isinstance(item, dict):
            source_ref = str(item.get("source_ref") or item.get("id") or "")
            source_class = str(item.get("source_class") or "unknown")
            rank = _positive_int(item.get("rank"), default=index)
        else:
            continue
        if not source_ref:
            continue
        candidates.append({"source_ref": source_ref, "source_class": source_class, "rank": rank})
    return candidates


def _rrf_rank(*candidate_lists: list[dict[str, Any]]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for candidates in candidate_lists:
        for index, item in enumerate(candidates, start=1):
            source_ref = item["source_ref"]
            rank = _positive_int(item.get("rank"), default=index)
            scores[source_ref] = scores.get(source_ref, 0.0) + 1.0 / (RRF_K + rank)
    return scores


def _positive_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(parsed, 1)


def _non_negative_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(parsed, 0)
