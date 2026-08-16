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
    classify_entity,
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


def _enable_entity_index_knob(roots: MemoryOSRoots) -> None:
    """Write a knob override to enable entity_index for testing."""
    override_dir = roots.memory_os_root / "system"
    override_dir.mkdir(parents=True, exist_ok=True)
    override_file = override_dir / "knob_overrides.jsonl"
    override_file.write_text(
        json.dumps({
            "knob": "entity_index_enabled",
            "override_value": True,
            "state": "active",
            "reason": "test",
        })
        + "\n",
        encoding="utf-8",
    )


def _build_index(
    tmp_path: Path, records: list[dict[str, Any]]
) -> tuple[MemoryOSStore, MemoryOSIndex]:
    """Create store, seed records, build index, return (store, index)."""
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="entity-index-test")
    store = MemoryOSStore(roots)
    _seed_crystallized(store, records)
    _enable_entity_index_knob(roots)
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
    """W9 语义反转:path 碎片不再入实体索引。

    生产实测:25 条结晶记录抽出 24 个实体,绝大多数为 /.git-credentials、
    /main 这类路径正则碎片 — 撑不起'实体图'且污染 shared_entity 边。
    路径/URL/UUID/IP 是标识符,不是实体;实体索引只收语义类。
    """
    entities = extract_entities(
        "The file is at /home/user/projects/hermes/config.json",
        record_id="rec_001",
    )
    assert not any(
        e["entity_class"] in ("path", "url", "uuid", "ip") for e in entities
    ), f"identifier classes must be filtered out: {entities}"


def test_extract_urls_from_body() -> None:
    """W9 语义反转:URL 不再入实体索引(同 path)。"""
    entities = extract_entities(
        "Visit https://example.com/path?q=test for details.",
        record_id="rec_001",
    )
    assert not any(
        e["entity_text"].startswith("http") for e in entities
    ), f"URLs must be filtered out: {entities}"


def test_extract_uuids_from_body() -> None:
    """W9 语义反转:UUID 不再入实体索引(同 path)。"""
    entities = extract_entities(
        "UUID 550e8400-e29b-41d4-a716-446655440000 was referenced.",
        record_id="rec_001",
    )
    assert not any(
        "550e8400" in e["entity_text"] for e in entities
    ), f"UUIDs must be filtered out: {entities}"


def test_w9_proper_nouns_survive_identifier_filter() -> None:
    """W9 反事实:过滤标识符类的同时,专名必须保留(不得一刀切清空)。"""
    entities = extract_entities(
        "Alice Bob deployed /opt/hermes/config.json to https://example.com "
        "with UUID 550e8400-e29b-41d4-a716-446655440000 for Memory State Overlay.",
        record_id="rec_001",
    )
    texts = [e["entity_text"] for e in entities]
    assert "Alice Bob" in texts, f"proper nouns must survive: {texts}"
    assert "Memory State Overlay" in texts
    assert all(e["entity_class"] == "proper_noun" for e in entities), entities


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
    """Rebuild -> entity_index has rows for crystallized records.

    W9 语义反转:索引只收语义类实体;path/url/uuid 碎片不得入索引。
    """
    body = (
        "Alice Chen reviewed the proposal at /var/log/hermes/audit.log. "
        "See https://docs.example.com for UUID 550e8400-e29b-41d4-a716-446655440000."
    )
    store, index = _build_index(tmp_path, [
        {"id": "rec_001", "body": body},
    ])
    conn = sqlite3.connect(str(index.roots.index_path))
    try:
        row_count = conn.execute("select count(*) from entity_index").fetchone()[0]
        assert row_count > 0, f"expected >0 entity_index rows, got {row_count}"
        # W9: identifier-class shards must NOT be indexed
        paths = conn.execute(
            "select entity_text from entity_index where entity_text like '/%'"
        ).fetchall()
        assert len(paths) == 0, f"path shards must be filtered (W9): {paths}"
        names = conn.execute(
            "select entity_text from entity_index where entity_text = 'Alice Chen'"
        ).fetchall()
        assert len(names) == 1, "proper nouns must be indexed"
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
    """Verify pairs found for records sharing entities (W9: 专名共享,非 path)。"""
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

        # Inverted index: lookup by entity_id (W9: 共享实体是专名,path 不入索引)
        entity_row = conn.execute(
            "select entity_id from entity_index where entity_text = 'Project Alpha' limit 1"
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

    def test_entity_index_enabled_persists_error_record_on_knob_resolution_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_entity_index_enabled must not silently swallow resolve_knob() failures.

        Counterfactual: before the fix, the except-Exception handler in
        _entity_index_enabled built an error_record via build_error_record()
        but discarded the return value as a bare expression statement —
        never appending, never writing it anywhere. A corrupt knob-override
        read therefore produced zero diagnostic trace. This test forces
        resolve_knob() to raise and asserts a fully-shaped error_record
        (component/operation/error_code/severity/recoverable/schema_version)
        lands durably in the audit log.
        """
        from plugins.memory.memory_os.audit import read_audit_records
        from plugins.memory.memory_os.index import _entity_index_enabled
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore

        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="entity-index-error-test")
        store = MemoryOSStore(roots)
        store.initialize()

        def _boom(*args, **kwargs):
            raise RuntimeError("corrupt knob-override store")

        monkeypatch.setattr(
            "plugins.memory.memory_os.knob_overrides.resolve_knob", _boom
        )

        result = _entity_index_enabled(store)
        assert result is False  # fail-closed default is preserved

        audit_records = read_audit_records(roots.audit_path)
        matching = [
            r for r in audit_records
            if r.get("action") == "entity_index_knob_resolution_failed"
        ]
        assert len(matching) == 1, (
            "expected exactly one durable audit record for the knob "
            f"resolution failure, got: {audit_records}"
        )
        error_record = matching[0].get("details", {}).get("error_record")
        assert isinstance(error_record, dict), "error_record must be persisted in details"
        assert error_record["schema_version"] == "memory-os.error_record.v0"
        assert error_record["component"] == "entity_index"
        assert error_record["operation"] == "knob_resolution"
        assert error_record["error_code"] == "ENTITY_INDEX_KNOB_FAILED"
        assert error_record["severity"] == "warning"
        assert error_record["recoverable"] is True
        assert "corrupt knob-override store" in error_record["details"]["error"]


# ── Whitespace collapse ─────────────────────────────────────────────


def test_entity_id_whitespace_collapse() -> None:
    """Entity IDs are identical regardless of internal whitespace variation."""
    from plugins.memory.memory_os.entity_extractor import _normalize_entity_id

    eid_single = _normalize_entity_id("John Smith")
    eid_double = _normalize_entity_id("John  Smith")
    eid_tab = _normalize_entity_id("John\tSmith")
    assert eid_single == eid_double, "double-space should collapse to single"
    assert eid_single == eid_tab, "tab should collapse to space"


def test_entity_extraction_whitespace_collapse() -> None:
    """Extracting same entity with different whitespace produces single entry."""
    from plugins.memory.memory_os.entity_extractor import extract_entities
    entities = extract_entities(
        "Alice Bob met. Alice  Bob discussed.",
        record_id="rec_001",
    )
    alice_bob_entries = [e for e in entities if e["entity_text"] == "Alice Bob"]
    assert len(alice_bob_entries) == 1, (
        f"expected exactly one 'Alice Bob' entry, got {alice_bob_entries}"
    )


# ── Phase 2: Entity classification + soft-weighting ────────────────────


class TestClassifyEntity:
    """Phase 2: entity_class assignment and soft-weighting (retrieval layer)."""

    def test_classify_path_entity(self):
        entity_class, weight = classify_entity("/opt/hermes/memory-os/config.json")
        assert entity_class == "path"
        assert weight == 0.4

    def test_classify_url_entity(self):
        entity_class, weight = classify_entity("https://docs.example.com/hermes/guide")
        assert entity_class == "url"
        assert weight == 0.5

    def test_classify_ip_entity(self):
        entity_class, weight = classify_entity("192.0.2.10")
        assert entity_class == "ip"
        assert weight == 0.6

    def test_classify_uuid_entity(self):
        entity_class, weight = classify_entity("550e8400-e29b-41d4-a716-446655440000")
        assert entity_class == "uuid"
        assert weight == 0.5

    def test_classify_proper_noun_entity(self):
        entity_class, weight = classify_entity("Alice Bob")
        assert entity_class == "proper_noun"
        assert weight == 0.9

    def test_classify_single_capitalized_word_not_proper_noun(self):
        """Single capitalized word doesn't match proper_noun pattern (needs 2+ words)."""
        entity_class, weight = classify_entity("Alice")
        # Should NOT be proper_noun (requires 2+ capitalized words pattern)
        assert entity_class != "proper_noun", f"single word should not be proper_noun, got {entity_class}"

    def test_classify_identifier_entity(self):
        entity_class, weight = classify_entity("config_parser_v2")
        assert entity_class == "identifier"
        assert weight == 0.7

    def test_classify_unknown_entity(self):
        entity_class, weight = classify_entity("xy")
        assert entity_class == "unknown"
        assert weight == 0.7

    def test_classify_empty_string(self):
        entity_class, weight = classify_entity("")
        assert entity_class == "empty"
        assert weight == 0.0

    def test_path_ranked_lower_than_proper_noun(self):
        """Constraint 2: paths are soft-weight 0.4, not hard-deleted."""
        _, path_weight = classify_entity("/var/log/hermes/audit.log")
        _, noun_weight = classify_entity("Hermes Memory OS")
        assert path_weight < noun_weight, (
            f"path weight ({path_weight}) should be lower than proper_noun ({noun_weight})"
        )


class TestEntityExtractionWithClass:
    """Phase 2: extract_entities includes entity_class and weight."""

    def test_extracted_entities_have_entity_class(self):
        entities = extract_entities(
            "Alice Bob worked on /opt/hermes/config.json and visited https://example.com",
            record_id="rec_001",
        )
        for ent in entities:
            assert "entity_class" in ent, f"entity missing entity_class: {ent}"
            assert "weight" in ent, f"entity missing weight: {ent}"
            assert isinstance(ent["weight"], float)

    def test_path_entity_has_low_weight(self):
        """W9 语义反转:path 类不再进入抽取结果;分类器契约本身保持。"""
        from plugins.memory.memory_os.entity_extractor import classify_entity

        # 分类器词表不变(未来类可显式 opt-in)
        assert classify_entity("/opt/hermes/config.json") == ("path", 0.4)
        # 抽取结果不含 path 类
        entities = extract_entities(
            "The config is at /opt/hermes/config.json",
            record_id="rec_001",
        )
        assert not [e for e in entities if e["entity_class"] == "path"], entities

    def test_proper_noun_entity_has_high_weight(self):
        entities = extract_entities(
            "Alice Bob and Charlie David discussed the project.",
            record_id="rec_001",
        )
        proper_entities = [e for e in entities if e["entity_class"] == "proper_noun"]
        assert len(proper_entities) >= 1
        for e in proper_entities:
            assert e["weight"] == 0.9, f"proper_noun should have weight=0.9, got {e}"


class TestEntityIndexStatsWithClasses:
    """Phase 2: entity_index_stats includes class_distribution."""

    def test_entity_index_stats_includes_class_distribution(self, tmp_path):
        from plugins.memory.memory_os.entity_index import entity_index_stats, refresh_entity_index

        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="entity-class-test")
        store = MemoryOSStore(roots)
        _seed_crystallized(store, [
            {"id": "rec_001", "body": "Alice Bob worked on /opt/hermes and https://example.com"},
        ])
        _enable_entity_index_knob(roots)

        db_path = roots.index_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        refresh_entity_index(db_path, roots.crystallized_root, enabled=True)

        stats = entity_index_stats(db_path)
        assert "class_distribution" in stats, f"stats missing class_distribution: {stats}"
        class_dist = stats["class_distribution"]
        assert len(class_dist) >= 1, f"class_distribution should have entries: {class_dist}"
        # path entity should be present
        assert "path" in class_dist or class_dist, f"expected some class distribution: {class_dist}"

    def test_top_entities_include_class_and_weight(self, tmp_path):
        from plugins.memory.memory_os.entity_index import entity_index_stats, refresh_entity_index

        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="entity-top-test")
        store = MemoryOSStore(roots)
        _seed_crystallized(store, [
            {"id": "rec_001", "body": "Alice Bob discussed /opt/hermes/config.json."},
        ])
        _enable_entity_index_knob(roots)

        db_path = roots.index_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        refresh_entity_index(db_path, roots.crystallized_root, enabled=True)

        stats = entity_index_stats(db_path)
        for ent in stats["top_entities"]:
            assert "entity_class" in ent, f"top entity missing entity_class: {ent}"
            assert "weight" in ent, f"top entity missing weight: {ent}"


class TestQueryRelatedRecordsWithWeight:
    """Phase 2: query_related_records with min_weight filter."""

    def test_query_related_records_respects_min_weight(self, tmp_path):
        from plugins.memory.memory_os.entity_index import query_related_records, refresh_entity_index

        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="entity-weight-query")
        store = MemoryOSStore(roots)
        _seed_crystallized(store, [
            {"id": "rec_001", "body": "Alice Bob at /opt/hermes/config.json."},
            {"id": "rec_002", "body": "Alice Bob reviewed the proposal."},
        ])
        _enable_entity_index_knob(roots)

        db_path = roots.index_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        refresh_entity_index(db_path, roots.crystallized_root, enabled=True)

        # Low min_weight: both records found
        all_related = query_related_records(db_path, ["rec_001"], min_weight=0.0)
        assert len(all_related) >= 1

        # High min_weight: path entity (0.4) excluded, proper_noun (0.9) still included
        high_weight_related = query_related_records(db_path, ["rec_001"], min_weight=0.8)
        # Only proper_noun entities should pass
        for rel in high_weight_related:
            assert rel["weight"] >= 0.8, (
                f"entity {rel['shared_entity']} with weight {rel['weight']} should be >= 0.8"
            )

    def test_query_related_records_includes_entity_class(self, tmp_path):
        from plugins.memory.memory_os.entity_index import query_related_records, refresh_entity_index

        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="entity-class-query")
        store = MemoryOSStore(roots)
        _seed_crystallized(store, [
            {"id": "rec_001", "body": "Alice Bob at /opt/hermes/config.json."},
            {"id": "rec_002", "body": "Alice Bob discussed the design."},
        ])
        _enable_entity_index_knob(roots)

        db_path = roots.index_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        refresh_entity_index(db_path, roots.crystallized_root, enabled=True)

        related = query_related_records(db_path, ["rec_001"], min_weight=0.0)
        for rel in related:
            assert "entity_class" in rel, f"related record missing entity_class: {rel}"
            assert "weight" in rel, f"related record missing weight: {rel}"


# ── Code-review fix: shared_entity/entity_class/weight provenance and
#    min_weight join-level filtering (query_related_records) ───────────
#
# W9 restricts the *default* extract_entities() call (used by both
# refresh_entity_index and index.py's _index_entities) to INDEXABLE_ENTITY_
# CLASSES = {"proper_noun"}, so a production entity_index table today only
# ever contains proper_noun/0.9 rows.  To build a real multi-class fixture
# — required to exercise the mis-provenance bug at all — these tests widen
# the module-level INDEXABLE_ENTITY_CLASSES to entity_extractor's own
# REFERENCE_DETECTION_CLASSES (the same constant __init__.py already uses
# for detection-style callers) for the duration of the test only, then run
# the real refresh_entity_index producer unmodified.  classify_entity()
# still assigns the real class/weight for every entity text; only which
# classes are allowed through the index gate is widened.


def _enable_reference_detection_classes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Widen the index-worthiness gate so refresh_entity_index indexes
    path/url/uuid/ip/identifier entities too, not just proper_noun.

    This does not change classify_entity()'s real (class, weight) mapping —
    only which classes extract_entities() lets through into entity_index.
    """
    from plugins.memory.memory_os.entity_extractor import REFERENCE_DETECTION_CLASSES

    monkeypatch.setattr(
        "plugins.memory.memory_os.entity_extractor.INDEXABLE_ENTITY_CLASSES",
        REFERENCE_DETECTION_CLASSES,
    )


class TestQueryRelatedRecordsProvenance:
    """Counterfactuals for two verified defects in query_related_records:

    1. min(entity_text) / max(weight) were independent aggregates over the
       same GROUP BY and could describe two different entities; entity_class
       was re-derived from the resulting weight via hardcoded float bands
       instead of being read from the authoritative column.
    2. min_weight was applied via `having max(weight) >= ?`, which filters
       GROUPS (whole records), not the entities that make up overlap_count —
       so low-weight entities could still inflate overlap_count and rank.
    """

    def test_shared_entity_class_and_weight_describe_the_same_entity(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Defect 1 counterfactual: a record sharing both a low-weight path
        entity and a high-weight proper_noun entity must return a row whose
        shared_entity/entity_class/weight all describe ONE entity — the
        highest-weight one — not a min(text)+max(weight) chimera.

        Without the fix: min(entity_text) picks a path (paths sort first —
        '/' < any letter), max(weight) picks the proper_noun's 0.9, and the
        weight-band derivation reports "proper_noun" for a shared_entity
        string that is actually a path. The returned row lies about which
        entity earned that class and weight.
        """
        from plugins.memory.memory_os.entity_index import query_related_records, refresh_entity_index

        _enable_reference_detection_classes(monkeypatch)

        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="entity-provenance-1")
        store = MemoryOSStore(roots)
        _seed_crystallized(store, [
            {
                "id": "anchor",
                "body": (
                    "Reviewed /opt/hermes/a.json /opt/hermes/b.json "
                    "/opt/hermes/c.json /opt/hermes/d.json along with "
                    "Zeta Corp and Alpha One and Beta Two."
                ),
            },
            {
                "id": "rec_a",
                "body": (
                    "Audit of /opt/hermes/a.json /opt/hermes/b.json "
                    "/opt/hermes/c.json /opt/hermes/d.json plus Zeta Corp notes."
                ),
            },
        ])
        _enable_entity_index_knob(roots)

        db_path = roots.index_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        refresh_entity_index(db_path, roots.crystallized_root, enabled=True)

        related = query_related_records(db_path, ["anchor"], min_weight=0.0)
        rows_for_a = [r for r in related if r["related_record_id"] == "rec_a"]
        assert len(rows_for_a) == 1, f"expected exactly one row for rec_a: {related}"
        row = rows_for_a[0]

        # The four shared paths (weight 0.4) must not win provenance over
        # the shared proper_noun (weight 0.9) — the row must describe the
        # highest-weight shared entity, consistently.
        assert row["shared_entity"] == "Zeta Corp", (
            f"shared_entity should be the highest-weight shared entity, got: {row}"
        )
        assert row["entity_class"] == "proper_noun", (
            f"entity_class must describe the SAME entity as shared_entity: {row}"
        )
        assert row["weight"] == 0.9, f"weight must match the winning entity: {row}"
        # All five shared entities (4 paths + 1 proper_noun) still counted
        # at min_weight=0.0 — this test is about provenance, not filtering.
        assert row["overlap_count"] == 5, f"unexpected overlap_count: {row}"

        # Independent verification: the real classifier agrees with what
        # query_related_records reported for the entity it named.
        from plugins.memory.memory_os.entity_extractor import classify_entity

        assert classify_entity(row["shared_entity"]) == (row["entity_class"], row["weight"])

    def test_entity_class_read_from_column_not_weight_band(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Defect 1 counterfactual: entity_class must come from the stored
        column, not be re-derived from weight via hardcoded float bands.

        uuid (weight 0.5) and url (weight 0.5) collide in the old band
        table — both hit the `weight == 0.5` branch, which always reported
        "url". A record sharing only a uuid must be reported as "uuid".
        """
        from plugins.memory.memory_os.entity_index import query_related_records, refresh_entity_index

        _enable_reference_detection_classes(monkeypatch)

        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="entity-provenance-2")
        store = MemoryOSStore(roots)
        _seed_crystallized(store, [
            {"id": "anchor", "body": "Ticket ref 550e8400-e29b-41d4-a716-446655440000 filed."},
            {"id": "rec_c", "body": "Follow-up for ticket 550e8400-e29b-41d4-a716-446655440000 pending."},
        ])
        _enable_entity_index_knob(roots)

        db_path = roots.index_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        refresh_entity_index(db_path, roots.crystallized_root, enabled=True)

        related = query_related_records(db_path, ["anchor"], min_weight=0.0)
        rows_for_c = [r for r in related if r["related_record_id"] == "rec_c"]
        assert len(rows_for_c) == 1, f"expected exactly one row for rec_c: {related}"
        row = rows_for_c[0]

        assert row["weight"] == 0.5
        assert row["entity_class"] == "uuid", (
            "entity_class must be read from the stored column (uuid), not "
            f"re-derived from the weight==0.5 band (which said url): {row}"
        )

    def test_min_weight_filters_entities_not_whole_groups(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Defect 2 counterfactual: min_weight must exclude low-weight
        entities from the JOIN (and thus from overlap_count), not merely
        gate whole groups via HAVING max(weight) >= threshold.

        rec_a shares 4 low-weight (0.4) paths + 1 high-weight (0.9) proper
        noun with the anchor (5 total). rec_b shares only 2 high-weight
        (0.9) proper nouns (2 total). At min_weight=0.5 the old HAVING
        clause let rec_a through with overlap_count=5 (inflated by the four
        sub-threshold paths) and ranked it above rec_b's overlap_count=2 —
        exactly backwards, since rec_a's genuinely-qualifying overlap is
        only 1.
        """
        from plugins.memory.memory_os.entity_index import query_related_records, refresh_entity_index

        _enable_reference_detection_classes(monkeypatch)

        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="entity-provenance-3")
        store = MemoryOSStore(roots)
        _seed_crystallized(store, [
            {
                "id": "anchor",
                "body": (
                    "Reviewed /opt/hermes/a.json /opt/hermes/b.json "
                    "/opt/hermes/c.json /opt/hermes/d.json along with "
                    "Zeta Corp and Alpha One and Beta Two."
                ),
            },
            {
                "id": "rec_a",
                "body": (
                    "Audit of /opt/hermes/a.json /opt/hermes/b.json "
                    "/opt/hermes/c.json /opt/hermes/d.json plus Zeta Corp notes."
                ),
            },
            {"id": "rec_b", "body": "Meeting notes: Alpha One and Beta Two discussed rollout."},
        ])
        _enable_entity_index_knob(roots)

        db_path = roots.index_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        refresh_entity_index(db_path, roots.crystallized_root, enabled=True)

        related = query_related_records(db_path, ["anchor"], min_weight=0.5)
        by_record = {r["related_record_id"]: r for r in related}

        assert by_record["rec_a"]["overlap_count"] == 1, (
            f"low-weight paths must not inflate overlap_count: {by_record['rec_a']}"
        )
        assert by_record["rec_b"]["overlap_count"] == 2, by_record["rec_b"]

        # Ranking must reflect genuinely-qualifying overlap: rec_b (2) ahead
        # of rec_a (1), not rec_a ahead on its inflated pre-filter count of 5.
        ranked_ids = [r["related_record_id"] for r in related]
        assert ranked_ids.index("rec_b") < ranked_ids.index("rec_a"), (
            f"rec_b should outrank rec_a once low-weight entities are "
            f"excluded from overlap_count: {related}"
        )

    def test_production_caller_min_weight_ranking_unchanged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Severity check: the only production caller (entity_graph.py,
        min_weight=0.3) sits below every real class weight (min is path at
        0.4), so the WHERE-vs-HAVING distinction is a no-op at that
        threshold — no entity is ever excluded either way. Same fixture as
        the min_weight=0.5 counterfactual above, but at the real call-site
        threshold: overlap_count and ranking must match the pre-fix values
        (rec_a=5 ahead of rec_b=2), proving the fix does not change today's
        production ranking.
        """
        from plugins.memory.memory_os.entity_index import query_related_records, refresh_entity_index

        _enable_reference_detection_classes(monkeypatch)

        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="entity-provenance-4")
        store = MemoryOSStore(roots)
        _seed_crystallized(store, [
            {
                "id": "anchor",
                "body": (
                    "Reviewed /opt/hermes/a.json /opt/hermes/b.json "
                    "/opt/hermes/c.json /opt/hermes/d.json along with "
                    "Zeta Corp and Alpha One and Beta Two."
                ),
            },
            {
                "id": "rec_a",
                "body": (
                    "Audit of /opt/hermes/a.json /opt/hermes/b.json "
                    "/opt/hermes/c.json /opt/hermes/d.json plus Zeta Corp notes."
                ),
            },
            {"id": "rec_b", "body": "Meeting notes: Alpha One and Beta Two discussed rollout."},
        ])
        _enable_entity_index_knob(roots)

        db_path = roots.index_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        refresh_entity_index(db_path, roots.crystallized_root, enabled=True)

        related = query_related_records(db_path, ["anchor"], min_weight=0.3)
        by_record = {r["related_record_id"]: r for r in related}

        assert by_record["rec_a"]["overlap_count"] == 5, by_record["rec_a"]
        assert by_record["rec_b"]["overlap_count"] == 2, by_record["rec_b"]
        ranked_ids = [r["related_record_id"] for r in related]
        assert ranked_ids.index("rec_a") < ranked_ids.index("rec_b"), (
            f"at the real call-site min_weight=0.3, ranking must be unchanged: {related}"
        )

    def test_query_related_records_fails_open_on_missing_weight_columns(
        self, tmp_path: Path
    ) -> None:
        """Preserve the existing fail-open contract: a table lacking
        entity_class/weight (pre-migration schema, not self-healed via
        refresh_entity_index's ALTER) must degrade to [] rather than raise,
        with a durable warning log — not silently swallowed either.
        """
        from plugins.memory.memory_os.entity_index import query_related_records

        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="entity-provenance-5")
        db_path = roots.index_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(
                """
                create table entity_index (
                    entity_id text not null,
                    entity_text text not null,
                    record_id text not null,
                    role text not null,
                    proposed_by text not null default 'structural',
                    created_at text not null,
                    primary key (entity_id, record_id, role)
                )
                """
            )
            conn.execute(
                "insert into entity_index (entity_id, entity_text, record_id, role,"
                " proposed_by, created_at) values ('e1', 'Alice Bob', 'anchor', 'mention',"
                " 'structural', '2026-01-01T00:00:00Z')"
            )
            conn.execute(
                "insert into entity_index (entity_id, entity_text, record_id, role,"
                " proposed_by, created_at) values ('e1', 'Alice Bob', 'rec_other', 'mention',"
                " 'structural', '2026-01-01T00:00:00Z')"
            )
            conn.commit()
        finally:
            conn.close()

        related = query_related_records(db_path, ["anchor"], min_weight=0.0)
        assert related == [], f"missing-column schema must degrade to [], got: {related}"


# ── Analysis-doc M2: index.py rebuild/sync must not drift from the
#    entity_index producer schema (class/weight columns) ────────────────


class TestEntityIndexSchemaParityWithRebuild:
    """Counterfactuals for the rebuild/sync schema drift (analysis-doc M2).

    Every prior test built the table through refresh_entity_index (which
    self-heals via ALTER); none exercised the index.py DDL + fill path that
    production rebuild and index_sync actually run. Without the fix the
    rebuilt table lacks entity_class/weight, query_related_records swallows
    the OperationalError into a silent [], and every sync flattens healed
    weights back to column defaults.
    """

    def test_rebuild_from_store_yields_weight_bearing_queryable_table(self, tmp_path):
        from plugins.memory.memory_os.entity_index import query_related_records

        store, index = _build_index(tmp_path, [
            {"id": "rec_001", "body": "Alice Bob at /opt/hermes/config.json."},
            {"id": "rec_002", "body": "Alice Bob reviewed the proposal."},
        ])

        conn = sqlite3.connect(str(index.roots.index_path))
        try:
            columns = {row[1] for row in conn.execute("pragma table_info(entity_index)")}
        finally:
            conn.close()
        assert "entity_class" in columns, f"rebuilt table missing entity_class: {columns}"
        assert "weight" in columns, f"rebuilt table missing weight: {columns}"

        related = query_related_records(index.roots.index_path, ["rec_001"], min_weight=0.8)
        assert related, "proper_noun-weighted related records must survive min_weight=0.8"
        for rel in related:
            assert rel["weight"] >= 0.8, f"expected real weights from rebuild fill: {rel}"

    def test_sync_from_store_preserves_refresh_weights(self, tmp_path):
        from plugins.memory.memory_os.entity_index import refresh_entity_index

        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="entity-sync-weights")
        store = MemoryOSStore(roots)
        _seed_crystallized(store, [
            {"id": "rec_001", "body": "Alice Bob at /opt/hermes/config.json."},
            {"id": "rec_002", "body": "Alice Bob discussed the design."},
        ])
        _enable_entity_index_knob(roots)

        roots.index_path.parent.mkdir(parents=True, exist_ok=True)
        refresh_entity_index(roots.index_path, roots.crystallized_root, enabled=True)

        index = MemoryOSIndex(roots)
        index.sync_from_store(store)

        conn = sqlite3.connect(str(roots.index_path))
        try:
            weights = {
                float(row[0])
                for row in conn.execute("select distinct weight from entity_index")
            }
        finally:
            conn.close()
        # W9 后索引只剩 proper_noun(0.9);flatten 缺陷的表现是列默认 0.7。
        assert 0.9 in weights, (
            f"sync must not flatten proper_noun weight to the column default: {weights}"
        )
        assert 0.7 not in weights, (
            f"column-default weight means sync flattened real weights: {weights}"
        )

    def test_sync_migrates_legacy_six_column_table(self, tmp_path):
        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="entity-legacy-migrate")
        store = MemoryOSStore(roots)
        _seed_crystallized(store, [
            {"id": "rec_001", "body": "Alice Bob at /opt/hermes/config.json."},
        ])
        _enable_entity_index_knob(roots)

        # Simulate a pre-fix live index: six-column table, no class/weight.
        roots.index_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(roots.index_path))
        try:
            conn.execute(
                """
                create table entity_index (
                    entity_id text not null,
                    entity_text text not null,
                    record_id text not null,
                    role text not null,
                    proposed_by text not null default 'structural',
                    created_at text not null,
                    primary key (entity_id, record_id, role)
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

        index = MemoryOSIndex(roots)
        counts = index.sync_from_store(store)
        assert counts["entity_index"] > 0

        conn = sqlite3.connect(str(roots.index_path))
        try:
            columns = {row[1] for row in conn.execute("pragma table_info(entity_index)")}
        finally:
            conn.close()
        assert {"entity_class", "weight"} <= columns, (
            f"legacy table must be migrated in place by sync: {columns}"
        )
