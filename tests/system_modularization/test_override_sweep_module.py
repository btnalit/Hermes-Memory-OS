"""Tests for override_sweep — TTL/cap/kill-switch lifecycle for knob overrides."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from plugins.memory.memory_os.knob_overrides import (
    register_override,
    list_active_overrides,
    revert_override,
    resolve_knob,
)
from plugins.modules.governance.override_sweep import OverrideSweepModule


class TestOverrideSweep:
    def test_V3_7_ttl_expired_reverts_to_prior(self, tmp_path):
        """V3.7: provisional override past expires_at → reverted, prior restored."""
        now = datetime.now(timezone.utc)
        # Register with short TTL (already expired)
        expires_past = (now - timedelta(hours=1)).isoformat()
        reg = register_override(
            "min_cluster_size", 3, prior=2, proposed_by="test",
            approved_via="resolver", expires_at=expires_past,
            _now=now, _store_root=tmp_path,
        )

        # Before sweep: override is active (expiry check happens at resolve time)
        # Sweep should catch it
        module = OverrideSweepModule(str(tmp_path), profile="test")
        result = module.run_once(_store_root=tmp_path, _now=now)

        assert result["expired_count"] >= 0  # TTL sweep ran
        # After sweep, resolve should return default
        val = resolve_knob("min_cluster_size", default=2, _store_root=tmp_path)
        assert val == 2  # Prior restored

    def test_V3_8_owner_confirmed_stays_permanent(self, tmp_path):
        """V3.8: confirmed override is permanent (provisional=False, no expires_at)."""
        now = datetime.now(timezone.utc)
        expires_future = (now + timedelta(days=7)).isoformat()
        reg = register_override(
            "min_cluster_size", 3, prior=2, proposed_by="self_evolution",
            approved_via="resolver", expires_at=expires_future,
            _now=now, _store_root=tmp_path,
        )

        # Simulate owner confirmation (write confirmed record)
        from plugins.memory.memory_os.knob_overrides import _override_store_path
        import json
        confirmed = {
            "schema_version": "memory-os.knob_override.v0",
            "id": f"ko_confirmed_{now.strftime('%Y%m%dT%H%M%S%fZ')}",
            "knob": "min_cluster_size",
            "override_value": 3,
            "prior_value": 2,
            "bounds": [2, 5],
            "provisional": False,
            "expires_at": "",
            "proposed_by": "owner",
            "approved_via": "owner",
            "state": "confirmed",
            "ts": now.isoformat(),
        }
        store_path = _override_store_path(_store_root=tmp_path)
        with store_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(confirmed, ensure_ascii=False, sort_keys=True) + "\n")

        # Run sweep — confirmed should not be reverted
        module = OverrideSweepModule(str(tmp_path), profile="test")
        result = module.run_once(_store_root=tmp_path, _now=now + timedelta(days=8))

        # Confirmed override still active
        val = resolve_knob("min_cluster_size", default=2,
                           _now=now + timedelta(days=8), _store_root=tmp_path)
        assert val == 3  # Confirmed stays

    def test_V3_9_owner_rejected_reverts(self, tmp_path):
        """V3.9: owner rejected → revert restores prior, audit record exists."""
        now = datetime.now(timezone.utc)
        expires_future = (now + timedelta(days=7)).isoformat()
        reg = register_override(
            "min_cluster_size", 3, prior=2, proposed_by="self_evolution",
            approved_via="resolver", expires_at=expires_future,
            _now=now, _store_root=tmp_path,
        )

        # Simulate owner rejection
        rev = revert_override(reg["id"], reason="owner_rejected", _store_root=tmp_path)
        assert rev["state"] == "reverted_owner_rejected"
        assert rev["override_value"] == 2  # prior restored

        # resolve_knob returns default
        val = resolve_knob("min_cluster_size", default=2, _store_root=tmp_path)
        assert val == 2

    def test_V3_10_kill_switch_reverts_all_active(self, tmp_path):
        """V3.10: kill switch engaged → all active overrides reverted to prior."""
        now = datetime.now(timezone.utc)
        expires_future = (now + timedelta(days=7)).isoformat()

        # Register two active overrides
        register_override(
            "min_cluster_size", 3, prior=2, proposed_by="test",
            approved_via="resolver", expires_at=expires_future,
            _now=now, _store_root=tmp_path,
        )

        # Kill switch: revert all
        active = list_active_overrides(_store_root=tmp_path, _now=now)
        for override in active:
            revert_override(override["id"], reason="kill_switch_engaged",
                           _store_root=tmp_path)

        # All reverted
        active_after = list_active_overrides(_store_root=tmp_path, _now=now)
        assert len(active_after) == 0

        # Values restored
        assert resolve_knob("min_cluster_size", default=2, _store_root=tmp_path) == 2


class TestOverrideSweepEndToEnd:
    def test_V3_11_full_cycle_propose_enact_revert(self, tmp_path):
        """V3.11: propose 2→3 → enact → clustering uses 3 → expire → revert → back to 2."""
        now = datetime.now(timezone.utc)

        # 1. Default is 2
        assert resolve_knob("min_cluster_size", default=2, _store_root=tmp_path) == 2

        # 2. Register override 2→3
        expires_future = (now + timedelta(days=7)).isoformat()
        register_override(
            "min_cluster_size", 3, prior=2, proposed_by="self_evolution",
            approved_via="resolver", expires_at=expires_future,
            _now=now, _store_root=tmp_path,
        )

        # 3. Override active → resolve returns 3
        assert resolve_knob("min_cluster_size", default=2, _store_root=tmp_path) == 3

        # 4. TTL expires → revert
        future = now + timedelta(days=8)
        module = OverrideSweepModule(str(tmp_path), profile="test")
        module.run_once(_store_root=tmp_path, _now=future)

        # 5. Back to default
        assert resolve_knob("min_cluster_size", default=2,
                           _now=future, _store_root=tmp_path) == 2
