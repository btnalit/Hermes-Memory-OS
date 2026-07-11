"""Tests for V2-A exposure rollup lane (A3)."""

from __future__ import annotations

from pathlib import Path

import pytest


class TestExposureRollupCycle:
    """A3: exposure rollup with conservation math and idempotency."""

    def test_rollup_idempotent_same_window(self, tmp_path: Path) -> None:
        """Same window re-run produces skipped result (idempotent)."""
        from plugins.memory.memory_os.exposure_rollup import run_exposure_rollup_cycle
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore

        store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="test"))
        store.initialize()

        # First run with no memory_sources — should skip (empty window)
        report1 = run_exposure_rollup_cycle(store)
        assert report1["status"] == "ok"
        assert report1["skipped"] is True, "Empty memory_sources should skip"

        # Second run — should also skip (watermark unchanged)
        report2 = run_exposure_rollup_cycle(store)
        assert report2["skipped"] is True, "Idempotent re-run should skip"

    def test_rollup_with_memory_source_records(self, tmp_path: Path) -> None:
        """Rollup processes memory_sources records and produces conservation."""
        from plugins.memory.memory_os.exposure_rollup import run_exposure_rollup_cycle
        from plugins.memory.memory_os.memory_sources import (
            append_memory_source_record,
        )
        from plugins.memory.memory_os.roots import MemoryOSRoots

        # Use MemoryOSRoots directly to write memory_sources records
        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="test")
        roots.memory_os_root.mkdir(parents=True, exist_ok=True)
        (roots.memory_os_root / "system").mkdir(parents=True, exist_ok=True)
        (roots.memory_os_root / "crystallized").mkdir(parents=True, exist_ok=True)

        # Write a memory_sources record with selected source_ids
        record = {
            "schema_version": "memory-os.memory_sources.v0",
            "record_id": "msrc_test_001",
            "created_at": "2026-07-11T10:00:00Z",
            "profile": "test",
            "route": "default",
            "selected": [
                {
                    "heading": "Crystallized Memory",
                    "source_class": "crystallized",
                    "source_ids": ["crystallized:rec_001", "crystallized:rec_002"],
                    "chars": 100,
                    "score": 0.9,
                    "reason_codes": ["fts5_hit"],
                },
                {
                    "heading": "Crystallized Memory",
                    "source_class": "crystallized",
                    "source_ids": ["crystallized:rec_001"],
                    "chars": 50,
                    "score": 0.7,
                    "reason_codes": ["vector_hit"],
                },
            ],
            "dropped": [
                {
                    "heading": "Crystallized Memory",
                    "source_class": "crystallized",
                    "source_ids": ["crystallized:rec_003"],
                    "count": 1,
                    "chars": 30,
                    "score": 0.3,
                    "reason_codes": ["budget"],
                },
                {
                    "heading": "Crystallized Memory",
                    "source_class": "crystallized",
                    "source_ids": ["crystallized:rec_004"],
                    "count": 1,
                    "chars": 25,
                    "score": 0.1,
                    "reason_codes": ["rank"],
                },
            ],
        }
        append_memory_source_record(roots, record)

        # Create a minimal store
        from plugins.memory.memory_os.store import MemoryOSStore
        store = MemoryOSStore(roots)
        store.initialize()

        report = run_exposure_rollup_cycle(store)
        assert report["status"] == "ok"
        assert report["skipped"] is False
        assert report["selected"] == 2, f"Expected 2 selected, got {report}"
        assert report["dropped_by_budget"] == 1
        assert report["dropped_by_rank"] == 1
        assert report["eligible"] == 4
        assert report["conservation_passes"] is True

    def test_rollup_conservation_math(self, tmp_path: Path) -> None:
        """eligible == selected + dropped_by_budget + dropped_by_rank."""
        from plugins.memory.memory_os.exposure_rollup import run_exposure_rollup_cycle
        from plugins.memory.memory_os.memory_sources import append_memory_source_record
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore

        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="test")
        roots.memory_os_root.mkdir(parents=True, exist_ok=True)
        (roots.memory_os_root / "system").mkdir(parents=True, exist_ok=True)
        (roots.memory_os_root / "crystallized").mkdir(parents=True, exist_ok=True)

        # Mix of selected, budget-dropped, rank-dropped — same record_id in
        # multiple lanes should be deduped (selected wins over budget over rank)
        record = {
            "schema_version": "memory-os.memory_sources.v0",
            "record_id": "msrc_cons_001",
            "created_at": "2026-07-11T11:00:00Z",
            "profile": "test",
            "route": "default",
            "selected": [
                {
                    "heading": "Crystallized Memory",
                    "source_class": "crystallized",
                    "source_ids": ["crystallized:cons_A", "crystallized:cons_B"],
                    "chars": 100,
                    "score": 0.9,
                    "reason_codes": ["fts5_hit"],
                },
            ],
            "dropped": [
                {
                    "heading": "Crystallized Memory",
                    "source_class": "crystallized",
                    "source_ids": ["crystallized:cons_B", "crystallized:cons_C"],
                    "count": 1,
                    "chars": 30,
                    "score": 0.3,
                    "reason_codes": ["budget"],
                },
                {
                    "heading": "Crystallized Memory",
                    "source_class": "crystallized",
                    "source_ids": ["crystallized:cons_D"],
                    "count": 1,
                    "chars": 25,
                    "score": 0.1,
                    "reason_codes": ["rank"],
                },
            ],
        }
        append_memory_source_record(roots, record)

        store = MemoryOSStore(roots)
        store.initialize()

        report = run_exposure_rollup_cycle(store)
        assert report["status"] == "ok"

        # cons_A: selected only
        # cons_B: selected AND dropped_by_budget → selected wins
        # cons_C: dropped_by_budget only
        # cons_D: dropped_by_rank only
        # Total classified: 4 records
        assert report["selected"] == 2  # A, B
        assert report["dropped_by_budget"] == 1  # C
        assert report["dropped_by_rank"] == 1  # D

        # Conservation: eligible == selected + dropped_by_budget + dropped_by_rank
        eligible = report["eligible"]
        assert eligible == report["selected"] + report["dropped_by_budget"] + report["dropped_by_rank"], (
            f"Conservation failure: {eligible} != {report['selected']} + "
            f"{report['dropped_by_budget']} + {report['dropped_by_rank']}"
        )
        assert report["conservation_passes"] is True

    def test_non_crystallized_source_ids_ignored(self, tmp_path: Path) -> None:
        """source_ids not starting with crystallized: or candidate: are ignored."""
        from plugins.memory.memory_os.exposure_rollup import run_exposure_rollup_cycle
        from plugins.memory.memory_os.memory_sources import append_memory_source_record
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore

        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="test")
        roots.memory_os_root.mkdir(parents=True, exist_ok=True)
        (roots.memory_os_root / "system").mkdir(parents=True, exist_ok=True)
        (roots.memory_os_root / "crystallized").mkdir(parents=True, exist_ok=True)

        record = {
            "schema_version": "memory-os.memory_sources.v0",
            "record_id": "msrc_guard_001",
            "created_at": "2026-07-11T12:00:00Z",
            "profile": "test",
            "route": "default",
            "selected": [
                {
                    "heading": "Recall Clarification Guard",
                    "source_class": "guard",
                    "source_ids": ["guard:recall_clarification"],
                    "chars": 10,
                    "score": None,
                    "reason_codes": [],
                },
                {
                    "heading": "Crystallized Memory",
                    "source_class": "crystallized",
                    "source_ids": ["crystallized:real_rec"],
                    "chars": 100,
                    "score": 0.9,
                    "reason_codes": ["fts5_hit"],
                },
            ],
            "dropped": [],
        }
        append_memory_source_record(roots, record)

        store = MemoryOSStore(roots)
        store.initialize()

        report = run_exposure_rollup_cycle(store)
        assert report["status"] == "ok"
        # guard:recall_clarification should NOT be counted
        assert report["selected"] == 1, (
            f"Guard IDs should be excluded, got {report['selected']}"
        )
