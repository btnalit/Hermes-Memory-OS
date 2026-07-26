"""Tests for natural evidence module."""

import pytest
from datetime import datetime, timezone, timedelta
from plugins.memory.memory_os.natural_evidence import (
    NaturalEvidenceConfig,
    ObservationWindow,
    TriggerProvenance,
    ObservationStatus,
    classify_trigger_provenance,
    record_observation,
    is_promotion_allowed,
    reset_window,
    build_gate_report,
)


class TestClassifyTriggerProvenance:
    def test_natural_cron_trigger(self):
        row = {"trigger": "natural_cron"}
        assert classify_trigger_provenance(row) == TriggerProvenance.NATURAL_CRON

    def test_manual_trigger(self):
        row = {"trigger": "manual"}
        assert classify_trigger_provenance(row) == TriggerProvenance.MANUAL

    def test_legacy_unmarked(self):
        row = {"trigger": "unknown"}
        assert classify_trigger_provenance(row) == TriggerProvenance.LEGACY_UNMARKED

    def test_empty_trigger(self):
        row = {}
        assert classify_trigger_provenance(row) == TriggerProvenance.LEGACY_UNMARKED

    def test_provenance_field(self):
        row = {"provenance": "natural_cron"}
        assert classify_trigger_provenance(row) == TriggerProvenance.NATURAL_CRON

    def test_custom_markers(self):
        row = {"trigger": "scheduled"}
        markers = {"scheduled", "cron"}
        assert classify_trigger_provenance(row, natural_cron_markers=markers) == TriggerProvenance.NATURAL_CRON


class TestRecordObservation:
    def test_first_observation(self):
        window = ObservationWindow(key="test")
        now = datetime(2026, 7, 22, 12, 0, 0, tzinfo=timezone.utc)
        updated = record_observation(
            window, {"trigger": "natural_cron"}, now=now,
        )
        assert updated.start_at == now.isoformat()
        assert updated.natural_cycle_count == 1
        assert not updated.is_contaminated

    def test_manual_contamination(self):
        cfg = NaturalEvidenceConfig(max_manual_credit_ratio=0.0)
        window = ObservationWindow(key="test")
        updated = record_observation(
            window, {"trigger": "manual"}, config=cfg,
        )
        assert updated.is_contaminated
        assert updated.contamination_reason == "manual_event"

    def test_legacy_contamination(self):
        cfg = NaturalEvidenceConfig(max_legacy_credit_ratio=0.0)
        window = ObservationWindow(key="test")
        updated = record_observation(
            window, {"trigger": "unknown"}, config=cfg,
        )
        assert updated.is_contaminated
        assert updated.contamination_reason == "legacy_unmarked_event"

    def test_multiple_observations(self):
        window = ObservationWindow(key="test")
        now = datetime(2026, 7, 22, 12, 0, 0, tzinfo=timezone.utc)
        for _ in range(5):
            window = record_observation(
                window, {"trigger": "natural_cron"}, now=now,
            )
        assert window.natural_cycle_count == 5


class TestIsPromotionAllowed:
    def test_not_allowed_insufficient(self):
        window = ObservationWindow(key="test", status="observing")
        assert not is_promotion_allowed(window)

    def test_not_allowed_contaminated(self):
        window = ObservationWindow(
            key="test", status="observing", is_contaminated=True,
        )
        assert not is_promotion_allowed(window)

    def test_allowed(self):
        window = ObservationWindow(
            key="test", status="sufficient", natural_cycle_count=30,
            start_at="2026-01-01T00:00:00Z",
        )
        cfg = NaturalEvidenceConfig(
            min_observation_days=1,
            min_natural_cycle_count=7,
        )
        assert is_promotion_allowed(window, cfg)


class TestResetWindow:
    def test_reset_clears_state(self):
        window = ObservationWindow(
            key="test", start_at="2026-01-01T00:00:00Z",
            natural_cycle_count=30, is_contaminated=True,
            contamination_reason="manual_event",
        )
        reset = reset_window(window, reason="test")
        assert reset.natural_cycle_count == 0
        assert not reset.is_contaminated
        assert reset.start_at == ""


class TestBuildGateReport:
    def test_report_structure(self):
        window = ObservationWindow(
            key="test", status="observing", natural_cycle_count=5,
        )
        cfg = NaturalEvidenceConfig(min_natural_cycle_count=7)
        report = build_gate_report(window, cfg)
        assert report["schema_version"] is not None
        assert report["key"] == "test"
        assert report["status"] == "observing"
        assert report["promotion_allowed"] is False