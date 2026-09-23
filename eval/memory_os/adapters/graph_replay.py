"""G4 — offline graph replay evaluation.

Report-only, deterministic: every run rebuilds real Memory-OS stores from a
labelled synthetic corpus (``eval/memory_os/data/graph_replay_cases.jsonl``)
and drives the REAL producers (``structural_edge_proposer.run_structural_proposer``,
``prefetch._graph_layer_shadow_lines``) rather than replaying a frozen
golden-edges file — the labels are human judgments about what SHOULD happen
to a given record pair, not a snapshot of what the code once did.

Measures (see docs/plans/2026-09-23-memory-os-next-phase-plan.md Phase 3
rows PR-G1/G4):
  - updates-detection accuracy per labelled subset (recall on
    near_verbatim_restatement, false-positive rate on paraphrase_low_dice /
    cross_kind_high_overlap),
  - direction correctness (newer endpoint) for detected updates edges,
  - injection-outcome distribution (novelty, redundancy via emitted_stub,
    slot waste via target_inactive, coverage), and, once PR-G1 lands,
  - stale_version_injection_count / superseded_by_newer_count.

Every ratio is reported alongside its sample size and a closed ``status``
(``sampled`` / ``healthy_no_sample``) — an empty denominator must never be
silently read as 0.0 or 1.0 (era-boundary rule: an empty gated set reports
no-sample, never PASS-by-omission).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from eval.memory_os.adapters.common import make_score
from eval.memory_os.runner.fixture_store import graph_replay_pair_store
from eval.memory_os.runner.safety import forbidden_field_count
from eval.memory_os.runner.types import Rh31Case, Rh31Document, Rh31Score

NAME = "graph_replay"
SCHEMA_VERSION = "memory-os.graph_replay_eval.v0"
DEFAULT_CASES_PATH = Path(__file__).resolve().parents[1] / "data" / "graph_replay_cases.jsonl"

# Subsets whose expect_updates is True — recall is measured here.
_POSITIVE_SUBSETS = frozenset({"near_verbatim_restatement"})
# Subsets that must never get a deterministic `updates` edge — false
# positives here are graded, not merely observed.
_NEGATIVE_SUBSETS = frozenset({"paraphrase_low_dice", "cross_kind_high_overlap", "unrelated_same_kind"})
_ALL_SUBSETS = _POSITIVE_SUBSETS | _NEGATIVE_SUBSETS


def build_graph_replay_report(cases_path: str | Path | None = None) -> dict[str, Any]:
    rows = _load_rows(Path(cases_path) if cases_path is not None else DEFAULT_CASES_PATH)

    per_case: list[dict[str, Any]] = []
    subset_counts: dict[str, int] = {name: 0 for name in _ALL_SUBSETS}
    subset_updates_hits: dict[str, int] = {name: 0 for name in _ALL_SUBSETS}
    direction_correct = 0
    direction_total = 0
    outcome_distribution: dict[str, int] = {}
    injected_novelties: list[float] = []
    stale_version_injection_count = 0
    superseded_by_newer_count = 0
    latest_wins_expected = 0
    latest_wins_observed = 0
    emitted_case_count = 0
    edge_found_case_count = 0

    for row in rows:
        case_id = str(row.get("case_id") or "")
        subset = str(row.get("subset") or "unknown")
        expect_updates = bool(row.get("expect_updates"))
        record_a = dict(row.get("record_a") or {})
        record_b = dict(row.get("record_b") or {})
        anchor_side = str(row.get("anchor") or "a")
        query = str(row.get("query") or "")
        expected_newer_id = row.get("expected_newer_id")

        subset_counts[subset] = subset_counts.get(subset, 0) + 1

        case_detail = _run_case(
            case_id=case_id,
            record_a=record_a,
            record_b=record_b,
            anchor_side=anchor_side,
            query=query,
        )
        actual_relation = case_detail["actual_relation"]
        actual_got_updates = actual_relation == "updates"
        if actual_got_updates:
            subset_updates_hits[subset] = subset_updates_hits.get(subset, 0) + 1

        if actual_got_updates and expected_newer_id:
            direction_total += 1
            if case_detail["actual_newer_id"] == expected_newer_id:
                direction_correct += 1

        if case_detail["edge_found"]:
            edge_found_case_count += 1
        if case_detail["injected_count"] > 0:
            emitted_case_count += 1
        for outcome, count in case_detail["outcome_counts"].items():
            outcome_distribution[outcome] = outcome_distribution.get(outcome, 0) + count
        injected_novelties.extend(case_detail["injected_novelties"])
        stale_version_injection_count += case_detail["stale_version_injection_count"]
        case_superseded = case_detail["outcome_counts"].get("superseded_by_newer", 0)
        superseded_by_newer_count += case_superseded
        # Anchored on the newer endpoint, the older one reaches the candidate
        # set only through the updates edge itself — prefetch step 1b must
        # suppress it. This is the injection half of PR-G1; without it the
        # gate below measures only edge detection.
        if actual_got_updates and case_detail["anchor_id"] == case_detail["actual_newer_id"]:
            latest_wins_expected += 1
            if case_superseded > 0:
                latest_wins_observed += 1

        per_case.append({
            "case_id": case_id,
            "subset": subset,
            "expect_updates": expect_updates,
            "actual_relation": actual_relation,
            "correct": actual_got_updates == expect_updates,
            "dice": row.get("dice"),
        })

    subset_reports: dict[str, Any] = {}
    for subset in sorted(_ALL_SUBSETS):
        total = subset_counts.get(subset, 0)
        hits = subset_updates_hits.get(subset, 0)
        if total == 0:
            subset_reports[subset] = {"status": "healthy_no_sample", "case_count": 0}
            continue
        if subset in _POSITIVE_SUBSETS:
            subset_reports[subset] = {
                "status": "sampled",
                "case_count": total,
                "updates_recall": hits / total,
            }
        else:
            subset_reports[subset] = {
                "status": "sampled",
                "case_count": total,
                "false_positive_count": hits,
                "false_positive_rate": hits / total,
            }

    direction_report = (
        {"status": "sampled", "sample_count": direction_total, "accuracy": direction_correct / direction_total}
        if direction_total > 0
        else {"status": "healthy_no_sample", "sample_count": 0}
    )

    novelty_report = (
        {
            "status": "sampled",
            "sample_count": len(injected_novelties),
            "mean_injected_novelty": sum(injected_novelties) / len(injected_novelties),
        }
        if injected_novelties
        else {"status": "healthy_no_sample", "sample_count": 0, "mean_injected_novelty": None}
    )

    latest_wins_report = (
        {"status": "sampled", "expected_count": latest_wins_expected, "observed_count": latest_wins_observed}
        if latest_wins_expected > 0
        else {"status": "healthy_no_sample", "expected_count": 0, "observed_count": 0}
    )

    coverage = (
        {"status": "sampled", "case_count": len(rows), "coverage_rate": emitted_case_count / len(rows)}
        if rows
        else {"status": "healthy_no_sample", "case_count": 0}
    )

    total_outcomes = sum(outcome_distribution.values())
    redundancy_report = (
        {
            "status": "sampled",
            "outcome_sample_count": total_outcomes,
            "emitted_stub_share": outcome_distribution.get("emitted_stub", 0) / total_outcomes,
        }
        if total_outcomes
        else {"status": "healthy_no_sample", "outcome_sample_count": 0}
    )
    slot_waste_report = (
        {
            "status": "sampled",
            "outcome_sample_count": total_outcomes,
            "target_inactive_share": outcome_distribution.get("target_inactive", 0) / total_outcomes,
        }
        if total_outcomes
        else {"status": "healthy_no_sample", "outcome_sample_count": 0}
    )

    boundaries = {
        "actual_send": False,
        "actual_execute": False,
        "actual_identity_write": False,
        "actual_crystallized_approval": False,
    }
    report = {
        "schema_version": SCHEMA_VERSION,
        "case_count": len(rows),
        "edge_found_case_count": edge_found_case_count,
        "subset_case_counts": {k: subset_counts.get(k, 0) for k in sorted(_ALL_SUBSETS)},
        "subset_reports": subset_reports,
        "direction_report": direction_report,
        "novelty_report": novelty_report,
        "coverage_report": coverage,
        "redundancy_report": redundancy_report,
        "slot_waste_report": slot_waste_report,
        "outcome_distribution": dict(sorted(outcome_distribution.items())),
        "stale_version_injection_count": stale_version_injection_count,
        "superseded_by_newer_count": superseded_by_newer_count,
        "latest_wins_report": latest_wins_report,
        "case_results": per_case,
        "route_live_applied": False,
        "score_live_applied": False,
        "canonical_state_changed": False,
        "boundaries": boundaries,
    }
    report["boundary_true_count"] = sum(1 for value in boundaries.values() if value)
    report["forbidden_field_count"] = forbidden_field_count(report)
    return report


def run(cases: list[Rh31Case], corpus: list[Rh31Document]) -> list[Rh31Score]:
    report = build_graph_replay_report()
    case = cases[0] if cases else Rh31Case(case_id="graph_replay_summary", query="", expected_class="graph_replay")

    def _recall_ok() -> bool:
        for subset in _POSITIVE_SUBSETS:
            entry = report["subset_reports"].get(subset, {})
            if entry.get("status") == "sampled" and entry.get("updates_recall", 0.0) < 1.0:
                return False
        return True

    def _no_false_positives() -> bool:
        for subset in _NEGATIVE_SUBSETS:
            entry = report["subset_reports"].get(subset, {})
            if entry.get("status") == "sampled" and entry.get("false_positive_count", 0) != 0:
                return False
        return True

    def _latest_wins_ok() -> bool:
        # A sampled positive subset with no newer-anchored case would leave
        # the injection half unmeasured, so that is a failure, not a pass.
        latest = report["latest_wins_report"]
        positive_sampled = any(
            report["subset_reports"].get(subset, {}).get("status") == "sampled"
            for subset in _POSITIVE_SUBSETS
        )
        if latest["status"] != "sampled":
            return not positive_sampled
        return latest["observed_count"] == latest["expected_count"]

    passed = (
        report["case_count"] > 0
        and _recall_ok()
        and _no_false_positives()
        and _latest_wins_ok()
        and report["stale_version_injection_count"] == 0
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
                case_id="graph_replay_summary",
                query=case.query,
                expected_class="graph_replay",
                family="graph_replay",
            ),
            passed=passed,
            metric_scope="graph_replay",
            failure_class="graph_replay_updates_regression",
            source_classes=sorted(report["subset_case_counts"]),
            details=report,
        )
    ]


def _load_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parsed = json.loads(line)
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows


def _run_case(
    *,
    case_id: str,
    record_a: dict[str, Any],
    record_b: dict[str, Any],
    anchor_side: str,
    query: str,
) -> dict[str, Any]:
    """Build an isolated pair store, run the real proposer + prefetch
    injection path once, and read back the single shadow record it wrote
    (0 or 1 rows — this store never sees any other case's data)."""
    from plugins.memory.memory_os.structural_edge_proposer import run_structural_proposer
    from plugins.memory.memory_os.prefetch import _graph_layer_shadow_lines

    rid_a = str(record_a["id"])
    rid_b = str(record_b["id"])
    anchor_id = rid_a if anchor_side == "a" else rid_b

    with graph_replay_pair_store(record_a, record_b) as (store, index):
        run_structural_proposer(
            str(store.roots.index_path),
            index=index,
            audit_path=str(store.roots.audit_path),
        )

        actual_relation = "none"
        actual_newer_id = None
        edge_found = False
        edges = _query_active_edges(store, rid_a, rid_b)
        if edges:
            edge_found = True
            # A pair carries at most one active structural edge (write-boundary
            # pair-level dedup) — take the first.
            edge = edges[0]
            actual_relation = str(edge.get("relation_type") or "none")
            if actual_relation == "updates":
                actual_newer_id = str(edge.get("from_record_id") or "")

        _graph_layer_shadow_lines(
            store,
            [anchor_id],
            index=index,
            seen=set(),
            source_ids=[],
            events=[],
            query=query,
            session_id=f"graph_replay_{case_id}",
        )

        shadow_row = _read_last_shadow_row(store)
        outcome_counts: dict[str, int] = {}
        injected_novelties: list[float] = []
        injected_count = 0
        stale_version_injection_count = 0
        if shadow_row:
            injected_count = int(shadow_row.get("injected_count") or 0)
            injected_pair_ids: set[str] = set()
            for edge_row in shadow_row.get("edges") or []:
                if not isinstance(edge_row, dict):
                    continue
                outcome = str(edge_row.get("outcome") or "unknown")
                outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
                if edge_row.get("injected"):
                    novelty = edge_row.get("novelty")
                    if isinstance(novelty, (int, float)) and not isinstance(novelty, bool):
                        injected_novelties.append(float(novelty))
                    if str(edge_row.get("relation_type") or "") == "updates":
                        pair_key = f"{edge_row.get('from_record_id')}|{edge_row.get('to_record_id')}"
                        if pair_key in injected_pair_ids:
                            stale_version_injection_count += 1
                        injected_pair_ids.add(pair_key)

        return {
            "anchor_id": anchor_id,
            "actual_relation": actual_relation,
            "actual_newer_id": actual_newer_id,
            "edge_found": edge_found,
            "injected_count": injected_count,
            "outcome_counts": outcome_counts,
            "injected_novelties": injected_novelties,
            "stale_version_injection_count": stale_version_injection_count,
        }


def _query_active_edges(store, rid_a: str, rid_b: str) -> list[dict[str, Any]]:
    import sqlite3

    conn = sqlite3.connect(str(store.roots.index_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "select * from memory_edges where state = 'active'"
            " and ((from_record_id = ? and to_record_id = ?)"
            "   or (from_record_id = ? and to_record_id = ?))",
            (rid_a, rid_b, rid_b, rid_a),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    return [dict(r) for r in rows]


def _read_last_shadow_row(store) -> dict[str, Any] | None:
    path = store.roots.memory_os_root / "system" / "graph_layer_shadow.jsonl"
    if not path.exists():
        return None
    last: dict[str, Any] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            last = parsed
    return last
