import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import numpy as np
import pytest

from plugins.memory.memory_os.embedder import EmbedderError, HttpEmbedder


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        size = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(size))
        assert body["model"] == "BAAI/bge-m3"
        payload = {"data": [{"embedding": [0.1, 0.2, 0.3], "index": 0}]}
        raw = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format, *args):  # noqa: A002, ANN001
        return


class _MalformedHandler(BaseHTTPRequestHandler):
    """Returns a structurally-valid 200 response with no usable embedding."""

    def do_POST(self):  # noqa: N802
        size = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(size)
        # No "data" key at all -> KeyError inside _request's parse step.
        payload = {}
        raw = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format, *args):  # noqa: A002, ANN001
        return


class _EmptyVectorHandler(BaseHTTPRequestHandler):
    """Returns a well-formed 200 response whose embedding vector is empty."""

    def do_POST(self):  # noqa: N802
        size = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(size)
        payload = {"data": [{"embedding": [], "index": 0}]}
        raw = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format, *args):  # noqa: A002, ANN001
        return


def test_http_embedder_returns_vector_without_ml_client_dependency():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        emb = HttpEmbedder(endpoint=f"http://127.0.0.1:{server.server_port}", model_name="BAAI/bge-m3")
        vector = emb.embed_query("hello")
        assert emb.model_name == "BAAI/bge-m3"
        assert emb._device == "cuda"
        assert isinstance(vector, np.ndarray)
        assert vector.dtype == np.float32
        np.testing.assert_allclose(vector, [0.1, 0.2, 0.3])
        assert emb.embed("hello") == vector.tobytes()
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def test_http_embedder_dead_endpoint_raises_typed_error_and_degrades_cleanly():
    """A dead endpoint must raise EmbedderError, never return None silently.

    Counterfactual: with the old `_request` that swallowed every failure into
    `return None`, `embed_query` returning None here would be indistinguishable
    from a legit empty vector — this is the HIGH-severity finding from the
    PR #74 review. `embed()`/`warmup()` keep their pre-existing contracts
    (`b""` / `False`) by catching `EmbedderError` internally.
    """
    emb = HttpEmbedder(endpoint="http://127.0.0.1:1", model_name="test-model", timeout_seconds=0.5)

    with pytest.raises(EmbedderError) as exc_info:
        emb.embed_query("hello")
    assert exc_info.value.reason in {"timeout", "network_error", "http_error"}

    assert emb.embed("hello") == b""
    assert emb.warmup() is False


def test_http_embedder_malformed_response_raises_malformed_response():
    server = HTTPServer(("127.0.0.1", 0), _MalformedHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        emb = HttpEmbedder(endpoint=f"http://127.0.0.1:{server.server_port}", model_name="test-model")
        with pytest.raises(EmbedderError) as exc_info:
            emb.embed_query("hello")
        assert exc_info.value.reason == "malformed_response"
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def test_http_embedder_empty_vector_in_200_response_raises_malformed_response():
    """A structurally-empty vector in a 200 response is malformed, not a valid empty result.

    The service contract always returns a non-empty embedding, so an empty
    vector is a signal of a broken service — not "no data" — and must raise
    rather than being treated as a successful empty result.
    """
    server = HTTPServer(("127.0.0.1", 0), _EmptyVectorHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        emb = HttpEmbedder(endpoint=f"http://127.0.0.1:{server.server_port}", model_name="test-model")
        with pytest.raises(EmbedderError) as exc_info:
            emb.embed_query("hello")
        assert exc_info.value.reason == "malformed_response"
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
