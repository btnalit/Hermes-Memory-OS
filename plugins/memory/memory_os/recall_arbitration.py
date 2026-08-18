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
    resolve_authority_rank,
)
from .recall_types import RecallObject, RecallType

SCHEMA_VERSION = "memory-os.recall_plan.v0"
_AUTHORITY_RANK = AUTHORITY_FRESHNESS_MATRIX["authority_rank"]
_DEFAULT_AUTHORITY = AUTHORITY_FRESHNESS_MATRIX["default_authority_by_recall_type"]
_EXPLICIT_RECALL_PATTERN = re.compile(
    r"(还记得|記得|记不记得|记得吗|继续上次|繼續上次|do you remember|remember|continue (?:the )?last)",
    re.I,
)

# Dedup semantics are READ FROM the matrix, never restated here: the matrix
# digest is the observation window's identity, so a threshold or tokenizer that
# lived only in this module could change detection behaviour without ending the
# window it invalidates.  A matrix key that the code does not actually read
# would be the mirror defect (see `relevance_score` in `ranking_precedence`),
# so `test_near_duplicate_config_is_sourced_from_the_matrix` asserts these
# module constants and the runtime default equal the matrix values.
# CJK ideographs + kana + hangul: the scripts whose runs `\w` swallows whole.
# Deliberately NOT shared with `_cjk_bigrams` below, which serves the cooldown
# escape path and is limited to ideographs; widening that helper would change
# query-match behaviour in an unrelated lane.
_SIMILARITY_CJK_RUN = re.compile(r"[㐀-鿿぀-ヿ가-힯]+")

_NEAR_DUPLICATE_CONFIG = AUTHORITY_FRESHNESS_MATRIX["near_duplicate"]
NEAR_DUPLICATE_TOKENIZER = str(_NEAR_DUPLICATE_CONFIG["tokenizer"])
NEAR_DUPLICATE_THRESHOLD = float(_NEAR_DUPLICATE_CONFIG["threshold"])

# FIX 5(b): L4 "ambiguous but not suppressed" band. Pairs at or above this
# jaccard similarity but below `near_duplicate_threshold` are too similar to
# ignore but not similar enough to collapse deterministically (no LLM on the
# hot path per the dedup-ladder design doc). Both entries survive and are
# cross-linked via `ambiguity_related` instead of one suppressing the other.
_AMBIGUITY_JACCARD_FLOOR = float(_NEAR_DUPLICATE_CONFIG["ambiguity_floor"])


def build_recall_plan(
    objects: list[RecallObject],
    *,
    mode: str = "shadow",
    budget_chars: int = 1800,
    current_query: str = "",
    current_task_revision: str = "",
    session_ledger: dict[str, Any] | None = None,
    near_duplicate_threshold: float = NEAR_DUPLICATE_THRESHOLD,
    freshness_guard_mode: str = "shadow",
    conflict_resolution_mode: str = "shadow",
) -> dict[str, Any]:
    """Build a bounded arbitration projection without mutating durable state."""

    ledger = session_ledger or {}
    candidates: list[dict[str, Any]] = []
    suppressed: list[dict[str, Any]] = []
    shadow_findings: list[dict[str, Any]] = []
    unknown_authority_classes: set[str] = set()
    for index, obj in enumerate(objects):
        fingerprint = content_fingerprint(obj.content)
        authority = obj.authority_class or str(obj.metadata.get("authority_class") or "") or _DEFAULT_AUTHORITY.get(obj.recall_type, "")
        task_revision = obj.task_revision or str(obj.metadata.get("task_revision") or "")
        claim_key = obj.claim_key or str(obj.metadata.get("claim_key") or "")
        metadata = obj.metadata if isinstance(obj.metadata, dict) else {}
        source_rev = str(metadata.get("source_updated_at") or "")
        cooldown_escape_reason = _cooldown_escape_reason(obj, current_query=current_query)
        # Defect-2 fix: `authority` may carry either this module's native
        # arbitration vocabulary OR a raw substrates-layer vocabulary
        # string (see recall_policy.resolve_authority_rank). A plain
        # `_AUTHORITY_RANK.get(authority, 0)` would silently rank an
        # unrecognized-but-genuinely-authoritative string (e.g.
        # "local_canonical") at 0 -- the same tier as an intentionally
        # empty value, and BELOW Hindsight's own "external_unverified"
        # (rank 1). `resolve_authority_rank` maps known substrates values
        # explicitly and flags anything recognized by neither vocabulary.
        authority_rank, authority_recognized = resolve_authority_rank(authority)
        if not authority_recognized:
            unknown_authority_classes.add(authority)
        entry = {
            "index": index,
            "object": obj,
            "fingerprint": fingerprint,
            "authority_class": authority,
            "authority_rank": authority_rank,
            "freshness": max(0.0, min(1.0, float(obj.freshness))),
            "task_revision": task_revision,
            "source_rev": source_rev,
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
            _session_ledger_hit(ledger.get(fingerprint), task_revision=current_task_revision, source_rev=source_rev)
            and not cooldown_escape_reason
        ):
            suppressed.append(_suppression(entry, "session_duplicate"))
            continue
        candidates.append(entry)

    # --- FIX 5(a): L0 exact source_ref dedup, ACROSS recall_types. Runs
    # before the existing L1 (exact content digest) and L3 (near-duplicate
    # jaccard) logic below, per the dedup-ladder design (L0 -> L1 -> ... ->
    # L4). Two entries that carry the identical non-empty source_ref are
    # the same underlying source object surfaced by more than one retriever
    # lane; keep the best-ranked one and drop the rest.
    source_ref_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in candidates:
        source_ref = str(entry["object"].source_ref or "").strip()
        if source_ref:
            source_ref_groups[source_ref].append(entry)
    # `exact_duplicate_count` is the shadow-observability bucket for ALL
    # deterministic (non-fuzzy) dedup -- both L0 (source_ref identity) and
    # the pre-existing L1 (content-digest identity) below fold into it.
    # recall_policy.append_recall_observation only exposes two buckets
    # (exact vs near); L0 is exact by construction (same literal source, not
    # a fuzzy match), so folding it into `exact_duplicate_count` keeps that
    # counter meaning "deterministic duplicates removed" instead of
    # under-reporting once L0 starts catching cases L1 used to miss.
    exact_duplicate_count = 0
    l0_suppressed_ids: set[int] = set()
    for group in source_ref_groups.values():
        if len(group) < 2:
            continue
        ranked = sorted(group, key=_rank_key)
        for duplicate in ranked[1:]:
            exact_duplicate_count += 1
            l0_suppressed_ids.add(id(duplicate))
            suppressed.append(_suppression(duplicate, "exact_source_duplicate"))
    l0_survivors = [entry for entry in candidates if id(entry) not in l0_suppressed_ids]

    exact_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in l0_survivors:
        exact_groups[entry["fingerprint"]].append(entry)
    deduped: list[dict[str, Any]] = []
    for group in exact_groups.values():
        ranked = sorted(group, key=_rank_key)
        deduped.append(ranked[0])
        for duplicate in ranked[1:]:
            exact_duplicate_count += 1
            suppressed.append(_suppression(duplicate, "exact_duplicate"))

    near_deduped: list[dict[str, Any]] = []
    near_duplicate_count = 0
    ambiguous_pair_count = 0
    for entry in sorted(deduped, key=_rank_key):
        duplicate_of = None
        ambiguous_with: list[dict[str, Any]] = []
        for retained in near_deduped:
            similarity = _token_jaccard(entry["object"].content, retained["object"].content)
            if similarity >= near_duplicate_threshold:
                duplicate_of = retained
                break
            if similarity >= _AMBIGUITY_JACCARD_FLOOR:
                ambiguous_with.append(retained)
        if duplicate_of is not None:
            near_duplicate_count += 1
            suppressed.append(_suppression(entry, "near_duplicate", related=duplicate_of["fingerprint"]))
            continue
        # FIX 5(b): L4 -- similarity landed in [floor, threshold) against one
        # or more retained entries. Neither side is suppressed; both are
        # cross-linked so a consumer can see the ambiguity and decide.
        for retained in ambiguous_with:
            if _link_ambiguous_pair(entry, retained):
                ambiguous_pair_count += 1
        near_deduped.append(entry)

    # Conflict resolution is gated entirely on `claim_key`, whose ONLY producer
    # is crystallized frontmatter (retrievers/crystallized.py). On production
    # no crystallized record carries one, so `conflict_count` has been 0 for
    # every sample this lane ever took -- and a permanent zero is ambiguous:
    # it reads identically whether no input was eligible or the grouping is
    # broken. `claim_keyed_input_count` below is what separates the two, per
    # the rule that a lane producing nothing must say why without anyone
    # re-running it or reading this source.
    conflict_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    claim_keyed_input_count = 0
    for entry in near_deduped:
        if entry["claim_key"]:
            claim_keyed_input_count += 1
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
        "ambiguous_pair_count": ambiguous_pair_count,
        "conflict_count": len(conflicts),
        # Denominator for conflict_count: zero here means the conflict lane had
        # nothing to work with, not that it failed to find conflicts.
        "claim_keyed_input_count": claim_keyed_input_count,
        "unknown_authority_classes": sorted(unknown_authority_classes),
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
    session_ledger: dict[str, Any],
    results: dict[str, list[RecallObject]],
    *,
    task_revision: str,
) -> None:
    """Record only actually formatted objects in the provider-local ledger.

    FIX 4: the ledger value is now ``{"task_revision": str, "source_rev":
    str}`` instead of a bare ``task_revision`` string. ``source_rev`` is the
    object's own ``metadata["source_updated_at"]`` (empty string when
    absent). Storing both means a source object that gets updated mid-task
    (same task_revision, new source_updated_at) is no longer wrongly
    suppressed as a session duplicate -- see `_session_ledger_hit`. This
    always writes the new shape, so a legacy plain-string entry for the
    same fingerprint is upgraded the moment the object is re-formatted.
    """
    for objects in results.values():
        for obj in objects:
            metadata = obj.metadata if isinstance(obj.metadata, dict) else {}
            session_ledger[content_fingerprint(obj.content)] = {
                "task_revision": task_revision,
                "source_rev": str(metadata.get("source_updated_at") or ""),
            }


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
        "source_rev": entry.get("source_rev", ""),
        "claim_key": entry["claim_key"],
        "cooldown_escape_reason": entry.get("cooldown_escape_reason", ""),
        "ambiguity_related": list(entry.get("ambiguity_related") or []),
    }


def _session_ledger_hit(entry_value: Any, *, task_revision: str, source_rev: str) -> bool:
    """FIX 4: return True only when the ledger entry is in the new
    ``{"task_revision": str, "source_rev": str}`` shape AND both fields
    match the object's current values -- i.e. suppress only when BOTH the
    task and the source object are unchanged since the last injection.

    Backward-compat tradeoff: a legacy plain-string ledger entry (the
    pre-fix shape, which stored only ``task_revision`` and had no way to
    express ``source_rev``) is always treated as changed, so it never
    suppresses. This costs one extra "already seen" re-injection per
    legacy entry during the transition, but it is fail-safe: we would
    rather show an object once more than silently suppress one that was
    actually updated mid-task just because an old-format ledger couldn't
    record that. `record_session_injection` always writes the new shape,
    so the moment an object is (re)formatted its ledger entry is upgraded
    and the grace period is one-shot.
    """
    if not isinstance(entry_value, dict):
        return False
    return (
        str(entry_value.get("task_revision") or "") == task_revision
        and str(entry_value.get("source_rev") or "") == source_rev
    )


def _link_ambiguous_pair(entry: dict[str, Any], retained: dict[str, Any]) -> bool:
    """FIX 5(b): cross-link two L4-ambiguous entries by fingerprint.

    Neither entry is suppressed; both keep a list of the other ambiguous
    fingerprint(s) so a consumer can see the relationship. Returns True
    only when this is a newly recorded pair (for accurate counting)."""
    entry_related: list[str] = entry.setdefault("ambiguity_related", [])
    retained_related: list[str] = retained.setdefault("ambiguity_related", [])
    is_new = retained["fingerprint"] not in entry_related
    if is_new:
        entry_related.append(retained["fingerprint"])
    if entry["fingerprint"] not in retained_related:
        retained_related.append(entry["fingerprint"])
    return is_new


def _suppression(entry: dict[str, Any], reason: str, *, related: str = "") -> dict[str, Any]:
    return {
        "fingerprint": entry["fingerprint"],
        "source_ref": entry["object"].source_ref,
        "recall_type": entry["object"].recall_type,
        "reason": reason,
        "related_fingerprint": related,
    }


def _similarity_tokens(text: str) -> set[str]:
    """Two-class token set: ASCII/word runs plus CJK character bigrams.

    The previous single-class regex (``[\\w\\u4e00-\\u9fff]+``) never broke
    between CJK characters -- ``\\w`` already matches them -- so an entire
    Chinese sentence became ONE token.  Two paraphrases then shared no token
    at all and scored 0.0, which made both L3 (>= threshold, suppress) and L4
    (ambiguity band) structurally unreachable for Chinese, Japanese and Korean
    content: measured on production, near-duplicate fired 5 times in 7134
    recall inputs while deterministic dedup fired 257.

    Bigrams for the CJK class follow the two implementations in this codebase
    that already got it right -- ``prefetch`` query tokens and ``_cjk_bigrams``
    below -- and keep ASCII behaviour bit-identical, since the ASCII class is
    unchanged and the CJK class contributes nothing to a pure-ASCII string.

    Scope note: what this restores is detection of differences *inside* a CJK
    run (a trailing particle scores ~0.95).  Differences at a run boundary --
    punctuation, spaces -- were already detectable, because the old regex
    treated those as separators too; the first counterfactual fixture written
    for this fix used exactly such a pair and therefore passed with the defect
    still in place.  Genuine paraphrases score ~0.22-0.54 and remain below
    both bands by design; semantic-equivalence dedup is a separate decision,
    not a side effect of this fix.
    """
    normalized = str(text or "").casefold()
    tokens: set[str] = set()
    # Non-CJK segments keep the original ``\w+`` rule verbatim, so accented
    # Latin, Cyrillic and every other word character tokenize exactly as they
    # did before; only the CJK class changes.
    for segment in re.split(_SIMILARITY_CJK_RUN, normalized):
        tokens.update(re.findall(r"\w+", segment))
    for run in re.findall(_SIMILARITY_CJK_RUN, normalized):
        if len(run) == 1:
            tokens.add(run)
            continue
        tokens.update(run[index:index + 2] for index in range(len(run) - 1))
    return tokens


def _token_jaccard(left: str, right: str) -> float:
    left_tokens = _similarity_tokens(left)
    right_tokens = _similarity_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
