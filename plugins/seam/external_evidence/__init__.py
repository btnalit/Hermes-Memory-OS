"""External Evidence Seam — provider adapters live here, never in memory_os/.

This directory is an L2 optional extension.  Deleting it must leave
Memory-OS core tests green.  Provider-specific literals (ragflow, etc.)
are allowed ONLY here — never in ``plugins/memory/memory_os/``.
"""

from plugins.seam.external_evidence.types import EvidenceChunk, EvidenceSource
from plugins.seam.external_evidence.config import load_seam_config

__all__ = [
    "EvidenceChunk",
    "EvidenceSource",
    "load_seam_config",
]
