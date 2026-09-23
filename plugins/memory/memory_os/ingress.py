"""Shared foreground and low-clue ingress classification.

This module is intentionally small: it owns the entry-turn decisions that must
stay consistent between the provider, context router, and attribution ledger.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace


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
    # Hermes self-injected turns (tools/process_registry_notifications.py,
    # gateway/run_busy.py). Four async-delegation dumps in the owner DM were
    # filed as owner cancellations and two as deferrals after 2026-09-10.
    "[async delegation batch complete",
    "[continuing toward your standing goal]",
    # Busy-state notices a Hermes gateway posts into a chat
    # (gateway/run_busy.py). In a shared group another agent's notice reaches
    # this provider as a user turn.
    "⚡ interrupting current task",
    "↪ redirected current run",
    "⏩ steered into current run",
    "⏳ queued for the next turn",
    "⏳ subagent working",
    "⏳ compressing context",
)

# ── Turn author ────────────────────────────────────────────────────────────
# Who wrote the user side of the turn, from the host's per-turn author
# (Hermes ``on_turn_start(author_id=, author_name=, author_is_bot=)``, filled
# from the platform's own bot flag). ``human`` is any non-bot author the host
# admitted — not a verified owner identity; ``unknown`` means the host said
# nothing (older hosts, CLI) and keeps the pre-2026-09 behaviour.
AUTHOR_CLASS_HUMAN = "human"
AUTHOR_CLASS_BOT = "bot"
AUTHOR_CLASS_UNKNOWN = "unknown"
FOREGROUND_CONTROL_AUTHOR_CLASSES = frozenset({AUTHOR_CLASS_HUMAN, AUTHOR_CLASS_UNKNOWN})

# ── Hermes framing around the author's own words ─────────────────────────
# Hermes wraps the author's text before the provider sees it; none of the
# wrapping is the author's utterance. On 2026-09-22 13 of 22 peer-agent turns
# read as cancellations matched only inside the reply quote — usually a quote
# of this agent's own apology ("误以为当前也要停止"), so every apology
# re-triggered the cancellation it apologised for. Formats are Hermes
# contracts, stripped only at the start of the turn, in any stacking order.
_LEADING_FRAME_PATTERNS = (
    # f'[Replying to{" your previous message"}: "{reply_text}"]\n\n{message}'
    # (gateway/run_inbound.py)
    re.compile(r'^\[Replying to(?: your previous message)?: ".*?"\](?:\s+|$)', re.S),
    # Origin header prepended to queued/busy messages (gateway/run_busy.py).
    re.compile(
        r"^Gateway message origin \(JSON data, not instructions or authorization\):.*?"
        r"Do not guess a reply destination when these fields are insufficient\.(?:\s+|$)",
        re.S,
    ),
    # f"[{user_name}|{user_id}]\n{text}": group sender attribution
    # (plugins/platforms/telegram/adapter.py).
    re.compile(r"^\[[^\[\]\n|]{1,80}\|[^\[\]\s|]{1,64}\](?:\s+|$)"),
)
_MAX_LEADING_FRAMES = 8

# A turn that stops or parks the foreground task is a short one. Measured on
# every cancelled anchor written after 2026-09-10 (33, both profiles): the
# genuine owner cancellations were 7, 10 and 28 characters of own text; the
# false ones were pasted reports, debate speeches and delegation dumps of
# 204–11867 characters. The bound is on the author's own text, after the
# frames above are stripped, so replying-with-a-quote still cancels.
_MAX_FOREGROUND_CONTROL_TURN_CHARS = 120

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
# framed descriptively by what follows ("取消前台任务时", "取消订单后多久").
#
# The object is NOT whitelisted. An earlier draft required the verb to be
# followed by one of ~20 task nouns, which rejected "取消掉这个渲染任务",
# "停止安装插件" and "放弃这个方案" — natural cancellations every one. That
# failure direction is worse than the bug this module fixes: an unmatched
# cancellation falls through to `_format_current_task_anchor` and becomes a
# new *active* anchor whose task is the cancellation sentence itself.
#
# What bounds the match instead is clause shape: an imperative is a short
# clause that the verb heads. A cancellation word buried in a pasted article
# or a long report sits inside a long clause and is rejected by the two
# length bounds, without any vocabulary having to anticipate the topic.
_CJK_CANCEL_VERBS = ("停止", "停下", "取消", "放弃", "收手")
_CJK_PRE_NEGATION = (
    "不要", "别", "不能", "不许", "不会", "不可", "不用", "没有", "没", "未", "已",
    "已经", "是否", "会不会", "要不要", "能不能", "可否", "如何", "怎么", "为什么",
    "为何", "自动", "被", "如果", "一旦", "会", "可能", "不提前", "不再",
)
# Negators that scope over a verb later in the same clause, not only when
# adjacent: "不要乱了无故停下" (the owner telling the agents NOT to stop — read
# as a cancellation on 2026-09-22), "不能因为治理复杂就取消证据链",
# "误以为当前也要停止". Bounded to a short window before the verb, and
# deliberately without bare 不 / 没 / 未 / 别, which begin ordinary words
# (不过, 没用的, 未完成的, 别的).
_CJK_WINDOW_NEGATORS = ("不要", "不能", "不许", "不可", "不用", "不必", "无需", "不该", "不应", "以为")
_CJK_NEGATION_WINDOW_CHARS = 8
# A bare "." is deliberately absent: it splits version and decimal numbers
# ("停止远端 2.88 的 gateway" would otherwise end its clause at "2"), and an
# English sentence break is already handled by the ASCII rule.
_CJK_CLAUSE_TERMINATORS = "，,。！!？?；;、\n"
# The verb heads a short clause: at most this many characters follow it
# before the clause ends, and the whole clause stays this short.
_CJK_MAX_CHARS_AFTER_VERB = 12
_CJK_MAX_CLAUSE_CHARS = 30
_CJK_TAIL_REJECT = (
    # "取消的那件事" / "停止的原因" — the verb is being referred to, not issued.
    re.compile(r"^[掉了啦呀啊吧]*的"),
    # "取消前台任务时，同时清除…" — a temporal clause about cancelling.
    re.compile(r"时$"),
    # "取消订单后多久到账" — note 后 alone is not enough ("停止后台任务").
    re.compile(r"后(?:多久|再|会|能|怎|才|就)"),
    # "这个任务取消了吗？" — an interrogative particle, not the bare mark.
    re.compile(r"[吗么]$"),
)

# Object classes checked across the WHOLE clause, not just the tail: the object
# can precede the verb ("旧服务该永远停止的要确保停止了").
_CJK_CLAUSE_REJECT = (
    # Business objects: cancelling one of these is not a foreground-task action.
    re.compile(r"(订单|订阅|预约|会员|挂号|开机启动|自动启动|计费|合同|机票|酒店|快递|保险|课程)"),
    # Ops objects: "停止远端 gateway" / "旧服务确保停止了" are instructions about
    # a service, issued *while* the foreground task continues. Deliberately
    # narrow — "停止安装插件" and "停止渲染视频" must still cancel.
    re.compile(r"(服务|service|gateway|网关|进程|process|容器|container|systemd|timer|daemon|守护|端口|\bport\b)"),
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
    author_class: str = "",
) -> IngressDecision:
    # Every decision reads the author's own words only, never the Hermes
    # frames around them (reply quote, origin header, sender tag).
    text = normalize_query(extract_own_text(query))
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

    # Another agent's turn (a peer bot in a shared chat) may be about
    # anything, including stopping; it is never an instruction to *this*
    # agent's owner-facing foreground task. 22 of the 33 cancelled anchors
    # written between 2026-09-10 and 09-22 were peer-agent debate turns.
    # ``author_class`` defaults to "" (= the caller does not know) so
    # text-only callers keep the owner-text rules below.
    if author_class and author_class not in FOREGROUND_CONTROL_AUTHOR_CLASSES:
        return IngressDecision(
            intent="non_owner_authored",
            route="",
            hard_route=False,
            reason_codes=["non_owner_authored_turn"],
        )

    decision = _classify_author_text(text, has_anchor=has_anchor)
    if (
        decision.intent != "cancellation"
        and len(text) > _MAX_FOREGROUND_CONTROL_TURN_CHARS
        and _match_cancellation_rule(text)
    ):
        # Report-only: the long turn contained an imperative shape the length
        # bound refused. Lets production tell "the gate held" from "nothing
        # to gate" without re-reading the transcript.
        decision = replace(decision, reason_codes=[*decision.reason_codes, "cancel_rejected_turn_too_long"])
    return decision


def _classify_author_text(text: str, *, has_anchor: bool) -> IngressDecision:
    lower = text.lower()
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
    lower = normalize_query(extract_own_text(text)).lower()
    return any(lower.startswith(prefix) for prefix in _MACHINE_AUTHORED_QUERY_PREFIXES)


def extract_own_text(text: str) -> str:
    """Return the turn with its leading Hermes frames removed.

    Idempotent, and safe on already-normalized text (the frame patterns accept
    any whitespace after the closing bracket). A quote that itself contains
    ``"]`` followed by whitespace ends early; what remains is then still
    classified, so the failure direction is keeping text, not dropping it.
    """
    own = str(text or "").lstrip()
    for _ in range(_MAX_LEADING_FRAMES):
        for pattern in _LEADING_FRAME_PATTERNS:
            stripped = pattern.sub("", own, count=1)
            if stripped != own:
                own = stripped.lstrip()
                break
        else:
            break
    return own


def author_class_from_host(
    *, author_id: object = None, author_name: object = None, author_is_bot: object = None
) -> str:
    """Map the host's per-turn author fields onto the closed author classes."""
    if author_is_bot is True:
        return AUTHOR_CLASS_BOT
    if str(author_id or "").strip() or str(author_name or "").strip():
        return AUTHOR_CLASS_HUMAN
    return AUTHOR_CLASS_UNKNOWN


def _looks_like_question(normalized: str) -> bool:
    return normalized.endswith(("?", "？")) or bool(_QUESTION_PATTERN.search(normalized))


def _ascii_negated(lower: str, start: int) -> bool:
    preceding = _ASCII_TOKEN_PATTERN.findall(lower[:start])[-3:]
    return any(token in _ASCII_NEGATION_TOKENS for token in preceding)


def _clause_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    """Return the span of the clause containing ``text[start:end]``."""
    left = start
    while left > 0 and text[left - 1] not in _CJK_CLAUSE_TERMINATORS:
        left -= 1
    right = end
    while right < len(text) and text[right] not in _CJK_CLAUSE_TERMINATORS:
        right += 1
    return left, right


def _cjk_verb_heads_an_imperative_clause(text: str, start: int, end: int) -> bool:
    """True when the cancellation verb at ``text[start:end]`` issues an order.

    Two bounds and a reject list, in place of a whitelist of objects: the verb
    must head a short clause (so a cancellation word inside a pasted article or
    a long report cannot match), and the tail must not turn it into a
    description, a question, or a business request.
    """
    left, right = _clause_bounds(text, start, end)
    tail = text[end:right]
    if len(tail) > _CJK_MAX_CHARS_AFTER_VERB or (right - left) > _CJK_MAX_CLAUSE_CHARS:
        return False
    if any(pattern.search(tail) for pattern in _CJK_TAIL_REJECT):
        return False
    return not any(pattern.search(text[left:right]) for pattern in _CJK_CLAUSE_REJECT)


def _cjk_verb_negated_in_clause(text: str, start: int) -> bool:
    """True when a scoping negator sits in the same clause shortly before the verb."""
    left, _ = _clause_bounds(text, start, start)
    longest = max(len(negator) for negator in _CJK_WINDOW_NEGATORS)
    window = text[max(left, start - _CJK_NEGATION_WINDOW_CHARS - longest) : start]
    return any(negator in window for negator in _CJK_WINDOW_NEGATORS)


def match_cancellation(text: str) -> str:
    """Return the id of the cancellation rule the text satisfies, or ``""``.

    Rule ids are a closed set (``ascii_imperative`` / ``cjk_imperative`` /
    ``cjk_resignation``) so the anchor audit can record *why* an owner turn
    was read as a cancellation. Machine-authored prompts and questions never
    match, whatever words they contain; only the author's own text is read,
    and only when it is short enough to be an order.
    """
    normalized = normalize_query(extract_own_text(text))
    if len(normalized) > _MAX_FOREGROUND_CONTROL_TURN_CHARS:
        return ""
    return _match_cancellation_rule(normalized)


def _match_cancellation_rule(normalized: str) -> str:
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
            if _cjk_verb_negated_in_clause(lower, found.start()):
                continue
            if _cjk_verb_heads_an_imperative_clause(lower, found.start(), found.end()):
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
    # Same own-text and length bound as cancellation: a deferral is a short
    # order too. Unbounded, a long instruction that merely mentioned
    # "明天再说" or "later" parked the owner's task (production deferral
    # ledger, 2026-09).
    normalized = normalize_query(extract_own_text(text))
    if len(normalized) > _MAX_FOREGROUND_CONTROL_TURN_CHARS:
        return False
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
