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

MEMORY_OS_REVIEW_REPLY_TOOL_DESCRIPTION = (
    "Apply a Memory-OS owner review action after the Hermes agent has "
    "understood the owner's interactive approval intent. Use structured "
    "arguments only: action=`approve|reject|allow|feedback` plus action_token="
    "`oa_<token>` and, for feedback, rating. Do not send a free-form command "
    "string. Use only when the latest owner message clearly asks to apply a "
    "specific owner review token, or after the agent has clarified the target. "
    "Do not use for ordinary chat, questions about Memory-OS, messages that "
    "merely mention a token, display anchors such as A1/R1 without resolving "
    "the matching token, or broad approval language without a confirmed oa_ "
    "action token. The tool routes through OwnerActionProcessor and never "
    "sends, executes work, writes identity, or approves crystallized memory "
    "without the matching owner action token."
)

MEMORY_OS_REVIEW_SURFACE_TOOL_DESCRIPTION = (
    "Read bounded Memory-OS owner-review surface data for Hermes agent "
    "conversation. Use when the owner asks for more review items, next page, "
    "an item detail such as '展开 R3', approved-proposal follow-up status, "
    "feedback context for the latest right-brain expression outcome, or "
    "feedback context for latest MemorySources recall/context quality. "
    "This tool is read-only: it never approves, rejects, sends, executes, "
    "writes identity, or writes crystallized memory. Hermes agent owns the "
    "Chinese explanation, pagination wording, and clarifying questions. "
    "Use memory_os_review_reply separately only after the owner gives a "
    "specific stable oa_ action token and clear action intent."
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
