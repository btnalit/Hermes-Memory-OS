"""
SectionStatus typed phase API for Memory-OS Monitor.

Defines the unified collection state machine that every Monitor section
must go through.  Replaces ad-hoc status checks with a typed pipeline:

    CollectedSnapshot → ClassifiedSnapshot → FinalMonitorSnapshot

Each phase is a read-only snapshot; later phases cannot re-write earlier
phase state.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Callable

SECTION_STATUS_SCHEMA_VERSION = "memory-os.section_status.v1"


class SectionStatus(str):
    """Unified collection status values."""

    COLLECTED = "collected"
    UNAVAILABLE = "unavailable"


# ── Phase snapshots ─────────────────────────────────────────────────────────


@dataclass
class CollectedSnapshot:
    """Raw collected data from a Monitor section.

    invariants:
      - status is always present
      - unavailable → error_code is always non-empty
      - collected → count fields are present
      - missing keys → unavailable, not healthy zero
    """

    section_key: str
    status: str = SectionStatus.UNAVAILABLE
    error_code: str = ""
    error_message: str = ""
    collected_at: str = ""
    count: int = 0
    items: list[dict[str, Any]] = field(default_factory=list)
    raw_data: dict[str, Any] = field(default_factory=dict)

    def is_collected(self) -> bool:
        return self.status == SectionStatus.COLLECTED

    def is_unavailable(self) -> bool:
        return self.status == SectionStatus.UNAVAILABLE

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.status == SectionStatus.UNAVAILABLE and not self.error_code:
            errors.append(f"{self.section_key}: unavailable without error_code")
        if self.status == SectionStatus.COLLECTED:
            if self.count < 0:
                errors.append(f"{self.section_key}: negative count")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SECTION_STATUS_SCHEMA_VERSION,
            "section_key": self.section_key,
            "status": self.status,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "collected_at": self.collected_at,
            "count": self.count,
            "is_collected": self.is_collected(),
        }


@dataclass
class ClassifiedSnapshot:
    """Classified data derived from a CollectedSnapshot.

    invariants:
      - only available when collected is available
      - classification counts sum to collected count
    """

    section_key: str
    status: str = SectionStatus.UNAVAILABLE
    error_code: str = ""
    collected_at: str = ""
    pass_count: int = 0
    fail_count: int = 0
    warn_count: int = 0
    skip_count: int = 0
    classifications: dict[str, int] = field(default_factory=dict)

    def is_collected(self) -> bool:
        return self.status == SectionStatus.COLLECTED

    def is_unavailable(self) -> bool:
        return self.status == SectionStatus.UNAVAILABLE

    def total_classified(self) -> int:
        return self.pass_count + self.fail_count + self.warn_count + self.skip_count

    def validate(self, collected: CollectedSnapshot | None = None) -> list[str]:
        errors: list[str] = []
        if self.status == SectionStatus.UNAVAILABLE and not self.error_code:
            errors.append(f"{self.section_key}: classified unavailable without error_code")
        counts = (self.pass_count, self.fail_count, self.warn_count, self.skip_count)
        if any(type(value) is not int or value < 0 for value in counts):
            errors.append(f"{self.section_key}: classified counts must be non-negative ints")
        if collected is not None and not collected.is_collected() and self.is_collected():
            errors.append(f"{self.section_key}: classified collected from unavailable input")
        if collected is not None and collected.is_collected():
            if self.total_classified() != collected.count:
                errors.append(
                    f"{self.section_key}: classified count {self.total_classified()} != "
                    f"collected count {collected.count}"
                )
        return errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SECTION_STATUS_SCHEMA_VERSION,
            "section_key": self.section_key,
            "status": self.status,
            "error_code": self.error_code,
            "collected_at": self.collected_at,
            "pass_count": self.pass_count,
            "fail_count": self.fail_count,
            "warn_count": self.warn_count,
            "skip_count": self.skip_count,
            "classifications": self.classifications,
            "total_classified": self.total_classified(),
        }


@dataclass
class FinalMonitorSnapshot:
    """Final Monitor snapshot derived from a ClassifiedSnapshot.

    This is the terminal phase.  No further re-writing is allowed.
    """

    section_key: str
    status: str = SectionStatus.UNAVAILABLE
    error_code: str = ""
    collected_at: str = ""
    final_classification: str = "unknown"
    summary: str = ""
    gate_decision: str = ""

    def is_collected(self) -> bool:
        return self.status == SectionStatus.COLLECTED

    def is_unavailable(self) -> bool:
        return self.status == SectionStatus.UNAVAILABLE

    def validate(self, classified: ClassifiedSnapshot | None = None) -> list[str]:
        errors: list[str] = []
        if self.status == SectionStatus.UNAVAILABLE and not self.error_code:
            errors.append(f"{self.section_key}: final unavailable without error_code")
        if classified is not None and not classified.is_collected() and self.is_collected():
            errors.append(f"{self.section_key}: final collected from unavailable input")
        if classified is not None and classified.is_collected():
            if self.final_classification not in ("pass", "fail", "warn", "unknown"):
                errors.append(f"{self.section_key}: invalid final_classification")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SECTION_STATUS_SCHEMA_VERSION,
            "section_key": self.section_key,
            "status": self.status,
            "error_code": self.error_code,
            "collected_at": self.collected_at,
            "final_classification": self.final_classification,
            "summary": self.summary,
            "gate_decision": self.gate_decision,
        }


# ── Phase pipeline ──────────────────────────────────────────────────────────


def build_collected_snapshot(
    section_key: str,
    collector: Callable[[], dict[str, Any]],
    *,
    now: datetime | None = None,
) -> CollectedSnapshot:
    """Build a CollectedSnapshot by calling the collector function.

    If the collector raises, the snapshot is marked unavailable with the
    error code.  Missing keys or type errors are not silently treated as
    healthy zeros.
    """
    ts = (now or datetime.now(timezone.utc)).isoformat()
    try:
        data = collector()
        if not isinstance(data, dict):
            raise TypeError("collector result must be an object")
        if "count" not in data:
            return CollectedSnapshot(
                section_key=section_key,
                status=SectionStatus.UNAVAILABLE,
                error_code="missing_count",
                error_message="collector result omitted required count",
                collected_at=ts,
            )
        count = data["count"]
        if type(count) is not int or count < 0:
            return CollectedSnapshot(
                section_key=section_key,
                status=SectionStatus.UNAVAILABLE,
                error_code="invalid_count_type",
                error_message=f"count must be non-negative int, got {type(count).__name__}",
                collected_at=ts,
            )
        items = data.get("items", [])
        if not isinstance(items, list):
            return CollectedSnapshot(
                section_key=section_key,
                status=SectionStatus.UNAVAILABLE,
                error_code="invalid_items_type",
                error_message=f"items must be a list, got {type(items).__name__}",
                collected_at=ts,
            )
        return CollectedSnapshot(
            section_key=section_key,
            status=SectionStatus.COLLECTED,
            collected_at=ts,
            count=count,
            items=items,
            raw_data=data,
        )
    except Exception as exc:
        return CollectedSnapshot(
            section_key=section_key,
            status=SectionStatus.UNAVAILABLE,
            error_code="collector_failed",
            error_message=str(exc),
            collected_at=ts,
        )


def classify_snapshot(
    collected: CollectedSnapshot,
    classifier: Callable[[CollectedSnapshot], dict[str, Any]],
    *,
    now: datetime | None = None,
) -> ClassifiedSnapshot:
    """Build a ClassifiedSnapshot from a CollectedSnapshot."""
    ts = (now or datetime.now(timezone.utc)).isoformat()
    if not collected.is_collected():
        return ClassifiedSnapshot(
            section_key=collected.section_key,
            status=SectionStatus.UNAVAILABLE,
            error_code=collected.error_code or "collected_unavailable",
            collected_at=ts,
        )
    try:
        data = classifier(collected)
        required = ("pass_count", "fail_count", "warn_count", "skip_count", "classifications")
        if not isinstance(data, dict) or any(key not in data for key in required):
            return ClassifiedSnapshot(
                section_key=collected.section_key,
                status=SectionStatus.UNAVAILABLE,
                error_code="classifier_contract_invalid",
                collected_at=ts,
            )
        counts = [data[key] for key in required[:4]]
        if any(type(value) is not int or value < 0 for value in counts) or not isinstance(
            data["classifications"], dict
        ):
            return ClassifiedSnapshot(
                section_key=collected.section_key,
                status=SectionStatus.UNAVAILABLE,
                error_code="classifier_contract_invalid",
                collected_at=ts,
            )
        snapshot = ClassifiedSnapshot(
            section_key=collected.section_key,
            status=SectionStatus.COLLECTED,
            collected_at=ts,
            pass_count=data["pass_count"],
            fail_count=data["fail_count"],
            warn_count=data["warn_count"],
            skip_count=data["skip_count"],
            classifications=data["classifications"],
        )
        if snapshot.validate(collected):
            return ClassifiedSnapshot(
                section_key=collected.section_key,
                status=SectionStatus.UNAVAILABLE,
                error_code="classification_count_mismatch",
                collected_at=ts,
            )
        return snapshot
    except Exception as exc:
        return ClassifiedSnapshot(
            section_key=collected.section_key,
            status=SectionStatus.UNAVAILABLE,
            error_code="classifier_failed",
            collected_at=ts,
        )


def finalize_snapshot(
    classified: ClassifiedSnapshot,
    finalizer: Callable[[ClassifiedSnapshot], dict[str, Any]],
    *,
    now: datetime | None = None,
) -> FinalMonitorSnapshot:
    """Build a FinalMonitorSnapshot from a ClassifiedSnapshot.

    This is the terminal phase.  No further re-writing is allowed.
    """
    ts = (now or datetime.now(timezone.utc)).isoformat()
    if not classified.is_collected():
        return FinalMonitorSnapshot(
            section_key=classified.section_key,
            status=SectionStatus.UNAVAILABLE,
            error_code=classified.error_code or "classified_unavailable",
            collected_at=ts,
        )
    try:
        data = finalizer(classified)
        if not isinstance(data, dict) or data.get("final_classification") not in {
            "pass", "fail", "warn"
        }:
            return FinalMonitorSnapshot(
                section_key=classified.section_key,
                status=SectionStatus.UNAVAILABLE,
                error_code="finalizer_contract_invalid",
                collected_at=ts,
            )
        return FinalMonitorSnapshot(
            section_key=classified.section_key,
            status=SectionStatus.COLLECTED,
            collected_at=ts,
            final_classification=data.get("final_classification", "unknown"),
            summary=data.get("summary", ""),
            gate_decision=data.get("gate_decision", ""),
        )
    except Exception as exc:
        return FinalMonitorSnapshot(
            section_key=classified.section_key,
            status=SectionStatus.UNAVAILABLE,
            error_code="finalizer_failed",
            collected_at=ts,
        )


def run_pipeline(
    section_key: str,
    collector: Callable[[], dict[str, Any]],
    classifier: Callable[[CollectedSnapshot], dict[str, Any]],
    finalizer: Callable[[ClassifiedSnapshot], dict[str, Any]],
    *,
    now: datetime | None = None,
) -> tuple[CollectedSnapshot, ClassifiedSnapshot, FinalMonitorSnapshot]:
    """Run the full typed pipeline for a Monitor section.

    Returns (collected, classified, final).
    """
    collected = build_collected_snapshot(section_key, collector, now=now)
    classified = classify_snapshot(collected, classifier, now=now)
    final = finalize_snapshot(classified, finalizer, now=now)
    return collected, classified, final