"""Local deterministic embedder for vector retrieval lane.

Uses sentence-transformers with paraphrase-multilingual-MiniLM-L12-v2.
Deterministic: same input -> same output vector. CPU-only, no network.
INV-5 safe: is_available() guard -> vector lane degrades to FTS5 floor.
"""

from __future__ import annotations

import numpy as np


class LocalEmbedder:
    """Local deterministic embedding model for semantic search.

    Wraps sentence-transformers behind an is_available() guard so the
    vector retrieval lane degrades gracefully when the dependency is
    not installed. CPU inference only -- no GPU, no network, no API keys.
    """

    def __init__(self, model_name: str = "paraphrase-multilingual-MiniLM-L12-v2") -> None:
        self._model_name = model_name
        self._model = None
        self._available: bool | None = None  # tri-state: None=unchecked

    def is_available(self) -> bool:
        """Check whether the embedding model can be loaded.

        Cached: the check runs once and the result is memoized.
        Returns False when sentence-transformers is not installed or
        the model cannot be downloaded/loaded.
        """
        if self._available is not None:
            return self._available
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name)
            # Warm-up: run a tiny inference to catch runtime errors early
            self._model.encode(["warmup"], show_progress_bar=False)
            self._available = True
        except Exception:
            self._available = False
        return self._available

    def embed(self, text: str) -> bytes:
        """Embed text -> serialized numpy array blob.

        Returns empty bytes if unavailable. Deterministic: same input
        produces the same output vector every time.
        """
        if not self.is_available():
            return b""
        vec = self._model.encode([text], show_progress_bar=False)[0]
        return vec.astype(np.float32).tobytes()

    def embed_query(self, text: str) -> np.ndarray | None:
        """Embed query text -> 1-D numpy array for cosine similarity.

        Returns None if unavailable. This is the hot-path call site --
        called during prefetch for every query. Must be local, fast,
        and never touch the network.
        """
        if not self.is_available():
            return None
        vec = self._model.encode([text], show_progress_bar=False)[0]
        return vec.astype(np.float32)
