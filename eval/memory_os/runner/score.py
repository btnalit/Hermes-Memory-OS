"""RH-31 score aggregation."""

from __future__ import annotations

from collections import Counter
from typing import Any

from eval.memory_os.runner.types import Rh31Score


def build_summary(
    *,
    run_id: str,
    fixture: str,
    adapter_names: list[str],
    scores: list[Rh31Score],
    report_dir: str,
    retention: dict[str, Any],
) -> dict[str, Any]:
    score_dicts = [score.to_dict() for score in scores]
    failures = [score for score in score_dicts if score.get("status") == "fail"]
    boundary_true_count = sum(1 for score in score_dicts if score.get("boundary_true") is True)
    forbidden_field_count = sum(int(score.get("forbidden_field_count") or 0) for score in score_dicts)
    failure_classes = Counter(
        str(score.get("failure_class") or "none") for score in score_dicts if score.get("failure_class")
    )
    source_distribution = Counter()
    for score in score_dicts:
        for source_class in score.get("source_classes") or []:
            source_distribution[str(source_class)] += 1
    if boundary_true_count or forbidden_field_count:
        status = "fail"
    elif failures:
        status = "warning"
    else:
        status = "pass"
    return {
        "schema_version": "memory-os.rh31_summary.v0",
        "run_id": run_id,
        "fixture": fixture,
        "status": status,
        "adapter_count": len(adapter_names),
        "adapters": [{"name": name, "deterministic": True} for name in adapter_names],
        "case_count": len({score.case_id for score in scores}),
        "score_count": len(scores),
        "failure_count": len(failures),
        "failure_class_distribution": dict(failure_classes),
        "source_distribution": dict(source_distribution),
        "boundary_true_count": boundary_true_count,
        "forbidden_field_count": forbidden_field_count,
        "report_dir": report_dir,
        "retention": retention,
        "scores": score_dicts,
    }


def scorecard_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# RH-31 Recall Eval Scorecard",
        "",
        f"- run_id: `{summary.get('run_id')}`",
        f"- fixture: `{summary.get('fixture')}`",
        f"- status: `{summary.get('status')}`",
        f"- adapters: {', '.join(adapter['name'] for adapter in summary.get('adapters', []))}",
        f"- boundary_true_count: {summary.get('boundary_true_count')}",
        f"- forbidden_field_count: {summary.get('forbidden_field_count')}",
        "",
        "| adapter | case | status | failure_class | metric_scope |",
        "| --- | --- | --- | --- | --- |",
    ]
    for score in summary.get("scores", []):
        lines.append(
            "| {adapter} | {case_id} | {status} | {failure_class} | {metric_scope} |".format(
                adapter=score.get("adapter", ""),
                case_id=score.get("case_id", ""),
                status=score.get("status", ""),
                failure_class=score.get("failure_class") or "",
                metric_scope=score.get("metric_scope", ""),
            )
        )
    return "\n".join(lines) + "\n"
