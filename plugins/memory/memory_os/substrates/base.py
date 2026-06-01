"""Provider-neutral substrate contracts for governed Memory-OS recall."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class SubstrateSnapshot:
    provider: str
    source_ref: str
    version: str

    @property
    def snapshot_id(self) -> str:
        return f"{self.provider}:{self.source_ref}:v{self.version}"


@dataclass(frozen=True)
class GroundingFact:
    provider: str
    capability: str
    body_summary: str
    confidence: float
    provenance: str
    source_event_refs: list[str]
    substrate_snapshot_id: str
    consumer: str = ""
    advisory_only: bool = True
    authority_class: str = "derived_projection"
    recall_llm_triggered: bool = False
    confab_flagged: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_monitor_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "capability": self.capability,
            "confidence": self.confidence,
            "provenance": self.provenance,
            "consumer": self.consumer,
            "advisory_only": self.advisory_only,
            "authority_class": self.authority_class,
            "recall_llm_triggered": self.recall_llm_triggered,
            "confab_flagged": self.confab_flagged,
            "substrate_snapshot_id": self.substrate_snapshot_id,
            "source_event_ref_count": len(self.source_event_refs),
        }


@dataclass(frozen=True)
class ProviderHealth:
    provider: str
    status: str
    capabilities: list[str]
    reason: str = ""
    kill_switch_forced_disabled: bool = False
    substrate_snapshot_id: str = ""

    def to_monitor_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "status": self.status,
            "capabilities": list(self.capabilities),
            "reason": self.reason,
            "kill_switch_forced_disabled": self.kill_switch_forced_disabled,
            "substrate_snapshot_id": self.substrate_snapshot_id,
        }


class MemorySubstrateProvider(Protocol):
    name: str

    def health(self) -> ProviderHealth:
        ...

    def recall(self, query: str, *, consumer: str) -> list[GroundingFact]:
        ...
