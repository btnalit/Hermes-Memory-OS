"""External evidence data types — provider-agnostic shapes.

All external providers normalize into these types before passing
through the ``external_intake`` port in core.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any


@dataclass
class EvidenceSource:
    """Identifies where external evidence came from."""

    provider: str = ""     # e.g. "ragflow"
    dataset_id: str = ""
    document_id: str = ""
    chunk_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvidenceChunk:
    """One retrieved chunk of external evidence.

    This is the canonical shape that every provider adapter must produce.
    The adapter is responsible for any provider-specific transformation.
    """

    content: str
    external_ref: str       # unique external reference (required for intake)
    source: EvidenceSource = field(default_factory=EvidenceSource)
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "external_ref": self.external_ref,
            "score": self.score,
            "source": self.source.to_dict(),
            "metadata": dict(self.metadata),
        }

    def is_valid(self) -> bool:
        """Return True if the chunk has a non-empty external_ref."""
        return bool(self.external_ref and self.external_ref.strip())
