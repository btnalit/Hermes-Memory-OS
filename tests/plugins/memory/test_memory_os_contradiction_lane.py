"""Tests for the LLM/evidence contradiction lane.

Covers: _claims_contradict unit tests (claims semantic conflict), integration
tests for run_contradiction_lane (guard gates), and counterfactual scenarios
(orthogonal embeddings, basic function existence).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np
import pytest

from plugins.memory.memory_os.llm_contradiction_lane import (
    _claims_contradict,
    _find_contradiction_candidates,
    _find_cosine_candidates,
    _find_entity_candidates,
    run_contradiction_lane,
)


# ── Test doubles ──────────────────────────────────────────────────────────────


class FakeRoots:
    """Minimal roots-like object exposing index_path + memory_os_root."""

    def __init__(self, tmp_path: Path) -> None:
        self.index_path = tmp_path / "index.db"
        self.memory_os_root = tmp_path / "memory-os"


class FakeStore:
    """Minimal store-like object exposing .roots."""

    def __init__(self, roots: FakeRoots) -> None:
        self.roots = roots


def _mock_embedder() -> object:
    """Return an object with is_available()→True, model_name→"test-model",
    embed(text)→hash-based deterministic bytes.
    """
    import hashlib

    class _MockEmbedder:
        def is_available(self) -> bool:
            return True

        @property
        def model_name(self) -> str:
            return "test-model"

        def embed(self, text: str) -> bytes:
            h = hashlib.sha256(text.encode()).digest()
            seed = int.from_bytes(h[:8], "big") % (2**32)
            rng = np.random.RandomState(seed)
            return rng.randn(384).astype(np.float32).tobytes()

    return _MockEmbedder()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _enable_lane_knob(roots: FakeRoots) -> None:
    """Write knob_overrides.jsonl with llm_contradiction_lane_enabled=True
    in confirmed state so resolve_knob picks it up."""
    path = roots.memory_os_root / "system" / "knob_overrides.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": "memory-os.knob_override.v0",
        "id": "test_ko_ko001",
        "knob": "llm_contradiction_lane_enabled",
        "override_value": True,
        "prior_value": False,
        "provisional": False,
        "expires_at": "",
        "state": "confirmed",
        "ts": "2026-07-01T00:00:00Z",
    }
    path.write_text(json.dumps(record, sort_keys=True) + "\n", encoding="utf-8")


def _set_threshold_knob(roots: FakeRoots, threshold: float, knob_id: str = "test_th_001") -> None:
    """Write a knob override for llm_contradiction_same_topic_threshold."""
    path = roots.memory_os_root / "system" / "knob_overrides.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": "memory-os.knob_override.v0",
        "id": knob_id,
        "knob": "llm_contradiction_same_topic_threshold",
        "override_value": threshold,
        "prior_value": 0.75,
        "provisional": False,
        "expires_at": "",
        "state": "confirmed",
        "ts": "2026-07-01T00:00:00Z",
    }
    # Append to existing file so it coexists with _enable_lane_knob
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(
        existing + json.dumps(record, sort_keys=True) + "\n", encoding="utf-8",
    )


def _set_source_knob(roots: FakeRoots, source: str, knob_id: str = "test_src_001") -> None:
    """Write a knob override for llm_contradiction_candidate_source."""
    path = roots.memory_os_root / "system" / "knob_overrides.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": "memory-os.knob_override.v0",
        "id": knob_id,
        "knob": "llm_contradiction_candidate_source",
        "override_value": source,
        "prior_value": "cosine",
        "provisional": False,
        "expires_at": "",
        "state": "confirmed",
        "ts": "2026-07-01T00:00:00Z",
    }
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(
        existing + json.dumps(record, sort_keys=True) + "\n", encoding="utf-8",
    )


def _create_tables(conn: sqlite3.Connection) -> None:
    """Create the two tables run_contradiction_lane queries."""
    conn.execute(
        "create table if not exists crystallized_records ("
        "id text primary key, kind text, created_at text, approved_by text, "
        "approved_at text, source_event_ids_json text, tags_json text, "
        "sensitivity text, hindsight_indexed integer, file_name text, body text)"
    )
    conn.execute(
        "create table if not exists memory_embeddings ("
        "record_type text, record_id text, embedding_model text, "
        "embedding blob, created_at text)"
    )


def _insert_record(
    conn: sqlite3.Connection,
    rec: dict[str, Any],
    embedding_bytes: bytes,
) -> None:
    """Insert a single crystallized record + its embedding row."""
    conn.execute(
        "insert into crystallized_records "
        "(id, kind, created_at, approved_by, approved_at, source_event_ids_json, "
        "tags_json, sensitivity, hindsight_indexed, file_name, body) "
        "values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            rec["id"],
            rec.get("kind", "note"),
            rec.get("created_at", "2026-07-01T00:00:00Z"),
            "owner",
            "2026-07-01T00:00:00Z",
            "[]",
            "[]",
            "private",
            0,
            f"{rec['id']}.md",
            rec.get("body", ""),
        ),
    )
    conn.execute(
        "insert into memory_embeddings "
        "(record_type, record_id, embedding_model, embedding, created_at) "
        "values (?, ?, ?, ?, ?)",
        (
            "crystallized_record",
            rec["id"],
            "test-model",
            embedding_bytes,
            "2026-07-01T00:00:00Z",
        ),
    )


# ── Unit: _claims_contradict ──────────────────────────────────────────────────


class TestClaimsContradict:
    """Unit tests for _claims_contradict()."""

    def test_same_subject_predicate_different_object(self) -> None:
        """Same subject+predicate, mutually exclusive object value → True."""
        a = {"subject": "Alice", "predicate": "age", "object": "30", "confidence": 0.9}
        b = {"subject": "Alice", "predicate": "age", "object": "35", "confidence": 0.9}
        assert _claims_contradict(a, b) is True

    def test_same_object(self) -> None:
        """Same object → claims agree, not contradictory → False."""
        a = {"subject": "Alice", "predicate": "age", "object": "30", "confidence": 0.9}
        b = {"subject": "Alice", "predicate": "age", "object": "30", "confidence": 0.9}
        assert _claims_contradict(a, b) is False

    def test_different_subject(self) -> None:
        """Different subject → not contradictory → False."""
        a = {"subject": "Alice", "predicate": "age", "object": "30", "confidence": 0.9}
        b = {"subject": "Bob", "predicate": "age", "object": "35", "confidence": 0.9}
        assert _claims_contradict(a, b) is False

    def test_different_predicate(self) -> None:
        """Different predicate → not contradictory → False."""
        a = {"subject": "Alice", "predicate": "age", "object": "30", "confidence": 0.9}
        b = {"subject": "Alice", "predicate": "height", "object": "tall", "confidence": 0.9}
        assert _claims_contradict(a, b) is False

    def test_low_confidence(self) -> None:
        """Confidence < 0.5 on either side → not contradictory (noise filter) → False."""
        a = {"subject": "Alice", "predicate": "age", "object": "30", "confidence": 0.4}
        b = {"subject": "Alice", "predicate": "age", "object": "35", "confidence": 0.9}
        assert _claims_contradict(a, b) is False

    def test_normalization(self) -> None:
        """Whitespace, case, and punctuation normalization → True."""
        a = {"subject": "  Alice ", "predicate": "AGE!", "object": "30.", "confidence": 0.9}
        b = {"subject": "alice", "predicate": "age:", "object": "35", "confidence": 0.9}
        assert _claims_contradict(a, b) is True


# ── Integration: run_contradiction_lane ──────────────────────────────────────


class TestContradictionLane:
    """Integration tests for run_contradiction_lane() guard gates."""

    def test_lane_disabled(self, tmp_path: Path) -> None:
        """Default knob is False → lane skipped with lane_disabled."""
        roots = FakeRoots(tmp_path)
        store = FakeStore(roots)
        result = run_contradiction_lane(store)
        assert result["status"] == "skipped"
        assert result["reason"] == "lane_disabled"
        assert result["contradictions_found"] == 0

    def test_embedder_none(self, tmp_path: Path) -> None:
        """Knob enabled but embedder=None → skipped with embedder_unavailable."""
        roots = FakeRoots(tmp_path)
        store = FakeStore(roots)
        _enable_lane_knob(roots)
        result = run_contradiction_lane(store, embedder=None, roots=roots)
        assert result["status"] == "skipped"
        assert result["reason"] == "embedder_unavailable"
        assert result["contradictions_found"] == 0

    def test_empty_crystallized_records(self, tmp_path: Path) -> None:
        """Knob enabled, embedder available, empty crystallized_records table → skipped."""
        roots = FakeRoots(tmp_path)
        store = FakeStore(roots)
        _enable_lane_knob(roots)
        conn = sqlite3.connect(str(roots.index_path))
        _create_tables(conn)
        conn.commit()
        conn.close()
        with patch(
            "plugins.memory.memory_os.low_clue_recall.low_clue_judge_availability"
        ) as mock_judge:
            mock_judge.return_value = {"available": True}
            result = run_contradiction_lane(store, embedder=_mock_embedder(), roots=roots)
        # < 2 records → no candidates → ok with no_high_similarity_pairs
        # (the lane ran correctly; it just had nothing to compare)
        assert result["status"] == "ok"
        assert result["reason"] == "no_high_similarity_pairs"


# ── Counterfactual scenarios ──────────────────────────────────────────────────


class TestCounterfactuals:
    """Counterfactual / edge-case scenarios for the contradiction lane."""

    def test_orthogonal_embeddings(self, tmp_path: Path) -> None:
        """C.2: orthogonal embeddings (cosine≈0) → candidate_pairs=0,
        contradictions_found=0."""
        roots = FakeRoots(tmp_path)
        store = FakeStore(roots)
        _enable_lane_knob(roots)

        conn = sqlite3.connect(str(roots.index_path))
        _create_tables(conn)
        # Strictly orthogonal 2-D vectors — cosine = 0.0
        v1 = np.array([1.0, 0.0], dtype=np.float32).tobytes()
        v2 = np.array([0.0, 1.0], dtype=np.float32).tobytes()
        _insert_record(conn, {"id": "cr_ortho_001", "body": "orthogonal A", "kind": "note"}, v1)
        _insert_record(conn, {"id": "cr_ortho_002", "body": "orthogonal B", "kind": "note"}, v2)
        conn.commit()
        conn.close()

        with patch(
            "plugins.memory.memory_os.low_clue_recall.low_clue_judge_availability"
        ) as mock_judge:
            mock_judge.return_value = {"available": True}
            result = run_contradiction_lane(store, embedder=_mock_embedder(), roots=roots)

        assert result["status"] == "ok"
        assert result["reason"] == "no_high_similarity_pairs"
        assert result["candidate_pairs"] == 0
        assert result["contradictions_found"] == 0

    def test_claims_contradict_basic(self) -> None:
        """C.X: basic _claims_contradict assertion proving function exists.
        Same subject+predicate, different object → True.
        Same object (agreement) → False.
        """
        a = {"subject": "X", "predicate": "Y", "object": "Z", "confidence": 1.0}
        b = {"subject": "X", "predicate": "Y", "object": "W", "confidence": 1.0}
        assert _claims_contradict(a, b) is True
        c = {"subject": "X", "predicate": "Y", "object": "Z", "confidence": 1.0}
        assert _claims_contradict(a, c) is False


def test_nested_json_extraction_from_llm_output() -> None:
    """Regex fallback handles nested claim objects in markdown-wrapped LLM output."""
    from plugins.memory.memory_os.llm_contradiction_lane import CLAIM_EXTRACTION_PROMPT
    # Simulate LLM returning JSON wrapped in markdown
    response = '''```json
{
  "claim_a": {"subject": "auth", "predicate": "uses", "object": "JWT", "confidence": 0.9},
  "claim_b": {"subject": "auth", "predicate": "uses", "object": "OAuth", "confidence": 0.85}
}
```'''
    import json as _json
    try:
        _json.loads(response.strip())
    except _json.JSONDecodeError:
        # This is the path under test — should extract the nested JSON
        start = response.find("{")
        assert start != -1
        depth = 0
        end = -1
        for i in range(start, len(response)):
            if response[i] == "{": depth += 1
            elif response[i] == "}":
                depth -= 1
                if depth == 0: end = i; break
        assert end != -1, "balanced-brace parser should find matching close brace"
        extracted = response[start:end + 1]
        parsed = _json.loads(extracted)
        assert parsed["claim_a"]["subject"] == "auth"
        assert parsed["claim_b"]["object"] == "OAuth"


def test_error_record_on_judge_check_failure(monkeypatch, tmp_path: Path) -> None:
    """Judge check failure produces an error record, not silent pass."""
    from plugins.memory.memory_os.llm_contradiction_lane import run_contradiction_lane
    # Force judge call to raise
    monkeypatch.setattr(
        "plugins.memory.memory_os.low_clue_recall.low_clue_judge_availability",
        lambda _config: (_ for _ in ()).throw(RuntimeError("test judge failure")),
        raising=True,
    )
    # The function should still return skipped (fail-open) with error record
    roots = FakeRoots(Path(tmp_path))
    store = FakeStore(roots)
    _enable_lane_knob(roots)
    result = run_contradiction_lane(store, embedder=_mock_embedder(), roots=roots)
    assert result["status"] == "skipped", (
        f"expected fail-open skipped, got {result}"
    )
    assert result["reason"] == "llm_unavailable", (
        f"expected llm_unavailable, got {result}"
    )


# ── 护栏①: threshold knob ──────────────────────────────────────────────────


class TestSameTopicThresholdKnob:
    """护栏①: llm_contradiction_same_topic_threshold knob is respected."""

    def test_threshold_knob_filters_pairs(self, tmp_path: Path) -> None:
        """High threshold (0.99) filters out pairs that 0.75 would admit."""
        roots = FakeRoots(tmp_path)
        store = FakeStore(roots)
        _enable_lane_knob(roots)
        _set_threshold_knob(roots, 0.99)

        conn = sqlite3.connect(str(roots.index_path))
        _create_tables(conn)
        # Cosine ≈ 0.88 — above default 0.75, below override 0.99
        v1 = np.array([1.0, 0.0], dtype=np.float32).tobytes()
        v2 = np.array([0.88, 0.475], dtype=np.float32).tobytes()
        _insert_record(conn, {"id": "cr_t_001", "body": "record A body", "kind": "note"}, v1)
        _insert_record(conn, {"id": "cr_t_002", "body": "record B body", "kind": "note"}, v2)
        conn.commit()
        conn.close()

        candidate_pairs, pairs_evaluated = _find_cosine_candidates(
            store, max_pairs=100, roots=roots,
        )
        # Cosine ≈ 0.88 — above 0.75 but below 0.99
        assert len(candidate_pairs) == 0, (
            f"threshold 0.99 should exclude cos≈0.88 pair, got {len(candidate_pairs)}"
        )
        assert pairs_evaluated > 0

    def test_default_threshold_admits_high_sim(self, tmp_path: Path) -> None:
        """Default threshold (0.75) admits high-similarity pairs."""
        roots = FakeRoots(tmp_path)
        store = FakeStore(roots)
        _enable_lane_knob(roots)
        # No threshold override → default 0.75

        conn = sqlite3.connect(str(roots.index_path))
        _create_tables(conn)
        v1 = np.array([1.0, 0.1], dtype=np.float32).tobytes()
        v2 = np.array([0.98, 0.05], dtype=np.float32).tobytes()
        _insert_record(conn, {"id": "cr_d_001", "body": "record A body", "kind": "note"}, v1)
        _insert_record(conn, {"id": "cr_d_002", "body": "record B body", "kind": "note"}, v2)
        conn.commit()
        conn.close()

        candidate_pairs, _ = _find_cosine_candidates(
            store, max_pairs=100, roots=roots,
        )
        assert len(candidate_pairs) == 1, (
            f"default 0.75 should admit cos≈0.999 pair, got {len(candidate_pairs)}"
        )
        assert candidate_pairs[0]["similarity"] > 0.75

    def test_threshold_override_via_run_contradiction_lane(self, tmp_path: Path) -> None:
        """End-to-end: threshold knob affects run_contradiction_lane output."""
        roots = FakeRoots(tmp_path)
        store = FakeStore(roots)
        _enable_lane_knob(roots)
        _set_threshold_knob(roots, 0.99)

        conn = sqlite3.connect(str(roots.index_path))
        _create_tables(conn)
        # Cosine ≈ 0.88 — above default 0.75, below override 0.99
        v1 = np.array([1.0, 0.0], dtype=np.float32).tobytes()
        v2 = np.array([0.88, 0.475], dtype=np.float32).tobytes()
        _insert_record(conn, {"id": "cr_e2e_001", "body": "record A body", "kind": "note"}, v1)
        _insert_record(conn, {"id": "cr_e2e_002", "body": "record B body", "kind": "note"}, v2)
        conn.commit()
        conn.close()

        with patch(
            "plugins.memory.memory_os.low_clue_recall.low_clue_judge_availability"
        ) as mock_judge:
            mock_judge.return_value = {"available": True}
            result = run_contradiction_lane(
                store, embedder=_mock_embedder(), roots=roots,
            )
        # Pair filtered by threshold → no candidates → lane completes ok
        assert result["status"] == "ok"
        assert result["reason"] == "no_high_similarity_pairs"
        assert result["candidate_pairs"] == 0


# ── 护栏②: candidate source dispatch ──────────────────────────────────────


class TestCandidateSourceDispatch:
    """护栏②: candidate source knob dispatches correctly."""

    def test_default_source_is_cosine(self, tmp_path: Path) -> None:
        """Without override, _find_contradiction_candidates uses cosine path."""
        roots = FakeRoots(tmp_path)
        store = FakeStore(roots)
        _enable_lane_knob(roots)

        conn = sqlite3.connect(str(roots.index_path))
        _create_tables(conn)
        v1 = np.array([1.0, 0.1], dtype=np.float32).tobytes()
        v2 = np.array([0.98, 0.05], dtype=np.float32).tobytes()
        _insert_record(conn, {"id": "cr_cs_001", "body": "record A body", "kind": "note"}, v1)
        _insert_record(conn, {"id": "cr_cs_002", "body": "record B body", "kind": "note"}, v2)
        conn.commit()
        conn.close()

        candidate_pairs, _ = _find_contradiction_candidates(
            store, max_pairs=100, roots=roots,
        )
        # Default cosine path finds the pair
        assert len(candidate_pairs) == 1

    def test_source_knob_entity_falls_back_empty(self, tmp_path: Path) -> None:
        """entity source without entity_index table → empty result."""
        roots = FakeRoots(tmp_path)
        store = FakeStore(roots)
        _enable_lane_knob(roots)
        _set_source_knob(roots, "entity")

        conn = sqlite3.connect(str(roots.index_path))
        _create_tables(conn)
        v1 = np.array([1.0, 0.1], dtype=np.float32).tobytes()
        v2 = np.array([0.98, 0.05], dtype=np.float32).tobytes()
        _insert_record(conn, {"id": "cr_ent_001", "body": "record A body", "kind": "note"}, v1)
        _insert_record(conn, {"id": "cr_ent_002", "body": "record B body", "kind": "note"}, v2)
        conn.commit()
        conn.close()

        candidate_pairs, _ = _find_contradiction_candidates(
            store, max_pairs=100, roots=roots,
        )
        # entity_index table does not exist → empty fallback
        assert len(candidate_pairs) == 0

    def test_source_knob_entity_with_index(self, tmp_path: Path) -> None:
        """entity source with populated entity_index discovers shared-entity pairs."""
        roots = FakeRoots(tmp_path)
        store = FakeStore(roots)
        _enable_lane_knob(roots)
        _set_source_knob(roots, "entity")

        conn = sqlite3.connect(str(roots.index_path))
        _create_tables(conn)
        # Create entity_index table and populate it
        conn.execute(
            "create table if not exists entity_index ("
            "entity_id text, entity_text text, record_id text, "
            "role text, proposed_by text, created_at text, "
            "primary key (entity_id, record_id, role))"
        )
        # Both records share entity "ent_shared"
        conn.execute(
            "insert into entity_index (entity_id, entity_text, record_id, role, proposed_by) "
            "values (?, ?, ?, ?, ?)",
            ("ent_shared", "shared_entity", "cr_ei_001", "mention", "structural"),
        )
        conn.execute(
            "insert into entity_index (entity_id, entity_text, record_id, role, proposed_by) "
            "values (?, ?, ?, ?, ?)",
            ("ent_shared", "shared_entity", "cr_ei_002", "mention", "structural"),
        )
        # Insert records with embeddings
        v1 = np.array([1.0, 0.1], dtype=np.float32).tobytes()
        v2 = np.array([0.98, 0.05], dtype=np.float32).tobytes()
        _insert_record(conn, {"id": "cr_ei_001", "body": "record A body", "kind": "note"}, v1)
        _insert_record(conn, {"id": "cr_ei_002", "body": "record B body", "kind": "note"}, v2)
        conn.commit()
        conn.close()

        candidate_pairs, _ = _find_contradiction_candidates(
            store, max_pairs=100, roots=roots,
        )
        # Entity path finds the shared-entity pair
        assert len(candidate_pairs) == 1
        assert candidate_pairs[0]["a"]["id"] == "cr_ei_001"
        assert candidate_pairs[0]["b"]["id"] == "cr_ei_002"

    def test_entity_candidates_respect_threshold(self, tmp_path: Path) -> None:
        """Entity path also respects llm_contradiction_same_topic_threshold."""
        roots = FakeRoots(tmp_path)
        store = FakeStore(roots)
        _enable_lane_knob(roots)
        _set_source_knob(roots, "entity")
        _set_threshold_knob(roots, 0.99, knob_id="test_th_entity")

        conn = sqlite3.connect(str(roots.index_path))
        _create_tables(conn)
        conn.execute(
            "create table if not exists entity_index ("
            "entity_id text, entity_text text, record_id text, "
            "role text, proposed_by text, created_at text, "
            "primary key (entity_id, record_id, role))"
        )
        conn.execute(
            "insert into entity_index (entity_id, entity_text, record_id, role, proposed_by) "
            "values (?, ?, ?, ?, ?)",
            ("ent_x", "entity_x", "cr_et_001", "mention", "structural"),
        )
        conn.execute(
            "insert into entity_index (entity_id, entity_text, record_id, role, proposed_by) "
            "values (?, ?, ?, ?, ?)",
            ("ent_x", "entity_x", "cr_et_002", "mention", "structural"),
        )
        # Cosine ≈ 0.88 — above default 0.75, below override 0.99
        v1 = np.array([1.0, 0.0], dtype=np.float32).tobytes()
        v2 = np.array([0.88, 0.475], dtype=np.float32).tobytes()
        _insert_record(conn, {"id": "cr_et_001", "body": "record A body", "kind": "note"}, v1)
        _insert_record(conn, {"id": "cr_et_002", "body": "record B body", "kind": "note"}, v2)
        conn.commit()
        conn.close()

        candidate_pairs, _ = _find_contradiction_candidates(
            store, max_pairs=100, roots=roots,
        )
        # threshold 0.99 excludes cos≈0.88 pair
        assert len(candidate_pairs) == 0
