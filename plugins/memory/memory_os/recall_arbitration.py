"""Read-time recall arbitration plan with shadow-first conflict handling."""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from typing import Any

from .recall_types import RecallObject, RecallType

SCHEMA_VERSION = "memory-os.recall_plan.v0"
_AUTHORITY_RANK = {
    "direct_current_task": 6,
    "owner_confirmed": 5,
    "approved_canonical": 5,
    "session_working": 4,
    "state_projection": 3,
    "indexed_derived": 2,
    "external_unverified": 1,
    "": 0,
}
_DEFAULT_AUTHORITY = {
    RecallType.STATE_OVERLAY.value: "state_projection",
    RecallType.CRYSTALLIZED.value: "approved_canonical",
    RecallType.WORKING.value: "session_working",
    RecallType.INDEXED_FTS.value: "indexed_derived",
    RecallType.VECTOR.value: "indexed_derived",
    RecallType.ENTITY_GRAPH.value: "indexed_derived",
    RecallType.TEMPORAL.value: "indexed_derived",
    RecallType.HINDSIGHT.value: "external_unverified",
    RecallType.EXTERNAL_EVIDENCE.value: "external_unverified",
}


def build_recall_plan(
    objects: list[RecallObject],
    *,
    mode: str = "shadow",
    budget_chars: int = 1800,
    current_task_revision: str = "",
    session_ledger: dict[str, str] | None = None,
    near_duplicate_threshold: float = 0.88,
    freshness_guard_mode: str = "shadow",
    conflict_resolution_mode: str = "shadow",
) -> dict[str, Any]:
    """Build a bounded arbitration projection without mutating durable state."""

    ledger = session_ledger or {}
    candidates: list[dict[str, Any]] = []
    suppressed: list[dict[str, Any]] = []
    shadow_findings: list[dict[str, Any]] = []
    for index, obj in enumerate(objects):
        fingerprint = content_fingerprint(obj.content)
        authority = obj.authority_class or str(obj.metadata.get("authority_class") or "") or _DEFAULT_AUTHORITY.get(obj.recall_type, "")
        task_revision = obj.task_revision or str(obj.metadata.get("task_revision") or "")
        claim_key = obj.claim_key or str(obj.metadata.get("claim_key") or "")
        entry = {
            "index": index,
            "object": obj,
            "fingerprint": fingerprint,
            "authority_class": authority,
            "authority_rank": _AUTHORITY_RANK.get(authority, 0),
            "freshness": max(0.0, min(1.0, float(obj.freshness))),
            "task_revision": task_revision,
            "claim_key": claim_key,
        }
        if obj.recall_type == RecallType.STATE_OVERLAY.value and current_task_revision and task_revision != current_task_revision:
            finding = _suppression(entry, "stale_task_revision")
            if freshness_guard_mode != "off" and not (
                mode == "apply_canary" and freshness_guard_mode == "shadow"
            ):
                suppressed.append(finding)
                continue
            if freshness_guard_mode == "shadow":
                shadow_findings.append(finding)
        if fingerprint in ledger and ledger[fingerprint] == current_task_revision:
            suppressed.append(_suppression(entry, "session_duplicate"))
            continue
        candidates.append(entry)

    exact_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in candidates:
        exact_groups[entry["fingerprint"]].append(entry)
    deduped: list[dict[str, Any]] = []
    exact_duplicate_count = 0
    for group in exact_groups.values():
        ranked = sorted(group, key=_rank_key)
        deduped.append(ranked[0])
        for duplicate in ranked[1:]:
            exact_duplicate_count += 1
            suppressed.append(_suppression(duplicate, "exact_duplicate"))

    near_deduped: list[dict[str, Any]] = []
    near_duplicate_count = 0
    for entry in sorted(deduped, key=_rank_key):
        duplicate_of = next(
            (
                retained
                for retained in near_deduped
                if _token_jaccard(entry["object"].content, retained["object"].content) >= near_duplicate_threshold
            ),
            None,
        )
        if duplicate_of is None:
            near_deduped.append(entry)
        else:
            near_duplicate_count += 1
            suppressed.append(_suppression(entry, "near_duplicate", related=duplicate_of["fingerprint"]))

    conflict_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in near_deduped:
        if entry["claim_key"]:
            conflict_groups[entry["claim_key"]].append(entry)
    conflict_fingerprints: set[str] = set()
    conflicts: list[dict[str, Any]] = []
    for claim_key, group in conflict_groups.items():
        if conflict_resolution_mode == "off":
            continue
        distinct = {entry["fingerprint"] for entry in group}
        if len(distinct) < 2:
            continue
        ranked = sorted(group, key=_rank_key)
        top_rank = ranked[0]["authority_rank"]
        top = [entry for entry in ranked if entry["authority_rank"] == top_rank]
        owner_conflict = top_rank >= _AUTHORITY_RANK["owner_confirmed"] and len({entry["fingerprint"] for entry in top}) > 1
        status = "owner_conflict_requires_clarification" if owner_conflict else "lower_authority_suppressed"
        conflicts.append({
            "claim_key": claim_key,
            "status": status,
            "source_refs": [entry["object"].source_ref for entry in ranked],
        })
        if owner_conflict:
            for entry in group:
                finding = _suppression(entry, status)
                if mode == "apply_canary" and conflict_resolution_mode == "shadow":
                    shadow_findings.append(finding)
                else:
                    conflict_fingerprints.add(entry["fingerprint"])
                    suppressed.append(finding)
        else:
            for entry in ranked[1:]:
                finding = _suppression(entry, "lower_authority_conflict")
                if mode == "apply_canary" and conflict_resolution_mode == "shadow":
                    shadow_findings.append(finding)
                else:
                    conflict_fingerprints.add(entry["fingerprint"])
                    suppressed.append(finding)

    ranked_candidates = [
        entry for entry in sorted(near_deduped, key=_rank_key)
        if entry["fingerprint"] not in conflict_fingerprints
    ]
    selected: list[dict[str, Any]] = []
    used_chars = 0
    for entry in ranked_candidates:
        cost = len(entry["object"].content)
        if used_chars + cost > max(0, int(budget_chars)):
            suppressed.append(_suppression(entry, "budget_exceeded"))
            continue
        selected.append(_public_entry(entry))
        used_chars += cost

    return {
        "schema_version": SCHEMA_VERSION,
        "mode": mode if mode in {"off", "shadow", "apply_canary"} else "shadow",
        "freshness_guard_mode": freshness_guard_mode,
        "conflict_resolution_mode": conflict_resolution_mode,
        "current_task_revision": current_task_revision,
        "input_count": len(objects),
        "selected_count": len(selected),
        "suppressed_count": len(suppressed),
        "exact_duplicate_count": exact_duplicate_count,
        "near_duplicate_count": near_duplicate_count,
        "conflict_count": len(conflicts),
        "used_budget_chars": used_chars,
        "budget_chars": max(0, int(budget_chars)),
        "selected": selected,
        "suppressed": suppressed,
        "conflicts": conflicts,
        "shadow_findings": shadow_findings,
        "would_change_live_recall": bool(suppressed or shadow_findings or len(selected) != len(objects)),
    }


def apply_recall_plan(plan: dict[str, Any]) -> dict[str, list[RecallObject]]:
    """Convert a validated plan into the facade's lane-keyed result shape."""
    results: dict[str, list[RecallObject]] = defaultdict(list)
    for entry in plan.get("selected") or []:
        payload = entry.get("object") if isinstance(entry, dict) else None
        if isinstance(payload, dict):
            try:
                obj = RecallObject(**payload)
            except (TypeError, ValueError):
                continue
            results[obj.recall_type].append(obj)
    return dict(results)


def record_session_injection(
    session_ledger: dict[str, str],
    results: dict[str, list[RecallObject]],
    *,
    task_revision: str,
) -> None:
    """Record only actually formatted objects in the provider-local ledger."""
    for objects in results.values():
        for obj in objects:
            session_ledger[content_fingerprint(obj.content)] = task_revision


def content_fingerprint(content: str) -> str:
    normalized = " ".join(str(content or "").casefold().split())
    return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _rank_key(entry: dict[str, Any]) -> tuple[float, float, float, int]:
    return (
        -float(entry["authority_rank"]),
        -float(entry["freshness"]),
        -float(entry["object"].score),
        int(entry["index"]),
    )


def _public_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "object": entry["object"].to_dict(),
        "fingerprint": entry["fingerprint"],
        "authority_class": entry["authority_class"],
        "freshness": entry["freshness"],
        "task_revision": entry["task_revision"],
        "claim_key": entry["claim_key"],
    }


def _suppression(entry: dict[str, Any], reason: str, *, related: str = "") -> dict[str, Any]:
    return {
        "fingerprint": entry["fingerprint"],
        "source_ref": entry["object"].source_ref,
        "recall_type": entry["object"].recall_type,
        "reason": reason,
        "related_fingerprint": related,
    }


def _token_jaccard(left: str, right: str) -> float:
    left_tokens = set(re.findall(r"[\w\u4e00-\u9fff]+", str(left or "").casefold()))
    right_tokens = set(re.findall(r"[\w\u4e00-\u9fff]+", str(right or "").casefold()))
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
