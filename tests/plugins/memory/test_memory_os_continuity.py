"""Tests for continuity freshness grading and disclosure."""

import pytest
from datetime import datetime, timedelta, timezone
from plugins.memory.memory_os.continuity import (
    CONTINUITY_FRESHNESS_SCHEMA_VERSION,
    STALE_TASK_REVISION_REASON_CODE,
    ContinuityObject,
    ContinuityState,
    FreshnessGrade,
    build_continuity_findings,
    build_continuity_freshness_record,
    build_continuity_recall_plan,
    build_current_task_continuity_object,
    continuity_freshness_record_is_reportable,
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

    def test_absent_current_task_is_not_stale(self):
        """Absence is UNKNOWN, not staleness.

        This assertion was deliberately inverted.  It previously read
        ``current_task_is_stale() is True  # None is stale`` — it pinned the
        bug, not the contract, exactly as ``test_naive_allowed`` did for
        ``parse_utc`` in batch B.  A helper that never had a production caller
        also never had its assumptions checked by anything but its own tests.
        Fed to a disclosure surface, the old behaviour told every owner opening
        a fresh session that their task information may be out of date.
        """
        state = ContinuityState()
        assert state.current_task_grade() == FreshnessGrade.UNKNOWN
        assert state.current_task_is_stale() is False

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


def _anchor_record(*, created_at: str, revision: int = 3) -> dict:
    """A ``read_effective_current_task`` projection, as task_state returns it."""
    return {
        "schema_version": "memory-os.active_task_anchor.v0",
        "record_id": "ata_0123456789abcdef",
        "created_at": created_at,
        "profile": "memoryos-test",
        "session_id": "sess-1",
        "anchor": "OWNER TASK BODY MUST NOT BE COPIED",
        "status": "active",
        "revision": revision,
        "source_at": created_at,
    }


class TestNaiveTimestampGrading:
    """Trap 1: a naive stamp must not grade UNKNOWN forever.

    ``age_seconds`` calls ``parse_utc``; with the default ``allow_naive=False``
    a naive input returns None, None grades UNKNOWN, and UNKNOWN never grades
    stale — the whole lane would spin silently on exactly the records it exists
    to grade.  ``task_state._parse_timestamp``, which owns this same record,
    coerces naive to UTC, so strict parsing here would also disagree with the
    producing module on one input.
    """

    def test_naive_timestamp_past_stale_after_grades_stale(self):
        now = datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc)
        naive = "2026-08-03T10:00:00"  # 2h old, no offset
        obj = ContinuityObject(
            kind="current_task", object_id="task-1",
            updated_at=naive, stale_after_seconds=3600,
        )
        assert obj.age_seconds(now) == pytest.approx(7200)
        assert obj.freshness_grade(now) == FreshnessGrade.STALE

    def test_space_separated_naive_timestamp_grades(self):
        now = datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc)
        obj = ContinuityObject(
            kind="current_task", object_id="task-1",
            updated_at="2026-08-03 10:00:00", stale_after_seconds=3600,
        )
        assert obj.freshness_grade(now) == FreshnessGrade.STALE

    def test_date_only_timestamp_is_unknown_and_counted(self):
        """The standing hazard from batch B stays visible rather than silent.

        ``parse_utc`` deliberately rejects date-only stamps.  Such a record
        grades UNKNOWN — which must never be reported as "out of date" — but it
        still makes the diagnostic record reportable, so a mapping that starts
        producing ungradeable timestamps shows up instead of vanishing.
        """
        now = datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc)
        state = ContinuityState(
            current_task=build_current_task_continuity_object(
                _anchor_record(created_at="2026-08-01")
            )
        )
        assert state.current_task_grade(now) == FreshnessGrade.UNKNOWN
        assert state.current_task_is_stale(now) is False
        record = build_continuity_freshness_record(state, now=now)
        assert record["unknown_grade_count"] == 1
        assert record["stale_task_count"] == 0
        assert continuity_freshness_record_is_reportable(record) is True


class TestCurrentTaskMapping:
    def test_maps_revision_and_source_at(self):
        obj = build_current_task_continuity_object(
            _anchor_record(created_at="2026-08-03T10:00:00Z", revision=7)
        )
        assert obj is not None
        assert obj.kind == "current_task"
        assert obj.object_id == "ata_0123456789abcdef"
        assert obj.revision == 7
        assert obj.updated_at == "2026-08-03T10:00:00Z"
        assert obj.stale_after_seconds == default_stale_after("current_task")
        assert obj.metadata["session_id"] == "sess-1"

    def test_never_copies_anchor_body(self):
        """The diagnostic ledger is a metadata-only surface."""
        obj = build_current_task_continuity_object(
            _anchor_record(created_at="2026-08-03T10:00:00Z")
        )
        assert obj is not None
        assert obj.summary == ""
        assert "OWNER TASK BODY MUST NOT BE COPIED" not in str(obj.to_dict())

    def test_absent_record_maps_to_none(self):
        assert build_current_task_continuity_object(None) is None
        assert build_current_task_continuity_object("not-a-dict") is None

    def test_non_integer_revision_does_not_raise(self):
        record = _anchor_record(created_at="2026-08-03T10:00:00Z")
        record["revision"] = "not-a-number"
        obj = build_current_task_continuity_object(record)
        assert obj is not None
        assert obj.revision == 0


class TestContinuityDisclosure:
    def test_stale_task_produces_finding(self):
        now = datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc)
        state = ContinuityState(
            current_task=build_current_task_continuity_object(
                _anchor_record(created_at="2026-08-03T10:00:00Z", revision=4)
            )
        )
        findings = build_continuity_findings(state, now=now)
        assert len(findings) == 1
        assert findings[0]["code"] == STALE_TASK_REVISION_REASON_CODE
        assert findings[0]["revision"] == 4
        assert findings[0]["age_seconds"] == 7200
        assert findings[0]["stale_after_seconds"] == 3600

    def test_aging_task_produces_no_finding(self):
        """AGING is a diagnostic grade, not an owner-facing claim."""
        now = datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc)
        state = ContinuityState(
            current_task=build_current_task_continuity_object(
                _anchor_record(created_at="2026-08-03T11:10:00Z")  # 50 min
            )
        )
        assert state.current_task_grade(now) == FreshnessGrade.AGING
        assert build_continuity_findings(state, now=now) == []

    def test_absent_task_produces_no_finding(self):
        now = datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc)
        assert build_continuity_findings(ContinuityState(), now=now) == []

    def test_record_pins_that_grading_filters_nothing(self):
        """``filters_applied``/``filtered_count`` are the machine-readable ruling.

        A future change that starts filtering cannot do so without this record
        contradicting itself.
        """
        now = datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc)
        state = ContinuityState(
            current_task=build_current_task_continuity_object(
                _anchor_record(created_at="2026-08-03T10:00:00Z")
            )
        )
        record = build_continuity_freshness_record(state, now=now, session_id="s9")
        assert record["schema_version"] == CONTINUITY_FRESHNESS_SCHEMA_VERSION
        assert record["mode"] == "disclose_only"
        assert record["filters_applied"] == []
        assert record["filtered_count"] == 0
        assert record["raw_body_included"] is False
        assert record["session_id"] == "s9"
        assert record["graded_count"] == 1
        assert record["grade_counts"][FreshnessGrade.STALE] == 1
        assert record["current_task_present"] is True

    def test_all_fresh_pass_is_not_reportable(self):
        """Bounded volume: an all-fresh grading pass writes nothing."""
        now = datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc)
        state = ContinuityState(
            current_task=build_current_task_continuity_object(
                _anchor_record(created_at="2026-08-03T11:58:00Z")
            )
        )
        record = build_continuity_freshness_record(state, now=now)
        assert record["current_task_grade"] == FreshnessGrade.FRESH
        assert continuity_freshness_record_is_reportable(record) is False

    def test_empty_state_is_not_reportable(self):
        record = build_continuity_freshness_record(ContinuityState())
        assert record["graded_count"] == 0
        assert continuity_freshness_record_is_reportable(record) is False

    def test_malformed_record_is_not_reportable(self):
        assert continuity_freshness_record_is_reportable(None) is False
        assert continuity_freshness_record_is_reportable(
            {"unknown_grade_count": "x"}
        ) is False


class TestGapNoteConsumesContinuityFindings:
    """The link that turns Gap Note from a dead renderer into a live one.

    Gap Note recognises exactly two reason codes and, before this lane, no
    production code emitted either.  Batch D renders what this produces, so the
    handoff shape is pinned here rather than discovered later.
    """

    def test_recall_plan_is_gap_note_eligible(self):
        from plugins.memory.memory_os.gap_note import build_gap_note_candidate

        now = datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc)
        state = ContinuityState(
            current_task=build_current_task_continuity_object(
                _anchor_record(created_at="2026-08-03T10:00:00Z")
            )
        )
        plan = build_continuity_recall_plan(state, now=now)
        candidate = build_gap_note_candidate(plan)

        assert candidate.is_eligible() is True
        assert candidate.would_render is True
        assert candidate.stale_task_count == 1
        assert candidate.reason_codes == [STALE_TASK_REVISION_REASON_CODE]

    def test_fresh_plan_is_not_gap_note_eligible(self):
        from plugins.memory.memory_os.gap_note import build_gap_note_candidate

        now = datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc)
        state = ContinuityState(
            current_task=build_current_task_continuity_object(
                _anchor_record(created_at="2026-08-03T11:58:00Z")
            )
        )
        candidate = build_gap_note_candidate(build_continuity_recall_plan(state, now=now))
        assert candidate.is_eligible() is False
        assert candidate.would_render is False