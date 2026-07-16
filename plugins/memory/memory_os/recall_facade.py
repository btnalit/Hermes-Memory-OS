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

    def __init__(
        self,
        *,
        arbitration_mode: str = "off",
        freshness_guard_mode: str = "shadow",
        conflict_resolution_mode: str = "shadow",
    ) -> None:
        self._retrievers: dict[RecallType, BaseRetriever] = {}
        self._arbitration_mode = arbitration_mode if arbitration_mode in {"off", "shadow", "apply_canary"} else "off"
        self._freshness_guard_mode = freshness_guard_mode
        self._conflict_resolution_mode = conflict_resolution_mode
        self._session_injection_ledger: dict[str, str] = {}
        self._last_task_revision = ""
        self.last_recall_plan: dict[str, Any] = {}

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
        task_revision = str((scope or {}).get("task_revision") or "")
        self._last_task_revision = task_revision
        if self._arbitration_mode != "off":
            from .recall_arbitration import apply_recall_plan, build_recall_plan

            flattened = [obj for objects in results.values() for obj in objects]
            self.last_recall_plan = build_recall_plan(
                flattened,
                mode=self._arbitration_mode,
                budget_chars=int((scope or {}).get("budget_chars") or 1800),
                current_task_revision=task_revision,
                session_ledger=self._session_injection_ledger,
                freshness_guard_mode=self._freshness_guard_mode,
                conflict_resolution_mode=self._conflict_resolution_mode,
            )
            if self._arbitration_mode == "apply_canary":
                return apply_recall_plan(self.last_recall_plan)
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
        formatted_results: dict[str, list[RecallObject]] = {}
        remaining = max(0, int(budget))
        for rt_str, objects in results.items():
            if not objects or remaining <= 0:
                continue
            rt = RecallType(rt_str)
            retriever = self._retrievers.get(rt)
            if retriever is None:
                continue
            separator_cost = 2 if parts else 0
            available = max(remaining - separator_cost, 0)
            if available <= 0:
                break
            chunk = ""
            included_objects: list[RecallObject] = []
            for count in range(1, len(objects) + 1):
                candidate_chunk = retriever.format_context(
                    objects[:count],
                    budget=min(available, 600),
                ).strip()
                if not candidate_chunk or len(candidate_chunk) > available:
                    break
                chunk = candidate_chunk
                included_objects = list(objects[:count])
            if chunk:
                parts.append(chunk)
                formatted_results[rt_str] = included_objects
                remaining -= separator_cost + len(chunk)
        rendered = "\n\n".join(parts)
        if rendered and formatted_results:
            from .recall_arbitration import record_session_injection

            record_session_injection(
                self._session_injection_ledger,
                formatted_results,
                task_revision=self._last_task_revision,
            )
        return rendered
