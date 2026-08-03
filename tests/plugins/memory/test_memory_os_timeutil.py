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
        # This previously asserted `dt.tzinfo is None`, pinning a defect: the
        # function's docstring promises "a timezone-aware datetime in UTC", and
        # every inlined copy it exists to replace coerces a naive value to UTC.
        # Returning naive made the helper unusable -- subtracting it from an
        # aware datetime raises TypeError. Nobody hit it because nothing in
        # production ever called this module, so its own test simply encoded
        # its own assumption. allow_naive means "accept input carrying no
        # offset", not "hand back something that cannot be used".
        dt = parse_utc("2026-07-22T12:00:00", allow_naive=True)
        assert dt is not None
        assert dt.tzinfo == timezone.utc

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

# ── allow_naive must still return a UTC-aware datetime ────────────────


def _inlined_parse(value):
    """The shape this helper exists to replace, copied verbatim from the
    call sites that have been running it in production for months."""
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def test_allow_naive_returns_utc_aware_not_naive():
    """Counterfactual: without the fix this returns a NAIVE datetime, and the
    first caller that subtracts it from an aware datetime raises
    TypeError: can't subtract offset-naive and offset-aware datetimes.

    The docstring promises "a timezone-aware datetime in UTC"; allow_naive
    means "accept input carrying no offset", not "return something unusable".
    """
    parsed = parse_utc("2026-08-03T04:05:06", allow_naive=True)

    assert parsed is not None
    assert parsed.tzinfo == timezone.utc
    # The arithmetic that would have blown up.
    assert (datetime(2026, 8, 3, 5, 0, 0, tzinfo=timezone.utc) - parsed).total_seconds() > 0


@pytest.mark.parametrize(
    "value",
    [
        "2026-08-03T04:05:06Z",
        "2026-08-03T04:05:06+08:00",
        "2026-08-03T04:05:06",
        "2026-08-03T04:05:06.123456Z",
        "2026-08-03 04:05:06",
        "",
    ],
)
def test_parse_utc_matches_the_inlined_implementation_it_replaces(value):
    """Differential test: migrating a call site must not change its result."""
    assert parse_utc(value, allow_naive=True) == _inlined_parse(value)


@pytest.mark.parametrize("value", ["2026-08-03", "2026-08-03T04:05"])
def test_parse_utc_is_deliberately_stricter_than_fromisoformat(value):
    """Standing hazard, pinned on purpose.

    parse_utc rejects date-only and second-less timestamps; the inlined
    implementation accepts both. Any call site that currently accepts these
    formats will SILENTLY START DROPPING RECORDS if migrated. This test exists
    so that divergence is a documented contract rather than a surprise.
    """
    assert _inlined_parse(value) is not None
    assert parse_utc(value, allow_naive=True) is None
