"""Local deterministic embedder for vector retrieval lane.

Uses sentence-transformers with paraphrase-multilingual-MiniLM-L12-v2.
Deterministic: same input -> same output vector. CPU-only, no network.
INV-5 safe: is_available() guard -> vector lane degrades to FTS5 floor.

Windows: sentence-transformers model loading is known-unstable on Windows
(segfault / MemoryError in native torch dependencies). The embedder
gracefully returns unavailable on Windows so the vector lane falls back
to FTS5 without crashing.
"""

from __future__ import annotations

import sys

import numpy as np


_WINDOWS = sys.platform == "win32"


class LocalEmbedder:
    """Local deterministic embedding model for semantic search.

    Wraps sentence-transformers behind an is_available() guard so the
    vector retrieval lane degrades gracefully when the dependency is
    not installed. CPU inference only -- no GPU, no network, no API keys.
    """

    def __init__(self, model_name: str = "paraphrase-multilingual-MiniLM-L12-v2",
                 device: str = "auto") -> None:
        self._model_name = model_name
        self._device = device
        self._model = None
        self._available: bool | None = None  # tri-state: None=unchecked

    @property
    def model_name(self) -> str:
        """Public read-only accessor for the configured model name."""
        return self._model_name

    def is_available(self) -> bool:
        """Check whether the embedding model can be loaded.

        Cached: the check runs once and the result is memoized.
        Returns False when sentence-transformers is not installed, the
        model cannot be downloaded/loaded, or the platform is Windows
        (sentence-transformers native deps are unstable on win32).
        """
        if self._available is not None:
            return self._available
        if _WINDOWS:
            self._available = False
            return False
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name, device=self._device)
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


def build_embedder(roots) -> LocalEmbedder | None:
    """Factory: build a LocalEmbedder from knob configuration.

    Reads vector_retrieval_enabled, vector_embedder_model, and
    vector_embedder_device from the knob override store. Returns None
    when vector retrieval is disabled or the embedder is unavailable.

    This is the single entry point for all embedder instantiation —
    replaces ad-hoc ``LocalEmbedder()`` calls across the codebase.
    """
    from .knob_overrides import resolve_knob

    enabled = resolve_knob("vector_retrieval_enabled", default=False, roots=roots)
    if not enabled:
        return None

    model = resolve_knob(
        "vector_embedder_model",
        default="paraphrase-multilingual-MiniLM-L12-v2",
        roots=roots,
    )
    device = resolve_knob(
        "vector_embedder_device",
        default="auto",
        roots=roots,
    )
    emb = LocalEmbedder(model_name=str(model), device=str(device))
    return emb if emb.is_available() else None
