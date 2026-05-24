"""Low-clue recall routing helpers.

This module only builds bounded attribution metadata and guard text. It never
writes canonical memory, promotes candidates, approves crystallized records, or
executes actions.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .memory_sources import read_memory_source_feedback_records, read_memory_source_records
from .store import MemoryOSStore


SCHEMA_VERSION = "memory-os.low_clue_recall.v0"

DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": False,
    "candidate_limit": 4,
    "llm_judge": {
        "enabled": False,
        "mode": "none",
        "provider": "hermes_default",
        "model": None,
        "temperature": 0,
        "timeout_ms": 1500,
        "max_tokens": 160,
        "max_candidates": 4,
        "on_error": "deterministic_fallback",
    },
}

_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)\S+"),
    re.compile(r"(?i)(token\s*[:=]\s*)\S+"),
    re.compile(r"(?i)(secret\s*[:=]\s*)\S+"),
    re.compile(r"(?i)(password\s*[:=]\s*)\S+"),
    re.compile(r"(?i)(cookie\s*[:=]\s*)\S+"),
)
_ARTIFACT_PATTERNS = (
    re.compile(r"(?i)\bMEDIA:\S+"),
    re.compile(r"(?i)\b[A-Za-z]:\\[^\s]+"),
    re.compile(r"(?<!:)\/[A-Za-z0-9_.-]+(?:\/[A-Za-z0-9_.-]+){1,}\S*"),
)

_ASCII_ENTITY_PATTERN = re.compile(r"\b[A-Za-z][A-Za-z0-9_.+-]{1,40}\b")
_CHINESE_KEYWORDS = {
    "互联网",
    "采集",
    "数据",
    "系统",
    "设计",
    "方案",
    "分层",
    "视频",
    "剪辑",
    "素材",
    "门禁",
    "自动化",
    "智能体",
    "记忆",
    "候选",
    "长期",
    "comfyui",
    "n8n",
    "make",
}
_GENERIC_RECALL_TERMS = {
    "之前",
    "以前",
    "上次",
    "昨天",
    "刚才",
    "那个",
    "那套",
    "继续",
    "记得",
    "设计",
    "方案",
    "事情",
}
_GENERIC_TOPIC_TERMS = _GENERIC_RECALL_TERMS | {
    "系统",
    "项目",
    "user",
    "assistant",
}
_ENGLISH_TOPIC_STOPWORDS = {
    "about",
    "above",
    "across",
    "action",
    "active",
    "add",
    "after",
    "again",
    "all",
    "also",
    "ambiguous",
    "and",
    "an",
    "appears",
    "are",
    "asset",
    "ask",
    "asked",
    "attached",
    "available",
    "before",
    "being",
    "built",
    "but",
    "can",
    "candidate",
    "candidates",
    "context",
    "completed",
    "could",
    "current",
    "default",
    "each",
    "feel",
    "for",
    "from",
    "guard",
    "have",
    "hermesdata",
    "http",
    "https",
    "if",
    "into",
    "latest",
    "like",
    "media",
    "memory",
    "models",
    "mb",
    "gb",
    "more",
    "must",
    "need",
    "needs",
    "not",
    "now",
    "only",
    "output",
    "owner",
    "previous",
    "preview",
    "process",
    "recall",
    "recent",
    "report",
    "result",
    "review",
    "saving",
    "selected",
    "shows",
    "should",
    "skills",
    "source",
    "state",
    "status",
    "system",
    "that",
    "the",
    "this",
    "tool",
    "to",
    "turn",
    "user",
    "www",
    "with",
    "workspace",
}
_CORRECTION_TERMS = ("不对", "少了", "不是这个", "还有吗", "不准确", "不全")
_SOURCE_DIVERSITY_LIMIT = 2
_SOURCE_DIVERSITY_LIMIT_AFTER_CORRECTION = 1
_MIN_LOW_CLUE_SELECT_SCORE = 0.12
_MIN_SOURCE_DIVERSITY_FALLBACK_SCORE = 0.03
_TITLE_MAX_CHARS = 96
_SPEAKER_PREFIX_RE = re.compile(r"(?i)\b(user|assistant|system)\s*[:：]\s*")
_TITLE_LEAD_RE = re.compile(
    r"^(记得|对|好的|明白|应该是|更像|那更像|这更像|你说的是|我觉得|不是这个|不是|不|看了|刚才那个|那|行)[，,。:：\s]*"
)

LlmRunner = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


def normalize_low_clue_recall_config(config: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(config, dict):
        return _deepcopy(DEFAULT_CONFIG)
    merged = _deepcopy(DEFAULT_CONFIG)
    for key in ("enabled", "candidate_limit"):
        if key in config:
            merged[key] = config[key]
    judge = dict(merged["llm_judge"])
    incoming_judge = config.get("llm_judge")
    if isinstance(incoming_judge, dict):
        for key in judge:
            if key in incoming_judge:
                judge[key] = incoming_judge[key]
    judge["enabled"] = bool(judge.get("enabled"))
    judge["mode"] = str(judge.get("mode") or "none")
    judge["provider"] = str(judge.get("provider") or "hermes_default")
    try:
        judge["timeout_ms"] = max(int(judge.get("timeout_ms") or 1500), 100)
    except (TypeError, ValueError):
        judge["timeout_ms"] = 1500
    try:
        judge["max_candidates"] = max(int(judge.get("max_candidates") or 4), 1)
    except (TypeError, ValueError):
        judge["max_candidates"] = 4
    merged["llm_judge"] = judge
    try:
        merged["candidate_limit"] = max(int(merged.get("candidate_limit") or 4), 1)
    except (TypeError, ValueError):
        merged["candidate_limit"] = 4
    return merged


def build_low_clue_recall_report(
    query: str,
    *,
    store: MemoryOSStore,
    limit: int = 4,
    config: dict[str, Any] | None = None,
    llm_runner: LlmRunner | None = None,
) -> dict[str, Any]:
    normalized_config = normalize_low_clue_recall_config(config)
    candidate_limit = max(int(limit or normalized_config.get("candidate_limit") or 4), 1)
    raw_candidates = _collect_candidates(store)
    ranked_raw = _rank_candidates(query, raw_candidates, limit=len(raw_candidates) or candidate_limit)
    candidates, candidate_quality = _build_quality_candidates(
        query,
        ranked_raw,
        store=store,
        limit=candidate_limit,
    )
    decision, reason_codes = _decision(candidates)
    report = {
        "schema_version": SCHEMA_VERSION,
        "profile": store.roots.profile or "default",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "query_class": "ambiguous_recall",
        "decision": decision,
        "reason_codes": reason_codes,
        "candidate_quality": candidate_quality,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "llm_judge": _llm_judge_report(
            candidates=candidates,
            config=normalized_config,
            llm_runner=llm_runner,
        ),
        "boundaries": _boundary_false(),
    }
    return report


def build_low_clue_guard_lines(
    query: str,
    *,
    store: MemoryOSStore,
    config: dict[str, Any] | None = None,
    limit: int = 4,
) -> list[str]:
    # Live prefetch must stay cheap. Report-only LLM judging is available
    # through CLI/monitor probes, but the injected guard uses deterministic
    # ranking so a slow model adapter never blocks the user's turn.
    report = build_low_clue_recall_report(
        query,
        store=store,
        limit=limit,
        config=_without_live_judge(config),
    )
    lines = [
        "The user's recall request is underspecified.",
        "Do not answer as if one remembered item is certain.",
    ]
    candidates = report.get("candidates") if isinstance(report.get("candidates"), list) else []
    if candidates:
        if report.get("decision") == "direct_resume":
            lines.append(
                "A likely recall candidate exists; state the likely match briefly "
                "and ask the owner to correct it if it is wrong."
            )
        else:
            lines.append("Plausible recall candidates are available; ask the owner to choose one.")
        lines.append("Likely recall candidate:" if report.get("decision") == "direct_resume" else "Plausible recall candidates:")
        for index, candidate in enumerate(candidates[:limit], start=1):
            label = _clip(str(candidate.get("label") or ""), 140)
            source_class = str(candidate.get("source_class") or "unknown")
            lines.append(f"- {index}. {label} ({source_class})")
    else:
        lines.append("No safe recall candidate is available.")
        lines.append("Ask for a keyword, time, project, or source before guessing.")
    lines.append("If the user rejects two guesses, stop guessing and ask for an anchor.")
    return lines


def _without_live_judge(config: dict[str, Any] | None) -> dict[str, Any]:
    normalized = normalize_low_clue_recall_config(config)
    judge = dict(normalized.get("llm_judge") if isinstance(normalized.get("llm_judge"), dict) else {})
    judge["enabled"] = False
    judge["mode"] = "none"
    normalized["llm_judge"] = judge
    return normalized


def low_clue_judge_availability(config: dict[str, Any] | None) -> dict[str, Any]:
    """Return bounded, non-network availability metadata for the optional judge."""

    normalized_config = normalize_low_clue_recall_config(config)
    judge = normalized_config.get("llm_judge") if isinstance(normalized_config.get("llm_judge"), dict) else {}
    mode = str(judge.get("mode") or "none")
    enabled = bool(normalized_config.get("enabled")) and bool(judge.get("enabled")) and mode != "none"
    report: dict[str, Any] = {
        "schema_version": "memory-os.low_clue_judge_availability.v0",
        "enabled": enabled,
        "mode": mode,
        "provider": str(judge.get("provider") or "hermes_default"),
        "configured_model": judge.get("model"),
        "available": False,
        "degrades_to": "deterministic_fallback",
    }
    if not enabled:
        report.update({"status": "disabled", "code": "judge_disabled"})
        return report
    if mode != "report_only":
        report.update({"status": "skipped", "code": "bounded_vote_not_enabled_in_rh28"})
        return report
    resolved = _resolve_hermes_default_runtime(judge)
    if not resolved.get("ok"):
        report.update(
            {
                "status": "unavailable",
                "code": resolved.get("code") or "runtime_unavailable",
                "reason_codes": list(resolved.get("reason_codes") or []),
            }
        )
        return report
    api_mode = str(resolved.get("api_mode") or "")
    supported_modes = {"chat_completions", "codex_responses", "anthropic_messages"}
    report.update(
        {
            "api_mode": api_mode,
            "resolved_provider": resolved.get("provider"),
            "resolved_model": resolved.get("model"),
            "credential_present": bool(resolved.get("credential_present")),
            "status": "available" if api_mode in supported_modes else "unsupported",
            "code": "ok" if api_mode in supported_modes else "unsupported_api_mode",
            "available": api_mode in supported_modes,
        }
    )
    return report


def _collect_candidates(store: MemoryOSStore) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    candidates.extend(_deferred_candidates(store))
    candidates.extend(_working_candidates(store))
    candidates.extend(_event_candidates(store))
    candidates.extend(_memory_source_candidates(store))
    candidates.extend(_feedback_candidates(store))
    return _dedupe_candidates(candidates)


def _deferred_candidates(store: MemoryOSStore) -> list[dict[str, Any]]:
    path = store.roots.memory_os_root / "system" / "deferred_foreground_tasks.jsonl"
    if not path.exists():
        return []
    result: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines()[-20:]:
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        anchor = str(record.get("anchor") or "")
        label = _label_from_text(anchor)
        if not label:
            continue
        record_id = _safe_id(str(record.get("record_id") or "unknown"))
        result.append(
            _candidate(
                candidate_id=f"lc_deferred_{record_id}",
                label=label,
                source_class="deferred_foreground",
                source_id=f"foreground_task:{record_id}",
                last_seen_at=str(record.get("created_at") or ""),
                base_score=0.48,
                reason_codes=["deferred_task"],
            )
        )
    return result


def _working_candidates(store: MemoryOSStore) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for path in sorted(store.roots.working_root.glob("*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for item in document.get("items", []) if isinstance(document.get("items"), list) else []:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "")
            label = _label_from_text(text)
            if not label or _looks_too_mechanistic(label):
                continue
            source_id = _safe_id(str(item.get("source_event_id") or item.get("id") or "unknown"))
            result.append(
                _candidate(
                    candidate_id=f"lc_working_{source_id}",
                    label=label,
                    source_class="working",
                    source_id=f"working:{source_id}",
                    last_seen_at=str(item.get("updated_at") or document.get("updated_at") or ""),
                    base_score=0.35,
                    reason_codes=["working_item"],
                )
            )
    return result


def _event_candidates(store: MemoryOSStore) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for event in store.read_events()[-30:]:
        event_id = str(event.id or "")
        if event_id.startswith("evt_gov_") or event_id.startswith("evt_rh"):
            continue
        label = _label_from_text(event.summary)
        if not label or _looks_too_mechanistic(label):
            continue
        result.append(
            _candidate(
                candidate_id=f"lc_event_{_safe_id(event.id)}",
                label=label,
                source_class="event",
                source_id=f"event:{_safe_id(event.id)}",
                last_seen_at=str(event.ts or ""),
                base_score=0.25,
                reason_codes=["event_summary"],
            )
        )
    return result


def _memory_source_candidates(store: MemoryOSStore) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for record in read_memory_source_records(store.roots, limit=50):
        route = str(record.get("route") or "unknown")
        selected = record.get("selected") if isinstance(record.get("selected"), list) else []
        headings = [str(item.get("heading") or "") for item in selected if isinstance(item, dict)]
        label = _label_from_text(f"{route}: {', '.join(headings[:3])}")
        if not label:
            continue
        result.append(
            _candidate(
                candidate_id=f"lc_memory_source_{_safe_id(str(record.get('record_id') or 'unknown'))}",
                label=label,
                source_class="memory_sources",
                source_id="",
                last_seen_at=str(record.get("created_at") or ""),
                base_score=0.03,
                reason_codes=["memory_sources_route"],
            )
        )
    return result


def _feedback_candidates(store: MemoryOSStore) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for record in read_memory_source_feedback_records(store.roots, limit=50):
        rating = str(record.get("rating") or "")
        if rating not in {"clarification_selected", "missing_candidate", "needs_specific_recall"}:
            continue
        note = str(record.get("note") or rating)
        label = _label_from_text(note)
        if not label:
            continue
        result.append(
            _candidate(
                candidate_id=f"lc_feedback_{_safe_id(str(record.get('feedback_id') or 'unknown'))}",
                label=label,
                source_class="feedback",
                source_id="",
                last_seen_at=str(record.get("created_at") or ""),
                base_score=0.20,
                reason_codes=["owner_feedback"],
            )
        )
    return result


def _rank_candidates(query: str, candidates: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    query_terms = _terms(query) - _GENERIC_RECALL_TERMS
    ranked: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_terms = _terms(str(candidate.get("label") or ""))
        matches = query_terms & candidate_terms
        score = float(candidate.get("score") or 0.0)
        reasons = [str(item) for item in candidate.get("reason_codes", [])]
        if matches:
            score += min(0.50, 0.25 * len(matches))
            reasons.append("query_term_match")
        if query_terms and query_terms <= candidate_terms:
            score += 0.20
            reasons.append("all_query_terms_match")
        if not query_terms:
            reasons.append("low_clue_no_specific_terms")
        candidate = dict(candidate)
        candidate["score"] = round(min(score, 1.0), 3)
        candidate["reason_codes"] = _dedupe(reasons)
        ranked.append(candidate)
    ranked.sort(key=lambda item: (float(item.get("score") or 0.0), str(item.get("last_seen_at") or "")), reverse=True)
    return ranked[:limit]


def _build_quality_candidates(
    query: str,
    candidates: list[dict[str, Any]],
    *,
    store: MemoryOSStore,
    limit: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    correction_active = _recent_correction_signal(store)
    adjusted = [_apply_correction_penalty(candidate) for candidate in candidates] if correction_active else list(candidates)
    clusters = _cluster_candidates(adjusted)
    selected, diversity_applied = _select_diverse_clusters(
        clusters,
        query_terms=_terms(query) - _GENERIC_RECALL_TERMS,
        limit=limit,
        correction_active=correction_active,
    )
    quality = {
        "raw_candidate_count": len(candidates),
        "cluster_count": len(clusters),
        "source_distribution": _source_distribution(candidates),
        "merged_duplicates": max(len(candidates) - len(clusters), 0),
        "diversity_applied": diversity_applied,
        "feedback_penalty_applied": correction_active,
        "title_normalization_applied": any(
            "title_normalized" in candidate.get("reason_codes", []) for candidate in clusters
        ),
        "max_title_chars": max((len(str(candidate.get("label") or "")) for candidate in selected), default=0),
    }
    return selected, quality


def _apply_correction_penalty(candidate: dict[str, Any]) -> dict[str, Any]:
    adjusted = dict(candidate)
    adjusted["score"] = round(max(float(adjusted.get("score") or 0.0) - 0.05, 0.0), 3)
    adjusted["reason_codes"] = _dedupe([str(item) for item in adjusted.get("reason_codes", [])] + ["recent_correction_penalty"])
    return adjusted


def _cluster_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    clusters: list[dict[str, Any]] = []
    for candidate in candidates:
        terms = _topic_terms(str(candidate.get("label") or ""))
        matched = None
        for cluster in clusters:
            if _same_topic(terms, cluster["topic_terms"]):
                matched = cluster
                break
        if matched is None:
            clusters.append({"topic_terms": terms, "candidates": [candidate]})
        else:
            matched["topic_terms"] = matched["topic_terms"] | terms
            matched["candidates"].append(candidate)
    result = [_cluster_to_candidate(cluster["candidates"], cluster["topic_terms"]) for cluster in clusters]
    result.sort(key=lambda item: (float(item.get("score") or 0.0), str(item.get("last_seen_at") or "")), reverse=True)
    return result


def _cluster_to_candidate(candidates: list[dict[str, Any]], topic_terms: set[str]) -> dict[str, Any]:
    ranked = sorted(
        candidates,
        key=lambda item: (float(item.get("score") or 0.0), str(item.get("last_seen_at") or "")),
        reverse=True,
    )
    primary = dict(ranked[0])
    source_classes = _dedupe([str(item.get("source_class") or "unknown") for item in ranked])
    source_ids = _dedupe([str(item.get("source_id") or "") for item in ranked if str(item.get("source_id") or "")])
    merged_count = len(ranked)
    if merged_count > 1:
        primary["score"] = round(min(float(primary.get("score") or 0.0) + min(0.12, 0.04 * (merged_count - 1)), 1.0), 3)
        primary["reason_codes"] = _dedupe(
            [str(item) for item in primary.get("reason_codes", [])] + ["merged_duplicate_topic"]
        )
    title, normalized = _normalized_cluster_title(ranked, topic_terms)
    if title:
        primary["label"] = title
    if normalized:
        primary["reason_codes"] = _dedupe([str(item) for item in primary.get("reason_codes", [])] + ["title_normalized"])
    primary["source_classes"] = source_classes
    primary["source_ids"] = [source_id for source_id in source_ids if _safe_source_id(source_id)][:6]
    primary["merged_candidate_count"] = merged_count
    primary["cluster_terms"] = sorted(topic_terms)[:12]
    return primary


def _select_diverse_clusters(
    clusters: list[dict[str, Any]],
    *,
    query_terms: set[str],
    limit: int,
    correction_active: bool,
) -> tuple[list[dict[str, Any]], bool]:
    if limit <= 0:
        return [], False
    if query_terms:
        return clusters[:limit], False
    per_source_limit = _SOURCE_DIVERSITY_LIMIT_AFTER_CORRECTION if correction_active else _SOURCE_DIVERSITY_LIMIT
    selected: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    source_counts: dict[str, int] = {}
    for cluster in clusters:
        if float(cluster.get("score") or 0.0) < _MIN_LOW_CLUE_SELECT_SCORE:
            deferred.append(cluster)
            continue
        source_class = str(cluster.get("source_class") or "unknown")
        if source_counts.get(source_class, 0) >= per_source_limit:
            deferred.append(cluster)
            continue
        selected.append(cluster)
        source_counts[source_class] = source_counts.get(source_class, 0) + 1
        if len(selected) >= limit:
            break
    selected, forced_diversity = _ensure_source_diversity_slot(selected, clusters, limit=limit)
    if len(selected) < limit:
        for cluster in deferred:
            selected.append(cluster)
            if len(selected) >= limit:
                break
    selected = selected[:limit]
    baseline_ids = [str(item.get("candidate_id") or "") for item in clusters[:limit]]
    selected_ids = [str(item.get("candidate_id") or "") for item in selected]
    return selected, forced_diversity or selected_ids != baseline_ids


def _ensure_source_diversity_slot(
    selected: list[dict[str, Any]],
    clusters: list[dict[str, Any]],
    *,
    limit: int,
) -> tuple[list[dict[str, Any]], bool]:
    if limit <= 1 or not selected:
        return selected, False
    selected_sources = {str(item.get("source_class") or "unknown") for item in selected}
    available_sources = {str(item.get("source_class") or "unknown") for item in clusters}
    if len(selected_sources) > 1 or len(available_sources) <= 1:
        return selected, False
    dominant_source = next(iter(selected_sources))
    for cluster in clusters:
        source_class = str(cluster.get("source_class") or "unknown")
        if source_class == dominant_source:
            continue
        if float(cluster.get("score") or 0.0) < _MIN_SOURCE_DIVERSITY_FALLBACK_SCORE:
            continue
        candidate = dict(cluster)
        candidate["reason_codes"] = _dedupe([str(item) for item in candidate.get("reason_codes", [])] + ["source_diversity_slot"])
        if len(selected) < limit:
            return selected + [candidate], True
        return selected[:-1] + [candidate], True
    return selected, False


def _topic_terms(text: str) -> set[str]:
    terms = _terms(text)
    filtered = {
        term
        for term in terms
        if term not in _GENERIC_TOPIC_TERMS
        and term not in _ENGLISH_TOPIC_STOPWORDS
        and len(term) > 1
    }
    return filtered or {term for term in terms if term not in _GENERIC_RECALL_TERMS}


def _same_topic(left: set[str], right: set[str]) -> bool:
    if not left or not right:
        return False
    overlap = left & right
    if len(overlap) >= 2:
        return True
    union = left | right
    return bool(union) and (len(overlap) / len(union)) >= 0.45


def _recent_correction_signal(store: MemoryOSStore) -> bool:
    for event in store.read_events()[-8:]:
        summary = str(event.summary or "")
        user_text = summary.split("|", 1)[0]
        if any(term in user_text for term in _CORRECTION_TERMS):
            return True
    for record in read_memory_source_feedback_records(store.roots, limit=10):
        if str(record.get("rating") or "") in {"clarification_rejected", "missing_candidate", "needs_specific_recall"}:
            return True
    return False


def _source_distribution(candidates: list[dict[str, Any]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for candidate in candidates:
        source_class = str(candidate.get("source_class") or "unknown")
        result[source_class] = result.get(source_class, 0) + 1
    return result


def _normalized_cluster_title(candidates: list[dict[str, Any]], topic_terms: set[str]) -> tuple[str, bool]:
    labels = [str(candidate.get("label") or "") for candidate in candidates if str(candidate.get("label") or "")]
    if not labels:
        return "", False
    fallback = _topic_title_from_terms(labels, topic_terms)
    title = _best_title_segment(labels, topic_terms) or fallback
    if fallback and _title_should_use_terms(title):
        title = fallback
    title = _clip(_clean_title(title), _TITLE_MAX_CHARS)
    if not title:
        title = _clip(_clean_title(labels[0]), _TITLE_MAX_CHARS)
    normalized = any(title != label for label in labels) or any(
        marker in title for marker in ("User:", "Assistant:", "|")
    )
    return title, normalized


def _best_title_segment(labels: list[str], topic_terms: set[str]) -> str:
    choices: list[tuple[int, int, str]] = []
    for label in labels:
        for segment in _title_segments(label):
            for option in _title_options(segment):
                clean = _clean_title(option)
                if not clean or _looks_too_mechanistic(clean):
                    continue
                if len(clean) > _TITLE_MAX_CHARS:
                    continue
                score = _title_score(clean, topic_terms)
                if score <= 0:
                    continue
                choices.append((score, -len(clean), clean))
    if not choices:
        return ""
    choices.sort(reverse=True)
    return choices[0][2]


def _title_segments(label: str) -> list[str]:
    clean = _SPEAKER_PREFIX_RE.sub("", str(label or ""))
    clean = clean.replace("###", " ").replace("**", " ").replace("`", " ")
    raw_segments = re.split(r"\s*\|\s*|\n+|[。！？]\s*", clean)
    return [_clean_title(segment) for segment in raw_segments if _clean_title(segment)]


def _title_options(segment: str) -> list[str]:
    options = [segment]
    for separator in ("：", ":"):
        if separator in segment:
            left, right = segment.split(separator, 1)
            options.extend([left, right])
            break
    return options


def _clean_title(text: str) -> str:
    clean = _strip_artifact_paths(_SPEAKER_PREFIX_RE.sub("", str(text or "")))
    clean = _TITLE_LEAD_RE.sub("", clean.strip())
    clean = re.sub(r"^[#>*\-\s]+", "", clean)
    clean = re.sub(r"^\d+[.)、]\s*", "", clean)
    clean = re.sub(r"\s+", " ", clean)
    return clean.strip(" -:：，,。")


def _title_score(text: str, topic_terms: set[str]) -> int:
    terms = _topic_terms(text)
    overlap = terms & topic_terms
    return min(len(overlap), 3) * 3 + min(len(terms), 4)


def _title_should_use_terms(title: str) -> bool:
    clean = str(title or "").strip()
    if not clean:
        return False
    if len(clean) > 72:
        return True
    if clean[:1].islower() and len(clean.split()) >= 6:
        return True
    lower = clean.lower()
    return any(
        marker in lower
        for marker in (
            "media:",
            ".png",
            ".jpg",
            ".jpeg",
            ".json",
            ".py",
            ".safetensors",
            "文件名",
            "路径",
            "大小",
            "它能做什么",
        )
    )


def _topic_title_from_terms(labels: list[str], topic_terms: set[str]) -> str:
    if not topic_terms:
        return ""
    text = " ".join(labels)
    text_lower = text.lower()
    ordered = sorted(
        topic_terms,
        key=lambda term: (
            text_lower.find(term.lower()) if text_lower.find(term.lower()) >= 0 else 999999,
            term,
        ),
    )
    filtered = [
        _display_topic_term(term, text)
        for term in ordered
        if term
        and term.lower() not in _ENGLISH_TOPIC_STOPWORDS
        and "." not in term
        and not re.search(r"(?i)\.(png|jpg|jpeg|json|py|safetensors|txt|md)$", term)
    ]
    return " / ".join(filtered[:5])


def _display_topic_term(term: str, text: str) -> str:
    value = str(term or "")
    if not value or not re.match(r"^[a-z0-9_.+-]+$", value):
        return value
    match = re.search(rf"\b{re.escape(value)}\b", text, flags=re.IGNORECASE)
    return match.group(0) if match else value


def _decision(candidates: list[dict[str, Any]]) -> tuple[str, list[str]]:
    if not candidates:
        return "ask_keyword", ["no_candidates"]
    if len(candidates) == 1:
        score = float(candidates[0].get("score") or 0.0)
        if score >= 0.75:
            return "direct_resume", ["single_high_confidence_candidate"]
        return "confirm_one", ["single_candidate_requires_confirmation"]
    top = float(candidates[0].get("score") or 0.0)
    second = float(candidates[1].get("score") or 0.0)
    margin = top - second
    if top >= 0.75 and margin >= 0.20:
        return "direct_resume", ["clear_score_margin"]
    if top >= 0.55 and margin >= 0.15:
        return "confirm_one", ["moderate_score_margin"]
    return "ask_choice", ["multiple_plausible_candidates"]


def _llm_judge_report(
    *,
    candidates: list[dict[str, Any]],
    config: dict[str, Any],
    llm_runner: LlmRunner | None,
) -> dict[str, Any]:
    judge = config.get("llm_judge") if isinstance(config.get("llm_judge"), dict) else {}
    if not bool(judge.get("enabled")) or str(judge.get("mode") or "none") == "none":
        return {"status": "disabled", "mode": "none"}
    mode = str(judge.get("mode") or "")
    if mode != "report_only":
        return {"status": "skipped", "mode": mode, "code": "bounded_vote_not_enabled_in_rh28"}
    if not candidates:
        return {"status": "skipped", "mode": mode, "code": "no_candidates"}
    payload = {
        "schema_version": "memory-os.low_clue_recall_judge_input.v0",
        "query_class": "ambiguous_recall",
        "candidates": [
            {
                "candidate_id": str(candidate.get("candidate_id") or ""),
                "label": str(candidate.get("label") or ""),
                "source_class": str(candidate.get("source_class") or ""),
                "score": candidate.get("score"),
                "reason_codes": list(candidate.get("reason_codes") or []),
            }
            for candidate in candidates[: int(judge.get("max_candidates") or 4)]
        ],
    }
    runner = llm_runner or _run_hermes_default_judge
    try:
        result = runner(payload, judge)
    except Exception as exc:
        return {"status": "error", "mode": mode, "code": "judge_exception", "error": _clip(str(exc), 160)}
    if not isinstance(result, dict):
        return {"status": "error", "mode": mode, "code": "judge_invalid_result"}
    return {
        "status": str(result.get("status") or "ok"),
        "mode": mode,
        "provider": str(judge.get("provider") or "hermes_default"),
        "model": judge.get("model"),
        "selected_candidate_id": str(result.get("selected_candidate_id") or ""),
        "confidence": result.get("confidence"),
        "reason_codes": [str(item) for item in result.get("reason_codes", []) if str(item)],
    }


def _run_hermes_default_judge(payload: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    if str(config.get("provider") or "hermes_default") != "hermes_default":
        return {"status": "skipped", "reason_codes": ["unsupported_provider"]}
    prompt = (
        "You are a report-only relevance judge for an ambiguous recall request. "
        "Choose the best candidate id if one clearly matches, otherwise return an empty selected_candidate_id. "
        "Return only JSON with keys: status, selected_candidate_id, confidence, reason_codes.\n"
        f"{json.dumps(payload, ensure_ascii=False, sort_keys=True)}"
    )
    response_text = _call_hermes_runtime_model(prompt, config)
    if not response_text:
        return {"status": "skipped", "reason_codes": ["hermes_runtime_adapter_unavailable"]}
    parsed = _extract_json_object(response_text)
    if not isinstance(parsed, dict):
        return {"status": "error", "reason_codes": ["judge_non_json"]}
    return parsed


def _call_hermes_runtime_model(prompt: str, config: dict[str, Any]) -> str:
    try:
        resolved = _resolve_hermes_default_runtime(config)
        if not resolved.get("ok"):
            return ""
        runtime = dict(resolved.get("runtime") or {})
        api_mode = str(runtime.get("api_mode") or "")
        model = str(runtime.get("model") or resolved.get("model") or "")
        if not model:
            return ""
        timeout = max(float(config.get("timeout_ms") or 8000) / 1000.0, 0.1)
        max_tokens = int(config.get("max_tokens") or 160)
        if api_mode == "chat_completions":
            return _call_openai_chat(runtime, model=model, prompt=prompt, timeout=timeout, max_tokens=max_tokens)
        if api_mode == "codex_responses":
            return _call_openai_responses(runtime, model=model, prompt=prompt, timeout=timeout, max_tokens=max_tokens)
        if api_mode == "anthropic_messages":
            return _call_anthropic_messages(runtime, model=model, prompt=prompt, timeout=timeout, max_tokens=max_tokens)
    except Exception:
        return ""
    return ""


def _resolve_hermes_default_runtime(config: dict[str, Any]) -> dict[str, Any]:
    if str(config.get("provider") or "hermes_default") != "hermes_default":
        return {"ok": False, "code": "unsupported_provider", "reason_codes": ["unsupported_provider"]}
    try:
        from hermes_cli.config import load_config
        from hermes_cli.runtime_provider import resolve_runtime_provider
    except Exception:
        for candidate in (
            os.environ.get("HERMES_AGENT_ROOT"),
            "/usr/local/lib/hermes-agent",
        ):
            if candidate and Path(candidate).exists() and candidate not in sys.path:
                sys.path.insert(0, candidate)
        try:
            from hermes_cli.config import load_config
            from hermes_cli.runtime_provider import resolve_runtime_provider
        except Exception:
            return {
                "ok": False,
                "code": "hermes_runtime_adapter_unavailable",
                "reason_codes": ["hermes_runtime_import_failed"],
            }
    try:
        hermes_config = load_config()
        model_cfg = hermes_config.get("model") if isinstance(hermes_config, dict) else {}
        if isinstance(model_cfg, str):
            effective_model = model_cfg.strip()
            configured_provider = None
        elif isinstance(model_cfg, dict):
            effective_model = str(model_cfg.get("default") or model_cfg.get("model") or "").strip()
            configured_provider = str(model_cfg.get("provider") or "").strip() or None
        else:
            effective_model = ""
            configured_provider = None
        runtime = resolve_runtime_provider(requested=configured_provider, target_model=effective_model or None)
    except Exception:
        return {
            "ok": False,
            "code": "runtime_resolve_failed",
            "reason_codes": ["runtime_resolve_failed"],
        }
    return {
        "ok": True,
        "runtime": runtime,
        "api_mode": runtime.get("api_mode"),
        "provider": runtime.get("provider") or configured_provider,
        "model": runtime.get("model") or effective_model,
        "credential_present": bool(runtime.get("api_key")),
    }


def _call_openai_chat(
    runtime: dict[str, Any],
    *,
    model: str,
    prompt: str,
    timeout: float,
    max_tokens: int,
) -> str:
    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=str(runtime.get("api_key") or "dummy"),
            base_url=str(runtime.get("base_url") or "").rstrip("/") or None,
            timeout=timeout,
        )
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=max_tokens,
        )
        return str(response.choices[0].message.content or "")
    except Exception:
        return ""


def _call_openai_responses(
    runtime: dict[str, Any],
    *,
    model: str,
    prompt: str,
    timeout: float,
    max_tokens: int,
) -> str:
    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=str(runtime.get("api_key") or "dummy"),
            base_url=str(runtime.get("base_url") or "").rstrip("/") or None,
            timeout=timeout,
        )
        base_url = str(runtime.get("base_url") or "")
        is_codex_backend = str(runtime.get("provider") or "") == "openai-codex" or (
            "chatgpt.com" in base_url and "/backend-api/codex" in base_url
        )
        if is_codex_backend:
            parts: list[str] = []
            with client.responses.stream(
                model=model,
                instructions="You are a JSON-only report-only relevance judge.",
                input=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
                store=False,
                include=[],
                extra_headers={
                    "session_id": "memory-os-low-clue-judge",
                    "x-client-request-id": "memory-os-low-clue-judge",
                },
            ) as stream:
                for event in stream:
                    event_type = str(getattr(event, "type", "") or "")
                    if "output_text.delta" in event_type or event_type == "response.output_text.delta":
                        delta = getattr(event, "delta", "")
                        if delta:
                            parts.append(str(delta))
                final_response = stream.get_final_response()
            streamed = "".join(parts).strip()
            if streamed:
                return streamed
            return str(getattr(final_response, "output_text", "") or "")

        response = client.responses.create(
            model=model,
            input=[{"role": "user", "content": prompt}],
            max_output_tokens=max_tokens,
        )
        return str(getattr(response, "output_text", "") or "")
    except Exception:
        return ""


def _call_anthropic_messages(
    runtime: dict[str, Any],
    *,
    model: str,
    prompt: str,
    timeout: float,
    max_tokens: int,
) -> str:
    try:
        import anthropic

        client = anthropic.Anthropic(
            api_key=str(runtime.get("api_key") or ""),
            base_url=str(runtime.get("base_url") or "").rstrip("/") or None,
            timeout=timeout,
        )
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        parts = []
        for part in getattr(response, "content", []) or []:
            text = getattr(part, "text", "")
            if text:
                parts.append(str(text))
        return "\n".join(parts)
    except Exception:
        return ""


def _extract_json_object(text: str) -> dict[str, Any] | None:
    value = str(text or "")
    start = value.find("{")
    end = value.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        parsed = json.loads(value[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _candidate(
    *,
    candidate_id: str,
    label: str,
    source_class: str,
    source_id: str,
    last_seen_at: str,
    base_score: float,
    reason_codes: list[str],
) -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "label": _clip(_redact(label), 180),
        "source_class": source_class,
        "source_id": source_id if _safe_source_id(source_id) else "",
        "last_seen_at": last_seen_at,
        "score": round(base_score, 3),
        "reason_codes": _dedupe(reason_codes),
    }


def _label_from_text(text: str) -> str:
    clean = _clip(_redact(" ".join(str(text or "").split())), 180)
    clean = clean.replace("### Memory-OS Current Task Anchor", "").strip()
    clean = re.sub(r"^-+\s*", "", clean)
    clean = re.sub(r"(?i)\b(current task|task|session id|response rule):\s*", "", clean)
    return clean.strip(" -")


def _terms(text: str) -> set[str]:
    normalized = " ".join(str(text or "").split()).lower()
    terms = {item.lower() for item in _ASCII_ENTITY_PATTERN.findall(normalized)}
    terms.update(keyword.lower() for keyword in _CHINESE_KEYWORDS if keyword.lower() in normalized)
    return terms


def _looks_too_mechanistic(text: str) -> bool:
    lower = str(text or "").lower()
    return any(
        term in lower
        for term in (
            "hindsight",
            "provider-status",
            "memory_os_status",
            "internal reflection",
            "ops-gate",
            "opsr_",
            "proposal queue",
            "proposal_create",
            "prop_",
            "self-evolution dry-run",
            "cognitive-loop",
            "runtime_heartbeat",
            "system note",
            "previous turn",
            "tool result",
            "review the conversation above",
            "saving to memory",
            "consider saving to memory",
            "[important:",
            "background process",
            "command:",
        )
    )


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.:-]+", "_", str(value or ""))[:80] or "unknown"


def _safe_source_id(value: str) -> bool:
    if not value:
        return True
    return bool(
        re.match(r"^(event|working|candidate|crystallized|digest|reflection_card|governance_feedback|proposal|foreground_task):[A-Za-z0-9_.:-]+$", value)
    )


def _dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.get("label") or "").lower()
        if not key or key in seen:
            continue
        result.append(candidate)
        seen.add(key)
    return result


def _redact(value: str) -> str:
    text = str(value or "")
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(r"\1[redacted]", text)
    return text


def _strip_artifact_paths(value: str) -> str:
    text = str(value or "")
    for pattern in _ARTIFACT_PATTERNS:
        text = pattern.sub("", text)
    return text


def _clip(value: str, limit: int) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)].rstrip() + "..."


def _dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = str(item).strip()
        if value and value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _boundary_false() -> dict[str, bool]:
    return {
        "actual_send": False,
        "actual_execute": False,
        "actual_identity_write": False,
        "actual_relationship_write": False,
        "actual_crystallized_approval": False,
        "hindsight_exported": False,
    }


def _deepcopy(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value))
