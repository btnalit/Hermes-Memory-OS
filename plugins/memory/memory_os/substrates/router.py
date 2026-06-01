"""Capability router for optional Memory-OS substrates."""

from __future__ import annotations

from typing import Any

from .base import GroundingFact


LOCAL_AUTHORITY_CLASSES = {"local_canonical", "owner_approved"}


def _health_value(health: Any, key: str, default: Any = None) -> Any:
    if isinstance(health, dict):
        return health.get(key, default)
    return getattr(health, key, default)


def _fact_to_dict(fact: Any) -> dict[str, Any]:
    if isinstance(fact, GroundingFact):
        return {
            **fact.to_monitor_dict(),
            "body_summary": fact.body_summary,
            "source_event_refs": list(fact.source_event_refs),
        }
    if isinstance(fact, dict):
        value = dict(fact)
        value.setdefault("provider", "unknown")
        value.setdefault("advisory_only", True)
        value.setdefault("authority_class", "derived_projection")
        value.setdefault("recall_llm_triggered", False)
        return value
    return {
        "provider": "unknown",
        "body_summary": str(fact),
        "advisory_only": True,
        "authority_class": "derived_projection",
        "recall_llm_triggered": False,
    }


def _rank_fact(fact: dict[str, Any]) -> tuple[int, float]:
    authority_class = str(fact.get("authority_class") or "")
    provider = str(fact.get("provider") or "")
    try:
        confidence = float(fact.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    if provider == "local_artifact" and authority_class in LOCAL_AUTHORITY_CLASSES:
        return (0, -confidence)
    if authority_class in LOCAL_AUTHORITY_CLASSES:
        return (1, -confidence)
    return (2, -confidence)


class SubstrateRouter:
    def __init__(self, *, providers: list[Any] | None = None, mode: str = "shadow") -> None:
        self.providers = list(providers or [])
        self.mode = mode if mode in {"shadow", "active"} else "shadow"

    def recall(self, query: str, *, consumer: str) -> dict[str, Any]:
        facts: list[dict[str, Any]] = []
        fallback_triggered = True
        for provider in self.providers:
            health = provider.health()
            capabilities = set(_health_value(health, "capabilities", []) or [])
            if _health_value(health, "status") != "ok" or "recall" not in capabilities:
                continue
            try:
                provider_facts = provider.recall(query, consumer=consumer)
            except Exception:
                continue
            if provider_facts:
                facts.extend(_fact_to_dict(fact) for fact in provider_facts)
                fallback_triggered = False
        facts.sort(key=_rank_fact)
        selected = str(facts[0].get("provider") or "unknown") if facts else "deterministic_fallback"
        authoritative = any(
            str(fact.get("provider") or "") == "local_artifact"
            and fact.get("advisory_only") is False
            and str(fact.get("authority_class") or "") in LOCAL_AUTHORITY_CLASSES
            for fact in facts
        )
        external_authoritative_count = sum(
            1
            for fact in facts
            if str(fact.get("provider") or "") != "local_artifact"
            and str(fact.get("authority_class") or "") in LOCAL_AUTHORITY_CLASSES
        )
        return {
            "schema_version": "memory-os.substrate_recall.v0",
            "mode": self.mode,
            "consumer": consumer,
            "selected_provider": selected,
            "facts": facts,
            "authoritative": authoritative,
            "external_authoritative_count": external_authoritative_count,
            "local_first_authority_preserved": external_authoritative_count == 0,
            "fallback_triggered": fallback_triggered,
            "recall_llm_triggered": any(bool(fact.get("recall_llm_triggered")) for fact in facts),
        }
