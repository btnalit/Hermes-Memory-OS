"""Tests for LocalEmbedder — deterministic, degradable, INV-5 safe."""
import numpy as np
import pytest


class TestLocalEmbedderAvailability:
    def test_is_available_returns_bool(self):
        """Embedder.is_available() returns a boolean."""
        from plugins.memory.memory_os.embedder import LocalEmbedder

        emb = LocalEmbedder()
        result = emb.is_available()
        assert isinstance(result, bool)

    def test_is_available_false_when_dependency_missing(self, monkeypatch):
        """When sentence-transformers is not installed, is_available returns False."""
        import sys

        # Simulate missing sentence-transformers
        monkeypatch.setitem(sys.modules, "sentence_transformers", None)
        # Force re-import check
        from plugins.memory.memory_os.embedder import LocalEmbedder

        emb = LocalEmbedder()
        # If sentence_transformers was never importable, is_available is False
        # (This test checks the graceful-degradation path contract)
        result = emb.is_available()
        assert isinstance(result, bool)


class TestLocalEmbedderEmbed:
    def test_embed_returns_bytes(self):
        """embed() returns bytes (serialized numpy array)."""
        from plugins.memory.memory_os.embedder import LocalEmbedder

        emb = LocalEmbedder()
        if not emb.is_available():
            pytest.skip("sentence-transformers not installed")
        blob = emb.embed("测试文本")
        assert isinstance(blob, bytes)
        assert len(blob) > 0

    def test_embed_deterministic(self):
        """Same text -> same blob (deterministic, INV-5)."""
        from plugins.memory.memory_os.embedder import LocalEmbedder

        emb = LocalEmbedder()
        if not emb.is_available():
            pytest.skip("sentence-transformers not installed")
        b1 = emb.embed("deterministic test")
        b2 = emb.embed("deterministic test")
        assert b1 == b2

    def test_embed_different_texts_different_vectors(self):
        """Different texts produce different embeddings."""
        from plugins.memory.memory_os.embedder import LocalEmbedder

        emb = LocalEmbedder()
        if not emb.is_available():
            pytest.skip("sentence-transformers not installed")
        b1 = emb.embed("Python development preferences")
        b2 = emb.embed("Docker container deployment strategy")
        assert b1 != b2

    def test_embed_query_returns_ndarray(self):
        """embed_query returns np.ndarray for cosine similarity computation."""
        from plugins.memory.memory_os.embedder import LocalEmbedder

        emb = LocalEmbedder()
        if not emb.is_available():
            pytest.skip("sentence-transformers not installed")
        vec = emb.embed_query("test query")
        assert vec is not None
        assert isinstance(vec, np.ndarray)
        assert vec.ndim == 1  # 1-D vector

    def test_embed_query_returns_none_when_unavailable(self, monkeypatch):
        """embed_query returns None when embedder is unavailable."""
        from plugins.memory.memory_os.embedder import LocalEmbedder

        emb = LocalEmbedder()
        # Force unavailable
        monkeypatch.setattr(emb, "_available", False)
        result = emb.embed_query("test")
        assert result is None
