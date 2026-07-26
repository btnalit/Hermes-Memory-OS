"""Tests for stable evidence auto-generation."""

import pytest
from plugins.memory.memory_os.evidence_gen import (
    build_test_delta,
    build_skip_reason_report,
    build_staged_diff_digest,
    DeltaReport,
    SkipReasonReport,
    StagedDiffDigest,
)


class TestBuildTestDelta:
    def test_no_change(self):
        before = {"total": 100, "passed": [], "failed": []}
        after = {"total": 100, "passed": [], "failed": []}
        delta = build_test_delta(before, after)
        assert delta.delta == 0
        assert delta.resolved_failures == []
        assert delta.new_failed == []

    def test_new_failures(self):
        before = {"total": 100, "passed": ["t1"], "failed": ["t2"]}
        after = {"total": 100, "passed": ["t1"], "failed": ["t2", "t3"]}
        delta = build_test_delta(before, after)
        assert delta.new_failed == ["t3"]

    def test_resolved_failures(self):
        before = {"total": 100, "passed": ["t1"], "failed": ["t2", "t3"]}
        after = {"total": 100, "passed": ["t1", "t2"], "failed": ["t3"]}
        delta = build_test_delta(before, after)
        assert delta.resolved_failures == ["t2"]


class TestBuildSkipReasonReport:
    def test_all_known(self):
        skips = [
            {"reason": "sentence-transformers not installed"},
            {"reason": "sentence-transformers not installed"},
        ]
        report = build_skip_reason_report(skips, {"sentence-transformers not installed"})
        assert report.total_skips == 2
        assert report.known_skip_count == 2
        assert report.unknown_skip_count == 0

    def test_unknown_skips(self):
        skips = [
            {"reason": "sentence-transformers not installed"},
            {"reason": "unknown reason"},
        ]
        report = build_skip_reason_report(skips, {"sentence-transformers not installed"})
        assert report.total_skips == 2
        assert report.known_skip_count == 1
        assert report.unknown_skip_count == 1
        assert "unknown reason" in report.unknown_skips


class TestBuildStagedDiffDigest:
    def test_parse_git_log(self):
        log = """create mode 100644 new_file.py
delete mode 100644 old_file.py
modified_file.py | 5 +++++
"""
        digest = build_staged_diff_digest(log)
        assert digest.files_changed == 3
        assert len(digest.new_files) == 1
        assert len(digest.deleted_files) == 1
        assert len(digest.modified_files) == 1
        assert digest.insertions == 5

    def test_empty_log(self):
        digest = build_staged_diff_digest("")
        assert digest.files_changed == 0