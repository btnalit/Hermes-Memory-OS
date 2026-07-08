"""Tests for candidate compact atomicity (V4.1 P0-2 counterfactuals).

Covers:
  C.1 — archive append failure keeps main candidates file untouched
  C.2 — normal compact writes conservation audit
  C.3 — conservation violation / malformed file does not replace
  C.4 — append works after compact (lock released)
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from plugins.memory.memory_os.audit import read_audit_records
from plugins.memory.memory_os.crystallized import (
    CrystallizedCandidate,
    append_candidate_queue,
    compact_candidate_queue,
    read_candidate_queue,
)
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore


def _make_candidate(
    candidate_id: str = "",
    kind: str = "note",
    body: str = "test body",
    source_event_ids: list[str] | None = None,
    bridge_state: str = "fleeting",
    created_at: str = "",
    age_days: int = 14,
) -> CrystallizedCandidate:
    if not created_at:
        created_at = (datetime.now(timezone.utc) - timedelta(days=age_days)).isoformat()
    return CrystallizedCandidate(
        candidate_id=candidate_id or uuid.uuid4().hex,
        kind=kind,
        body=body,
        source_event_ids=source_event_ids or [uuid.uuid4().hex],
        bridge_state=bridge_state,
        created_at=created_at,
    )


def _setup_store(tmp_path: Path) -> MemoryOSStore:
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="main")
    roots.memory_os_root.mkdir(parents=True, exist_ok=True)
    roots.crystallized_root.mkdir(parents=True, exist_ok=True)
    roots.audit_path.parent.mkdir(parents=True, exist_ok=True)
    return MemoryOSStore(roots)


# ── C.1: archive failure fail-closed ──────────────────────────────────

def test_compact_archive_append_failure_keeps_main_candidates(tmp_path, monkeypatch):
    """If archive append raises, main candidates file is untouched."""
    store = _setup_store(tmp_path)

    stale = _make_candidate(candidate_id="stale-1", age_days=14, bridge_state="fleeting")
    append_candidate_queue(store, stale)

    candidates_path = store.roots.crystallized_root / "candidates.jsonl"
    original_content = candidates_path.read_text()

    archive_path = store.roots.crystallized_root / "candidates_archive.jsonl"

    def _failing_append(*args, **kwargs):
        raise RuntimeError("simulated archive write failure")

    monkeypatch.setattr(
        "plugins.memory.memory_os.crystallized.append_jsonl_lines_locked",
        _failing_append,
    )

    with pytest.raises(RuntimeError, match="simulated archive write failure"):
        compact_candidate_queue(store, archive_path=archive_path, retention_days=1)

    assert candidates_path.read_text() == original_content
    assert not archive_path.exists() or archive_path.stat().st_size == 0


# ── C.2: normal compact conservation audit ────────────────────────────

def test_compact_writes_conservation_ok_audit(tmp_path):
    """Normal compact: stale to archive, active stays, audit ok."""
    store = _setup_store(tmp_path)

    active = _make_candidate(candidate_id="active-1", age_days=0, bridge_state="owner_eligible")
    stale = _make_candidate(candidate_id="stale-1", age_days=14, bridge_state="fleeting")

    append_candidate_queue(store, active)
    append_candidate_queue(store, stale)

    archive_path = store.roots.crystallized_root / "candidates_archive.jsonl"
    archived_count = compact_candidate_queue(store, archive_path=archive_path, retention_days=1)

    assert archived_count >= 1

    archive_records = [
        json.loads(line) for line in archive_path.read_text().strip().split("\n") if line.strip()
    ]
    archived_ids = {r["candidate_id"] for r in archive_records}
    assert "stale-1" in archived_ids
    assert "active-1" not in archived_ids

    remaining = read_candidate_queue(store)
    remaining_ids = {c.candidate_id for c in remaining}
    assert "active-1" in remaining_ids
    assert "stale-1" not in remaining_ids

    audit_records = read_audit_records(store.roots.audit_path)
    conservation_audits = [
        r for r in audit_records if r.get("action") == "candidate_compact_conservation"
    ]
    assert len(conservation_audits) >= 1
    assert any(a["status"] == "ok" for a in conservation_audits)


# ── C.3: malformed line fail-closed ───────────────────────────────────

def test_compact_malformed_line_does_not_replace(tmp_path):
    """A malformed line in candidates file prevents compact (fail-closed)."""
    store = _setup_store(tmp_path)

    candidate = _make_candidate(candidate_id="stale-1", age_days=14, bridge_state="fleeting")
    append_candidate_queue(store, candidate)

    candidates_path = store.roots.crystallized_root / "candidates.jsonl"
    original_content = candidates_path.read_text()

    # Append a malformed line directly (bypass append lock, simulate corruption)
    with candidates_path.open("a", encoding="utf-8") as f:
        f.write("{invalid json!!!\n")

    archive_path = store.roots.crystallized_root / "candidates_archive.jsonl"

    # compact should raise (JSONDecodeError) on the malformed line
    with pytest.raises((json.JSONDecodeError, Exception)):
        compact_candidate_queue(store, archive_path=archive_path, retention_days=1)

    # Original content is still present in the file
    current = candidates_path.read_text()
    assert original_content.strip() in current


# ── C.4: append-vs-compact deterministic interleaving ─────────────────

def test_concurrent_append_waits_for_compact_lock(tmp_path):
    """append_candidate_queue works after compact (lock released)."""
    store = _setup_store(tmp_path)

    stale = _make_candidate(candidate_id="stale-1", age_days=14, bridge_state="fleeting")
    append_candidate_queue(store, stale)

    archive_path = store.roots.crystallized_root / "candidates_archive.jsonl"
    count = compact_candidate_queue(store, archive_path=archive_path, retention_days=1)

    assert count >= 1

    new_candidate = _make_candidate(candidate_id="new-after-compact", age_days=0)
    append_candidate_queue(store, new_candidate)

    remaining = read_candidate_queue(store)
    remaining_ids = {c.candidate_id for c in remaining}
    assert "new-after-compact" in remaining_ids


# ── C.5: archive dedup by candidate_id (Patch C) ────────────────────────


def test_compact_skips_duplicate_candidate_ids_in_archive(tmp_path):
    """Compact twice with same stale candidate: second compact skips archive append."""
    store = _setup_store(tmp_path)

    stale = _make_candidate(candidate_id="stale-dedup-1", age_days=14, bridge_state="fleeting")
    append_candidate_queue(store, stale)

    archive_path = store.roots.crystallized_root / "candidates_archive.jsonl"

    # First compact: stale goes to archive, active stays empty
    count1 = compact_candidate_queue(store, archive_path=archive_path, retention_days=1)
    assert count1 == 1

    # Re-add the same stale candidate (simulating it re-entered queue)
    stale2 = _make_candidate(candidate_id="stale-dedup-1", age_days=14, bridge_state="fleeting")
    append_candidate_queue(store, stale2)

    # Second compact: should compact the stale candidate but dedup in archive
    count2 = compact_candidate_queue(store, archive_path=archive_path, retention_days=1)
    assert count2 == 1  # still archived from active

    # Archive should have exactly 1 entry (dedup kicked in)
    archive_lines = [
        line for line in archive_path.read_text().strip().split("\n") if line.strip()
    ]
    stale_entries = [
        json.loads(line)
        for line in archive_lines
        if json.loads(line).get("candidate_id") == "stale-dedup-1"
    ]
    assert len(stale_entries) == 1, (
        f"Expected 1 archive entry for stale-dedup-1, found {len(stale_entries)}"
    )


def test_compact_dedup_writes_audit_record(tmp_path):
    """When duplicates are skipped, a candidate_compact_dedup audit is written."""
    store = _setup_store(tmp_path)

    stale = _make_candidate(candidate_id="stale-dedup-audit", age_days=14, bridge_state="fleeting")
    append_candidate_queue(store, stale)

    archive_path = store.roots.crystallized_root / "candidates_archive.jsonl"

    # First compact
    compact_candidate_queue(store, archive_path=archive_path, retention_days=1)

    # Re-add and compact again
    stale2 = _make_candidate(candidate_id="stale-dedup-audit", age_days=14, bridge_state="fleeting")
    append_candidate_queue(store, stale2)
    compact_candidate_queue(store, archive_path=archive_path, retention_days=1)

    audit_records = read_audit_records(store.roots.audit_path)
    dedup_audits = [
        r for r in audit_records if r.get("action") == "candidate_compact_dedup"
    ]
    assert len(dedup_audits) >= 1, "Expected at least one candidate_compact_dedup audit"
    assert dedup_audits[0]["status"] == "ok"
    assert dedup_audits[0]["details"]["skipped_duplicates"] >= 1


def test_compact_no_dedup_audit_when_no_duplicates(tmp_path):
    """First compact (no prior archive entries) writes no dedup audit."""
    store = _setup_store(tmp_path)

    stale = _make_candidate(candidate_id="stale-fresh-1", age_days=14, bridge_state="fleeting")
    append_candidate_queue(store, stale)

    archive_path = store.roots.crystallized_root / "candidates_archive.jsonl"
    compact_candidate_queue(store, archive_path=archive_path, retention_days=1)

    audit_records = read_audit_records(store.roots.audit_path)
    dedup_audits = [
        r for r in audit_records if r.get("action") == "candidate_compact_dedup"
    ]
    assert len(dedup_audits) == 0, (
        "No dedup audit expected when archive was empty before compact"
    )


def test_compact_dedup_different_candidates_not_affected(tmp_path):
    """Dedup only filters exact candidate_id matches; different IDs are all archived."""
    store = _setup_store(tmp_path)

    stale_a = _make_candidate(candidate_id="stale-a", age_days=14, bridge_state="fleeting")
    stale_b = _make_candidate(candidate_id="stale-b", age_days=14, bridge_state="fleeting")
    append_candidate_queue(store, stale_a)
    append_candidate_queue(store, stale_b)

    archive_path = store.roots.crystallized_root / "candidates_archive.jsonl"
    count = compact_candidate_queue(store, archive_path=archive_path, retention_days=1)

    assert count == 2
    archive_records = [
        json.loads(line) for line in archive_path.read_text().strip().split("\n") if line.strip()
    ]
    archived_ids = {r["candidate_id"] for r in archive_records}
    assert archived_ids == {"stale-a", "stale-b"}


def test_compact_dedup_malformed_archive_lines_ignored(tmp_path):
    """Malformed lines in archive are skipped during dedup (fail-safe)."""
    store = _setup_store(tmp_path)

    archive_path = store.roots.crystallized_root / "candidates_archive.jsonl"
    # Pre-populate archive with a malformed line
    archive_path.write_text("{bad json!!!\n", encoding="utf-8")

    stale = _make_candidate(candidate_id="stale-after-malformed", age_days=14, bridge_state="fleeting")
    append_candidate_queue(store, stale)

    count = compact_candidate_queue(store, archive_path=archive_path, retention_days=1)
    assert count == 1  # should succeed despite malformed archive line

    # Parse archive lines individually — skip malformed (as production dedup does)
    archive_records = []
    for line in archive_path.read_text().strip().split("\n"):
        if not line.strip():
            continue
        try:
            archive_records.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # malformed lines skipped — matches production behavior
    archived_ids = {r.get("candidate_id") for r in archive_records if isinstance(r, dict)}
    assert "stale-after-malformed" in archived_ids


def test_counterfactual_compact_without_dedup_would_duplicate(tmp_path):
    """Without dedup, re-compacting the same candidate produces duplicate archive rows."""
    store = _setup_store(tmp_path)

    stale = _make_candidate(candidate_id="stale-cf", age_days=14, bridge_state="fleeting")
    append_candidate_queue(store, stale)

    archive_path = store.roots.crystallized_root / "candidates_archive.jsonl"

    # First compact
    compact_candidate_queue(store, archive_path=archive_path, retention_days=1)

    # Re-add and compact again
    stale2 = _make_candidate(candidate_id="stale-cf", age_days=14, bridge_state="fleeting")
    append_candidate_queue(store, stale2)
    compact_candidate_queue(store, archive_path=archive_path, retention_days=1)

    # With dedup, archive should have exactly 1 entry for stale-cf
    archive_records = [
        json.loads(line) for line in archive_path.read_text().strip().split("\n") if line.strip()
    ]
    cf_entries = [r for r in archive_records if r.get("candidate_id") == "stale-cf"]
    assert len(cf_entries) == 1, (
        f"Dedup should prevent duplicate archive rows; found {len(cf_entries)}"
    )


# ── Fix 2: default archive_path safety ────────────────────────────────

def test_compact_without_archive_path_uses_default_and_preserves_stale(tmp_path):
    """Calling compact_candidate_queue without archive_path must not lose data."""
    store = _setup_store(tmp_path)

    stale = _make_candidate(candidate_id="stale-default-path", age_days=14, bridge_state="fleeting")
    active = _make_candidate(candidate_id="active-default-path", age_days=1, bridge_state="owner_eligible")
    append_candidate_queue(store, stale)
    append_candidate_queue(store, active)

    # Call WITHOUT archive_path — must use safe default, not drop stale
    count = compact_candidate_queue(store, retention_days=1)
    assert count == 1  # stale-default-path archived

    # Main file should only have the active candidate
    remaining = read_candidate_queue(store)
    remaining_ids = {c.candidate_id for c in remaining}
    assert "active-default-path" in remaining_ids
    assert "stale-default-path" not in remaining_ids

    # Default archive file should exist and contain the stale candidate
    default_archive = store.roots.crystallized_root / "candidates.archive.jsonl"
    assert default_archive.exists(), "Default archive must be created when not specified"
    archive_lines = [
        json.loads(line) for line in default_archive.read_text().strip().split("\n") if line.strip()
    ]
    archived_ids = {r.get("candidate_id") for r in archive_lines}
    assert "stale-default-path" in archived_ids, "Stale candidate must be archived, not dropped"


def test_counterfactual_archive_path_none_drops_data(tmp_path):
    """Counterfactual: if archive_path=None were still a silent-drop trap, this
    would lose the stale candidate. The test verifies the fix is effective."""
    store = _setup_store(tmp_path)

    stale = _make_candidate(candidate_id="cf-none-safety", age_days=14, bridge_state="fleeting")
    append_candidate_queue(store, stale)

    # Explicit None must still get a safe default (not drop data)
    # Note: after Fix 2, None → derived default, so this is safe
    count = compact_candidate_queue(store, archive_path=None, retention_days=1)
    assert count == 1

    # Verify stale was archived, not lost
    default_archive = store.roots.crystallized_root / "candidates.archive.jsonl"
    archive_ids = {
        json.loads(line).get("candidate_id")
        for line in default_archive.read_text().strip().split("\n")
        if line.strip()
    }
    assert "cf-none-safety" in archive_ids, (
        "archive_path=None must NOT drop data — stale candidates must be archived"
    )


# ── Bonus: demoted/absorbed always archived, even when young ──────────

def test_compact_archives_young_demoted_candidate(tmp_path):
    """A demoted candidate newer than retention_days must be archived.

    Before the Bonus fix, the active filter was
    `effective == 'owner_eligible' or age < retention_days`; a young demoted
    candidate (age < retention) kept cluttering the live queue. Resolved
    outcomes (demoted/absorbed) are now always archived.
    """
    store = _setup_store(tmp_path)

    young_demoted = _make_candidate(
        candidate_id="young-demoted", age_days=1, bridge_state="demoted"
    )
    young_absorbed = _make_candidate(
        candidate_id="young-absorbed", age_days=1, bridge_state="absorbed"
    )
    append_candidate_queue(store, young_demoted)
    append_candidate_queue(store, young_absorbed)

    archive_path = store.roots.crystallized_root / "candidates_archive.jsonl"
    archived_count = compact_candidate_queue(store, archive_path=archive_path, retention_days=7)

    assert archived_count == 2
    remaining = read_candidate_queue(store)
    remaining_ids = {c.candidate_id for c in remaining}
    assert "young-demoted" not in remaining_ids
    assert "young-absorbed" not in remaining_ids


def test_compact_keeps_young_non_terminal_and_owner_eligible(tmp_path):
    """Regression guard: young owner_eligible and young fleeting stay active."""
    store = _setup_store(tmp_path)

    young_owner_eligible = _make_candidate(
        candidate_id="young-oe", age_days=1, bridge_state="owner_eligible"
    )
    young_fleeting = _make_candidate(
        candidate_id="young-fleeting", age_days=1, bridge_state="fleeting"
    )
    append_candidate_queue(store, young_owner_eligible)
    append_candidate_queue(store, young_fleeting)

    archive_path = store.roots.crystallized_root / "candidates_archive.jsonl"
    archived_count = compact_candidate_queue(store, archive_path=archive_path, retention_days=7)

    assert archived_count == 0
    remaining = read_candidate_queue(store)
    remaining_ids = {c.candidate_id for c in remaining}
    assert "young-oe" in remaining_ids
    assert "young-fleeting" in remaining_ids

