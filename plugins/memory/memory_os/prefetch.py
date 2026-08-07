"""Bounded context assembly for Memory-OS."""

from __future__ import annotations

import functools
import json
import re
import unicodedata
from collections import Counter
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from .context_router import ContextSection, is_low_clue_recall_query, route_context_sections
from .crystallized import (
    CrystallizedMemoryService,
    read_candidate_queue,
    _parse_markdown_records,
    is_active_crystallized_frontmatter,
)
from .low_clue_recall import (
    _bounded_query_features,
    build_low_clue_guard_lines,
    normalize_low_clue_recall_config,
)
from .jsonl_io import build_error_record
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
# Kill switch for continuity freshness grading (report-only disclosure lane).
CONTINUITY_FRESHNESS_KNOB = "lane_continuity_freshness_enabled"
# Max working items shown per file (most recent first).
WORKING_ITEMS_PER_FILE = 5

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
    # Generic ops / content words — deliberately excludes:
    #   - project-internal terms (e.g. 提案/治理/证据/结晶/候选/索引/会话)
    #     NOTE: these same terms appear in _CHINESE_TOPIC_KEYWORDS in __init__.py
    #     for task-continuity detection — the two lists serve different purposes
    #     (query routing vs. topic-change detection) and are intentionally divergent.
    #   - question / stop words (those go through slow_path full-query search)
    "报错",
    "错误",
    "失败",
    "丢包",
    "队列",
    "网关",
    "重启",
    "定时",
    "状态",
    "延迟",
    "记忆",
    # Generic cross-domain content / relation words
    "原因",
    "方法",
    "区别",
    "对比",
    "配置",
    "命令",
    "日志",
    "文件",
    "路径",
    "端口",
)

_FAST_PATH_STOP_WORDS: frozenset[str] = frozenset({
    "为什么", "怎么", "什么时候", "哪里", "谁", "多少",
    "是什么", "怎么样", "哪一个",
})

_fast_path_keywords_override: list[str] | None = None
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
    # Smoke / test pattern seeds — prevent synthetic test messages from
    # leaking into agent context via crystallized / cross-session / working memory sections.
    re.compile(r"\bsmoke\s+(user|assistant|test|event)\s+msg\b", re.I),
    re.compile(r"\bsmoke\s+test\s+(message|event|record)\b", re.I),
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
    session_id: str = "",
    diagnostic_grounding_enabled: bool = True,
    runtime_facts: dict[str, Any] | None = None,
    current_task_anchor: str | None = None,
    foreground_task_only: bool = False,
    context_router_config: dict[str, Any] | None = None,
    memory_sources_config: dict[str, Any] | None = None,
    low_clue_recall_config: dict[str, Any] | None = None,
    substrate_recall_report: dict[str, Any] | None = None,
    recall_facade: object | None = None,  # Phase 3: RetrieverFacade (provider-cached)
) -> str:
    router_config = _normalize_context_router_config(context_router_config)
    source_config = normalize_memory_sources_config(memory_sources_config)
    low_clue_config = normalize_low_clue_recall_config(low_clue_recall_config)
    # Graded before any early return, so every prefetch path (diagnostic
    # grounding, foreground-only, router-apply, normal) is covered by the same
    # disclosure.  This must not influence anything below it — see the
    # function docstring.
    _record_continuity_freshness(store, session_id=session_id)
    if isinstance(substrate_recall_report, dict):
        _record_substrate_shadow_recall(
            store=store,
            query=query,
            report=substrate_recall_report,
        )
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
            session_id=session_id,
            diagnostic_grounding_enabled=diagnostic_grounding_enabled,
            runtime_facts=runtime_facts,
            current_task_anchor=current_task_anchor,
            low_clue_recall_config=low_clue_config,
            substrate_recall_report=substrate_recall_report,
            recall_facade=recall_facade,
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
        _append_section(
            current_task_section, "Last Session",
            _last_session_lines(store, session_id=session_id, seen=None),
        )
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
            session_id=session_id,
            diagnostic_grounding_enabled=diagnostic_grounding_enabled,
            runtime_facts=runtime_facts,
            current_task_anchor=current_task_anchor,
            context_router_config=router_config,
            low_clue_recall_config=low_clue_config,
            substrate_recall_report=substrate_recall_report,
            recall_facade=recall_facade,
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
    sections, section_source_ids = _build_prefetch_sections(
        query,
        store=store,
        index=index,
        session_id=session_id,
        current_task_anchor=current_task_anchor,
        low_clue_recall_config=low_clue_config,
        substrate_recall_report=substrate_recall_report,
        recall_facade=recall_facade,
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
            metadata=_section_metadata(title, source_ids=section_source_ids.get(title)),
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


def build_prefetch_with_observability(
    query: str,
    *,
    budget_chars: int,
    store: MemoryOSStore,
    index: object | None = None,
    session_id: str = "",
    current_task_anchor: str | None = None,
    low_clue_recall_config: dict[str, Any] | None = None,
    substrate_recall_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    error_records: list[dict[str, Any]] = []
    sections, _section_ids = _build_prefetch_sections(
        query,
        store=store,
        index=index,
        session_id=session_id,
        current_task_anchor=current_task_anchor,
        low_clue_recall_config=low_clue_recall_config,
        substrate_recall_report=substrate_recall_report,
        error_records=error_records,
    )
    context = _fit_budget(_format(sections), budget_chars) if sections else ""
    return {
        "schema_version": "memory-os.prefetch_observability.v0",
        "context": context,
        "suppressed_error_count": len(error_records),
        "recent_error_codes": [
            str(record.get("error_code") or "")
            for record in error_records[-5:]
            if str(record.get("error_code") or "")
        ],
        "error_records": error_records[-5:],
    }


def build_prefetch_section_candidates(
    query: str,
    *,
    store: MemoryOSStore,
    index: object | None = None,
    session_id: str = "",
    diagnostic_grounding_enabled: bool = True,
    runtime_facts: dict[str, Any] | None = None,
    current_task_anchor: str | None = None,
    low_clue_recall_config: dict[str, Any] | None = None,
    substrate_recall_report: dict[str, Any] | None = None,
    recall_facade: object | None = None,  # Phase 3: provider-cached RetrieverFacade
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
    raw_sections, section_source_ids = _build_prefetch_sections(
        query,
        store=store,
        index=index,
        session_id=session_id,
        current_task_anchor=current_task_anchor,
        low_clue_recall_config=low_clue_recall_config,
        substrate_recall_report=substrate_recall_report,
        recall_facade=recall_facade,
    )
    return [
        ContextSection(
            section=title,
            text="\n".join(lines),
            source_class=_section_source_class(title),
            metadata=_section_metadata(title, source_ids=section_source_ids.get(title)),
        )
        for title, lines in raw_sections
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
    substrate_recall_report: dict[str, Any] | None = None,
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
            substrate_recall_report=substrate_recall_report,
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
    session_id: str = "",
    diagnostic_grounding_enabled: bool = True,
    runtime_facts: dict[str, Any] | None = None,
    current_task_anchor: str | None = None,
    context_router_config: dict[str, Any],
    low_clue_recall_config: dict[str, Any] | None = None,
    substrate_recall_report: dict[str, Any] | None = None,
    recall_facade: object | None = None,
) -> dict[str, Any] | None:
    candidates = build_prefetch_section_candidates(
        query,
        store=store,
        index=index,
        session_id=session_id,
        diagnostic_grounding_enabled=diagnostic_grounding_enabled,
        runtime_facts=runtime_facts,
        current_task_anchor=current_task_anchor,
        low_clue_recall_config=low_clue_recall_config,
        substrate_recall_report=substrate_recall_report,
        recall_facade=recall_facade,
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
    # Required headings are a route contract, not a property of whichever
    # non-empty candidates survived the raw builder.  Derive them directly
    # from the selected route so empty source data cannot erase the heading.
    required_by_route = {
        "foreground_control": ("Current Foreground Task",),
        "diagnostic_current_status": ("Diagnostic Grounding", "Current Memory-OS Runtime Facts"),
        "active_task": ("Current Foreground Task", "Indexed Recall"),
        "candidate_review": ("Crystallized Review Candidates", "Crystallized Memory"),
        "ambiguous_recall": ("Recall Clarification Guard",),
        "casual_continuity": ("Conversation Carryover",),
    }
    required_names = required_by_route.get(route, ())
    if any(section.text.startswith(HEADER) for section in selected_sections):
        # A preformatted aggregate already carries its own heading contract;
        # appending placeholders would force a second wrapper/header.
        required_names = ()
    found_names = {section.section for section in selected_sections}
    for name in required_names:
        if name in found_names:
            continue
        selected_sections.append(
            ContextSection(
                section=name,
                text="",
                source_class=_section_source_class(name),
                metadata={"required": True, "empty_body_placeholder": True},
            )
        )
        found_names.add(name)
    if route == "foreground_control":
        selected_sections = [section for section in selected_sections if section.section == "Current Foreground Task"]
    if not selected_sections:
        context = ""
    else:
        context = _fit_budget(
            _format_selected_context_sections(selected_sections),
            budget_chars,
            required_titles=set(required_names),
        )
    return {"context": context, "report": report, "selected_sections": selected_sections}


def _build_prefetch_sections(
    query: str,
    *,
    store: MemoryOSStore,
    index: object | None = None,
    session_id: str = "",
    current_task_anchor: str | None = None,
    low_clue_recall_config: dict[str, Any] | None = None,
    substrate_recall_report: dict[str, Any] | None = None,
    error_records: list[dict[str, Any]] | None = None,
    recall_facade: object | None = None,  # Phase 3: provider-cached RetrieverFacade
) -> tuple[list[tuple[str, list[str]]], dict[str, list[str]]]:
    sections: list[tuple[str, list[str]]] = []
    section_source_ids: dict[str, list[str]] = {}
    # Shared dedup set: record_ids emitted by dedicated sections are skipped
    # by Indexed Recall to avoid duplicate injection across sections.
    seen: set[tuple[str, str]] = set()
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
    _append_section(sections, "Memory State Overlay", _state_overlay_lines(
        store, roots=store.roots, current_task_anchor=current_task_anchor,
        session_id=session_id, query=query))
    # Single-pass event read: three sections below (Continuity Bridge, Recent
    # Cross-Session, Recent Event Summaries) filter the same canonical event
    # stream. Scanning it once per prefetch keeps the per-turn cost flat in
    # event-history size instead of paying the full JSONL scan three times.
    events_cache = list(store.read_events())
    _append_section(sections, "Continuity Bridge", _continuity_bridge_lines(store, session_id=session_id, seen=seen, events=events_cache))
    _append_section(sections, "Last Session", _last_session_lines(store, session_id=session_id, seen=seen))
    _append_section(
        sections,
        "Recent Cross-Session",
        _recent_cross_session_lines(
            store,
            session_id=session_id,
            error_records=error_records,
            seen=seen,
            query=query,
            events=events_cache,
        ),
    )
    _append_section(sections, "Conversation Carryover", _deep_reflection_lines(store))
    # Attribution (item 16a): every section class the disclosure audit treats as
    # attributable must record the canonical records it drew from, or the
    # disclosure is unauditable. Until this, section_source_ids had exactly ONE
    # assignment site (crystallized), so 12 content-bearing classes emitted
    # chars/count with no source_ids at all. The attributable set is defined on
    # the audit side (see ATTRIBUTABLE_SOURCE_CLASSES there); deliberately not
    # named here, because the X.3 firewall forbids this module from referencing
    # the exposure/audit layer at all -- prefetch ranking must never be able to
    # read audit data. This direction (producer records IDs, audit reads them)
    # is one-way and creates no dependency.
    working_ids: list[str] = []
    _append_section(
        sections, "Working Memory", _working_lines(store, query=query, source_ids=working_ids)
    )
    if working_ids:
        section_source_ids["Working Memory"] = working_ids
    _append_section(sections, "Relationship Memory", _relationship_lines(store))
    candidate_ids: list[str] = []
    _append_section(
        sections,
        "Crystallized Review Candidates",
        _candidate_lines(store, query=query, seen=seen, source_ids=candidate_ids),
    )
    if candidate_ids:
        section_source_ids["Crystallized Review Candidates"] = candidate_ids
    cryst_lines, cryst_degradation, cryst_ids = _crystallized_lines(store, query=query, index=index, seen=seen, error_records=error_records)
    if cryst_degradation >= 2:
        cryst_header = "Crystallized Memory (deterministic floor recall)"
    elif cryst_degradation == 1:
        cryst_header = "Crystallized Memory (recent — no query match)"
    else:
        cryst_header = "Crystallized Memory"
    _append_section(sections, cryst_header, cryst_lines)
    if cryst_ids:
        section_source_ids[cryst_header] = cryst_ids
    _append_section(sections, "Substrate Recall", _substrate_recall_lines(substrate_recall_report))
    indexed_ids: list[str] = []
    _append_section(
        sections,
        "Indexed Recall",
        _indexed_lines(query, index, error_records=error_records, seen=seen, source_ids=indexed_ids),
    )
    if indexed_ids:
        section_source_ids["Indexed Recall"] = indexed_ids
    event_ids: list[str] = []
    _append_section(
        sections,
        "Recent Event Summaries",
        _event_lines(store, session_id=session_id, seen=seen, source_ids=event_ids, events=events_cache),
    )
    if event_ids:
        section_source_ids["Recent Event Summaries"] = event_ids
    # Second-hop graph traversal: anchor_ids come from FTS5 results.
    # _collect_anchor_ids calls index.search() a second time (微秒级,可忽略).
    # See docstring at _collect_anchor_ids for details.
    _first_anchors = _collect_anchor_ids(query, index)
    graph_ids: list[str] = []
    _append_section(
        sections,
        "Related Memory",
        _graph_layer_shadow_lines(
            store,
            _first_anchors,
            index=index,
            seen=seen,
            source_ids=graph_ids,
            events=events_cache,
        ),
    )
    if graph_ids:
        section_source_ids["Related Memory"] = graph_ids

    # ── Phase 3: Retriever Facade observation/apply lane ───────────────
    # Shadow mode must be output-neutral: retrieve() builds and persists the
    # metadata-only Recall Plan, but only apply_canary may add formatted
    # facade content to the live prefetch. Existing sections remain the
    # fail-open baseline in every mode.
    if recall_facade is not None:
        try:
            from .task_state import read_effective_current_task

            facade: Any = recall_facade
            effective_task = read_effective_current_task(store.roots, max_age_hours=0)
            task_revision = str((effective_task or {}).get("revision") or "")
            results = facade.retrieve(
                store,
                query,
                top_k=10,
                scope={"task_revision": task_revision, "budget_chars": 800},
            )
            plan = getattr(facade, "last_recall_plan", {})
            if isinstance(plan, dict) and plan.get("mode") == "apply_canary":
                facade_text = facade.format_context(results, budget=800)
                if facade_text.strip():
                    sections.append(("Recall Facade (unified)", [facade_text]))
        except Exception as exc:
            # fail-open: facade failure must not block prefetch,
            # but record bounded error for monitor visibility
            if error_records is not None:
                error_records.append(build_error_record(
                    component="prefetch_facade",
                    operation="retrieve_or_format",
                    error_code="facade_exception",
                    severity="warning",
                    recoverable=True,
                    details=str(exc)[:200],
                ))

    return sections, section_source_ids


# Module-level so the attribution contract can be validated against it: the
# vocabulary a checker gates on must be provable against what the producer
# actually emits. Keeping this inside the function is what allowed the audit
# side's attributable-class list to drift onto four names with no producer at
# all (backlog item 16b) -- the mismatch was unobservable to any test.
SECTION_SOURCE_CLASS_BY_TITLE: dict[str, str] = {
    "Current Foreground Task": "foreground",
    "Recall Clarification Guard": "recall_guard",
    "Identity Memory": "identity",
    "Memory State Overlay": "state_overlay",
    "Continuity Bridge": "bridge",
    "Last Session": "last_session",
    "Conversation Carryover": "carryover",
    "Working Memory": "working",
    "Relationship Memory": "relationship",
    "Crystallized Review Candidates": "candidate",
    "Crystallized Memory": "crystallized",
    "Substrate Recall": "substrate_recall",
    "Indexed Recall": "indexed",
    "Recent Event Summaries": "event",
    "Related Memory": "graph_layer",
    "Diagnostic Grounding": "diagnostic",
}

# Returned for any title absent from the mapping above.
SECTION_SOURCE_CLASS_FALLBACK = "other"


def _section_source_class(title: str) -> str:
    # Strip degradation annotation suffix (e.g. "Crystallized Memory (deterministic floor recall)")
    base_title = title.split(" (")[0] if " (" in title else title
    return SECTION_SOURCE_CLASS_BY_TITLE.get(base_title, SECTION_SOURCE_CLASS_FALLBACK)


def _section_metadata(title: str, source_ids: list[str] | None = None) -> dict[str, Any]:
    if title == "Recall Clarification Guard":
        return {"source_ids": [GUARD_RECALL_CLARIFICATION]}
    if source_ids:
        return {"source_ids": source_ids}
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


def _record_substrate_shadow_recall(
    *,
    store: MemoryOSStore,
    query: str,
    report: dict[str, Any],
) -> None:
    facts = report.get("facts") if isinstance(report.get("facts"), list) else []
    if not facts:
        return
    path = store.roots.memory_os_root / "system" / "substrate_recall_shadow.jsonl"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        return  # fail-open: shadow loss must not break prefetch
    record = {
        "schema_version": "memory-os.substrate_recall_shadow.v0",
        # The field name is load-bearing: metadata_retention._record_created_at
        # reads only created_at/ts/timestamp. Without it every record parsed as
        # "no timestamp" and was retained forever (backlog 9). Forward-only:
        # historical rows still carry no timestamp and stay retained -- their
        # disposition is an owner decision recorded in the backlog.
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "query_class": str(report.get("query_class") or ""),
        "query_sha256": _safe_query_hash(query),
        "selected_provider": str(report.get("selected_provider") or ""),
        "fact_count": len(facts),
        "authoritative": bool(report.get("authoritative")),
        "external_authoritative_count": int(report.get("external_authoritative_count") or 0),
        "local_first_authority_preserved": bool(report.get("local_first_authority_preserved")),
        "recall_llm_triggered": bool(report.get("recall_llm_triggered")),
        "fallback_triggered": bool(report.get("fallback_triggered")),
    }
    try:
        from .jsonl_io import append_jsonl_locked
        append_jsonl_locked(path, record)
    except Exception:
        pass  # fail-open: shadow loss must not break prefetch

    from .substrates.ledger import SubstrateOperationLedger

    try:
        operation_ledger = SubstrateOperationLedger(
            store.roots.memory_os_root / "system" / "substrate_operations.jsonl"
        )
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            provider = str(fact.get("provider") or "")
            if provider != "hindsight":
                continue
            operation_ledger.append(
                {
                    "provider": "hindsight",
                    "operation": "recall",
                    "recall_llm_triggered": bool(fact.get("recall_llm_triggered")),
                    "advisory_only": bool(fact.get("advisory_only")),
                    "authority_class": str(fact.get("authority_class") or ""),
                    "substrate_snapshot_id": str(fact.get("substrate_snapshot_id") or ""),
                }
            )
    except Exception:
        pass  # fail-open: operations ledger loss must not break prefetch


def _record_continuity_freshness(store: MemoryOSStore, *, session_id: str = "") -> None:
    """Grade current-task freshness and append a report-only diagnostic record.

    **Discloses; never filters.**  This function returns None and is called for
    its side effect only.  It must never influence the assembled context: the
    existing recency filters (``state_overlay.py`` 7-day candidate window,
    ``_recent_cross_session_lines`` 48-hour window, ``recall_arbitration``'s
    freshness guard) stay exactly as they are, and the live prefetch string is
    byte-identical whether or not this runs.  A test pins that.

    What it produces is the ``stale_task_revision`` finding Gap Note can read.
    ``recall_arbitration.py:86`` emits the same string but under key
    ``"reason"`` with mismatch (not age) semantics, so it is not the same
    signal — see the comment on ``continuity.STALE_TASK_REVISION_REASON_CODE``.

    **Deliberately hooked in ``build_prefetch`` only.**
    ``build_prefetch_with_observability`` (used by
    ``memory_os_3_200_monitor.py``) does not grade, so there is exactly one
    writer to this ledger.  Adding a second entry point would put two writers
    on the same file with different ``session_id`` values and double-count the
    transitions the dedupe signature exists to collapse.  If grading is ever
    wanted there, route it through this function rather than adding a call.

    Kill switch: ``lane_continuity_freshness_enabled``, default True.  The
    owner ruling removed the *waiting window*, not the ability to turn a lane
    off; grading is live from day one and reversible by one owner override.
    """
    path = store.roots.memory_os_root / "system" / "continuity_freshness.jsonl"
    try:
        from .knob_overrides import resolve_knob
        if not bool(resolve_knob(
            CONTINUITY_FRESHNESS_KNOB, True, roots=store.roots,
        )):
            return
        from .continuity import (
            ContinuityState,
            build_continuity_freshness_record,
            build_current_task_continuity_object,
            continuity_freshness_record_is_reportable,
            continuity_freshness_signature,
        )
        from .task_state import read_effective_current_task

        # max_age_hours=0 is deliberate and must stay hardcoded.  That
        # parameter is itself one of the production recency filters: any
        # positive value makes the read return None for exactly the aged
        # records this lane exists to grade, so grading would see only what
        # already passed the filter and could never disagree with it.
        task_record = read_effective_current_task(store.roots, max_age_hours=0)
        state = ContinuityState(
            current_task=build_current_task_continuity_object(task_record),
        )
        freshness = build_continuity_freshness_record(state, session_id=session_id)
        if not continuity_freshness_record_is_reportable(freshness):
            return
        # One line per state transition, not per turn — see
        # ``continuity_freshness_signature``.
        signature = continuity_freshness_signature(freshness)
        if signature and signature == _last_continuity_freshness_signature(path):
            return
    except Exception:
        return  # fail-open: grading must never break prefetch

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        from .jsonl_io import append_jsonl_locked
        append_jsonl_locked(path, freshness)
    except Exception:
        pass  # fail-open: disclosure loss must not break prefetch


def _last_continuity_freshness_signature(path: Path) -> str | None:
    """Signature of the newest ledger record, or None when it cannot be read.

    Returns None rather than "" on any failure: None means "unknown", and the
    caller then writes.  Losing a duplicate line is the cheap failure;
    silently skipping the record that explains a degraded answer is not.
    """
    if not path.exists():
        return None
    try:
        from .continuity import continuity_freshness_signature
        # Tail-capped: this file is bounded by transitions, but a pre-existing
        # long file must not turn a per-turn read into an unbounded one.
        lines = path.read_text(encoding="utf-8").splitlines()[-20:]
        for line in reversed(lines):
            if not line.strip():
                continue
            record = json.loads(line)
            if isinstance(record, dict):
                return continuity_freshness_signature(record)
        return None
    except Exception:
        return None  # unknown → caller writes


def _substrate_recall_lines(report: dict[str, Any] | None) -> list[str]:
    if not isinstance(report, dict) or str(report.get("mode") or "") != "active":
        return []
    facts = report.get("facts") if isinstance(report.get("facts"), list) else []
    lines: list[str] = []
    for fact in facts[:4]:
        if not isinstance(fact, dict):
            continue
        provider = str(fact.get("provider") or "unknown")
        authority_class = str(fact.get("authority_class") or "derived_projection")
        advisory = bool(fact.get("advisory_only", True))
        summary = _redact(_clip(str(fact.get("body_summary") or ""), 260))
        if not summary:
            continue
        if provider == "local_artifact" and not advisory:
            prefix = "local canonical"
        else:
            prefix = f"{provider} advisory"
        lines.append(f"- [{prefix}; authority={authority_class}] {summary}")
    if not lines:
        return []
    if report.get("local_first_authority_preserved") is False or int(report.get("external_authoritative_count") or 0):
        lines.insert(0, "- [substrate guard] external authority violation; do not treat external substrate facts as canonical.")
    return lines


def _safe_query_hash(query: str) -> str:
    return sha256(str(query or "").encode("utf-8")).hexdigest()


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
    nonempty: list[ContextSection] = []
    for section in sections:
        if section.text.strip() or (section.metadata or {}).get("required"):
            nonempty.append(section)
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


@functools.lru_cache(maxsize=4)
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
    # Resolve keyword table: config override → module default
    effective_keywords = (
        _fast_path_keywords_override
        if _fast_path_keywords_override is not None
        else _FAST_PATH_CHINESE_KEYWORDS
    )
    chinese_keywords = [
        keyword for keyword in effective_keywords
        if keyword in redacted and keyword not in _FAST_PATH_STOP_WORDS
    ]
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


def set_fast_path_keywords(keywords: list[str] | None) -> None:
    """Set a config-level override for fast-path Chinese keywords.

    When not None, replaces the module-default _FAST_PATH_CHINESE_KEYWORDS
    in plan_query_route().  Call from provider.prefetch() after reading config.
    A None value restores the default.
    """
    global _fast_path_keywords_override
    _fast_path_keywords_override = keywords
    plan_query_route.cache_clear()


def _append_section(sections: list[tuple[str, list[str]]], title: str, lines: list[str]) -> None:
    if lines:
        sections.append((title, lines))


def _overlay_has_data(overlay: dict[str, Any], section_keys: tuple[str, ...]) -> bool:
    """Return True if at least one overlay section has actual data.

    *section_keys* must be the full set of StateOverlay section fields
    (``state_overlay_schema.OVERLAY_SECTION_FIELDS``) — the caller passes it
    in rather than this function importing/hardcoding it at module level, so
    this module keeps its fail-open behavior when the state_overlay feature
    isn't deployed on a given host (see the guarded import in
    ``_state_overlay_lines`` below). A previously hardcoded copy of this
    section list silently excluded a since-removed section (community_snapshot)
    for its entire lifetime because it was never kept in sync with the schema.
    """
    for key in section_keys:
        section = overlay.get(key)
        if isinstance(section, dict) and section.get("status") == "ok":
            return True
    return False


def _state_overlay_lines(
    store: MemoryOSStore,
    *,
    roots: Any,
    current_task_anchor: str | None = None,
    session_id: str = "",
    query: str = "",
) -> list[str]:
    """Memory State Overlay section — derived projection for conversation context.

    Reads the cron-cached ``current.json`` when available (the cache is
    refreshed by the state_overlay_refresh lane every 30 minutes and is NOT
    freshness-checked here — the O(1) fast path is deliberate), falling back
    to a fresh build only when the cache is missing or unparseable.

    W7 (S1): the cached ``active_projects`` reflects the durable anchor as
    of the last cron refresh — up to 30 minutes stale, which on production
    rendered "(insufficient data)" through entire conversations.  When the
    caller passes a live ``current_task_anchor`` it OVERRIDES the cached
    active_projects section (other sections keep their cached values); the
    cache-level task_revision keys are neutralized by the override helper.

    Fail-open: any exception returns [] so a broken overlay never blocks
    normal prefetch.
    """
    try:
        from .state_overlay import build_state_overlay as _build
        from .state_overlay import override_active_projects_with_live_anchor as _override
        from .state_overlay_renderer import render_state_overlay_md as _render
        from .state_overlay_schema import OVERLAY_SECTION_FIELDS
    except ImportError:
        return []

    # S6 终局(owner 决策 2026-08-06):状态层在所有路由下百分之百原样注入,
    # 包括 casual_continuity 兜底 — 「状态层是整个记忆系统的精髓」。闲聊
    # 上下文携带前台任务内容属已知观察项,不做代码抑制;任何重新引入的
    # 路由抑制(整段或按节)先红 test_s6_final_overlay_injects_fully_on_every_route,
    # 须经 owner 重新决策。``query`` 参数保留:路由感知的观察/演进入口。

    # ── Fast path: read cron-cached overlay ──────────────────────────
    cached_path = roots.memory_os_root / "system" / "state_overlay" / "current.json"
    overlay: dict[str, Any] | None = None
    if cached_path.exists():
        try:
            import json as _json
            overlay = _json.loads(cached_path.read_text(encoding="utf-8"))
        except Exception:
            overlay = None  # fall through to rebuild
    if overlay is not None and str(current_task_anchor or "").strip():
        try:
            _override(overlay, str(current_task_anchor))
        except Exception:
            pass  # fail-open: a broken override must not break the cache path

    # ── Slow path: rebuild overlay from canonical sources ────────────
    if overlay is None:
        try:
            overlay = _build(
                store, roots,
                current_task_anchor=str(current_task_anchor or ""),
                session_id=session_id,
                max_recent_sessions=1,  # only the most recent — avoids duplicating other sections
            )
        except Exception:
            return []  # fail-open — must never block prefetch

    # Suppress overlay when no section has any data — an empty overlay
    # must not consume prefetch budget or pollute context.
    if not _overlay_has_data(overlay, OVERLAY_SECTION_FIELDS):
        return []
    try:
        md = _render(overlay)
    except Exception:
        return []  # fail-open — must never block prefetch
    if not md.strip():
        return []
    lines = md.splitlines()
    if lines and lines[0].strip() == "### Memory State Overlay":
        lines = lines[1:]
    return lines


def _current_task_anchor_lines(anchor: str | None) -> list[str]:
    if not anchor:
        return []
    text = _redact(_clip_multiline(str(anchor), 500))
    info_lines: list[str] = []
    completed_ops: list[str] = []
    active_ops: list[str] = []
    response_rule_line = ""
    section: str = "info"  # info | completed_ops | active_ops
    for line in text.splitlines():
        clean = line.strip()
        if not clean or clean.startswith("###"):
            continue
        formatted = clean if clean.startswith("-") else f"- {clean}"
        # Always preserve the response/compression rule line — it is the
        # compression survival instruction and must never be clipped.
        if formatted.startswith("- response rule:") or formatted.startswith(
            "- compression rule:"
        ):
            response_rule_line = formatted
            continue
        # Section headers switch the parser state but are not emitted
        # themselves — the ops they label are already self-describing
        # (tool:/assistant: prefix) and the header text is recoverable
        # boilerplate.
        if formatted.startswith("- completed operations"):
            section = "completed_ops"
            continue
        if formatted.startswith("- active tool/process state:"):
            section = "active_ops"
            continue
        if section == "completed_ops":
            completed_ops.append(formatted)
        elif section == "active_ops":
            active_ops.append(formatted)
        else:
            info_lines.append(formatted)
    # Independent caps: task-info lines (max 4), completed ops (max 4).
    # Active ops are already bounded by _format_current_task_anchor (max 4).
    # The response/compression rule is always appended so it is never
    # silently dropped regardless of how many fields the anchor carries.
    result = info_lines[:4] + completed_ops[-4:] + active_ops
    if response_rule_line:
        result.append(response_rule_line)
    return result


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


def _working_lines(
    store: MemoryOSStore,
    *,
    query: str = "",
    source_ids: list[str] | None = None,
) -> list[str]:
    """Working-memory disclosure lines.

    ``source_ids`` is an optional out-parameter (same idiom as ``seen`` and
    ``error_records`` elsewhere in this module): when provided it is filled with
    the canonical ``working:<file_stem>:<item_id>`` reference for every emitted
    item, so the memory_sources disclosure record can name what it drew from.
    Populating it is required for attribution health (the attributable-class set
    lives on the audit side; not named here because the X.3 firewall forbids this
    module from referencing that layer). The end-to-end guard is
    test_real_prefetch_leaves_no_attribution_gap, not this signature, because an
    optional out-param cannot force a caller to pass it.
    """
    lines: list[str] = []
    query_features = _bounded_query_features(query)
    query_terms = {
        str(term).lower()
        for term in query_features.get("specific_terms", [])
        if str(term).strip()
    }
    query_trigrams = _text_trigrams(query)
    # F-1 guard: low/zero-feature queries retain the historical recency behavior.
    relevance_gate_enabled = bool(query_terms or query_trigrams)
    for path in sorted(store.roots.working_root.glob("*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        # Collect non-expired items, sort by recency, cap per file
        candidates: list[tuple[dict, str]] = []
        for item in document.get("items", []):
            if not isinstance(item, dict):
                continue
            if item.get("status") == "expired":
                continue
            text = _redact(_clip(str(item.get("text", "")), 220))
            if _is_diagnostic_style_seed(text):
                continue
            if relevance_gate_enabled and not _working_item_matches_query(
                text,
                query_terms=query_terms,
                query_trigrams=query_trigrams,
            ):
                continue
            if text:
                candidates.append((item, text))
        # Newest first (ISO 8601 sorts lexicographically)
        candidates.sort(key=lambda x: x[0].get("updated_at", ""), reverse=True)
        for item, text in candidates[:WORKING_ITEMS_PER_FILE]:
            lines.append(f"- {path.stem}/{item.get('kind', 'item')}: {text}")
            if source_ids is not None:
                # Canonical form already in production use at
                # deep_reflection.py:639 and allowlisted in v3_body_packet.py.
                item_id = str(item.get("id") or "").strip()
                if item_id:
                    source_ids.append(f"working:{path.stem}:{item_id}")
    return lines


def _working_item_matches_query(text: str, *, query_terms: set[str], query_trigrams: set[str]) -> bool:
    normalized = _normalize_for_overlap(text)
    expanded_terms = _expand_working_query_terms(query_terms)
    if expanded_terms and any(term in normalized for term in expanded_terms):
        return True
    if not query_trigrams:
        return False
    item_trigrams = _text_trigrams(text)
    overlap_count = len(item_trigrams & query_trigrams)
    return overlap_count >= 3 and overlap_count / max(len(query_trigrams), 1) >= 0.12


def _expand_working_query_terms(query_terms: set[str]) -> set[str]:
    expanded = set(query_terms)
    aliases = {
        "记忆": {"memory", "memory-os", "memory_os"},
        "系统": {"system", "memory-os", "memory_os"},
        "架构": {"architecture"},
        "候选": {"candidate"},
        "结晶": {"crystallized"},
        "治理": {"governance"},
    }
    for term in list(query_terms):
        expanded.update(aliases.get(term, set()))
    return expanded


def _text_trigrams(text: str) -> set[str]:
    normalized = _normalize_for_overlap(text)
    if len(normalized) < 3:
        return set()
    return {normalized[index : index + 3] for index in range(0, len(normalized) - 2)}


def _normalize_for_overlap(text: str) -> str:
    return re.sub(r"\s+", "", _redact(str(text or "")).lower())


def _relationship_lines(store: MemoryOSStore) -> list[str]:
    lines: list[str] = []
    for path in sorted(store.roots.relationships_root.glob("*.md")):
        text = _file_snippet(path)
        if text:
            lines.append(f"- {path.name}: {text}")
    return lines


# ── Deterministic Recall Floor helpers ──────────────────────────────────

def _tokenize_for_floor_match(query: str) -> list[str]:
    """Split a query into coarse tokens for deterministic substring matching.

    No external dependencies — pure Unicode boundary splitting.  Returns
    a list of non-empty, distinct, case-folded tokens suitable for
    brute-force file-body matching.
    """
    text = str(query or "").strip()
    if not text:
        return []
    # Split on Unicode punctuation / whitespace boundaries
    tokens: list[str] = []
    current: list[str] = []
    for ch in text:
        cat = unicodedata.category(ch)
        if cat.startswith("Z") or cat.startswith("P"):
            if current:
                tokens.append("".join(current))
                current = []
        else:
            current.append(ch)
    if current:
        tokens.append("".join(current))
    # Dedup preserving order; also include the full query as a fallback token
    seen: set[str] = set()
    result: list[str] = []
    full = text.casefold()
    if full not in seen:
        result.append(full)
        seen.add(full)
    for token in tokens:
        cf = token.casefold()
        if cf and cf not in seen:
            result.append(cf)
            seen.add(cf)
    return result


def _floor_match_score(path: Path, tokens: list[str], *, body_cache: dict[Path, str] | None = None, error_records: list[dict[str, Any]] | None = None) -> int:
    """Score a crystallized .md file by how many tokens appear in its body.

    Each distinct token that appears as a substring in the file body
    contributes 1 point.  The score is an integer ≥ 0 — higher = more
    relevant.  Pure deterministic computation: no LLM, no network, no
    external dependency.

    Complexity: O(N_body * |tokens|) per file — Python substring ``in``
    on the full file body.  Acceptable because (a) crystallized records
    are typically small (few KB each), (b) N is bounded by the file count
    (usually single digits in production), and (c) this only fires in the
    true fallback path (FTS5+vector both returned zero hits).

    If *body_cache* is provided, body lookups use the pre-read cache
    to avoid duplicate disk I/O when the caller also needs the raw body
    for line-building.

    Deprecated for record-level scoring: use :func:`_record_body_score`
    instead when individual records (not whole files) should be ranked.
    This function is retained for backward compatibility and for the
    :func:`_tokenize_for_floor_match` test suite.
    """
    if not tokens:
        return 0
    if body_cache is not None and path in body_cache:
        body = body_cache[path].casefold()
    else:
        try:
            body = path.read_text(encoding="utf-8").casefold()
        except Exception:
            if error_records is not None:
                error_records.append(build_error_record(
                    component="prefetch._floor_match_score",
                    operation="read_crystallized_body",
                    error_code="floor_match_read_error",
                    severity="warning",
                    recoverable=True,
                ))
            return 0
    score = 0
    for token in tokens:
        if token in body:
            score += 1
    return score


def _record_body_score(body_text: str, tokens: list[str]) -> int:
    """Score a single crystallized record body against floor-match tokens.

    Unlike :func:`_floor_match_score` which scores an entire file (giving
    large files an unfair advantage), this scores a single record's body
    text in isolation.  Each distinct token that appears as a substring
    in *body_text* contributes 1 point.

    Pure deterministic computation — no LLM, no network, no external
    dependency.  Returns an integer ≥ 0.
    """
    if not tokens or not body_text:
        return 0
    cf = body_text.casefold()
    score = 0
    for token in tokens:
        if token in cf:
            score += 1
    return score


def _rrf_union(
    fts_ids: list[str],
    vec_ids: list[str],
    *,
    k: int = 60,
    top_n: int = 60,
) -> set[str]:
    """Reciprocal Rank Fusion union of FTS5 and vector result sets.

    score = 1 / (k + rank + 1)
    Higher k reduces the impact of high rankings; k=60 is standard.

    Returns an UNORDERED set of the top_n record_ids by RRF score. RRF here
    only decides WHICH records enter the crystallized section — the caller
    uses the result purely as a membership filter (final ordering comes from
    the section builder), so set semantics are deliberate: a list would make
    the per-turn membership checks linear for zero consumer benefit.
    """
    scores: dict[str, float] = {}
    for rank, rid in enumerate(fts_ids):
        scores[rid] = scores.get(rid, 0.0) + 1.0 / (k + rank + 1)
    for rank, rid in enumerate(vec_ids):
        scores[rid] = scores.get(rid, 0.0) + 1.0 / (k + rank + 1)

    sorted_ids = sorted(scores.keys(), key=lambda rid: scores[rid], reverse=True)
    return set(sorted_ids[:top_n])


def _crystallized_lines(
    store: MemoryOSStore,
    *,
    query: str = "",
    index: object | None = None,
    seen: set[tuple[str, str]] | None = None,
    error_records: list[dict[str, Any]] | None = None,
) -> tuple[list[str], int, list[str]]:
    """Record-level crystallized memory lines with relevance filtering and caps.

    Uses FTS5 index (like Indexed Recall) to find records relevant to the
    current query, then caps output at MAX_TOTAL (20) records with at most
    MAX_PERMANENT (15) permanent and at least MAX_PROVISIONAL (5) provisional
    records — provisional always gets its reserved floor so imminent expiry
    records aren't starved by permanent volume.

    Falls back to reading all files (with caps) when the index is unavailable,
    the query is empty, or FTS5 returns zero hits (stale/missing index must not
    silently exclude on-disk records). Only records that survive the caps are
    registered in `seen` so Indexed Recall can still surface the rest.

    Provisional records (provisional=True) are annotated with countdown
    and sorted after permanent records. High-recurrence provisional records
    receive a high-recurrence marker.

    Returns (lines, degradation_level, record_ids) where:
      0 = normal (FTS5 or vector hits, relevance gate active)
      1 = mtime fallback (no search intent — empty query)
      2 = deterministic floor recall (non-empty query, FTS5+vector both
          returned zero hits; floor match scoring applied)
    record_ids = canonical IDs of records surviving the caps, formatted as
    ``crystallized:<id>`` entries for attribution closure (A1).
    """
    MAX_TOTAL = 20
    MAX_PROVISIONAL = 5
    MAX_PERMANENT = MAX_TOTAL - MAX_PROVISIONAL  # 15 — reserve floor for provisional

    now = datetime.now(timezone.utc)

    # ── FTS5 relevance lookup ──────────────────────────────────────
    route = plan_query_route(query, diagnostic_grounding_enabled=False)
    search_query = str(route.get("search_query", ""))
    relevant_ids: set[str] | None = None
    fts_ids: list[str] = []
    if index is not None and search_query and hasattr(index, "search"):
        try:
            result = index.search(search_query, limit=60)
            hits = [
                str(hit["record_id"])
                for hit in result.get("hits", [])
                if isinstance(hit, dict)
                and str(hit.get("record_type", "")) == "crystallized_record"
            ]
            fts_ids = hits
        except Exception as exc:
            if error_records is not None:
                error_records.append(
                    build_error_record(
                        component="prefetch",
                        operation="crystallized_lines",
                        error_code="prefetch_index_search_error",
                        severity="warning",
                        recoverable=True,
                        details={"error_type": type(exc).__name__},
                    )
                )

    # ── Vector similarity lane ─────────────────────────────────────
    from .knob_overrides import resolve_knob as _resolve_knob
    embedder = getattr(index, "_embedder", None)
    vec_ids: list[str] = []
    vector_enabled = _resolve_knob(
        "vector_retrieval_enabled", default=False, roots=store.roots,
    )
    if vector_enabled and embedder is not None and hasattr(embedder, "is_available") and embedder.is_available():
        qvec = embedder.embed_query(search_query) if search_query else None
        if qvec is not None and hasattr(index, "vector_search"):
            try:
                vec_ids = index.vector_search(qvec, limit=60)
            except Exception as exc:
                if error_records is not None:
                    error_records.append(
                        build_error_record(
                            component="prefetch",
                            operation="crystallized_lines",
                            error_code="prefetch_vector_search_error",
                            severity="warning",
                            recoverable=True,
                            details={"error_type": type(exc).__name__},
                        )
                    )
                vec_ids = []

    # ── RRF union + degradation level ───────────────────────────────
    degradation_level = 0
    if vec_ids:
        relevant_ids = _rrf_union(fts_ids, vec_ids, top_n=60)
    elif fts_ids:
        relevant_ids = set(fts_ids)
    else:
        # No FTS5 or vector hits — fallback path.
        # Distinguish: empty query → level 1 (pure recency, no search intent);
        # non-empty query → level 2 (deterministic floor recall with floor match).
        if search_query.strip():
            degradation_level = 2
        else:
            degradation_level = 1
    # else: leave relevant_ids=None so all on-disk records are included

    # (rid, line) for permanent, (expires_at_sort_key, rid, line, recurrence) for provisional
    permanent_entries: list[tuple[str, str, int]] = []  # (rid, line, recurrence)
    provisional_entries: list[tuple[datetime, str, str, int]] = []

    # ── File traversal ──────────────────────────────────────────────
    # When FTS5 provides relevance, sort by filename (stable, predictable).
    # When relevance is absent:
    #   - level 2 (deterministic floor recall): record-level scoring is
    #     applied *after* collecting all entries — each record body is
    #     scored individually against floor_tokens so small files with
    #     highly relevant records aren't pushed out of the cap by large
    #     files with dilute incidental matches.
    #   - level 1 (empty query / pure recency): sort by mtime descending
    paths = list(store.roots.crystallized_root.glob("*.md"))
    # Pre-read cache for degradation floor path — avoids double file I/O
    # (the same bodies serve both record-level scoring and line-building).
    body_cache: dict[Path, str] = {}
    floor_tokens: list[str] = []
    if degradation_level == 2:
        floor_tokens = _tokenize_for_floor_match(search_query)
        if floor_tokens:
            for p in paths:
                try:
                    body_cache[p] = p.read_text(encoding="utf-8")
                except Exception:
                    body_cache[p] = ""
                    if error_records is not None:
                        error_records.append(build_error_record(
                            component="prefetch._crystallized_lines",
                            operation="body_cache_pre_read",
                            error_code="body_cache_read_error",
                            severity="warning",
                            recoverable=True,
                        ))
            # Do NOT sort by file-level floor_match_score — record-level
            # scoring is applied later (see _record_body_score usage below).
        else:
            paths.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    elif relevant_ids is None:
        paths.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    else:
        paths.sort()
    for path in paths:
        # Use pre-read body from degradation floor path if available,
        # otherwise read from disk (normal FTS5/recency path).
        if body_cache and path in body_cache:
            content = body_cache[path]
        else:
            try:
                content = path.read_text(encoding="utf-8")
            except Exception:
                continue
        # Determine whether to apply record-level floor-match scoring.
        # Only active at degradation_level=2 (deterministic floor recall)
        # with non-empty tokens — otherwise behaviour is unchanged.
        record_scoring = degradation_level == 2 and bool(floor_tokens)

        for frontmatter, body in _parse_markdown_records(content):
            if not is_active_crystallized_frontmatter(frontmatter):
                continue
            rid = str(frontmatter.get("id", "")).strip()

            # FTS5 relevance gate: when the index is available and the query
            # is non-empty, only include records whose id matched the search.
            if relevant_ids is not None and rid not in relevant_ids:
                continue

            kind = str(frontmatter.get("kind", "item"))
            text = _redact(_clip(body, 220))
            if not text or _is_diagnostic_style_seed(text):
                continue

            # Record-level score at degradation level 2 — each record body
            # is scored individually so small files with relevant records
            # are not pushed out of the cap by large files (bugfix).
            rec_score = _record_body_score(body, floor_tokens) if record_scoring else 0

            is_provisional = frontmatter.get("provisional") is True
            if is_provisional:
                # Compute countdown
                expires_str = str(frontmatter.get("expires_at") or "").strip()
                days_remaining = 999
                expires_dt = datetime.max.replace(tzinfo=timezone.utc)
                if expires_str:
                    try:
                        expires_dt = datetime.fromisoformat(expires_str)
                        sec = (expires_dt - now).total_seconds()
                        days_remaining = max(0, int(sec / 86400))
                    except (ValueError, TypeError):
                        pass
                # Recurrence from frontmatter
                recurrence = 0
                try:
                    recurrence = int(frontmatter.get("recurrence", "0"))
                except (ValueError, TypeError):
                    pass
                # Build annotated line
                recurrence_marker = " ⚠high-recurrence" if recurrence >= 3 else ""
                line = (
                    f"- {path.name}/{kind}: "
                    f"(provisional·剩{days_remaining}d){recurrence_marker} {text}"
                )
                provisional_entries.append((expires_dt, rid, line, recurrence, rec_score))
            else:
                recurrence = 0
                try:
                    recurrence = int(frontmatter.get("recurrence", "0"))
                except (ValueError, TypeError):
                    pass
                permanent_entries.append((rid, f"- {path.name}/{kind}: {text}", recurrence, rec_score))

    # ── Sort entries ─────────────────────────────────────────────
    # At degradation_level=2 (deterministic floor recall), sort entries
    # by record-level score descending so query-relevant records survive
    # the cap regardless of which file they live in.  Score 0 (no token
    # match) sinks to the bottom and is truncated by the cap — this is
    # the intended behaviour: the floor is a query-aware fallback, not a
    # universal recall of every on-disk record.
    if degradation_level == 2 and floor_tokens:
        permanent_entries.sort(key=lambda e: (-e[3], e[0]))
        provisional_entries.sort(key=lambda e: (-e[4], e[0]))
    else:
        # Sort provisional entries: closest expiry first
        provisional_entries.sort(key=lambda e: e[0])
        # At degradation_level=1 (empty query, pure recency), sort permanent
        # entries by recurrence descending so the most-recurrent records
        # survive the per-class cap (MAX_PERMANENT=15).
        if degradation_level == 1 and permanent_entries:
            permanent_entries.sort(key=lambda e: (-e[2], e[0]))

    # ── Apply caps and track seen only for surviving records ──────
    result: list[str] = []
    record_ids: list[str] = []
    # Cap permanent records at MAX_PERMANENT (15) — reserve floor for provisional
    for rid, line, _recurrence, _score in permanent_entries[:MAX_PERMANENT]:
        result.append(line)
        record_ids.append(f"crystallized:{rid}")
        if seen is not None and rid:
            seen.add(("crystallized_record", rid))

    # Cap provisional records: at least MAX_PROVISIONAL (5), more if
    # permanent didn't fill its MAX_PERMANENT allocation.
    remaining_slots = MAX_TOTAL - len(result)
    for _, rid, line, _, _score in provisional_entries[:max(MAX_PROVISIONAL, remaining_slots)]:
        result.append(line)
        record_ids.append(f"crystallized:{rid}")
        if seen is not None and rid:
            seen.add(("crystallized_record", rid))

    return result, degradation_level, record_ids


def _candidate_lines(
    store: MemoryOSStore,
    *,
    query: str,
    seen: set[tuple[str, str]] | None = None,
    source_ids: list[str] | None = None,
) -> list[str]:
    # A magic word ("candidate", "结晶", "review queue", ...) is an explicit
    # "show me the review queue" request and always lists the queue
    # (unchanged behavior). Absent a magic word, a candidate is still
    # allowed to surface when it is genuinely relevant to the query — the
    # relevance floor below.
    #
    # Matching machinery reused: _extract_query_tokens (query -> tokens) +
    # _record_body_score (score one record body in isolation). Considered
    # _tokenize_for_floor_match first since it is _record_body_score's usual
    # partner in _crystallized_lines, but that pairing is a *soft* rank
    # (score-0 records sink and only drop out via a cap truncation) and its
    # tokenizer emits single-character tokens on punctuation boundaries
    # (e.g. "what's" -> "s"), which trivially substring-matches almost any
    # body and defeats a *hard* include/exclude gate — verified empirically:
    # an unrelated query ("What's the weather forecast for tomorrow?")
    # still matched via the stray "s" token. _extract_query_tokens is the
    # other mixed-language tokenizer already in this file (used for
    # cross-session event relevance above) and drops ASCII tokens under 3
    # chars plus stop words, so it doesn't produce that noise. Paired with
    # _record_body_score — which scores a single record body in isolation,
    # exactly the candidate-record shape — this is the closest existing fit
    # for a strict gate; no new scorer is introduced.
    #
    # Threshold: require >=2 distinct token hits, not >=1. _extract_query_tokens
    # emits overlapping CJK bigrams with no stop-word filter (unlike its ASCII
    # side), and a single shared bigram is often pure grammar noise (的/是/在-
    # style function words such as "什么"/"我们"/"这个") rather than topical
    # overlap — verified empirically: query "我们什么时候开会？" (meeting time)
    # scored 1 against an unrelated candidate body about a feature-confusion
    # report purely via the shared bigram "什么". Genuine topical overlap
    # reliably produces >=2 hits because a real shared multi-character word
    # contributes multiple overlapping bigrams (e.g. "日本旅行" shared between
    # query and body scored 4). The >=2 floor also holds for the ASCII case
    # this was built against (score 3 for "about"/"memory"/"continuity").
    RELEVANCE_FLOOR_MIN_SCORE = 2
    magic_word_match = _should_include_candidates(query)
    relevance_tokens: list[str] = [] if magic_word_match else _extract_query_tokens(query)
    if not magic_word_match and not relevance_tokens:
        return []
    lines: list[str] = []
    for candidate in read_candidate_queue(store.roots)[:5]:
        if not magic_word_match and _record_body_score(
            str(candidate.body or ""), relevance_tokens
        ) < RELEVANCE_FLOOR_MIN_SCORE:
            # Conservative relevance floor: fewer than 2 distinct token hits
            # => no line. Never emit an unmatched candidate as filler.
            continue
        text = _redact(_clip(candidate.body, 180))
        if _is_diagnostic_style_seed(text):
            continue
        if text:
            lines.append(
                "- candidate only / review candidate; not approved crystallized memory: "
                f"{candidate.candidate_id} {candidate.kind}: {text}"
            )
            if seen is not None:
                seen.add(("crystallized_candidate", candidate.candidate_id))
            if source_ids is not None and candidate.candidate_id:
                source_ids.append(f"candidate:{candidate.candidate_id}")
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


def _event_lines(
    store: MemoryOSStore,
    *,
    session_id: str = "",
    seen: set[tuple[str, str]] | None = None,
    source_ids: list[str] | None = None,
    events: list[Any] | None = None,
) -> list[str]:
    # When session-scoped: use pure recency sort (_select_session_events).
    # This prioritizes temporal proximity within a single session over
    # source-class diversity (foreground:2, cron:1, mailbox:1, etc. from
    # _select_continuity_events). The tradeoff is intentional: within one
    # session, the user cares most about what just happened, and extreme
    # source-class imbalance is rare in normal session loads.
    if session_id:
        selected = _select_session_events(store, session_id, events=events)
    else:
        selected, _dropped = _select_continuity_events(store, events=events)
    selected = sorted(selected, key=lambda e: (e.ts, e.id))  # chronological order for display
    lines: list[str] = []
    for event in selected:
        if _is_diagnostic_style_seed(str(event.summary)):
            continue
        lines.append(f"- {_event_source_class(event)}/{event.kind}: {_redact(_clip(event.summary, 220))}")
        if seen is not None and event.id:
            seen.add(("event", event.id))
        if source_ids is not None and event.id:
            source_ids.append(f"event:{event.id}")
    return lines


def _collect_anchor_ids(query: str, index: object | None) -> list[str]:
    """从第一跳 FTS5 召回结果中提取 record_id,作为第二跳图遍历的 anchor。

    Anchor 靠内容匹配(搜索)产生,遍历靠 id。空查询/无 index → 返回 []。
    与 _indexed_lines 使用相同的 plan_query_route 派生 search_query。
    在生产中,与 _indexed_lines 各调一次 index.search()(FTS5 微秒级,可忽略)。
    Mock index 追踪查询次数时,注意搜索次数因 Shadow 区块增加一次。
    """
    if not query or not query.strip() or index is None:
        return []
    if not hasattr(index, "search"):
        return []
    route = plan_query_route(query, diagnostic_grounding_enabled=False)
    search_query = str(route.get("search_query", "")).strip()
    if not search_query:
        return []

    def _hits_of(term: str, *, limit: int, record_type: str | None = None) -> list[str]:
        try:
            if record_type is None:
                result = index.search(term, limit=limit)
            else:
                result = index.search(term, limit=limit, record_type=record_type)
        except Exception:
            return []
        found: list[str] = []
        for hit in (result.get("hits", []) if isinstance(result, dict) else []):
            if not isinstance(hit, dict):
                continue
            rid = str(hit.get("record_id", "")).strip()
            if rid:
                found.append(rid)
        return found

    # E8b:结晶限定段优先 — FTS 通用命中被事件量级淹没(生产实测 top 8
    # 清一色 event),而边密度在结晶层;锚点池 = 结晶命中(前)∪ 通用命中,
    # cap 5。旧 index/mock 不支持 record_type 时 fail-open 降级为空段。
    crystallized_ids = _hits_of(
        search_query, limit=2, record_type="crystallized_record",
    )
    ids = _hits_of(search_query, limit=5)
    merged = _dedupe(crystallized_ids + ids)[:5]
    if merged:
        return merged

    # ── E8 回退(2026-08-07 生产实锤)────────────────────────────────
    # 派生的多词 search_query 在 FTS AND 语义下经常 0 命中(实测
    # 'Memory-OS Hermes' 两词单查各 5 命中、AND 交集 0),而
    # plan_query_route 的 `entities or chinese_keywords` 短路又把中文
    # 实词整体丢弃 — 双重作用下锚点恒空,图谱一跳展开永不触发
    # (shadow 月命中仅 4 条的根因)。回退:①派生词逐词并集;②仍空则
    # 用中文关键词表匹配原 query 逐词并集。全程有界:词 ≤6、每词
    # limit 3、锚点 ≤5。只改锚点收集,不碰全局共享的 plan_query_route。
    # 派生词逐词(单词派生无 AND 问题,重查等于原查询,跳过)…
    derived_terms = [t for t in search_query.split() if t]
    if len(derived_terms) <= 1:
        derived_terms = []
    # …加上被 entities 短路丢弃的中文关键词(仅用于锚点回退)
    effective_keywords = (
        _fast_path_keywords_override
        if _fast_path_keywords_override is not None
        else _FAST_PATH_CHINESE_KEYWORDS
    )
    redacted = _redact(" ".join(str(query).split()))
    chinese_terms = [
        kw for kw in effective_keywords
        if kw in redacted and kw not in _FAST_PATH_STOP_WORDS
    ]
    fallback_terms = _dedupe(derived_terms + chinese_terms)[:6]
    # 回退同样双段:结晶限定段先收(独立池,防被事件填满),通用段后补。
    crystallized_pool: list[str] = []
    general_pool: list[str] = []
    for term in fallback_terms:
        if len(crystallized_pool) + len(general_pool) >= 10:
            break
        for rid in _hits_of(term, limit=2, record_type="crystallized_record"):
            if rid not in crystallized_pool:
                crystallized_pool.append(rid)
        for rid in _hits_of(term, limit=3):
            if rid not in general_pool:
                general_pool.append(rid)
    return _dedupe(crystallized_pool + general_pool)[:5]


# W3 词表守卫锚点:图谱注入只消费此状态的边;owner approve(active 化)
# 是它的生产者。与 EDGE_STATE_TRANSITIONS / EDGE_REVIEW_DIGEST_STATE /
# PROMOTION_TARGET_STATE 一起被双向守卫测试钉死。
GRAPH_INJECTION_EDGE_STATE = "active"

# 图谱注入行的方向敏感关系短语表(主语固定为锚点侧)。Module 级:短语词表
# 必须能被守卫测试对照 producer 实际产出的 relation_type 全集双向校验——
# 词表与 producer 漂移的 gate 什么也不检查(CLAUDE.md「词表漂移」教训)。
GRAPH_RELATION_PHRASES: dict[tuple[str, str], str] = {
    ("co_occurs", "anchor_is_from"): "同源共现于",
    ("co_occurs", "anchor_is_to"): "同源共现于",
    ("depends_on", "anchor_is_from"): "依赖于",
    ("depends_on", "anchor_is_to"): "被以下内容依赖",
    ("refines", "anchor_is_from"): "细化了",
    ("refines", "anchor_is_to"): "被以下内容细化",
    ("evidence_for", "anchor_is_from"): "佐证了",
    ("evidence_for", "anchor_is_to"): "其证据为",
    ("contradicts", "anchor_is_from"): "与以下内容冲突",
    ("contradicts", "anchor_is_to"): "与以下内容冲突",
}
# 未知 relation_type 的兜底短语(方向无关)。
GRAPH_FALLBACK_PHRASE = "关联于"

# 注入的权重噪声下限。出生权重分层后这是不设防的安全底线(守卫测试钉
# min(出生权重) >= 此值),真实排序依赖权重本身,不依赖它。
GRAPH_INJECTION_WEIGHT_FLOOR = 0.3
GRAPH_MAX_LINES = 8
GRAPH_ANCHOR_PREVIEW_CHARS = 12
# 跨段去重命中的短预览长度:是结晶段同一正文 220 字符裁剪的精确前缀,
# 对阅读方 LLM 是零歧义对齐键(比 record_id 可靠——其它区段不显示 id)。
GRAPH_DEDUP_PREVIEW_CHARS = 60

_GRAPH_CRYSTALLIZED_TYPES = frozenset({"crystallized_record", "crystallized"})


def _graph_layer_shadow_lines(
    store: MemoryOSStore,
    anchor_ids: list[str],
    *,
    index: object | None = None,
    seen: set[tuple[str, str]] | None = None,
    source_ids: list[str] | None = None,
    events: list[Any] | None = None,
) -> list[str]:
    """Knob-gated graph layer edge injection with shadow audit.

    Knob disabled: writes candidate edges to system/graph_layer_shadow.jsonl
    for audit and returns []. Knob enabled: renders direction-normalized,
    human-readable Related Memory lines (see _render_graph_layer_lines).
    Shadow log is written regardless.

    Rules:
    - anchor_ids: 第一跳选出的 record_id 集合(来自 FTS5 hit)
    - 委托 MemoryOSIndex.query_edges() 查询
    - depth=1 (一跳,守 §5a)
    - state='active'
    - 不打断 main prefetch 路径(fail-open: 查询出错返回 [])
    - anchor_ids 为空 → 直接返回 [] (空 shadow 是诚实信号)
    - Config gate: graph_layer_injection_enabled knob (default=False)
    - Cross-section dedup via `seen` set
    - events: 调用方的 events 缓存,用于事件类锚点/邻居的预览解析
    """
    if not anchor_ids:
        return []
    if index is None or not hasattr(index, "query_edges"):
        return []
    try:
        edges = index.query_edges(anchor_ids, depth=1, state=GRAPH_INJECTION_EDGE_STATE, limit=8)
    except Exception:
        return []
    if not edges:
        return []

    # ── Shadow log ALWAYS written (audit trail) ─────────────────
    _record_graph_layer_shadow(store, anchor_ids, edges)

    # ── Knob gate ──────────────────────────────────────────────
    from .knob_overrides import resolve_knob as _resolve_knob
    injection_enabled = _resolve_knob(
        "graph_layer_injection_enabled",
        default=False,
        roots=store.roots,
    )
    if not injection_enabled:
        return []

    lines, _decisions = _render_graph_layer_lines(
        store,
        edges,
        anchor_ids=anchor_ids,
        seen=seen,
        source_ids=source_ids,
        events=events,
    )
    return lines


def _batch_resolve_crystallized(
    store: MemoryOSStore,
    record_ids: set[str] | list[str],
) -> dict[str, Any]:
    """Resolve a bounded id set in ONE pass over the crystallized store.

    逐 id 调 CrystallizedMemoryService.find_record 会对每个 id 重新 glob 全部
    结晶文件(热路径最坏 2×8 次全量扫描);这里一次遍历建 {id: record} 映射,
    预览解析与 inactive 判定共用同一份 record。fail-open:异常返回已收集的
    部分映射。
    """
    wanted = {str(r).strip() for r in record_ids if str(r or "").strip()}
    found: dict[str, Any] = {}
    if not wanted:
        return found
    try:
        svc = CrystallizedMemoryService(store)
        root = store.roots.crystallized_root
        if not root.exists():
            return found
        for path in sorted(root.glob("*.md")):
            for record in svc.read_records(path.name):
                rid = str(record.frontmatter.get("id") or "")
                if rid in wanted and rid not in found:
                    found[rid] = record
            if len(found) == len(wanted):
                break
    except Exception:
        return found
    return found


def _graph_preview(
    record_id: str,
    record_type: str,
    cry_map: dict[str, Any],
    event_summaries: dict[str, str],
) -> tuple[str | None, str]:
    """Resolve a graph edge endpoint to ``(redacted_preview, status)``.

    status ∈ {"ok", "inactive", "missing"}。结晶记录走批量映射(inactive 与
    missing 可区分),事件走调用方 events 缓存;其余一律 missing(fail-open)。
    """
    normalized = str(record_id or "").strip()
    if not normalized:
        return None, "missing"
    record = cry_map.get(normalized)
    if record is not None:
        try:
            if not is_active_crystallized_frontmatter(record.frontmatter):
                return None, "inactive"
            text = _redact(_clip(str(record.body or ""), 220))
            if not text or _is_diagnostic_style_seed(text):
                return None, "missing"
            return text, "ok"
        except Exception:
            return None, "missing"
    summary = event_summaries.get(normalized, "")
    if summary:
        text = _redact(_clip(summary, 220))
        if text and not _is_diagnostic_style_seed(text):
            return text, "ok"
    return None, "missing"


def _render_graph_layer_lines(
    store: MemoryOSStore,
    edges: list[dict],
    *,
    anchor_ids: list[str],
    seen: set[tuple[str, str]] | None = None,
    source_ids: list[str] | None = None,
    events: list[Any] | None = None,
) -> tuple[list[str], list[dict]]:
    """Render graph edges as owner-readable Related Memory lines.

    行文法(F1/P2 2026-08-07):方向归一 + 中文自然语言短语 + 锚点短预览:

        - 「{锚点预览}」{关系短语}:{邻居正文预览}({已列出·}关联度 {w:.2f})

    规则:
    - 方向归一:展示目标永远是边上非锚点的一端(neighbor)。旧实现无条件取
      to_record_id — 当边是「X→锚点」时会把锚点自己当"关联记忆"展示,且
      depends_on 的方向语义读反。
    - 永不打印 record_id:解析失败整行丢弃(诊断归 shadow 账本的 outcome,
      不进 agent 上下文 — 旧 [unresolved:id] 行会诱导 LLM 编造引用)。
    - 跨段去重命中不丢行(继承 E8c):降级为 60 字符短预览 + 「已列出·」
      标记 — 短预览是结晶段同一正文的精确前缀,零歧义对齐键。
    - 同一 (锚点,邻居) 的多条边聚合为一行,短语「、」连接,关联度取最大。
    - 每行 ≤220 字符、最多 GRAPH_MAX_LINES 行、weight < FLOOR 跳过。
    - 返回 (lines, decisions):decisions 给每条边一个封闭 outcome
      (emitted_full / emitted_stub / below_weight_floor / target_inactive /
      non_crystallized_target / unresolved / not_selected),供 shadow 账本
      区分「注入」与「查到但未注入」。
    """
    anchor_set = {str(a).strip() for a in anchor_ids if str(a or "").strip()}
    decisions: list[dict] = []

    # ── 1. 方向归一 + 权重下限 ─────────────────────────────────────
    workable: list[dict] = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        from_id = str(edge.get("from_record_id") or "").strip()
        to_id = str(edge.get("to_record_id") or "").strip()
        if not from_id or not to_id:
            continue
        weight = float(edge.get("weight", 1.0))
        if weight < GRAPH_INJECTION_WEIGHT_FLOOR:
            decisions.append(
                {"edge": edge, "injected": False, "outcome": "below_weight_floor"}
            )
            continue
        if to_id in anchor_set and from_id not in anchor_set:
            direction = "anchor_is_to"
            anchor_id, anchor_type = to_id, str(edge.get("to_record_type") or "")
            neighbor_id, neighbor_type = from_id, str(edge.get("from_record_type") or "")
        else:
            # 锚点在 from 侧;两端皆锚点或(防御)两端皆非锚点时同样取 to 为
            # 展示目标 — 行仍表达「两条已知记忆相关」这一图谱独有信息。
            direction = "anchor_is_from"
            anchor_id, anchor_type = from_id, str(edge.get("from_record_type") or "")
            neighbor_id, neighbor_type = to_id, str(edge.get("to_record_type") or "")
        workable.append({
            "edge": edge,
            "weight": weight,
            "direction": direction,
            "anchor_id": anchor_id,
            "anchor_type": anchor_type,
            "neighbor_id": neighbor_id,
            "neighbor_type": neighbor_type,
        })

    if not workable:
        return [], decisions

    # ── 2. 预览源批量解析(一次结晶扫描 + events 缓存)────────────────
    preview_ids: set[str] = set()
    for item in workable:
        preview_ids.add(item["anchor_id"])
        preview_ids.add(item["neighbor_id"])
    cry_map = _batch_resolve_crystallized(store, preview_ids)
    event_summaries: dict[str, str] = {}
    for ev in events or []:
        try:
            ev_id = str(getattr(ev, "id", "") or "")
            if ev_id and ev_id in preview_ids:
                event_summaries[ev_id] = str(getattr(ev, "summary", "") or "")
        except Exception:
            continue

    # ── 3. 按 (锚点,邻居) 聚合 ─────────────────────────────────────
    groups: dict[tuple[str, str], dict] = {}
    for item in workable:
        key = (item["anchor_id"], item["neighbor_id"])
        group = groups.setdefault(key, {
            "anchor_id": item["anchor_id"],
            "anchor_type": item["anchor_type"],
            "neighbor_id": item["neighbor_id"],
            "neighbor_type": item["neighbor_type"],
            "phrases": [],
            "weight": 0.0,
            "items": [],
        })
        phrase = GRAPH_RELATION_PHRASES.get(
            (str(item["edge"].get("relation_type") or ""), item["direction"]),
            GRAPH_FALLBACK_PHRASE,
        )
        if phrase not in group["phrases"]:
            group["phrases"].append(phrase)
        group["weight"] = max(group["weight"], item["weight"])
        group["items"].append(item)

    # ── 4. 渲染 ────────────────────────────────────────────────────
    lines: list[str] = []
    for group in groups.values():
        if len(lines) >= GRAPH_MAX_LINES:
            for item in group["items"]:
                decisions.append(
                    {"edge": item["edge"], "injected": False, "outcome": "not_selected"}
                )
            continue

        n_text, n_status = _graph_preview(
            group["neighbor_id"], group["neighbor_type"], cry_map, event_summaries,
        )
        if n_status != "ok" or not n_text:
            if n_status == "inactive":
                # Revoked/demoted canonical targets are fully suppressed.
                outcome = "target_inactive"
            elif group["neighbor_type"] in _GRAPH_CRYSTALLIZED_TYPES:
                outcome = "unresolved"
            else:
                # W4: 非结晶目标(事件等)按保留策略淡出热存储,解析失败的
                # 标识符行是纯噪声,不是诊断。
                outcome = "non_crystallized_target"
            for item in group["items"]:
                decisions.append(
                    {"edge": item["edge"], "injected": False, "outcome": outcome}
                )
            continue

        a_text, a_status = _graph_preview(
            group["anchor_id"], group["anchor_type"], cry_map, event_summaries,
        )
        if a_status == "ok" and a_text:
            anchor_label = _clip(a_text, GRAPH_ANCHOR_PREVIEW_CHARS)
        elif group["anchor_type"] == "event":
            anchor_label = "近期事件"
        else:
            anchor_label = "相关记忆"

        dedup_hit = (
            seen is not None
            and (group["neighbor_type"], group["neighbor_id"]) in seen
        )
        prefix = f"- 「{anchor_label}」{'、'.join(group['phrases'])}:"
        suffix = f"({'已列出·' if dedup_hit else ''}关联度 {group['weight']:.2f})"
        body_budget = max(40, 220 - len(prefix) - len(suffix))
        if dedup_hit:
            body_budget = min(body_budget, GRAPH_DEDUP_PREVIEW_CHARS)
        lines.append(prefix + _clip(n_text, body_budget) + suffix)

        outcome = "emitted_stub" if dedup_hit else "emitted_full"
        for item in group["items"]:
            decisions.append({"edge": item["edge"], "injected": True, "outcome": outcome})
        if seen is not None:
            seen.add((group["neighbor_type"], group["neighbor_id"]))
        if source_ids is not None:
            source_ids.append(f"{group['neighbor_type']}:{group['neighbor_id']}")

    return lines, decisions


def _record_graph_layer_shadow(
    store: MemoryOSStore,
    anchor_ids: list[str],
    edges: list[dict],
) -> None:
    """Append a bounded shadow record to system/graph_layer_shadow.jsonl.

    Matches the SubstrateRecall shadow-log pattern but for graph edges.
    This is purely audit/inspection data — NOT injected into agent context.
    """
    path = store.roots.memory_os_root / "system" / "graph_layer_shadow.jsonl"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        return  # fail-open: shadow loss must not break prefetch
    _now_stamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    record = {
        "schema_version": "memory-os.graph_layer_shadow.v0",
        "phase": "1",
        "anchor_count": len(anchor_ids),
        "edge_count": len(edges),
        # created_at is the name metadata_retention._record_created_at ages on
        # (backlog 9); recorded_at stays for existing readers of this ledger.
        # Forward-only: historical recorded_at-only rows remain unaged -- an
        # owner decision, recorded in the backlog.
        "created_at": _now_stamp,
        "recorded_at": _now_stamp,
        "edges": [
            {
                "relation_type": str(edge.get("relation_type", "unknown")),
                "from_record_type": str(edge.get("from_record_type", "")),
                "from_record_id": str(edge.get("from_record_id", "")),
                "to_record_type": str(edge.get("to_record_type", "")),
                "to_record_id": str(edge.get("to_record_id", "")),
                "weight": float(edge.get("weight", 1.0)),
            }
            for edge in edges
            if isinstance(edge, dict)
        ],
    }
    try:
        from .jsonl_io import append_jsonl_locked
        append_jsonl_locked(path, record)
    except Exception:
        pass  # fail-open: shadow loss must not break prefetch


def _last_session_lines(
    store: MemoryOSStore,
    *,
    session_id: str = "",
    seen: set[tuple[str, str]] | None = None,
) -> list[str]:
    """Read the most recent non-current session anchor.

    Scans ``last_session_anchor.jsonl``, selects the anchor with the latest
    ``ended_at`` whose ``session_id`` differs from the current session.
    Returns a single-line injection or empty list (fail-open).

    The returned line uses a factual-tone marker ("上一次会话") — never
    the "[跨会话·待结晶]" marker used by Recent Cross-Session.
    """
    if not session_id:
        return []

    path = store.roots.memory_os_root / "system" / "last_session_anchor.jsonl"
    if not path.exists():
        return []

    now = datetime.now(timezone.utc)
    best: tuple[datetime, dict[str, Any]] | None = None

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        # Exclude current session's own anchor
        if str(record.get("session_id", "")) == session_id:
            continue
        foreground = str(record.get("foreground_summary", "")).strip()
        if not foreground:
            continue
        try:
            ended_at = datetime.fromisoformat(str(record.get("ended_at", "")))
        except (ValueError, TypeError):
            continue
        if best is None or ended_at > best[0]:
            best = (ended_at, record)

    if best is None:
        return []

    ended_ts, record = best
    foreground_summary = str(record.get("foreground_summary", ""))
    age_h = max(1, int((now - ended_ts).total_seconds() / 3600))

    # Session-level dedup marker: signals to downstream sections that this
    # session's content has been summarized as a session-level anchor.
    if seen is not None:
        seen.add(("last_session", str(record.get("session_id", ""))))

    return [f"- 上一次会话({age_h}h前): {_redact(foreground_summary)}"]


def _recent_cross_session_lines(
    store: MemoryOSStore,
    *,
    session_id: str = "",
    max_items: int = 5,
    max_age_hours: int = 48,
    error_records: list[dict[str, Any]] | None = None,
    seen: set[tuple[str, str]] | None = None,
    query: str = "",
    events: list[Any] | None = None,
) -> list[str]:
    """Source-gate-passed events from recent sessions (not current).

    Bridges the gap between working memory decay (~hours) and crystallized
    availability (~7 days). Only includes events that passed source gate
    (have a corresponding candidate in candidates.jsonl), are from a
    different session, and are within the recency window.

    When *query* is non-empty, collected events are ranked by token overlap
    with the query (soft boost) — events that share terms with the current
    task float to the top, reducing cross-session noise.

    Each line carries a "[跨会话·待结晶]" marker so the agent knows this
    is not yet owner-confirmed memory.
    """
    if not session_id:
        return []

    from .knob_overrides import resolve_knobs as _resolve_knobs

    # Defaults must match the function signature (max_items=5, max_age_hours=48).
    # The function-parameter values are fallbacks used when a knob override
    # cannot be coerced to int (e.g. hand-edited JSONL with non-numeric value).
    resolved = _resolve_knobs(
        {
            "recent_cross_session_enabled": True,
            "recent_cross_session_max_items": 5,
            "recent_cross_session_max_age_hours": 48,
        },
        roots=store.roots,
    )
    if not resolved["recent_cross_session_enabled"]:
        return []

    def _safe_int_knob(value: Any, fallback: int) -> int:
        """Coerce a knob override value to int with floor of 1.

        Guards against non-numeric or None override values (e.g. from
        hand-edited JSONL); falls back to *fallback* on any coercion error.
        An explicit override of 0 is floored to 1 (the knob's minimum).
        """
        try:
            return max(int(value), 1)
        except (ValueError, TypeError):
            return max(int(fallback), 1)

    limit = _safe_int_knob(resolved["recent_cross_session_max_items"], max_items)
    age_hours = _safe_int_knob(resolved["recent_cross_session_max_age_hours"], max_age_hours)

    # Collect source_event_ids from candidates.jsonl — these are the
    # source-gate signature: only events that passed source gate have
    # a corresponding candidate record.
    candidates_path = store.roots.crystallized_root / "candidates.jsonl"
    source_gate_passed_ids: set[str] = set()
    if candidates_path.exists():
        try:
            for line in candidates_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(rec, dict):
                    continue
                for eid in rec.get("source_event_ids", []):
                    eid_str = str(eid).strip()
                    if eid_str:
                        source_gate_passed_ids.add(eid_str)
        except Exception:
            if error_records is not None:
                error_records.append(
                    build_error_record(
                        component="prefetch",
                        operation="recent_cross_session_lines",
                        error_code="candidates_read_error",
                        severity="warning",
                        recoverable=True,
                    )
                )

    if not source_gate_passed_ids:
        return []

    # Read events, filter to cross-session + source-gate-passed + recent
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=age_hours)
    collected: list[tuple[datetime, str]] = []

    for event in (events if events is not None else store.read_events()):
        eid = str(event.id).strip()
        if eid not in source_gate_passed_ids:
            continue
        # Dedup: skip events already injected by Continuity Bridge (earlier section)
        if seen is not None and eid and ("event", eid) in seen:
            continue
        event_session = str((event.safe_ref or {}).get("session_id", ""))
        if event_session == session_id:
            continue
        try:
            ts = datetime.fromisoformat(str(event.ts))
        except (ValueError, TypeError):
            continue
        if ts < cutoff:
            continue
        summary = _clip(str(event.summary), 180)
        if not summary.strip() or _is_diagnostic_style_seed(summary):
            continue
        if seen is not None and eid:
            seen.add(("event", eid))
        collected.append((ts, summary))

    if not collected:
        return []

    collected.sort(key=lambda x: x[0], reverse=True)

    # ── Query-aware soft ranking ──────────────────────────────────────
    # When the caller passes a non-empty query, boost events whose summary
    # shares tokens with the current task.  This keeps the section narrower
    # and more relevant without dropping events entirely when there's no
    # overlap (no-overlap items still appear after overlap items).
    if query and len(collected) > 1:
        query_tokens = _extract_query_tokens(query)
        if query_tokens:
            scored: list[tuple[int, datetime, str]] = []
            for ts, summary in collected:
                summary_lower = summary.lower()
                score = sum(1 for token in query_tokens if token in summary_lower)
                scored.append((score, ts, summary))
            # Stable sort: higher score first, then newer first within same score
            scored.sort(key=lambda x: (-x[0], x[1]), reverse=False)
            collected = [(ts, s) for _, ts, s in scored]

    lines: list[str] = []
    for ts, summary in collected[:limit]:
        age_h = max(1, int((now - ts).total_seconds() / 3600))
        lines.append(
            f"- [跨会话·待结晶·{age_h}h前] {_redact(summary)}"
        )

    lines.insert(0, "— 近期跨会话 (source gate 通过, 待 owner 结晶) —")
    return lines


def _continuity_bridge_lines(
    store: MemoryOSStore,
    *,
    session_id: str = "",
    seen: set[tuple[str, str]] | None = None,
    events: list[Any] | None = None,
) -> list[str]:
    selected, _dropped = _select_continuity_events(
        store, exclude_session_id=session_id or None, events=events
    )
    if not selected:
        return []
    # NOTE: "此前会话" (Previous Sessions) marker appears even when session
    # scoping is disabled (session_id=""). In that mode, _select_continuity_events
    # returns cross-session events without exclusion, which is the pre-existing
    # behavior. The marker is accurate: these ARE prior-session events.
    lines = ["— 此前会话 —"]
    for event in selected:
        if _event_source_class(event) not in {"cron", "mailbox", "room_family", "state_source", "governance"}:
            continue
        # Dedup: skip events already injected by earlier sections
        if seen is not None and event.id:
            key = ("event", event.id)
            if key in seen:
                continue
            seen.add(key)
        lines.append(
            f"- {_event_source_class(event)}/{event.kind}: "
            f"{_redact(_clip(event.summary, 220))}"
        )
    if len(lines) == 1:
        # Only the marker, no filtered events survived
        return []
    return lines


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


def _select_continuity_events(
    store: MemoryOSStore,
    *,
    exclude_session_id: str | None = None,
    events: list[Any] | None = None,
) -> tuple[list[Any], list[Any]]:
    # *events* lets the per-turn caller share one canonical scan across
    # sections; None (the default) self-scans, preserving standalone behavior.
    source = events if events is not None else store.read_events()
    events = sorted(source, key=lambda event: (event.ts, event.id), reverse=True)
    if exclude_session_id is not None:
        events = [e for e in events
                  if str((e.safe_ref or {}).get("session_id", "")) != exclude_session_id]
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


def _select_session_events(
    store: MemoryOSStore,
    session_id: str,
    *,
    events: list[Any] | None = None,
) -> list[Any]:
    """Return events for *session_id*, ts-descending, capped at _MAX_CONTINUITY_RECORDS.

    Includes events whose safe_ref.session_id matches *session_id*, AND
    events with no session_id at all (legacy events from before the
    session_id stamp was added, or events created directly via the store
    without going through sync_turn).

    Pure deterministic function — no LLM, no network (INV-5 safe).
    When session_id is empty the caller should fall back to
    _select_continuity_events instead; this function returns [] for
    empty session_id.
    """
    if not session_id:
        return []
    # Include events with safe_ref.session_id == "" (legacy/unstamped events,
    # ~0.3% of production events on 3.200) alongside the target session_id.
    # These events were created before session_id stamping was added (pre-stamp
    # legacy) or via store.append_event() bypassing sync_turn. Excluding them
    # would silently drop relevant context from the current session's view.
    source = events if events is not None else store.read_events()
    filtered = [
        e for e in source
        if str((e.safe_ref or {}).get("session_id", "")) in (session_id, "")
    ]
    return sorted(filtered, key=lambda e: (e.ts, e.id), reverse=True)[:_MAX_CONTINUITY_RECORDS]


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


def _indexed_lines(
    # Intentional divergence from retrievers/indexed_fts.py (pinned by
    # test_memory_os_fts_path_pins.py): this path feeds the raw query to
    # index.search(), whose LIKE fallback guarantees deterministic floor
    # recall on malformed or FTS-missed queries. The retriever sanitizes and
    # cross-validates against canonical bodies instead — an O(corpus) read
    # that must stay off this per-turn path. Do not "unify" one into the
    # other without deciding which recall guarantee survives.
    query: str,
    index: object | None,
    *,
    error_records: list[dict[str, Any]] | None = None,
    seen: set[tuple[str, str]] | None = None,
    source_ids: list[str] | None = None,
) -> list[str]:
    route = plan_query_route(query, diagnostic_grounding_enabled=False)
    search_query = str(route.get("search_query", ""))
    if index is None or not search_query.strip() or not hasattr(index, "search"):
        return []
    try:
        result = index.search(search_query, limit=5)
    except Exception as exc:
        if error_records is not None:
            error_records.append(
                build_error_record(
                    component="prefetch",
                    operation="indexed_lines",
                    error_code="prefetch_index_search_error",
                    severity="warning",
                    recoverable=True,
                    details={"error_type": type(exc).__name__},
                )
            )
        return []
    hits = result.get("hits", [])
    if not hits and search_query.strip() and error_records is not None:
        error_records.append(
            build_error_record(
                component="prefetch._indexed_lines",
                operation="fts5_empty_on_query",
                error_code="prefetch_indexed_search_empty",
                severity="warning",
                recoverable=True,
                details={"message": "FTS5 returned zero indexed hits for non-empty query — possible stale/missing FTS index"},
            )
        )
    lines: list[str] = []
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        record_type = str(hit.get("record_type", ""))
        record_id = str(hit.get("record_id", ""))
        if seen is not None and record_type and record_id:
            if (record_type, record_id) in seen:
                continue  # already emitted by a dedicated section
        snippet = _redact(_clip(str(hit.get("snippet", "")), 220))
        if snippet:
            lines.append(f"- {record_type}/{record_id}: {snippet}")
            if source_ids is not None and record_type and record_id:
                source_ids.append(f"{record_type}:{record_id}")
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


def _extract_query_tokens(query: str) -> list[str]:
    """Extract meaningful search tokens from a mixed-language query.

    Returns a list of lowercase tokens suitable for substring matching
    against event summaries.  CJK segments are split into overlapping
    character bigrams; ASCII words shorter than 3 chars are dropped.
    """
    import re
    tokens: list[str] = []
    normalized = str(query or "").lower().strip()
    if not normalized:
        return tokens
    # ASCII words (3+ chars, excluding common stop words)
    for token in re.findall(r"[a-z0-9]{3,}", normalized):
        if token not in _QUERY_STOP_WORDS:
            tokens.append(token)
    # CJK character bigrams for Chinese/Japanese/Korean segments
    for segment in re.findall(r"[一-鿿぀-ゟ゠-ヿ가-힯]+", normalized):
        for i in range(len(segment) - 1):
            tokens.append(segment[i : i + 2])
    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for token in tokens:
        if token not in seen:
            seen.add(token)
            unique.append(token)
    return unique


_QUERY_STOP_WORDS: frozenset[str] = frozenset({
    "the", "and", "for", "are", "but", "not", "you", "all", "can",
    "had", "her", "was", "one", "our", "out", "has", "have", "from",
    "this", "that", "with", "will", "your", "what", "when", "they",
    "them", "then", "than", "some", "just", "also", "very", "been",
    "were", "does", "did", "its",
})


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


def _format(sections: list[tuple[str, list[str]]]) -> str:
    output = [HEADER]
    for title, lines in sections:
        output.append("")
        output.append(f"### {title}")
        output.extend(lines)
    return "\n".join(output)


def _fit_budget(context: str, budget_chars: int, *, required_titles: set[str] | None = None) -> str:
    if budget_chars <= 0:
        return ""
    if len(context) <= budget_chars:
        return context
    if budget_chars <= len(HEADER):
        return HEADER[:budget_chars]

    sections = _parse_formatted_sections(context)
    if sections:
        fitted = _fit_sections_budget(sections, budget_chars, required_titles=required_titles)
        if fitted:
            return fitted
        return HEADER[:budget_chars]

    trimmed = context[:budget_chars].rstrip()
    if "\n" in trimmed:
        trimmed = trimmed.rsplit("\n", 1)[0].rstrip()
    return trimmed[:budget_chars]


def _parse_formatted_sections(context: str) -> list[tuple[str, list[str]]]:
    lines = context.splitlines()
    if not lines or lines[0].strip() != HEADER:
        return []
    sections: list[tuple[str, list[str]]] = []
    current_title = ""
    current_lines: list[str] = []
    for line in lines[1:]:
        if line.startswith("### "):
            if current_title:
                sections.append((current_title, current_lines))
            current_title = line[4:].strip()
            current_lines = []
            continue
        if current_title:
            current_lines.append(line)
    if current_title:
        sections.append((current_title, current_lines))
    return sections


def _fit_sections_budget(
    sections: list[tuple[str, list[str]]],
    budget_chars: int,
    *,
    required_titles: set[str] | None = None,
) -> str:
    required = {_base_section_title(title) for title in (required_titles or set())}
    kept = [True for _ in sections]
    for index, (title, lines) in enumerate(sections):
        if not _section_has_body(lines) and _base_section_title(title) not in required:
            kept[index] = False
    while True:
        output = _format([section for section, include in zip(sections, kept, strict=False) if include])
        if len(output) <= budget_chars:
            return output
        remaining = [section for section, include in zip(sections, kept, strict=False) if include]
        if remaining and all(_base_section_title(title) in required for title, _ in remaining):
            return _fit_required_sections_budget(remaining, budget_chars)
        if len(remaining) == 1:
            return _fit_single_section_budget(remaining[0], budget_chars)
        drop_index = _next_budget_drop_index(sections, kept, required_titles=required)
        if drop_index is None:
            return HEADER if len(HEADER) <= budget_chars else HEADER[:budget_chars]
        kept[drop_index] = False


def _fit_single_section_budget(section: tuple[str, list[str]], budget_chars: int) -> str:
    title, lines = section
    output_lines = [HEADER, "", f"### {title}"]
    if len("\n".join(output_lines)) > budget_chars:
        return HEADER if len(HEADER) <= budget_chars else HEADER[:budget_chars]
    for line in lines:
        if not line.strip():
            continue
        candidate = "\n".join([*output_lines, line])
        if len(candidate) > budget_chars:
            break
        output_lines.append(line)
    if len(output_lines) <= 3:
        return HEADER if len(HEADER) <= budget_chars else HEADER[:budget_chars]
    return "\n".join(output_lines)


def _fit_required_sections_budget(sections: list[tuple[str, list[str]]], budget_chars: int) -> str:
    """Keep every route-required heading while fitting bounded body evidence."""
    fitted = [(title, []) for title, _ in sections]
    headings_only = _format(fitted)
    if len(headings_only) > budget_chars:
        return HEADER if len(HEADER) <= budget_chars else HEADER[:budget_chars]

    for section_index, (_, lines) in enumerate(sections):
        for line in lines:
            if not line.strip():
                continue
            candidate_sections = [(title, list(body)) for title, body in fitted]
            candidate_sections[section_index][1].append(line)
            candidate = _format(candidate_sections)
            if len(candidate) <= budget_chars:
                fitted = candidate_sections
                continue
            remaining = budget_chars - len(_format(fitted)) - 1
            if remaining > 0:
                candidate_sections = [(title, list(body)) for title, body in fitted]
                candidate_sections[section_index][1].append(_clip_multiline(line, remaining))
                clipped = _format(candidate_sections)
                if len(clipped) <= budget_chars:
                    fitted = candidate_sections
            break
    return _format(fitted)


def _section_has_body(lines: list[str]) -> bool:
    return any(line.strip() and not line.strip().startswith("### ") for line in lines)


def _next_budget_drop_index(
    sections: list[tuple[str, list[str]]],
    kept: list[bool],
    *,
    required_titles: set[str] | None = None,
) -> int | None:
    required = required_titles or set()
    candidates: list[tuple[int, int, int]] = []
    for index, (title, lines) in enumerate(sections):
        if not kept[index]:
            continue
        if _base_section_title(title) in required:
            continue
        priority = _budget_keep_priority(title)
        section_size = len(_format([(title, lines)])) - len(HEADER)
        candidates.append((priority, -section_size, index))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][2]


def _budget_keep_priority(title: str) -> int:
    """Higher value means survive budget pressure longer."""
    base_title = _base_section_title(title)
    priorities = {
        "Identity Memory": 10,
        "Last Session": 62,  # above Crystallized Memory(60): temporal anchor outranks older crystallized under budget
        "Continuity Bridge": 20,
        "Conversation Carryover": 30,
        "Working Memory": 40,
        "Relationship Memory": 45,
        "Crystallized Review Candidates": 50,
        "Crystallized Memory": 60,
        "Related Memory": 65,
        "Recent Event Summaries": 80,
        "Indexed Recall": 90,
        "Substrate Recall": 100,
        "Current Foreground Task": 105,
        "Recall Clarification Guard": 110,
        "Diagnostic Grounding": 120,
        "Current Memory-OS Runtime Facts": 130,
    }
    return priorities.get(base_title, 50)


def _base_section_title(title: str) -> str:
    return title.split(" (")[0] if " (" in title else title


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
