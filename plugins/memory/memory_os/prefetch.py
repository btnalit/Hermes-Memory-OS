"""Bounded context assembly for Memory-OS."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from .crystallized import read_candidate_queue
from .store import MemoryOSStore


HEADER = "## Memory-OS Context"
DIAGNOSTIC_SUPPRESSION_NOTICE = (
    "Historical recall suppressed for diagnostic query. Use Current Memory-OS Runtime Facts only."
)
CONTINUITY_SELECTOR_SCHEMA_VERSION = "memory-os.continuity_selector.v0"

_BRIDGE_SEED_SLOTS = {
    "foreground": 2,
    "cron": 1,
    "mailbox": 1,
    "room_family": 1,
    "state_source": 1,
    "governance": 1,
}

_MAX_CONTINUITY_RECORDS = 8

_DIAGNOSTIC_QUERY_PATTERNS = (
    re.compile(r"(当前|现在|目前|当前的).{0,12}记忆.{0,8}(架构|系统|后端|provider|提供商|状态)"),
    re.compile(r"当前.*(memory_os|memory-os|记忆|memory).*(状态|架构|系统|provider|backend)", re.I),
    re.compile(r"(memory[-_ ]?os|hindsight).*(canonical|store|provider|backend|正常|还在用)", re.I),
    re.compile(r"(memory_os|memory-os).*(状态|正常|provider|backend)", re.I),
    re.compile(r"(memory architecture|memory backend|memory provider|current memory state)", re.I),
    re.compile(r"(which|what).*(memory|storage).*(provider|backend|system)", re.I),
    re.compile(r"用的什么.*记忆"),
    re.compile(r"记忆.*provider", re.I),
    re.compile(r"记忆系统.*(怎么|如何).*(工作|运行)"),
)

_ASCII_ENTITY_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_-]{1,}|[A-Z0-9_-]{2,}")
_FAST_PATH_CHINESE_KEYWORDS = (
    "报错",
    "错误",
    "失败",
    "丢包",
    "队列",
    "网关",
    "重启",
    "提案",
    "治理",
    "证据",
    "结晶",
    "候选",
    "会话",
    "定时",
    "状态",
    "索引",
    "延迟",
    "记忆",
)
_ROUTE_STOP_ENTITIES = {
    "api_key",
    "key",
    "token",
    "secret",
    "password",
    "redacted",
}

_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)\S+"),
    re.compile(r"(?i)(token\s*[:=]\s*)\S+"),
    re.compile(r"(?i)(secret\s*[:=]\s*)\S+"),
)


def build_prefetch(
    query: str,
    *,
    budget_chars: int,
    store: MemoryOSStore,
    index: object | None = None,
    diagnostic_grounding_enabled: bool = True,
    runtime_facts: dict[str, Any] | None = None,
) -> str:
    if _should_ground_diagnostic_query(
        query,
        diagnostic_grounding_enabled=diagnostic_grounding_enabled,
    ):
        return _fit_budget(_format_diagnostic(runtime_facts or {}), budget_chars)
    sections: list[tuple[str, list[str]]] = []
    _append_section(sections, "Identity Memory", _identity_lines(store))
    _append_section(sections, "Continuity Bridge", _continuity_bridge_lines(store))
    _append_section(sections, "Working Memory", _working_lines(store))
    _append_section(sections, "Relationship Memory", _relationship_lines(store))
    _append_section(sections, "Crystallized Review Candidates", _candidate_lines(store))
    _append_section(sections, "Crystallized Memory", _crystallized_lines(store))
    _append_section(sections, "Indexed Recall", _indexed_lines(query, index))
    _append_section(sections, "Recent Event Summaries", _event_lines(store))
    if not sections:
        return ""
    return _fit_budget(_format(sections), budget_chars)


def plan_query_route(
    query: str,
    *,
    diagnostic_grounding_enabled: bool = True,
) -> dict[str, Any]:
    text = " ".join(str(query or "").split())
    if not text:
        return {"route": "slow_path", "search_query": "", "display_query": "", "keywords": []}
    if _should_ground_diagnostic_query(text, diagnostic_grounding_enabled=diagnostic_grounding_enabled):
        return {"route": "diagnostic", "search_query": "", "display_query": "", "keywords": []}

    redacted = _redact(text)
    entities = [
        entity
        for entity in _ASCII_ENTITY_PATTERN.findall(redacted)
        if entity.lower() not in _ROUTE_STOP_ENTITIES
    ]
    chinese_keywords = [keyword for keyword in _FAST_PATH_CHINESE_KEYWORDS if keyword in redacted]
    keywords = _dedupe(entities or chinese_keywords)
    if keywords:
        search_query = " ".join(keywords[:6])
        return {
            "route": "fast_path",
            "search_query": search_query,
            "display_query": search_query,
            "keywords": keywords[:6],
        }
    slow_query = _clip(redacted, 120)
    return {
        "route": "slow_path",
        "search_query": slow_query,
        "display_query": slow_query,
        "keywords": [],
    }


def _append_section(sections: list[tuple[str, list[str]]], title: str, lines: list[str]) -> None:
    if lines:
        sections.append((title, lines))


def _identity_lines(store: MemoryOSStore) -> list[str]:
    path = store.roots.identity_manifest_path
    if not path.exists():
        return []
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    sources = manifest.get("identity_sources", [])
    kinds = [str(source.get("kind", "")) for source in sources if isinstance(source, dict) and source.get("kind")]
    if not kinds:
        return []
    return [f"- manifest sources: {', '.join(sorted(kinds))}"]


def _working_lines(store: MemoryOSStore) -> list[str]:
    lines: list[str] = []
    for path in sorted(store.roots.working_root.glob("*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for item in document.get("items", []):
            if not isinstance(item, dict):
                continue
            text = _redact(_clip(str(item.get("text", "")), 220))
            if text:
                lines.append(f"- {path.stem}/{item.get('kind', 'item')}: {text}")
    return lines


def _relationship_lines(store: MemoryOSStore) -> list[str]:
    lines: list[str] = []
    for path in sorted(store.roots.relationships_root.glob("*.md")):
        text = _file_snippet(path)
        if text:
            lines.append(f"- {path.name}: {text}")
    return lines


def _crystallized_lines(store: MemoryOSStore) -> list[str]:
    lines: list[str] = []
    for path in sorted(store.roots.crystallized_root.glob("*.md")):
        text = _crystallized_snippet(path)
        if text:
            lines.append(f"- {path.name}: {text}")
    return lines


def _candidate_lines(store: MemoryOSStore) -> list[str]:
    lines: list[str] = []
    for candidate in read_candidate_queue(store.roots)[:5]:
        text = _redact(_clip(candidate.body, 180))
        if text:
            lines.append(
                "- candidate only / review candidate; not approved crystallized memory: "
                f"{candidate.candidate_id} {candidate.kind}: {text}"
            )
    return lines


def _event_lines(store: MemoryOSStore) -> list[str]:
    selected, _dropped = _select_continuity_events(store)
    return [
        f"- {_event_source_class(event)}/{event.kind}: {_redact(_clip(event.summary, 220))}"
        for event in selected
    ]


def _continuity_bridge_lines(store: MemoryOSStore) -> list[str]:
    selected, _dropped = _select_continuity_events(store)
    return [
        f"- {_event_source_class(event)}/{event.kind}: {_redact(_clip(event.summary, 220))}"
        for event in selected
        if _event_source_class(event) in {"cron", "mailbox", "room_family", "state_source", "governance"}
    ]


def continuity_selector_report(store: MemoryOSStore) -> dict[str, Any]:
    selected, dropped = _select_continuity_events(store)
    return {
        "schema_version": CONTINUITY_SELECTOR_SCHEMA_VERSION,
        "selected_total": len(selected),
        "dropped_total": len(dropped),
        "selected_by_source_class": dict(Counter(_event_source_class(event) for event in selected)),
        "dropped_by_source_class": dict(Counter(_event_source_class(event) for event in dropped)),
        "seed_slots": dict(_BRIDGE_SEED_SLOTS),
        "max_records": _MAX_CONTINUITY_RECORDS,
    }


def _select_continuity_events(store: MemoryOSStore) -> tuple[list[Any], list[Any]]:
    events = sorted(store.read_events(), key=lambda event: (event.ts, event.id), reverse=True)
    selected: list[Any] = []
    selected_ids: set[str] = set()
    buckets: dict[str, list[Any]] = {source_class: [] for source_class in _BRIDGE_SEED_SLOTS}
    for event in events:
        source_class = _event_source_class(event)
        if source_class in buckets:
            buckets[source_class].append(event)

    for source_class, limit in _BRIDGE_SEED_SLOTS.items():
        for event in sorted(buckets[source_class], key=_seed_sort_key, reverse=True)[:limit]:
            if len(selected) >= _MAX_CONTINUITY_RECORDS:
                break
            if event.id in selected_ids:
                continue
            selected.append(event)
            selected_ids.add(event.id)

    remaining = [event for event in events if event.id not in selected_ids]
    for event in sorted(remaining, key=_global_sort_key, reverse=True):
        if len(selected) >= _MAX_CONTINUITY_RECORDS:
            break
        selected.append(event)
        selected_ids.add(event.id)

    dropped = [event for event in events if event.id not in selected_ids]
    selected = sorted(selected, key=lambda event: (event.ts, event.id))
    return selected, dropped


def _seed_sort_key(event: Any) -> tuple[str, float, str]:
    return (str(getattr(event, "ts", "")), _event_importance(event), str(getattr(event, "id", "")))


def _global_sort_key(event: Any) -> tuple[float, str, str]:
    return (_event_importance(event), str(getattr(event, "ts", "")), str(getattr(event, "id", "")))


def _event_importance(event: Any) -> float:
    safe_ref = getattr(event, "safe_ref", {}) or {}
    for key in ("importance", "score", "drive_weight"):
        try:
            return float(safe_ref.get(key, 0.0))
        except (TypeError, ValueError):
            continue
    return 0.0


def _event_source_class(event: Any) -> str:
    safe_ref = getattr(event, "safe_ref", {}) or {}
    source = str(getattr(event, "source", "")).lower()
    kind = str(getattr(event, "kind", "")).lower()
    tags = {str(tag).lower() for tag in getattr(event, "tags", [])}
    source_module = str(safe_ref.get("source_module", "")).lower()
    source_class = str(safe_ref.get("source_class", "")).lower()
    platform = str(safe_ref.get("platform", "")).lower()
    if source_module == "cron_mirror" or source == "cron" or "cron" in tags or platform == "cron":
        return "cron"
    if source_module == "state_source_mirror" or source_class.startswith("state:") or source == "state_source_mirror":
        return "state_source"
    if platform == "mailbox" or source == "mailbox" or "mailbox" in tags:
        return "mailbox"
    if platform in {"room", "family", "household"} or source in {"room", "family", "household"}:
        return "room_family"
    if source_module in {"ops_gate", "proposal_queue", "evidence_scoring", "self_evolution"}:
        return "governance"
    if any(marker in kind for marker in ("proposal", "governance", "evidence", "ops_gate", "self_evolution")):
        return "governance"
    if kind in {"conversation_turn", "memory_write", "conversation_turn_mirrored"}:
        return "foreground"
    return "other"


def _indexed_lines(query: str, index: object | None) -> list[str]:
    route = plan_query_route(query, diagnostic_grounding_enabled=False)
    search_query = str(route.get("search_query", ""))
    if index is None or not search_query.strip() or not hasattr(index, "search"):
        return []
    try:
        result = index.search(search_query, limit=5)
    except Exception:
        return []
    lines: list[str] = []
    for hit in result.get("hits", []):
        if not isinstance(hit, dict):
            continue
        snippet = _redact(_clip(str(hit.get("snippet", "")), 220))
        if snippet:
            lines.append(f"- {hit.get('record_type', 'record')}/{hit.get('record_id', '')}: {snippet}")
    if lines:
        display_query = str(route.get("display_query", ""))
        lines.insert(0, f"- query route: {route.get('route', 'slow_path')}; search: {display_query}")
    return lines


def _should_ground_diagnostic_query(
    query: str,
    *,
    diagnostic_grounding_enabled: bool,
) -> bool:
    if not diagnostic_grounding_enabled:
        return False
    text = " ".join(str(query or "").split())
    if not text:
        return False
    return any(pattern.search(text) for pattern in _DIAGNOSTIC_QUERY_PATTERNS)


def _format_diagnostic(runtime_facts: dict[str, Any]) -> str:
    context_facts = {
        key: value
        for key, value in runtime_facts.items()
        if key not in {"forbidden_claims"}
    }
    output = [
        HEADER,
        "",
        "### Diagnostic Grounding",
        f"- {DIAGNOSTIC_SUPPRESSION_NOTICE}",
        "",
        "### Current Memory-OS Runtime Facts",
    ]
    for key in (
        "provider",
        "canonical_store",
        "storage_model",
        "uses_hindsight_http_api",
        "hindsight_role",
        "index_health",
        "prefetch_mode",
    ):
        if key in context_facts:
            output.append(f"- {key}: {_fact_value(context_facts[key])}")
    output.append("```json")
    output.append(json.dumps(context_facts, ensure_ascii=False, indent=2, sort_keys=True))
    output.append("```")
    return "\n".join(output)


def _fact_value(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def _dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        normalized = item.strip()
        key = normalized.lower()
        if normalized and key not in seen:
            result.append(normalized)
            seen.add(key)
    return result


def _file_snippet(path: Path) -> str:
    try:
        return _redact(_clip(path.read_text(encoding="utf-8"), 260))
    except Exception:
        return ""


def _crystallized_snippet(path: Path) -> str:
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        return ""
    parts = content.split("---", 2)
    body = parts[2] if len(parts) == 3 else content
    return _redact(_clip(body, 260))


def _format(sections: list[tuple[str, list[str]]]) -> str:
    output = [HEADER]
    for title, lines in sections:
        output.append("")
        output.append(f"### {title}")
        output.extend(lines)
    return "\n".join(output)


def _fit_budget(context: str, budget_chars: int) -> str:
    if budget_chars <= 0:
        return ""
    if len(context) <= budget_chars:
        return context
    if budget_chars <= len(HEADER):
        return HEADER[:budget_chars]
    trimmed = context[:budget_chars].rstrip()
    if "\n" in trimmed:
        trimmed = trimmed.rsplit("\n", 1)[0].rstrip()
    return trimmed[:budget_chars]


def _clip(value: str, limit: int) -> str:
    clean = " ".join(str(value or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "..."


def _redact(value: str) -> str:
    redacted = value
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(r"\1[redacted]", redacted)
    return redacted
