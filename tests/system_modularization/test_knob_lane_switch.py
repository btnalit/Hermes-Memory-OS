"""A3 lane switch tests — boolean knob type + owner-gated routing + MAX_OVERRIDES."""
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from plugins.memory.memory_os.knob_overrides import (
    OVERRIDABLE_KNOBS,
    register_override,
    resolve_knob,
    revert_override,
    confirm_override,
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
    assert record["bounds"] == [2, 5]
    assert record["allowed"] is None
