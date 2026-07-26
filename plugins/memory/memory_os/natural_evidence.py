"""
Natural evidence conditions and promotion gate for Memory-OS.

Defines the minimum sufficient conditions for natural evidence,
distinguishes natural from manual and legacy trigger provenance,
and provides the promotion gate that prevents artificial events
from satisfying graduation criteria.

Architecture
============
Natural evidence is evidence produced by scheduled cron jobs, not by
manual invocation or backfill.  The promotion gate checks:
1. Trigger provenance (natural_cron vs manual vs legacy_unmarked)
2. Observation window duration
3. Continuous observation pressure
4. Absence of artificial events
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from .timeutil import parse_utc, now_utc, age_seconds

NATURAL_EVIDENCE_SCHEMA_VERSION = "memory-os.natural_evidence.v1"


class TriggerProvenance(str, Enum):
    """Provenance of a trigger event.

    - NATURAL_CRON: produced by a scheduled cron job (natural_cron)
    - MANUAL: produced by manual invocation
    - LEGACY_UNMARKED: legacy rows without provenance marking
    """

    NATURAL_CRON = "natural_cron"
    MANUAL = "manual"
    LEGACY_UNMARKED = "legacy_unmarked"


class ObservationStatus(str, Enum):
    """Status of an observation window."""

    OBSERVING = "observing"
    SUFFICIENT = "sufficient"
    INSUFFICIENT = "insufficient"
    CONTAMINATED = "contaminated"  # artificial events present


@dataclass
class NaturalEvidenceConfig:
    """Configuration for natural evidence gates."""

    min_observation_days: int = 30
    min_natural_cycle_count: int = 7
    max_manual_credit_ratio: float = 0.0  # no manual credit allowed
    max_legacy_credit_ratio: float = 0.0  # no legacy credit allowed
    observation_window_reset_on_contamination: bool = True


@dataclass
class ObservationWindow:
    """An observation window for a specific phenomenon."""

    key: str
    start_at: str = ""
    natural_cycle_count: int = 0
    manual_cycle_count: int = 0
    legacy_unmarked_count: int = 0
    last_observation_at: str = ""
    is_contaminated: bool = False
    contamination_reason: str = ""
    status: str = "observing"


@dataclass
class NaturalEvidenceGate:
    """Promotion gate for natural evidence.

    Checks whether a phenomenon has accumulated sufficient natural
    observation without artificial contamination.
    """

    key: str
    config: NaturalEvidenceConfig = field(default_factory=NaturalEvidenceConfig)
    window: ObservationWindow = field(default_factory=lambda: ObservationWindow(key=""))


def classify_trigger_provenance(
    row: dict[str, Any],
    *,
    natural_cron_markers: set[str] | None = None,
) -> TriggerProvenance:
    """Classify the trigger provenance of a row.

    A row is:
    - NATURAL_CRON if its trigger field contains a known natural cron marker
    - MANUAL if its trigger field is explicitly "manual"
    - LEGACY_UNMARKED if it has no trigger provenance marker
    """
    markers = natural_cron_markers or {"natural_cron", "cron"}
    trigger = str(row.get("trigger", "") or row.get("provenance", "") or "")
    trigger_lower = trigger.strip().lower()
    if trigger_lower in markers:
        return TriggerProvenance.NATURAL_CRON
    if trigger_lower == "manual":
        return TriggerProvenance.MANUAL
    return TriggerProvenance.LEGACY_UNMARKED


def record_observation(
    window: ObservationWindow,
    row: dict[str, Any],
    *,
    config: NaturalEvidenceConfig | None = None,
    now: datetime | None = None,
) -> ObservationWindow:
    """Record one observation row into the window.

    Returns the updated window.
    """
    cfg = config or NaturalEvidenceConfig()
    ref = now or now_utc()
    provenance = classify_trigger_provenance(row)

    if not window.start_at:
        window.start_at = ref.isoformat()

    window.last_observation_at = ref.isoformat()

    if provenance == TriggerProvenance.NATURAL_CRON:
        window.natural_cycle_count += 1
    elif provenance == TriggerProvenance.MANUAL:
        window.manual_cycle_count += 1
        if cfg.max_manual_credit_ratio == 0.0:
            window.is_contaminated = True
            window.contamination_reason = "manual_event"
    elif provenance == TriggerProvenance.LEGACY_UNMARKED:
        window.legacy_unmarked_count += 1
        if cfg.max_legacy_credit_ratio == 0.0:
            window.is_contaminated = True
            window.contamination_reason = "legacy_unmarked_event"

    window.status = _compute_status(window, cfg, now=ref)
    return window


def _compute_status(
    window: ObservationWindow,
    config: NaturalEvidenceConfig,
    *,
    now: datetime | None = None,
) -> str:
    """Compute the observation status from the window."""
    ref = now or now_utc()
    if window.is_contaminated:
        return ObservationStatus.CONTAMINATED.value

    if not window.start_at:
        return ObservationStatus.INSUFFICIENT.value

    start = parse_utc(window.start_at)
    if start is None:
        return ObservationStatus.INSUFFICIENT.value

    days_elapsed = (ref - start).total_seconds() / 86400.0
    if days_elapsed < config.min_observation_days:
        return ObservationStatus.OBSERVING.value

    if window.natural_cycle_count < config.min_natural_cycle_count:
        return ObservationStatus.OBSERVING.value

    return ObservationStatus.SUFFICIENT.value


def is_promotion_allowed(
    window: ObservationWindow,
    config: NaturalEvidenceConfig | None = None,
) -> bool:
    """Check whether promotion is allowed based on the observation window.

    Returns True only when:
    - Status is SUFFICIENT
    - Window is not contaminated
    """
    cfg = config or NaturalEvidenceConfig()
    if window.is_contaminated:
        return False
    if window.status != ObservationStatus.SUFFICIENT.value:
        return False
    return True


def reset_window(
    window: ObservationWindow,
    *,
    reason: str = "",
) -> ObservationWindow:
    """Reset an observation window (e.g., after contamination)."""
    return ObservationWindow(
        key=window.key,
        start_at="",
        natural_cycle_count=0,
        manual_cycle_count=0,
        legacy_unmarked_count=0,
        last_observation_at="",
        is_contaminated=False,
        contamination_reason="",
        status="observing",
    )


def build_gate_report(
    window: ObservationWindow,
    config: NaturalEvidenceConfig | None = None,
) -> dict[str, Any]:
    """Build a structured gate report."""
    cfg = config or NaturalEvidenceConfig()
    return {
        "schema_version": NATURAL_EVIDENCE_SCHEMA_VERSION,
        "key": window.key,
        "status": window.status,
        "is_contaminated": window.is_contaminated,
        "contamination_reason": window.contamination_reason,
        "natural_cycle_count": window.natural_cycle_count,
        "manual_cycle_count": window.manual_cycle_count,
        "legacy_unmarked_count": window.legacy_unmarked_count,
        "min_observation_days": cfg.min_observation_days,
        "min_natural_cycle_count": cfg.min_natural_cycle_count,
        "promotion_allowed": is_promotion_allowed(window, cfg),
        "observation_days": _observation_days(window),
    }


def _observation_days(window: ObservationWindow) -> float:
    """Return the number of days since the window started."""
    if not window.start_at:
        return 0.0
    start = parse_utc(window.start_at)
    if start is None:
        return 0.0
    return (now_utc() - start).total_seconds() / 86400.0