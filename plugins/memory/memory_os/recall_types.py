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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
