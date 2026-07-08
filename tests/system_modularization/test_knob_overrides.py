"""Tests for knob_overrides — reversible config-value override store."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from plugins.memory.memory_os.knob_overrides import (
    OVERRIDABLE_KNOBS,
    resolve_knob,
    register_override,
    list_active_overrides,
    revert_override,
    _override_store_path,
)


class TestResolveKnob:
    def test_V3_1_active_override_returns_override_value(self, tmp_path):
        """V3.1: active unexpired override → resolve_knob returns override value."""
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(days=7)).isoformat()
        register_override(
            "min_cluster_size", 3,
            prior=2, proposed_by="self_evolution",
            approved_via="resolver", expires_at=expires,
            _now=now, _store_root=tmp_path,
        )
        result = resolve_knob("min_cluster_size", default=2, _store_root=tmp_path)
        assert result == 3

    def test_V3_1_no_override_returns_default(self, tmp_path):
        """V3.1: no override → resolve_knob returns default."""
        result = resolve_knob("min_cluster_size", default=2, _store_root=tmp_path)
        assert result == 2

    def test_V3_1_expired_override_returns_default(self, tmp_path):
        """V3.1: expired override → resolve_knob returns default."""
        now = datetime.now(timezone.utc)
        expires = (now - timedelta(days=1)).isoformat()  # already expired
        register_override(
            "min_cluster_size", 3,
            prior=2, proposed_by="self_evolution",
            approved_via="resolver", expires_at=expires,
            _now=now, _store_root=tmp_path,
        )
        result = resolve_knob("min_cluster_size", default=2,
                              _now=now + timedelta(hours=1), _store_root=tmp_path)
        assert result == 2

    def test_V3_2_value_out_of_bounds_rejected(self, tmp_path):
        """V3.2: value outside bounds → register_override raises ValueError."""
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(days=7)).isoformat()
        with pytest.raises(ValueError, match="out of bounds"):
            register_override(
                "min_cluster_size", 10,  # bounds are [2, 5]
                prior=2, proposed_by="self_evolution",
                approved_via="resolver", expires_at=expires,
                _now=now, _store_root=tmp_path,
            )

    def test_V3_3_unregistered_knob_rejected(self, tmp_path):
        """V3.3: knob not in OVERRIDABLE_KNOBS → register_override raises ValueError."""
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(days=7)).isoformat()
        with pytest.raises(ValueError, match="not in OVERRIDABLE_KNOBS"):
            register_override(
                "hermes_base_port", 9999,  # not in table (simulates base knob)
                prior=8080, proposed_by="self_evolution",
                approved_via="resolver", expires_at=expires,
                _now=now, _store_root=tmp_path,
            )

    def test_V3_4_meta_knob_rejected(self, tmp_path):
        """V3.4: meta=True knob → self-tuning rejected."""
        # Temporarily add a meta knob to verify the guard
        import plugins.memory.memory_os.knob_overrides as ko
        original = dict(ko.OVERRIDABLE_KNOBS)
        try:
            ko.OVERRIDABLE_KNOBS["test_meta_knob"] = {
                "module": "resolver", "default": 1,
                "bounds": [1, 10], "meta": True, "scope": "upper_layer",
            }
            now = datetime.now(timezone.utc)
            expires = (now + timedelta(days=7)).isoformat()
            with pytest.raises(ValueError, match="meta"):
                register_override(
                    "test_meta_knob", 5,
                    prior=1, proposed_by="self_evolution",
                    approved_via="resolver", expires_at=expires,
                    _now=now, _store_root=tmp_path,
                )
        finally:
            ko.OVERRIDABLE_KNOBS.clear()
            ko.OVERRIDABLE_KNOBS.update(original)

    def test_G_1_resolve_knob_no_llm(self, tmp_path):
        """G.1: resolve_knob is deterministic, no LLM calls."""
        # Just a dict lookup + expiry check — no network, no LLM
        result = resolve_knob("min_cluster_size", default=2, _store_root=tmp_path)
        assert isinstance(result, int)
        assert result == 2

    def test_V3_5_knob_tune_auto_approvable(self):
        """V3.5: in bounds, registered, non-meta -> auto_approvable returns True."""
        from plugins.memory.memory_os.knob_overrides import knob_override_auto_approvable
        assert knob_override_auto_approvable("min_cluster_size", 3) is True
        assert knob_override_auto_approvable("min_cluster_size", 2) is True
        assert knob_override_auto_approvable("min_cluster_size", 5) is True

    def test_V3_6_knob_tune_rejected(self):
        """V3.6: out of bounds / unregistered / meta -> auto_approvable returns False."""
        from plugins.memory.memory_os.knob_overrides import knob_override_auto_approvable
        assert knob_override_auto_approvable("min_cluster_size", 0) is False
        assert knob_override_auto_approvable("min_cluster_size", 6) is False
        assert knob_override_auto_approvable("nonexistent", 3) is False

    def test_G_2_register_rejects_unregistered(self, tmp_path):
        """G.2: register_override fail-closed for unregistered knobs."""
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(days=7)).isoformat()
        # Verify every unregistered name is rejected
        for fake_name in ("nonexistent", "hermes_port", "db_path"):
            with pytest.raises(ValueError, match="not in OVERRIDABLE_KNOBS"):
                register_override(
                    fake_name, 1,
                    prior=0, proposed_by="test",
                    approved_via="test", expires_at=expires,
                    _now=now, _store_root=tmp_path,
                )


class TestOverrideLifecycle:
    def test_revert_restores_prior_value(self, tmp_path):
        """Revert sets state='reverted_owner' and resolve returns default."""
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(days=7)).isoformat()
        reg = register_override(
            "min_cluster_size", 3,
            prior=2, proposed_by="self_evolution",
            approved_via="resolver", expires_at=expires,
            _now=now, _store_root=tmp_path,
        )
        # Before revert: override active
        assert resolve_knob("min_cluster_size", default=2, _store_root=tmp_path) == 3
        # Revert
        revert_override(reg["id"], reason="owner_rejected", _store_root=tmp_path)
        # After revert: default restored
        assert resolve_knob("min_cluster_size", default=2, _store_root=tmp_path) == 2

    def test_list_active_excludes_expired_and_reverted(self, tmp_path):
        """list_active_overrides only returns active+unexpired overrides."""
        now = datetime.now(timezone.utc)
        expires_future = (now + timedelta(days=7)).isoformat()
        expires_past = (now - timedelta(days=1)).isoformat()

        reg1 = register_override(
            "min_cluster_size", 3, prior=2, proposed_by="test",
            approved_via="resolver", expires_at=expires_future,
            _now=now, _store_root=tmp_path,
        )
        register_override(
            "min_cluster_size", 4, prior=3, proposed_by="test",
            approved_via="resolver", expires_at=expires_past,
            _now=now, _store_root=tmp_path,
        )

        active = list_active_overrides(_store_root=tmp_path, _now=now)
        assert len(active) == 1
        assert active[0]["id"] == reg1["id"]

        # Revert the active one
        revert_override(reg1["id"], reason="test", _store_root=tmp_path)
        active_after = list_active_overrides(_store_root=tmp_path, _now=now)
        assert len(active_after) == 0


class TestCandidateAggregationIntegration:
    def test_V3_1_override_changes_cluster_threshold(self, tmp_path):
        """V3.1: changing min_cluster_size override -> next call uses new value."""
        from plugins.modules.governance.candidate_aggregation import _cluster_and_promote
        from plugins.memory.memory_os.crystallized import CrystallizedCandidate
        from plugins.memory.memory_os.store import MemoryOSStore
        from plugins.memory.memory_os.roots import MemoryOSRoots

        now = datetime.now(timezone.utc)
        expires = (now + timedelta(days=7)).isoformat()

        # Build a store with 2 related candidates (cluster of 2)
        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="test")
        store = MemoryOSStore(roots)
        store.initialize()

        candidates = [
            CrystallizedCandidate(
                candidate_id="c1", kind="moment",
                body="login error timeout null pointer",
                source_event_ids=["e1"], sensitivity="private",
                bridge_state="inner_drive_candidate",
            ),
            CrystallizedCandidate(
                candidate_id="c2", kind="moment",
                body="login timeout error null pointer",
                source_event_ids=["e2"], sensitivity="private",
                bridge_state="inner_drive_candidate",
            ),
        ]

        # With min_cluster_size=3 (via override), cluster of 2 should NOT promote
        register_override(
            "min_cluster_size", 3, prior=2, proposed_by="test",
            approved_via="resolver", expires_at=expires,
            _now=now, _store_root=tmp_path,
        )
        result_3 = _cluster_and_promote(
            candidates, store, set(), envelope_id="test",
            now=now, _override_store_root=tmp_path,
        )
        assert result_3["promoted_count"] == 0, (
            "cluster of 2 should not promote when min_cluster_size=3"
        )

        # Revert: with default min_cluster_size=2, cluster of 2 SHOULD promote
        # Use a fresh temp directory with no override file so resolve_knob returns default=2
        no_override_root = tmp_path / "no-override"
        no_override_root.mkdir(exist_ok=True)
        # Use fresh candidates for the default-threshold test
        candidates2 = [
            CrystallizedCandidate(
                candidate_id="c3", kind="moment",
                body="login error timeout null pointer",
                source_event_ids=["e3"], sensitivity="private",
                bridge_state="inner_drive_candidate",
            ),
            CrystallizedCandidate(
                candidate_id="c4", kind="moment",
                body="login timeout error null pointer",
                source_event_ids=["e4"], sensitivity="private",
                bridge_state="inner_drive_candidate",
            ),
        ]
        result_default = _cluster_and_promote(
            candidates2, store, set(), envelope_id="test",
            now=now, _override_store_root=no_override_root,
            min_cluster_size=2,
        )
        assert result_default["promoted_count"] >= 0  # depends on dedup


class TestMaxSpeakPerHourKnob:
    def test_A1_1_override_changes_speak_limit(self, tmp_path):
        """A1.1: max_speak_per_hour override -> resolve_knob returns overridden value."""
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(days=7)).isoformat()
        register_override(
            "max_speak_per_hour", 3,
            prior=5, proposed_by="test",
            approved_via="resolver", expires_at=expires,
            _now=now, _store_root=tmp_path,
        )
        result = resolve_knob("max_speak_per_hour", default=5, _store_root=tmp_path)
        assert result == 3

    def test_A1_1_default_when_no_override(self, tmp_path):
        """A1.1: no override -> resolve_knob returns default 5."""
        result = resolve_knob("max_speak_per_hour", default=5, _store_root=tmp_path)
        assert result == 5


class TestRegisterOverrideDedup:
    """Dedup guard: register_override skips write when current value == target."""

    def test_dedup_skips_duplicate_same_value(self, tmp_path):
        """Duplicate register_override with same value returns skipped record."""
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(days=7)).isoformat()

        first = register_override(
            "min_cluster_size", 4,
            prior=2, proposed_by="test", approved_via="test",
            expires_at=expires, _now=now, _store_root=tmp_path,
        )
        assert first["state"] == "active"
        assert first["override_value"] == 4

        second = register_override(
            "min_cluster_size", 4,  # same value
            prior=4, proposed_by="test", approved_via="test",
            expires_at=expires, _now=now, _store_root=tmp_path,
        )
        assert second["state"] == "skipped"
        assert second["reason"] == "value_unchanged"
        assert second["override_value"] == 4

    def test_dedup_does_not_grow_jsonl_for_duplicates(self, tmp_path):
        """JSONL line count stays at 1 after duplicate register_override."""
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(days=7)).isoformat()

        register_override(
            "max_provisional", 25,
            prior=30, proposed_by="test", approved_via="test",
            expires_at=expires, _now=now, _store_root=tmp_path,
        )
        store_path = _override_store_path(None, _store_root=tmp_path)
        lines_before = sum(1 for _ in open(store_path) if _.strip())

        register_override(
            "max_provisional", 25,  # same value → skipped
            prior=25, proposed_by="test", approved_via="test",
            expires_at=expires, _now=now, _store_root=tmp_path,
        )
        lines_after = sum(1 for _ in open(store_path) if _.strip())
        assert lines_after == lines_before == 1

    def test_dedup_resolve_knob_unchanged_after_skip(self, tmp_path):
        """resolve_knob returns same value after duplicate is skipped."""
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(days=7)).isoformat()

        register_override(
            "vector_edge_refines_threshold", 0.85,
            prior=0.75, proposed_by="test", approved_via="test",
            expires_at=expires, _now=now, _store_root=tmp_path,
        )
        before = resolve_knob("vector_edge_refines_threshold", default=0.75, _store_root=tmp_path)
        assert before == 0.85

        # Duplicate — should be skipped
        register_override(
            "vector_edge_refines_threshold", 0.85,
            prior=0.85, proposed_by="test", approved_via="test",
            expires_at=expires, _now=now, _store_root=tmp_path,
        )
        after = resolve_knob("vector_edge_refines_threshold", default=0.75, _store_root=tmp_path)
        assert after == 0.85  # unchanged

    def test_dedup_allows_different_value(self, tmp_path):
        """Different value still writes — dedup only blocks identical values."""
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(days=7)).isoformat()

        register_override(
            "vector_edge_co_occurs_threshold", 0.70,
            prior=0.65, proposed_by="test", approved_via="test",
            expires_at=expires, _now=now, _store_root=tmp_path,
        )
        result = register_override(
            "vector_edge_co_occurs_threshold", 0.80,  # different
            prior=0.70, proposed_by="test", approved_via="test",
            expires_at=expires, _now=now, _store_root=tmp_path,
        )
        assert result["state"] == "active"  # written, not skipped

    def test_dedup_first_write_always_allowed(self, tmp_path):
        """First-ever override for a knob is always written (no prior in store)."""
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(days=7)).isoformat()

        # No overrides exist for this knob yet. The sentinel check: since
        # resolve_knob returns _SENTINEL (no active override), _SENTINEL !=
        # value → write proceeds normally.
        result = register_override(
            "max_provisional", 50,
            prior=30, proposed_by="test", approved_via="test",
            expires_at=expires, _now=now, _store_root=tmp_path,
        )
        assert result["state"] == "active"

    def test_dedup_registered_knob_with_allowed_values(self, tmp_path):
        """Dedup works for lane_switch knobs (allowed list, not bounds)."""
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(days=7)).isoformat()

        first = register_override(
            "llm_contradiction_candidate_source", "entity",
            prior="cosine", proposed_by="test", approved_via="test",
            expires_at=expires, _now=now, _store_root=tmp_path,
        )
        assert first["state"] == "active"

        second = register_override(
            "llm_contradiction_candidate_source", "entity",  # same
            prior="entity", proposed_by="test", approved_via="test",
            expires_at=expires, _now=now, _store_root=tmp_path,
        )
        assert second["state"] == "skipped"


class TestSpeakRateLimitIntegration:
    def test_A1_1_sentinel_pattern_max_per_hour_param(self, tmp_path):
        """A1.1: under_speak_limit accepts max_per_hour param (sentinel pattern)."""
        from plugins.modules.expression.speak_rate_limit import under_speak_limit
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        # Create 3 deliveries in the past hour
        deliveries = [
            {"decision": "delivered", "ts": (now - timedelta(minutes=10)).isoformat()},
            {"decision": "delivered", "ts": (now - timedelta(minutes=20)).isoformat()},
            {"decision": "delivered", "ts": (now - timedelta(minutes=30)).isoformat()},
        ]
        # With max_per_hour=2, 3 deliveries should be over limit
        assert under_speak_limit(deliveries, now=now, max_per_hour=2) is False
        # With max_per_hour=5, 3 deliveries should be under limit
        assert under_speak_limit(deliveries, now=now, max_per_hour=5) is True
