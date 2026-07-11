"""Tests for V2-E clearance cycle orchestration (E4-E9).

Covers: rejudge queue, cycle API, initial receipt generation (E9),
and monitor stats.
"""

from __future__ import annotations

from pathlib import Path

import pytest


class FakeRoots:
    def __init__(self, tmp_path: Path) -> None:
        self.memory_os_root = tmp_path / "memory-os"
        self.memory_os_root.mkdir(parents=True, exist_ok=True)
        (self.memory_os_root / "system").mkdir(parents=True, exist_ok=True)
        self.crystallized_root = self.memory_os_root / "crystallized"
        self.crystallized_root.mkdir(parents=True, exist_ok=True)
        self.hermes_home = tmp_path
        self.profile = "default"


# ── E9: Initial receipt generation for never-judged provisionals ─────────


class TestInitialReceiptGeneration:
    """E9a: never-judged provisional records get their first clearance receipt."""

    def test_initial_receipt_generated_for_never_judged_provisional(
        self, tmp_path: Path,
    ) -> None:
        """A provisional record with no receipt gets one after cycle runs."""
        from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
        from plugins.memory.memory_os.clearance_cycle import run_clearance_cycle
        from plugins.memory.memory_os.clearance_receipts import (
            read_clearance_receipts,
        )
        from plugins.memory.memory_os.crystallized import (
            CrystallizedCandidate,
            CrystallizedMemoryService,
        )
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore

        store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="test"))
        store.initialize()
        service = CrystallizedMemoryService(store)
        candidate = CrystallizedCandidate(
            "cand_e9a", "fact", "A provisional fact for E9a.", ["evt_e9a"],
        )
        decision = ApprovalDecision(
            "cand_e9a", ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED, "owner",
            "2026-07-01T00:00:00Z", provisional=True,
            expires_at="2026-08-01T00:00:00Z",
        )
        service.write_approved_record(candidate, decision, file_name="owner_approved.md")

        # Verify no receipts exist yet
        receipts_before = read_clearance_receipts(store.roots)
        assert len(receipts_before) == 0

        # Run the cycle — should generate a first receipt for the provisional
        report = run_clearance_cycle(store, v2e_enabled=True)
        assert report["status"] == "ok"
        assert report["judged"] >= 1
        assert report["initial_never_judged_queued"] >= 1

        # Verify receipt was created and is active
        receipts_after = read_clearance_receipts(store.roots)
        assert len(receipts_after) >= 1

        from plugins.memory.memory_os.clearance_receipts import ClearanceReceipt
        # Find the receipt for our record
        prov_records = service.list_provisional_records()
        prov_id = str(prov_records[0]["id"])
        matching = [
            r for r in receipts_after
            if ClearanceReceipt.from_dict(r).record_id == prov_id
            and ClearanceReceipt.from_dict(r).is_active
        ]
        assert len(matching) == 1, (
            f"Expected 1 active receipt for {prov_id}, got {len(matching)}"
        )
        assert matching[0]["verdict"] == "clear"

    def test_initial_receipt_not_duplicated_on_next_cycle(
        self, tmp_path: Path,
    ) -> None:
        """E9 idempotency: once active receipt exists, never-judged isn't re-queued."""
        from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
        from plugins.memory.memory_os.clearance_cycle import run_clearance_cycle
        from plugins.memory.memory_os.clearance_receipts import (
            ClearanceReceipt,
            read_clearance_receipts,
        )
        from plugins.memory.memory_os.crystallized import (
            CrystallizedCandidate,
            CrystallizedMemoryService,
        )
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore

        store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="test"))
        store.initialize()
        service = CrystallizedMemoryService(store)
        candidate = CrystallizedCandidate(
            "cand_e9a2", "fact", "Idempotent provisional.", ["evt_e9a2"],
        )
        decision = ApprovalDecision(
            "cand_e9a2", ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED, "owner",
            "2026-07-01T00:00:00Z", provisional=True,
            expires_at="2026-08-01T00:00:00Z",
        )
        service.write_approved_record(candidate, decision, file_name="owner_approved.md")

        # First cycle — generates receipt
        report1 = run_clearance_cycle(store, v2e_enabled=True)
        assert report1["judged"] >= 1
        assert report1["initial_never_judged_queued"] >= 1

        # Second cycle — E9 idempotency: the provisional now has an active
        # receipt, so it must NOT re-enter the never-judged queue
        report2 = run_clearance_cycle(store, v2e_enabled=True)
        assert report2["initial_never_judged_queued"] == 0, (
            f"E9 idempotency failure: never-judged re-entered queue: "
            f"{report2['initial_never_judged_queued']}"
        )


class TestInitialAndRejudgeSharedBudget:
    """E9b: initial + rejudge share budget, oldest-first."""

    def test_initial_and_rejudge_entries_coexist_in_queue(
        self, tmp_path: Path,
    ) -> None:
        """E9b: initial entries and rejudge entries coexist, oldest-first, shared budget."""
        from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
        from plugins.memory.memory_os.clearance_cycle import run_clearance_cycle
        from plugins.memory.memory_os.clearance_receipts import (
            ClearanceReceipt,
            read_clearance_receipts,
            write_clearance_receipt,
        )
        from plugins.memory.memory_os.crystallized import (
            CrystallizedCandidate,
            CrystallizedMemoryService,
        )
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore

        store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="test"))
        store.initialize()
        service = CrystallizedMemoryService(store)

        # Create one provisional (will be never-judged → initial queue)
        candidate = CrystallizedCandidate(
            "cand_new", "fact", "Never-judged provisional.", ["evt_new"],
        )
        decision = ApprovalDecision(
            "cand_new", ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED, "owner",
            "2026-07-01T00:00:00Z", provisional=True,
            expires_at="2026-08-01T00:00:00Z",
        )
        service.write_approved_record(candidate, decision, file_name="owner_approved.md")

        # Write a pre-invalidated receipt with an OLDER entered_at for a
        # different record that doesn't actually exist in crystallized (it
        # will be in the rejudge queue via get_rejudge_queue, oldest-first)
        write_clearance_receipt(store.roots, ClearanceReceipt(
            receipt_id="clr_old_rejudge", record_id="rid_old_rejudge",
            content_hash="aa", verdict="clear", corpus_watermark=0,
            judge_version="v2e_heuristic", judged_at="2026-06-01T00:00:00Z",
            invalidated_at="2026-06-15T00:00:00Z", invalidated_by="test",
        ))

        # Run the cycle — both should be in queue, budget shared
        report = run_clearance_cycle(store, v2e_enabled=True)
        assert report["status"] == "ok"

        # The report should show queue had entries from both sources
        assert report["queue_depth"] >= 2, (
            f"Expected >= 2 in queue (1 rejudge + 1 initial), got {report['queue_depth']}"
        )
        # At least the never-judged provisional should have been judged
        assert report["judged"] >= 1


class TestClearanceCycleMonitorStats:
    """E8: monitor stats coverage."""

    def test_monitor_stats_includes_verdict_counts(self, tmp_path: Path) -> None:
        """clearance_monitor_stats returns correct verdict distribution."""
        from plugins.memory.memory_os.clearance_cycle import clearance_monitor_stats
        from plugins.memory.memory_os.clearance_receipts import (
            ClearanceReceipt,
            write_clearance_receipt,
        )
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore

        store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="test"))
        store.initialize()

        # Write receipts with different verdicts
        write_clearance_receipt(store.roots, ClearanceReceipt(
            receipt_id="clr_stat_1", record_id="rec_1", content_hash="h1",
            verdict="clear", corpus_watermark=0, judge_version="v1",
            judged_at="2026-07-11T00:00:00Z",
        ))
        write_clearance_receipt(store.roots, ClearanceReceipt(
            receipt_id="clr_stat_2", record_id="rec_2", content_hash="h2",
            verdict="conflict", conflict_refs=["rec_1"], corpus_watermark=1,
            judge_version="v1", judged_at="2026-07-11T00:00:00Z",
        ))
        write_clearance_receipt(store.roots, ClearanceReceipt(
            receipt_id="clr_stat_3", record_id="rec_3", content_hash="h3",
            verdict="unknown", corpus_watermark=2, judge_version="v1",
            judged_at="2026-07-11T00:00:00Z",
        ))

        stats = clearance_monitor_stats(store.roots)
        assert stats["clearance_receipts_total"] == 3
        assert stats["clearance_receipts_clear"] == 1
        assert stats["clearance_receipts_conflict"] == 1
        assert stats["clearance_receipts_unknown"] == 1
        assert stats["receipts_invalidated_count"] == 0
