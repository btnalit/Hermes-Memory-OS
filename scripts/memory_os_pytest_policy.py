#!/usr/bin/env python3
"""Pytest policy gate for classified skips and warnings.

The gate deliberately does not pin test/pass/skip totals.  It fails only when a
skip or warning is unknown, a known skip/warning class exceeds its explicit
bound, or a warning originates from project-owned code.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Pattern

import pytest


SCHEMA_VERSION = "memory-os.pytest_policy.v1"


@dataclass(frozen=True)
class ReasonRule:
    rule_id: str
    pattern: re.Pattern[str]
    max_count: int
    nodeid_pattern: re.Pattern[str] | None = None
    warning_category: str | None = None
    filename_pattern: re.Pattern[str] | None = None
    allowed_stages: tuple[str, ...] = ("call",)

SKIP_RULES = (
    ReasonRule(
        "internal_closure_docs_absent",
        re.compile(r"^internal closure matrix docs are not included in public checkouts$"),
        10,
        nodeid_pattern=re.compile(
            r"^tests/scripts/test_memory_os_closure_matrix_check\.py::(?:"
            r"test_closure_matrix_check_passes_for_current_repo|"
            r"test_closure_matrix_check_fails_when_live_module_row_is_missing|"
            r"test_closure_matrix_check_rejects_freeform_classification_text|"
            r"test_closure_matrix_check_accepts_expression_feedback_class|"
            r"test_closure_matrix_check_fails_when_active_work_mapping_is_missing)$"
        ),
        allowed_stages=("setup", "call"),
    ),
    ReasonRule(
        "sentence_transformers_absent",
        re.compile(r"^sentence-transformers not installed$"),
        4,
        nodeid_pattern=re.compile(
            r"^tests/plugins/memory/test_memory_os_embedder\.py::TestLocalEmbedderEmbed::(?:"
            r"test_embed_returns_bytes|test_embed_deterministic|"
            r"test_embed_different_texts_different_vectors|test_embed_query_returns_ndarray)$"
        ),
    ),
    ReasonRule(
        "hermes_agent_absent",
        re.compile(r"^Hermes agent not installed(?: .*)?$"),
        3,
        nodeid_pattern=re.compile(
            r"^tests/plugins/memory/test_memory_os_hermes_contract\.py::(?:"
            r"TestABCImport::test_provider_inherits_from_host_abc_when_available|"
            r"TestABCImport::test_vendored_abc_has_same_abstractmethods_as_host|"
            r"TestSyncTurnSignature::test_sync_turn_signature_matches_host_abc)$"
        ),
    ),
    ReasonRule(
        "compaction_cancelled_anchor_absent",
        re.compile(r"^anchor was cleared, not formatted as cancelled$"),
        1,
        nodeid_pattern=re.compile(
            r"^tests/plugins/memory/test_memory_os_compaction_stability\.py::"
            r"test_a10_capture_turn_operations_noops_on_cancelled_anchor$"
        ),
    ),
    ReasonRule(
        "compaction_deferred_anchor_absent",
        re.compile(r"^anchor was not formatted as deferred$"),
        1,
        nodeid_pattern=re.compile(
            r"^tests/plugins/memory/test_memory_os_compaction_stability\.py::"
            r"test_a11_capture_turn_operations_noops_on_deferred_anchor$"
        ),
    ),
)

DEPENDENCY_WARNING_RULES = (
    ReasonRule(
        "swig_packed_missing_module",
        re.compile(r"^builtin type SwigPyPacked has no __module__ attribute$"),
        2,
        warning_category="DeprecationWarning",
        filename_pattern=re.compile(r"^<frozen importlib\._bootstrap>$"),
    ),
    ReasonRule(
        "swig_object_missing_module",
        re.compile(r"^builtin type SwigPyObject has no __module__ attribute$"),
        2,
        warning_category="DeprecationWarning",
        filename_pattern=re.compile(r"^<frozen importlib\._bootstrap>$"),
    ),
    ReasonRule(
        "swig_varlink_missing_module",
        re.compile(r"^builtin type swigvarlink has no __module__ attribute$"),
        2,
        warning_category="DeprecationWarning",
        filename_pattern=re.compile(r"^<frozen importlib\._bootstrap>$"),
    ),
)


def normalize_skip_reason(reason: str) -> str:
    normalized = str(reason or "").strip()
    if normalized.startswith("Skipped: "):
        return normalized[len("Skipped: ") :].strip()
    return normalized


def _matching_rule(
    value: str,
    rules: tuple[ReasonRule, ...],
    *,
    nodeid: str | None = None,
    stage: str = "call",
) -> ReasonRule | None:
    return next(
        (
            rule
            for rule in rules
            if rule.pattern.fullmatch(value)
            and stage in rule.allowed_stages
            and (
                rule.nodeid_pattern is None
                or (nodeid is not None and rule.nodeid_pattern.search(nodeid))
            )
        ),
        None,
    )


def _matching_warning_rule(
    message: str,
    *,
    category: str,
    filename: str,
) -> ReasonRule | None:
    rule = _matching_rule(message, DEPENDENCY_WARNING_RULES)
    if rule is None:
        return None
    if rule.warning_category is not None and category != rule.warning_category:
        return None
    if rule.filename_pattern is not None and not rule.filename_pattern.fullmatch(filename):
        return None
    return rule


def _is_project_owned(filename: str, repo_root: Path) -> bool:
    if not filename or filename.startswith("<"):
        return False
    candidate = Path(filename)
    if not candidate.is_absolute():
        candidate = repo_root / candidate
    try:
        candidate.resolve().relative_to(repo_root.resolve())
    except (OSError, ValueError):
        return False
    return True


def evaluate_policy(
    *,
    skips: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    repo_root: Path,
) -> dict[str, Any]:
    classified_skips: list[dict[str, Any]] = []
    skip_rule_counts: Counter[str] = Counter()
    unknown_skips: list[dict[str, Any]] = []
    for item in skips:
        reason = normalize_skip_reason(str(item.get("reason") or ""))
        nodeid = str(item.get("nodeid") or "")
        stage = str(item.get("stage") or "call")
        rule = (
            None
            if stage == "collect"
            else _matching_rule(reason, SKIP_RULES, nodeid=nodeid, stage=stage)
        )
        record = {
            **item,
            "stage": stage,
            "reason": reason,
            "rule_id": rule.rule_id if rule else None,
        }
        classified_skips.append(record)
        if rule is None:
            unknown_skips.append(record)
        else:
            skip_rule_counts[rule.rule_id] += 1

    skip_overflows = [
        {
            "rule_id": rule.rule_id,
            "count": skip_rule_counts[rule.rule_id],
            "max_count": rule.max_count,
        }
        for rule in SKIP_RULES
        if skip_rule_counts[rule.rule_id] > rule.max_count
    ]

    classified_warnings: list[dict[str, Any]] = []
    project_warnings: list[dict[str, Any]] = []
    unknown_warnings: list[dict[str, Any]] = []
    dependency_rule_counts: Counter[str] = Counter()
    for item in warnings:
        message = str(item.get("message") or "").strip()
        filename = str(item.get("filename") or "")
        category = str(item.get("category") or "")
        dependency_rule = _matching_warning_rule(
            message,
            category=category,
            filename=filename,
        )
        if _is_project_owned(filename, repo_root):
            classification = "project_owned"
            rule_id = None
            project_warnings.append(item)
        elif dependency_rule is not None:
            classification = "allowed_dependency"
            rule_id = dependency_rule.rule_id
            dependency_rule_counts[rule_id] += 1
        else:
            classification = "unknown"
            rule_id = None
            unknown_warnings.append(item)
        classified_warnings.append(
            {**item, "classification": classification, "rule_id": rule_id}
        )

    warning_overflows = [
        {
            "rule_id": rule.rule_id,
            "count": dependency_rule_counts[rule.rule_id],
            "max_count": rule.max_count,
        }
        for rule in DEPENDENCY_WARNING_RULES
        if dependency_rule_counts[rule.rule_id] > rule.max_count
    ]
    allowed_dependency_warning_count = sum(dependency_rule_counts.values())
    failed = bool(
        unknown_skips
        or skip_overflows
        or project_warnings
        or unknown_warnings
        or warning_overflows
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "fail" if failed else "pass",
        "skip_count": len(skips),
        "unknown_skip_count": len(unknown_skips),
        "skip_allowlist_overflow_count": len(skip_overflows),
        "skip_rule_counts": dict(sorted(skip_rule_counts.items())),
        "warning_count": len(warnings),
        "project_owned_warning_count": len(project_warnings),
        "unknown_warning_count": len(unknown_warnings),
        "allowed_dependency_warning_count": allowed_dependency_warning_count,
        "warning_allowlist_overflow_count": len(warning_overflows),
        "dependency_warning_rule_counts": dict(sorted(dependency_rule_counts.items())),
        "skip_allowlist_overflows": skip_overflows,
        "warning_allowlist_overflows": warning_overflows,
        "skips": classified_skips,
        "warnings": classified_warnings,
    }


class _PolicyCollector:
    def __init__(self, *, report_path: Path, repo_root: Path) -> None:
        self.report_path = report_path
        self.repo_root = repo_root
        self.skips: list[dict[str, Any]] = []
        self._skip_keys: set[tuple[str, str, str]] = set()
        self.warnings: list[dict[str, Any]] = []

    def add_skip(self, report: Any, *, stage: str) -> None:
        reason = ""
        if isinstance(report.longrepr, tuple) and len(report.longrepr) >= 3:
            reason = str(report.longrepr[2])
        else:
            reason = str(report.longrepr or "")
        nodeid = str(report.nodeid)
        key = (stage, nodeid, normalize_skip_reason(reason))
        if key in self._skip_keys:
            return
        self._skip_keys.add(key)
        self.skips.append({"nodeid": nodeid, "reason": reason, "stage": stage})

    def add_warning(self, warning_message: Any, nodeid: str | None) -> None:
        self.warnings.append(
            {
                "nodeid": str(nodeid or ""),
                "message": str(warning_message.message),
                "category": warning_message.category.__name__,
                "filename": str(warning_message.filename or ""),
                "lineno": int(warning_message.lineno or 0),
            }
        )

    def finish(self) -> dict[str, Any]:
        report = evaluate_policy(
            skips=self.skips,
            warnings=self.warnings,
            repo_root=self.repo_root,
        )
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        self.report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return report


_ACTIVE_COLLECTOR: _PolicyCollector | None = None


def pytest_addoption(parser: Any) -> None:
    parser.addoption(
        "--memory-os-policy-report",
        action="store",
        default="",
        help="Write classified Memory-OS skip/warning policy JSON to this path.",
    )


def pytest_configure(config: Any) -> None:
    global _ACTIVE_COLLECTOR
    report_path = str(config.getoption("--memory-os-policy-report") or "").strip()
    _ACTIVE_COLLECTOR = (
        _PolicyCollector(report_path=Path(report_path).resolve(), repo_root=Path(config.rootpath).resolve())
        if report_path
        else None
    )


def pytest_collectreport(report: Any) -> None:
    if _ACTIVE_COLLECTOR is not None and report.skipped:
        _ACTIVE_COLLECTOR.add_skip(report, stage="collect")


def pytest_runtest_logreport(report: Any) -> None:
    if _ACTIVE_COLLECTOR is not None and report.skipped:
        _ACTIVE_COLLECTOR.add_skip(report, stage=str(report.when))


def pytest_warning_recorded(
    warning_message: Any,
    when: str,
    nodeid: str | None,
    location: tuple[str, int, str] | None,
) -> None:
    del when, location
    if _ACTIVE_COLLECTOR is not None:
        _ACTIVE_COLLECTOR.add_warning(warning_message, nodeid)


def pytest_sessionfinish(session: Any, exitstatus: int) -> None:
    del exitstatus
    if _ACTIVE_COLLECTOR is None:
        return
    report = _ACTIVE_COLLECTOR.finish()
    if report["status"] != "pass" and session.exitstatus == pytest.ExitCode.OK:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
