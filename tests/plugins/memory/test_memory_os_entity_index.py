"""Tests for entity_index table and deterministic entity extraction.

Covers: schema, extraction rules, dedup, rebuild/sync integration,
inverted index lookup, shared-entity pair derivation, and counts.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from plugins.memory.memory_os.entity_extractor import (
    _normalize_entity_id,
    entity_inverted_index,
    extract_entities,
    shared_entity_pairs,
)
from plugins.memory.memory_os.index import MemoryOSIndex, _index_entities
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore


# ── Helpers ────────────────────────────────────────────────────────────


def _seed_crystallized(
    store: MemoryOSStore,
    records: list[dict[str, Any]],
) -> list[str]:
    """Write canonical crystallized records and return their ids."""
    store.initialize()
    ids: list[str] = []
    for i, rec in enumerate(records):
        rid = rec.get("id", f"ent_index_test_{i:03d}_v1")
        frontmatter = {
            "schema_version": "memory-os.crystallized.v0",
            "id": rid,
            "kind": rec.get("kind", "note"),
            "created_at": rec.get("created_at", "2026-07-01T00:00:00Z"),
            "approved_by": "owner",
            "approved_at": rec.get("created_at", "2026-07-01T00:00:00Z"),
            "approval_purpose": "test",
            "approval_note": "entity index test seed",
            "source_event_ids": rec.get("source_event_ids", []),
            "tags": rec.get("tags", []),
            "sensitivity": "private",
            "hindsight_indexed": False,
            "bridge_state": "active",
        }
        body = rec.get("body", "test entity index body")
        store.append_crystallized_record(f"ent_index_{i:03d}.md", frontmatter, body)
        ids.append(rid)
    return ids


def _build_index(
    tmp_path: Path, records: list[dict[str, Any]]
) -> tuple[MemoryOSStore, MemoryOSIndex]:
    """Create store, seed records, build index, return (store, index)."""
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="entity-index-test")
    store = MemoryOSStore(roots)
    _seed_crystallized(store, records)
    index = MemoryOSIndex(roots)
    index.rebuild_from_store(store)
    return store, index


# ── Schema ─────────────────────────────────────────────────────────────


def test_entity_index_table_created(tmp_path: Path) -> None:
    """Verify entity_index table exists after index rebuild."""
    store, index = _build_index(tmp_path, [
        {"id": "rec_001", "body": "Alice met Bob."},
    ])
    conn = sqlite3.connect(str(index.roots.index_path))
    try:
        tables = [
            str(r[0])
            for r in conn.execute("select name from sqlite_master where type='table'").fetchall()
        ]
        assert "entity_index" in tables, "entity_index table should exist"
    finally:
        conn.close()


# ── Extraction rules ───────────────────────────────────────────────────


def test_extract_paths_from_body() -> None:
    """Verify path extraction from text."""
    entities = extract_entities(
        "The file is at /home/user/projects/hermes/config.json",
        record_id="rec_001",
    )
    paths = [e["entity_text"] for e in entities if "/" in e["entity_text"]]
    assert any("/home/user/projects/hermes/config.json" in p for p in paths), (
        f"expected path in extracted entities: {paths}"
    )


def test_extract_urls_from_body() -> None:
    """Verify URL extraction."""
    entities = extract_entities(
        "Visit https://example.com/path?q=test for details.",
        record_id="rec_001",
    )
    urls = [e["entity_text"] for e in entities if e["entity_text"].startswith("http")]
    assert "https://example.com/path?q=test" in urls, (
        f"expected URL in extracted entities: {urls}"
    )


def test_extract_uuids_from_body() -> None:
    """Verify UUID extraction."""
    entities = extract_entities(
        "UUID 550e8400-e29b-41d4-a716-446655440000 was referenced.",
        record_id="rec_001",
    )
    uuids = [e["entity_text"] for e in entities if "-" in e["entity_text"]]
    assert "550e8400-e29b-41d4-a716-446655440000" in uuids, (
        f"expected UUID in extracted entities: {uuids}"
    )


def test_entity_deduplication() -> None:
    """Same entity text -> same entity_id, one row per (entity_id, record_id, role)."""
    entities = extract_entities(
        "Alice Bob discussed architecture. Alice Bob also reviewed the design.",
        record_id="rec_001",
    )
    texts = [e["entity_text"] for e in entities]
    # "Alice Bob" is a capitalized phrase matching \b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b
    # It should appear only once despite appearing twice in the text (dedup by entity_id)
    alice_bob_entries = [e for e in entities if e["entity_text"] == "Alice Bob"]
    assert len(alice_bob_entries) == 1, (
        f"expected exactly one 'Alice Bob' entry (deduped), got {len(alice_bob_entries)}: {entities}"
    )
    assert alice_bob_entries[0]["entity_id"] == _normalize_entity_id("Alice Bob")
    # Verify entity_id is deterministic
    eid1 = _normalize_entity_id("Alice Bob")
    eid2 = _normalize_entity_id("alice bob")
    assert eid1 == eid2, "normalized entity ids should be case-insensitive"


# ── Edge cases ─────────────────────────────────────────────────────────


def test_empty_body_returns_empty() -> None:
    """Empty body returns empty list."""
    assert extract_entities("", record_id="rec_001") == []
    assert extract_entities("   ", record_id="rec_001") == []
    assert extract_entities(None, record_id="rec_001") == []  # type: ignore[arg-type]


# ── Rebuild integration ───────────────────────────────────────────────


def test_index_rebuild_populates_entities(tmp_path: Path) -> None:
    """Rebuild -> entity_index has rows for crystallized records."""
    body = (
        "Alice reviewed the proposal at /var/log/hermes/audit.log. "
        "See https://docs.example.com for UUID 550e8400-e29b-41d4-a716-446655440000."
    )
    store, index = _build_index(tmp_path, [
        {"id": "rec_001", "body": body},
    ])
    conn = sqlite3.connect(str(index.roots.index_path))
    try:
        row_count = conn.execute("select count(*) from entity_index").fetchone()[0]
        assert row_count > 0, f"expected >0 entity_index rows, got {row_count}"
        # Verify specific entity types are present
        paths = conn.execute(
            "select entity_text from entity_index where entity_text like '/%'"
        ).fetchall()
        assert len(paths) > 0, f"expected path entities: {paths}"
    finally:
        conn.close()


def test_index_sync_updates_entities(tmp_path: Path) -> None:
    """Sync -> entity_index updated for crystallized records."""
    store, index = _build_index(tmp_path, [
        {"id": "rec_001", "body": "Alice met Bob at /tmp/test."},
    ])
    roots = index.roots
    conn = sqlite3.connect(str(roots.index_path))
    try:
        before_count = conn.execute("select count(*) from entity_index").fetchone()[0]
    finally:
        conn.close()

    # Add a second record and sync
    store.append_crystallized_record(
        "ent_index_sync.md",
        {
            "schema_version": "memory-os.crystallized.v0",
            "id": "rec_002",
            "kind": "note",
            "created_at": "2026-07-01T00:00:00Z",
            "approved_by": "owner",
            "approved_at": "2026-07-01T00:00:00Z",
            "approval_purpose": "test",
            "approval_note": "sync test",
            "source_event_ids": [],
            "tags": [],
            "sensitivity": "private",
            "hindsight_indexed": False,
            "bridge_state": "active",
        },
        "New Path /another/path/file.txt and https://sync.example.com",
    )

    # Sync the index
    counts = index.sync_from_store(store)
    assert "entity_index" in counts, "counts should include entity_index"

    conn = sqlite3.connect(str(roots.index_path))
    try:
        after_count = conn.execute("select count(*) from entity_index").fetchone()[0]
        assert after_count > before_count, (
            f"expected entity_index to grow after sync: {before_count} -> {after_count}"
        )
        # Verify new entities from rec_002 are present
        rec_002_entities = conn.execute(
            "select entity_text from entity_index where record_id = 'rec_002'"
        ).fetchall()
        assert len(rec_002_entities) > 0, (
            f"expected entities for rec_002: {rec_002_entities}"
        )
    finally:
        conn.close()


# ── Inverted index + shared pairs ──────────────────────────────────────


def test_shared_entity_pairs(tmp_path: Path) -> None:
    """Verify pairs found for records sharing entities."""
    body_a = "Project Alpha uses /shared/path and UUID 550e8400-e29b-41d4-a716-446655440000."
    body_b = "Project Alpha deployment at /shared/path references same UUID 550e8400-e29b-41d4-a716-446655440000."
    store, index = _build_index(tmp_path, [
        {"id": "rec_001", "body": body_a},
        {"id": "rec_002", "body": body_b},
    ])

    conn = sqlite3.connect(str(index.roots.index_path))
    try:
        pairs = shared_entity_pairs(conn, min_shared_entities=1)
        assert len(pairs) >= 1, f"expected at least 1 shared pair, got {pairs}"
        found = any(
            p["record_a"] == "rec_001" and p["record_b"] == "rec_002"
            for p in pairs
        )
        assert found, f"expected pair (rec_001, rec_002) in {pairs}"

        # Inverted index: lookup by entity_id
        entity_row = conn.execute(
            "select entity_id from entity_index where entity_text = '/shared/path' limit 1"
        ).fetchone()
        assert entity_row is not None
        eid = str(entity_row[0])
        records = entity_inverted_index(conn, eid)
        assert "rec_001" in records, f"expected rec_001 in inverted lookup: {records}"
        assert "rec_002" in records, f"expected rec_002 in inverted lookup: {records}"
    finally:
        conn.close()


def test_entity_index_counts(tmp_path: Path) -> None:
    """Verify counts() includes entity_index."""
    # No index yet -> entity_index should be 0
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="entity-index-counts")
    index = MemoryOSIndex(roots)
    before_counts = index.counts()
    assert "entity_index" in before_counts, "counts should include entity_index"
    assert before_counts["entity_index"] == 0, "entity_index should be 0 before rebuild"

    # After rebuild with records -> entity_index count should increase
    store, index = _build_index(tmp_path, [
        {"id": "rec_001", "body": "Alice Bob at /tmp/test."},
        {"id": "rec_002", "body": "Visit https://example.com for details."},
    ])
    after_counts = index.counts()
    assert "entity_index" in after_counts
    assert after_counts["entity_index"] > 0, (
        f"expected >0 entity_index after rebuild, got {after_counts}"
    )


# ── Cognitive loop integration (V2-P1, Task 2) ──────────────────────────


class TestEntityIndexCognitiveLoop:
    """V2-P1: cognitive_loop integration tests for entity index extraction stage."""

    def test_entity_index_knob_defaults_disabled(self, tmp_path: Path) -> None:
        """entity_index_enabled knob defaults to False when no override file."""
        from plugins.memory.memory_os.knob_overrides import resolve_knob
        from plugins.memory.memory_os.roots import MemoryOSRoots

        roots = MemoryOSRoots.from_hermes_home(tmp_path)
        enabled = resolve_knob("entity_index_enabled", default=False, roots=roots)
        assert enabled is False

    def test_entity_index_stage_skipped_when_disabled(self, tmp_path: Path) -> None:
        """Stage returns skipped when knob is disabled (default)."""
        from plugins.memory.memory_os.cognitive_loop import CognitiveLoopRunner
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore

        roots = MemoryOSRoots.from_hermes_home(tmp_path)
        store = MemoryOSStore(roots)
        store.initialize()

        runner = CognitiveLoopRunner(store)
        result = runner._entity_index({})
        assert result["status"] == "skipped"
        assert result["reason"] == "knob_disabled"

    def test_entity_index_runs_when_knob_enabled(self, tmp_path: Path) -> None:
        """When knob enabled via override, stage extracts entities."""
        from plugins.memory.memory_os.cognitive_loop import CognitiveLoopRunner
        from plugins.memory.memory_os.index import MemoryOSIndex
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore

        roots = MemoryOSRoots.from_hermes_home(tmp_path)
        store = MemoryOSStore(roots)
        store.initialize()

        # Enable knob via override file (must match resolve_knob expected format)
        override_dir = roots.memory_os_root / "system"
        override_dir.mkdir(parents=True, exist_ok=True)
        override_file = override_dir / "knob_overrides.jsonl"
        override_file.write_text(
            json.dumps({
                "knob": "entity_index_enabled",
                "override_value": True,
                "state": "active",
            }) + "\n",
            encoding="utf-8",
        )

        # Create a crystallized record with entity-containing text
        store.append_crystallized_record(
            "test_entity_record.md",
            {
                "id": "rec-001",
                "kind": "moment",
                "created_at": "2024-01-01T00:00:00Z",
                "approved_by": "test",
                "approved_at": "2024-01-01T00:00:00Z",
                "source_event_ids": [],
                "tags": [],
                "sensitivity": "private",
                "hindsight_indexed": False,
            },
            "The production path /var/log/app was configured on Server Alpha.",
        )

        # Initialize index first (so index_path exists)
        index = MemoryOSIndex(roots)
        index.try_rebuild_from_store(store)

        # Run entity_index stage
        runner = CognitiveLoopRunner(store)
        result = runner._entity_index({})
        assert result["status"] == "ok"
        assert result["entities_indexed"] > 0
