"""Governance modules."""

from .ops_gate import OpsGateModule, ops_gate_manifest
from .proposal_queue import ProposalQueueModule, proposal_queue_manifest

__all__ = [
    "OpsGateModule",
    "ProposalQueueModule",
    "ops_gate_manifest",
    "proposal_queue_manifest",
]
