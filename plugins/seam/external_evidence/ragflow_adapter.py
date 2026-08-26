"""RAGFlow HTTP adapter — external evidence provider for 3.200.

This adapter lives under ``plugins/seam/external_evidence/`` — NEVER in
``plugins/memory/memory_os/``.  The seam boundary is enforced by the
static hygiene check.

Design:
  - Mock-first: default ``_client`` is a no-op stub; real HTTP calls
    require an explicit ``HttpClient`` injection.
  - Fail-open: network errors, timeouts, and non-2xx responses return
    empty results — a broken RAGFlow connection must not block recall.
  - Normalizes RAGFlow search results into ``EvidenceChunk`` via
    ``external_intake`` in core.

3.200 has RAGFlow running (verified 2026-07-06 probe).  Set
``base_url`` + ``api_key_file`` in seam_config.json to activate.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from plugins.seam.external_evidence.types import EvidenceChunk, EvidenceSource
from plugins.seam.external_evidence.config import (
    get_provider_config,
    load_seam_config,
)


@runtime_checkable
class HttpClient(Protocol):
    """Minimal HTTP client protocol — injectable for testing."""

    def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str],
             timeout: float) -> "HttpResponse": ...


class HttpResponse(Protocol):
    status_code: int

    def json(self) -> dict[str, Any]: ...


# ── Default (no-op) client — mock-safe ───────────────────────────────


class _NoOpClient:
    """Default client: always returns empty results (disabled by default)."""

    def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str],
             timeout: float) -> Any:
        return _NoOpResponse()


class _NoOpResponse:
    status_code = 503

    def json(self) -> dict[str, Any]:
        return {}


_noop = _NoOpClient()


class RAGFlowAdapter:
    """Thin adapter wrapping RAGFlow's search API.

    Usage::

        config = load_seam_config("/root/.hermes")
        adapter = RAGFlowAdapter(config)
        chunks = adapter.search("how to fix index-sync", top_k=5)
        for chunk in chunks:
            external_intake(store, content=chunk.content,
                           external_ref=chunk.external_ref,
                           provider="ragflow")
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        *,
        client: HttpClient | None = None,
    ) -> None:
        self._config = config or {}
        self._client: Any = client or _noop
        self._provider_config = get_provider_config(self._config, "ragflow")

    @property
    def enabled(self) -> bool:
        return bool(self._provider_config.get("enabled"))

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        timeout: float = 5.0,
    ) -> list[EvidenceChunk]:
        """Search RAGFlow for evidence matching *query*.

        Returns up to *top_k* ``EvidenceChunk`` results.  Empty list when
        disabled, unreachable, or no results found.
        """
        if not self.enabled:
            return []

        base_url = str(self._provider_config.get("base_url", "")).rstrip("/")
        dataset_id = str(self._provider_config.get("dataset_id", ""))
        api_key = self._read_api_key()

        if not base_url or not dataset_id or not api_key:
            return []

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        # RAGFlow's current retrieval API is dataset-scoped through the
        # request body.  Keep the older dataset search route as a fallback
        # for deployments that still expose it.
        attempts = (
            (
                f"{base_url}/api/v1/retrieval",
                {"question": query, "dataset_ids": [dataset_id], "page_size": top_k},
            ),
            (
                f"{base_url}/api/v1/datasets/{dataset_id}/documents/search",
                {"query": query, "top_k": top_k},
            ),
        )

        for url, body in attempts:
            try:
                resp = self._client.post(
                    url,
                    json=body,
                    headers=headers,
                    timeout=timeout,
                )
                if resp.status_code != 200:
                    continue
                data = resp.json()
                parsed = self._parse_response(data, top_k)
                if parsed:
                    return parsed
            except Exception:
                continue  # fail-open — try compatibility fallback

        return []  # network/API issues must not block recall

    # ── Internal ────────────────────────────────────────────────────

    def _read_api_key(self) -> str:
        api_key_file = str(self._provider_config.get("api_key_file", ""))
        if not api_key_file:
            return ""
        try:
            return Path(api_key_file).read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def _parse_response(
        self, data: dict[str, Any], top_k: int,
    ) -> list[EvidenceChunk]:
        chunks: list[EvidenceChunk] = []
        # RAGFlow returns results in "data.documents" or "data"
        results = data.get("data", {})
        if isinstance(results, dict):
            docs = results.get("documents") or results.get("chunks") or []
        elif isinstance(results, list):
            docs = results
        else:
            return []

        if not isinstance(docs, list):
            return []

        for doc in docs[:top_k]:
            if not isinstance(doc, dict):
                continue
            content = str(doc.get("content") or doc.get("text") or "")
            doc_id = str(doc.get("document_id") or doc.get("id") or "")
            chunk_id = str(doc.get("chunk_id") or doc.get("id") or "")
            score = float(doc.get("score") or doc.get("similarity") or 0.0)

            external_ref = f"ragflow:{doc_id}:{chunk_id}" if doc_id else ""
            if not content.strip() or not external_ref:
                continue

            chunks.append(EvidenceChunk(
                content=content.strip(),
                external_ref=external_ref,
                source=EvidenceSource(
                    provider="ragflow",
                    dataset_id=str(self._provider_config.get("dataset_id", "")),
                    document_id=doc_id,
                    chunk_id=chunk_id,
                ),
                score=score,
            ))

        return chunks
