"""Tests for V2-E clearance cycle orchestration (E4-E9).

Covers: rejudge queue, cycle API, initial receipt generation (E9),
and monitor stats.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.usefixtures("crystallized_test_write_authority")


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
            verdict, conflict_refs, checked_entity_set, invalidation_mode, _unk_reason = (
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
            verdict, conflict_refs, checked_entity_set, invalidation_mode, _unk_reason = (
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

        verdict, conflict_refs, checked_entity_set, invalidation_mode, _unk_reason = (
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
        verdict, conflict_refs, checked_entity_set, invalidation_mode, _unk_reason = (
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


    def test_unindexed_candidate_plus_nonempty_corpus_must_return_unknown(
        self, tmp_path: Path,
    ) -> None:
        """Unindexed candidate + non-empty corpus → unknown (not clear).

        Counterfactual: without this test, a candidate with no index entries
        could fall through to the "empty corpus → clear" clause if the
        pairing logic returned an empty list AND the permanent list appeared
        empty to an accidental code path.  The distinction between "no
        permanents exist" and "permanents exist but can't be paired" must
        be explicit.
        """
        from plugins.memory.memory_os.clearance_cycle import (
            _judge_against_permanents,
        )
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore

        store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="test"))
        store.initialize()

        perm_records = [
            {"id": "perm_exists", "body": "Permanent record body text.",
             "frontmatter": {"id": "perm_exists", "provisional": False}}
        ]

        # No embeddings, no entity_index for this provisional —
        # _pair_with_permanents will return [].

        # NOTE: The conditional in _judge_against_permanents first checks
        # `if not permanent_records: return clear`.  Since we pass a
        # non-empty permanent list, it MUST NOT take that branch.
        # It then tries pairing, gets [], and returns unknown.
        # This test locks that ordering — the empty-corpus clause is
        # NEVER reached when permanents exist, even if pairing fails.

        verdict, conflict_refs, checked_entity_set, invalidation_mode, unknown_reason = (
            _judge_against_permanents(
                store,
                "rec_unindexed",
                "Any provisional body.",
                {"id": "rec_unindexed"},
                perm_records,
                max_pairs=5,
            )
        )

        assert verdict == "unknown", (
            f"UNINDEXED-CORPUS FAILURE: unindexed candidate with non-empty "
            f"corpus returned verdict={verdict!r}. Must be 'unknown', not 'clear'. "
            f"The empty-corpus clause must not trigger when permanents exist."
        )
        assert unknown_reason in ("candidate_unindexed", "judge_unavailable"), (
            f"Expected infra or judge unknown_reason, got {unknown_reason!r}"
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


# ── Error observability (silent-failure fix) ────────────────────────────


class TestRunClearanceCycleErrorObservability:
    """run_clearance_cycle must never report status='ok' after a total
    per-item judge failure, and per-item error_records must be full
    schema-conformant error_record dicts (not raw ad-hoc dicts).
    """

    def test_run_clearance_cycle_empty_batch_stays_ok(self, tmp_path: Path) -> None:
        """No queue items at all — status must remain 'ok' (nothing to fail)."""
        from plugins.memory.memory_os.clearance_cycle import run_clearance_cycle
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore

        store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="test"))
        store.initialize()

        report = run_clearance_cycle(store, v2e_enabled=True)
        assert report["status"] == "ok"
        assert report["budget_used"] == 0
        assert report["error_records"] == []

    def test_run_clearance_cycle_total_batch_failure_flips_status_to_error(
        self, tmp_path: Path,
    ) -> None:
        """Counterfactual for Defect 2.

        Before the fix, run_clearance_cycle initialized report["status"] to
        "ok" and never re-evaluated it after the per-item try/except loop,
        so a cycle where EVERY item in the rejudge batch raised still
        reported "ok" — and memory_os_clearance_cycle_helper.py maps
        status=="ok" straight to cron exit code 0. The per-item except
        handler also appended a raw dict (record_id/error_code/
        error_summary) instead of a schema-conformant error_record. This
        test asserts both are fixed: status flips to "error" on total
        failure, and the error_record carries the full canonical schema.
        """
        from unittest.mock import patch

        from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
        from plugins.memory.memory_os.clearance_cycle import run_clearance_cycle
        from plugins.memory.memory_os.crystallized import (
            CrystallizedCandidate,
            CrystallizedMemoryService,
        )
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore

        store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="test"))
        store.initialize()
        service = CrystallizedMemoryService(store)

        # One never-judged provisional -> exactly one item in the batch.
        candidate = CrystallizedCandidate(
            "cand_total_fail", "fact", "A provisional fact.", ["evt_total_fail"],
        )
        decision = ApprovalDecision(
            "cand_total_fail", ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED, "owner",
            "2026-07-01T00:00:00Z", provisional=True,
            expires_at="2026-08-01T00:00:00Z",
        )
        service.write_approved_record(candidate, decision, file_name="prov_total_fail.md")

        # A permanent record is required so the real judge branch
        # (_judge_against_permanents) is invoked instead of the
        # empty-corpus "always clear" shortcut.
        perm_candidate = CrystallizedCandidate(
            "cand_total_fail_perm", "fact", "An unrelated permanent fact.", ["evt_perm"],
        )
        perm_decision = ApprovalDecision(
            "cand_total_fail_perm", ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED, "owner",
            "2026-06-01T00:00:00Z", provisional=False,
        )
        service.write_approved_record(perm_candidate, perm_decision, file_name="perm_total_fail.md")

        # Crystallized records get their own auto-generated frontmatter
        # "id" (not the candidate_id) — that generated id is what
        # run_clearance_cycle uses as record_id.
        prov_records = service.list_provisional_records()
        assert len(prov_records) == 1
        real_record_id = str(prov_records[0]["id"])

        with patch(
            "plugins.memory.memory_os.clearance_cycle._judge_against_permanents",
            side_effect=RuntimeError("judge unavailable"),
        ):
            report = run_clearance_cycle(store, v2e_enabled=True)

        assert report["judged"] == 0
        assert report["budget_used"] == 1
        assert len(report["error_records"]) == 1
        assert report["status"] == "error", (
            "every item in the batch errored — status must not report 'ok'"
        )
        error_record = report["error_records"][0]
        assert error_record["schema_version"] == "memory-os.error_record.v0"
        assert error_record["component"] == "clearance_cycle"
        assert error_record["operation"] == "run_clearance_cycle_judge_item"
        assert error_record["error_code"] == "RuntimeError"
        assert error_record["severity"] == "error"
        assert error_record["recoverable"] is True
        assert error_record["details"]["record_id"] == real_record_id

    def test_run_clearance_cycle_partial_batch_failure_keeps_status_ok(
        self, tmp_path: Path,
    ) -> None:
        """One bad record among several must not flip the cron exit code.

        memory_os_clearance_cycle_helper.py maps status=="ok" to exit 0 —
        a single flaky judge call is expected/recoverable noise (the record
        stays unjudged and is retried next cycle), so it must not fail the
        whole cron run. Only a *total* batch failure should.
        """
        from unittest.mock import patch

        from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
        from plugins.memory.memory_os.clearance_cycle import run_clearance_cycle
        from plugins.memory.memory_os.crystallized import (
            CrystallizedCandidate,
            CrystallizedMemoryService,
        )
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore

        store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="test"))
        store.initialize()
        service = CrystallizedMemoryService(store)

        fail_id = "cand_partial_fail"
        ok_id = "cand_partial_ok"
        for cid, entered_at in ((fail_id, "2026-07-01T00:00:00Z"), (ok_id, "2026-07-02T00:00:00Z")):
            candidate = CrystallizedCandidate(cid, "fact", f"Provisional {cid}.", [f"evt_{cid}"])
            decision = ApprovalDecision(
                cid, ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED, "owner",
                entered_at, provisional=True, expires_at="2026-08-01T00:00:00Z",
            )
            service.write_approved_record(candidate, decision, file_name=f"{cid}.md")

        perm_candidate = CrystallizedCandidate(
            "cand_partial_perm", "fact", "An unrelated permanent fact.", ["evt_perm2"],
        )
        perm_decision = ApprovalDecision(
            "cand_partial_perm", ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED, "owner",
            "2026-06-01T00:00:00Z", provisional=False,
        )
        service.write_approved_record(perm_candidate, perm_decision, file_name="perm_partial.md")

        # Fail one item by patching the receipt write, NOT the judge.
        # run_clearance_cycle only calls _judge_against_permanents in its
        # `else` branch; when the permanent corpus is empty it takes the
        # "empty corpus clause" branch and never calls the judge at all.
        # A judge-level patch therefore silently never fires, every item
        # succeeds, and the test asserts nothing. write_clearance_receipt
        # is reached on BOTH branches, inside the same try, immediately
        # before `report["judged"] += 1` — so it fails exactly one item.
        from plugins.memory.memory_os.clearance_receipts import (
            write_clearance_receipt as _real_write_clearance_receipt,
        )

        # The batch item's record_id is the GENERATED crystallized record id
        # (`cry_<timestamp>_<hash>`) assigned by write_approved_record — NOT
        # the candidate id. Matching on the candidate id would never fire, so
        # fail the first receipt write and remember which record it was.
        failed_record_ids: list[str] = []

        def _flaky_receipt_write(roots, receipt):
            if not failed_record_ids:
                failed_record_ids.append(receipt.record_id)
                raise RuntimeError("receipt store unavailable")
            return _real_write_clearance_receipt(roots, receipt)

        with patch(
            "plugins.memory.memory_os.clearance_cycle.write_clearance_receipt",
            side_effect=_flaky_receipt_write,
        ):
            report = run_clearance_cycle(store, v2e_enabled=True)

        # Two provisional records enter the batch; exactly one was induced
        # to fail, so the other must still have been judged successfully.
        assert len(failed_record_ids) == 1, "expected exactly one induced failure"
        assert report["judged"] == 1
        assert len(report["error_records"]) == 1
        assert report["error_records"][0]["details"]["record_id"] == failed_record_ids[0]
        assert report["status"] == "ok", (
            "a single per-item failure among a larger batch must not flip status"
        )


class TestSweepUnavailableOpenProposalsOnFlagFlip:
    """Defect 2 coverage for sweep_unavailable_open_proposals_on_flag_flip.

    Also covers a functional bug found in the same call while fixing the
    error-record schema: the call passed append_terminal(detail=...), but
    ProposalLedger.append_terminal() has no `detail` parameter (confirmed —
    no other call site in the repo passes it), so the sweep TypeError'd on
    every single eligible proposal, unconditionally. That is fixed alongside
    the error-record/status fix since it lives in the same function.
    """

    def _make_eligible_proposal(self, store: Any, seed: str) -> str:
        from plugins.memory.memory_os.permanent_promotion import PermanentPromotionService

        service = PermanentPromotionService(store, v2e_enabled=False)
        proposal, created = service.proposals.create_or_get(
            target_id=f"target_{seed}",
            candidate_id=f"cand_{seed}",
            body=f"body for {seed}",
            channel="cli",
            origin="owner_initiated",
            clearance={"status": "unavailable", "reason_code": "test"},
        )
        assert created is True
        assert proposal["status"] == "open"
        return str(proposal["proposal_id"])

    def test_sweep_revokes_eligible_open_proposals_real_path(self, tmp_path: Path) -> None:
        """End-to-end, no mocking: proves the append_terminal(detail=...)
        TypeError bug is fixed and the sweep now actually revokes proposals.
        """
        from plugins.memory.memory_os.clearance_cycle import (
            sweep_unavailable_open_proposals_on_flag_flip,
        )
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore

        store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="test"))
        store.initialize()
        proposal_id = self._make_eligible_proposal(store, "sweep_real")

        result = sweep_unavailable_open_proposals_on_flag_flip(store)

        assert result["status"] == "ok"
        assert result["error_records"] == []
        assert result["swept_count"] == 1
        assert proposal_id in result["swept_proposal_ids"]

    def test_sweep_total_failure_flips_status_to_error(self, tmp_path: Path) -> None:
        """Counterfactual for Defect 2 (second call site).

        Before the fix this always returned status="ok" (initialized once,
        never re-evaluated) with raw (proposal_id, error_code)-only dicts
        instead of schema-conformant error_records — even when every
        eligible proposal failed to sweep.
        """
        from unittest.mock import patch

        from plugins.memory.memory_os.clearance_cycle import (
            sweep_unavailable_open_proposals_on_flag_flip,
        )
        from plugins.memory.memory_os.permanent_promotion import ProposalLedger
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore

        store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="test"))
        store.initialize()
        self._make_eligible_proposal(store, "sweep_total_fail")

        with patch.object(
            ProposalLedger, "append_terminal",
            side_effect=RuntimeError("ledger unavailable"),
        ):
            result = sweep_unavailable_open_proposals_on_flag_flip(store)

        assert result["swept_count"] == 0
        assert len(result["error_records"]) == 1
        assert result["status"] == "error"
        error_record = result["error_records"][0]
        assert error_record["schema_version"] == "memory-os.error_record.v0"
        assert error_record["component"] == "clearance_cycle"
        assert error_record["operation"] == "sweep_unavailable_open_proposals_on_flag_flip"
        assert error_record["severity"] == "error"
        assert error_record["recoverable"] is True
        assert "proposal_id" in error_record["details"]

    def test_sweep_partial_failure_keeps_status_ok(self, tmp_path: Path) -> None:
        """One proposal failing to sweep is recoverable noise (retried on
        the next flag-flip pass) and must not fail the whole sweep result.
        """
        from unittest.mock import patch

        from plugins.memory.memory_os.clearance_cycle import (
            sweep_unavailable_open_proposals_on_flag_flip,
        )
        from plugins.memory.memory_os.permanent_promotion import ProposalLedger
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore

        store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="test"))
        store.initialize()
        fail_id = self._make_eligible_proposal(store, "sweep_partial_fail")
        ok_id = self._make_eligible_proposal(store, "sweep_partial_ok")

        real_append_terminal = ProposalLedger.append_terminal

        def _flaky_append_terminal(self, proposal_id, status, **kwargs):
            if proposal_id == fail_id:
                raise RuntimeError("ledger unavailable")
            return real_append_terminal(self, proposal_id, status, **kwargs)

        with patch.object(ProposalLedger, "append_terminal", _flaky_append_terminal):
            result = sweep_unavailable_open_proposals_on_flag_flip(store)

        assert result["swept_count"] == 1
        assert ok_id in result["swept_proposal_ids"]
        assert len(result["error_records"]) == 1
        assert result["error_records"][0]["details"]["proposal_id"] == fail_id
        assert result["status"] == "ok", (
            "a single per-proposal failure must not flip status when others swept fine"
        )


def test_dead_judge_returning_empty_for_every_pair_fails_closed(tmp_path: Path) -> None:
    """Backlog 14 (completion is not output): _call_hermes_runtime_model
    reports most failures as "" (27.5% measured on fact_judge). With per-pair
    skips alone, a judge whose every call comes back empty falls through every
    pair and returns "clear" -- clearing a provisional record on the strength
    of a judge that never judged, the constant verdict the constitution
    forbids.

    Counterfactual: without the pairs_evaluated guard this returns "clear";
    with it, "unknown"/"judge_unavailable" (fail-closed, same as the
    availability-probe path).
    """
    from unittest.mock import patch

    from plugins.memory.memory_os.clearance_cycle import _judge_against_permanents
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="test"))
    store.initialize()

    perm_records_list = [
        {"id": "perm_dead_judge", "body": "The sky is blue.",
         "frontmatter": {"id": "perm_dead_judge", "provisional": False}},
    ]
    mock_pairs = [{"permanent": perm_records_list[0], "similarity": 0.9}]

    with patch(
        "plugins.memory.memory_os.clearance_cycle._pair_with_permanents",
        return_value=mock_pairs,
    ), patch(
        "plugins.memory.memory_os.low_clue_recall._call_hermes_runtime_model",
        return_value="",
    ), patch(
        "plugins.memory.memory_os.clearance_cycle._check_llm_available",
        return_value=True,
    ), patch(
        "plugins.memory.memory_os.low_clue_recall._resolve_hermes_default_runtime",
        return_value={"ok": True},
    ):
        verdict, conflict_refs, _entities, _mode, unknown_reason = (
            _judge_against_permanents(
                store, "cand_dead_judge", "The sky is green.", {},
                perm_records_list, max_pairs=5,
            )
        )

    assert verdict == "unknown", (
        f"a judge that never judged must fail closed, got {verdict!r}"
    )
    assert unknown_reason == "judge_unavailable"
    assert conflict_refs == []

    # The dual: one real (parseable) judgment among the pairs keeps "clear"
    # reachable -- the guard must only catch the zero-evaluations case.
    responses = iter([
        "",
        '{"claim_a": {"subject": "sky", "predicate": "color", "object": "green", '
        '"confidence": 0.2}, "claim_b": {"subject": "sky", "predicate": "color", '
        '"object": "blue", "confidence": 0.2}}',
    ])
    two_pairs = [
        {"permanent": perm_records_list[0], "similarity": 0.9},
        {"permanent": perm_records_list[0], "similarity": 0.8},
    ]
    with patch(
        "plugins.memory.memory_os.clearance_cycle._pair_with_permanents",
        return_value=two_pairs,
    ), patch(
        "plugins.memory.memory_os.low_clue_recall._call_hermes_runtime_model",
        side_effect=lambda prompt, config: next(responses),
    ), patch(
        "plugins.memory.memory_os.clearance_cycle._check_llm_available",
        return_value=True,
    ), patch(
        "plugins.memory.memory_os.low_clue_recall._resolve_hermes_default_runtime",
        return_value={"ok": True},
    ):
        verdict, _refs, _entities, _mode, unknown_reason = (
            _judge_against_permanents(
                store, "cand_partial_judge", "The sky is green.", {},
                perm_records_list, max_pairs=5,
            )
        )
    assert verdict == "clear"
    assert unknown_reason == ""
