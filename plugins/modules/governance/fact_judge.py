"""Offline LLM durable-fact judge for crystallization unblock.

Runs in a dedicated cron lane (fact_judge), NOT on the hot path (INV-5).
Judges inner_drive_candidates for a single question: "Is this a durable fact
worth permanently remembering, or a transient moment?"

Conservative by design — only marks clearly durable facts; unsure → False.
Fail-safe on all errors — candidate stays untouched on any failure.

Verdicts are written to a JSONL sidecar that the candidate_aggregation lane
reads to bypass the size≥2 cluster gate for durable singletons.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from plugins.memory.memory_os import jev_backend
from plugins.memory.memory_os.crystallized import CrystallizedCandidate, read_candidate_queue
from plugins.memory.memory_os.low_clue_recall import (
    LlmCallResult,
    _call_hermes_runtime_model_result,
    _extract_json_object,
    _llm_call_diagnostics,
)
from plugins.memory.memory_os.store import MemoryOSStore


def _call_diagnostics(call_result: LlmCallResult | None) -> dict[str, Any]:
    """Typed transport diagnostics to fold onto a verdict/report (W2).

    ``llm_transport_failure_reason`` is the RAW closed-set reason from
    :class:`LlmCallResult` -- distinct from this module's own
    ``failure_reason`` vocabulary (llm_exception/llm_empty_content/
    llm_parse_failed/llm_missing_key), which additionally covers post-
    transport parsing/schema failures the transport layer knows nothing
    about. Kept in a separate field so the two vocabularies never collide
    (e.g. the transport's llm_missing_key means "credential missing";
    this module's llm_missing_key means "durable_fact key missing").

    W4-A: delegates to the single shared seam
    (``low_clue_recall._llm_call_diagnostics``) that also now forwards
    ``llm_expected_model``/``llm_actual_model``/``llm_route_unexpected``/
    ``llm_route_unknown`` (plan row L1) -- every key this function
    previously returned is unchanged in name and value.
    """
    return _llm_call_diagnostics(call_result)


def fact_judge_manifest() -> dict[str, Any]:
    return {
        "name": "fact_judge",
        "kind": "governance",
        "version": "0.1.0",
        "layer": "L3",
        "dependencies": {
            "required": ["memory_os >=0.1.0", "execution_gate", "candidate_aggregation"],
        },
        "provides": {
            "commands": ["run_once", "read_fact_judge_verdicts"],
            "schedules": ["fact_judge"],
            "reads": ["memory_os.crystallized.candidates"],
            "writes": ["local_artifact.fact_judge_verdicts"],
            "consumed_by": ["candidate_aggregation"],
        },
        "defaults": {
            "enabled": True,
            "profile_scope": "per-profile",
            "heuristic_only": False,
        },
    }

# ── Judge config defaults ────────────────────────────────────────────────
DEFAULT_JUDGE_CONFIG: dict[str, Any] = {
    "provider": "hermes_default",
    "timeout_ms": 15000,
    "max_tokens": 1024,
    "max_per_tick": 8,
    # J1: optional structured-judge backend (owner ruling 2026-09-23,
    # next-phase plan row J1). "hermes_default" is the existing free-text
    # LLM judge path below; "typesafe_jev" routes through jev_backend.py's
    # native noul primitive first, falling back to this path on any Jev
    # failure. Overridden by the fact_judge_judge_backend knob, which wins
    # over this lane-config default -- see run_fact_judge_lane.
    "judge_backend": "hermes_default",
}

# ── Retry + heuristic fallback ─────────────────────────────────────────────
MAX_JUDGE_RETRIES = 2

# Heuristic durable/transient markers (Chinese + English).
# Used ONLY as fallback when LLM fails — not as primary judgment.
_DURABLE_MARKERS: frozenset[str] = frozenset({
    "prefer", "决定", "用", "记住", "我喜欢", "我爱",
    "framework", "框架", "策略", "always", "commit",
    "i prefer", "i like", "i use", "我的", "我是",
    "want to", "想要", "打算", "plan to", "will use",
    "习惯", "常用", "一直在", "选择", "选择使用",
})

_TRANSIENT_MARKERS: frozenset[str] = frozenset({
    # Original seed (greetings / confirmations)
    "谢谢", "收到", "hello", "thanks", "open", "show me",
    "天气", "今天", "hi", "bye", "再见", "好的",
    "ok", "明白了", "知道了", "不用谢",
    # Extended: Chinese process markers (shared with inner_drive source gate)
    "更新部署看看", "部署看看", "验证结果如何", "检查一下",
    "试试看", "感觉一下", "感受一下", "体验一下",
    "好不好", "行不行", "对不对", "可不可以",
    "查一下", "看一下", "搜一下", "找一下",
    "帮我查", "帮我找", "帮我搜索", "帮我看看",
    "打开看看", "打开页面", "打开文件", "打开项目",
    "运行一下", "跑一下", "测一下", "编译一下",
    "部署一下", "提交一下", "推送一下", "拉一下代码",
    "继续", "嗯", "好的", "好", "行", "可以",
    "稍等", "等一下", "马上", "待会",
    "这个是什么", "这是什么", "怎么用", "怎么操作",
    # Extended: English short commands / fragments
    "show", "check", "run", "build", "test", "deploy",
    "push", "pull", "commit", "merge", "rebase",
    "look at", "take a look", "let me see",
    "wait", "hold on", "one sec", "just a moment",
    "what is", "how to", "tell me about",
})


def _heuristic_durable(candidate: "CrystallizedCandidate") -> dict[str, Any]:
    """Deterministic keyword-based fallback when LLM fails all retries.

    NOT fail-open: requires positive marker match to return True.
    Durable markers checked FIRST (lean-capture priority) — a body
    with both durable and transient markers gets durable_fact=True.
    Returns verdict dict with reason="heuristic_fallback:..."
    The reason includes the specific matched marker for traceability.
    """
    text = (candidate.body or "").lower()
    # Check durable markers FIRST (C1 fix: lean-capture priority)
    # A body with both durable and transient markers should be captured.
    for marker in _DURABLE_MARKERS:
        if marker in text:
            return {"durable_fact": True, "reason": f"heuristic_fallback:durable_marker:{marker}"}
    # Then check transient markers
    for marker in _TRANSIENT_MARKERS:
        if marker in text:
            return {"durable_fact": False, "reason": f"heuristic_fallback:transient_marker:{marker}"}
    return {"durable_fact": False, "reason": "heuristic_fallback:no_markers"}


# ── Verdict schema ───────────────────────────────────────────────────────
VERDICT_SCHEMA_VERSION = "memory-os.fact_judge_verdict.v0"

# ── Durable fact prompt ──────────────────────────────────────────────────
_JUDGE_SYSTEM_PROMPT = (
    "You are a lean-capture durability judge for a memory system. "
    "Your ONLY task: decide whether a conversation snippet is a DURABLE FACT "
    "(worth permanently remembering) or a TRANSIENT MOMENT (should fade away).\n\n"
    "DURABLE FACTS (mark True):\n"
    "- User preferences and tastes (\"I prefer dark mode\", \"I like concise answers\")\n"
    "- Decisions and commitments (\"I'll use PostgreSQL for this project\")\n"
    "- Factual knowledge about the user (\"I work at Acme Corp\", \"My dog is named Max\")\n"
    "- Explicit requests to remember (\"Remember that I...\")\n"
    "- Reusable project context (\"This repo uses pytest with coverage threshold 80%\")\n"
    "- Messy real-world statements that still convey preference/decision/fact:\n"
    '  * "联网做数据复盘完善下注策略" (colloquial decision about strategy) → True\n'
    '  * "三层穿透框架定义" (framework defined in discussion) → True\n\n'
    "TRANSIENT MOMENTS (mark False):\n"
    "- Greetings and pleasantries (\"Hello\", \"Thanks\")\n"
    "- Process and navigation (\"Open the file\", \"Show me the code\")\n"
    "- Momentary emotional states (\"I'm tired today\", \"This is frustrating\")\n"
    "- Pure information requests (\"What does git status do?\")\n"
    "- Content-free chatter with no substantive content\n\n"
    "RULES:\n"
    "1. LEAN TOWARD CAPTURE: if a snippet plausibly states a user preference, "
    "decision, commitment, or fact about the user, mark True — even if phrased "
    "casually or embedded in conversation. Real statements are messy.\n"
    "2. Only mark False for CLEAR transients: greetings, process/navigation, "
    "momentary emotional states, pure info requests, content-free chatter.\n"
    "3. A fact or preference stated once IS durable. Do NOT require repetition "
    "or an explicit \"remember this\" signal.\n\n"
    "Return ONLY a JSON object with keys:\n"
    "- durable_fact: boolean\n"
    "- reason: short string explaining the decision (max 120 chars)\n"
)

# ── Adaptive bias ──────────────────────────────────────────────────────────
LEAN_CAPTURE_THRESHOLD = 50
"""Meta constant: when active crystallized count < this, judge leans toward capture.

NOT in OVERRIDABLE_KNOBS — the judge's own threshold is meta, system cannot self-tune.
"""

_JUDGE_SYSTEM_PROMPT_STRICT = (
    "You are a conservative durability judge for a memory system. "
    "Your ONLY task: decide whether a conversation snippet is a DURABLE FACT "
    "(worth permanently remembering) or a TRANSIENT MOMENT (should fade away).\n\n"
    "DURABLE FACTS (mark True):\n"
    "- User preferences and tastes (\"I prefer dark mode\", \"I like concise answers\")\n"
    "- Decisions and commitments (\"I'll use PostgreSQL for this project\")\n"
    "- Factual knowledge about the user (\"I work at Acme Corp\", \"My dog is named Max\")\n"
    "- Explicit requests to remember (\"Remember that I...\")\n"
    "- Reusable project context (\"This repo uses pytest with coverage threshold 80%\")\n\n"
    "TRANSIENT MOMENTS (mark False):\n"
    "- Greetings and pleasantries (\"Hello\", \"Thanks\")\n"
    "- Process and navigation (\"Open the file\", \"Show me the code\")\n"
    "- Emotional expressions (\"I'm tired today\", \"This is frustrating\")\n"
    "- Pure information requests (\"What does git status do?\")\n"
    "- Inconclusive discussion without closure\n"
    "- Single-turn task instructions with no lasting value\n\n"
    "RULES:\n"
    "1. If UNCERTAIN whether something is durable, answer False. "
    "Only mark True when clearly a lasting preference, decision, or factual knowledge.\n"
    "2. A fact stated once IS durable if it reveals a preference or identity.\n"
    "3. Do NOT mark True for transient emotional states, even if strongly expressed.\n\n"
    "Return ONLY a JSON object with keys:\n"
    "- durable_fact: boolean\n"
    "- reason: short string explaining the decision (max 120 chars)\n"
)


def _count_active_crystallized(store: "MemoryOSStore") -> int:
    """Count active (non-inactive) crystallized records across all .md files."""
    from plugins.memory.memory_os.crystallized import (
        CrystallizedMemoryService,
        is_active_crystallized_frontmatter,
    )
    svc = CrystallizedMemoryService(store)
    crystallized_root = store.roots.crystallized_root
    if not crystallized_root.exists():
        return 0
    count = 0
    for md_path in sorted(crystallized_root.glob("*.md")):
        try:
            records = svc.read_records(md_path.name)
        except Exception:
            continue
        for record in records:
            if is_active_crystallized_frontmatter(record.frontmatter):
                count += 1
    return count


def _adaptive_prompt(active_crystallized_count: int) -> str:
    """Return lean or strict judge prompt based on active crystallized count."""
    if active_crystallized_count < LEAN_CAPTURE_THRESHOLD:
        return _JUDGE_SYSTEM_PROMPT
    return _JUDGE_SYSTEM_PROMPT_STRICT


# ── J1: Jev native-noul mapping (owner ruling 2026-09-23) ───────────────
# TypeSafe's own docs are explicit that a yes/no judgment like this one
# should be a noul question, NOT a 2-option choice: "Use Noul for a yes/no
# judgment... the deciding factor isn't confidence -- it's what the
# probability means" (https://docs.typesafe.ai/primitives.md). Their own
# worked example ("does this message contain PII") is the same shape as
# "is this a durable fact" -- a probability that is directly actionable.
#
# instructions/criteria mirror the same lean/strict asymmetry as
# _JUDGE_SYSTEM_PROMPT vs _JUDGE_SYSTEM_PROMPT_STRICT above, condensed into
# Jev's native {instructions, criteria: {true, false}} shape instead of a
# free-text prompt wrapped as one question (the owner explicitly rejected
# that lower-fidelity mapping).
_JEV_NOUL_INSTRUCTIONS_LEAN = (
    "Is this conversation snippet from a personal memory system a DURABLE "
    "FACT worth permanently remembering, as opposed to a TRANSIENT MOMENT "
    "that should fade away? Lean toward capture: a preference, decision, "
    "commitment, or fact about the user stated once, even casually or "
    "embedded in messy conversation, counts as durable."
)
_JEV_NOUL_CRITERIA_LEAN = {
    "true": (
        "States a user preference, decision, commitment, or fact about the "
        "user (e.g. a stated preference, a decision to use something, "
        "factual knowledge about the user, an explicit request to "
        "remember, or reusable project context) -- even if stated only "
        "once or phrased casually."
    ),
    "false": (
        "Greeting or pleasantry, process/navigation chatter (open/show/"
        "run/check/deploy), a momentary emotional state, a pure "
        "information request, or content-free chatter with no "
        "substantive content about the user."
    ),
}

_JEV_NOUL_INSTRUCTIONS_STRICT = (
    "Is this conversation snippet from a personal memory system a DURABLE "
    "FACT worth permanently remembering -- a clearly lasting user "
    "preference, decision, or factual knowledge -- as opposed to a "
    "TRANSIENT MOMENT? If uncertain, this is NOT a durable fact."
)
_JEV_NOUL_CRITERIA_STRICT = {
    "true": (
        "Clearly states a lasting user preference, decision/commitment, or "
        "factual knowledge about the user. A fact stated once IS durable "
        "if it reveals a preference or identity."
    ),
    "false": (
        "Greeting/pleasantry, process/navigation chatter, an emotional "
        "expression (even if strongly expressed), a pure information "
        "request, inconclusive discussion without closure, or a "
        "single-turn instruction with no lasting value. When uncertain, "
        "this is the default."
    ),
}

# Threshold to convert Jev's noul probability into a boolean durable_fact
# decision. Documented, asymmetric by design (same lean/strict rationale as
# the two prompt variants above): below LEAN_CAPTURE_THRESHOLD active
# crystallized records the lane leans toward capture, so a lower bar (0.4)
# is used; above it, more evidence is required before marking durable
# (0.6). TypeSafe's own docs endorse this: "Lower the threshold when false
# negatives are expensive... Raise the threshold when false positives are
# expensive" (https://docs.typesafe.ai/primitives/noul.md).
_JEV_NOUL_THRESHOLD_LEAN = 0.4
_JEV_NOUL_THRESHOLD_STRICT = 0.6


def _judge_via_jev(body: str, active_crystallized_count: int, config: dict[str, Any]) -> dict[str, Any]:
    """Ask Jev's native noul primitive whether *body* is a durable fact.

    Returns a fact_judge-shaped verdict dict: ``{"durable_fact", "reason",
    "failure_reason", ...}``. ``failure_reason`` is ``None`` on success
    (drawn from :data:`jev_backend.JEV_CALL_FAILURE_REASONS` on failure) --
    callers must treat any non-``None`` failure_reason as "fall back to the
    hermes_default path", never as a False durable_fact answer.
    """
    lean = active_crystallized_count < LEAN_CAPTURE_THRESHOLD
    instructions = _JEV_NOUL_INSTRUCTIONS_LEAN if lean else _JEV_NOUL_INSTRUCTIONS_STRICT
    criteria = _JEV_NOUL_CRITERIA_LEAN if lean else _JEV_NOUL_CRITERIA_STRICT
    threshold = _JEV_NOUL_THRESHOLD_LEAN if lean else _JEV_NOUL_THRESHOLD_STRICT

    result = jev_backend.judge_noul(
        question_id="durable_fact",
        instructions=instructions,
        criteria=criteria,
        state={"candidate_body": body},
        threshold=threshold,
        config=config,
    )
    if result.failure_reason:
        return {
            "durable_fact": False,
            "reason": "",
            "failure_reason": result.failure_reason,
            "jev_failure_detail": result.detail,
        }

    probability_text = f"{result.probability:.2f}" if result.probability is not None else "?"
    return {
        "durable_fact": result.label == "true",
        "reason": _clip_jev_reason(probability_text, threshold),
        "failure_reason": None,
        "judge_backend": jev_backend.JEV_BACKEND_NAME,
        "judge_confidence": result.confidence,
        "jev_probability": result.probability,
        "jev_model": result.model,
        "jev_latency_ms": result.latency_ms,
    }


def _clip_jev_reason(probability_text: str, threshold: float) -> str:
    return f"jev_noul_probability={probability_text}_threshold={threshold}"[:200]


def judge_candidate(
    candidate: CrystallizedCandidate,
    config: dict[str, Any] | None = None,
    *,
    active_crystallized_count: int = 0,
    heuristic_only: bool = False,
    judge_backend: str = "hermes_default",
) -> dict[str, Any]:
    """Judge whether a candidate is a durable fact or a transient moment.

    Args:
        candidate: The inner_drive_candidate to judge.
        config: Optional judge config overrides (provider, timeout_ms, max_tokens).
        heuristic_only: When True, skip LLM entirely and use keyword heuristic
            (emergency knob: ``fact_judge_heuristic_only``).
        judge_backend: ``"hermes_default"`` (default) uses the free-text LLM
            judge below unchanged. ``"typesafe_jev"`` (owner ruling
            2026-09-23, opt-in via the ``fact_judge_judge_backend`` knob)
            asks Jev's native noul primitive first; on ANY Jev failure it
            falls back to this same hermes_default path (never straight to
            heuristic), and the fallback is recorded in
            ``judge_backend_fallback_reason`` on the returned verdict so the
            cron lane can count it (see run_fact_judge_lane). When
            ``judge_backend`` stays at its default, this parameter changes
            nothing below -- default-off is byte-identical.

    Returns:
        {"durable_fact": bool, "reason": str, "failure_reason": str | None}
        On total failure after retries, falls back to heuristic (content-based,
        not fail-open).  The ``failure_reason`` field records *why* the LLM path
        failed (empty_content / parse_failed / missing_key / exception / None
        for success) so the cron lane can produce accurate error telemetry.
    """
    if heuristic_only:
        verdict = _heuristic_durable(candidate)
        verdict["failure_reason"] = "heuristic_only_knob"
        return verdict

    effective_config = dict(DEFAULT_JUDGE_CONFIG, **(config or {}))
    body = str(candidate.body or "").strip()
    if not body:
        return {"durable_fact": False, "reason": "empty_body", "failure_reason": None}

    # Truncate very long bodies to keep the prompt reasonable
    body_for_prompt = body[:2000]

    # J1: try the optional Jev backend first when selected. ANY failure here
    # (missing key, network, HTTP, parse) falls through to the unchanged
    # hermes_default path below rather than straight to heuristic -- this is
    # a typed, counted fallback, not a silent one (see
    # judge_backend_fallback_reason threaded into both return points below).
    jev_fallback_reason: str | None = None
    jev_fallback_detail = ""
    if judge_backend == jev_backend.JEV_BACKEND_NAME:
        jev_verdict = _judge_via_jev(body_for_prompt, active_crystallized_count, effective_config)
        if jev_verdict.get("failure_reason") is None:
            return jev_verdict
        jev_fallback_reason = str(jev_verdict.get("failure_reason") or "")
        jev_fallback_detail = str(jev_verdict.get("jev_failure_detail") or "")[:160]

    user_prompt = (
        f'Candidate ID: {candidate.candidate_id}\n'
        f'Kind: {candidate.kind}\n'
        f'Body: """{body_for_prompt}"""\n\n'
        f'Is this a durable fact or a transient moment? Return JSON.'
    )

    system_prompt = _adaptive_prompt(active_crystallized_count)
    prompt = f"{system_prompt}\n\n{user_prompt}"

    # Retry loop: empty / non-JSON / missing-key responses get retried
    last_failure: str | None = None
    last_call_result: LlmCallResult | None = None
    for attempt in range(1 + MAX_JUDGE_RETRIES):  # 1 initial + N retries
        try:
            call_result = _call_hermes_runtime_model_result(prompt, effective_config)
        except Exception:
            # Defensive only: _call_hermes_runtime_model_result is designed to
            # never raise (every failure is a typed LlmCallResult), but this
            # guard is kept so a genuinely unexpected exception still degrades
            # to the heuristic fallback instead of crashing the lane.
            last_failure = "llm_exception"
            if attempt < MAX_JUDGE_RETRIES:
                continue
            break
        last_call_result = call_result

        if call_result.failure_reason == "llm_empty_content":
            last_failure = "llm_empty_content"
            if attempt < MAX_JUDGE_RETRIES:
                continue
            break
        if call_result.failure_reason:
            # Any other typed transport failure (transport_unavailable,
            # http_4xx, timeout, missing_key/credential, exception) --
            # this module's own "llm_exception" bucket covers all of them,
            # matching the pre-W2 behavior where the legacy wire collapsed
            # every non-empty-response failure to a bare "". The raw,
            # finer-grained reason survives in _call_diagnostics below.
            last_failure = "llm_exception"
            if attempt < MAX_JUDGE_RETRIES:
                continue
            break

        response_text = call_result.text
        try:
            parsed = _extract_json_object(response_text)
        except Exception:
            last_failure = "llm_parse_failed"
            if attempt < MAX_JUDGE_RETRIES:
                continue
            break

        if not isinstance(parsed, dict):
            last_failure = "llm_parse_failed"
            if attempt < MAX_JUDGE_RETRIES:
                continue
            break

        durable = parsed.get("durable_fact")
        if not isinstance(durable, bool):
            last_failure = "llm_missing_key"
            if attempt < MAX_JUDGE_RETRIES:
                continue
            break

        # Successful parse with valid durable_fact
        reason = str(parsed.get("reason") or "")[:200]
        result = {
            "durable_fact": durable,
            "reason": reason,
            "failure_reason": None,
            **_call_diagnostics(call_result),
        }
        if jev_fallback_reason:
            result["judge_backend_fallback_reason"] = jev_fallback_reason
            result["judge_backend_fallback_detail"] = jev_fallback_detail
        return result

    # All attempts exhausted — fall back to deterministic heuristic
    verdict = _heuristic_durable(candidate)
    verdict["failure_reason"] = last_failure
    verdict.update(_call_diagnostics(last_call_result))
    if jev_fallback_reason:
        verdict["judge_backend_fallback_reason"] = jev_fallback_reason
        verdict["judge_backend_fallback_detail"] = jev_fallback_detail
    return verdict


def run_fact_judge_lane(
    store: MemoryOSStore,
    *,
    now: datetime | None = None,
    execution_gate_envelope_id: str = "",
) -> dict[str, Any]:
    """Run one tick of the fact_judge cron lane.

    Reads all inner_drive_candidates, judges each for durable_fact,
    and writes verdicts to the sidecar JSONL file.

    Does NOT mutate candidates — only writes verdicts for the aggregation
    lane to consume.

    Config is resolved from knobs (``fact_judge_max_tokens``,
    ``fact_judge_max_per_tick``, ``fact_judge_timeout_ms``,
    ``fact_judge_heuristic_only``).  A bounded per-tick drain
    (``max_per_tick``, default 8) prevents unbounded backlog blow-up
    from dragging down the cron window.
    """
    _now = now or datetime.now(timezone.utc)

    # ── Resolve knobs ──────────────────────────────────────────────────
    from plugins.memory.memory_os.knob_overrides import resolve_knob

    def _safe_int_knob(name: str, default: int) -> int:
        """Resolve *name* and coerce to int; fall back to *default* on any error.

        Guards against non-numeric override values (e.g. a string ``"true"``
        written to the knob-override store) that would cause ``int()`` to raise
        ``ValueError`` and crash the lane.
        """
        raw = resolve_knob(name, default=default, roots=store.roots)
        try:
            return int(raw)
        except (ValueError, TypeError):
            return default

    judge_config: dict[str, Any] = dict(DEFAULT_JUDGE_CONFIG)
    judge_config["max_tokens"] = _safe_int_knob(
        "fact_judge_max_tokens", DEFAULT_JUDGE_CONFIG["max_tokens"],
    )
    judge_config["max_per_tick"] = _safe_int_knob(
        "fact_judge_max_per_tick", DEFAULT_JUDGE_CONFIG["max_per_tick"],
    )
    judge_config["timeout_ms"] = _safe_int_knob(
        "fact_judge_timeout_ms", DEFAULT_JUDGE_CONFIG["timeout_ms"],
    )
    # Strict identity check: only the Python bool True enables the lane switch.
    # ``bool("false")`` / ``bool("0")`` would be True — reject those.
    heuristic_only = (
        resolve_knob("fact_judge_heuristic_only", default=False, roots=store.roots)
        is True
    )

    # J1: judge_backend knob override wins over lane config (same precedence
    # as low_clue_recall._resolve_llm_transport) -- resolved once per tick
    # rather than per-candidate, matching how heuristic_only is resolved
    # above. Default "hermes_default" is untouched by this resolution when
    # no override is registered, so the rest of the lane behaves exactly as
    # before J1.
    judge_backend = str(
        resolve_knob(
            "fact_judge_judge_backend",
            default=str(judge_config.get("judge_backend") or "hermes_default"),
            roots=store.roots,
        )
        or "hermes_default"
    )
    if judge_backend not in ("hermes_default", jev_backend.JEV_BACKEND_NAME):
        judge_backend = "hermes_default"
    judge_config["judge_backend"] = judge_backend

    max_per_tick = _safe_int_knob("fact_judge_max_per_tick", 8)
    # ───────────────────────────────────────────────────────────────────

    active_count = _count_active_crystallized(store)
    candidates = read_candidate_queue(store)

    # Only judge inner_drive candidates that haven't been judged yet
    existing_verdicts = _read_verdicts(store)
    already_judged: set[str] = set(existing_verdicts.keys())

    judged_count = 0
    durable_count = 0
    skipped_count = 0
    error_count = 0
    # W2: typed transport diagnostics, aggregated across this tick's calls.
    llm_transport_failures_by_reason: dict[str, int] = {}
    llm_provider = ""
    llm_model = ""
    llm_transport = ""
    llm_usage_prompt_tokens = 0
    llm_usage_completion_tokens = 0
    # W4-A / plan row L1: route-mismatch counters, plus a sample of the
    # expected/actual model names from the most recent mismatch this tick
    # (see LlmCallResult's docstring for the route_unexpected/route_unknown
    # definition and the alias-handling note).
    llm_route_unexpected_count = 0
    llm_route_unknown_count = 0
    llm_route_unexpected_expected_model = ""
    llm_route_unexpected_actual_model = ""
    # J1: optional Jev backend diagnostics, aggregated across this tick.
    judge_confidence: float | None = None
    judge_backend_fallback_count = 0
    judge_backend_fallback_reasons: dict[str, int] = {}
    judge_backend_fallback_detail_sample = ""

    for candidate in candidates:
        if candidate.candidate_id in already_judged:
            skipped_count += 1
            continue

        # Only judge inner_drive_candidate bridge states
        if candidate.bridge_state not in ("", "inner_drive_candidate"):
            continue

        # Bounded drain: stop when we've judged enough this tick
        if judged_count >= max_per_tick:
            skipped_count += 1
            continue

        verdict = judge_candidate(
            candidate,
            config=judge_config,
            active_crystallized_count=active_count,
            heuristic_only=heuristic_only,
            judge_backend=judge_backend,
        )
        judged_count += 1

        if verdict.get("durable_fact"):
            durable_count += 1

        # ── Failure telemetry ──────────────────────────────────────────
        failure_reason = str(verdict.get("failure_reason") or "")
        if failure_reason:
            error_count += 1
        # ─────────────────────────────────────────────────────────────────

        # ── W2 transport diagnostics ────────────────────────────────────
        transport_reason = str(verdict.get("llm_transport_failure_reason") or "")
        if transport_reason:
            llm_transport_failures_by_reason[transport_reason] = (
                llm_transport_failures_by_reason.get(transport_reason, 0) + 1
            )
        if verdict.get("llm_provider"):
            llm_provider = str(verdict["llm_provider"])
        if verdict.get("llm_model"):
            llm_model = str(verdict["llm_model"])
        if verdict.get("llm_transport"):
            llm_transport = str(verdict["llm_transport"])
        llm_usage_prompt_tokens += int(verdict.get("llm_usage_prompt_tokens") or 0)
        llm_usage_completion_tokens += int(verdict.get("llm_usage_completion_tokens") or 0)
        if verdict.get("llm_route_unexpected"):
            llm_route_unexpected_count += 1
            llm_route_unexpected_expected_model = str(verdict.get("llm_expected_model") or "")
            llm_route_unexpected_actual_model = str(verdict.get("llm_actual_model") or "")
        if verdict.get("llm_route_unknown"):
            llm_route_unknown_count += 1
        # ─────────────────────────────────────────────────────────────────

        # ── J1 Jev backend diagnostics ──────────────────────────────────
        verdict_judge_backend = verdict.get("judge_backend")
        verdict_judge_confidence = verdict.get("judge_confidence")
        if verdict_judge_confidence is not None:
            judge_confidence = float(verdict_judge_confidence)
        fallback_reason = str(verdict.get("judge_backend_fallback_reason") or "")
        if fallback_reason:
            # Keep one clipped sample of the backend's own error text so the
            # reason bucket can be diagnosed from the report alone.
            judge_backend_fallback_detail_sample = str(verdict.get("judge_backend_fallback_detail") or "")[:160]
            judge_backend_fallback_count += 1
            judge_backend_fallback_reasons[fallback_reason] = (
                judge_backend_fallback_reasons.get(fallback_reason, 0) + 1
            )
        # ─────────────────────────────────────────────────────────────────

        _append_verdict(
            store,
            candidate_id=candidate.candidate_id,
            durable_fact=bool(verdict.get("durable_fact")),
            reason=str(verdict.get("reason") or ""),
            failure_reason=failure_reason or None,
            now=_now,
            judge_backend=str(verdict_judge_backend) if verdict_judge_backend else None,
            judge_confidence=float(verdict_judge_confidence) if verdict_judge_confidence is not None else None,
        )

    return {
        "schema_version": VERDICT_SCHEMA_VERSION,
        "status": "ok",
        "candidates_read": len(candidates),
        "judged_count": judged_count,
        "durable_count": durable_count,
        "moment_count": judged_count - durable_count,
        "skipped_count": skipped_count,
        "error_count": error_count,
        "profile": store.roots.profile or "default",
        "action": "fact_judge_tick",
        "actual_send": False,
        "actual_execute": False,
        "actual_identity_write": False,
        "actual_crystallized_approval": False,
        # W2: typed LLM transport diagnostics (ADD-only; does not replace
        # error_count/failure_reason, which keep their pre-W2 meaning).
        "llm_transport_failures_by_reason": llm_transport_failures_by_reason,
        "llm_provider": llm_provider,
        "llm_model": llm_model,
        "llm_transport": llm_transport,
        "llm_usage_prompt_tokens": llm_usage_prompt_tokens,
        "llm_usage_completion_tokens": llm_usage_completion_tokens,
        # W4-A / plan row L1: route-mismatch counters (ADD-only).
        "llm_route_unexpected_count": llm_route_unexpected_count,
        "llm_route_unknown_count": llm_route_unknown_count,
        "llm_route_unexpected_expected_model": llm_route_unexpected_expected_model,
        "llm_route_unexpected_actual_model": llm_route_unexpected_actual_model,
        # J1: optional Jev judge-backend diagnostics (ADD-only). judge_backend
        # is the resolved backend for this tick ("hermes_default" unless the
        # fact_judge_judge_backend knob selects "typesafe_jev").
        # judge_backend_fallback_count/reasons count ticks where Jev was
        # selected but failed and this tick fell back to hermes_default --
        # Completion Is Not Output: a clean envelope alone cannot distinguish
        # "Jev worked" from "Jev failed and fell back silently" without this.
        "judge_backend": judge_backend,
        "judge_confidence": judge_confidence,
        "judge_backend_fallback_count": judge_backend_fallback_count,
        "judge_backend_fallback_reasons": judge_backend_fallback_reasons,
        "judge_backend_fallback_detail_sample": judge_backend_fallback_detail_sample,
    }


def _verdicts_path(store: MemoryOSStore) -> Path:
    return store.roots.memory_os_root / "system-modules" / "fact_judge" / "verdicts.jsonl"


def _read_verdicts(store: MemoryOSStore) -> dict[str, dict[str, Any]]:
    """Read all existing verdicts into a candidate_id-keyed map."""
    path = _verdicts_path(store)
    if not path.exists():
        return {}
    verdicts: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        cid = str(record.get("candidate_id") or "")
        if cid:
            verdicts[cid] = record
    return verdicts


def _append_verdict(
    store: MemoryOSStore,
    *,
    candidate_id: str,
    durable_fact: bool,
    reason: str,
    failure_reason: str | None = None,
    now: datetime,
    judge_backend: str | None = None,
    judge_confidence: float | None = None,
) -> None:
    path = _verdicts_path(store)
    record = {
        "schema_version": VERDICT_SCHEMA_VERSION,
        "candidate_id": candidate_id,
        "durable_fact": durable_fact,
        "reason": reason,
        "judged_at": now.isoformat(),
    }
    if failure_reason:
        record["failure_reason"] = failure_reason
    # J1: only stamped when the Jev backend actually produced this verdict --
    # hermes_default-path records (the default, always, when the feature is
    # off) keep their exact pre-J1 shape.
    if judge_backend:
        record["judge_backend"] = judge_backend
    if judge_confidence is not None:
        record["judge_confidence"] = judge_confidence
    from plugins.memory.memory_os.jsonl_io import append_jsonl_locked

    append_jsonl_locked(path, record)


def read_fact_judge_verdicts(store: MemoryOSStore) -> dict[str, bool]:
    """Public reader for the aggregation lane: returns {candidate_id: durable_fact}.

    Only returns verdicts where durable_fact is True — the aggregation lane
    only cares about which candidates get the single-item bypass.
    """
    all_verdicts = _read_verdicts(store)
    return {
        cid: bool(record.get("durable_fact"))
        for cid, record in all_verdicts.items()
        if record.get("durable_fact") is True
    }
