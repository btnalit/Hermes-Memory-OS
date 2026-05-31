"""Adapter registry for RH-31 eval surfaces."""

from __future__ import annotations

from dataclasses import dataclass


FIRST_SIX_ADAPTERS = (
    "grep",
    "memory_os_fts",
    "context_projection",
    "low_clue_candidates",
    "memory_sources_replay",
    "diagnostic_grounding",
)


@dataclass(frozen=True)
class EvalAdapterSpec:
    name: str
    module_path: str
    deterministic: bool = True
    provenance: str = "synthetic_fixture"


class EvalAdapterRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, EvalAdapterSpec] = {}

    def register(
        self,
        name: str,
        *,
        module_path: str,
        deterministic: bool = True,
        provenance: str = "synthetic_fixture",
    ) -> None:
        self._specs[name] = EvalAdapterSpec(
            name=name,
            module_path=module_path,
            deterministic=deterministic,
            provenance=provenance,
        )

    def expand(self, adapters: list[str] | tuple[str, ...]) -> list[EvalAdapterSpec]:
        names: list[str] = []
        for adapter in adapters:
            value = str(adapter or "").strip()
            if not value:
                continue
            if value == "all":
                names.extend(FIRST_SIX_ADAPTERS)
            else:
                names.append(value)
        deduped: list[EvalAdapterSpec] = []
        seen: set[str] = set()
        for name in names or list(FIRST_SIX_ADAPTERS):
            spec = self._specs.get(name)
            if spec is None:
                raise ValueError(f"Unsupported RH-31 adapter: {name}")
            if name not in seen:
                deduped.append(spec)
                seen.add(name)
        return deduped


def default_adapter_registry() -> EvalAdapterRegistry:
    registry = EvalAdapterRegistry()
    for name in FIRST_SIX_ADAPTERS:
        registry.register(name, module_path=f"eval.memory_os.adapters.{name}")
    registry.register(
        "simulation_coverage",
        module_path="eval.memory_os.adapters.simulation_coverage",
        provenance="simulated_fixture",
    )
    registry.register(
        "scoring_band",
        module_path="eval.memory_os.adapters.scoring_band",
    )
    registry.register(
        "judge_consistency",
        module_path="eval.memory_os.adapters.judge_consistency",
    )
    registry.register(
        "review_accuracy",
        module_path="eval.memory_os.adapters.review_accuracy",
    )
    registry.register(
        "shadow_recall",
        module_path="eval.memory_os.adapters.shadow_recall",
    )
    registry.register(
        "deferral_accuracy",
        module_path="eval.memory_os.adapters.deferral_accuracy",
    )
    registry.register(
        "migration_regression",
        module_path="eval.memory_os.adapters.migration_regression",
    )
    registry.register(
        "expression_quality",
        module_path="eval.memory_os.adapters.expression_quality",
    )
    registry.register(
        "distillation_fidelity",
        module_path="eval.memory_os.adapters.distillation_fidelity",
    )
    registry.register(
        "confabulation_detection",
        module_path="eval.memory_os.adapters.confabulation_detection",
    )
    registry.register(
        "crystallized_regression",
        module_path="eval.memory_os.adapters.crystallized_regression",
    )
    registry.register(
        "cross_check_anchoring",
        module_path="eval.memory_os.adapters.cross_check_anchoring",
    )
    registry.register(
        "confidence_routing",
        module_path="eval.memory_os.adapters.confidence_routing",
    )
    registry.register(
        "offload_integrity",
        module_path="eval.memory_os.adapters.offload_integrity",
    )
    registry.register(
        "retrieval_shadow",
        module_path="eval.memory_os.adapters.retrieval_shadow",
    )
    return registry
