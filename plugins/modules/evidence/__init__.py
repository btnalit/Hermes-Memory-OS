"""Evidence modules."""

from .confabulation import ConfabulationDetectorModule, confabulation_detector_manifest
from .scoring import EvidenceScoringModule, evidence_scoring_manifest

__all__ = [
    "ConfabulationDetectorModule",
    "EvidenceScoringModule",
    "confabulation_detector_manifest",
    "evidence_scoring_manifest",
]
