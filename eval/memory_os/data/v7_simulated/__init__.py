"""V7 simulated governance scenarios."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


_SCENARIOS: tuple[dict[str, Any], ...] = (
    {
        "scenario_id": "owner_can_be_wrong",
        "summary": "Owner-approved memory is later contradicted by newer observed evidence.",
        "dimensions": ["confab", "crystallized_regression"],
        "provenance": "simulated",
    },
    {
        "scenario_id": "double_blind_unanchored",
        "summary": "Left and right brain agree but neither side has an external grounding anchor.",
        "dimensions": ["double_blind", "grounding_gap"],
        "provenance": "simulated",
    },
    {
        "scenario_id": "cold_start_thin_evidence",
        "summary": "A new subject gets high confidence from one thin inferred signal.",
        "dimensions": ["cold_start", "confab"],
        "provenance": "simulated",
    },
    {
        "scenario_id": "high_confidence_thin_inference",
        "summary": "A high maturity score is attached to inference with low source diversity.",
        "dimensions": ["confab"],
        "provenance": "simulated",
    },
    {
        "scenario_id": "hypothesis_requires_observed_validation",
        "summary": "A proposed candidate hypothesis cannot be promoted until observed evidence validates it.",
        "dimensions": ["cold_start", "double_blind"],
        "provenance": "simulated",
    },
)


def load_scenarios() -> list[dict[str, Any]]:
    return [deepcopy(scenario) for scenario in _SCENARIOS]
