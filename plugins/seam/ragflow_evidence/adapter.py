"""RAGFlow evidence adapter — one-way seam from RAGFlow into Memory-OS.

This module is the ONLY place in the codebase where "ragflow" appears as a
code literal.  Memory-OS core (plugins/memory/memory_os/) imports nothing
from here — the dependency flows one way: seam -> memory_os, never reverse.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from plugins.memory.memory_os.external_intake import external_intake
from plugins.memory.memory_os.store import MemoryOSStore


@dataclass(frozen=True)
class EvidenceChunk:
    """A single evidence chunk returned from RAGFlow retrieval."""

    content: str
    external_ref: str
    score: float = 0.0


class RagflowEvidenceClient:
    """RAGFlow HTTP evidence client (stub — HTTP not yet wired).

    Raises ``ValueError`` if constructed without a valid ``base_url``, and
    ``NotImplementedError`` on any retrieval call until the HTTP transport is
    added.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str = "",
        dataset_id: str = "",
        profile: str = "",
    ) -> None:
        if not base_url or not base_url.strip():
            raise ValueError("base_url must be configured")
        self.base_url = base_url.strip()
        self.api_key = api_key.strip()
        self.dataset_id = dataset_id.strip()
        self.profile = profile.strip()

    def retrieve(self, query: str, *, top_k: int = 5) -> list[EvidenceChunk]:
        """Retrieve evidence chunks from RAGFlow.

        Args:
            query: The search query string.
            top_k: Maximum number of chunks to return.

        Returns:
            A list of ``EvidenceChunk`` instances.

        Raises:
            NotImplementedError: HTTP client is not yet wired.
        """
        raise NotImplementedError("RAGFlow HTTP client not yet wired — retrieve is a stub")


def _load_config(hermes_home: str | Path) -> dict[str, Any]:
    """Load RAGFlow adapter config from ``hermes_home/seam/ragflow_evidence/config.json``."""
    config_path = Path(hermes_home).expanduser().resolve() / "seam" / "ragflow_evidence" / "config.json"
    if not config_path.exists():
        return {"ragflow_evidence": {"enabled": False}}
    try:
        return dict(json.loads(config_path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return {"ragflow_evidence": {"enabled": False}}


def ingest_evidence(
    store: MemoryOSStore,
    query: str,
    *,
    hermes_home: str | Path | None = None,
    config: dict[str, Any] | None = None,
) -> list[str]:
    """Retrieve evidence from RAGFlow and land it as tainted events.

    This is the main entry point for the seam adapter.  When the adapter is
    disabled (``enabled != true``) the function is a no-op that returns ``[]``.

    Args:
        store: The ``MemoryOSStore`` instance.
        query: The search query to send to RAGFlow.
        hermes_home: Path to ``HERMES_HOME`` (used when ``config`` is not
            provided to locate ``seam/ragflow_evidence/config.json``).
        config: Inline config dict (takes precedence over file-based config).

    Returns:
        A list of event IDs created by ``external_intake``, one per chunk
        retrieved from RAGFlow.  Empty list when disabled or no chunks found.
    """
    # ── Resolve config ─────────────────────────────────────────────────
    resolved: dict[str, Any] = {"enabled": False}
    if config is not None:
        root = dict(config)
        resolved = dict(root.get("ragflow_evidence", root))
    elif hermes_home is not None:
        resolved = dict(_load_config(hermes_home).get("ragflow_evidence", {}))

    if resolved.get("enabled") is not True:
        return []

    base_url = str(resolved.get("base_url") or "").strip()
    api_key = str(resolved.get("api_key") or "").strip()
    dataset_id = str(resolved.get("dataset_id") or "").strip()
    profile = str(resolved.get("profile") or "").strip()

    client = RagflowEvidenceClient(
        base_url=base_url,
        api_key=api_key,
        dataset_id=dataset_id,
        profile=profile,
    )

    chunks = client.retrieve(query)
    event_ids: list[str] = []

    for chunk in chunks:
        metadata: dict[str, Any] = {}
        if chunk.score:
            metadata["score"] = chunk.score

        event_id = external_intake(
            store,
            content=chunk.content,
            external_ref=chunk.external_ref,
            provider="ragflow",
            metadata=metadata,
        )
        event_ids.append(event_id)

    return event_ids
