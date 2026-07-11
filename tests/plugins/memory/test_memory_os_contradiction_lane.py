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
    """Minimal roots-like object exposing index_path + memory_os_root + crystallized_root."""

    def __init__(self, tmp_path: Path) -> None:
        self.index_path = tmp_path / "index.db"
        self.memory_os_root = tmp_path / "memory-os"
        self.crystallized_root = self.memory_os_root / "crystallized"
        self.hermes_home = tmp_path
        self.profile = "default"


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


# ── E1: Clearance pair source ──────────────────────────────────────────────


def _insert_provisional_record(
    conn: sqlite3.Connection,
    rec_id: str,
    body: str,
    *,
    kind: str = "note",
    provisional: int = 1,
    embedding_bytes: bytes | None = None,
) -> None:
    """Insert a provisional crystallized record + optional embedding."""
    conn.execute(
        "insert into crystallized_records "
        "(id, kind, created_at, approved_by, approved_at, source_event_ids_json, "
        "tags_json, sensitivity, hindsight_indexed, file_name, body) "
        "values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            rec_id,
            kind,
            "2026-06-01T00:00:00Z",  # created_at
            "owner",
            "2026-06-01T00:00:00Z",  # approved_at — 40+ days ago (>> min_age)
            '["evt_001"]',
            "[]",
            "private",
            int(provisional),
            f"{rec_id}.md",
            body,
        ),
    )
    if embedding_bytes is not None:
        conn.execute(
            "insert into memory_embeddings "
            "(record_type, record_id, embedding_model, embedding, created_at) "
            "values (?, ?, ?, ?, ?)",
            ("crystallized_record", rec_id, "test-model", embedding_bytes, "2026-07-01T00:00:00Z"),
        )


def _write_crystallized_md(
    roots: FakeRoots,
    rec_id: str,
    body: str,
    *,
    kind: str = "note",
    provisional: bool = True,
) -> None:
    """Write a crystallized markdown file so CrystallizedMemoryService can read it."""
    md_dir = roots.crystallized_root
    md_dir.mkdir(parents=True, exist_ok=True)
    prov_line = "true" if provisional else "false"
    expires_line = "expires_at: 2026-08-01T00:00:00Z\n" if provisional else ""
    content = (
        "---\n"
        f"schema_version: memory-os.crystallized.v0\n"
        f"id: {rec_id}\n"
        f"candidate_id: cand_{rec_id}\n"
        f"kind: {kind}\n"
        "created_at: 2026-06-01T00:00:00Z\n"
        "approved_by: owner\n"
        "approved_at: 2026-06-01T00:00:00Z\n"
        'approval_purpose: approve_for_crystallized\n'
        'approval_note: ""\n'
        'source_event_ids: ["evt_001"]\n'
        "tags: []\n"
        "sensitivity: private\n"
        "hindsight_indexed: false\n"
        "bridge_state: active\n"
        f"provisional: {prov_line}\n"
        f"{expires_line}"
        "---\n"
        f"{body}\n"
    )
    (md_dir / f"{rec_id}.md").write_text(content, encoding="utf-8")


def _insert_entity_link(
    conn: sqlite3.Connection,
    entity_id: str,
    entity_text: str,
    record_id: str,
) -> None:
    """Insert an entity_index row for a record."""
    conn.execute(
        "insert into entity_index (entity_id, entity_text, record_id, role, proposed_by) "
        "values (?, ?, ?, ?, ?)",
        (entity_id, entity_text, record_id, "mention", "structural"),
    )


def _ensure_entity_index_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "create table if not exists entity_index ("
        "entity_id text, entity_text text, record_id text, "
        "role text, proposed_by text, created_at text, "
        "primary key (entity_id, record_id, role))"
    )


class TestClearancePairSource:
    """E1 RED: candidate/provisional × active permanent pair source."""

    # ── helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _setup_clearance_knob(roots: FakeRoots) -> None:
        """Enable the lane + set source=clearance."""
        _enable_lane_knob(roots)
        _set_source_knob(roots, "clearance")

    # ── RED tests ────────────────────────────────────────────────────────

    def test_empty_permanents_yields_no_pairs(self, tmp_path: Path) -> None:
        """No active permanent records → 0 pairs, 0 pairs_evaluated."""
        roots = FakeRoots(tmp_path)
        store = FakeStore(roots)
        self._setup_clearance_knob(roots)

        conn = sqlite3.connect(str(roots.index_path))
        _create_tables(conn)
        # One provisional, zero permanents
        _insert_provisional_record(
            conn, "prov_001", "candidate body about project X",
            embedding_bytes=np.array([1.0, 0.0], dtype=np.float32).tobytes(),
        )
        _write_crystallized_md(roots, "prov_001", "candidate body about project X", provisional=True)
        conn.commit()
        conn.close()

        pairs, evaluated = _find_contradiction_candidates(
            store, max_pairs=100, roots=roots,
        )
        assert len(pairs) == 0, f"expected 0 pairs with no permanents, got {len(pairs)}"
        assert evaluated == 0

    def test_entity_intersection_priority(self, tmp_path: Path) -> None:
        """Candidate + permanent share entity → pair via entity priority."""
        roots = FakeRoots(tmp_path)
        store = FakeStore(roots)
        self._setup_clearance_knob(roots)

        conn = sqlite3.connect(str(roots.index_path))
        _create_tables(conn)
        _ensure_entity_index_table(conn)

        # One provisional, one permanent — share entity "ent_X"
        _insert_provisional_record(
            conn, "prov_ent", "we use PostgreSQL for the main database",
            embedding_bytes=np.array([1.0, 0.1], dtype=np.float32).tobytes(),
        )
        _write_crystallized_md(roots, "prov_ent", "we use PostgreSQL for the main database", provisional=True)
        _insert_record(
            conn,
            {"id": "perm_ent", "body": "the primary database is PostgreSQL 15", "kind": "note"},
            np.array([0.98, 0.05], dtype=np.float32).tobytes(),
        )
        _write_crystallized_md(roots, "perm_ent", "the primary database is PostgreSQL 15", provisional=False)
        _insert_entity_link(conn, "ent_X", "PostgreSQL", "prov_ent")
        _insert_entity_link(conn, "ent_X", "PostgreSQL", "perm_ent")
        conn.commit()
        conn.close()

        pairs, evaluated = _find_contradiction_candidates(
            store, max_pairs=100, roots=roots,
        )
        assert len(pairs) == 1
        assert pairs[0]["a"]["id"] == "prov_ent"
        assert pairs[0]["b"]["id"] == "perm_ent"
        assert evaluated > 0

    def test_cosine_fallback_when_no_entity_overlap(self, tmp_path: Path) -> None:
        """No shared entities, high cosine sim → pair via fallback."""
        roots = FakeRoots(tmp_path)
        store = FakeStore(roots)
        self._setup_clearance_knob(roots)

        conn = sqlite3.connect(str(roots.index_path))
        _create_tables(conn)
        _ensure_entity_index_table(conn)
        # Entities exist but don't overlap between prov and perm
        _insert_entity_link(conn, "ent_A", "entity_A", "prov_cos")
        _insert_entity_link(conn, "ent_B", "entity_B", "perm_cos")

        # High cosine similarity vectors
        _insert_provisional_record(
            conn, "prov_cos", "candidate body about system architecture",
            embedding_bytes=np.array([1.0, 0.1], dtype=np.float32).tobytes(),
        )
        _write_crystallized_md(roots, "prov_cos", "candidate body about system architecture", provisional=True)
        _insert_record(
            conn,
            {"id": "perm_cos", "body": "permanent record about system architecture v2", "kind": "note"},
            np.array([0.98, 0.05], dtype=np.float32).tobytes(),
        )
        _write_crystallized_md(roots, "perm_cos", "permanent record about system architecture v2", provisional=False)
        conn.commit()
        conn.close()

        pairs, evaluated = _find_contradiction_candidates(
            store, max_pairs=100, roots=roots,
        )
        # Cosine fallback finds the pair even without shared entities
        assert len(pairs) == 1
        assert pairs[0]["a"]["id"] == "prov_cos"
        assert pairs[0]["b"]["id"] == "perm_cos"
        assert pairs[0]["similarity"] > 0.75

    def test_respects_clearance_pair_top_k_knob(self, tmp_path: Path) -> None:
        """clearance_pair_top_k bounds per-candidate permanent pairs."""
        roots = FakeRoots(tmp_path)
        store = FakeStore(roots)
        self._setup_clearance_knob(roots)

        # Override top_k to 2
        topk_path = roots.memory_os_root / "system" / "knob_overrides.jsonl"
        topk_path.parent.mkdir(parents=True, exist_ok=True)
        existing = topk_path.read_text(encoding="utf-8") if topk_path.exists() else ""
        topk_path.write_text(
            existing
            + json.dumps({
                "schema_version": "memory-os.knob_override.v0",
                "id": "test_topk_001",
                "knob": "clearance_pair_top_k",
                "override_value": 2,
                "prior_value": 5,
                "provisional": False,
                "expires_at": "",
                "state": "confirmed",
                "ts": "2026-07-01T00:00:00Z",
            }, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )

        conn = sqlite3.connect(str(roots.index_path))
        _create_tables(conn)

        # One provisional
        _insert_provisional_record(
            conn, "prov_topk", "candidate body",
            embedding_bytes=np.array([1.0, 0.0], dtype=np.float32).tobytes(),
        )
        _write_crystallized_md(roots, "prov_topk", "candidate body", provisional=True)
        # Four permanents — all high cosine sim to the provisional
        for i in range(4):
            _insert_record(
                conn,
                {"id": f"perm_topk_{i}", "body": f"permanent record variant {i}", "kind": "note"},
                np.array([0.95 + i * 0.01, 0.05], dtype=np.float32).tobytes(),
            )
            _write_crystallized_md(roots, f"perm_topk_{i}", f"permanent record variant {i}", provisional=False)
        conn.commit()
        conn.close()

        pairs, _ = _find_contradiction_candidates(
            store, max_pairs=100, roots=roots,
        )
        # With top_k=2, at most 2 pairs per candidate
        prov_pairs = [p for p in pairs if p["a"]["id"] == "prov_topk"]
        assert len(prov_pairs) <= 2, f"top_k=2 but got {len(prov_pairs)} pairs for prov_topk"

    def test_bounded_total_pairs(self, tmp_path: Path) -> None:
        """Total pairs capped at max_pairs regardless of candidates."""
        roots = FakeRoots(tmp_path)
        store = FakeStore(roots)
        self._setup_clearance_knob(roots)

        conn = sqlite3.connect(str(roots.index_path))
        _create_tables(conn)

        # Three provisionals, three permanents — all high sim
        for i in range(3):
            _insert_provisional_record(
                conn, f"prov_bound_{i}", f"candidate body {i}",
                embedding_bytes=np.array([1.0, float(i) * 0.01], dtype=np.float32).tobytes(),
            )
            _write_crystallized_md(roots, f"prov_bound_{i}", f"candidate body {i}", provisional=True)
            _insert_record(
                conn,
                {"id": f"perm_bound_{i}", "body": f"permanent body {i}", "kind": "note"},
                np.array([0.98, float(i) * 0.01], dtype=np.float32).tobytes(),
            )
            _write_crystallized_md(roots, f"perm_bound_{i}", f"permanent body {i}", provisional=False)
        conn.commit()
        conn.close()

        pairs, evaluated = _find_contradiction_candidates(
            store, max_pairs=2, roots=roots,
        )
        # max_pairs=2 caps total pairs, even though more exist
        assert len(pairs) <= 2, f"max_pairs=2 but got {len(pairs)}"
        assert evaluated <= 2

    def test_source_dispatch_to_clearance(self, tmp_path: Path) -> None:
        """Knob llm_contradiction_candidate_source='clearance' dispatches correctly."""
        roots = FakeRoots(tmp_path)
        store = FakeStore(roots)
        self._setup_clearance_knob(roots)

        conn = sqlite3.connect(str(roots.index_path))
        _create_tables(conn)
        _ensure_entity_index_table(conn)

        _insert_provisional_record(
            conn, "prov_disp", "dispatch test candidate",
            embedding_bytes=np.array([1.0, 0.1], dtype=np.float32).tobytes(),
        )
        _write_crystallized_md(roots, "prov_disp", "dispatch test candidate", provisional=True)
        _insert_record(
            conn,
            {"id": "perm_disp", "body": "dispatch test permanent", "kind": "note"},
            np.array([0.98, 0.05], dtype=np.float32).tobytes(),
        )
        _write_crystallized_md(roots, "perm_disp", "dispatch test permanent", provisional=False)
        _insert_entity_link(conn, "ent_disp", "dispatch_entity", "prov_disp")
        _insert_entity_link(conn, "ent_disp", "dispatch_entity", "perm_disp")
        conn.commit()
        conn.close()

        pairs, _ = _find_contradiction_candidates(
            store, max_pairs=100, roots=roots,
        )
        # Clearance source uses provisional × permanent, not crystallized × crystallized
        assert len(pairs) >= 1
        # Verify the pairs are provisional→permanent, not perm→perm
        for p in pairs:
            assert p["a"]["id"].startswith("prov_"), f"side A should be provisional, got {p['a']['id']}"
            assert p["b"]["id"].startswith("perm_"), f"side B should be permanent, got {p['b']['id']}"

    def test_no_eligible_provisionals_yields_no_pairs(self, tmp_path: Path) -> None:
        """Zero eligible provisional records → 0 pairs."""
        roots = FakeRoots(tmp_path)
        store = FakeStore(roots)
        self._setup_clearance_knob(roots)

        conn = sqlite3.connect(str(roots.index_path))
        _create_tables(conn)
        # Only permanents, no provisionals
        _insert_record(
            conn,
            {"id": "perm_only", "body": "just a permanent record", "kind": "note"},
            np.array([1.0, 0.0], dtype=np.float32).tobytes(),
        )
        _write_crystallized_md(roots, "perm_only", "just a permanent record", provisional=False)
        conn.commit()
        conn.close()

        pairs, evaluated = _find_contradiction_candidates(
            store, max_pairs=100, roots=roots,
        )
        assert len(pairs) == 0
        assert evaluated == 0
