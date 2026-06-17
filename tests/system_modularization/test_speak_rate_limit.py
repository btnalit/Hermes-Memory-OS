"""Tests for speak_rate_limit — deterministic rolling-window rate limiter."""
from datetime import datetime, timedelta, timezone

from plugins.modules.expression.speak_rate_limit import under_speak_limit


def _delivery(ts: str, decision: str = "delivered") -> dict:
    return {"ts": ts, "decision": decision}


class TestUnderSpeakLimit:
    def test_V1_1_five_delivered_in_window_blocks_sixth(self):
        """V1.1: 窗口内已5条 delivered → under_speak_limit False (第6条不发)"""
        now = datetime(2026, 6, 17, 12, 0, 0, tzinfo=timezone.utc)
        deliveries = [
            _delivery("2026-06-17T11:55:00+00:00"),
            _delivery("2026-06-17T11:56:00+00:00"),
            _delivery("2026-06-17T11:57:00+00:00"),
            _delivery("2026-06-17T11:58:00+00:00"),
            _delivery("2026-06-17T11:59:00+00:00"),
        ]
        assert under_speak_limit(deliveries, now=now) is False

    def test_V1_2_four_delivered_allows_fifth(self):
        """V1.2: 窗口内4条 → True (第5条放行)"""
        now = datetime(2026, 6, 17, 12, 0, 0, tzinfo=timezone.utc)
        deliveries = [
            _delivery("2026-06-17T11:55:00+00:00"),
            _delivery("2026-06-17T11:56:00+00:00"),
            _delivery("2026-06-17T11:57:00+00:00"),
            _delivery("2026-06-17T11:58:00+00:00"),
        ]
        assert under_speak_limit(deliveries, now=now) is True

    def test_V1_3_expired_delivery_not_counted(self):
        """V1.3: 5条中有过期(>60min)的 → 过期不计, 放行"""
        now = datetime(2026, 6, 17, 12, 0, 0, tzinfo=timezone.utc)
        deliveries = [
            _delivery("2026-06-17T10:50:00+00:00"),  # expired (>60 min ago)
            _delivery("2026-06-17T11:55:00+00:00"),
            _delivery("2026-06-17T11:56:00+00:00"),
            _delivery("2026-06-17T11:57:00+00:00"),
            _delivery("2026-06-17T11:58:00+00:00"),
        ]
        # Only 4 are in window (the 10:50 one is expired)
        assert under_speak_limit(deliveries, now=now) is True

    def test_non_delivered_decisions_not_counted(self):
        """Only decision='delivered' counts toward the limit."""
        now = datetime(2026, 6, 17, 12, 0, 0, tzinfo=timezone.utc)
        deliveries = [
            _delivery("2026-06-17T11:55:00+00:00", "delivered"),
            _delivery("2026-06-17T11:56:00+00:00", "rate_limited"),
            _delivery("2026-06-17T11:57:00+00:00", "send_blocked"),
            _delivery("2026-06-17T11:58:00+00:00", "no_send"),
            _delivery("2026-06-17T11:59:00+00:00", "delivered"),
        ]
        # Only 2 delivered → well under limit
        assert under_speak_limit(deliveries, now=now) is True

    def test_default_now_is_utc(self):
        """Calling without now= uses current UTC time."""
        assert under_speak_limit([]) is True

    def test_empty_deliveries_always_under_limit(self):
        """No deliveries → always under limit."""
        assert under_speak_limit([]) is True

    def test_missing_ts_field_treated_as_expired(self):
        """Deliveries with missing ts field are treated as ancient (don't count)."""
        now = datetime(2026, 6, 17, 12, 0, 0, tzinfo=timezone.utc)
        deliveries = [
            {"decision": "delivered"},  # no ts
            {"decision": "delivered"},  # no ts
            {"decision": "delivered"},  # no ts
            {"decision": "delivered"},  # no ts
            {"decision": "delivered"},  # no ts
            {"decision": "delivered"},  # no ts
        ]
        assert under_speak_limit(deliveries, now=now) is True

    def test_boundary_exactly_one_hour_ago_not_counted(self):
        """Delivery exactly 60 min ago is outside the window (strict > cutoff)."""
        now = datetime(2026, 6, 17, 12, 0, 0, tzinfo=timezone.utc)
        deliveries = [
            _delivery("2026-06-17T11:00:00+00:00"),  # exactly 60 min ago
            _delivery("2026-06-17T11:30:00+00:00"),
            _delivery("2026-06-17T11:40:00+00:00"),
            _delivery("2026-06-17T11:50:00+00:00"),
            _delivery("2026-06-17T11:55:00+00:00"),
        ]
        assert under_speak_limit(deliveries, now=now) is True
