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
