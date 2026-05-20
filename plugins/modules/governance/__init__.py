"""Governance modules."""

from .ops_gate import OpsGateModule, ops_gate_manifest
from .proposal_queue import ProposalQueueModule, proposal_queue_manifest
from .self_evolution import SelfEvolutionGovernorModule, self_evolution_manifest

__all__ = [
    "OpsGateModule",
    "ProposalQueueModule",
    "SelfEvolutionGovernorModule",
    "ops_gate_manifest",
    "proposal_queue_manifest",
    "self_evolution_manifest",
]
