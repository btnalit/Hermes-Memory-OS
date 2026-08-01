"""Test memory_os_index_sync drift check against real crystallized records.

The __canonical_counts function must count active crystallized records
the same way the index does (via _markdown_records + is_active_crystallized_frontmatter)
to avoid false drift warnings.
"""

from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest

from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
from plugins.memory.memory_os.crystallized import (
    CrystallizedCandidate,
    CrystallizedMemoryService,
)
from plugins.memory.memory_os.fixtures import build_event
from plugins.memory.memory_os.index import MemoryOSIndex
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.schema import EventEnvelope
from plugins.memory.memory_os.store import MemoryOSStore

pytestmark = pytest.mark.usefixtures("crystallized_test_write_authority")


def _load_sync_module():
    """Load memory_os_index_sync.py via importlib (same pattern as other script tests)."""
    path = Path(__file__).resolve().parents[2] / "scripts" / "memory_os_index_sync.py"
    spec = importlib.util.spec_from_file_location("memory_os_index_sync", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _service(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    store = MemoryOSStore(roots)
    store.initialize()
    return CrystallizedMemoryService(store)


def test_canonical_count_matches_index_count_when_1_active_record(tmp_path):
    """Phase-2 bug regression: canonical crystallized_records must be 1, not 2."""
    service = _service(tmp_path)
    event = EventEnvelope.from_dict(build_event(seed=21, profile="memoryos-test"))
    candidate = CrystallizedCandidate(
        candidate_id="cand-sync-drift-001",
        kind="moment",
        body="Drift test memory.",
        source_event_ids=[event.id],
        sensitivity="private",
        tags=["test", "drift"],
        bridge_state="owner_eligible",
    )
    decision = ApprovalDecision(
        candidate_id=candidate.candidate_id,
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="owner",
        reviewed_at="2026-05-20T08:00:00+00:00",
    )
    service.write_approved_record(
        candidate,
        decision,
        file_name="drift_test.md",
        now=datetime(2026, 5, 20, 8, 1, tzinfo=timezone.utc),
    )

    # Build index
    roots = service.store.roots
    store = service.store
    index = MemoryOSIndex(roots)
    index.try_rebuild_from_store(store)  # full rebuild from canonical

    # Index should see 1 active crystallized record
    idx_counts = index.counts()
    assert idx_counts["crystallized_records"] == 1, (
        f"Index should have 1 crystallized record, got {idx_counts}"
    )

    # canonical_counts must match (the bug was counting --- lines → 2)
    sync = _load_sync_module()
    canonical = sync._canonical_counts(store)  # noqa: SLF001
    assert canonical["crystallized_records"] == 1, (
        f"Canonical should have 1 crystallized record, got {canonical}"
        " — _canonical_counts must use _markdown_records + "
        "is_active_crystallized_frontmatter, not '---' line count"
    )

    # Drift must be empty for crystallized_records: drift_ok == True
    drifts = sync._drift_report(idx_counts, canonical)  # noqa: SLF001
    assert "crystallized_records" not in drifts, (
        f"crystallized_records drift should be 0, got: {drifts.get('crystallized_records')}"
        " — _canonical_counts must count active records, not --- lines"
    )


def test_canonical_count_excludes_revoked_records(tmp_path):
    """Revoked crystallized records (canonical_state=revoked)
    must not inflate the canonical count."""
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    store = MemoryOSStore(roots)
    store.initialize()

    # Write 1 active record to multi_status.md
    active_md = """---
id: cand-sync-drift-002-active
kind: moment
schema_version: 3
candidate_id: cand-sync-drift-002-active
approved_by: owner
approved_at: 2026-05-20T08:01:00+00:00
approval_purpose: approve_for_crystallized
source_event_ids:
  - evt-sync-drift-002-01
sensitivity: private
hindsight_indexed: false
tags:
  - test
canonical_state: active
---
Active drift test memory.
---
id: cand-sync-drift-002-revoked
kind: moment
schema_version: 3
candidate_id: cand-sync-drift-002-revoked
approved_by: owner
approved_at: 2026-05-20T08:02:00+00:00
approval_purpose: approve_for_crystallized
source_event_ids:
  - evt-sync-drift-002-02
sensitivity: private
hindsight_indexed: false
tags:
  - test
canonical_state: revoked
---
Revoked drift test memory.
---"""
    crystallized_root = roots.crystallized_root
    crystallized_root.mkdir(parents=True, exist_ok=True)
    (crystallized_root / "multi_status.md").write_text(active_md.lstrip(), encoding="utf-8")

    index = MemoryOSIndex(roots)
    index.try_rebuild_from_store(store)

    idx_counts = index.counts()
    assert idx_counts["crystallized_records"] == 1, (
        f"Index should count only the active record (canonical_state=active). Got {idx_counts}"
    )

    sync = _load_sync_module()
    canonical = sync._canonical_counts(store)  # noqa: SLF001

    assert canonical["crystallized_records"] == 1, (
        f"Canonical should count only the active record (1), got {canonical}"
        " — revoked records must be excluded via is_active_crystallized_frontmatter"
    )
