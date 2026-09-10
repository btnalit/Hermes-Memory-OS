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
    matched_rule: str = ""


# ── Machine-authored queries ──────────────────────────────────────────────
# Hermes drives scheduled jobs through the same provider hooks as owner turns:
# the job prompt arrives as the prefetch ``query`` and the session id carries
# the ``cron_<job_id>_<timestamp>`` shape (both verified on production
# 2026-09-10, main and sannai profiles). Neither is an owner utterance, so
# neither may drive a foreground-control decision (cancel / defer / continue /
# anchor writes). Two seams, both load-bearing: the session-id prefix is the
# primary metadata signal (the provider has it); the prompt preamble is the
# fallback for callers that only see text (context router, monitor probes).
# Both strings are Hermes contracts, not Memory-OS choices.
SCHEDULED_SESSION_ID_PREFIX = "cron_"

_MACHINE_AUTHORED_QUERY_PREFIXES = (
    # Hermes cron runner prepends this preamble to every scheduled job prompt.
    "[important: you are running as a scheduled cron job",
    # Hermes cron delivery header (job output re-entering a chat as a turn).
    "cronjob response:",
)

# ── Cancellation intent ───────────────────────────────────────────────────
# Cancellation is an owner *imperative* aimed at the foreground task. The
# pre-2026-09 test was a bare substring scan over these words, so it fired on
# any mention of them — "取消订单后多久到账", "服务不要停止", "为什么有取消的
# 提示词", and every scheduled prompt containing "停止" — and each hit wrote a
# cancelled anchor plus a "stop the foreground task" instruction into the next
# context. Production ledgers on 2026-09-10: 113/121 cancelled anchors on
# sannai and 586/731 on main were cron prompts. The rules below form a closed
# set; ``match_cancellation`` reports the rule id so the anchor audit can say
# why an anchor was cancelled.
#
# Rule ids: ``ascii_imperative`` / ``cjk_imperative`` / ``cjk_resignation``.

# ASCII markers must be whole words (``stopped``/``unstoppable``/``stop_reason``
# never match) and not negated by the preceding tokens (``do not stop``).
# The boundaries are ASCII-only on purpose: ``\w`` matches CJK in Python, so a
# ``\b`` boundary would reject "请stop吧".
_ASCII_CANCELLATION_PATTERN = re.compile(
    r"(?<![a-z0-9_'])(never mind|give up|cancel|abort|stop)(?![a-z0-9_'])"
)
_ASCII_NEGATION_TOKENS = frozenset(
    {"not", "don't", "dont", "never", "without", "cannot", "can't", "won't", "no"}
)
_ASCII_TOKEN_PATTERN = re.compile(r"[a-z']+")

# CJK verbs are imperative only when they are neither negated / reported /
# questioned by what precedes them ("不要停止", "已取消", "为什么取消") nor
# attached to an object outside the foreground-task frame ("取消订单",
# "取消前台任务时", "取消的那件事").
_CJK_CANCEL_VERBS = ("停止", "停下", "取消", "放弃", "收手")
_CJK_PRE_NEGATION = (
    "不要", "别", "不能", "不许", "不会", "不可", "不用", "没有", "没", "未", "已",
    "已经", "是否", "会不会", "要不要", "能不能", "可否", "如何", "怎么", "为什么",
    "为何", "自动", "被", "如果", "一旦", "会", "可能",
)
_CJK_CANCEL_TAIL = re.compile(
    r"^(?:来|掉|吧|了|啦|呀|啊|它|这个|那个|这项|那项|这件|那件|这条|那条|这|那|当前|前台|全部|所有|一切|一下|先)*"
    # Task-like objects only: "取消安装" is a foreground cancellation,
    # "取消订单" / "取消订阅" are business requests.
    r"(?:任务|工作|操作|事|计划|安装|部署|构建|渲染|下载|运行|执行|生成|处理|同步|迁移|升级|测试)?"
    r"(?:吧|了|啦|呀|啊)?"
    r"(?:$|[\s，,。.！!？?；;、：:~～…）)\]】])"
)

# Resignation forms already carry their negation ("别做视频了" cancels the
# video task), so they accept any object; they are rejected only inside a
# descriptive / conditional frame ("为什么不做了", "如果不做了") or when the
# tail turns them into something else ("算了一下", "不要做成微服务").
_CJK_RESIGNATION_MARKERS = (
    "算了", "不做了", "别做", "不要做", "不用做", "别弄",
    "别继续", "不要继续", "不用继续", "不继续了",
)
_CJK_RESIGNATION_PRE_GUARD = (
    "为什么", "为啥", "怎么", "如何", "是否", "会不会", "要不要", "如果", "一旦",
)
_CJK_RESIGNATION_TAIL_GUARD = ("的", "时", "吗", "么", "成", "得", "为", "到", "一下", "一笔")

# A question is never a command.
_QUESTION_PATTERN = re.compile(r"(为什么|为啥|怎么回事|是不是|会不会|多久|\bwhy\b|how come)", re.I)

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


def classify_ingress(
    query: str,
    *,
    current_task_anchor: str | None = None,
    session_id: str = "",
) -> IngressDecision:
    text = normalize_query(query)
    lower = text.lower()
    has_anchor = bool(str(current_task_anchor or "").strip())

    # Scheduled-job prompts are not owner utterances: no foreground-control
    # branch below may fire on them. ``route=""`` lets the context router
    # plan the turn normally; the provider stops before any anchor write.
    # ``session_id`` defaults to "" (= unknown) so callers that cannot know
    # the session fall back to the text guard alone.
    if is_scheduled_session_id(session_id) or is_machine_authored_query(text):
        return IngressDecision(
            intent="machine_authored",
            route="",
            hard_route=False,
            reason_codes=["machine_authored_query"],
        )

    cancellation_rule = match_cancellation(text) if text else ""
    if cancellation_rule:
        return IngressDecision(
            intent="cancellation",
            route="foreground_control",
            hard_route=True,
            reason_codes=["cancellation"],
            foreground_task_only=True,
            matched_rule=cancellation_rule,
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


def is_scheduled_session_id(session_id: str) -> bool:
    return str(session_id or "").strip().lower().startswith(SCHEDULED_SESSION_ID_PREFIX)


def is_machine_authored_query(text: str) -> bool:
    lower = normalize_query(text).lower()
    return any(lower.startswith(prefix) for prefix in _MACHINE_AUTHORED_QUERY_PREFIXES)


def _looks_like_question(normalized: str) -> bool:
    return normalized.endswith(("?", "？")) or bool(_QUESTION_PATTERN.search(normalized))


def _ascii_negated(lower: str, start: int) -> bool:
    preceding = _ASCII_TOKEN_PATTERN.findall(lower[:start])[-3:]
    return any(token in _ASCII_NEGATION_TOKENS for token in preceding)


def match_cancellation(text: str) -> str:
    """Return the id of the cancellation rule the text satisfies, or ``""``.

    Rule ids are a closed set (``ascii_imperative`` / ``cjk_imperative`` /
    ``cjk_resignation``) so the anchor audit can record *why* an owner turn
    was read as a cancellation. Machine-authored prompts and questions never
    match, whatever words they contain.
    """
    normalized = normalize_query(text)
    if not normalized or is_machine_authored_query(normalized) or _looks_like_question(normalized):
        return ""
    lower = normalized.lower()

    for found in _ASCII_CANCELLATION_PATTERN.finditer(lower):
        if not _ascii_negated(lower, found.start()):
            return "ascii_imperative"

    for verb in _CJK_CANCEL_VERBS:
        for found in re.finditer(re.escape(verb), lower):
            preceding = lower[: found.start()].rstrip()
            if any(preceding.endswith(negation) for negation in _CJK_PRE_NEGATION):
                continue
            if _CJK_CANCEL_TAIL.match(lower[found.end():]):
                return "cjk_imperative"

    for marker in _CJK_RESIGNATION_MARKERS:
        for found in re.finditer(re.escape(marker), lower):
            preceding = lower[: found.start()].rstrip()
            if any(preceding.endswith(guard) for guard in _CJK_RESIGNATION_PRE_GUARD):
                continue
            if lower[found.end():].startswith(_CJK_RESIGNATION_TAIL_GUARD):
                continue
            return "cjk_resignation"

    return ""


def has_cancellation(text: str) -> bool:
    return bool(match_cancellation(text))


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
