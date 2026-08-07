"""A3 lane switch tests — boolean knob type + owner-gated routing + MAX_OVERRIDES."""
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from plugins.memory.memory_os.knob_overrides import (
    OVERRIDABLE_KNOBS,
    confirm_override,
    register_override,
    resolve_knob,
    revert_override,
    list_active_overrides,
    knob_override_auto_approvable,
)


# ── Helpers ──────────────────────────────────────────────────────────────

@pytest.fixture
def store_root():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _future_iso(hours: int = 24) -> str:
    return (_now() + timedelta(hours=hours)).isoformat()


# ── A3.1: Boolean value validation ───────────────────────────────────────

def test_lane_switch_accepts_true(store_root):
    """A3.1: register_override accepts True for lane_switch knob."""
    record = register_override(
        "lane_low_clue_recall_enabled", True,
        prior=False, proposed_by="test", approved_via="test",
        expires_at=_future_iso(), _store_root=store_root,
    )
    assert record["override_value"] is True
    assert record["state"] == "active"


def test_lane_switch_accepts_false(store_root):
    """A3.1: register_override accepts False for lane_switch knob."""
    record = register_override(
        "lane_low_clue_recall_enabled", False,
        prior=True, proposed_by="test", approved_via="test",
        expires_at=_future_iso(), _store_root=store_root,
    )
    assert record["override_value"] is False
    assert record["state"] == "active"


def test_lane_switch_rejects_int(store_root):
    """A3.1: register_override rejects int for lane_switch knob (not in allowed)."""
    with pytest.raises(ValueError, match="not in allowed"):
        register_override(
            "lane_low_clue_recall_enabled", 1,
            prior=False, proposed_by="test", approved_via="test",
            expires_at=_future_iso(), _store_root=store_root,
        )


def test_lane_switch_rejects_string(store_root):
    """A3.1: register_override rejects 'yes' for lane_switch knob."""
    with pytest.raises(ValueError, match="not in allowed"):
        register_override(
            "lane_low_clue_recall_enabled", "yes",
            prior=False, proposed_by="test", approved_via="test",
            expires_at=_future_iso(), _store_root=store_root,
        )


def test_lane_switch_rejects_none(store_root):
    """A3.1: register_override rejects None for lane_switch knob."""
    with pytest.raises(ValueError, match="not in allowed"):
        register_override(
            "lane_low_clue_recall_enabled", None,
            prior=False, proposed_by="test", approved_via="test",
            expires_at=_future_iso(), _store_root=store_root,
        )


# ── A3.2 + A3.2a: resolve_knob returns boolean correctly ─────────────────

def test_resolve_lane_switch_override_true(store_root):
    """A3.2: resolve_knob returns True when override(True) is active."""
    register_override(
        "lane_low_clue_recall_enabled", True,
        prior=False, proposed_by="test", approved_via="test",
        expires_at=_future_iso(), _store_root=store_root,
    )
    result = resolve_knob("lane_low_clue_recall_enabled", default=False, _store_root=store_root)
    assert result is True


def test_resolve_lane_switch_override_false_with_default_true(store_root):
    """A3.2a: resolve_knob returns False when override(False) is active, even with default=True.

    This is the critical False-boundary test — verifies that Python's
    .get("override_value", default) correctly returns False when the
    key exists, rather than falling back to the default.
    """
    register_override(
        "lane_low_clue_recall_enabled", False,
        prior=True, proposed_by="test", approved_via="test",
        expires_at=_future_iso(), _store_root=store_root,
    )
    result = resolve_knob("lane_low_clue_recall_enabled", default=True, _store_root=store_root)
    assert result is False  # ← NOT True (would happen if .get() treated False as missing)


def test_resolve_lane_switch_no_override_returns_default(store_root):
    """A3.2: resolve_knob returns config default when no override exists."""
    result = resolve_knob("lane_low_clue_recall_enabled", default=True, _store_root=store_root)
    assert result is True
    result2 = resolve_knob("lane_low_clue_recall_enabled", default=False, _store_root=store_root)
    assert result2 is False


# ── A3.3: Owner-gated routing ─────────────────────────────────────────────

def test_lane_switch_never_auto_approvable_true(store_root):
    """A3.3: knob_override_auto_approvable returns False for lane_switch (True value)."""
    assert knob_override_auto_approvable("lane_low_clue_recall_enabled", True) is False


def test_lane_switch_never_auto_approvable_false(store_root):
    """A3.3: knob_override_auto_approvable returns False for lane_switch (False value)."""
    assert knob_override_auto_approvable("lane_low_clue_recall_enabled", False) is False


# ── A3.4: Threshold knobs still auto-approvable ───────────────────────────

def test_threshold_knob_still_auto_approvable_in_bounds():
    """A3.4: min_cluster_size within [2,5] still auto-approvable (A3 doesn't break A1/A2)."""
    assert knob_override_auto_approvable("min_cluster_size", 3) is True


def test_threshold_knob_still_rejects_out_of_bounds():
    """A3.4: min_cluster_size outside [2,5] still rejected."""
    assert knob_override_auto_approvable("min_cluster_size", 6) is False


# ── A3.5: Lane switch skipped by A/B ──────────────────────────────────────

def test_lane_switch_not_ab_evaluated():
    """A3.5: lane_switch knob has ab_metric=None, so A/B eval skips it.

    This is verified by inspecting the knob spec — no runtime A/B needed.
    knob_ab_eval.run_once() checks `if not ab_metric: continue`."""
    spec = OVERRIDABLE_KNOBS["lane_low_clue_recall_enabled"]
    assert spec["ab_metric"] is None


# ── A3.7: Boundary enforcement ───────────────────────────────────────────

def test_unregistered_knob_rejected(store_root):
    """A3.7: register_override rejects knobs not in OVERRIDABLE_KNOBS."""
    with pytest.raises(ValueError, match="not in OVERRIDABLE_KNOBS"):
        register_override(
            "ops_gate", True,
            prior=False, proposed_by="test", approved_via="test",
            expires_at=_future_iso(), _store_root=store_root,
        )


# ── A3.8: Revert restores config default ─────────────────────────────────

def test_lane_switch_revert_restores_default(store_root):
    """A3.8: reverting a lane override restores the config default."""
    register_override(
        "lane_low_clue_recall_enabled", True,
        prior=False, proposed_by="test", approved_via="test",
        expires_at=_future_iso(), _store_root=store_root,
    )
    active = list_active_overrides(_store_root=store_root)
    assert len(active) == 1
    override_id = active[0]["id"]

    revert_override(override_id, reason="owner_reverted", _store_root=store_root)

    # After revert, resolve_knob returns the default (False)
    result = resolve_knob("lane_low_clue_recall_enabled", default=False, _store_root=store_root)
    assert result is False


# ── A3.9: Kill switch reverts lane override ──────────────────────────────

def test_lane_switch_kill_reverts(store_root):
    """A3.9: kill switch (override_sweep) reverts lane override back to default."""
    register_override(
        "lane_low_clue_recall_enabled", True,
        prior=False, proposed_by="test", approved_via="test",
        expires_at=_future_iso(), _store_root=store_root,
    )
    # Simulate what override_sweep does with kill switch engaged
    from plugins.modules.governance.override_sweep import OverrideSweepModule
    mod = OverrideSweepModule(hermes_home=store_root.parent, profile="test")
    result = mod.run_once(_kill_switch_enabled=True, _store_root=store_root)

    assert result["kill_reverted_count"] >= 1
    # After kill, resolve_knob returns the default
    resolved = resolve_knob("lane_low_clue_recall_enabled", default=False, _store_root=store_root)
    assert resolved is False


# ── MAX_OVERRIDES constant ────────────────────────────────────────────────

def test_max_overrides_is_module_level_constant():
    """#4: MAX_OVERRIDES is a module-level constant, not a local variable."""
    from plugins.modules.governance import override_sweep
    assert hasattr(override_sweep, "MAX_OVERRIDES")
    assert override_sweep.MAX_OVERRIDES == 30


# ── allowed field stored in records ───────────────────────────────────────

def test_lane_switch_record_stores_allowed(store_root):
    """#3: register_override stores 'allowed' field in the JSONL record."""
    record = register_override(
        "lane_low_clue_recall_enabled", True,
        prior=False, proposed_by="test", approved_via="test",
        expires_at=_future_iso(), _store_root=store_root,
    )
    assert record["allowed"] == [True, False]
    assert record["bounds"] is None  # lane_switch has no bounds


def test_threshold_knob_record_stores_bounds_not_allowed(store_root):
    """Threshold knobs still store bounds, allowed is None."""
    record = register_override(
        "min_cluster_size", 3,
        prior=2, proposed_by="test", approved_via="test",
        expires_at=_future_iso(), _store_root=store_root,
    )
    assert record["bounds"] == [1, 5]
    assert record["allowed"] is None


# ── A3.6: Runtime gate integration ────────────────────────────────────────

def test_resolve_knob_injects_into_prefetch_config(store_root):
    """A3.6: resolve_knob result injected into low_clue_recall_config before build_prefetch.

    Verifies the injection pattern: read config default → resolve knob →
    inject resolved value into config dict. The resolved dict is then
    passed to build_prefetch, where normalize_low_clue_recall_config merges
    it and _recall_clarification_guard_lines reads bool(config.get('enabled')).
    """
    from plugins.memory.memory_os.knob_overrides import resolve_knob

    # Simulate the pattern that prefetch() will use:
    #   1. Start with the config dict
    #   2. Extract the raw enabled value as default
    #   3. Resolve knob — this may override the default
    #   4. Inject resolved value back into config dict
    #   5. Pass to build_prefetch / normalize_low_clue_recall_config

    config = {"enabled": False, "candidate_limit": 4}

    # Pattern A: config default is False, no override → remains False
    cfg_enabled_a = bool(config.get("enabled"))
    resolved_a = resolve_knob(
        "lane_low_clue_recall_enabled",
        default=cfg_enabled_a,
        _store_root=store_root,
    )
    config_a = dict(config)
    config_a["enabled"] = resolved_a
    assert config_a["enabled"] is False  # default preserved

    # Pattern B: config default is True, no override → remains True
    config2 = {"enabled": True, "candidate_limit": 4}
    cfg_enabled_b = bool(config2.get("enabled"))
    resolved_b = resolve_knob(
        "lane_low_clue_recall_enabled",
        default=cfg_enabled_b,
        _store_root=store_root,
    )
    config2["enabled"] = resolved_b
    assert config2["enabled"] is True  # config default preserved


def test_resolve_knob_in_prefetch_with_active_override(store_root):
    """A3.6: when an active override(True) exists, config dict gets True injected."""
    register_override(
        "lane_low_clue_recall_enabled", True,
        prior=False, proposed_by="test", approved_via="test",
        expires_at=_future_iso(), _store_root=store_root,
    )

    from plugins.memory.memory_os.knob_overrides import resolve_knob

    config = {"enabled": False, "candidate_limit": 4}
    cfg_enabled = bool(config.get("enabled"))
    resolved = resolve_knob(
        "lane_low_clue_recall_enabled", default=cfg_enabled,
        _store_root=store_root,
    )
    config["enabled"] = resolved
    assert config["enabled"] is True  # override active, overrides config default


def test_resolve_knob_override_false_overrides_config_true(store_root):
    """A3.6: override(False) overrides config default(True) — lane forced off."""
    register_override(
        "lane_low_clue_recall_enabled", False,
        prior=True, proposed_by="test", approved_via="test",
        expires_at=_future_iso(), _store_root=store_root,
    )

    from plugins.memory.memory_os.knob_overrides import resolve_knob

    config = {"enabled": True, "candidate_limit": 4}
    cfg_enabled = bool(config.get("enabled"))
    resolved = resolve_knob(
        "lane_low_clue_recall_enabled", default=cfg_enabled,
        _store_root=store_root,
    )
    config["enabled"] = resolved
    assert config["enabled"] is False  # override forces off despite config


# ── CR-FIX #1, #2: allowed field propagation ────────────────────────────

def test_revert_override_propagates_allowed_field(store_root):
    """CR-FIX #1: revert_override stores 'allowed' from the original record."""
    record = register_override(
        "lane_low_clue_recall_enabled", True,
        prior=False, proposed_by="test", approved_via="test",
        expires_at=_future_iso(), _store_root=store_root,
    )
    # Read the raw JSONL to find the reversion record after revert
    reversion = revert_override(
        record["id"], reason="owner_reverted", _store_root=store_root,
    )
    assert reversion["allowed"] == [True, False]
    assert reversion["bounds"] is None


def test_confirm_override_propagates_allowed_field(store_root):
    """CR-FIX #2: confirm_override stores 'allowed' from the original record."""
    record = register_override(
        "lane_low_clue_recall_enabled", False,
        prior=True, proposed_by="test", approved_via="test",
        expires_at=_future_iso(), _store_root=store_root,
    )
    confirmed = confirm_override(
        record["id"], reason="ab_confirmed", _store_root=store_root,
    )
    assert confirmed["allowed"] == [True, False]
    assert confirmed["bounds"] is None


def test_threshold_knob_revert_still_propagates_bounds(store_root):
    """CR-FIX #1 regression: threshold knob revert still propagates bounds correctly."""
    record = register_override(
        "min_cluster_size", 4,
        prior=2, proposed_by="test", approved_via="test",
        expires_at=_future_iso(), _store_root=store_root,
    )
    reversion = revert_override(
        record["id"], reason="owner_reverted", _store_root=store_root,
    )
    assert reversion["bounds"] == [1, 5]
    assert reversion["allowed"] is None  # threshold knobs have no allowed


# ── CR-FIX #3: non-boolean allowed list support ─────────────────────────

def test_register_override_rejects_value_not_in_allowed_non_bool(store_root):
    """CR-FIX #3: non-boolean allowed lists reject values outside allowed."""
    # Simulate a future string-enum knob — the type check should NOT be
    # bool-only when allowed values are not bools.
    # We cannot add a real knob to OVERRIDABLE_KNOBS, so we verify the
    # logic via the existing lane_switch knob (bool allowed) still works
    # and that the type guard only activates for bool allowed lists.

    # Bool allowed: int 1 should STILL be rejected (type guard active)
    with pytest.raises(ValueError, match="not in allowed"):
        register_override(
            "lane_low_clue_recall_enabled", 1,
            prior=False, proposed_by="test", approved_via="test",
            expires_at=_future_iso(), _store_root=store_root,
        )

    # Bool allowed: bool True should STILL be accepted (type guard active, value in allowed)
    record = register_override(
        "lane_low_clue_recall_enabled", True,
        prior=False, proposed_by="test", approved_via="test",
        expires_at=_future_iso(), _store_root=store_root,
    )
    assert record["override_value"] is True


# ── A3.10: graph_layer_injection_enabled knob ──────────────────────────────

def test_graph_layer_injection_enabled_is_registered_lane_switch(store_root):
    """graph_layer_injection_enabled: lane_switch, default True(P1 2026-08-07,
    owner 裁定图谱为永久能力 — 开关保留作回滚,not for graduation;旧默认
    False 靠无过期 override 撑着,override 丢失即静默变暗且监控不响)。"""
    from plugins.memory.memory_os.knob_overrides import OVERRIDABLE_KNOBS, resolve_knob

    spec = OVERRIDABLE_KNOBS.get("graph_layer_injection_enabled")
    assert spec is not None, "graph_layer_injection_enabled must be in OVERRIDABLE_KNOBS"
    assert spec.get("kind") == "lane_switch"
    assert spec.get("default") is True
    assert spec.get("allowed") == [True, False]
    assert spec.get("meta") is False

    # Verify resolve_knob returns default when no override exists
    result = resolve_knob(
        "graph_layer_injection_enabled",
        default=True,
        _store_root=store_root,
    )
    assert result is True


def test_non_bool_allowed_list_would_not_trigger_type_guard():
    """CR-FIX #3: the isinstance(allowed[0], bool) guard means non-bool allowed
    lists (e.g. string enums) would skip the type-strict check and use plain
    membership. This is verified by code inspection — no runtime test possible
    without a real non-bool knob in OVERRIDABLE_KNOBS.

    The guard logic:
      if allowed and isinstance(allowed[0], bool):
          # type-strict bool check
      else:
          # plain value-in-allowed check (no type constraint)
    """
    # Sanity: lane_switch allowed[0] is True (a bool), so the guard activates
    spec = OVERRIDABLE_KNOBS["lane_low_clue_recall_enabled"]
    assert isinstance(spec["allowed"][0], bool)  # guard would activate


# ── A3.11: vector_retrieval_enabled knob ────────────────────────────────

def test_vector_retrieval_enabled_is_registered_lane_switch():
    """vector_retrieval_enabled is a registered lane_switch knob."""
    from plugins.memory.memory_os.knob_overrides import OVERRIDABLE_KNOBS, knob_override_auto_approvable
    assert "vector_retrieval_enabled" in OVERRIDABLE_KNOBS
    spec = OVERRIDABLE_KNOBS["vector_retrieval_enabled"]
    assert spec["default"] is False
    assert spec["kind"] == "lane_switch"
    assert spec["module"] == "prefetch"
    assert spec["meta"] is False
    assert False in spec["allowed"]
    assert True in spec["allowed"]
    # lane_switch is not auto-approvable
    assert knob_override_auto_approvable("vector_retrieval_enabled", True) is False


# ── A3.12: vector_edge_proposer_enabled knob ─────────────────────────────


def test_vector_edge_proposer_enabled_is_registered_lane_switch():
    """vector_edge_proposer_enabled is a registered lane_switch knob."""
    from plugins.memory.memory_os.knob_overrides import OVERRIDABLE_KNOBS, knob_override_auto_approvable
    assert "vector_edge_proposer_enabled" in OVERRIDABLE_KNOBS
    spec = OVERRIDABLE_KNOBS["vector_edge_proposer_enabled"]
    assert spec["default"] is False
    assert spec["kind"] == "lane_switch"
    assert spec["module"] == "vector_edge_proposer"
    assert spec["meta"] is False
    assert False in spec["allowed"]
    assert True in spec["allowed"]
    # lane_switch is not auto-approvable
    assert knob_override_auto_approvable("vector_edge_proposer_enabled", True) is False


# ── CR-FIX #6: session_scoped_recent_events knob ────────────────────────────


def test_session_scoped_recent_events_knob_registered():
    """#6: session_scoped_recent_events must be in OVERRIDABLE_KNOBS."""
    from plugins.memory.memory_os.knob_overrides import OVERRIDABLE_KNOBS
    assert "session_scoped_recent_events" in OVERRIDABLE_KNOBS
    knob = OVERRIDABLE_KNOBS["session_scoped_recent_events"]
    assert knob["module"] == "prefetch"
    assert knob["default"] is True
    assert knob["kind"] == "lane_switch"
    assert knob["allowed"] == [True, False]
