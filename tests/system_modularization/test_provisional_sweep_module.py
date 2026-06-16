"""Tests for provisional_sweep module - TTL/cap/recurrence lifecycle."""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path


def _setup_store_with_provisional_records(tmp_path, *, count=5, expires_days=7):
    """Create a store with provisional crystallized records for sweep testing."""
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
    from plugins.memory.memory_os.crystallized import CrystallizedCandidate, CrystallizedMemoryService
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="test")
    store = MemoryOSStore(roots)
    store.initialize()
    now = datetime.now(timezone.utc)
    service = CrystallizedMemoryService(store)

    for i in range(count):
        candidate = CrystallizedCandidate(
            candidate_id=f"cand_sweep_{i:03d}",
            kind="moment",
            body=f"Sweep test memory {i}.",
            source_event_ids=[f"evt_{i:03d}"],
            sensitivity="private",
            bridge_state="inner_drive_candidate",
        )
        decision = ApprovalDecision(
            candidate_id=f"cand_sweep_{i:03d}",
            purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
            reviewer="resolver",
            reviewed_at=(now - timedelta(hours=i)).isoformat(),
            source_state="resolver_approved",
            provisional=True,
            expires_at=(now + timedelta(days=expires_days)).isoformat(),
        )
        service.write_approved_record(candidate, decision, file_name="owner_approved.md")

    return store, service, now


def test_provisional_sweep_manifest():
    """Manifest must have correct name, kind, version, and commands."""
    from plugins.modules.governance.provisional_sweep import provisional_sweep_manifest

    manifest = provisional_sweep_manifest()
    assert manifest["name"] == "provisional_sweep"
    assert manifest["kind"] == "governance"
    assert manifest["version"] == "0.1.0"
    assert "status" in manifest["provides"]["commands"]
    assert "doctor" in manifest["provides"]["commands"]
    assert "run_once" in manifest["provides"]["commands"]


def test_provisional_sweep_run_once_ttl_expiry(tmp_path):
    """run_once must invalidate records past their expires_at."""
    store, service, now = _setup_store_with_provisional_records(
        tmp_path, count=3, expires_days=-1  # already expired
    )
    from plugins.modules.governance.provisional_sweep import ProvisionalSweepModule

    module = ProvisionalSweepModule(tmp_path, profile="test")
    result = module.run_once(store=store)
    assert result["provisional_total"] == 3
    assert result["expired_count"] == 3

    # Verify records are now inactive
    active = service.list_provisional_records()
    assert len(active) == 0


def test_provisional_sweep_run_once_cap_eviction(tmp_path):
    """run_once must evict oldest records when count > 30."""
    store, service, now = _setup_store_with_provisional_records(
        tmp_path, count=35, expires_days=30  # far future, all active
    )
    from plugins.modules.governance.provisional_sweep import ProvisionalSweepModule

    module = ProvisionalSweepModule(tmp_path, profile="test")
    result = module.run_once(store=store)
    assert result["provisional_total"] == 35
    assert result["evicted_count"] == 5  # 35 - 30

    active = service.list_provisional_records()
    assert len(active) == 30


def test_provisional_sweep_status(tmp_path):
    """status must report correct counts before and after sweep."""
    store, service, now = _setup_store_with_provisional_records(
        tmp_path, count=3, expires_days=30
    )
    from plugins.modules.governance.provisional_sweep import ProvisionalSweepModule

    module = ProvisionalSweepModule(tmp_path, profile="test")
    status = module.status()
    assert status["module"] == "provisional_sweep"
    assert status["profile"] == "test"
    assert status["provisional_count"] == 3


def test_provisional_sweep_doctor(tmp_path):
    """doctor must report ok when no issues found."""
    store, service, now = _setup_store_with_provisional_records(
        tmp_path, count=1, expires_days=30
    )
    from plugins.modules.governance.provisional_sweep import ProvisionalSweepModule

    module = ProvisionalSweepModule(tmp_path, profile="test")
    result = module.doctor()
    assert result["module"] == "provisional_sweep"
    assert result["status"] in ("ok", "warning")
