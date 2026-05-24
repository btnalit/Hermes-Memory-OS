"""RH-31 eval runner.

This runner is report-only. It uses synthetic fixtures, does not read Hermes
private transcripts, and does not write Memory-OS canonical state.
"""

from __future__ import annotations

import importlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from eval.memory_os.data.rh31_synthetic import load_cases, load_corpus
from eval.memory_os.runner.retention import build_report_retention_plan
from eval.memory_os.runner.score import build_summary, scorecard_markdown
from eval.memory_os.runner.types import Rh31Score


FIRST_SIX_ADAPTERS = [
    "grep",
    "memory_os_fts",
    "context_projection",
    "low_clue_candidates",
    "memory_sources_replay",
    "diagnostic_grounding",
]


def run_rh31_eval(
    *,
    fixture: str = "synthetic",
    adapters: list[str] | tuple[str, ...] | None = None,
    report_root: str | Path | None = None,
    write_report: bool = True,
    keep_latest: int = 20,
    retention_days: int = 30,
) -> dict[str, Any]:
    if fixture != "synthetic":
        raise ValueError(f"Unsupported RH-31 fixture: {fixture}")
    adapter_names = _expand_adapters(adapters or ["all"])
    cases = load_cases()
    corpus = load_corpus()
    run_id = _run_id()
    root = Path(report_root) if report_root is not None else Path.cwd() / "eval" / "reports"
    run_dir = root / "memory-os-rh31" / run_id
    scores: list[Rh31Score] = []
    for adapter_name in adapter_names:
        module = importlib.import_module(f"eval.memory_os.adapters.{adapter_name}")
        scores.extend(module.run(cases, corpus))
    retention = build_report_retention_plan(
        root / "memory-os-rh31",
        keep_latest=keep_latest,
        retention_days=retention_days,
    )
    summary = build_summary(
        run_id=run_id,
        fixture=fixture,
        adapter_names=adapter_names,
        scores=scores,
        report_dir=str(run_dir) if write_report else "",
        retention=retention,
    )
    if write_report:
        _write_report(run_dir, summary)
    return summary


def latest_summary(report_root: str | Path | None = None) -> dict[str, Any]:
    root = Path(report_root) if report_root is not None else Path.cwd() / "eval" / "reports"
    report_parent = root / "memory-os-rh31"
    candidates = sorted(report_parent.glob("*/summary.json"), reverse=True)
    if not candidates:
        return {
            "schema_version": "memory-os.rh31_summary.v0",
            "status": "error",
            "code": "rh31_report_missing",
            "report_root": str(report_parent),
        }
    return json.loads(candidates[0].read_text(encoding="utf-8"))


def latest_failures(report_root: str | Path | None = None, *, failure_class: str = "") -> dict[str, Any]:
    root = Path(report_root) if report_root is not None else Path.cwd() / "eval" / "reports"
    report_parent = root / "memory-os-rh31"
    candidates = sorted(report_parent.glob("*/failure_cases.ndjson"), reverse=True)
    if not candidates:
        return {
            "schema_version": "memory-os.rh31_failures.v0",
            "status": "error",
            "code": "rh31_report_missing",
            "records": [],
        }
    records = []
    for line in candidates[0].read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if failure_class and record.get("failure_class") != failure_class:
            continue
        records.append(record)
    return {
        "schema_version": "memory-os.rh31_failures.v0",
        "status": "ok",
        "failure_class": failure_class,
        "record_count": len(records),
        "records": records,
    }


def _write_report(run_dir: Path, summary: dict[str, Any]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    scores = list(summary.get("scores") or [])
    (run_dir / "scores.ndjson").write_text(
        "".join(json.dumps(score, ensure_ascii=False, sort_keys=True) + "\n" for score in scores),
        encoding="utf-8",
    )
    failures = [score for score in scores if score.get("status") == "fail"]
    (run_dir / "failure_cases.ndjson").write_text(
        "".join(json.dumps(score, ensure_ascii=False, sort_keys=True) + "\n" for score in failures),
        encoding="utf-8",
    )
    (run_dir / "source_distribution.json").write_text(
        json.dumps(summary.get("source_distribution") or {}, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (run_dir / "scorecard.md").write_text(scorecard_markdown(summary), encoding="utf-8")


def _expand_adapters(adapters: list[str] | tuple[str, ...]) -> list[str]:
    names: list[str] = []
    for adapter in adapters:
        value = str(adapter or "").strip()
        if not value:
            continue
        if value == "all":
            names.extend(FIRST_SIX_ADAPTERS)
        else:
            names.append(value)
    deduped: list[str] = []
    for name in names:
        if name not in FIRST_SIX_ADAPTERS:
            raise ValueError(f"Unsupported RH-31 adapter: {name}")
        if name not in deduped:
            deduped.append(name)
    return deduped or list(FIRST_SIX_ADAPTERS)


def _run_id() -> str:
    return "rh31_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
