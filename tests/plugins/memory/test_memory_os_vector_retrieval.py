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
        """Verify results have correct structure and score ordering."""
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

        results = index.vector_search("query", limit=5)
        assert len(results) == 3
        for r in results:
            assert "record_id" in r
            assert "record_type" in r
            assert r["record_type"] == "crystallized_record"
            assert "score" in r
            assert isinstance(r["score"], float)
        # Sorted descending by score
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True)

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

        assert index.vector_search("test") == []

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
        results = index2.vector_search("test", limit=5)
        # Only v0 result should appear; bad-shape row is skipped
        # (v0's record_id is auto-generated, not "v0" — just check count)
        assert len(results) == 1


class TestRRFUnion:
    """W.6: _rrf_union combines FTS5 and vector results via RRF."""

    def test_rrf_union_combines_two_lists(self):
        """Two non-overlapping lists are combined with RRF scoring."""
        from plugins.memory.memory_os.prefetch import _rrf_union

        fts = ["a", "b", "c"]
        vec = ["d", "e", "f"]
        result = _rrf_union(fts, vec)
        assert len(result) == 6
        assert set(result) == {"a", "b", "c", "d", "e", "f"}

    def test_rrf_union_prefers_common_ids(self):
        """IDs appearing in both lists get higher RRF score -> ranked first."""
        from plugins.memory.memory_os.prefetch import _rrf_union

        fts = ["x", "y", "z"]
        vec = ["z", "w"]  # "z" appears in both
        result = _rrf_union(fts, vec, top_n=5)
        # "z" should be first (appears in both lists = higher RRF score)
        assert result[0] == "z"
        assert "x" in result
        assert "y" in result
        assert "w" in result

    def test_rrf_union_empty_lists(self):
        """Empty inputs produce empty output."""
        from plugins.memory.memory_os.prefetch import _rrf_union

        assert _rrf_union([], []) == []
        assert _rrf_union(["a"], []) == ["a"]
        assert _rrf_union([], ["b"]) == ["b"]

    def test_rrf_union_respects_top_n(self):
        """top_n limits the result count."""
        from plugins.memory.memory_os.prefetch import _rrf_union

        fts = ["a", "b", "c", "d", "e"]
        vec = ["f", "g", "h"]
        result = _rrf_union(fts, vec, top_n=3)
        assert len(result) == 3


class TestCrystallizedLinesVectorLane:
    """W.7: Vector lane in _crystallized_lines integrates via knob."""

    def test_vector_lane_falls_back_to_fts_when_disabled(self, tmp_path):
        """When vector_retrieval_enabled=False, only FTS5 results are used."""
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

        # Build index with embedder — vector_search is available
        index = MemoryOSIndex(roots)
        index._embedder = MockEmbedder(available=True)
        index.rebuild_from_store(store)

        # Knob not set → defaults to False → pure FTS5 path
        lines = _crystallized_lines(store, query="网络搜索", index=index)
        assert len(lines) >= 1

    def test_vector_lane_uses_rrf_when_knob_enabled(self, tmp_path):
        """When vector_retrieval_enabled=True, RRF union is used."""
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
            lines = _crystallized_lines(store, query="网络搜索", index=index)
            assert len(lines) >= 1
        finally:
            # Cleanup the override file
            if override_path.exists():
                override_path.unlink()
