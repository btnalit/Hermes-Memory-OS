"""Tests for unified timeutil module."""

import pytest
from datetime import datetime, timezone, timedelta
from plugins.memory.memory_os.timeutil import (
    parse_utc,
    format_utc,
    format_utc_micro,
    now_utc,
    safe_compare,
    max_safe,
    min_safe,
    age_seconds,
    parse_timestamp,
    parse_dt,
)


class TestParseUtc:
    def test_utc_z_suffix(self):
        dt = parse_utc("2026-07-22T12:00:00Z")
        assert dt is not None
        assert dt.tzinfo == timezone.utc
        assert dt.year == 2026 and dt.month == 7 and dt.day == 22

    def test_utc_with_offset(self):
        dt = parse_utc("2026-07-22T12:00:00+08:00")
        assert dt is not None
        assert dt.tzinfo == timezone.utc
        assert dt.hour == 4  # 12:00 +08:00 = 04:00 UTC

    def test_naive_rejected(self):
        assert parse_utc("2026-07-22T12:00:00") is None

    def test_naive_allowed(self):
        dt = parse_utc("2026-07-22T12:00:00", allow_naive=True)
        assert dt is not None
        assert dt.tzinfo is None

    def test_empty_string(self):
        assert parse_utc("") is None
        assert parse_utc(None) is None

    def test_date_only(self):
        assert parse_utc("2026-07-22") is None

    def test_invalid_value(self):
        assert parse_utc("not-a-date") is None
        assert parse_utc("2026-13-01T00:00:00Z") is None  # invalid month

    def test_microsecond_handling(self):
        dt = parse_utc("2026-07-22T12:00:00.123456Z")
        assert dt is not None
        assert dt.microsecond == 123456

    def test_microsecond_padding(self):
        dt = parse_utc("2026-07-22T12:00:00.123Z")
        assert dt is not None
        assert dt.microsecond == 123000

    def test_space_separator(self):
        dt = parse_utc("2026-07-22 12:00:00Z")
        assert dt is not None
        assert dt.hour == 12


class TestFormatUtc:
    def test_format_utc(self):
        dt = datetime(2026, 7, 22, 12, 0, 0, tzinfo=timezone.utc)
        result = format_utc(dt)
        assert result.startswith("2026-07-22T12:00:00.")
        assert result.endswith("Z")

    def test_format_utc_none(self):
        assert format_utc(None) == ""

    def test_format_utc_micro(self):
        dt = datetime(2026, 7, 22, 12, 0, 0, 123456, tzinfo=timezone.utc)
        result = format_utc_micro(dt)
        assert "123456" in result

    def test_format_naive_assumed_utc(self):
        dt = datetime(2026, 7, 22, 12, 0, 0)
        result = format_utc(dt)
        assert result.endswith("Z")


class TestNowUtc:
    def test_now_utc_is_aware(self):
        dt = now_utc()
        assert dt.tzinfo == timezone.utc
        assert dt.year >= 2026


class TestSafeCompare:
    def test_compare_earlier(self):
        a = datetime(2026, 7, 22, 12, 0, 0, tzinfo=timezone.utc)
        b = datetime(2026, 7, 22, 13, 0, 0, tzinfo=timezone.utc)
        assert safe_compare(a, b) == -1

    def test_compare_equal(self):
        a = datetime(2026, 7, 22, 12, 0, 0, tzinfo=timezone.utc)
        b = datetime(2026, 7, 22, 12, 0, 0, tzinfo=timezone.utc)
        assert safe_compare(a, b) == 0

    def test_compare_later(self):
        a = datetime(2026, 7, 22, 13, 0, 0, tzinfo=timezone.utc)
        b = datetime(2026, 7, 22, 12, 0, 0, tzinfo=timezone.utc)
        assert safe_compare(a, b) == 1

    def test_none_handling(self):
        a = datetime(2026, 7, 22, 12, 0, 0, tzinfo=timezone.utc)
        assert safe_compare(None, a) == -1
        assert safe_compare(a, None) == 1
        assert safe_compare(None, None) == 0

    def test_different_timezones(self):
        a = datetime(2026, 7, 22, 12, 0, 0, tzinfo=timezone.utc)
        b = datetime(2026, 7, 22, 20, 0, 0, tzinfo=timezone(timedelta(hours=8)))
        assert safe_compare(a, b) == 0  # same instant


class TestMaxSafe:
    def test_max_safe(self):
        a = datetime(2026, 7, 22, 12, 0, 0, tzinfo=timezone.utc)
        b = datetime(2026, 7, 22, 13, 0, 0, tzinfo=timezone.utc)
        assert max_safe(a, b) == b

    def test_max_safe_none(self):
        a = datetime(2026, 7, 22, 12, 0, 0, tzinfo=timezone.utc)
        assert max_safe(None, a) == a
        assert max_safe(a, None) == a
        assert max_safe(None, None) is None


class TestAgeSeconds:
    def test_age_seconds(self):
        dt = datetime(2026, 7, 22, 12, 0, 0, tzinfo=timezone.utc)
        now = datetime(2026, 7, 22, 13, 0, 0, tzinfo=timezone.utc)
        age = age_seconds(dt, now=now)
        assert age == pytest.approx(3600, rel=0.01)

    def test_age_seconds_none(self):
        assert age_seconds(None) is None


class TestAliases:
    def test_parse_timestamp(self):
        assert parse_timestamp("2026-07-22T12:00:00Z") is not None

    def test_parse_dt(self):
        assert parse_dt("2026-07-22T12:00:00Z") is not None
        assert parse_dt("2026-07-22T12:00:00") is None  # naive rejected