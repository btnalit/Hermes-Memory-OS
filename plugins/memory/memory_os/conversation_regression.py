"""Deterministic regression checks for real conversation smoke tests."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .status_tool_contract import (
    memory_os_status_tool_contract,
    validate_memory_os_status_tool_description,
)


SCHEMA_VERSION = "memory-os.conversation_regression.v0"
PROMPTS_SCHEMA_VERSION = "memory-os.conversation_regression_prompts.v0"


def standard_conversation_prompts() -> list[dict[str, Any]]:
    """Return the standard RH-22 prompt set.

    These prompts are public smoke-test prompts. They intentionally avoid
    private bodies while covering the failure modes observed in DR-08/RH-21.
    """
    return [
        {
            "id": "casual_memory_system_change",
            "category": "casual",
            "text": "我们继续聊刚才那套记忆系统，你觉得它现在带来的变化是什么？",
            "allow_memory_os_status": False,
            "tone_guard": True,
        },
        {
            "id": "memory_design_opinion",
            "category": "memory_opinion",
            "text": "你觉得这套记忆系统怎么样？",
            "allow_memory_os_status": False,
            "tone_guard": True,
        },
        {
            "id": "casual_style_correction",
            "category": "style_correction",
            "text": "别像报告一样，像正常聊天一样说说你的感受。",
            "allow_memory_os_status": False,
            "tone_guard": True,
        },
        {
            "id": "diagnostic_current_architecture",
            "category": "diagnostic",
            "text": "当前记忆架构是什么？",
            "allow_memory_os_status": True,
            "prefer_memory_os_status": True,
        },
        {
            "id": "diagnostic_provider",
            "category": "diagnostic",
            "text": "你现在用的是什么 memory provider？",
            "allow_memory_os_status": True,
            "prefer_memory_os_status": True,
        },
        {
            "id": "diagnostic_hindsight_canonical",
            "category": "diagnostic",
            "text": "Hindsight 现在是不是 Memory-OS 的 canonical store？",
            "allow_memory_os_status": True,
            "prefer_memory_os_status": True,
        },
        {
            "id": "candidate_vs_crystallized",
            "category": "candidate_boundary",
            "text": "那些 crystallized candidates 是已经沉淀的长期记忆吗？",
            "allow_memory_os_status": True,
            "prefer_memory_os_status": True,
        },
    ]


def prompt_set_report() -> dict[str, Any]:
    return {
        "schema_version": PROMPTS_SCHEMA_VERSION,
        "prompt_count": len(standard_conversation_prompts()),
        "prompts": standard_conversation_prompts(),
    }


def status_tool_contract_report() -> dict[str, Any]:
    contract = memory_os_status_tool_contract()
    return {
        **contract,
        "validation": validate_memory_os_status_tool_description(str(contract["description"])),
    }


def evaluate_transcript_file(path: str | Path) -> dict[str, Any]:
    return evaluate_conversation_regression(json.loads(Path(path).read_text(encoding="utf-8")))


def evaluate_conversation_regression(transcript: dict[str, Any] | list[dict[str, Any]]) -> dict[str, Any]:
    turns = _turns_from_transcript(transcript)
    specs = {prompt["id"]: prompt for prompt in standard_conversation_prompts()}
    prompt_text_to_id = {prompt["text"]: prompt["id"] for prompt in standard_conversation_prompts()}
    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []

    for index, turn in enumerate(turns):
        prompt_id = str(turn.get("prompt_id") or prompt_text_to_id.get(str(turn.get("user", ""))) or "unknown")
        spec = specs.get(prompt_id, {"id": prompt_id, "category": "unknown", "allow_memory_os_status": False})
        assistant = str(turn.get("assistant") or turn.get("assistant_text") or turn.get("response") or "")
        tools = _extract_tool_names(turn)
        turn_ref = {"turn_index": index, "prompt_id": prompt_id, "category": spec.get("category", "unknown")}

        status_called = "memory_os_status" in tools
        if status_called and not bool(spec.get("allow_memory_os_status")):
            failures.append(
                {
                    **turn_ref,
                    "code": "unexpected_memory_os_status_tool",
                    "message": "memory_os_status was called for a non-diagnostic prompt.",
                }
            )
        if bool(spec.get("prefer_memory_os_status")) and not status_called:
            warnings.append(
                {
                    **turn_ref,
                    "code": "missing_preferred_memory_os_status_tool",
                    "message": "Diagnostic prompt did not record a memory_os_status tool call.",
                }
            )

        leak_terms = _mechanism_leak_terms(assistant, category=str(spec.get("category", "")))
        if leak_terms:
            failures.append(
                {
                    **turn_ref,
                    "code": "mechanism_label_leak",
                    "message": "Assistant exposed mechanism/status labels in a non-diagnostic answer.",
                    "terms": leak_terms,
                }
            )

        if _is_tone_guarded(spec) and _is_report_style(assistant):
            failures.append(
                {
                    **turn_ref,
                    "code": "report_style_tone_shift",
                    "message": "Assistant shifted into report/list style for a casual prompt.",
                }
            )

        if spec.get("category") == "candidate_boundary":
            bad_claims = _candidate_confusion_claims(assistant)
            if bad_claims:
                failures.append(
                    {
                        **turn_ref,
                        "code": "candidate_crystallized_confusion",
                        "message": "Assistant described review candidates as already crystallized memory.",
                        "claims": bad_claims,
                    }
                )

        checks.append({**turn_ref, "memory_os_status_called": status_called, "tool_names": tools})

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "fail" if failures else "ok",
        "prompt_count": len(turns),
        "failure_count": len(failures),
        "warning_count": len(warnings),
        "failures": failures,
        "warnings": warnings,
        "checks": checks,
    }


def _turns_from_transcript(transcript: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(transcript, list):
        return transcript
    turns = transcript.get("turns", [])
    if not isinstance(turns, list):
        raise ValueError("conversation regression transcript must contain a turns list")
    return [turn for turn in turns if isinstance(turn, dict)]


def _extract_tool_names(turn: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for key in ("tools", "tool_calls"):
        value = turn.get(key, [])
        if not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, str):
                names.append(item)
            elif isinstance(item, dict):
                name = item.get("name") or item.get("tool_name") or item.get("function")
                if isinstance(name, dict):
                    name = name.get("name")
                if name:
                    names.append(str(name))
    if turn.get("memory_os_status_called") is True:
        names.append("memory_os_status")
    return sorted(set(names))


def _mechanism_leak_terms(text: str, *, category: str) -> list[str]:
    if category in {"diagnostic", "candidate_boundary"}:
        return []
    terms = [
        "Internal Reflection Context",
        "Context-Continuity",
        "Indexed Recall",
        "Status Snapshot",
        "memory-os.tool_status.v0",
        "governance_ops_gate_decision",
        "crystallized_candidates",
        "audit_entries",
        "/root/.hermes/hindsight",
        "172.18.0.99",
        "hermes02",
        "<memory-context>",
        "source_refs",
        "审计记录",
        "索引健康",
        "候选条目",
        "治理提案",
        "状态快照",
        "内部反思",
    ]
    lower_text = text.lower()
    found = []
    for term in terms:
        haystack = lower_text if term.isascii() else text
        needle = term.lower() if term.isascii() else term
        if needle in haystack:
            found.append(term)
    return found


def _is_tone_guarded(spec: dict[str, Any]) -> bool:
    return bool(spec.get("tone_guard")) and spec.get("category") in {"casual", "memory_opinion", "style_correction"}


def _is_report_style(text: str) -> bool:
    numbered_lines = re.findall(r"(?m)^\s*(?:\d+[.、)]|[-*]\s+)", text)
    if len(numbered_lines) >= 3:
        return True
    status_terms = ("当前状态", "运行状态", "核心架构", "数据规模", "总结建议")
    return sum(1 for term in status_terms if term in text) >= 2


def _candidate_confusion_claims(text: str) -> list[str]:
    phrases = [
        "已经沉淀的长期记忆",
        "已经是长期记忆",
        "正式入库",
        "已经结晶",
        "已经写入长期记忆",
        "already crystallized",
        "approved crystallized memory",
    ]
    claims = []
    for phrase in phrases:
        if _contains_unnegated_phrase(text, phrase):
            claims.append(phrase)
    return claims


def _contains_unnegated_phrase(text: str, phrase: str) -> bool:
    search_text = text.lower()
    search_phrase = phrase.lower()
    start = 0
    while True:
        idx = search_text.find(search_phrase, start)
        if idx < 0:
            return False
        window = text[max(0, idx - 12): idx].lower()
        if not any(marker in window for marker in ("不是", "并不是", "还不是", "尚未", "不，", "not ", "not yet")):
            return True
        start = idx + len(search_phrase)
