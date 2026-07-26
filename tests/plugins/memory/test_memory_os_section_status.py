"""Tests for SectionStatus typed phase API."""

import pytest
from plugins.memory.memory_os.section_status import (
    CollectedSnapshot,
    ClassifiedSnapshot,
    FinalMonitorSnapshot,
    SectionStatus,
    build_collected_snapshot,
    classify_snapshot,
    finalize_snapshot,
    run_pipeline,
)


class TestCollectedSnapshot:
    def test_collected(self):
        snap = CollectedSnapshot(section_key="test", status=SectionStatus.COLLECTED, count=5)
        assert snap.is_collected()
        assert not snap.is_unavailable()
        assert snap.validate() == []

    def test_unavailable_without_error(self):
        snap = CollectedSnapshot(section_key="test", status=SectionStatus.UNAVAILABLE)
        assert snap.is_unavailable()
        errors = snap.validate()
        assert len(errors) == 1
        assert "unavailable without error_code" in errors[0]

    def test_unavailable_with_error(self):
        snap = CollectedSnapshot(section_key="test", status=SectionStatus.UNAVAILABLE, error_code="test_error")
        assert snap.validate() == []

    def test_negative_count(self):
        snap = CollectedSnapshot(section_key="test", status=SectionStatus.COLLECTED, count=-1)
        errors = snap.validate()
        assert len(errors) == 1
        assert "negative count" in errors[0]


class TestClassifiedSnapshot:
    def test_classified(self):
        snap = ClassifiedSnapshot(section_key="test", status=SectionStatus.COLLECTED, pass_count=5, fail_count=1)
        assert snap.is_collected()
        assert snap.total_classified() == 6

    def test_collected_count_exceeds(self):
        collected = CollectedSnapshot(section_key="test", status=SectionStatus.COLLECTED, count=3)
        snap = ClassifiedSnapshot(section_key="test", status=SectionStatus.COLLECTED, pass_count=5)
        errors = snap.validate(collected)
        assert len(errors) == 1
        assert "classified count 5 > collected count 3" in errors[0]


class TestBuildCollectedSnapshot:
    def test_collector_success(self):
        snap = build_collected_snapshot("test", lambda: {"count": 3, "items": [{"id": "1"}]})
        assert snap.is_collected()
        assert snap.count == 3

    def test_collector_raises(self):
        def failing():
            raise ValueError("test error")
        snap = build_collected_snapshot("test", failing)
        assert snap.is_unavailable()
        assert snap.error_code == "collector_failed"

    def test_invalid_count_type(self):
        snap = build_collected_snapshot("test", lambda: {"count": "not_int"})
        assert snap.is_unavailable()
        assert snap.error_code == "invalid_count_type"


class TestPipeline:
    def test_full_pipeline(self):
        collected, classified, final = run_pipeline(
            "test",
            collector=lambda: {"count": 3, "items": [{"id": "1"}]},
            classifier=lambda c: {"pass_count": 2, "fail_count": 1},
            finalizer=lambda c: {"final_classification": "pass", "summary": "all good"},
        )
        assert collected.is_collected()
        assert classified.is_collected()
        assert classified.pass_count == 2
        assert final.final_classification == "pass"

    def test_collector_failure_propagates(self):
        collected, classified, final = run_pipeline(
            "test",
            collector=lambda: (_ for _ in ()).throw(ValueError("fail")),
            classifier=lambda c: {},
            finalizer=lambda c: {},
        )
        assert collected.is_unavailable()
        assert classified.is_unavailable()
        assert final.is_unavailable()