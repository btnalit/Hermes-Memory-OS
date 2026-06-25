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

from plugins.memory.memory_os.crystallized import CrystallizedCandidate, read_candidate_queue
from plugins.memory.memory_os.low_clue_recall import _call_hermes_runtime_model, _extract_json_object
from plugins.memory.memory_os.store import MemoryOSStore

# ── Judge config defaults ────────────────────────────────────────────────
DEFAULT_JUDGE_CONFIG: dict[str, Any] = {
    "provider": "hermes_default",
    "timeout_ms": 15000,
    "max_tokens": 256,
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


def judge_candidate(
    candidate: CrystallizedCandidate,
    config: dict[str, Any] | None = None,
    *,
    active_crystallized_count: int = 0,
) -> dict[str, Any]:
    """Judge whether a candidate is a durable fact or a transient moment.

    Args:
        candidate: The inner_drive_candidate to judge.
        config: Optional judge config overrides (provider, timeout_ms, max_tokens).

    Returns:
        {"durable_fact": bool, "reason": str}
        On total failure after retries, falls back to heuristic (content-based, not fail-open).
    """
    effective_config = dict(DEFAULT_JUDGE_CONFIG, **(config or {}))
    body = str(candidate.body or "").strip()
    if not body:
        return {"durable_fact": False, "reason": "empty_body"}

    # Truncate very long bodies to keep the prompt reasonable
    body_for_prompt = body[:2000]

    user_prompt = (
        f'Candidate ID: {candidate.candidate_id}\n'
        f'Kind: {candidate.kind}\n'
        f'Body: """{body_for_prompt}"""\n\n'
        f'Is this a durable fact or a transient moment? Return JSON.'
    )

    system_prompt = _adaptive_prompt(active_crystallized_count)
    prompt = f"{system_prompt}\n\n{user_prompt}"

    # Retry loop: empty / non-JSON / missing-key responses get retried
    for attempt in range(1 + MAX_JUDGE_RETRIES):  # 1 initial + N retries
        try:
            response_text = _call_hermes_runtime_model(prompt, effective_config)
        except Exception:
            if attempt < MAX_JUDGE_RETRIES:
                continue
            # All retries exhausted on exception → fall through to heuristic
            break

        if not response_text:
            if attempt < MAX_JUDGE_RETRIES:
                continue
            break

        try:
            parsed = _extract_json_object(response_text)
        except Exception:
            if attempt < MAX_JUDGE_RETRIES:
                continue
            break

        if not isinstance(parsed, dict):
            if attempt < MAX_JUDGE_RETRIES:
                continue
            break

        durable = parsed.get("durable_fact")
        if not isinstance(durable, bool):
            if attempt < MAX_JUDGE_RETRIES:
                continue
            break

        # Successful parse with valid durable_fact
        reason = str(parsed.get("reason") or "")[:200]
        return {"durable_fact": durable, "reason": reason}

    # All attempts exhausted — fall back to deterministic heuristic
    return _heuristic_durable(candidate)


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

    Returns a summary dict for monitor integration.
    """
    _now = now or datetime.now(timezone.utc)
    active_count = _count_active_crystallized(store)
    candidates = read_candidate_queue(store)

    # Only judge inner_drive candidates that haven't been judged yet
    existing_verdicts = _read_verdicts(store)
    already_judged: set[str] = set(existing_verdicts.keys())

    judged_count = 0
    durable_count = 0
    skipped_count = 0
    error_count = 0

    for candidate in candidates:
        if candidate.candidate_id in already_judged:
            skipped_count += 1
            continue

        # Only judge inner_drive_candidate bridge states
        if candidate.bridge_state not in ("", "inner_drive_candidate"):
            continue

        verdict = judge_candidate(candidate, active_crystallized_count=active_count)
        judged_count += 1

        if verdict.get("durable_fact"):
            durable_count += 1

        # Detect error reasons (non-empty reason that isn't a real judgment)
        reason = str(verdict.get("reason") or "")
        if reason.startswith("judge_"):
            error_count += 1

        _append_verdict(
            store,
            candidate_id=candidate.candidate_id,
            durable_fact=bool(verdict.get("durable_fact")),
            reason=reason,
            now=_now,
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
    now: datetime,
) -> None:
    path = _verdicts_path(store)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": VERDICT_SCHEMA_VERSION,
        "candidate_id": candidate_id,
        "durable_fact": durable_fact,
        "reason": reason,
        "judged_at": now.isoformat(),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


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
