import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import numpy as np

from plugins.memory.memory_os.embedder import HttpEmbedder


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
