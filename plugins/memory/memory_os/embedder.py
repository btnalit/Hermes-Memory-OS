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
                 device: str = "cpu") -> None:
        self._model_name = model_name
        self._device = device
        self._model = None
        self._available: bool | None = None  # tri-state: None=unchecked
        self._load_failed: bool = False  # guard against repeated failed loads

    @property
    def model_name(self) -> str:
        """Public read-only accessor for the configured model name."""
        return self._model_name

    def is_available(self) -> bool:
        """Lightweight check: is sentence-transformers importable?

        Cached: the check runs once and the result is memoized.
        Returns False when sentence-transformers is not installed or
        the platform is Windows (native deps are unstable on win32).

        This does NOT load the model — model loading is deferred to
        first ``embed()`` / ``embed_query()`` call, or can be triggered
        explicitly via :meth:`warmup`.
        """
        if self._available is not None:
            return self._available
        if _WINDOWS:
            import logging as _logging
            _log = _logging.getLogger(__name__)
            _log.warning(
                "Vector embedding unavailable on Windows: sentence-transformers "
                "native dependencies (torch) are known-unstable on win32 "
                "(segfault / MemoryError). Vector search degrades to FTS5 "
                "full-text search. See docs for platform compatibility details."
            )
            self._available = False
            return False
        try:
            import sentence_transformers  # noqa: F401 — import check only
            self._available = True
        except ImportError:
            self._available = False
        return self._available

    def _ensure_model(self) -> bool:
        """Lazy-load the embedding model on first use.

        Returns True if the model is ready for inference.  Caches the
        loaded model; guards against repeated attempts after a failure
        (call :meth:`warmup` to retry explicitly).
        """
        if self._model is not None:
            return True
        if self._load_failed:
            return False
        if not self.is_available():
            self._load_failed = True
            return False
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name, device=self._device)
            # Warm-up: run a tiny inference to catch runtime errors early
            self._model.encode(["warmup"], show_progress_bar=False)
            return True
        except Exception:
            import logging as _logging
            _log = _logging.getLogger(__name__)
            _log.warning(
                "Failed to load embedding model '%s' on device '%s'. "
                "Vector search will use FTS5 fallback. "
                "Call embedder.warmup() to retry after fixing the issue.",
                self._model_name, self._device, exc_info=True,
            )
            self._load_failed = True
            return False

    def embed(self, text: str) -> bytes:
        """Embed text -> serialized numpy array blob.

        Returns empty bytes if unavailable. Deterministic: same input
        produces the same output vector every time.  Model is loaded
        lazily on first call.
        """
        if not self._ensure_model():
            return b""
        vec = self._model.encode([text], show_progress_bar=False)[0]
        return vec.astype(np.float32).tobytes()

    def embed_query(self, text: str) -> np.ndarray | None:
        """Embed query text -> 1-D numpy array for cosine similarity.

        Returns None if unavailable. This is the hot-path call site --
        called during prefetch for every query. Must be local, fast,
        and never touch the network.  Model is loaded lazily on first call.
        """
        if not self._ensure_model():
            return None
        vec = self._model.encode([text], show_progress_bar=False)[0]
        return vec.astype(np.float32)

    def warmup(self) -> bool:
        """Explicitly pre-load the embedding model.

        Call during controlled initialization to move model loading
        off the hot path.  Resets the failure guard so a previously
        failed load can be retried.

        Returns True if the model loaded successfully.
        """
        self._load_failed = False  # allow retry
        return self._ensure_model()


def build_embedder(roots, *, batch: bool = False) -> LocalEmbedder | None:
    """Factory: build a LocalEmbedder from knob configuration.

    Reads vector_retrieval_enabled, vector_embedder_model, and
    vector_embedder_device from the knob override store. Returns None
    when vector retrieval is disabled or the embedder is unavailable.

    When *batch* is True, reads vector_embedder_batch_device for device
    selection.  Both knobs default to ``"cpu"``; set them independently
    when online and batch jobs need different devices (e.g. online=cpu,
    batch=cuda:0).

    This is the single entry point for all embedder instantiation —
    replaces ad-hoc ``LocalEmbedder()`` calls across the codebase.
    """
    from .knob_overrides import resolve_knob

    enabled = resolve_knob("vector_retrieval_enabled", default=False, roots=roots)
    if not enabled:
        # Startup diagnostic: if embeddings exist but knob is off, warn the operator.
        # This handles the upgrade case where embeddings were previously computed
        # but the new knob defaults to False.
        _index_path = getattr(roots, "index_path", None)
        if _index_path is not None and _index_path.exists():
            try:
                import sqlite3 as _sqlite3
                _conn = _sqlite3.connect(str(_index_path))
                try:
                    _count = _conn.execute(
                        "select count(*) from memory_embeddings"
                    ).fetchone()[0]
                    if _count > 0:
                        import logging as _logging
                        _logging.warning(
                            "vector_retrieval_enabled=False but %d embeddings exist in index. "
                            "Set knob 'vector_retrieval_enabled' to True to restore vector search. "
                            "See: memory-os vector calibrate-thresholds",
                            _count,
                        )
                finally:
                    _conn.close()
            except Exception:
                pass  # Index not accessible — silently skip diagnostic
        return None

    model = resolve_knob(
        "vector_embedder_model",
        default="paraphrase-multilingual-MiniLM-L12-v2",
        roots=roots,
    )
    device = resolve_knob(
        "vector_embedder_device",
        default="cpu",
        roots=roots,
    )
    if batch:
        batch_device = resolve_knob(
            "vector_embedder_batch_device",
            default="cpu",
            roots=roots,
        )
        device = batch_device
    emb = LocalEmbedder(model_name=str(model), device=str(device))
    return emb if emb.is_available() else None
