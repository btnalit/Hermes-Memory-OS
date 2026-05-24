"""Bounded context assembly for Memory-OS."""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .context_router import ContextSection, is_low_clue_recall_query, route_context_sections
from .crystallized import read_candidate_queue
from .low_clue_recall import build_low_clue_guard_lines, normalize_low_clue_recall_config
from .memory_sources import (
    GUARD_RECALL_CLARIFICATION,
    append_memory_source_record,
    build_memory_source_record,
    memory_sources_enabled,
    normalize_memory_sources_config,
)
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
    re.compile(r"(?i)(password\s*[:=]\s*)\S+"),
)

_DIAGNOSTIC_STYLE_SEED_PATTERNS = (
    re.compile(r"memory[-_ ]?os\.tool_status", re.I),
    re.compile(r"memory_os_status", re.I),
    re.compile(r"index_health", re.I),
    re.compile(r"prefetch_mode", re.I),
    re.compile(r"canonical_store|canonical store", re.I),
    re.compile(r"storage_model", re.I),
    re.compile(r"172\.18\.0\.99"),
    re.compile(r"/root/\.hermes/memory-os"),
    re.compile(r"<memory-context>", re.I),
    re.compile(r"hindsight api", re.I),
    re.compile(r"\bops-gate\b", re.I),
    re.compile(r"\bproposal queue\b", re.I),
    re.compile(r"runtime facts", re.I),
    re.compile(r"internal reflection context", re.I),
    re.compile(r"context[- ]continuity", re.I),
    re.compile(r"indexed recall", re.I),
    re.compile(r"skill_manage", re.I),
    re.compile(r"hermes02", re.I),
    re.compile(r"\bself[-_ ]?evolution\b", re.I),
    re.compile(r"\bgovernance\b.*(集成|event_kinds|proposal|evidence|ops|dry[-_ ]?run|report)", re.I),
    re.compile(r"governance_(proposal|evidence|self_evolution|ops_gate)", re.I),
    re.compile(r"event_kinds", re.I),
    re.compile(r"crystallized candidates?", re.I),
    re.compile(r"crystallized records?", re.I),
    re.compile(r"audit entries", re.I),
    re.compile(r"working items", re.I),
    re.compile(r"\bRH-\d+", re.I),
    re.compile(r"status snapshot", re.I),
    re.compile(r"governance_ops_gate_decision", re.I),
    re.compile(r"cron_job_run", re.I),
    re.compile(r"crystallized_candidates?", re.I),
    re.compile(r"crystallized_records?", re.I),
    re.compile(r"系统实时状态"),
    re.compile(r"多源融合"),
    re.compile(r"决策门控"),
    re.compile(r"审计条目"),
    re.compile(r"审计记录"),
    re.compile(r"工作项"),
    re.compile(r"结晶候选|待结晶"),
    re.compile(r"实时诊断数据"),
    re.compile(r"当前提供商"),
    re.compile(r"权威存储路径"),
    re.compile(r"权威路径"),
    re.compile(r"核心架构"),
    re.compile(r"索引健康"),
)


def build_prefetch(
    query: str,
    *,
    budget_chars: int,
    store: MemoryOSStore,
    index: object | None = None,
    diagnostic_grounding_enabled: bool = True,
    runtime_facts: dict[str, Any] | None = None,
    current_task_anchor: str | None = None,
    foreground_task_only: bool = False,
    context_router_config: dict[str, Any] | None = None,
    memory_sources_config: dict[str, Any] | None = None,
    low_clue_recall_config: dict[str, Any] | None = None,
) -> str:
    router_config = _normalize_context_router_config(context_router_config)
    source_config = normalize_memory_sources_config(memory_sources_config)
    low_clue_config = normalize_low_clue_recall_config(low_clue_recall_config)
    router_apply_enabled = _context_router_apply_enabled(router_config)
    if _should_ground_diagnostic_query(
        query,
        diagnostic_grounding_enabled=diagnostic_grounding_enabled,
    ) and not router_apply_enabled:
        context = _fit_budget(_format_diagnostic(runtime_facts or {}), budget_chars)
        candidates = build_prefetch_section_candidates(
            query,
            store=store,
            index=index,
            diagnostic_grounding_enabled=diagnostic_grounding_enabled,
            runtime_facts=runtime_facts,
            current_task_anchor=current_task_anchor,
            low_clue_recall_config=low_clue_config,
        )
        report = route_context_sections(
            query,
            sections=candidates,
            current_task_anchor=current_task_anchor,
            budget_chars=budget_chars,
            mode="disabled",
        )
        _record_memory_sources(
            store=store,
            config=source_config,
            route_report=report,
            selected_sections=candidates,
            context_router_config=router_config,
            router_applied=False,
            prefetch_mode=_prefetch_mode(index),
        )
        return context
    current_task_section: list[tuple[str, list[str]]] = []
    _append_section(current_task_section, "Current Foreground Task", _current_task_anchor_lines(current_task_anchor))
    if foreground_task_only and current_task_section:
        context = _fit_budget(_format(current_task_section), budget_chars)
        selected_sections = [
            ContextSection(
                section=title,
                text="\n".join(lines),
                source_class=_section_source_class(title),
                metadata=_section_metadata(title),
            )
            for title, lines in current_task_section
        ]
        report = route_context_sections(
            query,
            sections=selected_sections,
            current_task_anchor=current_task_anchor,
            budget_chars=budget_chars,
            mode="foreground_only",
        )
        _record_memory_sources(
            store=store,
            config=source_config,
            route_report=report,
            selected_sections=selected_sections,
            context_router_config=router_config,
            router_applied=False,
            prefetch_mode=_prefetch_mode(index),
        )
        return context
    if router_apply_enabled:
        routed = _build_context_router_apply_prefetch(
            query,
            budget_chars=budget_chars,
            store=store,
            index=index,
            diagnostic_grounding_enabled=diagnostic_grounding_enabled,
            runtime_facts=runtime_facts,
            current_task_anchor=current_task_anchor,
            context_router_config=router_config,
            low_clue_recall_config=low_clue_config,
        )
        if routed is not None:
            _record_memory_sources(
                store=store,
                config=source_config,
                route_report=routed["report"],
                selected_sections=routed["selected_sections"],
                context_router_config=router_config,
                router_applied=True,
                prefetch_mode=_prefetch_mode(index),
            )
            return str(routed["context"])
    sections = _build_prefetch_sections(
        query,
        store=store,
        index=index,
        current_task_anchor=current_task_anchor,
        low_clue_recall_config=low_clue_config,
    )
    if not sections:
        report = route_context_sections(
            query,
            sections=[],
            current_task_anchor=current_task_anchor,
            budget_chars=budget_chars,
            mode=str(router_config.get("mode") or "disabled"),
        )
        _record_memory_sources(
            store=store,
            config=source_config,
            route_report=report,
            selected_sections=[],
            context_router_config=router_config,
            router_applied=False,
            prefetch_mode=_prefetch_mode(index),
        )
        return ""
    context = _fit_budget(_format(sections), budget_chars)
    candidates = [
        ContextSection(
            section=title,
            text="\n".join(lines),
            source_class=_section_source_class(title),
            metadata=_section_metadata(title),
        )
        for title, lines in sections
    ]
    report = route_context_sections(
        query,
        sections=candidates,
        current_task_anchor=current_task_anchor,
        budget_chars=budget_chars,
        mode=str(router_config.get("mode") or "disabled"),
    )
    _record_memory_sources(
        store=store,
        config=source_config,
        route_report=report,
        selected_sections=candidates,
        context_router_config=router_config,
        router_applied=False,
        prefetch_mode=_prefetch_mode(index),
    )
    return context


def build_prefetch_section_candidates(
    query: str,
    *,
    store: MemoryOSStore,
    index: object | None = None,
    diagnostic_grounding_enabled: bool = True,
    runtime_facts: dict[str, Any] | None = None,
    current_task_anchor: str | None = None,
    low_clue_recall_config: dict[str, Any] | None = None,
) -> list[ContextSection]:
    if _should_ground_diagnostic_query(
        query,
        diagnostic_grounding_enabled=diagnostic_grounding_enabled,
    ):
        return [
            ContextSection(
                section="Diagnostic Grounding",
                text=_format_diagnostic(runtime_facts or {}),
                source_class="diagnostic",
            )
        ]
    return [
        ContextSection(
            section=title,
            text="\n".join(lines),
            source_class=_section_source_class(title),
            metadata=_section_metadata(title),
        )
        for title, lines in _build_prefetch_sections(
            query,
            store=store,
            index=index,
            current_task_anchor=current_task_anchor,
            low_clue_recall_config=low_clue_recall_config,
        )
    ]


def build_context_router_report(
    query: str,
    *,
    budget_chars: int,
    store: MemoryOSStore,
    index: object | None = None,
    diagnostic_grounding_enabled: bool = True,
    runtime_facts: dict[str, Any] | None = None,
    current_task_anchor: str | None = None,
    low_clue_recall_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return route_context_sections(
        query,
        sections=build_prefetch_section_candidates(
            query,
            store=store,
            index=index,
            diagnostic_grounding_enabled=diagnostic_grounding_enabled,
            runtime_facts=runtime_facts,
            current_task_anchor=current_task_anchor,
            low_clue_recall_config=low_clue_recall_config,
        ),
        current_task_anchor=current_task_anchor,
        budget_chars=budget_chars,
        mode="dry_run",
    )


def _build_context_router_apply_prefetch(
    query: str,
    *,
    budget_chars: int,
    store: MemoryOSStore,
    index: object | None = None,
    diagnostic_grounding_enabled: bool = True,
    runtime_facts: dict[str, Any] | None = None,
    current_task_anchor: str | None = None,
    context_router_config: dict[str, Any],
    low_clue_recall_config: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    candidates = build_prefetch_section_candidates(
        query,
        store=store,
        index=index,
        diagnostic_grounding_enabled=diagnostic_grounding_enabled,
        runtime_facts=runtime_facts,
        current_task_anchor=current_task_anchor,
        low_clue_recall_config=low_clue_recall_config,
    )
    report = route_context_sections(
        query,
        sections=candidates,
        current_task_anchor=current_task_anchor,
        budget_chars=budget_chars,
        mode="apply",
    )
    route = str(report.get("route") or "")
    if not _context_router_route_applies(route, context_router_config):
        return None
    selected_names = [str(item.get("section") or "") for item in report.get("selected_sections", [])]
    selected_sections = _sections_for_selected_names(candidates, selected_names)
    if route == "foreground_control":
        selected_sections = [section for section in selected_sections if section.section == "Current Foreground Task"]
    if not selected_sections:
        context = ""
    else:
        context = _fit_budget(_format_selected_context_sections(selected_sections), budget_chars)
    return {"context": context, "report": report, "selected_sections": selected_sections}


def _build_prefetch_sections(
    query: str,
    *,
    store: MemoryOSStore,
    index: object | None = None,
    current_task_anchor: str | None = None,
    low_clue_recall_config: dict[str, Any] | None = None,
) -> list[tuple[str, list[str]]]:
    sections: list[tuple[str, list[str]]] = []
    _append_section(
        sections,
        "Recall Clarification Guard",
        _recall_clarification_guard_lines(
            query,
            store=store,
            low_clue_recall_config=low_clue_recall_config,
        ),
    )
    _append_section(sections, "Current Foreground Task", _current_task_anchor_lines(current_task_anchor))
    _append_section(sections, "Identity Memory", _identity_lines(store))
    _append_section(sections, "Continuity Bridge", _continuity_bridge_lines(store))
    _append_section(sections, "Conversation Carryover", _deep_reflection_lines(store))
    _append_section(sections, "Working Memory", _working_lines(store))
    _append_section(sections, "Relationship Memory", _relationship_lines(store))
    _append_section(sections, "Crystallized Review Candidates", _candidate_lines(store, query=query))
    _append_section(sections, "Crystallized Memory", _crystallized_lines(store))
    _append_section(sections, "Indexed Recall", _indexed_lines(query, index))
    _append_section(sections, "Recent Event Summaries", _event_lines(store))
    return sections


def _section_source_class(title: str) -> str:
    mapping = {
        "Current Foreground Task": "foreground",
        "Recall Clarification Guard": "recall_guard",
        "Identity Memory": "identity",
        "Continuity Bridge": "bridge",
        "Conversation Carryover": "carryover",
        "Working Memory": "working",
        "Relationship Memory": "relationship",
        "Crystallized Review Candidates": "candidate",
        "Crystallized Memory": "crystallized",
        "Indexed Recall": "indexed",
        "Recent Event Summaries": "event",
        "Diagnostic Grounding": "diagnostic",
    }
    return mapping.get(title, "other")


def _section_metadata(title: str) -> dict[str, Any]:
    if title == "Recall Clarification Guard":
        return {"source_ids": [GUARD_RECALL_CLARIFICATION]}
    return {}


def _record_memory_sources(
    *,
    store: MemoryOSStore,
    config: dict[str, Any],
    route_report: dict[str, Any],
    selected_sections: list[ContextSection],
    context_router_config: dict[str, Any],
    router_applied: bool,
    prefetch_mode: str,
) -> None:
    if not memory_sources_enabled(config) or not bool(config.get("record_live_prefetch", True)):
        return
    record = build_memory_source_record(
        roots=store.roots,
        route_report=route_report,
        selected_sections=selected_sections,
        context_router_config=context_router_config,
        router_applied=router_applied,
        prefetch_mode=prefetch_mode,
    )
    append_memory_source_record(store.roots, record)


def _prefetch_mode(index: object | None) -> str:
    return "indexed" if index is not None else "degraded_filesystem"


def _normalize_context_router_config(config: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(config, dict):
        return {
            "enabled": False,
            "mode": "dry_run",
            "apply_routes": [],
            "dry_run_routes": [],
            "llm_judge_mode": "disabled",
        }
    return {
        "enabled": bool(config.get("enabled")),
        "mode": str(config.get("mode") or "dry_run"),
        "apply_routes": list(config.get("apply_routes") or []),
        "dry_run_routes": list(config.get("dry_run_routes") or []),
        "llm_judge_mode": str(config.get("llm_judge_mode") or "disabled"),
    }


def _context_router_apply_enabled(config: dict[str, Any]) -> bool:
    return bool(config.get("enabled")) and str(config.get("mode") or "") == "apply"


def _context_router_route_applies(route: str, config: dict[str, Any]) -> bool:
    routes = {str(item) for item in config.get("apply_routes", [])}
    return "all" in routes or route in routes


def _sections_for_selected_names(candidates: list[ContextSection], selected_names: list[str]) -> list[ContextSection]:
    remaining = list(candidates)
    selected: list[ContextSection] = []
    for name in selected_names:
        for index, candidate in enumerate(remaining):
            if candidate.section != name:
                continue
            selected.append(candidate)
            remaining.pop(index)
            break
    return selected


def _format_selected_context_sections(sections: list[ContextSection]) -> str:
    nonempty = [section for section in sections if section.text.strip()]
    if len(nonempty) == 1 and nonempty[0].text.startswith(HEADER):
        return nonempty[0].text
    return _format([(section.section, section.text.splitlines()) for section in nonempty])


def _recall_clarification_guard_lines(
    query: str,
    *,
    store: MemoryOSStore,
    low_clue_recall_config: dict[str, Any] | None = None,
) -> list[str]:
    if not is_low_clue_recall_query(query):
        return []
    config = normalize_low_clue_recall_config(low_clue_recall_config)
    if bool(config.get("enabled")):
        return build_low_clue_guard_lines(
            query,
            store=store,
            config=config,
            limit=int(config.get("candidate_limit") or 4),
        )
    return [
        "The user's recall request is underspecified.",
        "Do not answer as if one remembered item is certain.",
        "Offer 2-3 plausible directions or ask for a keyword, time, project, or source.",
        "If the user rejects two guesses, stop guessing and ask for an anchor.",
    ]


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


def _current_task_anchor_lines(anchor: str | None) -> list[str]:
    if not anchor:
        return []
    text = _redact(_clip_multiline(str(anchor), 700))
    lines: list[str] = []
    for line in text.splitlines():
        clean = line.strip()
        if not clean or clean.startswith("###"):
            continue
        lines.append(clean if clean.startswith("-") else f"- {clean}")
    return lines[:6]


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
            if _is_diagnostic_style_seed(text):
                continue
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


def _candidate_lines(store: MemoryOSStore, *, query: str) -> list[str]:
    if not _should_include_candidates(query):
        return []
    lines: list[str] = []
    for candidate in read_candidate_queue(store.roots)[:5]:
        text = _redact(_clip(candidate.body, 180))
        if _is_diagnostic_style_seed(text):
            continue
        if text:
            lines.append(
                "- candidate only / review candidate; not approved crystallized memory: "
                f"{candidate.candidate_id} {candidate.kind}: {text}"
            )
    return lines


def _should_include_candidates(query: str) -> bool:
    text = " ".join(str(query or "").split()).lower()
    if not text:
        return False
    patterns = (
        r"candidate|candidates",
        r"crystallized|crystallization|long[- ]term memory|review queue",
        r"候选|结晶|沉淀|长期记忆|长期智慧|审查队列|待审",
    )
    return any(re.search(pattern, text, re.I) for pattern in patterns)


def _event_lines(store: MemoryOSStore) -> list[str]:
    selected, _dropped = _select_continuity_events(store)
    return [
        f"- {_event_source_class(event)}/{event.kind}: {_redact(_clip(event.summary, 220))}"
        for event in selected
        if not _is_diagnostic_style_seed(str(event.summary))
    ]


def _continuity_bridge_lines(store: MemoryOSStore) -> list[str]:
    selected, _dropped = _select_continuity_events(store)
    return [
        f"- {_event_source_class(event)}/{event.kind}: {_redact(_clip(event.summary, 220))}"
        for event in selected
        if _event_source_class(event) in {"cron", "mailbox", "room_family", "state_source", "governance"}
        and not _is_diagnostic_style_seed(str(event.summary))
    ]


def _deep_reflection_lines(store: MemoryOSStore) -> list[str]:
    module_root = store.roots.hermes_home / "system-modules" / "deep_reflection"
    config_path = module_root / "config.json"
    current_path = module_root / "injection" / "current.json"
    if not config_path.exists() or not current_path.exists():
        return []
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        current = json.loads(current_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(config, dict) or config.get("injection_mode") != "auto_bounded":
        return []
    if not isinstance(current, dict):
        return []
    lines: list[str] = []
    for card in current.get("selected_cards", [])[:3]:
        if not isinstance(card, dict) or not _deep_reflection_card_is_safe(card):
            continue
        text = _redact(_clip(str(card.get("text", "")), 220))
        if text:
            lines.append(f"- {text}")
    return lines


def _deep_reflection_card_is_safe(card: dict[str, Any]) -> bool:
    text = str(card.get("text", ""))
    if not text or not card.get("source_refs"):
        return False
    if card.get("instruction_like_hit") or card.get("mechanism_terms_hit"):
        return False
    if _is_diagnostic_style_seed(text):
        return False
    lowered = text.lower()
    if any(
        marker in lowered
        for marker in (
            "you must",
            "you should",
            "execute",
            "approve",
            "modify identity",
            "send a message",
            "system prompt",
            "prefetch",
            "injection card",
            "source refs",
            "deep reflection",
            "runtime index",
            "你必须",
            "你应该",
            "执行",
            "批准",
            "修改身份",
            "发消息",
        )
    ):
        return False
    expires_at = str(card.get("expires_at", ""))
    if expires_at:
        try:
            if datetime.fromisoformat(expires_at) <= datetime.now(timezone.utc):
                return False
        except ValueError:
            return False
    return True


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


def _is_diagnostic_style_seed(text: str) -> bool:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return False
    return any(pattern.search(normalized) for pattern in _DIAGNOSTIC_STYLE_SEED_PATTERNS)


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


def _clip_multiline(value: str, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def _redact(value: str) -> str:
    redacted = value
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(r"\1[redacted]", redacted)
    return redacted
