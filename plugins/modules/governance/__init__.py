"""Governance modules."""

from .feedback_bridge import GovernanceFeedbackBridgeModule, governance_feedback_manifest
from .pipeline_checker import LeftBrainPipelineCheckModule, left_brain_pipeline_check_manifest
from .ops_gate import OpsGateModule, ops_gate_manifest
from .proposal_queue import ProposalQueueModule, proposal_queue_manifest
from .self_evolution import SelfEvolutionGovernorModule, self_evolution_manifest

__all__ = [
    "GovernanceFeedbackBridgeModule",
    "LeftBrainPipelineCheckModule",
    "OpsGateModule",
    "ProposalQueueModule",
    "SelfEvolutionGovernorModule",
    "governance_feedback_manifest",
    "left_brain_pipeline_check_manifest",
    "ops_gate_manifest",
    "proposal_queue_manifest",
    "self_evolution_manifest",
]
