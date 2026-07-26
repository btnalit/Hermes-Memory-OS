"""Tests for continuity freshness and stale degradation."""

import pytest
from datetime import datetime, timedelta, timezone
from plugins.memory.memory_os.continuity import (
    ContinuityObject,
    ContinuityState,
    FreshnessGrade,
    default_stale_after,
)


class TestContinuityObject:
    def test_fresh(self):
        obj = ContinuityObject(
            kind="current_task", object_id="task-1",
            updated_at=datetime.now(timezone.utc).isoformat(),
            stale_after_seconds=3600,
        )
        assert obj.freshness_grade() == FreshnessGrade.FRESH
        assert not obj.is_stale()

    def test_aging(self):
        now = datetime.now(timezone.utc)
        obj = ContinuityObject(
            kind="current_task", object_id="task-1",
            updated_at=(now - timedelta(seconds=3000)).isoformat(),
            stale_after_seconds=3600,
        )
        assert obj.freshness_grade() == FreshnessGrade.AGING
        assert not obj.is_stale()

    def test_stale(self):
        now = datetime.now(timezone.utc)
        obj = ContinuityObject(
            kind="current_task", object_id="task-1",
            updated_at=(now - timedelta(seconds=4000)).isoformat(),
            stale_after_seconds=3600,
        )
        assert obj.freshness_grade() == FreshnessGrade.STALE
        assert obj.is_stale()

    def test_unknown(self):
        obj = ContinuityObject(kind="current_task", object_id="task-1")
        assert obj.freshness_grade() == FreshnessGrade.UNKNOWN
        assert obj.is_stale() is False  # unknown is not stale

    def test_future_timestamp(self):
        now = datetime.now(timezone.utc)
        obj = ContinuityObject(
            kind="current_task", object_id="task-1",
            updated_at=(now + timedelta(hours=1)).isoformat(),
        )
        assert obj.freshness_grade() == FreshnessGrade.FRESH
        assert not obj.is_stale()


class TestContinuityState:
    def test_active_open_threads(self):
        now = datetime.now(timezone.utc)
        state = ContinuityState(
            open_threads=[
                ContinuityObject(kind="open_thread", object_id="t1",
                    updated_at=(now - timedelta(seconds=500)).isoformat(),
                    stale_after_seconds=3600),
                ContinuityObject(kind="open_thread", object_id="t2",
                    updated_at=(now - timedelta(seconds=5000)).isoformat(),
                    stale_after_seconds=3600),
            ]
        )
        assert len(state.active_open_threads(now)) == 1
        assert len(state.stale_open_threads(now)) == 1

    def test_stale_current_task(self):
        state = ContinuityState()
        assert state.current_task_is_stale() is True  # None is stale

    def test_fresh_current_task(self):
        now = datetime.now(timezone.utc)
        state = ContinuityState(
            current_task=ContinuityObject(
                kind="current_task", object_id="task-1",
                updated_at=(now - timedelta(seconds=300)).isoformat(),
            )
        )
        assert not state.current_task_is_stale(now)


class TestDefaultStaleAfter:
    def test_current_task(self):
        assert default_stale_after("current_task") == 3600

    def test_open_thread(self):
        assert default_stale_after("open_thread") == 7200

    def test_unknown_kind(self):
        assert default_stale_after("unknown") == 3600  # default