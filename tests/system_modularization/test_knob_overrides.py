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
