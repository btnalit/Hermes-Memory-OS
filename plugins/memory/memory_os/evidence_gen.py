"""
Stable evidence auto-generation for Memory-OS.

Automatically generates test deltas, skip reasons, warning classifications,
static gate reports, and staged diff digests.  The generator is read-only:
it never modifies canonical memory, Owner state, or production ledgers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EVIDENCE_GEN_SCHEMA_VERSION = "memory-os.evidence_gen.v1"


@dataclass
class DeltaReport:
    """A structured delta between two test runs."""

    before_total: int = 0
    after_total: int = 0
    delta: int = 0
    new_passed: list[str] = field(default_factory=list)
    new_failed: list[str] = field(default_factory=list)
    new_skipped: list[str] = field(default_factory=list)
    resolved_failures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": EVIDENCE_GEN_SCHEMA_VERSION,
            "before_total": self.before_total,
            "after_total": self.after_total,
            "delta": self.delta,
            "new_passed": self.new_passed[:10],
            "new_failed": self.new_failed[:10],
            "new_skipped": self.new_skipped[:10],
            "resolved_failures": self.resolved_failures[:10],
        }


@dataclass
class SkipReasonReport:
    """Structured report of skip reasons across a test run."""

    total_skips: int = 0
    skip_reasons: dict[str, int] = field(default_factory=dict)
    unknown_skips: list[str] = field(default_factory=list)
    known_skip_count: int = 0
    unknown_skip_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": EVIDENCE_GEN_SCHEMA_VERSION,
            "total_skips": self.total_skips,
            "skip_reasons": self.skip_reasons,
            "known_skip_count": self.known_skip_count,
            "unknown_skip_count": self.unknown_skip_count,
        }


@dataclass
class WarningClassificationReport:
    """Structured report of warning classifications."""

    total_warnings: int = 0
    warning_categories: dict[str, int] = field(default_factory=dict)
    project_warnings: list[str] = field(default_factory=list)
    dependency_warnings: list[str] = field(default_factory=list)
    unknown_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": EVIDENCE_GEN_SCHEMA_VERSION,
            "total_warnings": self.total_warnings,
            "warning_categories": self.warning_categories,
            "project_warning_count": len(self.project_warnings),
            "dependency_warning_count": len(self.dependency_warnings),
            "unknown_warning_count": len(self.unknown_warnings),
        }


@dataclass
class StagedDiffDigest:
    """Structured digest of a staged diff."""

    commit_sha: str = ""
    files_changed: int = 0
    insertions: int = 0
    deletions: int = 0
    new_files: list[str] = field(default_factory=list)
    modified_files: list[str] = field(default_factory=list)
    deleted_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": EVIDENCE_GEN_SCHEMA_VERSION,
            "commit_sha": self.commit_sha,
            "files_changed": self.files_changed,
            "insertions": self.insertions,
            "deletions": self.deletions,
            "new_files": self.new_files[:20],
            "modified_files": self.modified_files[:20],
        }


def build_test_delta(
    before: dict[str, Any],
    after: dict[str, Any],
) -> DeltaReport:
    """Build a structured delta between two test run results."""
    delta = DeltaReport(
        before_total=before.get("total", 0),
        after_total=after.get("total", 0),
    )
    delta.delta = delta.after_total - delta.before_total

    before_failed = set(before.get("failed", []))
    after_failed = set(after.get("failed", []))
    after_passed = set(after.get("passed", []))

    delta.resolved_failures = list(before_failed - after_failed)
    delta.new_failed = list(after_failed - before_failed)
    delta.new_passed = list(after_passed - set(before.get("passed", [])))

    return delta


def build_skip_reason_report(
    skips: list[dict[str, Any]],
    known_reasons: set[str],
) -> SkipReasonReport:
    """Build a structured report of skip reasons."""
    report = SkipReasonReport()
    for skip in skips:
        reason = str(skip.get("reason", "unknown"))
        report.total_skips += 1
        report.skip_reasons[reason] = report.skip_reasons.get(reason, 0) + 1
        if reason in known_reasons:
            report.known_skip_count += 1
        else:
            report.unknown_skip_count += 1
            report.unknown_skips.append(reason)
    return report


def build_staged_diff_digest(
    git_log_output: str,
    *,
    commit_sha: str = "",
) -> StagedDiffDigest:
    """Build a structured digest from git log output."""
    digest = StagedDiffDigest(commit_sha=commit_sha)
    for line in git_log_output.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if line.startswith("create mode "):
            # create mode 100644 new_file.py
            digest.new_files.append(parts[-1])
            digest.files_changed += 1
        elif line.startswith("delete mode "):
            # delete mode 100644 old_file.py
            digest.deleted_files.append(parts[-1])
            digest.files_changed += 1
        elif " | " in line:
            # modified_file.py | 5 +++++
            before_pipe, after_pipe = line.split(" | ", 1)
            filename = before_pipe.strip()
            stat_parts = after_pipe.split()
            digest.modified_files.append(filename)
            digest.files_changed += 1
            if stat_parts:
                try:
                    count = int(stat_parts[0])
                except ValueError:
                    count = 0
                if len(stat_parts) > 1:
                    changes = stat_parts[1]
                    digest.insertions += changes.count("+")
                    digest.deletions += changes.count("-")
                else:
                    digest.insertions += count
    return digest