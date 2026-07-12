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


class TestAntiRubberStamp:
    """R4: anti-rubber-stamp poison — permanent test matrix.

    These tests verify that the clearance judge can NEVER be a constant
    function.  Their absence was the root cause that allowed the heuristic
    stub (always-``clear``) to survive into production.
    """

    def test_known_conflict_pair_must_return_conflict_not_clear(
        self, tmp_path: Path,
    ) -> None:
        """A pair of known-contradictory records MUST produce ``conflict``.

        Counterfactual: if this test were absent, a constant-judge stub
        that always returns ``clear`` would pass all existing tests.
        """
        from unittest.mock import patch

        from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
        from plugins.memory.memory_os.clearance_cycle import (
            _judge_against_permanents,
            _collect_entities_from_record,
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

        # Create a provisional record asserting "X is A"
        provisional = CrystallizedCandidate(
            "cand_conflict_a", "fact",
            "The project status is complete and ready for production deployment.",
            ["evt_conflict"],
        )
        prov_decision = ApprovalDecision(
            "cand_conflict_a", ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED, "owner",
            "2026-07-01T00:00:00Z", provisional=True,
            expires_at="2026-08-01T00:00:00Z",
        )
        service.write_approved_record(provisional, prov_decision, file_name="prov.md")

        # Create a permanent record asserting "X is NOT A" (contradiction)
        permanent = CrystallizedCandidate(
            "cand_conflict_b", "fact",
            "The project status is blocked and not ready for production deployment.",
            ["evt_conflict2"],
        )
        perm_decision = ApprovalDecision(
            "cand_conflict_b", ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED, "owner",
            "2026-06-15T00:00:00Z", provisional=False,
        )
        service.write_approved_record(permanent, perm_decision, file_name="perm.md")

        prov_records = service.list_provisional_records()
        assert len(prov_records) == 1
        prov_record = service.find_record(str(prov_records[0]["id"]))
        assert prov_record is not None

        perm_records_list = [
            {"id": str(perm_decision.candidate_id), "body": permanent.body,
             "frontmatter": {"id": perm_decision.candidate_id, "provisional": False}}
        ]

        # Mock the LLM to return contradictory claims
        mock_llm_response = (
            '{"claim_a": {"subject": "project status", "predicate": "is", '
            '"object": "complete and ready", "confidence": 0.9}, '
            '"claim_b": {"subject": "project status", "predicate": "is", '
            '"object": "blocked and not ready", "confidence": 0.9}}'
        )

        # Build a mock pair so the judge has something to evaluate
        mock_pairs = [{"permanent": perm_records_list[0], "similarity": 0.9}]

        with patch(
            "plugins.memory.memory_os.clearance_cycle._pair_with_permanents",
            return_value=mock_pairs,
        ), patch(
            "plugins.memory.memory_os.low_clue_recall._call_hermes_runtime_model",
            return_value=mock_llm_response,
        ), patch(
            "plugins.memory.memory_os.clearance_cycle._check_llm_available",
            return_value=True,
        ), patch(
            "plugins.memory.memory_os.low_clue_recall._resolve_hermes_default_runtime",
            return_value={"ok": True},
        ):
            verdict, conflict_refs, checked_entity_set, invalidation_mode = (
                _judge_against_permanents(
                    store,
                    str(prov_records[0]["id"]),
                    prov_record.body,
                    prov_record.frontmatter,
                    perm_records_list,
                    max_pairs=5,
                )
            )

        # The critical assertion: must NOT be "clear"
        assert verdict in {"conflict", "unknown"}, (
            f"ANTI-RUBBER-STAMP FAILURE: known-conflict pair returned verdict={verdict!r}. "
            f"Constitution requires 'conflict' (or 'unknown' if LLM unavailable). "
            f"Constant 'clear' is forbidden."
        )
        # With mocked LLM returning contradictory claims, we expect "conflict"
        assert verdict == "conflict", (
            f"Expected 'conflict' with mocked contradictory claims, got {verdict!r}"
        )
        assert len(conflict_refs) > 0, (
            "conflict_refs must be populated when verdict is 'conflict'"
        )

    def test_known_unrelated_pair_must_return_clear(
        self, tmp_path: Path,
    ) -> None:
        """A pair of known-unrelated records MUST produce ``clear``.

        The dual of the conflict test: the judge must be able to return
        ``clear`` when records genuinely don't conflict — but only after
        actual evaluation, never as a constant.
        """
        from unittest.mock import patch

        from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
        from plugins.memory.memory_os.clearance_cycle import (
            _judge_against_permanents,
            _collect_entities_from_record,
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

        # Two records about completely different topics
        provisional = CrystallizedCandidate(
            "cand_unrel_a", "weather",
            "The temperature in Beijing today is 25 degrees Celsius.",
            ["evt_unrel"],
        )
        prov_decision = ApprovalDecision(
            "cand_unrel_a", ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED, "owner",
            "2026-07-01T00:00:00Z", provisional=True,
            expires_at="2026-08-01T00:00:00Z",
        )
        service.write_approved_record(provisional, prov_decision, file_name="prov2.md")

        permanent2 = CrystallizedCandidate(
            "cand_unrel_b", "sports",
            "The local football team won their match yesterday 3-1.",
            ["evt_unrel2"],
        )
        perm_decision2 = ApprovalDecision(
            "cand_unrel_b", ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED, "owner",
            "2026-06-15T00:00:00Z", provisional=False,
        )
        service.write_approved_record(permanent2, perm_decision2, file_name="perm2.md")

        prov_records = service.list_provisional_records()
        prov_record = service.find_record(str(prov_records[0]["id"]))
        assert prov_record is not None

        perm_records_list = [
            {"id": str(perm_decision2.candidate_id), "body": permanent2.body,
             "frontmatter": {"id": perm_decision2.candidate_id, "provisional": False}}
        ]

        # Mock the LLM to return unrelated claims (different subjects)
        mock_llm_response = (
            '{"claim_a": {"subject": "temperature", "predicate": "is", '
            '"object": "25 degrees", "confidence": 0.9}, '
            '"claim_b": {"subject": "football team", "predicate": "won", '
            '"object": "3-1", "confidence": 0.9}}'
        )

        # Build a mock pair so the judge has something to evaluate
        mock_pairs2 = [{"permanent": perm_records_list[0], "similarity": 0.82}]

        with patch(
            "plugins.memory.memory_os.clearance_cycle._pair_with_permanents",
            return_value=mock_pairs2,
        ), patch(
            "plugins.memory.memory_os.low_clue_recall._call_hermes_runtime_model",
            return_value=mock_llm_response,
        ), patch(
            "plugins.memory.memory_os.clearance_cycle._check_llm_available",
            return_value=True,
        ), patch(
            "plugins.memory.memory_os.low_clue_recall._resolve_hermes_default_runtime",
            return_value={"ok": True},
        ):
            verdict, conflict_refs, checked_entity_set, invalidation_mode = (
                _judge_against_permanents(
                    store,
                    str(prov_records[0]["id"]),
                    prov_record.body,
                    prov_record.frontmatter,
                    perm_records_list,
                    max_pairs=5,
                )
            )

        assert verdict == "clear", (
            f"ANTI-RUBBER-STAMP FAILURE: known-unrelated pair returned verdict={verdict!r}. "
            f"Constitution requires 'clear' when no contradiction is detected."
        )

    def test_empty_permanents_returns_clear(
        self, tmp_path: Path,
    ) -> None:
        """Empty permanent corpus MUST return ``clear`` (empty corpus clause).

        This is the ONLY path where a constant verdict is valid — the
        constitution explicitly allows it: with no permanent records, there
        is nothing to conflict against.
        """
        from plugins.memory.memory_os.clearance_cycle import (
            _judge_against_permanents,
        )
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore

        store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="test"))
        store.initialize()

        verdict, conflict_refs, checked_entity_set, invalidation_mode = (
            _judge_against_permanents(
                store,
                "rec_empty_corpus",
                "Any body text.",
                {"id": "rec_empty_corpus", "tags": ["test"]},
                [],  # empty permanent corpus
                max_pairs=5,
            )
        )

        assert verdict == "clear", (
            f"Empty corpus clause: expected 'clear', got {verdict!r}"
        )
        assert conflict_refs == []
        # Entity set should be collected from the provisional's own frontmatter
        assert isinstance(checked_entity_set, list)

    def test_llm_unavailable_returns_unknown_fail_closed(
        self, tmp_path: Path,
    ) -> None:
        """LLM unavailable MUST return ``unknown`` (fail-closed).

        This is the constitutional requirement: when the judge cannot
        evaluate, the receipt must be ``unknown``, which blocks automatic
        promotion.  Never fabricate ``clear``.
        """
        from plugins.memory.memory_os.clearance_cycle import (
            _judge_against_permanents,
        )
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore

        store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="test"))
        store.initialize()

        perm_records_list = [
            {"id": "perm_1", "body": "Some permanent record body.",
             "frontmatter": {"id": "perm_1", "provisional": False}}
        ]

        # _judge_against_permanents checks LLM availability internally;
        # without an actual LLM, it should return "unknown"
        verdict, conflict_refs, checked_entity_set, invalidation_mode = (
            _judge_against_permanents(
                store,
                "rec_no_llm",
                "Any provisional body text.",
                {"id": "rec_no_llm", "tags": ["test"]},
                perm_records_list,
                max_pairs=5,
            )
        )

        assert verdict == "unknown", (
            f"Fail-closed failure: LLM unavailable but returned {verdict!r}. "
            f"Constitution requires 'unknown'."
        )


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
