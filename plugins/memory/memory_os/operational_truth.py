"""Typed, read-only Operational Truth projection for persisted monitor artifacts.

This module owns no authority and writes no ledger.  It selects exactly one
artifact (the newest observed file), preserves legacy artifact readability, and
keeps artifact freshness distinct from the monitor's policy classification.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


FULL_MONITOR_ARTIFACT_SCHEMA_VERSION = "memory-os.full_monitor_artifact.v1"
LEGACY_MONITOR_SCHEMA_VERSIONS = frozenset({"", "memory-os.monitor.v0"})
UNKNOWN_STATUS = "unknown"
OPERATIONAL_TRUTH_SCHEMA_VERSION = "memory-os.operational_truth_snapshot.v1"
MAX_FUTURE_CLOCK_SKEW_SECONDS = 300


@dataclass(frozen=True)
class ArtifactIdentity:
    path: Path | None
    schema_version: str
    generated_at: str | None
    source_head: str
    runtime_digest: str
    monitor_version: str
    producer_receipt_id: str
    envelope_complete: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path) if self.path is not None else None,
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "source_head": self.source_head,
            "runtime_digest": self.runtime_digest,
            "monitor_version": self.monitor_version,
            "producer_receipt_id": self.producer_receipt_id,
            "envelope_complete": self.envelope_complete,
        }


@dataclass(frozen=True)
class ArtifactFreshness:
    state: str
    age_seconds: int
    stale_after_seconds: int
    observed_from: str

    @property
    def stale(self) -> bool:
        return self.state != "fresh"

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "stale": self.stale,
            "age_seconds": self.age_seconds,
            "stale_after_seconds": self.stale_after_seconds,
            "observed_from": self.observed_from,
        }


@dataclass(frozen=True)
class MonitorClassification:
    status: str
    fail_codes: tuple[str, ...]
    warn_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "fail_codes": list(self.fail_codes),
            "warn_codes": list(self.warn_codes),
        }


@dataclass(frozen=True)
class RuntimeCountObservation:
    field: str
    observed: dict[str, Any]
    conflict: bool
    value: int | None
    invalid_sources: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "observed": dict(self.observed),
            "conflict": self.conflict,
            "value": self.value,
            "invalid_sources": list(self.invalid_sources),
        }


@dataclass(frozen=True)
class FullMonitorTruth:
    artifact: ArtifactIdentity
    freshness: ArtifactFreshness
    classification: MonitorClassification
    payload: dict[str, Any]
    read_error: str | None = None


@dataclass(frozen=True)
class OperationalTruthSnapshot:
    """Shared read projection consumed by status, lane status, and Dashboard."""

    full_monitor: FullMonitorTruth
    runtime_fields: dict[str, RuntimeCountObservation]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": OPERATIONAL_TRUTH_SCHEMA_VERSION,
            "full_monitor": {
                "status": self.full_monitor.classification.status,
                "fail_codes": list(self.full_monitor.classification.fail_codes),
                "warn_codes": list(self.full_monitor.classification.warn_codes),
                "classification": self.full_monitor.classification.to_dict(),
                "generated_at": self.full_monitor.artifact.generated_at,
                "artifact_path": str(self.full_monitor.artifact.path)
                if self.full_monitor.artifact.path
                else None,
                "artifact_age_seconds": self.full_monitor.freshness.age_seconds,
                "stale": self.full_monitor.freshness.stale,
                "artifact_identity": self.full_monitor.artifact.to_dict(),
                "freshness": self.full_monitor.freshness.to_dict(),
                "read_error": self.full_monitor.read_error,
            },
            "runtime_fields": {
                field: observation.to_dict()
                for field, observation in sorted(self.runtime_fields.items())
            },
        }


def _identity_text(value: Any, *, reject_unknown: bool = True) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        return ""
    if reject_unknown and value.lower() == "unknown":
        return ""
    return value


def _strict_nonnegative_count(raw_value: Any) -> int | None:
    if type(raw_value) is int:
        return raw_value if raw_value >= 0 else None
    if isinstance(raw_value, str) and re.fullmatch(r"(?:0|[1-9][0-9]*)", raw_value):
        return int(raw_value)
    return None


def runtime_count_observation(
    *, field: str, observations: Mapping[str, Any]
) -> RuntimeCountObservation:
    normalized: dict[str, int] = {}
    observed: dict[str, Any] = {}
    invalid_sources: list[str] = []
    for source, raw_value in observations.items():
        source_name = str(source)
        if raw_value is None:
            continue
        normalized_value = _strict_nonnegative_count(raw_value)
        if normalized_value is None:
            observed[source_name] = raw_value
            invalid_sources.append(source_name)
            continue
        normalized[source_name] = normalized_value
        observed[source_name] = normalized_value
    distinct = set(normalized.values())
    conflict = bool(invalid_sources) or len(distinct) > 1
    value = next(iter(distinct)) if len(distinct) == 1 and not invalid_sources else None
    return RuntimeCountObservation(
        field=field,
        observed=observed,
        conflict=conflict,
        value=value,
        invalid_sources=tuple(sorted(invalid_sources)),
    )


def read_operational_truth_snapshot(
    *,
    memory_root: Path,
    now: datetime,
    stale_after_seconds: int,
    runtime_count_observations: Mapping[str, Mapping[str, Any]] | None = None,
) -> OperationalTruthSnapshot:
    """Build the single typed read projection used by all operational surfaces."""
    truth = read_full_monitor_truth(
        memory_root=memory_root,
        now=now,
        stale_after_seconds=stale_after_seconds,
    )
    monitor_status = truth.payload.get("memory_status")
    monitor_status = monitor_status if isinstance(monitor_status, dict) else {}
    monitor_counts = monitor_status.get("counts")
    monitor_counts = monitor_counts if isinstance(monitor_counts, dict) else {}
    projected: dict[str, RuntimeCountObservation] = {}
    for field, surface_observations in (runtime_count_observations or {}).items():
        monitor_value: Any = monitor_counts.get(field)
        if field in monitor_counts and (
            truth.read_error or truth.freshness.state in {"invalid_clock", "invalid_envelope"}
        ):
            monitor_value = {"invalid_artifact": truth.read_error or truth.freshness.state}
        observations = {
            "full_monitor.memory_status.counts": monitor_value,
            **dict(surface_observations),
        }
        projected[str(field)] = runtime_count_observation(
            field=str(field),
            observations=observations,
        )
    return OperationalTruthSnapshot(full_monitor=truth, runtime_fields=projected)


def read_full_monitor_truth(
    *, memory_root: Path, now: datetime, stale_after_seconds: int
) -> FullMonitorTruth:
    """Read the newest observed artifact without green-snapshot fallback.

    ``memory_root`` and ``now`` are injected by the caller.  File mtime is used
    only as a legacy freshness fallback; complete v1 envelopes use generated_at.
    """
    selected = _latest_artifact(memory_root)
    if selected is None:
        return _unknown_truth(stale_after_seconds=stale_after_seconds)
    try:
        loaded = json.loads(selected.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return _invalid_truth(
            selected,
            now=now,
            stale_after_seconds=stale_after_seconds,
            read_error=type(exc).__name__,
        )
    if not isinstance(loaded, dict):
        return _invalid_truth(
            selected,
            now=now,
            stale_after_seconds=stale_after_seconds,
            read_error="artifact_root_not_object",
        )

    schema_raw = loaded.get("schema_version")
    is_legacy_envelope = schema_raw is None or (
        isinstance(schema_raw, str) and schema_raw in LEGACY_MONITOR_SCHEMA_VERSIONS
    )
    is_v1_envelope = schema_raw == FULL_MONITOR_ARTIFACT_SCHEMA_VERSION
    unsupported_schema = not is_legacy_envelope and not is_v1_envelope

    receipt_raw = loaded.get("producer_receipt")
    receipt = receipt_raw if isinstance(receipt_raw, dict) else {}
    generated_raw = loaded.get("generated_at")
    generated_at = generated_raw if isinstance(generated_raw, str) and generated_raw else None
    parsed_generated_at = _parse_utc(generated_at)
    source_head = _identity_text(loaded.get("source_head"))
    runtime_digest = _identity_text(loaded.get("runtime_digest"))
    monitor_version = _identity_text(loaded.get("monitor_version"))
    producer_receipt_id = _identity_text(receipt.get("receipt_id"))
    envelope_complete = (
        is_v1_envelope
        and parsed_generated_at is not None
        and bool(source_head)
        and bool(runtime_digest)
        and bool(monitor_version)
        and bool(producer_receipt_id)
    )
    identity = ArtifactIdentity(
        path=selected,
        schema_version=_identity_text(schema_raw, reject_unknown=False),
        generated_at=generated_at,
        source_head=source_head,
        runtime_digest=runtime_digest,
        monitor_version=monitor_version,
        producer_receipt_id=producer_receipt_id,
        envelope_complete=envelope_complete,
    )
    freshness = _freshness(
        selected,
        generated_at=generated_at if envelope_complete else None,
        now=now,
        stale_after_seconds=stale_after_seconds,
    )
    classification_raw = loaded.get("classification")
    if not isinstance(classification_raw, dict):
        classification_raw = loaded.get("results")
    if not isinstance(classification_raw, dict):
        classification_raw = {}
    classification = MonitorClassification(
        status=_classification_status(classification_raw.get("status")),
        fail_codes=_finding_codes(classification_raw, "fail", "fail_codes"),
        warn_codes=_finding_codes(classification_raw, "warn", "warn_codes"),
    )
    read_error = None
    if unsupported_schema or (is_v1_envelope and not envelope_complete):
        read_error = "unsupported_schema_version" if unsupported_schema else "v1_envelope_incomplete"
        freshness = ArtifactFreshness(
            state="invalid_envelope",
            age_seconds=freshness.age_seconds,
            stale_after_seconds=freshness.stale_after_seconds,
            observed_from=read_error,
        )
        classification = MonitorClassification(UNKNOWN_STATUS, (), ())
    elif freshness.state == "invalid_clock":
        read_error = "generated_at_future_clock"
        classification = MonitorClassification(UNKNOWN_STATUS, (), ())
    return FullMonitorTruth(
        artifact=identity,
        freshness=freshness,
        classification=classification,
        payload=loaded,
        read_error=read_error,
    )


def build_full_monitor_envelope(
    payload: Mapping[str, Any],
    *,
    generated_at: datetime,
    source_head: str,
    runtime_digest: str,
    monitor_version: str,
    producer_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Add the standard envelope while preserving monitor-domain payloads."""
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("full-monitor generated_at must be timezone-aware")
    source_head = _identity_text(source_head)
    runtime_digest = _identity_text(runtime_digest)
    monitor_version = _identity_text(monitor_version)
    receipt = dict(producer_receipt)
    receipt_id = _identity_text(receipt.get("receipt_id"))
    missing = [
        name
        for name, value in (
            ("source_head", source_head),
            ("runtime_digest", runtime_digest),
            ("monitor_version", monitor_version),
            ("producer_receipt.receipt_id", receipt_id),
        )
        if not value
    ]
    if missing:
        raise ValueError("incomplete full-monitor envelope identity: " + ", ".join(missing))
    envelope = dict(payload)
    envelope.update(
        {
            "schema_version": FULL_MONITOR_ARTIFACT_SCHEMA_VERSION,
            "generated_at": _utc_text(generated_at),
            "source_head": source_head,
            "runtime_digest": runtime_digest,
            "monitor_version": monitor_version,
            "producer_receipt": receipt,
        }
    )
    return envelope


def _latest_artifact(memory_root: Path) -> Path | None:
    current = [
        path
        for path in (memory_root / "system" / "monitor_artifacts").glob("*.json")
        if path.is_file()
    ]
    if current:
        return max(current, key=_artifact_generation_key)
    legacy = [
        path
        for path in (memory_root / "system").glob("monitor_*.json")
        if path.is_file()
    ]
    if not legacy:
        return None
    return max(legacy, key=lambda path: (path.stat().st_mtime_ns, path.name))


def _artifact_generation_key(path: Path) -> tuple[float, int, str]:
    """Order authoritative artifacts by semantic generation, not mutable mtime alone."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        payload = {}
    if isinstance(payload, dict):
        generated = _parse_utc(payload.get("generated_at"))
        if generated is not None:
            return (generated.timestamp(), 2, path.name)
    match = re.fullmatch(r"monitor_(\d{8}T\d{12}Z)\.json", path.name)
    if match:
        try:
            generated = datetime.strptime(match.group(1), "%Y%m%dT%H%M%S%fZ").replace(tzinfo=timezone.utc)
        except ValueError:
            generated = None
        if generated is not None:
            return (generated.timestamp(), 1, path.name)
    return (path.stat().st_mtime_ns / 1_000_000_000, 0, path.name)


def project_public_counts(
    raw_counts: Mapping[str, Any], operational_truth: Mapping[str, Any]
) -> dict[str, Any]:
    """Render public count fields from the typed projection, hiding conflicted winners."""
    projected = dict(raw_counts)
    runtime_fields = operational_truth.get("runtime_fields")
    if not isinstance(runtime_fields, Mapping):
        return projected
    for field, observation in runtime_fields.items():
        if field not in projected or not isinstance(observation, Mapping):
            continue
        projected[str(field)] = observation.get("value")
    return projected


def _freshness(
    path: Path,
    *,
    generated_at: str | None,
    now: datetime,
    stale_after_seconds: int,
) -> ArtifactFreshness:
    observed_from = "generated_at" if generated_at else "artifact_mtime_legacy"
    observed_at = _parse_utc(generated_at) if generated_at else None
    if observed_at is None:
        observed_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if generated_at:
            observed_from = "artifact_mtime_invalid_generated_at"
    normalized_now = _as_utc(now)
    raw_age_seconds = int((normalized_now - observed_at).total_seconds())
    threshold = max(int(stale_after_seconds), 0)
    if generated_at and raw_age_seconds < -MAX_FUTURE_CLOCK_SKEW_SECONDS:
        return ArtifactFreshness(
            state="invalid_clock",
            age_seconds=raw_age_seconds,
            stale_after_seconds=threshold,
            observed_from="generated_at_future_clock",
        )
    age_seconds = max(raw_age_seconds, 0)
    return ArtifactFreshness(
        state="stale" if age_seconds > threshold else "fresh",
        age_seconds=age_seconds,
        stale_after_seconds=threshold,
        observed_from=observed_from,
    )


def _unknown_truth(*, stale_after_seconds: int) -> FullMonitorTruth:
    return FullMonitorTruth(
        artifact=ArtifactIdentity(None, "", None, "", "", "", "", False),
        freshness=ArtifactFreshness("missing", -1, max(int(stale_after_seconds), 0), "none"),
        classification=MonitorClassification(UNKNOWN_STATUS, (), ()),
        payload={},
        read_error="artifact_missing",
    )


def _invalid_truth(
    path: Path, *, now: datetime, stale_after_seconds: int, read_error: str
) -> FullMonitorTruth:
    observed = _freshness(
        path,
        generated_at=None,
        now=now,
        stale_after_seconds=stale_after_seconds,
    )
    return FullMonitorTruth(
        artifact=ArtifactIdentity(path, "", None, "", "", "", "", False),
        freshness=ArtifactFreshness(
            state="invalid_envelope",
            age_seconds=observed.age_seconds,
            stale_after_seconds=observed.stale_after_seconds,
            observed_from=read_error,
        ),
        classification=MonitorClassification(UNKNOWN_STATUS, (), ()),
        payload={},
        read_error=read_error,
    )


def _finding_codes(data: Mapping[str, Any], entries_key: str, codes_key: str) -> tuple[str, ...]:
    entries = data.get(entries_key)
    if isinstance(entries, list):
        return tuple(
            str(item.get("code") or "")
            for item in entries
            if isinstance(item, dict) and item.get("code")
        )
    codes = data.get(codes_key)
    if isinstance(codes, list):
        return tuple(str(code) for code in codes if str(code))
    return ()


def _classification_status(value: Any) -> str:
    status = str(value or UNKNOWN_STATUS).upper()
    return status if status in {"PASS", "WARN", "FAIL"} else UNKNOWN_STATUS


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return _as_utc(parsed)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _utc_text(value: datetime) -> str:
    return _as_utc(value).isoformat().replace("+00:00", "Z")
