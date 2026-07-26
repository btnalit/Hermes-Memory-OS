"""Tests for shared natural-row detection."""

import pytest
from plugins.memory.memory_os.natural_row import (
    is_natural,
    is_manual,
    is_legacy_unmarked,
    classify_row,
    natural_rows,
    manual_rows,
    legacy_rows,
    latest_natural_row,
    natural_row_date_counts,
    has_natural_row_for_date,
    natural_row_count,
    latest_natural_row_date,
)


class TestIsNatural:
    def test_trigger_class_natural_cron(self):
        assert is_natural({"trigger_class": "natural_cron"}) is True

    def test_trigger_class_cron(self):
        assert is_natural({"trigger_class": "cron"}) is True

    def test_provenance_natural_cron(self):
        assert is_natural({"provenance": "natural_cron"}) is True

    def test_natural_production(self):
        assert is_natural({"natural_production": True, "traffic_class": "production"}) is True

    def test_traffic_not_production(self):
        assert is_natural({"natural_production": True, "traffic_class": "test"}) is False

    def test_manual_is_not_natural(self):
        assert is_natural({"trigger_class": "manual"}) is False

    def test_empty_is_not_natural(self):
        assert is_natural({}) is False

    def test_unknown_trigger(self):
        assert is_natural({"trigger_class": "unknown"}) is False


class TestIsManual:
    def test_manual_trigger(self):
        assert is_manual({"trigger_class": "manual"}) is True

    def test_natural_not_manual(self):
        assert is_manual({"trigger_class": "natural_cron"}) is False


class TestIsLegacyUnmarked:
    def test_empty_trigger(self):
        assert is_legacy_unmarked({}) is True

    def test_unknown_trigger(self):
        assert is_legacy_unmarked({"trigger_class": "unknown"}) is True

    def test_natural_not_legacy(self):
        assert is_legacy_unmarked({"trigger_class": "natural_cron"}) is False

    def test_manual_not_legacy(self):
        assert is_legacy_unmarked({"trigger_class": "manual"}) is False


class TestClassifyRow:
    def test_natural(self):
        assert classify_row({"trigger_class": "natural_cron"}) == "natural_cron"

    def test_manual(self):
        assert classify_row({"trigger_class": "manual"}) == "manual"

    def test_legacy(self):
        assert classify_row({}) == "legacy_unmarked"


class TestFilterHelpers:
    def test_natural_rows(self):
        rows = [
            {"trigger_class": "natural_cron", "id": "1"},
            {"trigger_class": "manual", "id": "2"},
            {"trigger_class": "natural_cron", "id": "3"},
        ]
        result = natural_rows(rows)
        assert len(result) == 2
        assert result[0]["id"] == "1"

    def test_manual_rows(self):
        rows = [
            {"trigger_class": "natural_cron", "id": "1"},
            {"trigger_class": "manual", "id": "2"},
        ]
        result = manual_rows(rows)
        assert len(result) == 1
        assert result[0]["id"] == "2"

    def test_legacy_rows(self):
        rows = [
            {"trigger_class": "natural_cron", "id": "1"},
            {"id": "2"},
        ]
        result = legacy_rows(rows)
        assert len(result) == 1
        assert result[0]["id"] == "2"


class TestLatestNaturalRow:
    def test_returns_latest(self):
        rows = [
            {"trigger_class": "natural_cron", "created_at": "2026-07-20T12:00:00Z"},
            {"trigger_class": "natural_cron", "created_at": "2026-07-22T12:00:00Z"},
            {"trigger_class": "natural_cron", "created_at": "2026-07-21T12:00:00Z"},
        ]
        latest = latest_natural_row(rows)
        assert latest is not None
        assert latest["created_at"] == "2026-07-22T12:00:00Z"

    def test_no_natural_rows(self):
        assert latest_natural_row([]) is None

    def test_ignores_non_natural(self):
        rows = [{"trigger_class": "manual", "created_at": "2026-07-22T12:00:00Z"}]
        assert latest_natural_row(rows) is None


class TestDateCounts:
    def test_date_counts(self):
        rows = [
            {"trigger_class": "natural_cron", "created_at": "2026-07-20T12:00:00Z"},
            {"trigger_class": "natural_cron", "created_at": "2026-07-20T14:00:00Z"},
            {"trigger_class": "natural_cron", "created_at": "2026-07-22T12:00:00Z"},
        ]
        counts = natural_row_date_counts(rows)
        assert counts["2026-07-20"] == 2
        assert counts["2026-07-22"] == 1

    def test_has_natural_row_for_date(self):
        rows = [
            {"trigger_class": "natural_cron", "created_at": "2026-07-22T12:00:00Z"},
        ]
        assert has_natural_row_for_date(rows, "2026-07-22") is True
        assert has_natural_row_for_date(rows, "2026-07-21") is False

    def test_natural_row_count(self):
        rows = [
            {"trigger_class": "natural_cron", "id": "1"},
            {"trigger_class": "manual", "id": "2"},
            {"trigger_class": "natural_cron", "id": "3"},
        ]
        assert natural_row_count(rows) == 2

    def test_latest_natural_row_date(self):
        rows = [
            {"trigger_class": "natural_cron", "created_at": "2026-07-22T12:00:00Z"},
        ]
        assert latest_natural_row_date(rows) == "2026-07-22"
        assert latest_natural_row_date([]) == ""