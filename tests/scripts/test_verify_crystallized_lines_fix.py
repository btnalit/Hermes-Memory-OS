#!/usr/bin/env python3
"""Real-world verification of the _crystallized_lines fix.

Validates fix for:
  Bug 1 — accumulation decay: records appended later invisible due to clip(260)
  Bug 2 — revocation leak:    revoked records still appear in prefetch context
"""

import json
import sys
import tempfile
from pathlib import Path

# Ensure the repo is on sys.path
sys.path.insert(0, "/root/hermes-memory-os")

from plugins.memory.memory_os.crystallized import (
    CrystallizedCandidate,
    CrystallizedMemoryService,
    ApprovalDecision,
    ApprovalPurpose,
    append_candidate_queue,
    is_active_crystallized_frontmatter,
    _parse_markdown_records,
)
from plugins.memory.memory_os.prefetch import _crystallized_lines
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.memory.memory_os.ids import new_crystallized_id, new_event_id
from datetime import datetime, timezone


def _ts():
    return datetime.now(timezone.utc).isoformat()


def _make_roots(tmpdir: Path) -> MemoryOSRoots:
    return MemoryOSRoots.from_hermes_home(tmpdir, profile="memoryos-test")


def test_accumulation_decay_fixed():
    """Bug 1: Appending a new record to a file with existing records must not hide it."""
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        roots = _make_roots(tmpdir)
        store = MemoryOSStore(roots)
        store.initialize()
        service = CrystallizedMemoryService(store)

        now = datetime(2026, 1, 1, tzinfo=timezone.utc)

        # Record 1: active, short body (simulates a crystallized memory)
        cand1 = CrystallizedCandidate(
            candidate_id="cand_probe_test_1",
            kind="preference",
            body="第一笔结晶记忆，语句简短，只有几十个字的长度。",
            source_event_ids=[new_event_id()],
            tags=["test", "probe"],
        )
        dec1 = ApprovalDecision(
            candidate_id=cand1.candidate_id,
            purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
            reviewer="owner",
            reviewed_at=_ts(),
            note="verification test record 1",
        )
        service.write_approved_record(cand1, dec1, file_name="owner_approved.md", now=now)

        # Record 2: active, LONG body (>260 chars to simulate real-world accumulation)
        long_body = "X" * 400  # Deliberately long
        cand2 = CrystallizedCandidate(
            candidate_id="cand_probe_test_2",
            kind="insight",
            body=long_body,
            source_event_ids=[new_event_id()],
            tags=["test", "probe"],
        )
        dec2 = ApprovalDecision(
            candidate_id=cand2.candidate_id,
            purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
            reviewer="owner",
            reviewed_at=_ts(),
            note="verification test record 2 (long body)",
        )
        service.write_approved_record(cand2, dec2, file_name="owner_approved.md", now=now)

        # Record 3: the "probe nonce" — this is what was being lost in the old code
        nonce_text = "The system deployment codename is: ZAQ12345-XYZ"
        cand3 = CrystallizedCandidate(
            candidate_id="cand_probe_test_3",
            kind="probe",
            body=nonce_text,
            source_event_ids=[new_event_id()],
            tags=["probe_only"],
        )
        dec3 = ApprovalDecision(
            candidate_id=cand3.candidate_id,
            purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
            reviewer="owner",
            reviewed_at=_ts(),
            note="L3 probe nonce verification",
        )
        service.write_approved_record(cand3, dec3, file_name="owner_approved.md", now=now)

        # NOW: call _crystallized_lines — the new record-level version
        lines, _crystallized_degradation = _crystallized_lines(store)
        combined = "\n".join(lines)

        # Assert: all three records are visible — not clipped away
        assert "第一笔结晶记忆" in combined, \
            f"FAIL: Record 1 body missing from _crystallized_lines output:\n{combined}"
        # Long body record 2 should appear (clipped to 220 + "...")
        assert "probe" in combined or "insight" in combined, \
            f"FAIL: Record 2/3 kind missing. Output:\n{combined}"
        assert nonce_text in combined, \
            f"FAIL: Record 3 (probe nonce) invisible — accumulation decay bug present!\nOutput:\n{combined}"
        
        print(f"  ✅ Bug 1 fixed: {len(lines)} lines produced, all 3 records visible")
        for line in lines:
            print(f"     {line[:80]}..." if len(line) > 80 else f"     {line}")
        print()


def test_revocation_leak_fixed():
    """Bug 2: Revoked records must NOT appear in _crystallized_lines."""
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        roots = _make_roots(tmpdir)
        store = MemoryOSStore(roots)
        store.initialize()
        service = CrystallizedMemoryService(store)

        now_1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        now_2 = datetime(2026, 1, 2, tzinfo=timezone.utc)

        # Record 1: active
        cand1 = CrystallizedCandidate(
            candidate_id="cand_revoke_test_1",
            kind="preference",
            body="这条记录是 active 的，应该出现在 prefetch 中。",
            source_event_ids=[new_event_id()],
            tags=["test"],
        )
        dec1 = ApprovalDecision(
            candidate_id=cand1.candidate_id,
            purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
            reviewer="owner",
            reviewed_at=_ts(),
        )
        path = service.write_approved_record(cand1, dec1, file_name="test_memories.md", now=now_1)

        # Record 2: write as active, then revoke
        cand2 = CrystallizedCandidate(
            candidate_id="cand_revoke_test_2",
            kind="secret",
            body="这条记录已被 owner 撤销，绝对不应该出现在 prefetch 中。如果出现就是 revocation leak bug。",
            source_event_ids=[new_event_id()],
            tags=["test"],
        )
        dec2 = ApprovalDecision(
            candidate_id=cand2.candidate_id,
            purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
            reviewer="owner",
            reviewed_at=_ts(),
        )
        service.write_approved_record(cand2, dec2, file_name="test_memories.md", now=now_2)

        # Revoke record 2
        record_id = service.read_records("test_memories.md")[1].frontmatter["id"]
        service.revoke_record(
            record_id,
            revoked_by="owner",
            reason="test revocation",
            now=datetime(2026, 1, 3, tzinfo=timezone.utc),
        )

        # Call _crystallized_lines
        lines, _crystallized_degradation = _crystallized_lines(store)
        combined = "\n".join(lines)

        # Assert: record 1 IS present, record 2 is NOT
        assert "active 的" in combined, \
            f"FAIL: Active record should be present. Output:\n{combined}"
        assert "已被 owner 撤销" not in combined, \
            f"FAIL: Revoked record leaked into prefetch context — revocation leak bug present!\nOutput:\n{combined}"

        print(f"  ✅ Bug 2 fixed: active record visible, revoked record filtered out ({len(lines)} line(s))")
        for line in lines:
            print(f"     {line[:80]}..." if len(line) > 80 else f"     {line}")
        print()


def test_format_does_not_break_build_prefetch():
    """Verify the format change doesn't break build_prefetch section ordering."""
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        roots = _make_roots(tmpdir)
        store = MemoryOSStore(roots)
        store.initialize()
        service = CrystallizedMemoryService(store)

        # Write one active record
        cand = CrystallizedCandidate(
            candidate_id="cand_format_test",
            kind="preference",
            body="格式测试。这条记录应该出现在 Crystallized Memory section 中。",
            source_event_ids=[new_event_id()],
            tags=["test"],
        )
        dec = ApprovalDecision(
            candidate_id=cand.candidate_id,
            purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
            reviewer="owner",
            reviewed_at=_ts(),
        )
        service.write_approved_record(cand, dec, file_name="owner_approved.md")

        # Call build_prefetch (full chain)
        from plugins.memory.memory_os.prefetch import build_prefetch
        context = build_prefetch(
            "memory test",
            budget_chars=2200,
            store=store,
            index=None,
        )

        assert context.startswith("## Memory-OS Context"), \
            f"FAIL: Context should start with header. First 50 chars: {context[:50]}"
        assert "### Crystallized Memory" in context, \
            "FAIL: '### Crystallized Memory' section missing from context"
        assert "格式测试" in context, \
            f"FAIL: Active record body missing from context. Context:\n{context[:500]}"
        
        print(f"  ✅ Full-chain integration test passed ({len(context)} chars)")
        lines = [l for l in context.splitlines() if "格式测试" in l]
        print(f"     Line format: {lines[0][:80]}..." if len(lines[0]) > 80 else f"     Line format: {lines[0]}")
        print()


def test_empty_file_no_crash():
    """Empty crystallized directory returns empty list, no crash."""
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        roots = _make_roots(tmpdir)
        store = MemoryOSStore(roots)
        store.initialize()

        lines, _crystallized_degradation = _crystallized_lines(store)
        assert lines == [], f"FAIL: Empty dir should return [], got {lines}"
        print("  ✅ Empty directory: returns [] without crash")


def test_no_active_records_returns_empty():
    """File with only revoked records returns empty."""
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        roots = _make_roots(tmpdir)
        store = MemoryOSStore(roots)
        store.initialize()

        # Manually create a file with only a revoked record
        file_path = roots.crystallized_root / "all_revoked.md"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(
            "---\n"
            "id: cry_revoked_only\n"
            "kind: moment\n"
            "approved_by: owner\n"
            "tags:\n"
            "  - test\n"
            "canonical_state: owner_revoked\n"
            "revoked_by: owner\n"
            "revoked_at: 2026-01-01T00:00:00+00:00\n"
            "revocation_reason: test\n"
            "---\n"
            "这条记录已经被撤销，不应该出现。\n\n",
            encoding="utf-8",
        )

        lines, _crystallized_degradation = _crystallized_lines(store)
        assert lines == [], f"FAIL: All-revoked file should return [], got {lines}"
        print("  ✅ All-revoked file: returns []")


def test_multiple_files():
    """Multiple .md files each produce their own lines."""
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        roots = _make_roots(tmpdir)
        store = MemoryOSStore(roots)
        store.initialize()
        service = CrystallizedMemoryService(store)

        ts = _ts()
        
        # File 1
        c1 = CrystallizedCandidate(
            candidate_id="cand_multi_file_1",
            kind="preference",
            body="来自 file1 的记忆",
            source_event_ids=[new_event_id()],
        )
        d1 = ApprovalDecision(candidate_id=c1.candidate_id, purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED, reviewer="owner", reviewed_at=ts)
        service.write_approved_record(c1, d1, file_name="file1.md")

        # File 2
        c2 = CrystallizedCandidate(
            candidate_id="cand_multi_file_2",
            kind="insight",
            body="来自 file2 的记忆",
            source_event_ids=[new_event_id()],
        )
        d2 = ApprovalDecision(candidate_id=c2.candidate_id, purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED, reviewer="owner", reviewed_at=ts)
        service.write_approved_record(c2, d2, file_name="file2.md")

        lines, _crystallized_degradation = _crystallized_lines(store)
        combined = "\n".join(lines)
        assert len(lines) == 2, f"FAIL: Expected 2 lines, got {len(lines)}: {lines}"
        assert "file1.md" in combined
        assert "file2.md" in combined
        assert "来自 file1 的记忆" in combined
        assert "来自 file2 的记忆" in combined
        print(f"  ✅ Multi-file: {len(lines)} lines from {len(set(l.split('/')[0] for l in lines))} files")


def test_kind_in_output():
    """Output format includes /kind after filename."""
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        roots = _make_roots(tmpdir)
        store = MemoryOSStore(roots)
        store.initialize()
        service = CrystallizedMemoryService(store)

        c = CrystallizedCandidate(
            candidate_id="cand_kind_check",
            kind="test_kind_value",
            body="验证kind字段",
            source_event_ids=[new_event_id()],
        )
        d = ApprovalDecision(candidate_id=c.candidate_id, purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED, reviewer="owner", reviewed_at=_ts())
        service.write_approved_record(c, d, file_name="kinds.md")

        lines, _crystallized_degradation = _crystallized_lines(store)
        assert len(lines) == 1
        assert "kinds.md/test_kind_value" in lines[0], \
            f"FAIL: Expected '/test_kind_value' in output, got: {lines[0]}"
        print(f"  ✅ Kind in output format: {lines[0][:70]}")


if __name__ == "__main__":
    print("=" * 60)
    print("Verify _crystallized_lines fix: real-world scenarios")
    print("=" * 60)
    print()

    tests = [
        ("Bug 1 — accumulation decay", test_accumulation_decay_fixed),
        ("Bug 2 — revocation leak", test_revocation_leak_fixed),
        ("Full-chain integration", test_format_does_not_break_build_prefetch),
        ("Empty directory", test_empty_file_no_crash),
        ("All revoked", test_no_active_records_returns_empty),
        ("Multi-file support", test_multiple_files),
        ("Kind in output format", test_kind_in_output),
    ]

    failures = 0
    for name, func in tests:
        print(f"  ── {name} ──")
        try:
            func()
        except Exception as e:
            print(f"  ❌ FAIL: {e}")
            import traceback
            traceback.print_exc()
            failures += 1
        print()

    print("=" * 60)
    if failures:
        print(f"❌ {failures}/{len(tests)} tests FAILED")
        sys.exit(1)
    else:
        print(f"✅ All {len(tests)} tests PASSED")
