"""Bounded context assembly for Memory-OS."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .store import MemoryOSStore


HEADER = "## Memory-OS Context"
DIAGNOSTIC_SUPPRESSION_NOTICE = (
    "Historical recall suppressed for diagnostic query. Use Current Memory-OS Runtime Facts only."
)

_DIAGNOSTIC_QUERY_PATTERNS = (
    re.compile(r"记忆\s*(架构|系统|后端|provider|提供商|状态)"),
    re.compile(r"当前.*(memory_os|memory-os|记忆|memory).*(状态|架构|系统|provider|backend)", re.I),
    re.compile(r"(memory[-_ ]?os|hindsight).*(canonical|store|provider|backend|正常|还在用)", re.I),
    re.compile(r"(memory architecture|memory backend|memory provider|current memory state)", re.I),
    re.compile(r"(which|what).*(memory|storage).*(provider|backend|system)", re.I),
    re.compile(r"用的什么.*记忆"),
)

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
    _append_section(sections, "Working Memory", _working_lines(store))
    _append_section(sections, "Relationship Memory", _relationship_lines(store))
    _append_section(sections, "Crystallized Memory", _crystallized_lines(store))
    _append_section(sections, "Indexed Recall", _indexed_lines(query, index))
    _append_section(sections, "Recent Event Summaries", _event_lines(store))
    if not sections:
        return ""
    return _fit_budget(_format(sections), budget_chars)


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


def _event_lines(store: MemoryOSStore) -> list[str]:
    events = sorted(store.read_events(), key=lambda event: event.ts)[-5:]
    return [f"- {event.kind}: {_redact(_clip(event.summary, 220))}" for event in events]


def _indexed_lines(query: str, index: object | None) -> list[str]:
    if index is None or not query.strip() or not hasattr(index, "search"):
        return []
    try:
        result = index.search(query, limit=5)
    except Exception:
        return []
    lines: list[str] = []
    for hit in result.get("hits", []):
        if not isinstance(hit, dict):
            continue
        snippet = _redact(_clip(str(hit.get("snippet", "")), 220))
        if snippet:
            lines.append(f"- {hit.get('record_type', 'record')}/{hit.get('record_id', '')}: {snippet}")
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
