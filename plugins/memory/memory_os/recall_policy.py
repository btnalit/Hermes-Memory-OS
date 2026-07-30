"""Versioned authority/freshness data contract for Recall Plan observations."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

AUTHORITY_FRESHNESS_MATRIX_VERSION = "memory-os.authority-freshness-matrix.v1"
AUTHORITY_FRESHNESS_MATRIX: dict[str, Any] = {
    "schema_version": AUTHORITY_FRESHNESS_MATRIX_VERSION,
    "authority_rank": {
        "direct_current_task": 6,
        "owner_confirmed": 5,
        "approved_canonical": 5,
        "session_working": 4,
        "state_projection": 3,
        "indexed_derived": 2,
        "external_unverified": 1,
        "": 0,
    },
    "default_authority_by_recall_type": {
        "state_overlay": "state_projection",
        "crystallized": "approved_canonical",
        "working": "session_working",
        "indexed_fts": "indexed_derived",
        "vector": "indexed_derived",
        "entity_graph": "indexed_derived",
        "temporal": "indexed_derived",
        "hindsight": "external_unverified",
        "external_evidence": "external_unverified",
    },
    "freshness": {
        "minimum": 0.0,
        "maximum": 1.0,
        "default": 1.0,
        "direction": "higher_is_fresher",
    },
    "ranking_precedence": [
        "authority_rank",
        "freshness",
        "relevance_score",
        "stable_input_order",
    ],
}


def authority_freshness_matrix_digest(matrix: Mapping[str, Any]) -> str:
    """Return a stable digest; any policy-data change creates a new window."""

    canonical = json.dumps(matrix, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


AUTHORITY_FRESHNESS_MATRIX_DIGEST = authority_freshness_matrix_digest(AUTHORITY_FRESHNESS_MATRIX)
OBSERVATION_WINDOW_ID = f"{AUTHORITY_FRESHNESS_MATRIX_VERSION}:{AUTHORITY_FRESHNESS_MATRIX_DIGEST}"


# --- Bridge for the substrates-layer authority vocabulary ------------------
#
# Two independent vocabularies encode the same "how authoritative is this
# fact" invariant in this codebase:
#
#   * this module's arbitration vocabulary, keyed directly in
#     ``AUTHORITY_FRESHNESS_MATRIX["authority_rank"]`` above
#     (direct_current_task .. external_unverified, plus "").
#   * the substrates vocabulary produced by GroundingFact-based providers
#     (plugins/memory/memory_os/substrates/base.py): "local_canonical",
#     "owner_approved", "derived_projection".
#
# A RecallObject-based retriever built on top of a substrate (e.g.
# retrievers/hindsight.py) can end up copying a raw substrates-vocabulary
# string into ``authority_class``. Looking that string up directly against
# ``authority_rank`` used to silently default to rank 0 via
# ``.get(authority, 0)`` for ANY unrecognized value -- including a
# genuinely authoritative "local_canonical"/"owner_approved" claim, which
# would then rank BELOW "external_unverified" (rank 1), inverting the
# local-first authority guarantee with no visible signal. This table maps
# every known substrates-vocabulary value onto its arbitration-vocabulary
# equivalent so the lookup is correct instead of a silent zero-default.
SUBSTRATE_AUTHORITY_ALIASES: dict[str, str] = {
    "local_canonical": "approved_canonical",
    "owner_approved": "owner_confirmed",
    "derived_projection": "external_unverified",
}


def resolve_authority_rank(authority_class: str) -> tuple[int, bool]:
    """Resolve an ``authority_class`` string to its arbitration rank.

    Checks the native arbitration vocabulary first (``authority_rank``,
    which also covers the intentionally-empty ``""`` default), then falls
    back to ``SUBSTRATE_AUTHORITY_ALIASES`` for substrates-vocabulary
    strings. Returns ``(rank, recognized)``. ``recognized`` is False only
    when ``authority_class`` matches NEITHER vocabulary -- callers MUST
    treat that case as a flagged anomaly, not as an ordinary rank-0 fact:
    an unrecognized string reaching this function is either a bug (typo,
    stale constant) or drift between the two vocabularies, and silently
    collapsing it into the same rank as an intentionally-unset value would
    hide exactly the authority-inversion failure this bridge exists to
    prevent.
    """
    authority_rank_table = AUTHORITY_FRESHNESS_MATRIX["authority_rank"]
    if authority_class in authority_rank_table:
        return authority_rank_table[authority_class], True
    aliased = SUBSTRATE_AUTHORITY_ALIASES.get(authority_class)
    if aliased is not None and aliased in authority_rank_table:
        return authority_rank_table[aliased], True
    return 0, False


def evaluate_observation_window(observations: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Keep only the latest contiguous suffix produced by the current matrix.

    A changed matrix identity invalidates all earlier samples.  If an old sample
    appears after current samples, the current window is empty rather than being
    silently joined across policy eras.
    """

    rows = [dict(row) for row in observations]
    current_reversed: list[dict[str, Any]] = []
    for row in reversed(rows):
        if str(row.get("observation_window_id") or "") != OBSERVATION_WINDOW_ID:
            break
        current_reversed.append(row)
    current = list(reversed(current_reversed))
    invalidated_count = len(rows) - len(current)
    return {
        "matrix_version": AUTHORITY_FRESHNESS_MATRIX_VERSION,
        "current_matrix_digest": AUTHORITY_FRESHNESS_MATRIX_DIGEST,
        "observation_window_id": OBSERVATION_WINDOW_ID,
        "window_reset_required": invalidated_count > 0,
        "invalidated_observation_count": invalidated_count,
        "current_observation_count": len(current),
        "current_observations": current,
    }


RECALL_OBSERVATION_SCHEMA_VERSION = "memory-os.recall_observation.v1"

# Size-gated retention (P2 fix): append_recall_observation grew the ledger
# forever. Once it exceeds RECALL_OBSERVATION_COMPACT_THRESHOLD records, it
# is rewritten to keep only the newest RECALL_OBSERVATION_RETAIN_COUNT — a
# contiguous tail (oldest rows dropped from the head only), so
# evaluate_observation_window's contiguous-suffix invariant is preserved:
# dropping old head rows can never corrupt the current-era suffix, since the
# suffix is defined relative to the trailing rows, which are never touched.
RECALL_OBSERVATION_COMPACT_THRESHOLD = 2000
RECALL_OBSERVATION_RETAIN_COUNT = 1000


def recall_observation_path(roots: Any) -> Path:
    return Path(roots.memory_os_root) / "system" / "recall_plan_observations.jsonl"


def _compact_recall_observation_ledger(roots: Any) -> None:
    """Trim the ledger to the newest ``RECALL_OBSERVATION_RETAIN_COUNT`` rows.

    No-op until the ledger exceeds ``RECALL_OBSERVATION_COMPACT_THRESHOLD``.
    Uses ``write_jsonl_atomic_locked`` — the same sidecar-lock primitive
    (``locked_jsonl_file``) that ``append_jsonl_locked`` uses for the append
    itself, so this runs under the identical lock discipline (Win32-safe:
    falls back to a threading.Lock when fcntl is unavailable, exactly like
    the append path). Called as a separate, sequential lock acquisition
    after the append's lock is released — nesting the two under one lock
    would trip the reentrant-lock guard in jsonl_io, since both target the
    same sidecar path.
    """
    from .jsonl_io import read_jsonl, write_jsonl_atomic_locked

    path = recall_observation_path(roots)
    records = read_jsonl(path)
    if len(records) <= RECALL_OBSERVATION_COMPACT_THRESHOLD:
        return
    write_jsonl_atomic_locked(path, records[-RECALL_OBSERVATION_RETAIN_COUNT:])


def append_recall_observation(
    roots: Any,
    plan: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> bool:
    """Persist metadata-only shadow evidence bound to the active matrix."""

    if str(plan.get("mode") or "") not in {"shadow", "apply_canary"}:
        return False
    selected_value = plan.get("selected")
    selected: list[Any] = list(selected_value) if isinstance(selected_value, list) else []
    escape_counts: dict[str, int] = {}
    for entry in selected:
        if not isinstance(entry, Mapping):
            continue
        reason = str(entry.get("cooldown_escape_reason") or "")
        if reason:
            escape_counts[reason] = escape_counts.get(reason, 0) + 1
    observed_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    record = {
        "schema_version": RECALL_OBSERVATION_SCHEMA_VERSION,
        "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
        "matrix_version": str(plan.get("authority_freshness_matrix_version") or ""),
        "matrix_digest": str(plan.get("authority_freshness_matrix_digest") or ""),
        "observation_window_id": str(plan.get("observation_window_id") or ""),
        "mode": str(plan.get("mode") or ""),
        "input_count": int(plan.get("input_count") or 0),
        "selected_count": int(plan.get("selected_count") or 0),
        "suppressed_count": int(plan.get("suppressed_count") or 0),
        "exact_duplicate_count": int(plan.get("exact_duplicate_count") or 0),
        "near_duplicate_count": int(plan.get("near_duplicate_count") or 0),
        "conflict_count": int(plan.get("conflict_count") or 0),
        "would_change_live_recall": bool(plan.get("would_change_live_recall")),
        "cooldown_escape_counts": dict(sorted(escape_counts.items())),
    }
    try:
        from .jsonl_io import append_jsonl_locked

        append_jsonl_locked(recall_observation_path(roots), record, durable=True)
        _compact_recall_observation_ledger(roots)
    except OSError:
        return False
    return True


def read_recall_observation_window(roots: Any) -> dict[str, Any]:
    """Consume durable observations and reject every prior matrix era."""

    from .jsonl_io import read_jsonl

    status = evaluate_observation_window(read_jsonl(recall_observation_path(roots)))
    status.pop("current_observations", None)
    return status
