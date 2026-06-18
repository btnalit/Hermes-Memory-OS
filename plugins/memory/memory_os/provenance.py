"""Provider-agnostic provenance/taint checks for canonical memory writes."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from .jsonl_io import build_error_record

TAINTED_SOURCE_CLASSES = frozenset({"external_evidence"})


def _as_mapping(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if is_dataclass(obj):
        try:
            return asdict(obj)
        except TypeError:
            return {}
    data: dict[str, Any] = {}
    for name in ("safe_ref", "provenance", "source_event_ids", "id", "candidate_id"):
        if hasattr(obj, name):
            data[name] = getattr(obj, name)
    return data


def _provenance_of(obj: Any) -> dict[str, Any]:
    data = _as_mapping(obj)
    provenance = data.get("provenance")
    if isinstance(provenance, dict):
        return provenance
    return {}


def _safe_ref_of(obj: Any) -> dict[str, Any]:
    data = _as_mapping(obj)
    safe_ref = data.get("safe_ref")
    if isinstance(safe_ref, dict):
        return safe_ref
    return {}


def _source_class_of(obj: Any) -> str:
    """Return provider-agnostic source_class for events or candidates.

    Event records expose source_class through safe_ref. Candidate records expose
    it through provenance. The gate intentionally does not inspect provider
    names; provider-specific adapters live outside Memory-OS.
    """
    provenance = _provenance_of(obj)
    if provenance.get("source_class"):
        return str(provenance.get("source_class") or "")
    safe_ref = _safe_ref_of(obj)
    return str(safe_ref.get("source_class") or "")


def _source_event_ids_of(obj: Any) -> list[str]:
    raw = _as_mapping(obj).get("source_event_ids") or []
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if str(item or "").strip()]


_UNKNOWN_EVENT = object()


def _load_events(store: Any, *, error_records: list | None = None) -> list | object:
    """Read events from store once, returning a list or _UNKNOWN_EVENT on failure.

    The result is passed through the is_tainted() call tree so that
    store.read_events() is called exactly once per top-level is_tainted()
    invocation, regardless of recursion depth.
    """
    try:
        return list(store.read_events())
    except Exception:
        if error_records is not None:
            error_records.append(
                build_error_record(
                    component="provenance",
                    operation="load_events",
                    error_code="store_read_events_failed",
                    severity="warning",
                    recoverable=True,
                )
            )
        return _UNKNOWN_EVENT


def _resolve_event_from_store(
    store: Any,
    event_id: str,
    *,
    events_cache: list | object | None = None,
    error_records: list | None = None,
) -> Any | None:
    if not event_id:
        return None
    if events_cache is not None and events_cache is not _UNKNOWN_EVENT:
        for event in events_cache:
            if str(getattr(event, "id", "") or "") == event_id:
                return event
        return None
    if events_cache is _UNKNOWN_EVENT:
        return _UNKNOWN_EVENT
    try:
        events = store.read_events()
    except Exception:
        if error_records is not None:
            error_records.append(
                build_error_record(
                    component="provenance",
                    operation="resolve_event_from_store",
                    error_code="store_read_events_failed",
                    severity="warning",
                    recoverable=True,
                )
            )
        return _UNKNOWN_EVENT
    for event in events:
        if str(getattr(event, "id", "") or "") == event_id:
            return event
    return None


def is_tainted(
    obj: Any,
    *,
    store: Any,
    error_records: list | None = None,
    _events_cache: list | object | None = None,
) -> bool:
    """Return True when obj carries or derives from tainted external evidence.

    This is the single provider-agnostic write-boundary predicate. Missing
    candidate provenance is not treated as proof of cleanliness: source_event_ids
    are resolved transitively and any tainted source event taints the candidate.

    On lookup failure the gate fails closed (tainted=True, spec §2.2).
    When *error_records* is provided, store read failures are recorded as
    bounded error records instead of being silently swallowed.
    """
    source_class = _source_class_of(obj)
    if source_class in TAINTED_SOURCE_CLASSES:
        return True
    provenance = _provenance_of(obj)
    if provenance.get("crystallization_allowed") is False:
        return True
    # Load events once per call-tree — pass cached list through recursion
    events_cache = _events_cache
    if events_cache is None:
        events_cache = _load_events(store, error_records=error_records)
    if events_cache is _UNKNOWN_EVENT:
        return True
    for event_id in _source_event_ids_of(obj):
        event = _resolve_event_from_store(
            store, event_id, events_cache=events_cache, error_records=error_records
        )
        if event is _UNKNOWN_EVENT:
            return True
        if event is not None and is_tainted(
            event, store=store, error_records=error_records, _events_cache=events_cache
        ):
            return True
    return False


def candidate_external_ref(candidate: Any, *, store: Any) -> str | None:
    """Return the first external_ref on a candidate or its tainted source chain."""
    provenance = _provenance_of(candidate)
    direct = str(provenance.get("external_ref") or "").strip()
    if direct:
        return direct
    events_cache = _load_events(store)
    if events_cache is _UNKNOWN_EVENT:
        return None
    for event_id in _source_event_ids_of(candidate):
        event = _resolve_event_from_store(store, event_id, events_cache=events_cache)
        if event is None:
            continue
        for block in (_provenance_of(event), _safe_ref_of(event)):
            ref = str(block.get("external_ref") or "").strip()
            if ref:
                return ref
    return None
