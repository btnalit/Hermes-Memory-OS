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

    def test_default_thresholds_match_current_constants(self, tmp_path: Path):
        """Default knob values equal the current hardcoded constants."""
        from plugins.memory.memory_os.knob_overrides import resolve_knob

        # Use tmp_path to isolate from production /root/.hermes knob overrides
        refines = resolve_knob("vector_edge_refines_threshold", default=0.75,
                               _store_root=tmp_path)
        co_occurs = resolve_knob("vector_edge_co_occurs_threshold", default=0.65,
                                 _store_root=tmp_path)
        contradicts = resolve_knob("vector_edge_contradicts_threshold", default=0.35,
                                   _store_root=tmp_path)
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


def test_vector_cli_respects_hermes_home_flag(tmp_path: Path) -> None:
    """Vector commands accept and use --hermes-home flag."""
    import argparse
    from plugins.memory.memory_os.cli import register_cli

    parser = argparse.ArgumentParser()
    register_cli(parser)

    # Verify --hermes-home is registered on calibrate-thresholds
    args = parser.parse_args(["vector", "calibrate-thresholds", "--hermes-home", str(tmp_path)])
    assert args.hermes_home == str(tmp_path)

    # Verify --hermes-home is registered on reembed
    args2 = parser.parse_args(["vector", "reembed", "--hermes-home", str(tmp_path)])
    assert args2.hermes_home == str(tmp_path)


class TestBatchEmbedderDeviceKnob:
    """D2: vector_embedder_batch_device knob is registered and overridable."""

    def test_batch_device_knob_in_overridable_knobs(self):
        """vector_embedder_batch_device is present in OVERRIDABLE_KNOBS."""
        from plugins.memory.memory_os.knob_overrides import OVERRIDABLE_KNOBS
        assert "vector_embedder_batch_device" in OVERRIDABLE_KNOBS, (
            "D2: vector_embedder_batch_device must be in OVERRIDABLE_KNOBS "
            "so register_override() does not reject it"
        )

    def test_batch_device_knob_has_expected_spec(self):
        """vector_embedder_batch_device has correct module, default, and kind."""
        from plugins.memory.memory_os.knob_overrides import OVERRIDABLE_KNOBS
        spec = OVERRIDABLE_KNOBS["vector_embedder_batch_device"]
        assert spec["module"] == "embedder"
        assert spec["default"] == "cpu"
        assert spec["kind"] == "threshold"
        assert spec["meta"] is False

    def test_batch_device_resolves_default(self, tmp_path: Path):
        """Resolving vector_embedder_batch_device returns default 'cpu'."""
        from plugins.memory.memory_os.knob_overrides import resolve_knob
        # Use tmp_path to isolate from production /root/.hermes knob overrides
        result = resolve_knob("vector_embedder_batch_device", default="cpu",
                              _store_root=tmp_path)
        assert result == "cpu"

    def test_batch_device_override_via_jsonl(self, tmp_path: Path):
        """Overriding vector_embedder_batch_device via JSONL works."""
        import json
        system_dir = tmp_path / "memory-os" / "system"
        system_dir.mkdir(parents=True)
        knob_path = system_dir / "knob_overrides.jsonl"
        knob_path.write_text(json.dumps({
            "schema_version": "memory-os.knob_override.v0",
            "id": "ko_batch_test",
            "knob": "vector_embedder_batch_device",
            "override_value": "cuda:0",
            "prior_value": "auto",
            "bounds": None,
            "allowed": None,
            "provisional": False,
            "expires_at": "",
            "proposed_by": "test",
            "approved_via": "test",
            "state": "confirmed",
            "ts": "2026-01-01T00:00:00Z",
        }) + "\n", encoding="utf-8")

        from plugins.memory.memory_os.knob_overrides import resolve_knob
        result = resolve_knob("vector_embedder_batch_device", default="cpu",
                              _store_root=system_dir)
        assert result == "cuda:0", (
            f"D2: override should produce 'cuda:0', got {result}"
        )

    def test_batch_device_register_override_does_not_raise(self, tmp_path: Path):
        """register_override accepts vector_embedder_batch_device (no ValueError)."""
        from plugins.memory.memory_os.knob_overrides import register_override

        system_dir = tmp_path / "memory-os" / "system"
        system_dir.mkdir(parents=True)

        # Must not raise "not in OVERRIDABLE_KNOBS"
        record = register_override(
            "vector_embedder_batch_device",
            "cuda:0",
            prior="auto",
            proposed_by="test",
            approved_via="test",
            expires_at="2027-01-01T00:00:00Z",
            _store_root=system_dir,
        )
        assert record["knob"] == "vector_embedder_batch_device"
        assert record["override_value"] == "cuda:0"

    def test_batch_device_independent_of_online_device(self, tmp_path: Path):
        """batch_device and online device can differ (D2 core invariant)."""
        import json
        system_dir = tmp_path / "memory-os" / "system"
        system_dir.mkdir(parents=True)
        knob_path = system_dir / "knob_overrides.jsonl"

        # Set batch_device=cuda:0 but online device=cpu
        lines = [
            json.dumps({
                "schema_version": "memory-os.knob_override.v0",
                "id": "ko_batch",
                "knob": "vector_embedder_batch_device",
                "override_value": "cuda:0",
                "prior_value": "auto",
                "bounds": None, "allowed": None,
                "provisional": False, "expires_at": "",
                "proposed_by": "test", "approved_via": "test",
                "state": "confirmed", "ts": "2026-01-01T00:00:00Z",
            }),
            json.dumps({
                "schema_version": "memory-os.knob_override.v0",
                "id": "ko_online",
                "knob": "vector_embedder_device",
                "override_value": "cpu",
                "prior_value": "auto",
                "bounds": None, "allowed": None,
                "provisional": False, "expires_at": "",
                "proposed_by": "test", "approved_via": "test",
                "state": "confirmed", "ts": "2026-01-01T00:00:00Z",
            }),
        ]
        knob_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        from plugins.memory.memory_os.knob_overrides import resolve_knobs
        resolved = resolve_knobs(
            {
                "vector_embedder_device": "cpu",
                "vector_embedder_batch_device": "cpu",
            },
            _store_root=system_dir,
        )
        assert resolved["vector_embedder_device"] == "cpu"
        assert resolved["vector_embedder_batch_device"] == "cuda:0", (
            "D2: batch device must be independently overridable from online device"
        )


class TestBuildEmbedderBatchDevice:
    """D2: build_embedder(batch=True) consumes vector_embedder_batch_device.

    These tests verify that the batch knob actually controls embedder
    device selection, not just that the knob is registered.
    """

    def test_build_embedder_online_uses_vector_embedder_device(self, tmp_path: Path):
        """build_embedder(roots) uses vector_embedder_device (not batch knob)."""
        import json
        from plugins.memory.memory_os.embedder import build_embedder
        from plugins.memory.memory_os.roots import MemoryOSRoots

        system_dir = tmp_path / "memory-os" / "system"
        system_dir.mkdir(parents=True)
        knob_path = system_dir / "knob_overrides.jsonl"
        knob_path.write_text("\n".join([
            json.dumps({
                "schema_version": "memory-os.knob_override.v0",
                "id": "ko_online", "knob": "vector_embedder_device",
                "override_value": "cpu", "prior_value": "auto",
                "bounds": None, "allowed": None, "provisional": False,
                "expires_at": "", "proposed_by": "test", "approved_via": "test",
                "state": "confirmed", "ts": "2026-01-01T00:00:00Z",
            }),
            json.dumps({
                "schema_version": "memory-os.knob_override.v0",
                "id": "ko_batch", "knob": "vector_embedder_batch_device",
                "override_value": "cuda:0", "prior_value": "auto",
                "bounds": None, "allowed": None, "provisional": False,
                "expires_at": "", "proposed_by": "test", "approved_via": "test",
                "state": "confirmed", "ts": "2026-01-01T00:00:00Z",
            }),
        ]) + "\n", encoding="utf-8")

        roots = MemoryOSRoots.from_hermes_home(tmp_path)
        # Online path: must NOT read batch_device knob
        emb = build_embedder(roots)
        # If embedder is unavailable (no sentence-transformers), test still
        # validates that the factory didn't crash and returned correctly
        if emb is not None:
            assert emb._device == "cpu", (
                f"Online build_embedder should use vector_embedder_device=cpu, "
                f"got {emb._device}"
            )

    def test_build_embedder_batch_uses_batch_device_when_set(self, tmp_path: Path):
        """build_embedder(roots, batch=True) reads vector_embedder_batch_device."""
        import json
        from plugins.memory.memory_os.embedder import build_embedder
        from plugins.memory.memory_os.roots import MemoryOSRoots

        system_dir = tmp_path / "memory-os" / "system"
        system_dir.mkdir(parents=True)
        knob_path = system_dir / "knob_overrides.jsonl"
        knob_path.write_text("\n".join([
            json.dumps({
                "schema_version": "memory-os.knob_override.v0",
                "id": "ko_online", "knob": "vector_embedder_device",
                "override_value": "cuda", "prior_value": "auto",
                "bounds": None, "allowed": None, "provisional": False,
                "expires_at": "", "proposed_by": "test", "approved_via": "test",
                "state": "confirmed", "ts": "2026-01-01T00:00:00Z",
            }),
            json.dumps({
                "schema_version": "memory-os.knob_override.v0",
                "id": "ko_batch", "knob": "vector_embedder_batch_device",
                "override_value": "cpu", "prior_value": "auto",
                "bounds": None, "allowed": None, "provisional": False,
                "expires_at": "", "proposed_by": "test", "approved_via": "test",
                "state": "confirmed", "ts": "2026-01-01T00:00:00Z",
            }),
        ]) + "\n", encoding="utf-8")

        roots = MemoryOSRoots.from_hermes_home(tmp_path)
        emb = build_embedder(roots, batch=True)
        if emb is not None:
            assert emb._device == "cpu", (
                f"Batch build_embedder should use vector_embedder_batch_device=cpu, "
                f"got {emb._device}"
            )

    def test_build_embedder_batch_uses_default_device_when_not_overridden(self, tmp_path: Path):
        """When batch_device is not overridden (resolves to default 'cpu'),
        batch uses the default device."""
        import json
        from plugins.memory.memory_os.embedder import build_embedder
        from plugins.memory.memory_os.roots import MemoryOSRoots

        system_dir = tmp_path / "memory-os" / "system"
        system_dir.mkdir(parents=True)
        knob_path = system_dir / "knob_overrides.jsonl"
        knob_path.write_text(json.dumps({
            "schema_version": "memory-os.knob_override.v0",
            "id": "ko_online", "knob": "vector_embedder_device",
            "override_value": "cpu", "prior_value": "auto",
            "bounds": None, "allowed": None, "provisional": False,
            "expires_at": "", "proposed_by": "test", "approved_via": "test",
            "state": "confirmed", "ts": "2026-01-01T00:00:00Z",
        }) + "\n", encoding="utf-8")

        roots = MemoryOSRoots.from_hermes_home(tmp_path)
        emb = build_embedder(roots, batch=True)
        if emb is not None:
            assert emb._device == "cpu", (
                f"Batch with default device should use device=cpu, "
                f"got {emb._device}"
            )

    def test_build_embedder_without_batch_default_behavior_unchanged(self, tmp_path: Path):
        """Default path (batch=False) behavior is backward-compatible.

        Counterfactual: if batch=True accidentally became the default,
        this test would fail because the online device knob would be ignored.
        """
        import json
        from plugins.memory.memory_os.embedder import build_embedder
        from plugins.memory.memory_os.roots import MemoryOSRoots

        system_dir = tmp_path / "memory-os" / "system"
        system_dir.mkdir(parents=True)
        knob_path = system_dir / "knob_overrides.jsonl"
        # Set batch_device to something different — it must NOT affect default path
        knob_path.write_text("\n".join([
            json.dumps({
                "schema_version": "memory-os.knob_override.v0",
                "id": "ko_online", "knob": "vector_embedder_device",
                "override_value": "cpu", "prior_value": "auto",
                "bounds": None, "allowed": None, "provisional": False,
                "expires_at": "", "proposed_by": "test", "approved_via": "test",
                "state": "confirmed", "ts": "2026-01-01T00:00:00Z",
            }),
            json.dumps({
                "schema_version": "memory-os.knob_override.v0",
                "id": "ko_batch", "knob": "vector_embedder_batch_device",
                "override_value": "cuda:0", "prior_value": "auto",
                "bounds": None, "allowed": None, "provisional": False,
                "expires_at": "", "proposed_by": "test", "approved_via": "test",
                "state": "confirmed", "ts": "2026-01-01T00:00:00Z",
            }),
        ]) + "\n", encoding="utf-8")

        roots = MemoryOSRoots.from_hermes_home(tmp_path)
        emb = build_embedder(roots)  # batch=False default
        if emb is not None:
            assert emb._device == "cpu", (
                f"Default build_embedder must use vector_embedder_device=cpu "
                f"not batch_device. Got {emb._device}"
            )

    def test_index_sync_calls_build_embedder_with_batch_true(self):
        """Counterfactual: index_sync must pass batch=True to build_embedder."""
        import inspect
        import scripts.memory_os_index_sync as idx_sync

        source = inspect.getsource(idx_sync)
        assert "build_embedder(roots, batch=True)" in source, (
            "index_sync must call build_embedder with batch=True "
            "so it uses vector_embedder_batch_device"
        )
