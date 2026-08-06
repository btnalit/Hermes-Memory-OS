"""Memory-OS recall types — unified vocabulary for retriever composition.

Every recall lane gets an explicit enum member so retrievers can be
selected, composed, and probed without stringly-typed dispatch.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field, asdict
from typing import Any


class RecallType(str, enum.Enum):
    """Registered recall lanes.  L1 lanes are core; L2 lanes are optional."""

    # L1 — core retrievers
    STATE_OVERLAY = "state_overlay"
    CRYSTALLIZED = "crystallized"
    WORKING = "working"
    INDEXED_FTS = "indexed_fts"
    VECTOR = "vector"
    ENTITY_GRAPH = "entity_graph"
    TEMPORAL = "temporal"

    # L2 — optional retrievers (only available when extensions are active)
    HINDSIGHT = "hindsight"
    EXTERNAL_EVIDENCE = "external_evidence"


_CORE_RECALL_TYPES: frozenset[RecallType] = frozenset({
    RecallType.STATE_OVERLAY,
    RecallType.CRYSTALLIZED,
    RecallType.WORKING,
    RecallType.INDEXED_FTS,
    RecallType.VECTOR,
    RecallType.ENTITY_GRAPH,
    RecallType.TEMPORAL,
})

_L2_RECALL_TYPES: frozenset[RecallType] = frozenset({
    RecallType.HINDSIGHT,
    RecallType.EXTERNAL_EVIDENCE,
})

# Every enum member's actual implementation home, pinned at module scope so a
# census test can assert both directions (no member without a disposition, no
# disposition without a member). The enum alone over-promises: only the
# "registered" members are reachable through RetrieverFacade.
#   registered       — retriever class registered with the production facade
#   inlined_prefetch — served by a prefetch-internal section builder, not the
#                      facade (WORKING: _working_lines; VECTOR: RRF lane in
#                      _crystallized_lines, vector_retrieval_enabled-gated)
#   probe_only       — retriever class exists for the recall probe CLI and its
#                      tests; production recall goes through the substrate
#                      path instead (HINDSIGHT)
#   unimplemented_reserved — declared, no channel implementation anywhere
RECALL_TYPE_DISPOSITION: dict[RecallType, str] = {
    RecallType.STATE_OVERLAY: "registered",
    RecallType.CRYSTALLIZED: "registered",
    RecallType.WORKING: "inlined_prefetch",
    RecallType.INDEXED_FTS: "registered",
    RecallType.VECTOR: "inlined_prefetch",
    RecallType.ENTITY_GRAPH: "registered",
    RecallType.TEMPORAL: "registered",
    RecallType.HINDSIGHT: "probe_only",
    RecallType.EXTERNAL_EVIDENCE: "unimplemented_reserved",
}


def is_core_recall(recall_type: RecallType) -> bool:
    """Return True for L1 (always-available) recall types."""
    return recall_type in _CORE_RECALL_TYPES


def is_l2_recall(recall_type: RecallType) -> bool:
    """Return True for L2 (optional-extension) recall types."""
    return recall_type in _L2_RECALL_TYPES


@dataclass
class RecallObject:
    """One structured recall result from a retriever.

    Every retriever returns a list of these — same shape regardless of
    the underlying storage (crystallized markdown, FTS5 index, state
    overlay JSON, etc.).
    """

    recall_type: str
    content: str
    score: float = 1.0
    source_ref: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    authority_class: str = ""
    freshness: float = 1.0
    task_revision: str = ""
    claim_key: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
