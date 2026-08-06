"""
Memory-OS recall golden set — stable evaluation framework for recall quality.

Defines a golden set of expected recall results for known queries, enabling
automated evaluation of hit rate, miss rate, context sufficiency, and source
authority.

Architecture
============
A golden set is a JSON file listing (query, expected_results) pairs.  Each
expected result has a recall_type, content_pattern, and optional authority
and source_ref constraints.  The evaluator runs the recall pipeline against
each query and scores the results.

Golden set files live under ``<memory_os_root>/recall_golden/`` and are
named ``<profile>.golden.json``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, fields, asdict
from pathlib import Path
from typing import Any

from .recall_types import RecallType
from .store import MemoryOSStore

GOLDEN_SET_SCHEMA_VERSION = "memory-os.recall_golden_set.v1"


@dataclass(frozen=True)
class GoldenResult:
    """One expected result in a golden set.

    ``source_ref`` and ``authority_class`` are verified against the section
    that actually carried the matching content (backlog 10): ``source_ref``
    must appear in that section's ``source_ids`` and ``authority_class`` must
    equal its ``source_class`` (the ``prefetch.SECTION_SOURCE_CLASS_BY_TITLE``
    vocabulary: crystallized / working / candidate / event / indexed /
    graph_layer / substrate_recall / ...). A former ``min_score`` field was
    removed rather than implemented: no per-section score exists at the
    disclosure surface, so the field could only ever be dead weight — the
    loader ignores it (and any other unknown key) in existing golden files.
    """

    recall_type: str
    content_pattern: str  # regex pattern that must match
    source_ref: str = ""
    authority_class: str = ""
    must_hit: bool = True  # False = must NOT appear (negative test)


@dataclass(frozen=True)
class GoldenQuery:
    """One query in a golden set."""

    query: str
    expected: list[GoldenResult] = field(default_factory=list)
    description: str = ""


@dataclass(frozen=True)
class GoldenSet:
    """A complete golden set for one profile."""

    schema_version: str = GOLDEN_SET_SCHEMA_VERSION
    profile: str = "default"
    queries: list[GoldenQuery] = field(default_factory=list)
    created_at: str = ""
    description: str = ""


@dataclass(frozen=True)
class RecallEvaluationItem:
    """Evaluation result for one (query, golden) pair."""

    query: str
    recall_type: str
    content_pattern: str
    expected_source_ref: str
    must_hit: bool
    matched: bool
    expected_authority: str = ""
    matched_content: str = ""
    matched_source_ref: str = ""
    matched_authority: str = ""
    score: float = 0.0
    error: str = ""


@dataclass(frozen=True)
class RecallEvaluation:
    """Complete evaluation result for a golden set."""

    schema_version: str = GOLDEN_SET_SCHEMA_VERSION
    golden_set: str = ""
    profile: str = "default"
    items: list[RecallEvaluationItem] = field(default_factory=list)
    total_hits: int = 0
    total_misses: int = 0
    total_errors: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    executed_at: str = ""


# ── I/O ────────────────────────────────────────────────────────────────────


def load_golden_set(path: Path) -> GoldenSet:
    """Load a golden set from a JSON file."""
    if not path.exists():
        return GoldenSet(profile=path.stem.replace(".golden", ""))
    raw = json.loads(path.read_text(encoding="utf-8"))
    queries = []
    # Tolerate unknown keys: existing golden files on hosts may carry the
    # removed min_score field (or future additions); crashing the evaluator
    # over schema drift in an observation instrument helps nobody.
    known_fields = {f.name for f in fields(GoldenResult)}
    for q_raw in raw.get("queries", []):
        expected = [
            GoldenResult(**{k: v for k, v in e.items() if k in known_fields})
            for e in q_raw.get("expected", [])
            if isinstance(e, dict)
        ]
        queries.append(
            GoldenQuery(
                query=q_raw.get("query", ""),
                expected=expected,
                description=q_raw.get("description", ""),
            )
        )
    return GoldenSet(
        schema_version=raw.get("schema_version", GOLDEN_SET_SCHEMA_VERSION),
        profile=raw.get("profile", "default"),
        queries=queries,
        created_at=raw.get("created_at", ""),
        description=raw.get("description", ""),
    )


def save_golden_set(path: Path, gs: GoldenSet) -> None:
    """Save a golden set to a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "schema_version": gs.schema_version,
        "profile": gs.profile,
        "queries": [
            {
                "query": q.query,
                "expected": [asdict(e) for e in q.expected],
                "description": q.description,
            }
            for q in gs.queries
        ],
        "created_at": gs.created_at,
        "description": gs.description,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def golden_set_path(roots: Any, *, profile: str = "default") -> Path:
    """Return the path to the golden set file for a profile."""
    from .roots import MemoryOSRoots
    root: Path = roots.memory_os_root if hasattr(roots, "memory_os_root") else Path(str(roots))
    return root / "recall_golden" / f"{profile}.golden.json"


# ── Evaluation ─────────────────────────────────────────────────────────────


def evaluate_recall(
    store: MemoryOSStore,
    golden_set: GoldenSet,
    *,
    profile: str = "default",
) -> RecallEvaluation:
    """Run recall evaluation against a golden set.

    This calls the full recall pipeline (via build_prefetch) for each query
    and checks whether the expected results appear.
    """
    from datetime import datetime, timezone
    from .prefetch import build_prefetch, build_prefetch_section_candidates

    now = datetime.now(timezone.utc)
    items: list[RecallEvaluationItem] = []
    total_hits = 0
    total_misses = 0
    total_errors = 0
    false_positives = 0
    false_negatives = 0

    for gq in golden_set.queries:
        if not gq.query:
            continue
        try:
            prefetch_result = build_prefetch(
                gq.query,
                store=store,
                # Must match the production default (provider prefetch_char_budget
                # = 2200): a larger evaluation budget makes the golden set pass
                # on recall the deployed pipeline would truncate away.
                budget_chars=2200,
                diagnostic_grounding_enabled=False,
            )
        except Exception as exc:
            total_errors += 1
            items.append(RecallEvaluationItem(
                query=gq.query,
                recall_type="",
                content_pattern="",
                expected_source_ref="",
                must_hit=True,
                matched=False,
                error=str(exc),
            ))
            continue

        # Backlog 10: section-level attribution for the authority dimension.
        # Judged separately from hit/miss on purpose: hit/miss runs against the
        # BUDGETED text (what the agent actually sees), while attribution needs
        # the section structure that the flattened string no longer carries.
        # Failure here degrades to "no attribution available" (classification
        # context_insufficient when verification was requested), never to a
        # fabricated authority.
        try:
            sections = build_prefetch_section_candidates(
                gq.query,
                store=store,
                diagnostic_grounding_enabled=False,
            )
        except Exception:
            sections = []

        for expected in gq.expected:
            pattern = re.compile(expected.content_pattern, re.I | re.S)
            matched = bool(pattern.search(prefetch_result))
            matched_section = None
            if matched:
                matched_section = next(
                    (
                        section
                        for section in sections
                        if pattern.search(str(getattr(section, "text", "") or ""))
                    ),
                    None,
                )
            section_ids: list[str] = []
            matched_authority = ""
            if matched_section is not None:
                metadata = getattr(matched_section, "metadata", None)
                raw_ids = metadata.get("source_ids") if isinstance(metadata, dict) else None
                section_ids = [str(value) for value in raw_ids] if isinstance(raw_ids, list) else []
                matched_authority = str(getattr(matched_section, "source_class", "") or "")
            # matched_source_ref is derived from the section that actually
            # matched -- it was previously copied from the EXPECTED value,
            # which made the source_authority_issue classification
            # structurally unreachable.
            if expected.source_ref and expected.source_ref in section_ids:
                matched_source_ref = expected.source_ref
            else:
                matched_source_ref = section_ids[0] if section_ids else ""
            item = RecallEvaluationItem(
                query=gq.query,
                recall_type=expected.recall_type,
                content_pattern=expected.content_pattern,
                expected_source_ref=expected.source_ref,
                expected_authority=expected.authority_class,
                must_hit=expected.must_hit,
                matched=matched,
                matched_content=prefetch_result[:200] if matched else "",
                matched_source_ref=matched_source_ref,
                matched_authority=matched_authority,
                score=1.0 if matched else 0.0,
            )
            items.append(item)

            if expected.must_hit:
                if matched:
                    total_hits += 1
                else:
                    total_misses += 1
                    false_negatives += 1
            else:
                # Negative test: must NOT match
                if matched:
                    false_positives += 1
                    total_misses += 1
                else:
                    total_hits += 1

    return RecallEvaluation(
        schema_version=GOLDEN_SET_SCHEMA_VERSION,
        golden_set=golden_set.description or profile,
        profile=profile,
        items=items,
        total_hits=total_hits,
        total_misses=total_misses,
        total_errors=total_errors,
        false_positives=false_positives,
        false_negatives=false_negatives,
        executed_at=now.isoformat(),
    )


def score_from_evaluation(eval_result: RecallEvaluation) -> dict[str, Any]:
    """Derive a structured score from an evaluation result."""
    total = eval_result.total_hits + eval_result.total_misses
    recall_rate = eval_result.total_hits / total if total > 0 else 0.0
    precision = (
        eval_result.total_hits / (eval_result.total_hits + eval_result.false_positives)
        if (eval_result.total_hits + eval_result.false_positives) > 0
        else 0.0
    )
    return {
        "schema_version": GOLDEN_SET_SCHEMA_VERSION,
        "recall_rate": recall_rate,
        "precision": precision,
        "total_hits": eval_result.total_hits,
        "total_misses": eval_result.total_misses,
        "false_positives": eval_result.false_positives,
        "false_negatives": eval_result.false_negatives,
        "total_errors": eval_result.total_errors,
    }


# ── Reporting ──────────────────────────────────────────────────────────────


def run_golden_set_report(
    store: MemoryOSStore,
    path: Path,
    *,
    profile: str = "default",
) -> dict[str, Any]:
    """Load a golden set from ``path``, evaluate it, and return a report dict.

    Convenience composition of ``load_golden_set`` + ``evaluate_recall`` +
    ``score_from_evaluation`` + ``classify_evaluation_item`` for CLI and
    automation consumers (see ``memory_os_command`` sub-command
    ``recall-golden run`` in ``cli.py``).

    Read-only: this only reads the golden set file at ``path`` (missing file
    yields an empty golden set via ``load_golden_set``, not an error) and
    evaluates it against the live prefetch pipeline via ``evaluate_recall``.
    It never writes a golden set, never mutates canonical memory, and never
    approves or promotes anything.
    """
    golden_set = load_golden_set(path)
    evaluation = evaluate_recall(store, golden_set, profile=profile)
    score = score_from_evaluation(evaluation)
    return {
        "schema_version": GOLDEN_SET_SCHEMA_VERSION,
        "golden_path": str(path),
        "profile": profile,
        "query_count": len(golden_set.queries),
        "score": score,
        "items": [
            {
                "query": item.query,
                "recall_type": item.recall_type,
                "content_pattern": item.content_pattern,
                "expected_source_ref": item.expected_source_ref,
                "expected_authority": item.expected_authority,
                "must_hit": item.must_hit,
                "matched": item.matched,
                "matched_source_ref": item.matched_source_ref,
                "matched_authority": item.matched_authority,
                "classification": classify_evaluation_item(item),
                "error": item.error,
            }
            for item in evaluation.items
        ],
        "executed_at": evaluation.executed_at,
    }


# ── Classification ─────────────────────────────────────────────────────────


def classify_evaluation_item(item: RecallEvaluationItem) -> str:
    """Classify a single evaluation item.

    Returns one of:
    - "hit": correctly recalled
    - "miss_missing": should have been recalled but wasn't
    - "false_positive": should NOT have been recalled but was
    - "error": evaluation failed
    - "context_insufficient": matched, and source/authority verification was
      requested, but the matched disclosure carries no attribution to verify
      against (no section attributable, or the section exposes no source_ids)
    - "source_authority_issue": matched, attribution available, and it
      contradicts the expected source_ref or authority_class
    """
    if item.error:
        return "error"
    if not item.must_hit:
        return "false_positive" if item.matched else "hit"
    if not item.matched:
        return "miss_missing"
    if item.expected_authority:
        if not item.matched_authority:
            return "context_insufficient"
        if item.matched_authority != item.expected_authority:
            return "source_authority_issue"
    if item.expected_source_ref:
        if not item.matched_authority or not item.matched_source_ref:
            # No section attribution, or the section exposes no ids: the
            # expectation cannot be VERIFIED, which is a different failure
            # from a verified mismatch.
            return "context_insufficient"
        if item.matched_source_ref != item.expected_source_ref:
            return "source_authority_issue"
    return "hit"