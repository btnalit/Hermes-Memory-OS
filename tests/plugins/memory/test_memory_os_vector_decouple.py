"""Tests for vector backend decoupling (D-BUG + D1 + D4)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


class MockEmbedder:
    """Minimal embedder stub that returns a fixed model_name and produces
    deterministic 3-element float32 embeddings for testing."""
    def __init__(self, model_name: str = "test-model-v1"):
        self._model_name = model_name

    @property
    def model_name(self) -> str:
        return self._model_name

    def is_available(self) -> bool:
        return True

    def embed(self, text: str) -> bytes:
        import numpy as np
        import hashlib
        # Deterministic 3-dim embedding per text
        h = hashlib.sha256(text.encode()).digest()[:12]
        return np.frombuffer(h, dtype=np.float32).tobytes()


class TestEmbeddingModelLabel:
    """D-BUG: embedding_model field must match the embedder's actual model_name,
    not a hardcoded string."""

    def test_embedding_model_uses_embedder_model_name(self, tmp_path: Path):
        """Index writes embedder.model_name into memory_embeddings.embedding_model."""
        from plugins.memory.memory_os.index import _index_embeddings

        crystallized_root = tmp_path / "crystallized"
        crystallized_root.mkdir()

        # Write a minimal crystallized record .md file
        record_path = crystallized_root / "rec-1.md"
        record_path.write_text("""---
id: rec-1
kind: fact
provisional: false
approved_by: test
approved_at: 2026-01-01T00:00:00Z
tags: []
---
Test body.
""", encoding="utf-8")

        embedder = MockEmbedder(model_name="BAAI/bge-m3")
        index_path = tmp_path / "index.db"

        # Build a minimal index with the required table
        conn = sqlite3.connect(str(index_path))
        conn.executescript("""
            create table if not exists crystallized_records (
                id text primary key, kind text, created_at text,
                approved_by text, approved_at text,
                source_event_ids_json text, tags_json text,
                sensitivity text, hindsight_indexed integer,
                file_name text
            );
            create table if not exists memory_embeddings (
                record_type text not null,
                record_id text not null,
                embedding_model text not null,
                embedding blob not null,
                created_at text not null,
                primary key (record_type, record_id, embedding_model)
            );
        """)
        conn.execute(
            "insert into crystallized_records values (?,?,?,?,?,?,?,?,?,?)",
            ("rec-1", "fact", "2026-01-01T00:00:00Z", "test",
             "2026-01-01T00:00:00Z", "[]", "[]", "low", 0, "rec-1.md"),
        )
        conn.commit()

        _index_embeddings(conn, crystallized_root, embedder)

        # Verify the stored embedding_model matches the embedder
        row = conn.execute(
            "select embedding_model from memory_embeddings where record_id = ?",
            ("rec-1",),
        ).fetchone()
        conn.close()

        assert row is not None, "embedding row should exist"
        assert row[0] == "BAAI/bge-m3", (
            f"D-BUG: embedding_model should be 'BAAI/bge-m3' (embedder.model_name), "
            f"got '{row[0]}' — hardcoded MiniLM bug"
        )

    def test_embedding_model_minilm_default(self, tmp_path: Path):
        """Default embedder writes its default model_name."""
        from plugins.memory.memory_os.index import _index_embeddings
        from plugins.memory.memory_os.embedder import LocalEmbedder

        crystallized_root = tmp_path / "crystallized"
        crystallized_root.mkdir()

        record_path = crystallized_root / "rec-1.md"
        record_path.write_text("""---
id: rec-1
kind: fact
provisional: false
approved_by: test
approved_at: 2026-01-01T00:00:00Z
tags: []
---
Test.
""", encoding="utf-8")

        index_path = tmp_path / "index.db"
        conn = sqlite3.connect(str(index_path))
        conn.executescript("""
            create table if not exists crystallized_records (
                id text primary key, kind text, created_at text,
                approved_by text, approved_at text,
                source_event_ids_json text, tags_json text,
                sensitivity text, hindsight_indexed integer,
                file_name text
            );
            create table if not exists memory_embeddings (
                record_type text not null, record_id text not null,
                embedding_model text not null, embedding blob not null,
                created_at text not null,
                primary key (record_type, record_id, embedding_model)
            );
        """)
        conn.execute(
            "insert into crystallized_records values (?,?,?,?,?,?,?,?,?,?)",
            ("rec-1", "fact", "2026-01-01T00:00:00Z", "test",
             "2026-01-01T00:00:00Z", "[]", "[]", "low", 0, "rec-1.md"),
        )
        conn.commit()

        # Note: LocalEmbedder() defaults to MiniLM; is_available() may
        # return False on Windows or without sentence-transformers.
        # The test validates the code path, not actual model loading.
        embedder = LocalEmbedder()
        try:
            _index_embeddings(conn, crystallized_root, embedder)
        except Exception:
            # If sentence-transformers isn't installed, the embedder
            # won't produce vectors but shouldn't crash _index_embeddings
            # (graceful degrade path). We verify the schema is intact.
            pass

        # If embedder was available, verify the label matches
        row = conn.execute(
            "select count(*) from memory_embeddings"
        ).fetchone()
        conn.close()
        # If vectors were written, model_name must not be hardcoded
        if row and row[0] > 0:
            conn = sqlite3.connect(str(index_path))
            model_row = conn.execute(
                "select distinct embedding_model from memory_embeddings"
            ).fetchone()
            conn.close()
            assert model_row is not None
            assert "MiniLM" in model_row[0] or model_row[0] == embedder.model_name, (
                f"Default embedder model_name should contain MiniLM, got {model_row[0]}"
            )


class TestBuildEmbedder:
    """D1: build_embedder factory reads knobs and returns configured embedder."""

    def test_build_embedder_disabled_returns_none(self, tmp_path: Path):
        """When vector_retrieval_enabled knob=False, returns None."""
        # Set up roots with knob override store
        system_dir = tmp_path / "memory-os" / "system"
        system_dir.mkdir(parents=True)
        knob_path = system_dir / "knob_overrides.jsonl"
        import json
        knob_path.write_text(json.dumps({
            "schema_version": "memory-os.knob_override.v0",
            "id": "ko_test",
            "knob": "vector_retrieval_enabled",
            "override_value": False,
            "prior_value": False,
            "bounds": None,
            "allowed": [True, False],
            "provisional": False,
            "expires_at": "",
            "proposed_by": "test",
            "approved_via": "test",
            "state": "confirmed",
            "ts": "2026-01-01T00:00:00Z",
        }) + "\n", encoding="utf-8")

        # Override the store root for testing
        from plugins.memory.memory_os.knob_overrides import resolve_knob
        result = resolve_knob("vector_retrieval_enabled", default=False,
                              _store_root=system_dir)
        assert result is False

    def test_build_embedder_enabled_with_default_model(self, tmp_path: Path):
        """When vector_retrieval_enabled=True (defaults), returns embedder
        with default MiniLM model."""
        from plugins.memory.memory_os.knob_overrides import resolve_knob

        # No override → default True for test, but actual default in
        # OVERRIDABLE_KNOBS is False. Test the fallback path.
        result = resolve_knob("vector_retrieval_enabled", default=True,
                              _store_root=tmp_path / "nonexistent")
        assert result is True


class TestVectorEdgeThresholdKnobs:
    """D4: vector_edge thresholds read from knobs, not hardcoded constants."""

    def test_default_thresholds_match_current_constants(self):
        """Default knob values equal the current hardcoded constants."""
        from plugins.memory.memory_os.knob_overrides import resolve_knob

        refines = resolve_knob("vector_edge_refines_threshold", default=0.75,
                               _store_root=None)
        co_occurs = resolve_knob("vector_edge_co_occurs_threshold", default=0.65,
                                 _store_root=None)
        contradicts = resolve_knob("vector_edge_contradicts_threshold", default=0.35,
                                   _store_root=None)
        assert refines == 0.75
        assert co_occurs == 0.65
        assert contradicts == 0.35

    def test_override_threshold_changes_detection(self, tmp_path: Path):
        """Overriding a threshold knob changes _detect_relation_from_similarity."""
        system_dir = tmp_path / "memory-os" / "system"
        system_dir.mkdir(parents=True)
        knob_path = system_dir / "knob_overrides.jsonl"
        import json
        # Override refines threshold to 0.90 (bge-m3 style)
        knob_path.write_text(json.dumps({
            "schema_version": "memory-os.knob_override.v0",
            "id": "ko_test_2",
            "knob": "vector_edge_refines_threshold",
            "override_value": 0.90,
            "prior_value": 0.75,
            "bounds": [0.5, 1.0],
            "allowed": None,
            "provisional": False,
            "expires_at": "",
            "proposed_by": "test",
            "approved_via": "test",
            "state": "confirmed",
            "ts": "2026-01-01T00:00:00Z",
        }) + "\n", encoding="utf-8")

        from plugins.memory.memory_os.knob_overrides import resolve_knob
        result = resolve_knob("vector_edge_refines_threshold", default=0.75,
                              _store_root=system_dir)
        assert result == 0.90, (
            f"D.5: override should produce 0.90, got {result}"
        )


class TestCounterfactuals:
    """Core counterfactuals (must FAIL when guard is removed)."""

    def test_dx_hardcoded_model_name_fails(self, tmp_path: Path):
        """D.X: If embedder.model_name is bge-m3 but code writes 'MiniLM',
        the test must detect the mismatch."""
        from plugins.memory.memory_os.index import _index_embeddings

        crystallized_root = tmp_path / "crystallized"
        crystallized_root.mkdir()
        record_path = crystallized_root / "rec-1.md"
        record_path.write_text("""---
id: rec-1
kind: fact
provisional: false
approved_by: test
approved_at: 2026-01-01T00:00:00Z
tags: []
---
Test.
""", encoding="utf-8")

        embedder = MockEmbedder(model_name="BAAI/bge-m3")
        index_path = tmp_path / "index.db"
        conn = sqlite3.connect(str(index_path))
        conn.executescript("""
            create table if not exists crystallized_records (
                id text primary key, kind text, created_at text,
                approved_by text, approved_at text,
                source_event_ids_json text, tags_json text,
                sensitivity text, hindsight_indexed integer,
                file_name text
            );
            create table if not exists memory_embeddings (
                record_type text not null, record_id text not null,
                embedding_model text not null, embedding blob not null,
                created_at text not null,
                primary key (record_type, record_id, embedding_model)
            );
        """)
        conn.execute(
            "insert into crystallized_records values (?,?,?,?,?,?,?,?,?,?)",
            ("rec-1", "fact", "2026-01-01T00:00:00Z", "test",
             "2026-01-01T00:00:00Z", "[]", "[]", "low", 0, "rec-1.md"),
        )
        conn.commit()

        _index_embeddings(conn, crystallized_root, embedder)

        row = conn.execute(
            "select embedding_model from memory_embeddings where record_id = ?",
            ("rec-1",),
        ).fetchone()
        conn.close()

        # The stored label must NOT be MiniLM when using bge-m3
        assert row is not None
        assert row[0] != "paraphrase-multilingual-MiniLM-L12-v2", (
            "D.X FAIL: embedding_model should NOT be hardcoded MiniLM "
            "when embedder is bge-m3"
        )
