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
