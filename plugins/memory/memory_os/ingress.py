"""Shared foreground and low-clue ingress classification.

This module is intentionally small: it owns the entry-turn decisions that must
stay consistent between the provider, context router, and attribution ledger.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class IngressDecision:
    intent: str
    route: str
    hard_route: bool
    reason_codes: list[str]
    foreground_task_only: bool = False
    clear_current_task_anchor: bool = False
    open_issue: str = ""


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

_CURRENT_TASK_CONTINUE_MARKERS = {
    "continue",
    "resume",
    "继续",
    "继续当前任务",
    "继续刚才的任务",
    "接着来",
    "接着做",
    "继续任务",
    "继续这个任务",
}

_DEFER_CURRENT_TASK_PATTERNS = (
    re.compile(r"(先放一下|先放着|暂时不做|晚点再|等下再|下次再|明天再说|回头再说)"),
    re.compile(r"(pause|defer|later|tomorrow)", re.I),
)

_EXPLICIT_DEFERRED_RESUME_MARKERS = {
    "继续延期任务",
    "继续延后的任务",
    "继续搁置任务",
    "继续搁置的任务",
    "继续暂停的任务",
    "继续之前暂停的任务",
    "继续之前延期的任务",
    "继续 deferred task",
    "continue the deferred task",
    "resume the deferred task",
}

_DIAGNOSTIC_PATTERNS = (
    re.compile(r"(当前|现在|目前|当前的).{0,12}记忆.{0,8}(架构|系统|后端|provider|提供商|状态)"),
    re.compile(r"当前.*(memory_os|memory-os|记忆|memory).*(状态|架构|系统|provider|backend)", re.I),
    re.compile(r"(memory[-_ ]?os|hindsight).*(canonical|store|provider|backend|正常|还在用)", re.I),
    re.compile(r"(memory architecture|memory backend|memory provider|current memory state)", re.I),
    re.compile(r"(which|what).*(memory|storage).*(provider|backend|system)", re.I),
    re.compile(r"用的什么.*记忆"),
    re.compile(r"记忆.*provider", re.I),
)

_LOW_CLUE_RECALL_PATTERNS = (
    re.compile(r"(还记得|记不记得|记得吗).{0,20}(之前|以前|上次|跟你说过|聊过).{0,20}(设计|方案|事情|想法|那个|那套)?"),
    re.compile(r"(之前|以前|上次).{0,20}(跟你说过|聊过).{0,20}(设计|方案|事情|想法|那个|那套)?"),
    re.compile(r"(do you remember|remember).{0,40}(design|idea|thing|plan|that)", re.I),
)

_LOW_CLUE_DEICTIC_CONTINUE_PATTERNS = (
    re.compile(r"^(继续|接着|接着说|说回|回到).{0,8}(昨天|上次|刚才|之前|前面).{0,8}(那个|那条|那套|那件事|那一条|那一个|那个设计)$"),
    re.compile(r"^(继续|接着|接着说|说回|回到).{0,8}(那个|那条|那套|那件事|那一条|那一个|那个设计)$"),
    re.compile(r"^(continue|resume|back to).{0,20}(yesterday|last time|that one|that topic|that design)$", re.I),
)


def classify_ingress(query: str, *, current_task_anchor: str | None = None) -> IngressDecision:
    text = normalize_query(query)
    lower = text.lower()
    has_anchor = bool(str(current_task_anchor or "").strip())

    if text and has_cancellation(text):
        return IngressDecision(
            intent="cancellation",
            route="foreground_control",
            hard_route=True,
            reason_codes=["cancellation"],
            foreground_task_only=True,
        )

    if is_explicit_deferred_resume_query(text):
        return IngressDecision(
            intent="explicit_deferred_resume",
            route="foreground_control",
            hard_route=True,
            reason_codes=["explicit_deferred_resume"],
            foreground_task_only=True,
        )

    if has_anchor and matches_defer_current_task(text):
        return IngressDecision(
            intent="defer_current_task",
            route="foreground_control",
            hard_route=True,
            reason_codes=["deferred_cancellation_open"],
            foreground_task_only=True,
            open_issue="deferred_cancellation_requires_anchor_lifecycle",
        )

    if has_anchor and lower in _CURRENT_TASK_CONTINUE_MARKERS:
        return IngressDecision(
            intent="continue_current_task",
            route="foreground_control",
            hard_route=True,
            reason_codes=["vague_continue_with_anchor"],
            foreground_task_only=True,
        )

    if is_low_clue_deictic_continue_query(text):
        return IngressDecision(
            intent="ambiguous_recall",
            route="ambiguous_recall",
            hard_route=False,
            reason_codes=["low_clue_deictic_continue"],
            clear_current_task_anchor=True,
        )

    if is_low_clue_recall_query(text):
        return IngressDecision(
            intent="ambiguous_recall",
            route="ambiguous_recall",
            hard_route=False,
            reason_codes=["low_clue_recall"],
            clear_current_task_anchor=True,
        )

    return IngressDecision(intent="unclassified", route="", hard_route=False, reason_codes=[])


def normalize_query(text: str) -> str:
    return " ".join(str(text or "").strip().split())


def normalize_marker(text: str) -> str:
    return " ".join(str(text or "").strip().lower().rstrip("。.!！?？").split())


def has_cancellation(text: str) -> bool:
    lower = normalize_query(text).lower()
    return any(marker in lower for marker in _CANCELLATION_MARKERS)


def matches_defer_current_task(text: str) -> bool:
    normalized = normalize_query(text)
    return any(pattern.search(normalized) for pattern in _DEFER_CURRENT_TASK_PATTERNS)


def is_explicit_deferred_resume_query(text: str) -> bool:
    return normalize_marker(text) in _EXPLICIT_DEFERRED_RESUME_MARKERS


def is_low_clue_recall_query(text: str) -> bool:
    normalized = normalize_query(text)
    if not normalized:
        return False
    if any(pattern.search(normalized) for pattern in _DIAGNOSTIC_PATTERNS):
        return False
    return is_low_clue_deictic_continue_query(normalized) or any(
        pattern.search(normalized) for pattern in _LOW_CLUE_RECALL_PATTERNS
    )


def is_low_clue_deictic_continue_query(text: str) -> bool:
    normalized = normalize_marker(text)
    if not normalized:
        return False
    return any(pattern.search(normalized) for pattern in _LOW_CLUE_DEICTIC_CONTINUE_PATTERNS)
