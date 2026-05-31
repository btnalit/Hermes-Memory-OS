"""Derived V7 evidence profile helpers."""

from __future__ import annotations

from typing import Iterable


EVIDENCE_PROFILE_SCHEMA_VERSION = "memory-os.evidence_profile.v0"


def build_evidence_profile(
    *,
    subject_ref: str,
    subject_kind: str,
    source_ref: str,
    evidence_summary: str,
    tags: Iterable[str] = (),
    provenance: str = "observed",
) -> dict[str, object]:
    """Derive V7 profile fields from bounded metadata, not raw bodies."""

    normalized_tags = {str(tag).strip().lower() for tag in tags if str(tag).strip()}
    normalized_provenance = str(provenance or "observed").strip().lower()
    source = str(source_ref or "").strip().lower()
    kind = str(subject_kind or "").strip().lower()
    summary = str(evidence_summary or "").strip().lower()

    if normalized_provenance == "simulated" or "simulated" in normalized_tags or source.startswith("v7_simulated:"):
        derivation = "simulated"
        normalized_provenance = "simulated"
    elif _owner_assertion(kind=kind, source=source, summary=summary, tags=normalized_tags):
        derivation = "owner_assertion"
    elif _direct_observation(kind=kind, source=source):
        derivation = "direct_observation"
    elif _external_source(source=source, tags=normalized_tags):
        derivation = "external"
    else:
        derivation = "inference"

    return {
        "schema_version": EVIDENCE_PROFILE_SCHEMA_VERSION,
        "subject_ref": str(subject_ref),
        "derivation": derivation,
        "coverage": _coverage(source=source, tags=normalized_tags, provenance=normalized_provenance),
        "abstraction_level": _abstraction_level(derivation),
        "provenance": normalized_provenance,
    }


def _owner_assertion(*, kind: str, source: str, summary: str, tags: set[str]) -> bool:
    if "owner_review" in tags or "owner_action" in tags:
        return True
    if "owner approved" in summary or "owner-approved" in summary:
        return True
    return kind == "crystallized_candidate" and source.startswith("memory_os:crystallized_candidate")


def _direct_observation(*, kind: str, source: str) -> bool:
    if kind == "event" or source.startswith("memory_os:event"):
        return True
    return any(marker in source for marker in ("session_mirror", "state_source_mirror", "cron_mirror"))


def _external_source(*, source: str, tags: set[str]) -> bool:
    if any(marker in source for marker in ("external", "import", "source_mirror", "shadow_import")):
        return True
    return bool(tags & {"external", "import", "source_mirror"})


def _coverage(*, source: str, tags: set[str], provenance: str) -> dict[str, int]:
    if provenance == "simulated":
        return {
            "source_diversity": 0,
            "recurrence": 0,
            "tag_count": len(tags),
        }
    return {
        "source_diversity": 1 if source else 0,
        "recurrence": 0,
        "tag_count": len(tags),
    }


def _abstraction_level(derivation: str) -> str:
    if derivation in {"owner_assertion", "direct_observation"}:
        return "L0"
    if derivation == "external":
        return "L1"
    if derivation == "inference":
        return "L2"
    return "L3"
