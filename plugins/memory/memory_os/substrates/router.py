"""Capability router for optional Memory-OS substrates."""

from __future__ import annotations

from typing import Any

from .base import GroundingFact


LOCAL_AUTHORITY_CLASSES = {"local_canonical", "owner_approved"}

# Bounded cap on report["provider_errors"]: providers is a short, fixed
# list (LocalArtifact + at most a handful of substrates), so this is far
# above the realistic count. provider_error_count keeps counting past the
# cap; only the detail list is capped, per the project's bounded-error-record
# convention (see CLAUDE.md "No Silent Failures").
MAX_PROVIDER_ERROR_RECORDS = 8


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


def _is_spoofed_local_authority_claim(fact: dict[str, Any]) -> bool:
    """True when a NON-local-artifact provider self-reports a local
    authority_class (``local_canonical`` / ``owner_approved``).

    Provider identity is checked structurally -- ``provider ==
    "local_artifact"`` -- never inferred from the fact's own claim. Every
    substrate GroundingFact is supposed to be ``advisory_only=True`` /
    ``authority_class="derived_projection"`` (see substrates/base.py and
    this repo's CLAUDE.md: LocalArtifactProvider is the sole primary
    authority). A fact from any other provider claiming otherwise is a
    guard violation regardless of its own ``advisory_only`` value.
    """
    provider = str(fact.get("provider") or "")
    authority_class = str(fact.get("authority_class") or "")
    return provider != "local_artifact" and authority_class in LOCAL_AUTHORITY_CLASSES


def _rank_fact(fact: dict[str, Any]) -> tuple[int, float]:
    authority_class = str(fact.get("authority_class") or "")
    provider = str(fact.get("provider") or "")
    try:
        confidence = float(fact.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    # Tier 0: genuine local-authority facts. Structural provider-identity
    # check only -- a self-reported authority_class from any OTHER
    # provider earns no distinguished tier here. (Defense in depth: by the
    # time facts reach this sort key, SubstrateRouter.recall() has already
    # excluded spoofed claims from the list entirely -- see
    # `_is_spoofed_local_authority_claim` -- so this branch is the only
    # path that can ever produce tier 0.)
    if provider == "local_artifact" and authority_class in LOCAL_AUTHORITY_CLASSES:
        return (0, -confidence)
    return (1, -confidence)


class SubstrateRouter:
    def __init__(self, *, providers: list[Any] | None = None, mode: str = "shadow") -> None:
        self.providers = list(providers or [])
        self.mode = mode if mode in {"shadow", "active"} else "shadow"

    def recall(self, query: str, *, consumer: str) -> dict[str, Any]:
        raw_facts: list[dict[str, Any]] = []
        fallback_triggered = True
        provider_error_count = 0
        provider_errors: list[dict[str, Any]] = []
        for provider in self.providers:
            provider_name = str(getattr(provider, "name", "") or "unknown")
            # health() is guarded separately from recall(): one provider's
            # bad health check must only skip that provider, never abort the
            # whole loop -- an uncaught raise here would otherwise propagate
            # out of recall() entirely, discarding facts already collected
            # from providers processed earlier (including LocalArtifact, the
            # architecture's always-primary authority) and never reaching
            # the return below. Splitting the try per stage (rather than one
            # try around both calls) lets a raise be classified as
            # stage="health" vs stage="recall" -- see "No Silent Failures" in
            # CLAUDE.md: a broad except must not silently drop a provider
            # indistinguishably from one that legitimately reported
            # status != "ok". No message/traceback is recorded here -- only
            # the exception type name -- to keep the report bounded and safe
            # for the per-turn hot path (no I/O, no logging; see INV-5).
            try:
                health = provider.health()
                capabilities = set(_health_value(health, "capabilities", []) or [])
                is_healthy = _health_value(health, "status") == "ok" and "recall" in capabilities
            except Exception as exc:
                provider_error_count += 1
                if len(provider_errors) < MAX_PROVIDER_ERROR_RECORDS:
                    provider_errors.append(
                        {"provider": provider_name, "stage": "health", "error_type": type(exc).__name__}
                    )
                continue
            if not is_healthy:
                continue
            try:
                provider_facts = provider.recall(query, consumer=consumer)
            except Exception as exc:
                provider_error_count += 1
                if len(provider_errors) < MAX_PROVIDER_ERROR_RECORDS:
                    provider_errors.append(
                        {"provider": provider_name, "stage": "recall", "error_type": type(exc).__name__}
                    )
                continue
            if provider_facts:
                raw_facts.extend(_fact_to_dict(fact) for fact in provider_facts)
                fallback_triggered = False

        # Telemetry (authoritative / external_authoritative_count /
        # local_first_authority_preserved) is computed from the UNFILTERED
        # raw_facts so a guard violation is still visible even though it is
        # excluded from the selectable/returned `facts` below -- detection
        # must not disappear just because the offending content is dropped.
        authoritative = any(
            str(fact.get("provider") or "") == "local_artifact"
            and fact.get("advisory_only") is False
            and str(fact.get("authority_class") or "") in LOCAL_AUTHORITY_CLASSES
            for fact in raw_facts
        )
        external_authoritative_count = sum(1 for fact in raw_facts if _is_spoofed_local_authority_claim(fact))

        # Structural guard: a spoofed local-authority claim from a
        # non-local_artifact provider is excluded from `facts` entirely --
        # it must never become `facts[0]`, `selected_provider`, or visible
        # content, only a counted/flagged violation.
        facts = [fact for fact in raw_facts if not _is_spoofed_local_authority_claim(fact)]
        facts.sort(key=_rank_fact)
        selected = str(facts[0].get("provider") or "unknown") if facts else "deterministic_fallback"
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
            "recall_llm_triggered": any(bool(fact.get("recall_llm_triggered")) for fact in raw_facts),
            "provider_error_count": provider_error_count,
            "provider_errors": provider_errors,
        }
