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


def recall_observation_path(roots: Any) -> Path:
    return Path(roots.memory_os_root) / "system" / "recall_plan_observations.jsonl"


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
    except OSError:
        return False
    return True


def read_recall_observation_window(roots: Any) -> dict[str, Any]:
    """Consume durable observations and reject every prior matrix era."""

    from .jsonl_io import read_jsonl

    status = evaluate_observation_window(read_jsonl(recall_observation_path(roots)))
    status.pop("current_observations", None)
    return status
