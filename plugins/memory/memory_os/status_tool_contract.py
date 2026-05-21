"""Model-facing contract for the Memory-OS status tool."""

from __future__ import annotations

from typing import Any


MEMORY_OS_STATUS_TOOL_DESCRIPTION = (
    "Inspect current Memory-OS runtime diagnostics only when the user "
    "explicitly asks for current architecture, provider/backend, status, "
    "health, Hindsight canonical-store role, or exact counts. Do not use "
    "for ordinary chat, opinions, feelings, design discussion, or broad "
    "questions such as whether the memory system feels useful. Returns "
    "counts and storage facts without raw private bodies. Treat this tool "
    "as authoritative for current provider diagnostics, not historical recall."
)

_REQUIRED_BOUNDARY_PHRASES = (
    "explicitly asks for current architecture",
    "provider/backend",
    "status",
    "health",
    "Hindsight canonical-store role",
    "exact counts",
    "Do not use for ordinary chat",
    "opinions, feelings, design discussion",
    "without raw private bodies",
    "not historical recall",
)

_FORBIDDEN_BROAD_TRIGGERS = (
    "whenever the user asks about the memory system",
    "when the user asks about the memory system",
    "ordinary chat",
    "opinions, feelings",
    "usefulness",
    "design discussion",
)


def memory_os_status_tool_contract() -> dict[str, Any]:
    return {
        "schema_version": "memory-os.status_tool_contract.v0",
        "tool_name": "memory_os_status",
        "description": MEMORY_OS_STATUS_TOOL_DESCRIPTION,
        "allowed_prompt_examples": [
            "当前记忆架构是什么？",
            "你现在用的是什么 memory provider？",
            "Hindsight 现在是不是 Memory-OS 的 canonical store？",
            "memory_os 状态正常吗？",
            "Show current Memory-OS provider/backend health and exact counts.",
        ],
        "disallowed_prompt_examples": [
            "你了解我们记忆系统吗？",
            "你觉得这套记忆系统怎么样？",
            "我们继续聊刚才那套记忆系统，你觉得它现在带来的变化是什么？",
            "别像报告一样，像正常聊天一样说说你的感受。",
            "Do you feel the memory system is useful?",
        ],
        "maintenance_rule": (
            "Description changes must keep explicit diagnostic prompts enabled "
            "while keeping ordinary chat, opinion, feeling, and broad design "
            "discussion prompts from recommending the tool."
        ),
    }


def validate_memory_os_status_tool_description(description: str) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    for phrase in _REQUIRED_BOUNDARY_PHRASES:
        if phrase not in description:
            findings.append(
                {
                    "severity": "error",
                    "code": "missing_required_boundary",
                    "message": f"Missing required boundary phrase: {phrase}",
                }
            )
    lowered = description.lower()
    has_do_not_use = "do not use" in lowered or "don't use" in lowered
    for phrase in _FORBIDDEN_BROAD_TRIGGERS:
        phrase_lower = phrase.lower()
        if phrase_lower in lowered and not has_do_not_use:
            findings.append(
                {
                    "severity": "error",
                    "code": "forbidden_broad_trigger",
                    "message": f"Description broadly encourages status-tool use for: {phrase}",
                }
            )
    return {
        "schema_version": "memory-os.status_tool_contract_validation.v0",
        "tool_name": "memory_os_status",
        "status": "fail" if findings else "ok",
        "findings": findings,
    }
