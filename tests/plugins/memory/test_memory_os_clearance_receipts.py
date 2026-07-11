"""Tests for V2-E clearance receipt journal and corpus change events (E2).

Covers: ClearanceReceipt journal read/write, idempotency, snapshot derivation,
and corpus change event emission from crystallized write paths.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from plugins.memory.memory_os.clearance_receipts import (
    CLEARANCE_RECEIPT_SCHEMA_VERSION,
    CORPUS_CHANGE_EVENT_SCHEMA_VERSION,
    ClearanceReceipt,
    CorpusChangeEvent,
    append_corpus_change_event,
    clearance_receipts_path,
    clearance_receipt_snapshot_path,
    corpus_change_events_path,
    latest_corpus_watermark,
    read_clearance_receipt_snapshot,
    read_clearance_receipts,
    read_corpus_change_events,
    rebuild_clearance_receipt_snapshot,
    write_clearance_receipt,
)


class FakeRoots:
    def __init__(self, tmp_path: Path) -> None:
        self.memory_os_root = tmp_path / "memory-os"
        self.memory_os_root.mkdir(parents=True, exist_ok=True)
        (self.memory_os_root / "system").mkdir(parents=True, exist_ok=True)
        self.hermes_home = tmp_path
        self.profile = "default"


# ── Receipt journal ────────────────────────────────────────────────────────


class TestReceiptJournal:
    def test_write_and_read_receipt(self, tmp_path: Path) -> None:
        """Receipt is appended to journal and readable."""
        roots = FakeRoots(tmp_path)
        receipt = ClearanceReceipt(
            receipt_id="clr_test_001",
            record_id="prov_001",
            content_hash="abc123",
            verdict="clear",
            corpus_watermark=5,
            judge_version="v1",
            judged_at="2026-07-11T00:00:00Z",
        )
        result = write_clearance_receipt(roots, receipt)
        assert result["status"] == "ok"
        assert result["written"] is True

        records = read_clearance_receipts(roots)
        assert len(records) == 1
        assert records[0]["receipt_id"] == "clr_test_001"
        assert records[0]["verdict"] == "clear"
        assert records[0]["candidate_ref"]["record_id"] == "prov_001"

    def test_idempotent_write_suppressed(self, tmp_path: Path) -> None:
        """Same idempotency key → second write suppressed."""
        roots = FakeRoots(tmp_path)
        receipt = ClearanceReceipt(
            receipt_id="clr_idem_001",
            record_id="prov_X",
            content_hash="hash_XYZ",
            verdict="conflict",
            conflict_refs=["perm_A"],
            corpus_watermark=3,
            judge_version="v2",
            judged_at="2026-07-11T00:00:00Z",
        )
        r1 = write_clearance_receipt(roots, receipt)
        assert r1["written"] is True

        # Second write with same idempotency key
        r2 = write_clearance_receipt(roots, receipt)
        assert r2["written"] is False
        assert r2["status"] == "idempotent"
        assert r2["receipt_id"] == "clr_idem_001"

        # Only one record in journal
        assert len(read_clearance_receipts(roots)) == 1

    def test_different_watermark_produces_new_receipt(self, tmp_path: Path) -> None:
        """Different corpus_watermark (even with same content_hash + judge) → new receipt."""
        roots = FakeRoots(tmp_path)
        r1 = ClearanceReceipt(
            receipt_id="clr_wm_001", record_id="prov_W", content_hash="same_hash",
            verdict="clear", corpus_watermark=1, judge_version="v1",
            judged_at="2026-07-11T00:00:00Z",
        )
        r2 = ClearanceReceipt(
            receipt_id="clr_wm_002", record_id="prov_W", content_hash="same_hash",
            verdict="clear", corpus_watermark=2, judge_version="v1",
            judged_at="2026-07-12T00:00:00Z",
        )
        assert write_clearance_receipt(roots, r1)["written"] is True
        assert write_clearance_receipt(roots, r2)["written"] is True
        assert len(read_clearance_receipts(roots)) == 2

    def test_invalidated_receipt_does_not_block_new(self, tmp_path: Path) -> None:
        """Invalidated receipt → new receipt with same idempotency key can be written."""
        roots = FakeRoots(tmp_path)
        r1 = ClearanceReceipt(
            receipt_id="clr_inv_001", record_id="prov_I", content_hash="h",
            verdict="clear", corpus_watermark=1, judge_version="v1",
            judged_at="2026-07-11T00:00:00Z",
            invalidated_at="2026-07-12T00:00:00Z", invalidated_by="test",
        )
        write_clearance_receipt(roots, r1)
        # Same idempotency key but first is invalidated → new can be written
        r2 = ClearanceReceipt(
            receipt_id="clr_inv_002", record_id="prov_I", content_hash="h",
            verdict="conflict", conflict_refs=["perm_Z"],
            corpus_watermark=1, judge_version="v1",
            judged_at="2026-07-13T00:00:00Z",
        )
        # The idempotency check only blocks if existing active receipt exists
        result = write_clearance_receipt(roots, r2)
        assert result["written"] is True
        assert len(read_clearance_receipts(roots)) == 2

    def test_journal_path_is_correct(self, tmp_path: Path) -> None:
        roots = FakeRoots(tmp_path)
        assert clearance_receipts_path(roots).name == "clearance_receipts.jsonl"


# ── Receipt snapshot ───────────────────────────────────────────────────────


class TestReceiptSnapshot:
    def test_snapshot_from_empty_journal(self, tmp_path: Path) -> None:
        """Empty journal → snapshot with zero counts."""
        roots = FakeRoots(tmp_path)
        snapshot = rebuild_clearance_receipt_snapshot(roots)
        assert snapshot["total_receipts"] == 0
        assert snapshot["active_receipts"] == 0
        assert snapshot["latest_watermark"] == 0

    def test_snapshot_reflects_journal(self, tmp_path: Path) -> None:
        """Snapshot aggregates verdict counts and watermark."""
        roots = FakeRoots(tmp_path)
        write_clearance_receipt(roots, ClearanceReceipt(
            receipt_id="clr_s1", record_id="p1", content_hash="h1",
            verdict="clear", corpus_watermark=1, judge_version="v1",
            judged_at="2026-07-11T00:00:00Z",
        ))
        write_clearance_receipt(roots, ClearanceReceipt(
            receipt_id="clr_s2", record_id="p2", content_hash="h2",
            verdict="conflict", conflict_refs=["perm_X"], corpus_watermark=2,
            judge_version="v1", judged_at="2026-07-11T00:00:00Z",
        ))
        write_clearance_receipt(roots, ClearanceReceipt(
            receipt_id="clr_s3", record_id="p3", content_hash="h3",
            verdict="unknown", corpus_watermark=3, judge_version="v1",
            judged_at="2026-07-11T00:00:00Z",
        ))

        snapshot = rebuild_clearance_receipt_snapshot(roots)
        assert snapshot["total_receipts"] == 3
        assert snapshot["active_receipts"] == 3
        assert snapshot["verdict_distribution"] == {"clear": 1, "conflict": 1, "unknown": 1}
        assert snapshot["latest_watermark"] == 3

    def test_snapshot_excludes_invalidated_from_active(self, tmp_path: Path) -> None:
        """Invalidated receipts excluded from active count."""
        roots = FakeRoots(tmp_path)
        write_clearance_receipt(roots, ClearanceReceipt(
            receipt_id="clr_act", record_id="pA", content_hash="hA",
            verdict="clear", corpus_watermark=1, judge_version="v1",
            judged_at="2026-07-11T00:00:00Z",
        ))
        write_clearance_receipt(roots, ClearanceReceipt(
            receipt_id="clr_dead", record_id="pD", content_hash="hD",
            verdict="conflict", conflict_refs=["perm_Y"], corpus_watermark=2,
            judge_version="v1", judged_at="2026-07-11T00:00:00Z",
            invalidated_at="2026-07-12T00:00:00Z", invalidated_by="e3",
        ))
        snapshot = rebuild_clearance_receipt_snapshot(roots)
        assert snapshot["total_receipts"] == 2
        assert snapshot["active_receipts"] == 1

    def test_read_snapshot_roundtrip(self, tmp_path: Path) -> None:
        """Written snapshot is readable."""
        roots = FakeRoots(tmp_path)
        rebuild_clearance_receipt_snapshot(roots)
        snap = read_clearance_receipt_snapshot(roots)
        assert snap is not None
        assert snap["total_receipts"] == 0

    def test_missing_snapshot_returns_none(self, tmp_path: Path) -> None:
        roots = FakeRoots(tmp_path)
        assert read_clearance_receipt_snapshot(roots) is None


# ── ClearanceReceipt dataclass ─────────────────────────────────────────────


class TestClearanceReceiptDataclass:
    def test_roundtrip(self) -> None:
        receipt = ClearanceReceipt(
            receipt_id="clr_r1", record_id="prov_R", content_hash="hash_R",
            verdict="clear", conflict_refs=[], corpus_watermark=7,
            checked_entity_set=["ent_1", "ent_2"],
            judge_version="v3", judged_at="2026-07-11T00:00:00Z",
        )
        d = receipt.to_dict()
        r2 = ClearanceReceipt.from_dict(d)
        assert r2.receipt_id == receipt.receipt_id
        assert r2.verdict == "clear"
        assert r2.checked_entity_set == ["ent_1", "ent_2"]
        assert r2.is_active is True

    def test_idempotency_key_stability(self) -> None:
        """Same inputs → same idempotency key."""
        r1 = ClearanceReceipt(
            receipt_id="a", record_id="p", content_hash="H",
            verdict="clear", corpus_watermark=1, judge_version="j",
            judged_at="t1",
        )
        r2 = ClearanceReceipt(
            receipt_id="b", record_id="p", content_hash="H",
            verdict="conflict", corpus_watermark=1, judge_version="j",
            judged_at="t2",
        )
        assert r1.idempotency_key == r2.idempotency_key

    def test_idempotency_key_differs(self) -> None:
        """Different watermark → different key."""
        r1 = ClearanceReceipt(
            receipt_id="a", record_id="p", content_hash="H",
            verdict="clear", corpus_watermark=1, judge_version="j",
            judged_at="t1",
        )
        r2 = ClearanceReceipt(
            receipt_id="b", record_id="p", content_hash="H",
            verdict="clear", corpus_watermark=2, judge_version="j",
            judged_at="t2",
        )
        assert r1.idempotency_key != r2.idempotency_key

    def test_from_dict_handles_missing_fields(self) -> None:
        """Graceful defaults for missing fields."""
        r = ClearanceReceipt.from_dict({"receipt_id": "clr_min"})
        assert r.receipt_id == "clr_min"
        assert r.verdict == "unknown"
        assert r.content_hash == ""
        assert r.corpus_watermark == 0


# ── Corpus change events ───────────────────────────────────────────────────


class TestCorpusChangeEvents:
    def test_append_and_read_events(self, tmp_path: Path) -> None:
        """Events are appended and readable."""
        roots = FakeRoots(tmp_path)
        r1 = append_corpus_change_event(roots, "add", "perm_001")
        r2 = append_corpus_change_event(roots, "revoke", "perm_002")
        assert r1["event_id"] == 1
        assert r2["event_id"] == 2

        events = read_corpus_change_events(roots)
        assert len(events) == 2
        assert events[0]["change_type"] == "add"
        assert events[0]["record_id"] == "perm_001"
        assert events[1]["change_type"] == "revoke"

    def test_watermark_tracks_latest_event(self, tmp_path: Path) -> None:
        """latest_corpus_watermark returns highest event_id."""
        roots = FakeRoots(tmp_path)
        assert latest_corpus_watermark(roots) == 0
        append_corpus_change_event(roots, "add", "p1")
        assert latest_corpus_watermark(roots) == 1
        append_corpus_change_event(roots, "update", "p2")
        assert latest_corpus_watermark(roots) == 2

    def test_event_path_is_correct(self, tmp_path: Path) -> None:
        roots = FakeRoots(tmp_path)
        assert corpus_change_events_path(roots).name == "corpus_change_events.jsonl"

    def test_empty_events_watermark_zero(self, tmp_path: Path) -> None:
        roots = FakeRoots(tmp_path)
        assert latest_corpus_watermark(roots) == 0
        assert read_corpus_change_events(roots) == []


# ── Crystallized write hook integration ────────────────────────────────────


class TestCrystallizedCorpusHooks:
    """Verify that crystallized write paths emit corpus change events."""

    def test_write_approved_permanent_emits_add_event(self, tmp_path: Path) -> None:
        """write_approved_record for a permanent record emits 'add' event."""
        from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
        from plugins.memory.memory_os.crystallized import (
            CrystallizedCandidate,
            CrystallizedMemoryService,
        )
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore

        store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="test"))
        store.initialize()
        service = CrystallizedMemoryService(store)
        candidate = CrystallizedCandidate("cand_1", "fact", "A permanent fact.", ["evt_1"])
        decision = ApprovalDecision(
            "cand_1", ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED, "owner",
            "2026-06-01T00:00:00Z",
        )
        service.write_approved_record(candidate, decision, file_name="owner_approved.md")

        events = read_corpus_change_events(store.roots)
        add_events = [e for e in events if e["change_type"] == "add"]
        assert len(add_events) == 1

    def test_write_approved_provisional_emits_supersede_event(self, tmp_path: Path) -> None:
        """write_approved_record for a provisional record emits 'supersede' event."""
        from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
        from plugins.memory.memory_os.crystallized import (
            CrystallizedCandidate,
            CrystallizedMemoryService,
        )
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore

        store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="test"))
        store.initialize()
        service = CrystallizedMemoryService(store)
        candidate = CrystallizedCandidate("cand_2", "fact", "A provisional fact.", ["evt_2"])
        decision = ApprovalDecision(
            "cand_2", ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED, "owner",
            "2026-06-01T00:00:00Z", provisional=True, expires_at="2026-08-01T00:00:00Z",
        )
        service.write_approved_record(candidate, decision, file_name="owner_approved.md")

        events = read_corpus_change_events(store.roots)
        supersede_events = [e for e in events if e["change_type"] == "supersede"]
        assert len(supersede_events) == 1

    def test_revoke_emits_revoke_event(self, tmp_path: Path) -> None:
        """revoke_record emits 'revoke' event."""
        from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
        from plugins.memory.memory_os.crystallized import (
            CrystallizedCandidate,
            CrystallizedMemoryService,
        )
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore

        store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="test"))
        store.initialize()
        service = CrystallizedMemoryService(store)
        candidate = CrystallizedCandidate("cand_3", "fact", "To be revoked.", ["evt_3"])
        decision = ApprovalDecision(
            "cand_3", ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED, "owner",
            "2026-06-01T00:00:00Z",
        )
        service.write_approved_record(candidate, decision, file_name="owner_approved.md")
        record_id = service.read_records("owner_approved.md")[0].frontmatter["id"]
        service.revoke_record(record_id, revoked_by="owner", reason="test revoke")

        events = read_corpus_change_events(store.roots)
        revoke_events = [e for e in events if e["change_type"] == "revoke"]
        assert len(revoke_events) == 1
        assert revoke_events[0]["record_id"] == record_id
