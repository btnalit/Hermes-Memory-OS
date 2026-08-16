"""Counterfactual tests for DEFECT 1: naive-datetime expiry handling in
knob_overrides.py.

Before the fix, ``_is_expired`` caught only ``ValueError``. A
timezone-naive ``expires_at`` (e.g. ``"2026-12-31T00:00:00"``) parses fine
via ``datetime.fromisoformat`` and then raises ``TypeError`` on comparison
against the aware ``now`` used throughout this store -- uncaught, that
propagates out of ``resolve_knob`` / ``resolve_knobs`` /
``list_active_overrides`` into every hot-path caller (verified: prefetch's
``_graph_layer_shadow_lines`` calls ``_resolve_knob(...)`` with no try
around it, and ``build_prefetch`` does not wrap that section).

Fixtures are built through the real producer (``register_override``)
wherever possible, per project convention. The one exception is the
genuinely-unparseable-garbage case: since part (b) of the fix makes
``register_override`` reject a value that does not parse at all, that
fixture must be hand-written directly into the JSONL store to simulate a
pre-existing / hand-edited legacy record register_override would now
refuse to create.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from plugins.memory.memory_os.knob_overrides import (
    _override_store_path,
    list_active_overrides,
    register_override,
    resolve_knob,
    resolve_knobs,
)


class TestNaiveExpiryIsExpiredComparison:
    """DEFECT 1(a): _is_expired must not raise TypeError on a naive expires_at."""

    def test_naive_future_expiry_resolves_override_value_without_raising(self, tmp_path):
        """Counterfactual: a naive (no-offset) future expires_at, registered
        through the real producer, must resolve deterministically instead of
        raising TypeError. Before the fix this raised
        'TypeError: can't compare offset-naive and offset-aware datetimes'
        out of resolve_knob -- the fail-open `except ValueError` never ran.
        """
        now = datetime.now(timezone.utc)
        naive_future = (now + timedelta(days=7)).replace(tzinfo=None).isoformat()
        assert "+" not in naive_future and "Z" not in naive_future  # sanity: truly naive

        register_override(
            "min_cluster_size", 3,
            prior=2, proposed_by="test", approved_via="test",
            expires_at=naive_future, _now=now, _store_root=tmp_path,
        )

        result = resolve_knob("min_cluster_size", default=2, _now=now, _store_root=tmp_path)
        assert result == 3

    def test_naive_past_expiry_treated_as_utc_and_returns_default(self, tmp_path):
        """A naive PAST expiry (interpreted as UTC per the fix's documented
        assumption) must be treated as expired -- default returned, no raise.
        """
        now = datetime.now(timezone.utc)
        naive_past = (now - timedelta(days=1)).replace(tzinfo=None).isoformat()

        register_override(
            "min_cluster_size", 3,
            prior=2, proposed_by="test", approved_via="test",
            expires_at=naive_past, _now=now - timedelta(days=2), _store_root=tmp_path,
        )

        result = resolve_knob("min_cluster_size", default=2, _now=now, _store_root=tmp_path)
        assert result == 2

    def test_naive_future_expiry_excluded_correctly_from_list_active_overrides(self, tmp_path):
        """list_active_overrides shares the same _is_expired call and must
        not raise either."""
        now = datetime.now(timezone.utc)
        naive_future = (now + timedelta(days=7)).replace(tzinfo=None).isoformat()

        reg = register_override(
            "max_provisional", 50,
            prior=30, proposed_by="test", approved_via="test",
            expires_at=naive_future, _now=now, _store_root=tmp_path,
        )

        active = list_active_overrides(_store_root=tmp_path, _now=now)
        assert len(active) == 1
        assert active[0]["id"] == reg["id"]

    def test_resolve_knobs_batch_over_naive_expiry_store_does_not_raise(self, tmp_path):
        """Mirrors the verified hot-path shape: prefetch's
        _graph_layer_shadow_lines calls resolve_knob (which delegates to
        resolve_knobs) with no surrounding try/except. A naive-expiry record
        anywhere in the store must not make that call raise.
        """
        now = datetime.now(timezone.utc)
        naive_future = (now + timedelta(days=1)).replace(tzinfo=None).isoformat()
        register_override(
            "graph_layer_injection_enabled", False,
            prior=True, proposed_by="test", approved_via="test",
            expires_at=naive_future, _now=now, _store_root=tmp_path,
        )

        # Simulate a prefetch-style multi-knob batch resolve over the same store.
        result = resolve_knobs(
            {"graph_layer_injection_enabled": True, "lane_continuity_freshness_enabled": True},
            _now=now, _store_root=tmp_path,
        )
        assert result["graph_layer_injection_enabled"] is False
        assert result["lane_continuity_freshness_enabled"] is True

    def test_hand_written_unparseable_expiry_still_fails_open(self, tmp_path):
        """Genuinely unparseable expires_at (garbage, not just naive) must
        still fail open (treated as not-expired) via the ValueError branch,
        which the fix preserves. This record is hand-written because part
        (b) of the fix makes register_override reject it -- it simulates a
        pre-existing legacy record that predates the write-boundary guard.
        """
        store_path = _override_store_path(None, _store_root=tmp_path)
        store_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "schema_version": "memory-os.knob_override.v0",
            "id": "ko_legacy_garbage",
            "knob": "min_cluster_size",
            "override_value": 4,
            "prior_value": 2,
            "bounds": [1, 5],
            "provisional": True,
            "expires_at": "not-a-timestamp",
            "proposed_by": "legacy",
            "approved_via": "legacy",
            "state": "active",
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        with store_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

        # Fail-open: unparseable expiry treated as not-expired -> override wins.
        result = resolve_knob("min_cluster_size", default=2, _store_root=tmp_path)
        assert result == 4


class TestRegisterOverrideRejectsMalformedExpiry:
    """DEFECT 1(b): register_override must validate expires_at at the write
    boundary, while keeping expires_at="" (no expiry) valid."""

    def test_unparseable_expires_at_is_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="not a valid ISO-8601 timestamp"):
            register_override(
                "min_cluster_size", 3,
                prior=2, proposed_by="test", approved_via="test",
                expires_at="not-a-timestamp", _store_root=tmp_path,
            )

    def test_garbage_expires_at_does_not_get_written_to_store(self, tmp_path):
        """The rejected write must not land in the JSONL at all."""
        with pytest.raises(ValueError):
            register_override(
                "min_cluster_size", 3,
                prior=2, proposed_by="test", approved_via="test",
                expires_at="garbage", _store_root=tmp_path,
            )
        store_path = _override_store_path(None, _store_root=tmp_path)
        assert not store_path.exists()

    def test_empty_string_expires_at_still_means_no_expiry(self, tmp_path):
        """Regression guard: expires_at="" (documented no-expiry sentinel)
        must remain valid and must never expire."""
        now = datetime.now(timezone.utc)
        reg = register_override(
            "min_cluster_size", 3,
            prior=2, proposed_by="test", approved_via="test",
            expires_at="", _now=now, _store_root=tmp_path,
        )
        assert reg["state"] == "active"
        result = resolve_knob(
            "min_cluster_size", default=2,
            _now=now + timedelta(days=3650), _store_root=tmp_path,
        )
        assert result == 3

    def test_naive_expires_at_is_still_accepted_at_write_time(self, tmp_path):
        """A naive (no-offset) ISO timestamp parses fine and must still be
        accepted for registration -- only genuinely unparseable values are
        rejected. _is_expired's naive-as-UTC handling covers the rest."""
        now = datetime.now(timezone.utc)
        naive_future = (now + timedelta(days=7)).replace(tzinfo=None).isoformat()
        reg = register_override(
            "min_cluster_size", 3,
            prior=2, proposed_by="test", approved_via="test",
            expires_at=naive_future, _now=now, _store_root=tmp_path,
        )
        assert reg["state"] == "active"
        assert reg["expires_at"] == naive_future

    def test_existing_aware_expiry_callers_are_unaffected(self, tmp_path):
        """Regression guard: the ordinary aware-ISO caller shape used
        throughout the rest of the test suite must be unaffected."""
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(days=7)).isoformat()
        reg = register_override(
            "min_cluster_size", 3,
            prior=2, proposed_by="test", approved_via="test",
            expires_at=expires, _now=now, _store_root=tmp_path,
        )
        assert reg["state"] == "active"
        assert resolve_knob("min_cluster_size", default=2, _store_root=tmp_path) == 3
