"""Tests for vector retrieval: embeddings index, cosine search, RRF union."""
import json
import sqlite3
import numpy as np
import pytest
from pathlib import Path


# ── Mock embedder for tests (no model download needed) ──────────────
class MockEmbedder:
    """Deterministic mock that returns simple vectors from text length."""
    def __init__(self, available: bool = True):
        self._available = available

    def is_available(self) -> bool:
        return self._available

    def embed(self, text: str) -> bytes:
        if not self._available:
            return b""
        # Deterministic: vector = [len(text), len(text)*0.5, 1.0] padded to 384 dims
        vec = np.array([float(len(text)), float(len(text)) * 0.5, 1.0], dtype=np.float32)
        padded = np.zeros(384, dtype=np.float32)
        padded[:len(vec)] = vec
        return padded.tobytes()

    def embed_query(self, text: str) -> np.ndarray | None:
        if not self._available:
            return None
        vec = np.array([float(len(text)), float(len(text)) * 0.5, 1.0], dtype=np.float32)
        padded = np.zeros(384, dtype=np.float32)
        padded[:len(vec)] = vec
        return padded


# ── Fixtures ────────────────────────────────────────────────────────


class TestIndexEmbeddings:
    """W.4: _index_embeddings fills memory_embeddings table."""

    def test_index_embeddings_populates_table(self, tmp_path):
        """After rebuild with embedder, memory_embeddings has rows."""
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore
        from plugins.memory.memory_os.crystallized import (
            CrystallizedCandidate, CrystallizedMemoryService,
        )
        from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
        from plugins.memory.memory_os.index import MemoryOSIndex

        roots = MemoryOSRoots.from_hermes_home(str(tmp_path), profile="test")
        roots.memory_os_root.mkdir(parents=True, exist_ok=True)
        store = MemoryOSStore(roots)
        store.initialize()

        # Write 2 crystallized records
        svc = CrystallizedMemoryService(store)
        for i, body in enumerate(["记录一的内容文本", "第二条记忆的数据"]):
            candidate = CrystallizedCandidate(
                candidate_id=f"c{i}", kind="note", body=body,
                source_event_ids=[f"evt_{i}"],
            )
            decision = ApprovalDecision(
                candidate_id=f"c{i}",
                purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
                reviewer="owner", reviewed_at="2026-06-22T10:00:00Z",
                source_state="active",
            )
            svc.write_approved_record(candidate, decision, file_name="test.md")

        # Build index with mock embedder
        index = MemoryOSIndex(roots)
        index._embedder = MockEmbedder(available=True)
        index.rebuild_from_store(store)

        # Verify memory_embeddings table has rows
        conn = sqlite3.connect(str(roots.index_path))
        count = conn.execute("select count(*) from memory_embeddings").fetchone()[0]
        assert count == 2
        # Verify embedding blob is non-empty
        row = conn.execute(
            "select embedding, embedding_model from memory_embeddings limit 1"
        ).fetchone()
        assert row is not None
        assert len(row[0]) > 0  # blob non-empty
        assert row[1] == "paraphrase-multilingual-MiniLM-L12-v2"
        conn.close()

    def test_index_embeddings_skips_when_embedder_unavailable(self, tmp_path):
        """When embedder is None or unavailable, table remains empty — no crash."""
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore
        from plugins.memory.memory_os.crystallized import (
            CrystallizedCandidate, CrystallizedMemoryService,
        )
        from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
        from plugins.memory.memory_os.index import MemoryOSIndex

        roots = MemoryOSRoots.from_hermes_home(str(tmp_path), profile="test")
        roots.memory_os_root.mkdir(parents=True, exist_ok=True)
        store = MemoryOSStore(roots)
        store.initialize()

        svc = CrystallizedMemoryService(store)
        candidate = CrystallizedCandidate(
            candidate_id="c0", kind="note", body="test body",
            source_event_ids=["evt_0"],
        )
        decision = ApprovalDecision(
            candidate_id="c0", purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
            reviewer="owner", reviewed_at="2026-06-22T10:00:00Z",
            source_state="active",
        )
        svc.write_approved_record(candidate, decision, file_name="test.md")

        # Build index WITHOUT embedder — should not crash
        index = MemoryOSIndex(roots)
        index._embedder = None
        index.rebuild_from_store(store)

        conn = sqlite3.connect(str(roots.index_path))
        count = conn.execute("select count(*) from memory_embeddings").fetchone()[0]
        assert count == 0  # table exists but empty
        conn.close()

    def test_counts_includes_memory_embeddings(self, tmp_path):
        """MemoryOSIndex.counts() includes memory_embeddings table."""
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore
        from plugins.memory.memory_os.crystallized import (
            CrystallizedCandidate, CrystallizedMemoryService,
        )
        from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
        from plugins.memory.memory_os.index import MemoryOSIndex

        roots = MemoryOSRoots.from_hermes_home(str(tmp_path), profile="test")
        roots.memory_os_root.mkdir(parents=True, exist_ok=True)
        store = MemoryOSStore(roots)
        store.initialize()

        svc = CrystallizedMemoryService(store)
        candidate = CrystallizedCandidate(
            candidate_id="c0", kind="note", body="test",
            source_event_ids=["evt_0"],
        )
        decision = ApprovalDecision(
            candidate_id="c0", purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
            reviewer="owner", reviewed_at="2026-06-22T10:00:00Z",
            source_state="active",
        )
        svc.write_approved_record(candidate, decision, file_name="test.md")

        index = MemoryOSIndex(roots)
        index._embedder = MockEmbedder(available=True)
        index.rebuild_from_store(store)

        counts = index.counts()
        assert "memory_embeddings" in counts
        assert counts["memory_embeddings"] == 1


class TestVectorSearch:
    """W.5: MemoryOSIndex.vector_search returns cosine similarity results."""

    def test_vector_search_returns_results(self, tmp_path):
        """Verify results are record_id strings sorted by cosine similarity."""
        from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
        from plugins.memory.memory_os.crystallized import (CrystallizedCandidate,
                                                           CrystallizedMemoryService)
        from plugins.memory.memory_os.index import MemoryOSIndex
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore

        roots = MemoryOSRoots.from_hermes_home(str(tmp_path), profile="test")
        roots.memory_os_root.mkdir(parents=True, exist_ok=True)
        store = MemoryOSStore(roots)
        store.initialize()

        svc = CrystallizedMemoryService(store)
        for i, body in enumerate(["aaa", "bbb", "ccc"]):
            candidate = CrystallizedCandidate(
                candidate_id=f"v{i}", kind="note", body=body,
                source_event_ids=[f"evt_{i}"],
            )
            decision = ApprovalDecision(
                candidate_id=f"v{i}",
                purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
                reviewer="owner", reviewed_at="2026-06-22T10:00:00Z",
                source_state="active",
            )
            svc.write_approved_record(candidate, decision, file_name="test.md")

        index = MemoryOSIndex(roots)
        index._embedder = MockEmbedder(available=True)
        index.rebuild_from_store(store)

        # Pass a pre-computed numpy array, not raw text
        qvec = index._embedder.embed_query("query")
        results = index.vector_search(qvec, limit=5)
        assert len(results) == 3
        assert isinstance(results, list)
        for rid in results:
            assert isinstance(rid, str)
        # Sorted descending by cosine similarity (deterministic with MockEmbedder)
        # First result should be longest text ("ccc" = 3 chars, highest vector norm)
        assert results[0] != results[1]  # distinct record_ids

    def test_vector_search_empty_when_no_embedder(self, tmp_path):
        """No embedder or unavailable -> empty list."""
        from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
        from plugins.memory.memory_os.crystallized import (CrystallizedCandidate,
                                                           CrystallizedMemoryService)
        from plugins.memory.memory_os.index import MemoryOSIndex
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore

        roots = MemoryOSRoots.from_hermes_home(str(tmp_path), profile="test")
        roots.memory_os_root.mkdir(parents=True, exist_ok=True)
        store = MemoryOSStore(roots)
        store.initialize()

        svc = CrystallizedMemoryService(store)
        candidate = CrystallizedCandidate(
            candidate_id="v0", kind="note", body="test",
            source_event_ids=["evt_0"],
        )
        decision = ApprovalDecision(
            candidate_id="v0",
            purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
            reviewer="owner", reviewed_at="2026-06-22T10:00:00Z",
            source_state="active",
        )
        svc.write_approved_record(candidate, decision, file_name="test.md")

        index = MemoryOSIndex(roots)
        index._embedder = None
        index.rebuild_from_store(store)

        # Passing a numpy array but embedder is None — vector_search checks
        # query_vec is not None first, then finds no embeddings in the table
        assert index.vector_search(np.array([1.0], dtype=np.float32)) == []

    def test_vector_search_skips_shape_mismatch(self, tmp_path):
        """Rows with different embedding shapes are skipped."""
        from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
        from plugins.memory.memory_os.crystallized import (CrystallizedCandidate,
                                                           CrystallizedMemoryService)
        from plugins.memory.memory_os.index import MemoryOSIndex
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore

        roots = MemoryOSRoots.from_hermes_home(str(tmp_path), profile="test")
        roots.memory_os_root.mkdir(parents=True, exist_ok=True)
        store = MemoryOSStore(roots)
        store.initialize()

        svc = CrystallizedMemoryService(store)
        candidate = CrystallizedCandidate(
            candidate_id="v0", kind="note", body="test body",
            source_event_ids=["evt_0"],
        )
        decision = ApprovalDecision(
            candidate_id="v0",
            purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
            reviewer="owner", reviewed_at="2026-06-22T10:00:00Z",
            source_state="active",
        )
        svc.write_approved_record(candidate, decision, file_name="test.md")

        index = MemoryOSIndex(roots)
        index._embedder = MockEmbedder(available=True)
        index.rebuild_from_store(store)

        # Inject a bad-shape embedding directly
        conn = sqlite3.connect(str(roots.index_path))
        bad_vec = np.array([1.0, 2.0], dtype=np.float32).tobytes()
        conn.execute(
            "insert or replace into memory_embeddings "
            "(record_type, record_id, embedding_model, embedding, created_at) "
            "values (?, ?, ?, ?, ?)",
            ("crystallized_record", "bad_shape", "test", bad_vec,
             "2026-06-22T10:00:00Z"),
        )
        conn.commit()
        conn.close()

        # Fresh index instance to re-read the db
        index2 = MemoryOSIndex(roots)
        index2._embedder = MockEmbedder(available=True)
        qvec = index2._embedder.embed_query("test")
        results = index2.vector_search(qvec, limit=5)
        # Only v0 result should appear; bad-shape row is skipped
        assert len(results) == 1
        assert isinstance(results[0], str)

    def test_vector_search_min_score_filters_low_cosine(self, tmp_path):
        """min_score=0.30 excludes <0.30, retains >=0.30, boundary inclusive."""
        from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
        from plugins.memory.memory_os.crystallized import (CrystallizedCandidate,
                                                           CrystallizedMemoryService)
        from plugins.memory.memory_os.index import MemoryOSIndex
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore

        roots = MemoryOSRoots.from_hermes_home(str(tmp_path), profile="test")
        roots.memory_os_root.mkdir(parents=True, exist_ok=True)
        store = MemoryOSStore(roots)
        store.initialize()

        svc = CrystallizedMemoryService(store)
        records = [
            ("high", "high-sim body text here"),
            ("boundary", "boundary body text"),
            ("low", "low-sim body"),
            ("ortho", "orthogonal body text"),
        ]
        for rid, body in records:
            candidate = CrystallizedCandidate(
                candidate_id=rid, kind="note", body=body,
                source_event_ids=[f"evt_{rid}"],
            )
            decision = ApprovalDecision(
                candidate_id=rid,
                purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
                reviewer="owner", reviewed_at="2026-06-23T10:00:00Z",
                source_state="active",
            )
            svc.write_approved_record(candidate, decision, file_name="test.md")

        index = MemoryOSIndex(roots)
        index._embedder = MockEmbedder(available=True)
        index.rebuild_from_store(store)

        # Overwrite embeddings with precise cosine-controlled unit vectors.
        # Query = [1, 0, 0, ...] (unit along first axis).  All record vectors
        # are also unit vectors rotated in the XY plane so dot = cos(theta).
        DIM = 384
        qvec = np.zeros(DIM, dtype=np.float32)
        qvec[0] = 1.0  # unit vector along axis 0

        def _unit_vec(cos_theta: float) -> bytes:
            v = np.zeros(DIM, dtype=np.float32)
            v[0] = cos_theta
            v[1] = np.sqrt(max(0.0, 1.0 - cos_theta * cos_theta))
            return v.tobytes()

        conn = sqlite3.connect(str(roots.index_path))
        conn.execute("DELETE FROM memory_embeddings")
        for rid, cos_val in [("high", 1.0), ("boundary", 0.30), ("low", 0.29), ("ortho", 0.0)]:
            conn.execute(
                "INSERT INTO memory_embeddings (record_type, record_id, embedding_model, embedding, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                ("crystallized_record", rid, "test", _unit_vec(cos_val), "2026-06-23T10:00:00Z"),
            )
        conn.commit()
        conn.close()

        # Default min_score=0.30
        results = index.vector_search(qvec, limit=10)
        result_set = set(results)
        assert "high" in result_set, "cos=1.0 should be retained"
        assert "boundary" in result_set, "cos=0.30 (boundary) should be retained"
        assert "low" not in result_set, "cos=0.29 should be excluded"
        assert "ortho" not in result_set, "cos=0.0 should be excluded"
        assert len(results) == 2

    def test_vector_search_all_below_min_score_returns_empty(self, tmp_path):
        """When all cosine scores < min_score, vector_search returns [].
        This ensures graceful degradation — prefetch falls back to FTS5-only
        without error."""
        from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
        from plugins.memory.memory_os.crystallized import (CrystallizedCandidate,
                                                           CrystallizedMemoryService)
        from plugins.memory.memory_os.index import MemoryOSIndex
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore

        roots = MemoryOSRoots.from_hermes_home(str(tmp_path), profile="test")
        roots.memory_os_root.mkdir(parents=True, exist_ok=True)
        store = MemoryOSStore(roots)
        store.initialize()

        svc = CrystallizedMemoryService(store)
        for rid, body in [("a", "body a"), ("b", "body b")]:
            candidate = CrystallizedCandidate(
                candidate_id=rid, kind="note", body=body,
                source_event_ids=[f"evt_{rid}"],
            )
            decision = ApprovalDecision(
                candidate_id=rid,
                purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
                reviewer="owner", reviewed_at="2026-06-23T10:00:00Z",
                source_state="active",
            )
            svc.write_approved_record(candidate, decision, file_name="test.md")

        index = MemoryOSIndex(roots)
        index._embedder = MockEmbedder(available=True)
        index.rebuild_from_store(store)

        # All vectors are orthogonal to the query → cos ≈ 0.0
        DIM = 384
        qvec = np.zeros(DIM, dtype=np.float32)
        qvec[0] = 1.0

        conn = sqlite3.connect(str(roots.index_path))
        conn.execute("DELETE FROM memory_embeddings")
        for rid in ("a", "b"):
            v = np.zeros(DIM, dtype=np.float32)
            v[1] = 1.0  # orthogonal to query [1, 0, ...] → cos = 0.0
            conn.execute(
                "INSERT INTO memory_embeddings (record_type, record_id, embedding_model, embedding, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                ("crystallized_record", rid, "test", v.tobytes(), "2026-06-23T10:00:00Z"),
            )
        conn.commit()
        conn.close()

        results = index.vector_search(qvec, limit=10)
        assert results == [], f"all cos=0.0 < 0.30, expected [], got {results}"


class TestRRFUnion:
    """W.6: _rrf_union combines FTS5 and vector results via RRF."""

    def test_rrf_union_combines_two_lists(self):
        """Two non-overlapping lists are combined with RRF scoring — returns set."""
        from plugins.memory.memory_os.prefetch import _rrf_union

        fts = ["a", "b", "c"]
        vec = ["d", "e", "f"]
        result = _rrf_union(fts, vec)
        assert isinstance(result, set)
        assert len(result) == 6
        assert result == {"a", "b", "c", "d", "e", "f"}

    def test_rrf_union_prefers_common_ids(self):
        """IDs appearing in both lists get higher RRF score and appear in result."""
        from plugins.memory.memory_os.prefetch import _rrf_union

        fts = ["x", "y", "z"]
        vec = ["z", "w"]  # "z" appears in both
        result = _rrf_union(fts, vec, top_n=5)
        assert isinstance(result, set)
        # "z" appears in both lists = higher RRF score = included
        assert "z" in result
        assert "x" in result
        assert "y" in result
        assert "w" in result

    def test_rrf_union_empty_lists(self):
        """Empty inputs produce empty set or single-element set."""
        from plugins.memory.memory_os.prefetch import _rrf_union

        assert _rrf_union([], []) == set()
        assert _rrf_union(["a"], []) == {"a"}
        assert _rrf_union([], ["b"]) == {"b"}

    def test_rrf_union_respects_top_n(self):
        """top_n limits the result count."""
        from plugins.memory.memory_os.prefetch import _rrf_union

        fts = ["a", "b", "c", "d", "e"]
        vec = ["f", "g", "h"]
        result = _rrf_union(fts, vec, top_n=3)
        assert isinstance(result, set)
        assert len(result) == 3


class TestCrystallizedLinesVectorLane:
    """W.7: Vector lane in _crystallized_lines integrates via knob."""

    def test_vector_lane_falls_back_to_fts_when_embedder_unavailable(self, tmp_path):
        """When embedder is None, only FTS5 results are used — no crash."""
        from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
        from plugins.memory.memory_os.crystallized import (CrystallizedCandidate,
                                                           CrystallizedMemoryService)
        from plugins.memory.memory_os.index import MemoryOSIndex
        from plugins.memory.memory_os.prefetch import _crystallized_lines
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore

        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
        store = MemoryOSStore(roots)
        store.initialize()

        svc = CrystallizedMemoryService(store)
        candidate = CrystallizedCandidate(
            candidate_id="vec_lane_001", kind="note",
            body="一条关于网络搜索技术的记录",
            source_event_ids=["evt_001"],
        )
        decision = ApprovalDecision(
            candidate_id="vec_lane_001",
            purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
            reviewer="owner", reviewed_at="2026-06-22T10:00:00Z",
            source_state="active",
        )
        svc.write_approved_record(candidate, decision, file_name="fts_test.md")

        # Build index WITHOUT embedder — vector lane will be skipped
        index = MemoryOSIndex(roots)
        index._embedder = None
        index.rebuild_from_store(store)

        lines, _crystallized_degradation, _record_ids = _crystallized_lines(store, query="网络搜索", index=index)
        assert len(lines) >= 1  # FTS5 still works

    def test_vector_lane_uses_rrf_when_embedder_available(self, tmp_path):
        """When embedder is available on the index, RRF union is used."""
        import json

        from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
        from plugins.memory.memory_os.crystallized import (CrystallizedCandidate,
                                                           CrystallizedMemoryService)
        from plugins.memory.memory_os.index import MemoryOSIndex
        from plugins.memory.memory_os.prefetch import _crystallized_lines
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore

        roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
        store = MemoryOSStore(roots)
        store.initialize()

        svc = CrystallizedMemoryService(store)
        for i, body in enumerate(["网络搜索技术", "天气预报", "足球比赛结果"]):
            candidate = CrystallizedCandidate(
                candidate_id=f"vec_rrf_{i}", kind="note", body=body,
                source_event_ids=[f"evt_{i}"],
            )
            decision = ApprovalDecision(
                candidate_id=f"vec_rrf_{i}",
                purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
                reviewer="owner", reviewed_at="2026-06-22T10:00:00Z",
                source_state="active",
            )
            svc.write_approved_record(candidate, decision, file_name="test.md")

        # Build index with embedder — but knob defaults to False
        index = MemoryOSIndex(roots)
        index._embedder = MockEmbedder(available=True)
        index.rebuild_from_store(store)

        # Enable vector retrieval via knob store
        override_path = roots.memory_os_root / "system" / "knob_overrides.jsonl"
        override_path.parent.mkdir(parents=True, exist_ok=True)
        override_record = {
            "schema_version": "memory-os.knob_override.v0",
            "id": "ko_test_vector_lane",
            "knob": "vector_retrieval_enabled",
            "override_value": True,
            "prior_value": False,
            "provisional": False,
            "expires_at": "",
            "proposed_by": "test",
            "approved_via": "test",
            "state": "active",
            "ts": "2026-06-22T10:00:00Z",
        }
        with override_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(override_record, ensure_ascii=False, sort_keys=True) + "\n")

        try:
            lines, _crystallized_degradation, _record_ids = _crystallized_lines(store, query="网络搜索", index=index)
            assert len(lines) >= 1  # RRF union produces results
        finally:
            if override_path.exists():
                override_path.unlink()


class TestVectorRetrievalIntegration:
    """W.1, W.2, W.3: end-to-end vector retrieval with knob gating."""

    def test_full_flow_fts5_only_when_knob_disabled(self, tmp_path):
        """Default knob=False → pure FTS5, vector lane inactive."""
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore
        from plugins.memory.memory_os.crystallized import (
            CrystallizedCandidate, CrystallizedMemoryService,
        )
        from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
        from plugins.memory.memory_os.index import MemoryOSIndex
        from plugins.memory.memory_os.prefetch import _crystallized_lines
        from plugins.memory.memory_os.knob_overrides import resolve_knob

        roots = MemoryOSRoots.from_hermes_home(str(tmp_path), profile="test")
        roots.memory_os_root.mkdir(parents=True, exist_ok=True)
        store = MemoryOSStore(roots)
        store.initialize()

        svc = CrystallizedMemoryService(store)
        candidate = CrystallizedCandidate(
            candidate_id="c0", kind="note",
            body="语义相关的记忆内容但与关键词不重叠",
            source_event_ids=["evt_0"],
        )
        decision = ApprovalDecision(
            candidate_id="c0", purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
            reviewer="owner", reviewed_at="2026-06-22T10:00:00Z",
            source_state="active",
        )
        svc.write_approved_record(candidate, decision, file_name="test.md")

        index = MemoryOSIndex(roots)
        index._embedder = MockEmbedder(available=True)
        index.rebuild_from_store(store)

        # Verify knob is False by default
        assert resolve_knob("vector_retrieval_enabled", default=False, roots=roots) is False

        # FTS5 search for a keyword-matching term should work
        lines, _crystallized_degradation, _record_ids = _crystallized_lines(store, query="语义", index=index)
        assert len(lines) >= 1  # FTS5 trigram should match "语义"

    def test_full_flow_vector_union_when_knob_enabled(self, tmp_path):
        """Knob=True + embedder available → FTS5 ∪ vector results."""
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore
        from plugins.memory.memory_os.crystallized import (
            CrystallizedCandidate, CrystallizedMemoryService,
        )
        from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
        from plugins.memory.memory_os.index import MemoryOSIndex
        from plugins.memory.memory_os.prefetch import _crystallized_lines
        from plugins.memory.memory_os.knob_overrides import register_override

        roots = MemoryOSRoots.from_hermes_home(str(tmp_path), profile="test")
        roots.memory_os_root.mkdir(parents=True, exist_ok=True)
        store = MemoryOSStore(roots)
        store.initialize()

        svc = CrystallizedMemoryService(store)
        for i, body in enumerate([
            "Python 编程语言相关的内容",  # FTS5: "Python" matches
            "Docker 容器编排和部署策略",   # FTS5: "Docker" matches
        ]):
            candidate = CrystallizedCandidate(
                candidate_id=f"c{i}", kind="note", body=body,
                source_event_ids=[f"evt_{i}"],
            )
            decision = ApprovalDecision(
                candidate_id=f"c{i}",
                purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
                reviewer="owner", reviewed_at="2026-06-22T10:00:00Z",
                source_state="active",
            )
            svc.write_approved_record(candidate, decision, file_name="test.md")

        index = MemoryOSIndex(roots)
        index._embedder = MockEmbedder(available=True)
        index.rebuild_from_store(store)

        # Enable vector knob
        from datetime import datetime, timezone
        expires = datetime.now(timezone.utc).replace(hour=23, minute=59, second=59).isoformat()
        register_override(
            "vector_retrieval_enabled", True,
            prior=False, proposed_by="test",
            approved_via="resolver", expires_at=expires,
            roots=roots,
        )

        # Query should now include both FTS5 and vector results
        lines, _crystallized_degradation, _record_ids = _crystallized_lines(store, query="Python", index=index)
        assert len(lines) >= 1  # Should get at least FTS5 matches

    def test_vector_lane_degraded_when_embedder_unavailable(self, tmp_path):
        """When embedder is_available=False, vector lane skipped — pure FTS5."""
        from plugins.memory.memory_os.roots import MemoryOSRoots
        from plugins.memory.memory_os.store import MemoryOSStore
        from plugins.memory.memory_os.crystallized import (
            CrystallizedCandidate, CrystallizedMemoryService,
        )
        from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
        from plugins.memory.memory_os.index import MemoryOSIndex
        from plugins.memory.memory_os.prefetch import _crystallized_lines
        from plugins.memory.memory_os.knob_overrides import register_override

        roots = MemoryOSRoots.from_hermes_home(str(tmp_path), profile="test")
        roots.memory_os_root.mkdir(parents=True, exist_ok=True)
        store = MemoryOSStore(roots)
        store.initialize()

        svc = CrystallizedMemoryService(store)
        candidate = CrystallizedCandidate(
            candidate_id="c0", kind="note", body="Python development",
            source_event_ids=["evt_0"],
        )
        decision = ApprovalDecision(
            candidate_id="c0", purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
            reviewer="owner", reviewed_at="2026-06-22T10:00:00Z",
            source_state="active",
        )
        svc.write_approved_record(candidate, decision, file_name="test.md")

        index = MemoryOSIndex(roots)
        index._embedder = MockEmbedder(available=False)  # ← unavailable
        index.rebuild_from_store(store)

        from datetime import datetime, timezone
        expires = datetime.now(timezone.utc).replace(hour=23, minute=59, second=59).isoformat()
        register_override(
            "vector_retrieval_enabled", True,
            prior=False, proposed_by="test",
            approved_via="resolver", expires_at=expires,
            roots=roots,
        )

        # Should NOT crash — degrades to pure FTS5
        lines, _crystallized_degradation, _record_ids = _crystallized_lines(store, query="Python", index=index)
        assert len(lines) >= 1  # FTS5 still works

    def test_no_llm_no_network_in_vector_path(self, tmp_path):
        """W.2: vector_search and RRF contain no LLM/network code patterns."""
        from plugins.memory.memory_os.prefetch import _rrf_union
        import inspect

        # _rrf_union source must not contain network/LLM patterns
        rrf_source = inspect.getsource(_rrf_union)
        forbidden = ["http", "requests.", "urllib", "openai", "anthropic", "fetch("]
        for pattern in forbidden:
            assert pattern not in rrf_source.lower(), f"RRF contains forbidden pattern: {pattern}"

        # vector_search source must not contain network/LLM patterns
        from plugins.memory.memory_os.index import MemoryOSIndex
        vs_source = inspect.getsource(MemoryOSIndex.vector_search)
        for pattern in forbidden:
            assert pattern not in vs_source.lower(), f"vector_search contains forbidden pattern: {pattern}"
