"""Tests for Monitor performance budget and cache testing."""

import pytest
import time
from unittest.mock import MagicMock
from plugins.memory.memory_os.monitor_perf import (
    track_runtime,
    RuntimeBudget,
    verify_cache_parity,
    CacheParityResult,
)


class TestTrackRuntime:
    def test_within_budget(self):
        with track_runtime("test", 5.0) as budget:
            pass
        assert not budget.exceeded
        assert budget.elapsed < 5.0

    def test_exceeds_budget(self):
        with track_runtime("test", 0.01) as budget:
            time.sleep(0.02)
        assert budget.exceeded
        assert budget.elapsed >= 0.01

    def test_remaining(self):
        with track_runtime("test", 5.0) as budget:
            pass
        assert budget.remaining > 0


class TestVerifyCacheParity:
    def test_cache_and_live_match(self):
        result = verify_cache_parity(
            "test",
            cache_reader=lambda: 42,
            live_reader=lambda: 42,
        )
        assert result.equivalent is True
        assert result.cache_hit is True

    def test_cache_and_live_differ(self):
        result = verify_cache_parity(
            "test",
            cache_reader=lambda: 42,
            live_reader=lambda: 43,
        )
        assert result.equivalent is False

    def test_cache_hit_live_raises(self):
        result = verify_cache_parity(
            "test",
            cache_reader=lambda: 42,
            live_reader=lambda: (_ for _ in ()).throw(ValueError("fail")),
        )
        assert result.equivalent is True  # cache is valid fallback
        assert result.live_raised is True

    def test_cache_miss(self):
        result = verify_cache_parity(
            "test",
            cache_reader=lambda: None,
            live_reader=lambda: 42,
            allow_cache_zero=False,
        )
        assert result.cache_hit is False
        assert result.equivalent is False

    def test_cache_zero_allowed(self):
        result = verify_cache_parity(
            "test",
            cache_reader=lambda: 0,
            live_reader=lambda: 0,
            allow_cache_zero=True,
        )
        assert result.equivalent is True

    def test_cache_reader_raises(self):
        result = verify_cache_parity(
            "test",
            cache_reader=lambda: (_ for _ in ()).throw(ValueError("cache fail")),
            live_reader=lambda: 42,
        )
        assert "cache_read_failed" in result.error