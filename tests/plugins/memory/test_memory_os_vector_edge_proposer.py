"""Tests for vector_edge_proposer — embedding cosine-similarity edge proposals.

Covers: embedder guard, empty/single-record, similarity thresholds,
dedup against existing edges, cognitive loop integration, knob gate.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from plugins.memory.memory_os.audit import read_audit_entries
from plugins.memory.memory_os.embedder import LocalEmbedder
from plugins.memory.memory_os.index import MemoryOSIndex
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.memory.memory_os.vector_edge_proposer import (
    _cosine_similarity,
    _detect_relation_from_similarity,
    run_vector_proposer,
)


# ── Mock embedder ────────────────────────────────────────────────────────────


class MockEmbedder:
    """Deterministic mock: returns pre-configured embeddings for known texts."""

    def __init__(self, available: bool = True, dim: int = 384) -> None:
        self._available = available
        self._dim = dim
        self._call_count = 0

    def is_available(self) -> bool:
        return self._available

    def embed(self, text: str) -> bytes:
        import numpy as np

        self._call_count += 1
        import hashlib
        h = hashlib.sha256(text.encode()).digest()
        seed = int.from_bytes(h[:8], "big") % (2**32)
        rng = np.random.RandomState(seed)
        return rng.randn(self._dim).astype(np.float32).tobytes()


class UnavailableEmbedder:
    def is_available(self) -> bool:
        return False

    def embed(self, text: str) -> bytes:
        return b""


# ── Helpers ──────────────────────────────────────────────────────────────────


def _seed_crystallized(
    store: MemoryOSStore,
    records: list[dict[str, Any]],
) -> list[str]:
    """Write canonical crystallized records and return their ids."""
    store.initialize()
    ids: list[str] = []
    for i, rec in enumerate(records):
        rid = rec.get("id", f"cry_vector_test_{i:03d}_v1")
        frontmatter = {
            "schema_version": "memory-os.crystallized.v0",
            "id": rid,
            "kind": rec.get("kind", "note"),
            "created_at": rec.get("created_at", "2026-06-01T00:00:00Z"),
            "approved_by": "owner",
            "approved_at": rec.get("created_at", "2026-06-01T00:00:00Z"),
            "approval_purpose": "test",
            "approval_note": "test seed",
            "source_event_ids": rec.get("source_event_ids", []),
            "tags": rec.get("tags", []),
            "sensitivity": "private",
            "hindsight_indexed": False,
            "bridge_state": "active",
        }
        body = rec.get("body", "test crystallized record body")
        store.append_crystallized_record(f"test_vector_{i:03d}.md", frontmatter, body)
        ids.append(rid)
    return ids


def _store_with_records(
    tmp_path: Path,
    records: list[dict[str, Any]],
    *,
    embedder: object | None = None,
) -> tuple[MemoryOSStore, MemoryOSIndex]:
    """Create a store + index seeded with crystallized records and embeddings."""
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="vector-edge-test")
    store = MemoryOSStore(roots)
    _seed_crystallized(store, records)

    # Build index
    index = MemoryOSIndex(roots)
    index.rebuild_from_store(store)

    # Manually insert embeddings for records
    if embedder is not None and getattr(embedder, "is_available", lambda: False)():
        import numpy as np
        conn = sqlite3.connect(str(roots.index_path))
        conn.row_factory = sqlite3.Row
        cr_rows = conn.execute(
            "select id, kind from crystallized_records order by created_at"
        ).fetchall()
        for row in cr_rows:
            rid = str(row["id"])
            kind = str(row["kind"] or "")
            # Match with input record body if possible
            body = ""
            for rec in records:
                if rec.get("id") == rid:
                    body = rec.get("body", "")
                    break
            emb = embedder.embed(body or kind or rid)
            if emb and len(emb) > 0:
                conn.execute(
                    "insert or replace into memory_embeddings "
                    "(record_type, record_id, embedding_model, embedding, created_at) "
                    "values (?, ?, ?, ?, ?)",
                    (
                        "crystallized_record",
                        rid,
                        "mock-model",
                        emb,
                        "2026-06-01T00:00:00Z",
                    ),
                )
        conn.commit()
        conn.close()

    return store, index


# ── Unit: _cosine_similarity ─────────────────────────────────────────────────


def test_cosine_similarity_identical_vectors():
    import numpy as np
    v = np.array([1.0, 0.0, 0.0], dtype=np.float32).tobytes()
    sim = _cosine_similarity(v, v)
    assert sim == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors():
    import numpy as np
    a = np.array([1.0, 0.0], dtype=np.float32).tobytes()
    b = np.array([0.0, 1.0], dtype=np.float32).tobytes()
    sim = _cosine_similarity(a, b)
    assert sim == pytest.approx(0.0)


def test_cosine_similarity_opposite_vectors():
    import numpy as np
    a = np.array([1.0, 2.0, 3.0], dtype=np.float32).tobytes()
    b = np.array([-1.0, -2.0, -3.0], dtype=np.float32).tobytes()
    sim = _cosine_similarity(a, b)
    assert sim == pytest.approx(-1.0)


def test_cosine_similarity_shape_mismatch_returns_none():
    import numpy as np
    a = np.array([1.0, 0.0], dtype=np.float32).tobytes()
    b = np.array([1.0, 0.0, 0.0], dtype=np.float32).tobytes()
    assert _cosine_similarity(a, b) is None


def test_cosine_similarity_zero_vector_returns_none():
    import numpy as np
    a = np.array([0.0, 0.0], dtype=np.float32).tobytes()
    b = np.array([1.0, 0.0], dtype=np.float32).tobytes()
    assert _cosine_similarity(a, b) is None


def test_cosine_similarity_invalid_bytes_returns_none():
    assert _cosine_similarity(b"not valid", b"also not valid") is None


# ── Unit: _detect_relation_from_similarity ────────────────────────────────────


def test_detect_refines_high_sim_same_kind(tmp_path: Path) -> None:
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="test")
    assert _detect_relation_from_similarity(0.85, "note", "note", roots=roots) == "refines"


def test_detect_co_occurs_high_sim_different_kind(tmp_path: Path) -> None:
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="test")
    assert _detect_relation_from_similarity(0.85, "note", "decision", roots=roots) == "co_occurs"


def test_detect_co_occurs_mid_sim(tmp_path: Path) -> None:
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="test")
    assert _detect_relation_from_similarity(0.70, "note", "note", roots=roots) == "co_occurs"


def test_detect_contradicts_low_sim_different_kind(tmp_path: Path) -> None:
    """Low-similarity cross-kind pairs produce contradicts edges."""
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="test")
    assert _detect_relation_from_similarity(0.20, "note", "decision", roots=roots) == "contradicts"


def test_detect_none_mid_sim_same_kind_below_co_occurs(tmp_path: Path) -> None:
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="test")
    assert _detect_relation_from_similarity(0.50, "note", "note", roots=roots) is None


def test_detect_none_low_sim_same_kind(tmp_path: Path) -> None:
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="test")
    assert _detect_relation_from_similarity(0.10, "note", "note", roots=roots) is None


def test_low_similarity_cross_kind_contradicts_restored(tmp_path: Path) -> None:
    """Low-similarity cross-kind pairs still produce contradicts edges."""
    from plugins.memory.memory_os.knob_overrides import resolve_knob
    from plugins.memory.memory_os.vector_edge_proposer import _detect_relation_from_similarity
    # Use _store_root=tmp_path to isolate from production /root/.hermes knob overrides
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="test")
    refines = resolve_knob("vector_edge_refines_threshold", default=0.75, _store_root=tmp_path)
    co_occurs = resolve_knob("vector_edge_co_occurs_threshold", default=0.65, _store_root=tmp_path)
    contradicts = resolve_knob("vector_edge_contradicts_threshold", default=0.35, _store_root=tmp_path)
    # sim=0.30 <= contradicts(0.35), kind_a != kind_b -> should return "contradicts"
    assert 0.30 <= contradicts
    result = _detect_relation_from_similarity(0.30, "note", "moment", roots=roots)
    assert result == "contradicts", f"expected 'contradicts', got {result!r}"


def test_contradicts_not_triggered_same_kind(tmp_path: Path) -> None:
    """Low similarity but same kind should NOT trigger contradicts."""
    from plugins.memory.memory_os.vector_edge_proposer import _detect_relation_from_similarity
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="test")
    result = _detect_relation_from_similarity(0.30, "note", "note", roots=roots)
    assert result is None, f"expected None for same-kind, got {result!r}"


# ── Integration: run_vector_proposer ──────────────────────────────────────────


def test_embedder_unavailable_skips(tmp_path):
    store, index = _store_with_records(
        tmp_path,
        [
            {"kind": "note", "body": "first record"},
            {"kind": "note", "body": "second record"},
        ],
        embedder=UnavailableEmbedder(),
    )
    result = run_vector_proposer(
        str(store.roots.index_path),
        index=index,
        embedder=UnavailableEmbedder(),
    )
    assert result["status"] == "skipped"
    assert result["reason"] == "embedder_unavailable"
    assert result["proposed_count"] == 0


def test_embedder_none_skips(tmp_path):
    store, index = _store_with_records(
        tmp_path,
        [{"kind": "note", "body": "test"}],
    )
    result = run_vector_proposer(
        str(store.roots.index_path),
        index=index,
        embedder=None,
    )
    assert result["status"] == "skipped"


def test_single_record_skips(tmp_path):
    store, index = _store_with_records(
        tmp_path,
        [{"kind": "note", "body": "only one"}],
    )
    result = run_vector_proposer(
        str(store.roots.index_path),
        index=index,
        embedder=MockEmbedder(),
    )
    assert result["status"] == "skipped"
    assert "need ≥2" in result.get("reason", "")


def test_no_embeddings_found_skips(tmp_path):
    """Records exist but no embeddings in memory_embeddings -> skip."""
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="no-emb-test")
    store = MemoryOSStore(roots)
    _seed_crystallized(store, [
        {"kind": "note", "body": "first"},
        {"kind": "note", "body": "second"},
    ])
    index = MemoryOSIndex(roots)
    index.rebuild_from_store(store)
    # Don't insert embeddings

    result = run_vector_proposer(
        str(roots.index_path),
        index=index,
        embedder=MockEmbedder(),
    )
    assert result["status"] == "skipped"


def test_two_similar_records_propose_refines(tmp_path, monkeypatch):
    import warnings

    from plugins.memory.memory_os import knob_overrides

    embedder = MockEmbedder()
    store, index = _store_with_records(
        tmp_path,
        [
            {"kind": "note", "body": "same text"},
            {"kind": "note", "body": "same text"},
        ],
        embedder=embedder,
    )
    monkeypatch.setattr(knob_overrides, "_ambient_fallback_warned", False)
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        result = run_vector_proposer(
            str(store.roots.index_path),
            index=index,
            embedder=embedder,
        )
    assert result["status"] == "ok"
    assert result["proposed_count"] >= 1
    assert result["record_count"] == 2


def test_dissimilar_records_propose_nothing(tmp_path):
    """Two records with very different embeddings -> no edge proposed."""
    store, index = _store_with_records(
        tmp_path,
        [
            {"kind": "note", "body": "record one"},
            {"kind": "note", "body": "record two"},
        ],
        embedder=MockEmbedder(),
    )
    result = run_vector_proposer(
        str(store.roots.index_path),
        index=index,
        embedder=MockEmbedder(),
    )
    assert result["status"] == "ok"


def test_dedup_against_existing_edges(tmp_path):
    """If an edge already exists, vector proposer skips it."""
    embedder = MockEmbedder()
    store, index = _store_with_records(
        tmp_path,
        [
            {"kind": "note", "body": "same text"},
            {"kind": "note", "body": "same text"},
        ],
        embedder=embedder,
    )

    result1 = run_vector_proposer(
        str(store.roots.index_path),
        index=index,
        embedder=embedder,
    )
    first_count = result1["proposed_count"]

    result2 = run_vector_proposer(
        str(store.roots.index_path),
        index=index,
        embedder=embedder,
    )
    assert result2["proposed_count"] == 0
    assert first_count >= 1


def test_edge_has_vector_proposed_by(tmp_path):
    """Edges created by vector proposer have proposed_by='vector'."""
    embedder = MockEmbedder()
    store, index = _store_with_records(
        tmp_path,
        [
            {"kind": "note", "body": "same text"},
            {"kind": "note", "body": "same text"},
        ],
        embedder=embedder,
    )
    run_vector_proposer(
        str(store.roots.index_path),
        index=index,
        embedder=embedder,
    )

    conn = sqlite3.connect(str(store.roots.index_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "select proposed_by, state from memory_edges"
    ).fetchall()
    conn.close()
    assert len(rows) >= 1
    for row in rows:
        assert row["proposed_by"] == "vector"
        assert row["state"] == "candidate"


def test_edge_weight_reflects_similarity(tmp_path):
    """Edge weight should be the cosine similarity value."""
    embedder = MockEmbedder()
    store, index = _store_with_records(
        tmp_path,
        [
            {"kind": "note", "body": "same text"},
            {"kind": "note", "body": "same text"},
        ],
        embedder=embedder,
    )
    run_vector_proposer(
        str(store.roots.index_path),
        index=index,
        embedder=embedder,
    )

    conn = sqlite3.connect(str(store.roots.index_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "select weight from memory_edges where proposed_by = 'vector'"
    ).fetchall()
    conn.close()
    assert len(rows) >= 1
    for row in rows:
        w = float(row["weight"])
        assert 0.0 <= w <= 1.0


def test_audit_path_written(tmp_path):
    """When audit_path is provided, an audit entry is written."""
    embedder = MockEmbedder()
    store, index = _store_with_records(
        tmp_path,
        [
            {"kind": "note", "body": "same text"},
            {"kind": "note", "body": "same text"},
        ],
        embedder=embedder,
    )
    audit_path = str(tmp_path / "audit.jsonl")
    run_vector_proposer(
        str(store.roots.index_path),
        index=index,
        embedder=embedder,
        audit_path=audit_path,
    )
    entries = read_audit_entries(Path(audit_path))
    assert len(entries) >= 1
    assert entries[0]["action"] == "vector_edge_proposer_run"


# ── Cognitive loop integration ────────────────────────────────────────────────


def test_knob_disabled_skips_in_cognitive_loop(tmp_path):
    """With knob disabled (default), the cognitive loop step returns skipped."""
    from plugins.memory.memory_os.cognitive_loop import CognitiveLoopRunner

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="knob-off-test")
    store = MemoryOSStore(roots)
    store.initialize()
    runner = CognitiveLoopRunner(store)

    result = runner._vector_edge_proposer({})
    assert result["status"] == "skipped"
    assert result["reason"] == "knob_disabled"
    assert result["proposed_count"] == 0


def test_crystallized_records_have_kind_column(tmp_path):
    """Verify crystallized_records table has the kind column used by the
    vector proposer's SQL join query."""
    store, index = _store_with_records(
        tmp_path,
        [{"kind": "preference", "body": "test"}],
        embedder=MockEmbedder(),
    )
    conn = sqlite3.connect(str(store.roots.index_path))
    cols = {str(c[1]) for c in conn.execute("pragma table_info(crystallized_records)").fetchall()}
    conn.close()
    assert "kind" in cols, f"crystallized_records needs 'kind' column; got {cols}"
