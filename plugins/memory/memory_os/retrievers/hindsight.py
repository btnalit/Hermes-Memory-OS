"""Hindsight retriever — read-only advisory recall (L2 optional).

This retriever wraps the Hindsight substrate's recall path.  Every
returned ``RecallObject`` carries ``advisory_only=True`` in its
metadata — the retriever can surface insights but NEVER writes to
canonical memory.

Fail-open: when Hindsight is disabled, unreachable, or errors, the
retriever returns an empty list — it must never block normal recall.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from plugins.memory.memory_os.recall_types import RecallObject, RecallType

if TYPE_CHECKING:
    from plugins.memory.memory_os.store import MemoryOSStore


class HindsightRetriever:
    """Read-only Hindsight recall lane.

    Only active when the Hindsight substrate is configured with
    ``recall_mode`` set to ``"active"`` or ``"shadow"``.  In shadow
    mode, results are collected but may not be injected into prefetch
    (depends on the caller's lane policy).
    """

    @property
    def recall_type(self) -> RecallType:
        return RecallType.HINDSIGHT

    def retrieve(
        self,
        store: "MemoryOSStore",
        query: str,
        *,
        top_k: int = 10,
        scope: dict[str, Any] | None = None,
    ) -> list[RecallObject]:
        if not _hindsight_available(store):
            return []

        config = _read_hindsight_config(store)
        recall_mode = str(config.get("recall_mode") or "off")
        if recall_mode not in ("active", "shadow"):
            return []

        # Build a substrate recall report via the existing substrate path
        report = _substrate_recall(store, query, config)
        if not report:
            return []

        facts = report.get("facts", []) if isinstance(report, dict) else []
        if not isinstance(facts, list):
            return []

        objects: list[RecallObject] = []
        for fact in facts[:top_k]:
            if not isinstance(fact, dict):
                continue
            summary = str(fact.get("body_summary") or fact.get("summary") or "")
            if not summary.strip():
                continue
            provider = str(fact.get("provider") or "hindsight")
            authority = str(fact.get("authority_class") or "derived_projection")

            objects.append(RecallObject(
                recall_type=RecallType.HINDSIGHT.value,
                content=summary[:300],
                score=float(fact.get("relevance_score") or 0.5),
                source_ref=f"hindsight:{str(fact.get('substrate_snapshot_id', ''))}",
                metadata={
                    "advisory_only": True,
                    "authority_class": authority,
                    "provider": provider,
                    "recall_llm_triggered": bool(fact.get("recall_llm_triggered")),
                },
            ))

        objects.sort(key=lambda o: o.score, reverse=True)
        return objects[:top_k]

    def format_context(
        self,
        objects: list[RecallObject],
        *,
        budget: int = 800,
    ) -> str:
        if not objects:
            return ""
        lines = ["### Hindsight Advisory (read-only)"]
        lines.append("- ⚠ Advisory only — not canonical memory")
        for obj in objects:
            lines.append(f"- [advisory] {obj.content[:200]}")
        return "\n".join(lines)


# ── Internal ────────────────────────────────────────────────────────


def _hindsight_available(store: Any) -> bool:
    """Check whether the Hindsight substrate is configured and enabled."""
    try:
        config = _read_hindsight_config(store)
        return bool(config.get("enabled"))
    except Exception:
        return False


def _read_hindsight_config(store: Any) -> dict[str, Any]:
    """Extract hindsight config from the store's config dict."""
    # Access via the provider's config if available
    try:
        # MemoryOSStore doesn't carry config, but roots carry the hermes_home
        import json
        config_path = store.roots.hermes_home / "memory-os" / "config.json"
        if config_path.exists():
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            substrates = cfg.get("substrate_providers", {})
            if isinstance(substrates, dict):
                return substrates.get("hindsight", {})
    except Exception:
        pass
    return {}


def _substrate_recall(
    store: "MemoryOSStore",
    query: str,
    config: dict[str, Any],
) -> dict[str, Any] | None:
    """Perform a substrate recall through the existing adapter path.

    Fail-open: any exception returns None.
    """
    try:
        from plugins.memory.memory_os.substrates.hindsight import (
            GovernedHindsightConfig,
            GovernedHindsightSubstrate,
        )
        from plugins.memory.memory_os.substrates.local_artifact import (
            LocalArtifactProvider,
        )
        from plugins.memory.memory_os.substrates.router import SubstrateRouter
    except ImportError:
        return None

    try:
        hs_config = GovernedHindsightConfig.from_dict(config)
        providers: list[Any] = [LocalArtifactProvider(store)]
        providers.append(
            GovernedHindsightSubstrate(
                hs_config,
                client=_hindsight_http_client(config),
                live_guard={},
                invalidated_source_refs=set(),
            )
        )
        router = SubstrateRouter(
            providers=providers,
            mode="active" if config.get("recall_mode") == "active" else "shadow",
        )
        return router.recall(query, consumer="hindsight_retriever")
    except Exception:
        return None


def _hindsight_http_client(config: dict[str, Any]) -> Any:
    """Build an HTTP client for Hindsight from config."""
    api_url = str(config.get("api_url") or "")
    api_key = str(config.get("api_key") or "")
    api_key_env = str(config.get("api_key_env_var") or "HINDSIGHT_API_KEY")

    import os as _os
    if not api_key:
        api_key = _os.environ.get(api_key_env, "")

    class _SimpleClient:
        def __init__(self, base_url: str, key: str):
            self.base_url = base_url
            self.key = key

        def retain(self, payload: dict[str, Any]) -> dict[str, Any]:
            return {"status": "not_implemented_in_retriever"}

        def recall(self, *, bank_id: str, query: str, budget: str,
                   max_tokens: int) -> dict[str, Any]:
            import json as _json
            import urllib.request as _req
            url = f"{self.base_url.rstrip('/')}/banks/{bank_id}/recall"
            body = _json.dumps({
                "query": query, "budget": budget, "max_tokens": max_tokens,
            }).encode("utf-8")
            req = _req.Request(url, data=body, method="POST")
            req.add_header("Content-Type", "application/json")
            if self.key:
                req.add_header("Authorization", f"Bearer {self.key}")
            resp = _req.urlopen(req, timeout=5.0)
            return _json.loads(resp.read().decode("utf-8"))

        def reflect(self, *, bank_id: str, query: str, budget: str) -> dict[str, Any]:
            return {"status": "not_implemented_in_retriever"}

        def invalidate(self, payload: dict[str, Any]) -> dict[str, Any]:
            return {"status": "not_implemented_in_retriever"}

    return _SimpleClient(api_url, api_key)
