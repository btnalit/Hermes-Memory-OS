"""Tests for plugins/memory/memory_os/recall_policy.py.

Covers the authority/freshness matrix contract, evaluate_observation_window's
contiguous-suffix semantics, and the size-gated retention added to
append_recall_observation (P2 fix: the observation ledger previously grew
forever with no compaction).
"""

from __future__ import annotations

from pathlib import Path

from plugins.memory.memory_os import recall_policy
from plugins.memory.memory_os.jsonl_io import read_jsonl
from plugins.memory.memory_os.recall_policy import (
    OBSERVATION_WINDOW_ID,
    append_recall_observation,
    evaluate_observation_window,
    read_recall_observation_window,
    recall_observation_path,
)


class FakeRoots:
    def __init__(self, tmp_path: Path) -> None:
        self.memory_os_root = tmp_path / "memory-os"
        self.memory_os_root.mkdir(parents=True, exist_ok=True)
        (self.memory_os_root / "system").mkdir(parents=True, exist_ok=True)


def _plan(**overrides):
    plan = {
        "mode": "shadow",
        "selected": [],
        "authority_freshness_matrix_version": "x",
        "authority_freshness_matrix_digest": "y",
        "observation_window_id": OBSERVATION_WINDOW_ID,
        "input_count": 1,
        "selected_count": 1,
        "suppressed_count": 0,
        "exact_duplicate_count": 0,
        "near_duplicate_count": 0,
        "conflict_count": 0,
        "would_change_live_recall": False,
    }
    plan.update(overrides)
    return plan


class TestRecallObservationRetention:
    """P2 fix: append_recall_observation must not grow the ledger forever."""

    def test_compaction_bounds_ledger_growth_keeping_newest_tail(self, tmp_path, monkeypatch):
        """Retention is size-gated with hysteresis (compact once > threshold,
        keep the newest RETAIN_COUNT) — it does not fire on every single
        append. The invariant that must hold at every step (not just
        eventually) is that the ledger never grows past the threshold, and
        that whatever survives is a contiguous tail ending at the most
        recent append."""
        monkeypatch.setattr(recall_policy, "RECALL_OBSERVATION_COMPACT_THRESHOLD", 5)
        monkeypatch.setattr(recall_policy, "RECALL_OBSERVATION_RETAIN_COUNT", 3)

        roots = FakeRoots(tmp_path)
        for i in range(8):
            assert append_recall_observation(roots, _plan(input_count=i)) is True
            rows = read_jsonl(recall_observation_path(roots))
            # Bounded growth must hold at every step, not just at the end —
            # without compaction this would climb past 5 starting at i=5.
            assert len(rows) <= 5

        rows = read_jsonl(recall_observation_path(roots))
        # Contiguous tail: whatever remains is an unbroken run of the newest
        # appends, ending at the very last one written (input_count == 7).
        kept = [r["input_count"] for r in rows]
        assert kept == list(range(8))[-len(kept):]
        assert kept[-1] == 7

    def test_compaction_preserves_contiguous_suffix_for_current_window(self, tmp_path, monkeypatch):
        """Dropping old head rows must never corrupt
        evaluate_observation_window's contiguous-suffix semantics for the
        CURRENT matrix era — the whole point of keeping a tail rather than
        an arbitrary subset. Every surviving row shares the current window
        id, so nothing should ever be invalidated by the trim."""
        monkeypatch.setattr(recall_policy, "RECALL_OBSERVATION_COMPACT_THRESHOLD", 4)
        monkeypatch.setattr(recall_policy, "RECALL_OBSERVATION_RETAIN_COUNT", 2)

        roots = FakeRoots(tmp_path)
        for i in range(6):
            append_recall_observation(roots, _plan(input_count=i))

        status = read_recall_observation_window(roots)
        assert status["observation_window_id"] == OBSERVATION_WINDOW_ID
        assert status["window_reset_required"] is False
        assert status["invalidated_observation_count"] == 0
        # Bounded by the compaction threshold — without compaction this
        # would be 6 (every row ever appended).
        assert status["current_observation_count"] <= 4

    def test_no_compaction_below_threshold(self, tmp_path, monkeypatch):
        monkeypatch.setattr(recall_policy, "RECALL_OBSERVATION_COMPACT_THRESHOLD", 100)
        monkeypatch.setattr(recall_policy, "RECALL_OBSERVATION_RETAIN_COUNT", 50)
        roots = FakeRoots(tmp_path)
        for i in range(5):
            append_recall_observation(roots, _plan(input_count=i))
        rows = read_jsonl(recall_observation_path(roots))
        assert len(rows) == 5

    def test_evaluate_observation_window_still_rejects_stale_era_after_compaction(self, tmp_path, monkeypatch):
        """A stale-era row surviving compaction at the head must still be
        excluded from the current window once a current-era row exists
        after it (pre-existing invariant — must not regress)."""
        monkeypatch.setattr(recall_policy, "RECALL_OBSERVATION_COMPACT_THRESHOLD", 10)
        monkeypatch.setattr(recall_policy, "RECALL_OBSERVATION_RETAIN_COUNT", 5)
        roots = FakeRoots(tmp_path)

        from plugins.memory.memory_os.jsonl_io import append_jsonl_locked

        append_jsonl_locked(recall_observation_path(roots), {
            "schema_version": "memory-os.recall_observation.v1",
            "observation_window_id": "stale-version:stale-digest",
            "observed_at": "2026-01-01T00:00:00Z",
        })
        append_recall_observation(roots, _plan(input_count=1))

        status = read_recall_observation_window(roots)
        assert status["invalidated_observation_count"] == 1
        assert status["current_observation_count"] == 1
