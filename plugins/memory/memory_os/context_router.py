"""Dry-run context relevance routing for Memory-OS prefetch sections."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .source_ids import filter_safe_source_id_values

from .ingress import (
    classify_ingress as _classify_ingress,
    is_low_clue_deictic_continue_query as _ingress_is_low_clue_deictic_continue_query,
    is_low_clue_recall_query as _ingress_is_low_clue_recall_query,
)


SCHEMA_VERSION = "memory-os.context_router.v0"
INCLUDE_THRESHOLD = 0.30
RANKING_MODE = "score_then_budget"

# 图谱锚点溯源加分(CK 2026-08-07):Related Memory 的内容由当前 query 的
# FTS 命中锚点一跳展开(锚点收集含 E8b 中文回退)— 相关性已在上游用真实
# 查询词建立。本文件的打分词表(ASCII 实体 + 固定中文词表)是更弱的谓词,
# 让它重新裁决会出现「FTS 命中、词表盲区、整段否决」:生产实测图谱行对
# 纯中文 query 恒 0 分被 below_threshold 掉,锚点机制白干。加分不豁免
# 风险码(-0.80 仍可击杀泄漏行)、路由排除与预算排序。
# 刻意不含 "indexed":casual 兜底路由下词表不匹配的 Indexed Recall 内容
# 不免票是被测试钉住的既有强度(test_casual_continuity_report_selects_
# safe_carryover_without_mechanism_working);FTS 命中被词表二审否决的
# 同族问题对 indexed 是否也该修,留 owner 单独裁决(待办登记)。
_QUERY_PROVENANCE_SOURCE_CLASSES = frozenset({"graph_layer"})
GRAPH_ANCHOR_PROVENANCE_SCORE = 0.35

# FIX 3 (P3 audit): `allocated_chars` on each selected-section entry below is
# an ADVISORY per-section budget projection computed by this dry-run/apply
# router only -- it has no consumer. The real "apply" path
# (`prefetch._build_context_router_apply_prefetch`) re-reads the FULL,
# untruncated candidate sections by name and hands them to its own
# formatter/truncator (`prefetch._fit_budget` / `_fit_sections_budget`,
# which own the RH-26 `required_titles` fail-closed contract). That
# formatter recomputes its own per-section char budget from scratch and is
# the sole thing that actually clips text for the final assembled context.
#
# Two options were considered to close this gap:
#   (a) Make the real formatter consume `allocated_chars` directly.
#   (b) Make the advisory nature explicit and lock the real invariant with
#       a test, without touching the formatter.
# We chose (b): `prefetch.py` is out of this fix's file ownership, and its
# `_fit_budget`/`required_titles` contract is a battle-tested, separately
# unit-tested fail-closed mechanism (RH-26) for keeping route-required
# headings alive under budget pressure. Wiring `allocated_chars` into it
# would require redesigning that contract's truncation order and risks
# regressing the required-heading guarantee for no behavioral gain, since
# the formatter already enforces `len(final_context) <= budget_chars`
# independently. `allocated_chars_semantics` below makes the advisory-only
# status a discoverable, testable part of this report's own contract so a
# future maintainer cannot mistake it for an enforced truncation directive.
ALLOCATED_CHARS_SEMANTICS = "advisory_projection_not_enforced_by_formatter"

INCLUDE_REASONS = {
    "required_by_route",
    "high_relevance",
    "foreground_anchor",
    "entity_match",
    "keyword_match",
    "freshness_match",
}

EXCLUDE_REASONS = {
    "route_excludes_section",
    "route_excludes_broad_carryover",
    "below_threshold",
    "diagnostic_style_in_non_diagnostic_route",
    "mechanism_leak_detected",
    "stale_runtime",
    "budget_exceeded",
}

_ASCII_ENTITY_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_-]{1,}|[A-Z0-9_-]{2,}")

_CANCELLATION_MARKERS = (
    "算了",
    "别做",
    "不要做",
    "不做了",
    "停下",
    "停止",
    "收手",
    "放弃",
    "取消",
    "别弄",
    "不用做",
    "cancel",
    "stop",
    "abort",
    "give up",
    "never mind",
)

_VAGUE_CONTINUE_MARKERS = {
    "continue",
    "resume",
    "继续",
    "继续当前任务",
    "继续刚才的任务",
    "接着来",
    "接着做",
    "继续上面那个",
    "继续刚才那个",
}

_DEFERRED_CANCELLATION_PATTERNS = (
    re.compile(r"(先放一下|先放着|暂时不做|晚点再|等下再|下次再|明天再说|回头再说)"),
    re.compile(r"(pause|defer|later|tomorrow)", re.I),
)

_DIAGNOSTIC_PATTERNS = (
    re.compile(r"(当前|现在|目前|当前的).{0,12}记忆.{0,8}(架构|系统|后端|provider|提供商|状态)"),
    re.compile(r"当前.*(memory_os|memory-os|记忆|memory).*(状态|架构|系统|provider|backend)", re.I),
    re.compile(r"(memory[-_ ]?os|hindsight).*(canonical|store|provider|backend|正常|还在用)", re.I),
    re.compile(r"(memory architecture|memory backend|memory provider|current memory state)", re.I),
    re.compile(r"(which|what).*(memory|storage).*(provider|backend|system)", re.I),
    re.compile(r"用的什么.*记忆"),
    re.compile(r"记忆.*provider", re.I),
)

_CANDIDATE_PATTERNS = (
    re.compile(r"candidate|candidates|crystallized|crystallization|long[- ]term memory|review queue", re.I),
    re.compile(r"候选|结晶|沉淀|长期记忆|长期智慧|审查队列|待审"),
)

_ARCHITECTURE_PATTERNS = (
    re.compile(r"(memory[-_ ]?os|memory-os|记忆系统).{0,20}(层级|架构|设计|working memory|carryover)", re.I),
    re.compile(r"(working memory|conversation carryover|context router|上下文|层级).{0,20}(设计|关系|怎么|如何)", re.I),
)

_ACTIVE_TASK_TERMS = (
    "安装",
    "修",
    "修复",
    "测试",
    "部署",
    "渲染",
    "剪",
    "下载",
    "检查",
    "分析",
    "继续安装",
    "debug",
    "fix",
    "test",
    "deploy",
    "render",
    "install",
    "download",
    "inspect",
    "analyze",
    "comfyui",
    "ffmpeg",
)

_ORDINARY_OPINION_TERMS = (
    "你觉得",
    "感觉",
    "聊聊",
    "变化",
    "怎么样",
    "感受",
    "what do you think",
)

_LOW_CLUE_RECALL_PATTERNS = (
    re.compile(r"(还记得|记不记得|记得吗).{0,20}(之前|以前|上次|跟你说过|聊过).{0,20}(设计|方案|事情|想法|那个|那套)?"),
    re.compile(r"(之前|以前|上次).{0,20}(跟你说过|聊过).{0,20}(设计|方案|事情|想法|那个|那套)?"),
    re.compile(r"(do you remember|remember).{0,40}(design|idea|thing|plan|that)", re.I),
)

_LOW_CLUE_DEICTIC_CONTINUE_PATTERNS = (
    re.compile(r"^(继续|接着|接着说|说回|回到).{0,8}(昨天|上次|刚才|之前|前面).{0,8}(那个|那条|那套|那件事|那一条|那一个|那个设计)"),
    re.compile(r"^(继续|接着|接着说|说回|回到).{0,8}(那个|那条|那套|那件事|那一条|那一个|那个设计)$"),
    re.compile(r"^(continue|resume|back to).{0,20}(yesterday|last time|that one|that topic|that design)", re.I),
)

_CHINESE_KEYWORDS = (
    "记忆",
    "架构",
    "系统",
    "插件",
    "安装",
    "视频",
    "渲染",
    "错误",
    "失败",
    "网关",
    "状态",
    "候选",
    "结晶",
    "长期记忆",
    "治理",
    "证据",
    "任务",
)

_DIAGNOSTIC_STYLE_PATTERNS = (
    re.compile(r"hindsight|hermes02", re.I),
    re.compile(r"memory[-_ ]?os\.tool_status|memory_os_status", re.I),
    re.compile(r"index_health|prefetch_mode|audit_entries", re.I),
    re.compile(r"provider[-_ ]?status|runtime facts|status snapshot", re.I),
    re.compile(r"governance|ops[-_ ]?gate|proposal queue|self[-_ ]?evolution", re.I),
    re.compile(r"审计记录|索引健康|实时诊断|当前提供商|权威存储路径"),
)

_MECHANISM_PATTERNS = (
    re.compile(r"internal reflection context|injection card|source refs|system prompt|prefetch", re.I),
    re.compile(r"内部反思|注入卡片|源引用|系统提示词"),
)

_STALE_RUNTIME_PATTERNS = (
    re.compile(r"index_health\s*[:=]\s*stale", re.I),
    re.compile(r"stale diagnostic|old hindsight|旧.*hindsight", re.I),
)

_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)\S+"),
    re.compile(r"(?i)(token\s*[:=]\s*)\S+"),
    re.compile(r"(?i)(secret\s*[:=]\s*)\S+"),
    re.compile(r"(?i)(password\s*[:=]\s*)\S+"),
)


@dataclass(frozen=True)
class ContextSection:
    section: str
    text: str
    source_class: str = "other"
    metadata: dict[str, Any] | None = None

    @property
    def char_cost(self) -> int:
        return len(_redact(self.text))


def plan_context_route(query: str, *, current_task_anchor: str | None = None) -> dict[str, Any]:
    text = _normalize(query)
    lower = text.lower()
    reason_codes: list[str] = []
    ingress = _classify_ingress(query, current_task_anchor=current_task_anchor)
    if ingress.route:
        result = _route(ingress.route, hard_route=ingress.hard_route, reason_codes=list(ingress.reason_codes))
        if ingress.open_issue:
            result["open_issue"] = ingress.open_issue
        return result

    if text and _has_cancellation(text):
        return _route("foreground_control", hard_route=True, reason_codes=["cancellation"])

    if current_task_anchor and _matches_any(text, _DEFERRED_CANCELLATION_PATTERNS):
        result = _route("foreground_control", hard_route=True, reason_codes=["deferred_cancellation_open"])
        result["open_issue"] = "deferred_cancellation_requires_anchor_lifecycle"
        return result

    if current_task_anchor and lower in _VAGUE_CONTINUE_MARKERS:
        return _route("foreground_control", hard_route=True, reason_codes=["vague_continue_with_anchor"])

    if _matches_any(text, _DIAGNOSTIC_PATTERNS):
        return _route("diagnostic_current_status", hard_route=True, reason_codes=["explicit_diagnostic"])

    if _is_low_clue_deictic_continue_query(text):
        return _route("ambiguous_recall", hard_route=False, reason_codes=["low_clue_deictic_continue"])

    if is_low_clue_recall_query(text):
        return _route("ambiguous_recall", hard_route=False, reason_codes=["low_clue_recall"])

    if _matches_any(text, _CANDIDATE_PATTERNS):
        return _route("candidate_review", hard_route=False, reason_codes=["candidate_review_terms"])

    if _matches_any(text, _ARCHITECTURE_PATTERNS):
        return _route("memory_architecture_discussion", hard_route=False, reason_codes=["architecture_discussion_terms"])

    if _contains_any(lower, _ACTIVE_TASK_TERMS):
        return _route("active_task", hard_route=False, reason_codes=["active_task_terms"])

    if _contains_any(lower, _ORDINARY_OPINION_TERMS):
        reason_codes.append("ordinary_opinion")

    return _route("casual_continuity", hard_route=False, reason_codes=reason_codes or ["default_casual"])


def route_context_sections(
    query: str,
    *,
    sections: list[ContextSection],
    current_task_anchor: str | None = None,
    budget_chars: int,
    mode: str = "dry_run",
) -> dict[str, Any]:
    route = plan_context_route(query, current_task_anchor=current_task_anchor)
    selected: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    used_budget = 0

    evaluated: list[tuple[int, dict[str, Any]]] = []
    excluded: list[tuple[int, dict[str, Any]]] = []
    for index, section in enumerate(sections):
        decision = _section_decision(
            section,
            query=query,
            route=str(route["route"]),
            current_task_anchor=current_task_anchor or "",
        )
        entry = _section_report_entry(section, decision)
        if decision["include"]:
            evaluated.append((index, entry))
        else:
            excluded.append((index, entry))

    required_entries = sorted(
        (item for item in evaluated if item[1]["required"]),
        key=lambda item: item[0],
    )
    optional_entries = sorted(
        (item for item in evaluated if not item[1]["required"]),
        key=lambda item: (-float(item[1]["score"]), item[0]),
    )
    budget_limit = max(0, int(budget_chars))
    # NOTE: `allocated_chars` below (and this loop's `used_budget` running
    # total) is this router's own advisory bookkeeping only -- see
    # ALLOCATED_CHARS_SEMANTICS above. It is never read back to truncate
    # text; the real formatter in prefetch.py computes its own budget fit.
    for _index, entry in [*required_entries, *optional_entries]:
        remaining_budget = max(0, budget_limit - used_budget)
        if entry["required"]:
            selected_entry = dict(entry)
            allocated = min(int(entry["char_cost"]), remaining_budget)
            selected_entry["allocated_chars"] = allocated
            if allocated < int(entry["char_cost"]):
                selected_entry["reason_codes"] = _dedupe(
                    selected_entry["reason_codes"] + ["budget_truncated"]
                )
            selected.append(selected_entry)
            used_budget += allocated
        elif int(entry["char_cost"]) <= remaining_budget:
            selected_entry = dict(entry)
            selected_entry["allocated_chars"] = int(entry["char_cost"])
            selected.append(selected_entry)
            used_budget += int(entry["char_cost"])
        else:
            budget_entry = dict(entry)
            budget_entry["allocated_chars"] = 0
            budget_entry["reason_codes"] = _dedupe(budget_entry["reason_codes"] + ["budget_exceeded"])
            dropped.append(budget_entry)
    dropped.extend(entry for _index, entry in sorted(excluded, key=lambda item: item[0]))

    return {
        "schema_version": SCHEMA_VERSION,
        "mode": mode,
        "route": route["route"],
        "route_reason_codes": route["reason_codes"],
        "open_issue": route.get("open_issue"),
        "query_redacted": _clip(_redact(_normalize(query)), 160),
        "budget_chars": budget_limit,
        "used_budget_chars": used_budget,
        "ranking_mode": RANKING_MODE,
        "include_threshold": INCLUDE_THRESHOLD,
        "allocated_chars_semantics": ALLOCATED_CHARS_SEMANTICS,
        "selected_sections": selected,
        "dropped_sections": dropped,
        "risk_flags": _risk_flags(selected + dropped),
        "would_change_live_prefetch": bool(dropped),
    }


def _route(route: str, *, hard_route: bool, reason_codes: list[str]) -> dict[str, Any]:
    return {"route": route, "hard_route": hard_route, "reason_codes": reason_codes}


def _section_decision(
    section: ContextSection,
    *,
    query: str,
    route: str,
    current_task_anchor: str,
) -> dict[str, Any]:
    required = _is_required_by_route(section, route)
    excluded_reason = _route_exclusion_reason(section, route)
    score, reasons = _score_section(section, query=query, current_task_anchor=current_task_anchor)
    if required:
        score = max(score, 1.0)
        reasons = _dedupe(["required_by_route"] + reasons)
    if excluded_reason:
        return {
            "include": False,
            "required": False,
            "score": round(score, 3),
            "reason_codes": _dedupe([excluded_reason] + _risk_reason_codes(section)),
        }
    risk_reasons = _risk_reason_codes(section)
    if risk_reasons and route != "diagnostic_current_status":
        score = max(0.0, score - 0.80)
        reasons.extend(risk_reasons)
    include = required or score >= INCLUDE_THRESHOLD
    if not include:
        reasons.append("below_threshold")
    return {
        "include": include,
        "required": required,
        "score": round(score, 3),
        "reason_codes": _dedupe(reasons),
    }


def _is_required_by_route(section: ContextSection, route: str) -> bool:
    name = section.section.lower()
    if route == "foreground_control":
        return name == "current foreground task"
    if route == "diagnostic_current_status":
        return name in {"diagnostic grounding", "current memory-os runtime facts"}
    if route == "active_task":
        return name in {"current foreground task", "indexed recall"}
    if route == "candidate_review":
        return "candidate" in name or "crystallized" in name
    if route == "ambiguous_recall":
        return name == "recall clarification guard"
    if route == "casual_continuity":
        return name == "conversation carryover"
    return False


def _route_exclusion_reason(section: ContextSection, route: str) -> str:
    name = section.section.lower()
    if route == "foreground_control" and name != "current foreground task":
        return "route_excludes_section"
    if route == "diagnostic_current_status" and name not in {"diagnostic grounding", "current memory-os runtime facts"}:
        return "route_excludes_section"
    if route == "active_task" and name == "conversation carryover":
        return "route_excludes_broad_carryover"
    if route == "casual_continuity" and (
        name == "current foreground task"
        or name == "working memory"
        # S6 注(2026-08-06 二次精确化):Overlay 不在此整段排除。casual 是
        # 兜底默认路由,整段排除会让所有无任务信号的消息丢失全部状态层;
        # 泄漏面只有前台任务内容,由 prefetch._state_overlay_lines 按路由
        # 抑制 active_projects 一节(suppress_active_projects),其余节保留。
        or "diagnostic" in name
        or "candidate" in name
        or name == "crystallized memory"
    ):
        return "route_excludes_section"
    if route == "ambiguous_recall" and name == "working memory":
        return "route_excludes_section"
    if route == "ambiguous_recall" and name != "recall clarification guard":
        return "route_excludes_section"
    return ""


def _score_section(section: ContextSection, *, query: str, current_task_anchor: str) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    text_terms = _terms(section.text)
    query_terms = _terms(query)
    anchor_terms = _terms(current_task_anchor)

    entity_matches = text_terms["entities"] & (query_terms["entities"] | anchor_terms["entities"])
    keyword_matches = text_terms["keywords"] & (query_terms["keywords"] | anchor_terms["keywords"])
    if entity_matches:
        score += min(0.60, 0.30 * len(entity_matches))
        reasons.append("entity_match")
    if keyword_matches:
        score += min(0.45, 0.15 * len(keyword_matches))
        reasons.append("keyword_match")
    if section.section == "Current Foreground Task" or entity_matches & anchor_terms["entities"]:
        score += 0.50
        reasons.append("foreground_anchor")
    if (
        section.source_class in _QUERY_PROVENANCE_SOURCE_CLASSES
        and section.text.strip()
    ):
        score += GRAPH_ANCHOR_PROVENANCE_SCORE
        reasons.append("graph_anchor_provenance")
    if section.metadata and section.metadata.get("fresh"):
        score += 0.10
        reasons.append("freshness_match")
    if score >= INCLUDE_THRESHOLD:
        reasons.append("high_relevance")
    return score, reasons


def _terms(text: str) -> dict[str, set[str]]:
    normalized = _normalize(_redact(text))
    entities = {item.lower() for item in _ASCII_ENTITY_PATTERN.findall(normalized)}
    keywords = {keyword.lower() for keyword in _CHINESE_KEYWORDS if keyword.lower() in normalized.lower()}
    return {"entities": entities, "keywords": keywords}


def _risk_reason_codes(section: ContextSection) -> list[str]:
    text = section.text
    reasons: list[str] = []
    if _matches_any(text, _DIAGNOSTIC_STYLE_PATTERNS):
        reasons.append("diagnostic_style_in_non_diagnostic_route")
    if _matches_any(text, _MECHANISM_PATTERNS):
        reasons.append("mechanism_leak_detected")
    if _matches_any(text, _STALE_RUNTIME_PATTERNS):
        reasons.append("stale_runtime")
    return reasons


def _section_report_entry(section: ContextSection, decision: dict[str, Any]) -> dict[str, Any]:
    redacted = _redact(section.text)
    metadata = section.metadata if isinstance(section.metadata, dict) else {}
    source_ids = filter_safe_source_id_values(metadata.get("source_ids") or [])
    return {
        "section": section.section,
        "source_class": section.source_class,
        "char_cost": len(redacted),
        "score": decision["score"],
        "required": decision["required"],
        "reason_codes": decision["reason_codes"],
        "source_ids": source_ids,
        "preview": _clip(redacted, 180),
    }


def _risk_flags(entries: list[dict[str, Any]]) -> list[str]:
    flags: list[str] = []
    for entry in entries:
        for reason in entry.get("reason_codes", []):
            if reason in {
                "diagnostic_style_in_non_diagnostic_route",
                "mechanism_leak_detected",
                "stale_runtime",
            }:
                flags.append(reason)
    return _dedupe(flags)


def _has_cancellation(text: str) -> bool:
    normalized = _normalize(text).lower()
    return any(marker in normalized for marker in _CANCELLATION_MARKERS)


def is_low_clue_recall_query(text: str) -> bool:
    return _ingress_is_low_clue_recall_query(text)


def _is_low_clue_deictic_continue_query(text: str) -> bool:
    return _ingress_is_low_clue_deictic_continue_query(text)


def _matches_any(text: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term.lower() in text for term in terms)


def _redact(value: str) -> str:
    redacted = str(value or "")
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(r"\1[redacted]", redacted)
    return redacted


def _normalize(value: str) -> str:
    return " ".join(str(value or "").split())


def _clip(value: str, limit: int) -> str:
    text = _normalize(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item not in seen:
            result.append(item)
            seen.add(item)
    return result
