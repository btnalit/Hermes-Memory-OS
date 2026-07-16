"""Read-time recall arbitration plan with shadow-first conflict handling."""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from typing import Any

from .recall_policy import (
    AUTHORITY_FRESHNESS_MATRIX,
    AUTHORITY_FRESHNESS_MATRIX_DIGEST,
    AUTHORITY_FRESHNESS_MATRIX_VERSION,
    OBSERVATION_WINDOW_ID,
)
from .recall_types import RecallObject, RecallType

SCHEMA_VERSION = "memory-os.recall_plan.v0"
_AUTHORITY_RANK = AUTHORITY_FRESHNESS_MATRIX["authority_rank"]
_DEFAULT_AUTHORITY = AUTHORITY_FRESHNESS_MATRIX["default_authority_by_recall_type"]
_EXPLICIT_RECALL_PATTERN = re.compile(
    r"(还记得|記得|记不记得|记得吗|继续上次|繼續上次|do you remember|remember|continue (?:the )?last)",
    re.I,
)


def build_recall_plan(
    objects: list[RecallObject],
    *,
    mode: str = "shadow",
    budget_chars: int = 1800,
    current_query: str = "",
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
        cooldown_escape_reason = _cooldown_escape_reason(obj, current_query=current_query)
        entry = {
            "index": index,
            "object": obj,
            "fingerprint": fingerprint,
            "authority_class": authority,
            "authority_rank": _AUTHORITY_RANK.get(authority, 0),
            "freshness": max(0.0, min(1.0, float(obj.freshness))),
            "task_revision": task_revision,
            "claim_key": claim_key,
            "cooldown_escape_reason": cooldown_escape_reason,
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
        if (
            fingerprint in ledger
            and ledger[fingerprint] == current_task_revision
            and not cooldown_escape_reason
        ):
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
        "authority_freshness_matrix_version": AUTHORITY_FRESHNESS_MATRIX_VERSION,
        "authority_freshness_matrix_digest": AUTHORITY_FRESHNESS_MATRIX_DIGEST,
        "observation_window_id": OBSERVATION_WINDOW_ID,
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


def _cooldown_escape_reason(obj: RecallObject, *, current_query: str) -> str:
    """Return an auditable object-level cooldown escape reason, or empty."""

    query = str(current_query or "").strip()
    metadata = obj.metadata if isinstance(obj.metadata, dict) else {}
    entity_refs = _object_entity_refs(obj)
    entity_match = query and any(_query_mentions_entity(query, ref) for ref in entity_refs)
    if (
        query
        and _EXPLICIT_RECALL_PATTERN.search(query)
        and _query_references_object(
            query,
            obj,
            entity_match=bool(entity_match),
            has_entity_refs=bool(entity_refs),
        )
    ):
        return "explicit_recall"

    critical_class = str(metadata.get("critical_recall_class") or "").strip().casefold()
    trusted_task_boundary = (
        obj.recall_type == RecallType.TEMPORAL.value
        and obj.authority_class == "direct_current_task"
        and critical_class == "task_boundary"
    )
    trusted_owner_record = (
        obj.recall_type == RecallType.CRYSTALLIZED.value
        and obj.authority_class in {"owner_confirmed", "approved_canonical"}
        and metadata.get("owner_approved_permanent") is True
    )
    if trusted_task_boundary:
        return "task_boundary"
    if trusted_owner_record and (metadata.get("owner_pinned") is True or critical_class == "owner_pin"):
        return "owner_pin"
    if trusted_owner_record and (metadata.get("safety_rule") is True or critical_class == "safety_rule"):
        return "safety_rule"

    if entity_match:
        return "current_query_entity"
    return ""


def _object_entity_refs(obj: RecallObject) -> tuple[str, ...]:
    metadata = obj.metadata if isinstance(obj.metadata, dict) else {}
    values: list[Any] = []
    for key in ("entity_refs", "entities"):
        value = metadata.get(key)
        if isinstance(value, (list, tuple, set)):
            values.extend(value)
        elif isinstance(value, str):
            values.append(value)
    for key in ("shared_entity", "entity_ref", "entity_text"):
        value = metadata.get(key)
        if isinstance(value, str):
            values.append(value)
    refs = {
        " ".join(str(value or "").strip().split())
        for value in values
        if len(" ".join(str(value or "").strip().split())) >= 2
    }
    return tuple(sorted(refs, key=lambda value: (value.casefold(), value)))


def _query_references_object(
    query: str,
    obj: RecallObject,
    *,
    entity_match: bool,
    has_entity_refs: bool,
) -> bool:
    # Structured entity identity is authoritative and fail-closed: once an
    # object declares refs, lexical overlap cannot override a ref mismatch.
    if has_entity_refs:
        return entity_match
    if entity_match:
        return True
    claim_key = str(obj.claim_key or "").strip()
    raw_query = _EXPLICIT_RECALL_PATTERN.sub(" ", str(query or ""))
    cleaned_query = raw_query.casefold()
    content = f"{str(obj.content or '')} {claim_key}".casefold()
    stopwords = {
        "a", "about", "again", "an", "and", "are", "at", "could", "did", "do",
        "does", "for", "from", "in", "is", "it", "last", "me", "my", "of", "on",
        "or", "our", "please", "previous", "remember", "that", "the", "this", "to",
        "us", "was", "we", "were", "what", "when", "where", "with", "would", "you",
    }
    query_ascii: set[str] = set()
    for raw_token in re.findall(r"[A-Za-z0-9][A-Za-z0-9_.+#/-]*", raw_query):
        token = raw_token.casefold()
        short_upper_identifier = raw_token.isupper() and len(raw_token) <= 3
        if token not in stopwords or short_upper_identifier:
            query_ascii.add(token)
    content_ascii = set(re.findall(r"[a-z0-9][a-z0-9_.+#/-]*", content))
    ascii_matches = not query_ascii or query_ascii <= content_ascii
    cjk_query = cleaned_query
    for filler in ("帮我", "我们", "咱们", "上次", "之前", "以前", "那个", "这个", "一下"):
        cjk_query = cjk_query.replace(filler, "")
    cjk_query = re.sub(r"[的了吗呢啊呀么吧]", "", cjk_query)
    query_cjk = set(_cjk_bigrams(cjk_query))
    content_cjk = set(_cjk_bigrams(content))
    cjk_matches = not query_cjk or query_cjk <= content_cjk
    return bool(query_ascii or query_cjk) and ascii_matches and cjk_matches


def _cjk_bigrams(text: str) -> list[str]:
    bigrams: list[str] = []
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        bigrams.extend(run[index:index + 2] for index in range(max(0, len(run) - 1)))
    return bigrams


def _query_mentions_entity(query: str, entity_ref: str) -> bool:
    normalized_query = " ".join(str(query or "").casefold().split())
    normalized_ref = " ".join(str(entity_ref or "").casefold().split())
    if len(normalized_ref) < 2:
        return False
    escaped = re.escape(normalized_ref).replace(r"\ ", r"\s+")
    if re.search(r"[\u3400-\u9fff]", normalized_ref):
        pattern = rf"(?<![\u3400-\u9fff]){escaped}(?![\u3400-\u9fff])"
    else:
        entity_char = r"a-z0-9_.+#/@:-"
        pattern = rf"(?<![{entity_char}]){escaped}(?![{entity_char}])"
    return re.search(pattern, normalized_query) is not None


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
        "authority_rank": entry["authority_rank"],
        "freshness": entry["freshness"],
        "task_revision": entry["task_revision"],
        "claim_key": entry["claim_key"],
        "cooldown_escape_reason": entry.get("cooldown_escape_reason", ""),
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
