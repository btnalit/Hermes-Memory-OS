"""Governed Hindsight substrate for Memory-OS."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from ..adapters.hindsight import HindsightExportRefused
from .base import GroundingFact, ProviderHealth, SubstrateSnapshot


class HindsightSubstrateClient(Protocol):
    def retain(self, payload: dict[str, Any]) -> dict[str, Any]:
        ...

    def recall(self, *, bank_id: str, query: str, budget: str, max_tokens: int) -> dict[str, Any]:
        ...

    def reflect(self, *, bank_id: str, query: str, budget: str) -> dict[str, Any]:
        ...

    def invalidate(self, payload: dict[str, Any]) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class GovernedHindsightConfig:
    enabled: bool = False
    adoption_source: str = "none"
    api_url: str = ""
    bank_id: str = ""
    provider_config_path: str = ""
    provider_bank_id: str = ""
    bank_selection_reason: str = "not_selected"
    configured_provider_bank_ids: list[str] = field(default_factory=list)
    non_provider_configured_bank_count: int = 0
    api_key: str = ""
    api_key_env_var: str = "HINDSIGHT_API_KEY"
    retain_enabled: bool = False
    recall_mode: str = "off"
    reflect_enabled: bool = False
    allowed_retain_sources: list[str] = field(default_factory=lambda: ["crystallized", "owner_approved"])
    reject_raw_turns: bool = True
    recall_budget: str = "mid"
    recall_max_tokens: int = 1200
    legacy_provider_was_hindsight: bool = False
    legacy_auto_retain_observed_disabled: bool = False
    pollution_scan_status: str = "unknown"

    @property
    def snapshot_id(self) -> str:
        return SubstrateSnapshot("hindsight", self.bank_id or "unconfigured", "current").snapshot_id

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "GovernedHindsightConfig":
        data = value if isinstance(value, dict) else {}
        allowed = data.get("allowed_retain_sources")
        if not isinstance(allowed, list):
            allowed = ["crystallized", "owner_approved"]
        return cls(
            enabled=bool(data.get("enabled")),
            adoption_source=str(data.get("adoption_source") or "none"),
            api_url=str(data.get("api_url") or ""),
            bank_id=str(data.get("bank_id") or ""),
            provider_config_path=str(data.get("provider_config_path") or ""),
            provider_bank_id=str(data.get("provider_bank_id") or ""),
            bank_selection_reason=str(data.get("bank_selection_reason") or "not_selected"),
            configured_provider_bank_ids=[
                str(item) for item in data.get("configured_provider_bank_ids", []) if str(item)
            ]
            if isinstance(data.get("configured_provider_bank_ids"), list)
            else [],
            non_provider_configured_bank_count=int(data.get("non_provider_configured_bank_count") or 0),
            api_key=str(data.get("api_key") or ""),
            api_key_env_var=str(data.get("api_key_env_var") or "HINDSIGHT_API_KEY"),
            retain_enabled=bool(data.get("retain_enabled")),
            recall_mode=str(data.get("recall_mode") or "off"),
            reflect_enabled=bool(data.get("reflect_enabled")),
            allowed_retain_sources=[str(item) for item in allowed],
            reject_raw_turns=bool(data.get("reject_raw_turns", True)),
            recall_budget=str(data.get("recall_budget") or "mid"),
            recall_max_tokens=int(data.get("recall_max_tokens") or 1200),
            legacy_provider_was_hindsight=bool(data.get("legacy_provider_was_hindsight")),
            legacy_auto_retain_observed_disabled=bool(
                data.get("legacy_auto_retain_observed_disabled") or data.get("legacy_auto_retain_hardened")
            ),
            pollution_scan_status=str(data.get("pollution_scan_status") or "unknown"),
        )


class GovernedHindsightSubstrate:
    name = "hindsight"

    def __init__(
        self,
        config: GovernedHindsightConfig,
        *,
        client: HindsightSubstrateClient | None = None,
        live_guard: Any | None = None,
    ) -> None:
        self.config = config
        self.client = client
        self.live_guard = live_guard

    def _kill_switch_enabled(self) -> bool:
        if isinstance(self.live_guard, dict):
            l4 = self.live_guard.get("l4") if isinstance(self.live_guard.get("l4"), dict) else {}
            return bool(l4.get("kill_switch_enabled"))
        checker = getattr(self.live_guard, "kill_switch_enabled", None)
        if checker is None:
            return False
        for value in (self.name, "all_substrates"):
            try:
                if checker(value):
                    return True
            except (AttributeError, TypeError):
                break
        config = getattr(self.live_guard, "config", None)
        if isinstance(config, dict):
            try:
                return bool(checker(config))
            except (AttributeError, TypeError):
                return False
        return False

    def health(self) -> ProviderHealth:
        if self._kill_switch_enabled():
            return ProviderHealth(
                provider=self.name,
                status="disabled",
                capabilities=[],
                reason="kill_switch_enabled",
                kill_switch_forced_disabled=True,
                substrate_snapshot_id=self.config.snapshot_id,
            )
        if not self.config.enabled:
            return ProviderHealth(provider=self.name, status="disabled", capabilities=[])
        if not self.config.bank_id:
            return ProviderHealth(
                provider=self.name,
                status="misconfigured",
                capabilities=[],
                reason="bank_id_missing",
                substrate_snapshot_id=self.config.snapshot_id,
            )
        if self.client is None:
            return ProviderHealth(
                provider=self.name,
                status="unavailable",
                capabilities=[],
                reason="client_missing",
                substrate_snapshot_id=self.config.snapshot_id,
            )
        capabilities = ["retain"]
        if self.config.recall_mode in {"shadow", "active"}:
            capabilities.append("recall")
        if self.config.reflect_enabled:
            capabilities.append("reflect")
        return ProviderHealth(
            provider=self.name,
            status="ok",
            capabilities=capabilities,
            substrate_snapshot_id=self.config.snapshot_id,
        )

    def retain_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._kill_switch_enabled():
            return {"ok": False, "status": "disabled", "reason": "kill_switch_enabled"}
        if not self.config.enabled or not self.config.retain_enabled:
            return {"ok": False, "status": "disabled"}
        metadata = payload.setdefault("metadata", {})
        source_class = str(metadata.get("source_class") or "")
        if source_class not in set(self.config.allowed_retain_sources):
            raise HindsightExportRefused(f"Hindsight retain refused for source_class={source_class or 'raw'}")
        if self.config.reject_raw_turns and source_class in {"raw", "raw_turn", "conversation_turn", "event", "working"}:
            raise HindsightExportRefused("Hindsight retain refused for raw source")
        if self.client is None:
            return {"ok": False, "status": "unavailable", "reason": "client_missing"}
        metadata["substrate_snapshot_id"] = self.config.snapshot_id
        return self.client.retain(payload)

    def recall(self, query: str, *, consumer: str) -> list[GroundingFact]:
        if self._kill_switch_enabled():
            return []
        if not self.config.enabled or self.config.recall_mode == "off" or self.client is None:
            return []
        response = self.client.recall(
            bank_id=self.config.bank_id,
            query=query,
            budget=self.config.recall_budget,
            max_tokens=self.config.recall_max_tokens,
        )
        items = response.get("items", []) if isinstance(response, dict) else []
        facts: list[GroundingFact] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or item.get("summary") or "").strip()
            if not text:
                continue
            facts.append(
                GroundingFact(
                    provider=self.name,
                    capability="recall",
                    body_summary=text,
                    confidence=float(item.get("score") or item.get("confidence") or 0.5),
                    provenance="hindsight_recall",
                    source_event_refs=[str(item.get("source") or "")],
                    substrate_snapshot_id=self.config.snapshot_id,
                    consumer=consumer,
                    advisory_only=True,
                    authority_class="derived_projection",
                    recall_llm_triggered=False,
                )
            )
        return facts

    def reflect(self, query: str, *, consumer: str) -> dict[str, Any]:
        if self._kill_switch_enabled():
            return {
                "provider": self.name,
                "capability": "reflect",
                "status": "disabled",
                "reason": "kill_switch_enabled",
            }
        if not self.config.enabled or not self.config.reflect_enabled:
            return {"provider": self.name, "capability": "reflect", "status": "disabled"}
        if self.client is None:
            return {"provider": self.name, "capability": "reflect", "status": "unavailable"}
        response = self.client.reflect(bank_id=self.config.bank_id, query=query, budget=self.config.recall_budget)
        return {
            "provider": self.name,
            "capability": "reflect",
            "status": "ok",
            "consumer": consumer,
            "advisory_only": True,
            "provenance": "reflect_synthesized",
            "substrate_snapshot_id": self.config.snapshot_id,
            "response": response,
        }

    def invalidate_projection(self, *, source_record_ref: str, source_version: str, reason: str) -> dict[str, Any]:
        if self._kill_switch_enabled():
            return {"ok": False, "status": "disabled", "operation": "invalidate", "reason": "kill_switch_enabled"}
        if not self.config.enabled:
            return {"ok": False, "status": "disabled", "operation": "invalidate"}
        payload = {
            "schema_version": "memory-os.hindsight_invalidate.v0",
            "source_record_ref": source_record_ref,
            "source_version": source_version,
            "reason": reason,
            "substrate_snapshot_id": self.config.snapshot_id,
            "delete_policy": "invalidate_not_delete",
        }
        if self.client is None:
            return {"ok": False, "status": "unavailable", "operation": "invalidate", "payload": payload}
        return self.client.invalidate(payload)
