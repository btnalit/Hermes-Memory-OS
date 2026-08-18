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


class TestRecallShadowMonitorStats:
    """The shadow window's first production reader.

    Before this function the ledger's only consumer was the provider's own
    `status` call, so a lane whose entire purpose is to produce graduation
    evidence had no way to show that evidence to anyone.
    """

    def test_empty_window_reports_no_sample_rather_than_health(self, tmp_path):
        from plugins.memory.memory_os.recall_policy import recall_shadow_monitor_stats

        stats = recall_shadow_monitor_stats(FakeRoots(tmp_path))

        assert stats["sample_state"] == "healthy_no_sample", (
            "an empty window must say so on its face; a silent 0 reads as a clean bill of health"
        )
        assert stats["current_observation_count"] == 0
        assert stats["suppressed_total"] == 0
        assert stats["latest_observed_at"] == ""

    def test_window_aggregates_reason_decomposition_and_saturation(self, tmp_path):
        from plugins.memory.memory_os.recall_policy import (
            SUPPRESSION_REASONS,
            recall_shadow_monitor_stats,
        )

        roots = FakeRoots(tmp_path)
        append_recall_observation(roots, _plan(
            suppressed=[{"reason": "near_duplicate"}, {"reason": "budget_exceeded"}],
            suppressed_count=2, near_duplicate_count=1, ambiguous_pair_count=2,
            input_count=5, selected_count=3, would_change_live_recall=True,
        ))
        append_recall_observation(roots, _plan(
            suppressed=[{"reason": "near_duplicate"}],
            suppressed_count=1, near_duplicate_count=1,
            input_count=4, selected_count=3, would_change_live_recall=True,
        ))

        stats = recall_shadow_monitor_stats(roots)

        assert stats["sample_state"] == "sampled"
        assert stats["current_observation_count"] == 2
        assert set(stats["suppressed_by_reason"]) == set(SUPPRESSION_REASONS)
        assert stats["suppressed_by_reason"]["near_duplicate"] == 2
        assert stats["suppressed_by_reason"]["budget_exceeded"] == 1
        assert stats["input_total"] == 9
        assert stats["selected_total"] == 6
        assert stats["suppressed_total"] == 3
        assert stats["ambiguous_pair_total"] == 2
        # Reported beside the decomposition precisely because it saturated at
        # 100% on production and therefore decides nothing on its own.
        assert stats["would_change_live_recall_true_count"] == 2
        assert stats["schema_version_counts"] == {"memory-os.recall_observation.v2": 2}

    def test_conflict_denominator_survives_into_the_window(self, tmp_path):
        """A permanently-zero conflict_total needs its input count beside it."""
        from plugins.memory.memory_os.recall_policy import recall_shadow_monitor_stats

        roots = FakeRoots(tmp_path)
        append_recall_observation(roots, _plan(conflict_count=0, claim_keyed_input_count=0))
        append_recall_observation(roots, _plan(conflict_count=0, claim_keyed_input_count=3))

        stats = recall_shadow_monitor_stats(roots)

        assert stats["conflict_total"] == 0
        assert stats["claim_keyed_input_total"] == 3, (
            "without this the zero above cannot be told from a broken lane"
        )

    def test_mixed_schema_versions_in_one_window_are_visible(self, tmp_path):
        """A window holding two schema versions means a deploy skipped its era
        boundary; every ratio computed over it would mix incompatible rows, so
        the mix must be readable rather than averaged away."""
        from plugins.memory.memory_os.jsonl_io import append_jsonl_locked
        from plugins.memory.memory_os.recall_policy import recall_shadow_monitor_stats

        roots = FakeRoots(tmp_path)
        append_jsonl_locked(recall_observation_path(roots), {
            "schema_version": "memory-os.recall_observation.v1",
            "observation_window_id": OBSERVATION_WINDOW_ID,
            "observed_at": "2026-08-01T00:00:00Z",
            "input_count": 2, "selected_count": 1, "suppressed_count": 1,
        })
        append_recall_observation(roots, _plan(
            suppressed=[{"reason": "near_duplicate"}], suppressed_count=1))

        stats = recall_shadow_monitor_stats(roots)

        assert stats["schema_version_counts"] == {
            "memory-os.recall_observation.v1": 1,
            "memory-os.recall_observation.v2": 1,
        }
        # The v1 row contributes its totals but no reason breakdown; that
        # asymmetry is exactly what the version counts warn the reader about.
        assert stats["suppressed_total"] == 2
        assert stats["suppressed_by_reason"]["near_duplicate"] == 1


class TestRecallObservationV2Reasons:
    """v2: the ledger must carry WHY things were suppressed, not just how many.

    v1 recorded 5022 suppressions on production with no reason breakdown, so
    suppression precision -- the one number a graduation decision needs -- was
    not computable from the ledger at all.
    """

    def test_reason_buckets_are_always_complete_so_zero_differs_from_absent(self, tmp_path):
        from plugins.memory.memory_os.recall_policy import SUPPRESSION_REASONS

        roots = FakeRoots(tmp_path)
        append_recall_observation(roots, _plan(
            suppressed=[
                {"reason": "near_duplicate"},
                {"reason": "near_duplicate"},
                {"reason": "budget_exceeded"},
            ],
            suppressed_count=3,
            ambiguous_pair_count=4,
        ))

        record = read_jsonl(recall_observation_path(roots))[-1]
        assert record["schema_version"] == "memory-os.recall_observation.v2"
        assert set(record["suppressed_by_reason"]) == set(SUPPRESSION_REASONS), (
            "a reason that did not occur must read as 0, never as a missing key"
        )
        assert record["suppressed_by_reason"]["near_duplicate"] == 2
        assert record["suppressed_by_reason"]["budget_exceeded"] == 1
        assert record["suppressed_by_reason"]["exact_duplicate"] == 0
        assert record["unknown_reason_count"] == 0
        assert record["ambiguous_pair_count"] == 4, (
            "computed by build_recall_plan since L4 shipped and persisted by nobody until v2"
        )

    def test_unregistered_reason_is_counted_not_dropped(self, tmp_path):
        """An unknown reason must be visible, not silently absorbed.

        Bucketing by a closed vocabulary risks losing anything outside it;
        the `unknown` counter is what turns that into a signal a reader can
        act on (and what the census test then chases down).
        """
        roots = FakeRoots(tmp_path)
        append_recall_observation(roots, _plan(
            suppressed=[
                {"reason": "near_duplicate"},
                {"reason": "reason_invented_by_a_future_producer"},
                {"not_a_mapping_row": True},
                "malformed-row",
            ],
            suppressed_count=4,
        ))

        record = read_jsonl(recall_observation_path(roots))[-1]
        assert record["suppressed_by_reason"]["near_duplicate"] == 1
        assert record["unknown_reason_count"] == 3
        total = sum(record["suppressed_by_reason"].values()) + record["unknown_reason_count"]
        assert total == record["suppressed_count"], (
            "every suppressed row must land in exactly one bucket"
        )

    def test_plan_produced_by_the_real_builder_round_trips_into_the_ledger(self, tmp_path):
        """End-to-end: the producer's reasons must survive into the ledger.

        Hand-built plan dicts would pass even if `build_recall_plan` renamed
        every reason, so this drives the real builder.
        """
        from plugins.memory.memory_os.recall_arbitration import build_recall_plan
        from plugins.memory.memory_os.recall_types import RecallObject, RecallType

        def _object(content: str, ref: str, score: float) -> RecallObject:
            return RecallObject(
                recall_type=RecallType.INDEXED_FTS.value,
                content=content,
                score=score,
                source_ref=ref,
                authority_class="indexed_derived",
            )

        plan = build_recall_plan(
            [
                _object("用户在书房安装了一个定时器用于夜间断电", "cjk-keep", 0.9),
                _object("用户在书房安装了一个定时器用于夜间断电吗", "cjk-drop", 0.4),
            ],
            budget_chars=4000,
        )
        roots = FakeRoots(tmp_path)
        assert append_recall_observation(roots, plan) is True

        record = read_jsonl(recall_observation_path(roots))[-1]
        assert record["suppressed_by_reason"]["near_duplicate"] == 1
        assert record["unknown_reason_count"] == 0
