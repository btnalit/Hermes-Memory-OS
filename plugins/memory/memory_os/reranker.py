"""Optional post-retrieval reranking for Memory-OS.

The core package intentionally has no ML dependency.  A deployment may provide
an HTTP reranker (or another adapter implementing ``Reranker``), while the
normal/default path remains the existing FTS5 + vector + RRF retrieval.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class RerankerError(RuntimeError):
    """A reranker was unavailable or returned an invalid response."""


@dataclass(frozen=True)
class RerankCandidate:
    record_id: str
    text: str


@dataclass(frozen=True)
class RankedCandidate:
    record_id: str
    score: float
    source_index: int


class Reranker(Protocol):
    def rank(
        self,
        query: str,
        candidates: list[RerankCandidate],
        *,
        top_n: int,
    ) -> list[RankedCandidate]:
        """Return candidates ordered from most to least relevant."""
        ...


class HttpReranker:
    """Small stdlib-only client for an OpenAI-compatible ``/rerank`` service."""

    def __init__(self, *, endpoint: str, model: str = "", timeout_ms: int = 12000) -> None:
        self.endpoint = endpoint.strip()
        self.model = model.strip()
        self.timeout_seconds = max(int(timeout_ms), 100) / 1000.0
        if not self.endpoint:
            raise ValueError("reranker endpoint must not be empty")

    def rank(
        self,
        query: str,
        candidates: list[RerankCandidate],
        *,
        top_n: int,
    ) -> list[RankedCandidate]:
        if not query or not candidates:
            return []
        limit = max(min(int(top_n), len(candidates)), 1)
        payload: dict[str, Any] = {
            "model": self.model,
            "query": query,
            "documents": [candidate.text for candidate in candidates],
            "top_n": limit,
        }
        request = Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise RerankerError(f"reranker request failed: {type(exc).__name__}") from exc
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RerankerError("reranker returned invalid JSON") from exc
        results = body.get("results") if isinstance(body, dict) else None
        if not isinstance(results, list):
            raise RerankerError("reranker response has no results list")

        ranked: list[RankedCandidate] = []
        seen: set[int] = set()
        for item in results:
            if not isinstance(item, dict):
                continue
            try:
                source_index = int(item["index"])
                raw_score = item.get("relevance_score", item.get("score"))
                if raw_score is None:
                    continue
                score = float(raw_score)
            except (KeyError, TypeError, ValueError):
                continue
            if source_index in seen or not 0 <= source_index < len(candidates):
                continue
            seen.add(source_index)
            ranked.append(
                RankedCandidate(
                    record_id=candidates[source_index].record_id,
                    score=score,
                    source_index=source_index,
                )
            )
        if not ranked:
            raise RerankerError("reranker returned no valid candidate results")
        return ranked[:limit]


def build_reranker(config: dict[str, Any] | None) -> Reranker | None:
    """Build an optional provider; return ``None`` for the default path."""
    if not isinstance(config, dict) or not bool(config.get("enabled", False)):
        return None
    provider = str(config.get("provider") or "http").strip().lower()
    if provider != "http":
        raise RerankerError(f"unsupported reranker provider: {provider}")
    return HttpReranker(
        endpoint=str(config.get("endpoint") or ""),
        model=str(config.get("model") or ""),
        timeout_ms=int(config.get("timeout_ms") or 12000),
    )
