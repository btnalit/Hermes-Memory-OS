"""Reversible knob-override store — mirrors crystallized provisional lifecycle.

Boundary is machine-enforced: knobs not in OVERRIDABLE_KNOBS cannot be
overridden. The store is a single JSONL file under the memory-os system
directory. resolve_knob() is deterministic — no LLM on the hot path (INV-5).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .roots import MemoryOSRoots

# ── Dedup sentinel — must be a unique object that cannot appear in JSON ──
_SENTINEL = object()

# ── Overridable knob registry ──────────────────────────────────────────
# Boundary: only knobs listed here can be overridden. base/Hermes knobs
# are never listed → V3 physically cannot touch them.

OVERRIDABLE_KNOBS: dict[str, dict[str, Any]] = {
    "min_cluster_size": {
        "module": "candidate_aggregation",
        "default": 2,
        "bounds": [2, 5],
        "meta": False,
        "scope": "upper_layer",
        "ab_metric": "confirm_rate",
    },
    "max_speak_per_hour": {
        "module": "expression/speak_rate_limit",
        "default": 5,
        "bounds": [1, 12],
        "meta": False,
        "scope": "upper_layer",
        "ab_metric": None,
    },
    "max_provisional": {
        "module": "provisional_sweep",
        "default": 30,
        "bounds": [10, 100],
        "meta": False,
        "scope": "upper_layer",
        "ab_metric": None,
    },
    "lane_low_clue_recall_enabled": {
        "module": "low_clue_recall",
        "default": False,
        "kind": "lane_switch",
        "allowed": [True, False],
        "meta": False,
        "scope": "upper_layer",
        "ab_metric": None,
    },
    "graph_layer_injection_enabled": {
        "module": "prefetch",
        "default": False,
        "kind": "lane_switch",
        "allowed": [True, False],
        "meta": False,
        "scope": "upper_layer",
        "ab_metric": None,
    },
    "session_scoped_recent_events": {
        "module": "prefetch",
        "default": True,
        "kind": "lane_switch",
        "allowed": [True, False],
        "meta": False,
        "scope": "upper_layer",
        "ab_metric": None,
    },
    "vector_retrieval_enabled": {
        "module": "prefetch",
        "default": False,
        "kind": "lane_switch",
        "allowed": [True, False],
        "meta": False,
        "scope": "upper_layer",
        "ab_metric": None,
    },
    "vector_edge_proposer_enabled": {
        "module": "vector_edge_proposer",
        "default": False,
        "kind": "lane_switch",
        "allowed": [True, False],
        "meta": False,
        "scope": "upper_layer",
        "ab_metric": None,
    },
    "vector_embedder_model": {
        "module": "embedder",
        "default": "paraphrase-multilingual-MiniLM-L12-v2",
        "kind": "threshold",
        "bounds": None,
        "meta": False,
        "scope": "upper_layer",
        "ab_metric": None,
    },
    "vector_embedder_device": {
        "module": "embedder",
        "default": "auto",
        "kind": "threshold",
        "bounds": None,
        "meta": False,
        "scope": "upper_layer",
        "ab_metric": None,
    },
    "vector_edge_refines_threshold": {
        "module": "vector_edge_proposer",
        "default": 0.75,
        "bounds": [0.5, 1.0],
        "meta": False,
        "scope": "upper_layer",
        "ab_metric": "refines_rate",
    },
    "vector_edge_co_occurs_threshold": {
        "module": "vector_edge_proposer",
        "default": 0.65,
        "bounds": [0.3, 1.0],
        "meta": False,
        "scope": "upper_layer",
        "ab_metric": "co_occurs_rate",
    },
    "vector_edge_contradicts_threshold": {
        "module": "vector_edge_proposer",
        "default": 0.35,
        "bounds": [0.0, 0.8],
        "meta": False,
        "scope": "upper_layer",
        "ab_metric": "contradicts_rate",
    },
    "llm_contradiction_lane_enabled": {
        "module": "contradiction_lane",
        "default": False,
        "kind": "lane_switch",
        "allowed": [True, False],
        "meta": False,
        "scope": "upper_layer",
        "ab_metric": None,
    },
    "llm_contradiction_same_topic_threshold": {
        "module": "contradiction_lane",
        "default": 0.75,
        "bounds": [0.0, 1.0],
        "meta": False,
        "scope": "upper_layer",
        "ab_metric": "contradiction_candidate_rate",
    },
    "llm_contradiction_candidate_source": {
        "module": "contradiction_lane",
        "default": "cosine",
        "kind": "lane_switch",
        "allowed": ["cosine", "entity"],
        "meta": False,
        "scope": "upper_layer",
        "ab_metric": None,
    },
    "entity_index_enabled": {
        "module": "entity_index",
        "default": False,
        "kind": "lane_switch",
        "allowed": [True, False],
        "meta": False,
        "scope": "upper_layer",
        "ab_metric": None,
    },
    # ── Source gate quality knobs (F.8) ────────────────────────────────
    "auto_promote_enabled": {
        "module": "crystallized",
        "default": True,
        "kind": "lane_switch",
        "allowed": [True, False],
        "meta": False,
        "scope": "upper_layer",
        "ab_metric": None,
    },
    "auto_promote_min_age_days": {
        "module": "crystallized",
        "default": 7,
        "bounds": [3, 30],
        "meta": False,
        "scope": "upper_layer",
        "ab_metric": "promotion_rate",
    },
    "moment_provisional_ttl_days": {
        "module": "crystallized",
        "default": 3,
        "bounds": [1, 14],
        "meta": False,
        "scope": "upper_layer",
        "ab_metric": "moment_ttl_days",
    },
    "recent_cross_session_enabled": {
        "module": "prefetch",
        "default": True,
        "kind": "lane_switch",
        "allowed": [True, False],
        "meta": False,
        "scope": "upper_layer",
        "ab_metric": None,
    },
    "recent_cross_session_max_age_hours": {
        "module": "prefetch",
        "default": 48,
        "bounds": [6, 168],
        "meta": False,
        "scope": "upper_layer",
        "ab_metric": "cross_session_recall_window_hours",
    },
    "recent_cross_session_max_items": {
        "module": "prefetch",
        "default": 5,
        "bounds": [1, 10],
        "meta": False,
        "scope": "upper_layer",
        "ab_metric": "cross_session_max_items",
    },
}

# ── Auto-approvable check ──────────────────────────────────────────────
# Used by self_evolution._knob_tune_proposals() to decide whether a
# knob_tune proposal can be enacted without owner review.

def knob_override_auto_approvable(knob: str, to: Any) -> bool:
    """Return True if a knob_tune proposal can be auto-approved by resolver.

    Four conditions (all must pass):
    1. Knob is registered in OVERRIDABLE_KNOBS (boundary enforcement)
    2. Knob is not meta=True (can't self-tune governance knobs)
    3. Knob is not kind=lane_switch (blast radius too large; always owner)
    4. Value is within bounds (threshold knobs only)

    Reversible is always True for config values (revert = restore prior_value),
    so we don't check it.
    """
    spec = OVERRIDABLE_KNOBS.get(knob)
    if spec is None:
        return False
    if spec.get("meta") is True:
        return False
    if spec.get("kind") == "lane_switch":
        return False
    bounds = spec.get("bounds")
    if bounds is None:
        return False
    lo, hi = bounds[0], bounds[1]
    return lo <= to <= hi


# ── Path resolution ────────────────────────────────────────────────────

def _override_store_path(roots: MemoryOSRoots | None = None, *,
                         _store_root: Path | None = None) -> Path:
    """Resolve the knob-override store path. _store_root is for testing."""
    if _store_root is not None:
        return _store_root / "knob_overrides.jsonl"
    if roots is None:
        roots = MemoryOSRoots.from_profile()
    return roots.memory_os_root / "system" / "knob_overrides.jsonl"


# ── Read ────────────────────────────────────────────────────────────────

def resolve_knob(name: str, default: Any, *,
                 roots: MemoryOSRoots | None = None,
                 _now: datetime | None = None,
                 _store_root: Path | None = None) -> Any:
    """Deterministic: return active override value if present+unexpired, else default.

    No LLM, no network, no side effects — safe for hot paths (INV-5).

    Delegates to :func:`resolve_knobs` so the resolution loop has a single
    implementation shared with ``list_active_overrides``.
    """
    return resolve_knobs(
        {name: default}, roots=roots, _now=_now, _store_root=_store_root,
    )[name]


def resolve_knobs(
    queries: dict[str, Any],
    *,
    roots: MemoryOSRoots | None = None,
    _now: datetime | None = None,
    _store_root: Path | None = None,
) -> dict[str, Any]:
    """Resolve multiple knobs from a single file read (INV-5 hot-path safe).

    Each key in *queries* is a knob name; each value is the default.
    Returns a dict with the same keys mapped to resolved values.
    Reads the knob-override store at most once — substantially cheaper
    than calling :func:`resolve_knob` repeatedly for the same store.
    """
    now = _now or datetime.now(timezone.utc)
    store_path = _override_store_path(roots, _store_root=_store_root)
    if not store_path.exists():
        return dict(queries)

    results: dict[str, Any] = dict(queries)
    definitively_seen: set[str] = set()
    _all_queries = len(queries)
    for record in _read_jsonl_reversed(store_path):
        knob = str(record.get("knob") or "")
        if knob not in queries:
            continue
        if knob in definitively_seen:
            continue
        if not _is_active_state(record):
            definitively_seen.add(knob)
            if len(definitively_seen) == _all_queries:
                break
            continue
        expires_str = str(record.get("expires_at") or "").strip()
        if expires_str and _is_expired(expires_str, now) and _is_provisional_state(record):
            continue
        definitively_seen.add(knob)
        results[knob] = record.get("override_value", queries[knob])
        if len(definitively_seen) == _all_queries:
            break
    return results


# ── Write ───────────────────────────────────────────────────────────────

def register_override(
    name: str,
    value: Any,
    *,
    prior: Any,
    proposed_by: str,
    approved_via: str,
    expires_at: str,
    roots: MemoryOSRoots | None = None,
    _now: datetime | None = None,
    _store_root: Path | None = None,
) -> dict[str, Any]:
    """Write a new override record. Rejects unregistered / out-of-bounds / meta knobs."""
    spec = OVERRIDABLE_KNOBS.get(name)
    if spec is None:
        raise ValueError(
            f"Knob '{name}' is not in OVERRIDABLE_KNOBS — "
            f"boundary enforcement: base/Hermes knobs are not overridable"
        )
    if spec.get("meta") is True:
        raise ValueError(
            f"Knob '{name}' is meta=True — self-tuning of governance knobs is blocked"
        )

    # Allowed-list knobs: validate against allowed list
    allowed = spec.get("allowed")
    if allowed is not None:
        # When the allowed values are bool, use a type-strict check to prevent
        # Python's True==1 / False==0 from accepting int 1 for [True, False].
        if allowed and isinstance(allowed[0], bool):
            if not (type(value) in (bool,) and value in allowed):
                raise ValueError(
                    f"Value {value!r} for knob '{name}' is not in allowed {allowed}"
                )
        else:
            if value not in allowed:
                raise ValueError(
                    f"Value {value!r} for knob '{name}' is not in allowed {allowed}"
                )
    else:
        # Threshold knobs: validate against bounds range
        bounds = spec.get("bounds")
        if bounds is not None:
            lo, hi = bounds[0], bounds[1]
            if not (lo <= value <= hi):
                raise ValueError(
                    f"Value {value} for knob '{name}' is out of bounds [{lo}, {hi}]"
                )

    now = _now or datetime.now(timezone.utc)
    store_path = _override_store_path(roots, _store_root=_store_root)
    store_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Dedup: skip write when the effective value is already the target ──
    # Uses a sentinel default so we can distinguish "no override exists"
    # from "override exists and its value happens to equal the registry
    # default". Prevents self_evolution no-change proposal spam and any
    # other duplicate-override source from bloating the JSONL file.
    if store_path.exists():
        try:
            current_effective = resolve_knob(
                name, default=_SENTINEL, roots=roots, _store_root=_store_root,
            )
        except Exception:
            current_effective = _SENTINEL
        if current_effective is not _SENTINEL and current_effective == value:
            return {
                "schema_version": "memory-os.knob_override.v0",
                "id": "skipped",
                "knob": name,
                "override_value": value,
                "prior_value": prior,
                "state": "skipped",
                "reason": "value_unchanged",
                "ts": now.isoformat(),
            }

    record = {
        "schema_version": "memory-os.knob_override.v0",
        "id": f"ko_{now.strftime('%Y%m%dT%H%M%S%fZ')}_{uuid4().hex[:10]}",
        "knob": name,
        "override_value": value,
        "prior_value": prior,
        "bounds": spec.get("bounds"),
        "allowed": spec.get("allowed"),
        "provisional": True,
        "expires_at": expires_at,
        "proposed_by": proposed_by,
        "approved_via": approved_via,
        "state": "active",
        "ts": now.isoformat(),
    }
    with store_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return record


# ── Lifecycle ───────────────────────────────────────────────────────────

def list_active_overrides(*,
                          roots: MemoryOSRoots | None = None,
                          _now: datetime | None = None,
                          _store_root: Path | None = None) -> list[dict[str, Any]]:
    """Return all currently active (unexpired, unreverted) overrides."""
    now = _now or datetime.now(timezone.utc)
    store_path = _override_store_path(roots, _store_root=_store_root)
    if not store_path.exists():
        return []

    # Iterate newest-first: only the latest record per knob counts.
    # If the latest record is a reversion (inactive state), the knob is not active.
    # But if the latest record is just an expired provisional (active state + past expiry),
    # it is a no-op — skip it and keep looking at older records for the same knob.
    active: dict[str, dict[str, Any]] = {}
    definitively_seen: set[str] = set()  # knobs with a non-expired-inactive latest record
    for record in _read_jsonl_reversed(store_path):
        knob = str(record.get("knob") or "")
        if knob in definitively_seen:
            continue
        if not _is_active_state(record):
            # Non-active record is a definitive state change (e.g. reverted)
            definitively_seen.add(knob)
            continue
        expires_str = str(record.get("expires_at") or "").strip()
        if expires_str and _is_expired(expires_str, now) and _is_provisional_state(record):
            # Expired provisional is a no-op — check older records for this knob
            continue
        # Found an active+unexpired record — this knob's state is settled
        active[knob] = record
        definitively_seen.add(knob)
    return list(active.values())


def revert_override(
    override_id: str,
    *,
    reason: str,
    roots: MemoryOSRoots | None = None,
    _store_root: Path | None = None,
) -> dict[str, Any]:
    """Revert an override: append a new record with state='reverted_*'.

    Invalidate-not-delete: the original override record stays; a new record
    marks the reversion. resolve_knob() reads newest-first, so the reversion
    takes effect.
    """
    now = datetime.now(timezone.utc)
    store_path = _override_store_path(roots, _store_root=_store_root)

    # Find the original override to get prior_value
    original = None
    for record in _read_jsonl(store_path):
        if record.get("id") == override_id:
            original = record
            break
    if original is None:
        raise ValueError(f"Override not found: {override_id}")

    valid_reasons = {
        "owner_rejected", "resolver_ttl_expired", "resolver_cap_evicted",
        "kill_switch_engaged", "owner_reverted",
    }
    state = f"reverted_{reason}" if reason in valid_reasons else "reverted_owner"

    reversion = {
        "schema_version": "memory-os.knob_override.v0",
        "id": f"ko_rev_{now.strftime('%Y%m%dT%H%M%S%fZ')}_{uuid4().hex[:10]}",
        "knob": original.get("knob"),
        "override_value": original.get("prior_value"),  # restored
        "prior_value": original.get("override_value"),   # what was reverted
        "bounds": original.get("bounds"),
        "allowed": original.get("allowed"),
        "provisional": False,
        "expires_at": "",
        "proposed_by": "override_sweep",
        "approved_via": "system",
        "state": state,
        "reverted_from": override_id,
        "revert_reason": reason,
        "ts": now.isoformat(),
    }
    store_path.parent.mkdir(parents=True, exist_ok=True)
    with store_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(reversion, ensure_ascii=False, sort_keys=True) + "\n")
    return reversion


def confirm_override(
    override_id: str,
    *,
    reason: str,
    roots: MemoryOSRoots | None = None,
    _store_root: Path | None = None,
) -> dict[str, Any]:
    """Confirm a provisional override: append a new record with state='confirmed'.

    Mirror of revert_override but instead of reverting, it hardens the override:
    - state='confirmed' (permanent until explicit revert)
    - provisional=False (won't be swept by TTL)
    - expires_at='' (no expiry)
    - prior_value preserved from the original

    This is the A/B auto-confirm write path — goes directly to the knob store
    JSONL (path.open('a')), not through append_governed_jsonl. The
    write_surface_check.py classifies it as 'knob_override_store'.

    Invalidate-not-delete: the original override record stays; a new record
    marks the confirmation.
    """
    now = datetime.now(timezone.utc)
    store_path = _override_store_path(roots, _store_root=_store_root)

    # Find the original override to get its values
    original = None
    for record in _read_jsonl(store_path):
        if record.get("id") == override_id:
            original = record
            break
    if original is None:
        raise ValueError(f"Override not found: {override_id}")

    confirmed = {
        "schema_version": "memory-os.knob_override.v0",
        "id": f"ko_cnf_{now.strftime('%Y%m%dT%H%M%S%fZ')}_{uuid4().hex[:10]}",
        "knob": original.get("knob"),
        "override_value": original.get("override_value"),
        "prior_value": original.get("prior_value"),
        "bounds": original.get("bounds"),
        "allowed": original.get("allowed"),
        "provisional": False,
        "expires_at": "",
        "proposed_by": "knob_ab_eval",
        "approved_via": "ab_auto_confirm",
        "state": "confirmed",
        "confirmed_from": override_id,
        "confirm_reason": reason,
        "ts": now.isoformat(),
    }
    store_path.parent.mkdir(parents=True, exist_ok=True)
    with store_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(confirmed, ensure_ascii=False, sort_keys=True) + "\n")
    return confirmed


# ── Internal helpers ────────────────────────────────────────────────────

def _is_active_state(record: dict[str, Any]) -> bool:
    """Check if record has an active/confirmed state."""
    state = str(record.get("state") or "")
    return state in ("active", "confirmed")


def _is_provisional_state(record: dict[str, Any]) -> bool:
    """Check if record is in a provisional (owner-reversible) state."""
    state = str(record.get("state") or "")
    return state in ("active",)


def _is_expired(expires_str: str, now: datetime) -> bool:
    """Check if an ISO-format expiry string is in the past."""
    try:
        expires_at = datetime.fromisoformat(expires_str)
        return expires_at <= now
    except ValueError:
        return False


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                records.append(parsed)
    return records


def _read_jsonl_reversed(path: Path) -> list[dict[str, Any]]:
    """Read newest-first — latest record per knob takes precedence."""
    records = _read_jsonl(path)
    records.reverse()
    return records
