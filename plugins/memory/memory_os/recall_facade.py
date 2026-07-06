"""Memory-OS retriever facade — composable recall with unified interface.

Every recall lane implements the :class:`BaseRetriever` protocol so
it can be selected, composed, and probed independently.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .recall_types import RecallObject, RecallType


@runtime_checkable
class BaseRetriever(Protocol):
    """Protocol that every Memory-OS retriever must satisfy.

    Implementations live under ``retrievers/`` and are registered
    in :class:`RetrieverFacade` for composite querying.
    """

    @property
    def recall_type(self) -> RecallType: ...

    def retrieve(
        self,
        store: Any,
        query: str,
        *,
        top_k: int = 10,
        scope: dict[str, Any] | None = None,
    ) -> list[RecallObject]:
        """Return up to *top_k* scored :class:`RecallObject` results."""
        ...

    def format_context(
        self,
        objects: list[RecallObject],
        *,
        budget: int = 800,
    ) -> str:
        """Render recall results as bounded markdown for prefetch injection."""
        ...


class RetrieverFacade:
    """Composite retriever that delegates to registered lane retrievers.

    Usage::

        facade = RetrieverFacade()
        facade.register(StateOverlayRetriever())
        results = facade.retrieve(store, "上次做到哪了", recall_types=[RecallType.STATE_OVERLAY])
    """

    def __init__(self) -> None:
        self._retrievers: dict[RecallType, BaseRetriever] = {}

    def register(self, retriever: BaseRetriever) -> None:
        self._retrievers[retriever.recall_type] = retriever

    def get(self, recall_type: RecallType) -> BaseRetriever | None:
        return self._retrievers.get(recall_type)

    def retrieve(
        self,
        store: Any,
        query: str,
        *,
        recall_types: list[RecallType] | None = None,
        top_k: int = 10,
        scope: dict[str, Any] | None = None,
    ) -> dict[str, list[RecallObject]]:
        """Run retrieval across selected (or all registered) lanes.

        Returns a dict mapping recall_type value → list of RecallObject.
        Fail-open: a failing retriever does not block others; its error
        is recorded in the returned dict as an empty list.
        """
        types = recall_types or list(self._retrievers.keys())
        results: dict[str, list[RecallObject]] = {}
        for rt in types:
            retriever = self._retrievers.get(rt)
            if retriever is None:
                results[rt.value] = []
                continue
            try:
                results[rt.value] = retriever.retrieve(
                    store, query, top_k=top_k, scope=scope,
                )
            except Exception:
                results[rt.value] = []  # fail-open
        return results

    def format_context(
        self,
        results: dict[str, list[RecallObject]],
        *,
        budget: int = 1800,
    ) -> str:
        """Render all recall results as bounded prefetch context.

        Each lane's results are rendered through its own
        :meth:`BaseRetriever.format_context` and concatenated.
        """
        parts: list[str] = []
        remaining = budget
        for rt_str, objects in results.items():
            if not objects:
                continue
            rt = RecallType(rt_str)
            retriever = self._retrievers.get(rt)
            if retriever is None:
                continue
            chunk = retriever.format_context(objects, budget=min(remaining, 600))
            if chunk.strip():
                parts.append(chunk)
                remaining -= len(chunk)
                if remaining <= 0:
                    break
        return "\n\n".join(parts)
