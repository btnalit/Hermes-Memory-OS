import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, cast

from plugins.memory.memory_os.config import normalize_memory_reranker_config
from plugins.memory.memory_os.prefetch import (
    _rrf_ordered_ids,
    _try_rerank_crystallized_entries,
)
from plugins.memory.memory_os.reranker import HttpReranker, RerankCandidate


class _TestServer(HTTPServer):
    seen_payload: dict[str, Any] | None


class _RerankHandler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        size = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(size))
        self.server.seen_payload = payload
        body = json.dumps({
            "results": [
                {"index": 1, "relevance_score": 0.99},
                {"index": 0, "relevance_score": 0.80},
            ]
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def _server():
    server = _TestServer(("127.0.0.1", 0), _RerankHandler)
    server.seen_payload = None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_reranker_is_disabled_by_default_without_endpoint():
    config = normalize_memory_reranker_config(None)
    assert config["enabled"] is False
    assert config["mode"] == "disabled"
    assert config["endpoint"] == ""


def test_http_reranker_uses_stdlib_contract_and_preserves_indices():
    server, thread = _server()
    try:
        reranker = HttpReranker(
            endpoint=f"http://127.0.0.1:{server.server_port}/rerank",
            model="Qwen3-Reranker-0.6B",
            timeout_ms=1000,
        )
        result = reranker.rank(
            "Memory-OS 偏好",
            [RerankCandidate("a", "候选 A"), RerankCandidate("b", "候选 B")],
            top_n=2,
        )
        assert [item.record_id for item in result] == ["b", "a"]
        assert server.seen_payload is not None
        assert server.seen_payload["model"] == "Qwen3-Reranker-0.6B"
        assert server.seen_payload["documents"] == ["候选 A", "候选 B"]
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def test_display_rerank_returns_top_n_without_mutating_entries():
    server, thread = _server()
    permanent = [("a", "line A", 0, 0), ("b", "line B", 0, 0), ("c", "line C", 0, 0)]
    before = list(permanent)
    try:
        result = _try_rerank_crystallized_entries(
            "查询 Memory-OS 偏好",
            route="fast_path",
            permanent_entries=permanent,
            provisional_entries=[],
            candidate_order=["a", "b", "c"],
            config={
                "enabled": True,
                "mode": "gated_active",
                "provider": "http",
                "endpoint": f"http://127.0.0.1:{server.server_port}/rerank",
                "model": "test",
                "candidate_limit": 3,
                "output_limit": 2,
                "timeout_ms": 1000,
                "fallback": "rrf",
            },
            error_records=[],
        )
        assert result is not None
        assert [entry[0] for entry in result] == ["b", "a"]
        assert permanent == before
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def test_rerank_failure_returns_none_and_records_fallback():
    errors = []
    result = _try_rerank_crystallized_entries(
        "查询 Memory-OS 偏好",
        route="fast_path",
        permanent_entries=[("a", "line A", 0, 0), ("b", "line B", 0, 0), ("c", "line C", 0, 0)],
        provisional_entries=[],
        candidate_order=["a", "b", "c"],
        config={
            "enabled": True,
            "mode": "gated_active",
            "provider": "http",
            "endpoint": "http://127.0.0.1:1/rerank",
            "candidate_limit": 3,
            "output_limit": 2,
            "timeout_ms": 100,
            "fallback": "rrf",
        },
        error_records=errors,
    )
    assert result is None
    assert errors[-1]["error_code"] == "memory_reranker_fallback_rrf"


def test_router_apply_forwards_memory_reranker_config(monkeypatch):
    from plugins.memory.memory_os import prefetch
    from plugins.memory.memory_os.context_router import ContextSection

    captured = {}
    sections = [ContextSection(
        section="Conversation Carryover",
        text="- carryover",
        source_class="carryover",
        metadata={},
    )]
    config = {"enabled": True, "mode": "gated_active", "provider": "http"}

    def fake_builder(*args, **kwargs):
        captured.update(kwargs)
        return sections

    monkeypatch.setattr(prefetch, "build_prefetch_section_candidates", fake_builder)
    monkeypatch.setattr(
        prefetch,
        "route_context_sections",
        lambda *args, **kwargs: {
            "route": "casual_continuity",
            "selected_sections": [{"section": "Conversation Carryover", "score": 1.0}],
            "dropped_sections": [],
        },
    )
    result = prefetch._build_context_router_apply_prefetch(
        "普通对话",
        budget_chars=2000,
        store=cast(Any, object()),
        context_router_config={"apply_routes": ["all"]},
        memory_reranker_config=config,
    )

    assert result is not None
    assert captured["memory_reranker_config"] is config


def test_rrf_order_is_deterministic_and_union_semantics_remain_separate():
    assert _rrf_ordered_ids(["a", "b"], ["b", "c"], top_n=3) == ["b", "a", "c"]
