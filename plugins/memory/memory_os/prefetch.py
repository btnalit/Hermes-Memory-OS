"""Bounded context assembly for Memory-OS."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .store import MemoryOSStore


HEADER = "## Memory-OS Context"

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
) -> str:
    sections: list[tuple[str, list[str]]] = []
    _append_section(sections, "Identity Memory", _identity_lines(store))
    _append_section(sections, "Working Memory", _working_lines(store))
    _append_section(sections, "Relationship Memory", _relationship_lines(store))
    _append_section(sections, "Crystallized Memory", _crystallized_lines(store))
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
