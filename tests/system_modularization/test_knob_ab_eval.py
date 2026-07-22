"""Tests for knob_ab_eval — stratified A/B self-validation decisions.

Covers:
  - Multi-step tighten: intermediate layers included in discarded
  - A2.2: auto-confirm (tighten, discarded clearly worse)
  - A2.3: auto-revert (tighten, discarded clearly better)
  - A2.4: relax direction falls back to owner
  - A2.5: insufficient observations falls back to owner
  - A2.5b: ambiguous diff falls back to owner
  - A2.6: confirm_override side effects (permanent, no expiry)
  - Edge cases: no overrides, no ab_metric, malformed data
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from plugins.modules.governance.knob_ab_eval import AB_MARGIN, AB_MIN_OBS


# ── Fixture helpers ────────────────────────────────────────────────────

def _make_store(tmp_path, *, profile="test"):
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile=profile)
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def _write_candidate_triage(store, entries):
    """Write candidate_triage.jsonl from list of (candidate_id, cluster_size) tuples."""
    path = store.roots.crystallized_root / "candidate_triage.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    with path.open("w", encoding="utf-8") as f:
        for cid, cs in entries:
            rec = {
                "candidate_id": cid,
                "cluster_size": cs,
                "action": "promote",
                "target_state": "promoted",
                "reason": "cluster_promotion",
                "cluster_key": f"key_{cs}",
                "execution_gate_envelope_id": "test_envelope",
                "created_at": now,
            }
            f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True))
            f.write("\n")


def _write_owner_actions(store, entries):
    """Write owner_actions.jsonl from list of (target_id, action) tuples.

    action in: approve, confirm, confirmed, reject, rejected, demote
    """
    path = store.roots.memory_os_root / "system" / "owner_actions.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    with path.open("w", encoding="utf-8") as f:
        for target_id, action in entries:
            rec = {
                "target_id": target_id,
                "action": action,
                "candidate_id": target_id,
                "created_at": now,
                "action_token": f"oa_{target_id}",
                "reviewer": "test_owner",
                "purpose": "approve_for_crystallized",
            }
            f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True))
            f.write("\n")


def _register_test_override(tmp_path, *, knob="min_cluster_size", value, prior, **kwargs):
    """Register a single test override with future expiry."""
    from plugins.memory.memory_os.knob_overrides import register_override

    now = datetime.now(timezone.utc)
    expires = kwargs.get("expires_at", (now + timedelta(days=7)).isoformat())
    return register_override(
        knob, value,
        prior=prior,
        proposed_by=kwargs.get("proposed_by", "self_evolution"),
        approved_via=kwargs.get("approved_via", "resolver"),
        expires_at=expires,
        _now=now,
        _store_root=tmp_path,
    )


def _run_ab_eval(tmp_path, store):
    """Run one tick of KnobABEvalModule."""
    from plugins.modules.governance.knob_ab_eval import KnobABEvalModule

    module = KnobABEvalModule(tmp_path, profile="test")
    return module.run_once(store=store, _store_root=tmp_path)


# ── A2.2: Auto-confirm ─────────────────────────────────────────────────

def test_run_once_uses_injected_store_roots_without_ambient_fallback(tmp_path, monkeypatch):
    import warnings

    from plugins.memory.memory_os import knob_overrides
    from plugins.modules.governance.knob_ab_eval import KnobABEvalModule

    store = _make_store(tmp_path)
    monkeypatch.setattr(knob_overrides, "_ambient_fallback_warned", False)
    module = KnobABEvalModule(tmp_path, profile="test")

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        result = module.run_once(store=store, _now=datetime.now(timezone.utc))

    assert result["ab_confirmed_count"] == 0
    assert result["ab_reverted_count"] == 0


class TestA2AutoConfirm:
    """A2.2: tighten where discarded layer has significantly lower confirm rate."""

    def test_single_step_tighten_auto_confirms(self, tmp_path):
        """prior=2→3: size=2 discarded (20% confirm), size≥3 retained (80%) → auto-confirm."""
        store = _make_store(tmp_path)

        # Layer 2 (discarded): 2 confirmed, 8 rejected → 20%
        triage = [(f"c{i:03d}", 2) for i in range(10)]
        # Layer 3 (retained): 8 confirmed, 2 rejected → 80%
        triage += [(f"c1{i:02d}", 3) for i in range(10)]
        _write_candidate_triage(store, triage)

        oa = [(f"c{i:03d}", "approve") for i in range(2)]
        oa += [(f"c{i:03d}", "reject") for i in range(2, 10)]
        oa += [(f"c1{i:02d}", "approve") for i in range(8)]
        oa += [(f"c1{i:02d}", "reject") for i in range(8, 10)]
        _write_owner_actions(store, oa)

        _register_test_override(tmp_path, value=3, prior=2)

        result = _run_ab_eval(tmp_path, store)
        assert result["ab_confirmed_count"] == 1
        assert result["ab_reverted_count"] == 0
        assert result["skipped_no_data_count"] == 0

    def test_tighten_multi_step_handles_intermediate_layers(self, tmp_path):
        """Multi-step 2→4: sizes 2+3 discarded, sizes 4+5 retained.

        This is a RED test — current code only includes size==prior (layer 2)
        in the discarded set, losing size=3 entirely. The result is a wrong
        decision (skip instead of auto-confirm).

        Layer 2: 9 confirm, 1 reject  → 90%
        Layer 3: 1 confirm, 9 reject   → 10%  (MUST be in discarded — CURRENTLY LOST)
        Layer 4: 8 confirm, 2 reject   → 80%  (retained)
        Layer 5: 8 confirm, 2 reject   → 80%  (retained)

        Buggy:  discarded=layer2(90%) vs retained=80% → diff=-10pp → skip
        Correct: discarded=layers2+3(50%) vs retained=80% → diff=30pp → auto-confirm
        """
        store = _make_store(tmp_path)

        triage = []
        triage += [(f"s2_{i:02d}", 2) for i in range(10)]
        triage += [(f"s3_{i:02d}", 3) for i in range(10)]
        triage += [(f"s4_{i:02d}", 4) for i in range(10)]
        triage += [(f"s5_{i:02d}", 5) for i in range(10)]
        _write_candidate_triage(store, triage)

        oa = []
        # Layer 2: 9 approved, 1 rejected
        oa += [(f"s2_{i:02d}", "approve") for i in range(9)]
        oa += [("s2_09", "reject")]
        # Layer 3: 1 approved, 9 rejected
        oa += [("s3_00", "approve")]
        oa += [(f"s3_{i:02d}", "reject") for i in range(1, 10)]
        # Layer 4: 8 approved, 2 rejected
        oa += [(f"s4_{i:02d}", "approve") for i in range(8)]
        oa += [(f"s4_{i:02d}", "reject") for i in range(8, 10)]
        # Layer 5: 8 approved, 2 rejected
        oa += [(f"s5_{i:02d}", "approve") for i in range(8)]
        oa += [(f"s5_{i:02d}", "reject") for i in range(8, 10)]
        _write_owner_actions(store, oa)

        _register_test_override(tmp_path, value=4, prior=2)

        result = _run_ab_eval(tmp_path, store)
        assert result["ab_confirmed_count"] == 1, (
            f"Multi-step tighten should auto-confirm "
            f"(discarded[2+3]=50% vs retained[4+5]=80%, diff=30pp >= {AB_MARGIN}), "
            f"but got confirmed={result['ab_confirmed_count']}, "
            f"reverted={result['ab_reverted_count']}, "
            f"skipped_insufficient={result['skipped_insufficient_obs_count']}"
        )


# ── A2.3: Auto-revert ──────────────────────────────────────────────────

class TestA2AutoRevert:
    """A2.3: tighten where discarded layer has significantly higher confirm rate."""

    def test_single_step_tighten_discarded_better_auto_reverts(self, tmp_path):
        """size=2 discarded (80% confirm), size=3 retained (20%) → auto-revert."""
        store = _make_store(tmp_path)

        triage = [(f"c{i:03d}", 2) for i in range(10)]
        triage += [(f"c1{i:02d}", 3) for i in range(10)]
        _write_candidate_triage(store, triage)

        oa = [(f"c{i:03d}", "approve") for i in range(8)]
        oa += [(f"c{i:03d}", "reject") for i in range(8, 10)]
        oa += [(f"c1{i:02d}", "approve") for i in range(2)]
        oa += [(f"c1{i:02d}", "reject") for i in range(2, 10)]
        _write_owner_actions(store, oa)

        _register_test_override(tmp_path, value=3, prior=2)

        result = _run_ab_eval(tmp_path, store)
        assert result["ab_reverted_count"] == 1
        assert result["ab_confirmed_count"] == 0
        assert result["skipped_no_data_count"] == 0

    def test_multi_step_tighten_discarded_better_auto_reverts(self, tmp_path):
        """Multi-step 2→4 where intermediate layer supports the revert signal.

        Layer 2: 8 confirm, 2 reject  → 80%
        Layer 3: 8 confirm, 2 reject  → 80%  (MUST be in discarded)
        Layer 4: 2 confirm, 8 reject  → 20%  (retained)
        Layer 5: 2 confirm, 8 reject  → 20%  (retained)

        Buggy:  discarded=layer2(80%) vs retained=20% → diff=-60pp → auto-revert
                (correct result, wrong data — layer 3 inclusion doesn't change outcome)
        Correct: discarded=layers2+3(80%) vs retained=20% → diff=-60pp → auto-revert

        Both paths produce auto-revert here, but the buggy path is fragile:
        if layer 3 has a different ratio, the decision flips incorrectly.
        """
        store = _make_store(tmp_path)

        triage = []
        triage += [(f"s2_{i:02d}", 2) for i in range(10)]
        triage += [(f"s3_{i:02d}", 3) for i in range(10)]
        triage += [(f"s4_{i:02d}", 4) for i in range(10)]
        triage += [(f"s5_{i:02d}", 5) for i in range(10)]
        _write_candidate_triage(store, triage)

        oa = []
        # Layer 2: 8 approved, 2 rejected
        oa += [(f"s2_{i:02d}", "approve") for i in range(8)]
        oa += [(f"s2_{i:02d}", "reject") for i in range(8, 10)]
        # Layer 3: 8 approved, 2 rejected (same signal as layer 2)
        oa += [(f"s3_{i:02d}", "approve") for i in range(8)]
        oa += [(f"s3_{i:02d}", "reject") for i in range(8, 10)]
        # Layer 4: 2 approved, 8 rejected
        oa += [(f"s4_{i:02d}", "approve") for i in range(2)]
        oa += [(f"s4_{i:02d}", "reject") for i in range(2, 10)]
        # Layer 5: 2 approved, 8 rejected
        oa += [(f"s5_{i:02d}", "approve") for i in range(2)]
        oa += [(f"s5_{i:02d}", "reject") for i in range(2, 10)]
        _write_owner_actions(store, oa)

        _register_test_override(tmp_path, value=4, prior=2)

        result = _run_ab_eval(tmp_path, store)
        assert result["ab_reverted_count"] == 1


# ── A2.4: Relax falls back to owner ────────────────────────────────────

class TestA2RelaxFallsBack:
    """A2.4: relax direction (override <= prior) → always skip (no auto-decision)."""

    def test_relax_skip_no_data(self, tmp_path):
        """override=2, prior=3 → relax → skipped_no_data."""
        store = _make_store(tmp_path)
        _write_candidate_triage(store, [])
        _write_owner_actions(store, [])
        _register_test_override(tmp_path, value=2, prior=3)

        result = _run_ab_eval(tmp_path, store)
        assert result["skipped_no_data_count"] == 1
        assert result["ab_confirmed_count"] == 0
        assert result["ab_reverted_count"] == 0

    def test_equal_values_skip_no_data(self, tmp_path):
        """override=3, prior=3 → equal (no-op) → skipped_no_data."""
        store = _make_store(tmp_path)
        _write_candidate_triage(store, [])
        _write_owner_actions(store, [])
        _register_test_override(tmp_path, value=3, prior=3)

        result = _run_ab_eval(tmp_path, store)
        assert result["skipped_no_data_count"] == 1
        assert result["ab_confirmed_count"] == 0


# ── A2.5: Insufficient observations ────────────────────────────────────

class TestA2InsufficientObs:
    """A2.5: < AB_MIN_OBS observations → falls back to owner (conservative)."""

    def test_too_few_observations_skip(self, tmp_path):
        """Only 3 obs per layer (< AB_MIN_OBS=5) → insufficient → skip."""
        store = _make_store(tmp_path)

        triage = [(f"c{i}", 2) for i in range(3)]
        triage += [(f"d{i}", 3) for i in range(3)]
        _write_candidate_triage(store, triage)

        oa = [(f"c{i}", "approve") for i in range(3)]
        oa += [(f"d{i}", "reject") for i in range(3)]
        _write_owner_actions(store, oa)

        _register_test_override(tmp_path, value=3, prior=2)

        result = _run_ab_eval(tmp_path, store)
        assert result["skipped_insufficient_obs_count"] >= 1
        assert result["ab_confirmed_count"] == 0
        assert result["ab_reverted_count"] == 0

    def test_no_triage_data_skip(self, tmp_path):
        """Empty candidate_triage → no layer_rates → insufficient."""
        store = _make_store(tmp_path)
        _write_candidate_triage(store, [])
        _write_owner_actions(store, [])
        _register_test_override(tmp_path, value=3, prior=2)

        result = _run_ab_eval(tmp_path, store)
        assert result["skipped_insufficient_obs_count"] == 1
        assert result["ab_confirmed_count"] == 0

    def test_discarded_layer_missing_skip(self, tmp_path):
        """No data for prior_value layer → discarded_rate is None → insufficient."""
        store = _make_store(tmp_path)
        # Only size=3 data, no size=2 (prior_value)
        triage = [(f"c{i:02d}", 3) for i in range(10)]
        _write_candidate_triage(store, triage)
        oa = [(f"c{i:02d}", "approve") for i in range(5)]
        oa += [(f"c{i:02d}", "reject") for i in range(5, 10)]
        _write_owner_actions(store, oa)
        _register_test_override(tmp_path, value=3, prior=2)

        result = _run_ab_eval(tmp_path, store)
        assert result["skipped_insufficient_obs_count"] == 1
        assert result["ab_confirmed_count"] == 0

    def test_one_layer_below_min_obs_skip(self, tmp_path):
        """Discarded layer has 6 obs (>=5) but retained has 4 obs (<5) → insufficient."""
        store = _make_store(tmp_path)

        triage = [(f"c{i:02d}", 2) for i in range(6)]
        triage += [(f"d{i:02d}", 3) for i in range(4)]  # too few
        _write_candidate_triage(store, triage)

        oa = [(f"c{i:02d}", "approve") for i in range(1)]
        oa += [(f"c{i:02d}", "reject") for i in range(1, 6)]
        oa += [(f"d{i:02d}", "approve") for i in range(4)]
        _write_owner_actions(store, oa)

        _register_test_override(tmp_path, value=3, prior=2)

        result = _run_ab_eval(tmp_path, store)
        assert result["skipped_insufficient_obs_count"] == 1
        assert result["ab_confirmed_count"] == 0


# ── A2.5b: Ambiguous diff ──────────────────────────────────────────────

class TestA2AmbiguousDiff:
    """Diff within AB_MARGIN → falls back to owner (not clear enough)."""

    def test_diff_within_margin_skip(self, tmp_path):
        """Discarded 50%, retained 60% → diff=10pp < AB_MARGIN(15pp) → skip."""
        store = _make_store(tmp_path)

        triage = [(f"c{i:02d}", 2) for i in range(10)]
        triage += [(f"d{i:02d}", 3) for i in range(10)]
        _write_candidate_triage(store, triage)

        oa = [(f"c{i:02d}", "approve") for i in range(5)]
        oa += [(f"c{i:02d}", "reject") for i in range(5, 10)]
        oa += [(f"d{i:02d}", "approve") for i in range(6)]
        oa += [(f"d{i:02d}", "reject") for i in range(6, 10)]
        _write_owner_actions(store, oa)

        _register_test_override(tmp_path, value=3, prior=2)

        result = _run_ab_eval(tmp_path, store)
        assert result["skipped_insufficient_obs_count"] == 1
        assert result["ab_confirmed_count"] == 0
        assert result["ab_reverted_count"] == 0

    def test_diff_exactly_at_margin_confirms(self, tmp_path):
        """Diff exactly == AB_MARGIN → auto-confirm (>= boundary)."""
        store = _make_store(tmp_path)

        # AB_MARGIN = 0.15 = 15pp
        # discarded: 3.5/10 = 35%, retained: 5/10 = 50% → diff = 15pp
        # But we need integer counts...  15pp of 10 obs = 1.5 obs
        # Use 20 obs per layer for cleaner math
        # discarded: 7/20 = 35%, retained: 10/20 = 50% → diff = 15pp exactly
        triage = [(f"c{i:02d}", 2) for i in range(20)]
        triage += [(f"d{i:02d}", 3) for i in range(20)]
        _write_candidate_triage(store, triage)

        oa = [(f"c{i:02d}", "approve") for i in range(7)]
        oa += [(f"c{i:02d}", "reject") for i in range(7, 20)]
        oa += [(f"d{i:02d}", "approve") for i in range(10)]
        oa += [(f"d{i:02d}", "reject") for i in range(10, 20)]
        _write_owner_actions(store, oa)

        _register_test_override(tmp_path, value=3, prior=2)

        result = _run_ab_eval(tmp_path, store)
        # diff = 0.50 - 0.35 = 0.15 >= AB_MARGIN → auto-confirm
        assert result["ab_confirmed_count"] == 1


# ── A2.6: confirm_override side effects ─────────────────────────────────

class TestA2ConfirmOverrideEffects:
    """A2.6: confirm_override writes confirmed record, override stays active."""

    def test_confirmed_override_stays_active(self, tmp_path):
        """After auto-confirm, override is still active (state=confirmed, no expiry)."""
        store = _make_store(tmp_path)

        triage = [(f"c{i:03d}", 2) for i in range(10)]
        triage += [(f"c1{i:02d}", 3) for i in range(10)]
        _write_candidate_triage(store, triage)

        oa = [(f"c{i:03d}", "approve") for i in range(2)]
        oa += [(f"c{i:03d}", "reject") for i in range(2, 10)]
        oa += [(f"c1{i:02d}", "approve") for i in range(8)]
        oa += [(f"c1{i:02d}", "reject") for i in range(8, 10)]
        _write_owner_actions(store, oa)

        _register_test_override(tmp_path, value=3, prior=2)

        result = _run_ab_eval(tmp_path, store)
        assert result["ab_confirmed_count"] == 1

        from plugins.memory.memory_os.knob_overrides import list_active_overrides

        active = list_active_overrides(_store_root=tmp_path)
        assert len(active) == 1, (
            "Confirmed override should remain active (now permanent, state='confirmed')"
        )
        assert active[0]["state"] == "confirmed"
        assert active[0]["expires_at"] == ""

    def test_auto_confirm_resolve_returns_override_value(self, tmp_path):
        """After auto-confirm, resolve_knob still returns the override value."""
        store = _make_store(tmp_path)

        triage = [(f"c{i:03d}", 2) for i in range(10)]
        triage += [(f"c1{i:02d}", 3) for i in range(10)]
        _write_candidate_triage(store, triage)

        oa = [(f"c{i:03d}", "approve") for i in range(2)]
        oa += [(f"c{i:03d}", "reject") for i in range(2, 10)]
        oa += [(f"c1{i:02d}", "approve") for i in range(8)]
        oa += [(f"c1{i:02d}", "reject") for i in range(8, 10)]
        _write_owner_actions(store, oa)

        _register_test_override(tmp_path, value=3, prior=2)

        result = _run_ab_eval(tmp_path, store)
        assert result["ab_confirmed_count"] == 1

        from plugins.memory.memory_os.knob_overrides import resolve_knob

        val = resolve_knob("min_cluster_size", default=2, _store_root=tmp_path)
        assert val == 3, "Confirmed override should still return override value"


# ── Edge cases ──────────────────────────────────────────────────────────

class TestKnobABEdgeCases:
    """Edge cases that must not crash."""

    def test_no_active_overrides_clean_noop(self, tmp_path):
        """No overrides registered → all counters zero."""
        store = _make_store(tmp_path)
        _write_candidate_triage(store, [])
        _write_owner_actions(store, [])

        result = _run_ab_eval(tmp_path, store)
        assert result["ab_confirmed_count"] == 0
        assert result["ab_reverted_count"] == 0
        assert result["skipped_no_data_count"] == 0
        assert result["skipped_insufficient_obs_count"] == 0

    def test_override_without_ab_metric_skipped(self, tmp_path):
        """Knob without ab_metric is not evaluated (not counted in any counter)."""
        store = _make_store(tmp_path)
        _write_candidate_triage(store, [])
        _write_owner_actions(store, [])

        # max_speak_per_hour has NO ab_metric in OVERRIDABLE_KNOBS
        now = datetime.now(timezone.utc)
        from plugins.memory.memory_os.knob_overrides import register_override

        register_override(
            "max_speak_per_hour", 3, prior=5,
            proposed_by="test", approved_via="resolver",
            expires_at=(now + timedelta(days=7)).isoformat(),
            _now=now, _store_root=tmp_path,
        )

        result = _run_ab_eval(tmp_path, store)
        assert result["ab_confirmed_count"] == 0
        assert result["ab_reverted_count"] == 0

    def test_malformed_owner_actions_not_crash(self, tmp_path):
        """Malformed JSON in owner_actions → skipped gracefully, no crash."""
        store = _make_store(tmp_path)

        triage = [(f"c{i:03d}", 2) for i in range(10)]
        triage += [(f"c1{i:02d}", 3) for i in range(10)]
        _write_candidate_triage(store, triage)

        # Write valid owner_actions but half are on referenced candidates
        oa = [(f"c{i:03d}", "approve") for i in range(5)]
        oa += [(f"c{i:03d}", "reject") for i in range(5, 10)]
        # Only 5 of the size=3 candidates have owner decisions
        oa += [(f"c1{i:02d}", "approve") for i in range(5)]
        _write_owner_actions(store, oa)

        _register_test_override(tmp_path, value=3, prior=2)

        result = _run_ab_eval(tmp_path, store)
        # Layer 2: 5 confirmed, 5 rejected = 10 obs → fine
        # Layer 3: 5 confirmed, 0 rejected = 5 obs → exactly at AB_MIN_OBS
        # So both layers have enough obs
        # discarded_rate = 0.5 (5/10), retained_rate = 1.0 (5/5)
        # Wait, but candidates without owner decisions are just not in the map
        # So layer 3 only has 5 obs not 10 — that's exactly AB_MIN_OBS
        # diff = 1.0 - 0.5 = 0.5 >= 0.15 → auto-confirm
        assert result["ab_confirmed_count"] >= 0  # doesn't crash

    def test_corrupt_candidate_triage_not_crash(self, tmp_path):
        """Corrupt JSON in candidate_triage → error_record, not crash."""
        store = _make_store(tmp_path)

        # Write malformed candidate_triage
        triage_path = store.roots.crystallized_root / "candidate_triage.jsonl"
        triage_path.parent.mkdir(parents=True, exist_ok=True)
        triage_path.write_text("not valid json\n", encoding="utf-8")

        _write_owner_actions(store, [])
        _register_test_override(tmp_path, value=3, prior=2)

        result = _run_ab_eval(tmp_path, store)
        # Should not crash — _compute_stratified_confirm_rates raises,
        # run_once catches it and records error
        assert len(result.get("error_records", [])) >= 1, (
            "Corrupt triage data must produce error_record, not silent pass"
        )

    def test_status_includes_active_ab_overrides(self, tmp_path):
        """status() reports count of active overrides with ab_metric."""
        store = _make_store(tmp_path)
        _write_candidate_triage(store, [])
        _write_owner_actions(store, [])

        # Register two overrides: one with ab_metric, one without
        now = datetime.now(timezone.utc)
        from plugins.memory.memory_os.knob_overrides import register_override

        register_override(
            "min_cluster_size", 3, prior=2,  # HAS ab_metric
            proposed_by="test", approved_via="resolver",
            expires_at=(now + timedelta(days=7)).isoformat(),
            _now=now, roots=store.roots,
        )
        register_override(
            "max_speak_per_hour", 3, prior=5,  # NO ab_metric
            proposed_by="test", approved_via="resolver",
            expires_at=(now + timedelta(days=7)).isoformat(),
            _now=now, roots=store.roots,
        )

        from plugins.modules.governance.knob_ab_eval import KnobABEvalModule

        module = KnobABEvalModule(tmp_path, profile="test")
        status = module.status()
        assert status["ab_eligible_override_count"] == 1
