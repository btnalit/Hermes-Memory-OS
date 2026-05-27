#!/usr/bin/env python3
"""Render a bounded MemorySources feedback prompt for Hermes agent delivery.

This script does not send messages and does not write Memory-OS state. Hermes
cron owns delivery and the Hermes agent owns the owner interaction. Empty
stdout means there is no suitable feedback context to ask about.
"""

from __future__ import annotations

import json
import subprocess
import sys


def main() -> int:
    report = _run_json(
        [
            "hermes",
            "memory-os-agent-os",
            "review",
            "surface",
            "--operation",
            "memory_sources_feedback_context",
            "--limit",
            "3",
        ]
    )
    if report.get("status") != "ok":
        return 0
    item = report.get("latest_memory_source")
    if not isinstance(item, dict):
        return 0
    token = str((item.get("action_tokens") or {}).get("mark_feedback") or "").strip()
    if not token:
        return 0

    examples = [str(value) for value in item.get("owner_utterance_examples") or []]
    source_classes = ", ".join(str(value) for value in item.get("source_classes") or []) or "unknown"
    route = str(item.get("route") or item.get("query_class") or "unknown")
    selected_count = int(item.get("selected_count") or 0)
    selected_chars = int(item.get("selected_chars_total") or 0)
    consequence = str(item.get("consequence") or "")

    print("Memory-OS MemorySources feedback request")
    print()
    print("请用中文、自然地向用户询问下面这个上下文/记忆来源是否有帮助。")
    print("不要称呼 Owner，不要展示内部 record id，不要替用户判断。")
    print("这次只收一个 rating；如果用户一次给出多个 rating，先反问确认，不要一起提交。")
    print("用户说清楚后，再调用结构化工具 memory_os_review_reply。")
    print()
    print(f"- target_type: memory_source")
    print(f"- action_token: {token}")
    print(f"- route/query_class: {route}")
    print(f"- source_classes: {source_classes}")
    print(f"- selected_count: {selected_count}")
    print(f"- selected_chars_total: {selected_chars}")
    if consequence:
        print(f"- consequence: {consequence}")
    print()
    print("用户可以选择的反馈：")
    print("- useful: 这次上下文有帮助")
    print("- missing_context: 缺了关键上下文")
    print("- too_mechanistic: 太机制化/程序味")
    print("- needs_specific_recall: 需要更具体的召回")
    print()
    print("建议只问这个问题：")
    print("这次 Memory-OS 为候选/审批上下文选出来的来源，对你刚才的判断有帮助吗？")
    print()
    print("如果用户明确选择一个 rating，调用：")
    print('memory_os_review_reply({ "action": "feedback", "action_token": "' + token + '", "rating": "<owner_rating>" })')
    print()
    print("可展示给用户的会话回复示例：")
    for example in examples[:4]:
        print(f"- {example}")
    return 0


def _run_json(command: list[str]) -> dict[str, object]:
    try:
        completed = subprocess.run(command, check=True, text=True, capture_output=True)
    except FileNotFoundError as exc:
        raise SystemExit("hermes command not found; cannot render MemorySources feedback prompt") from exc
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(exc.stderr or exc.stdout or str(exc))
        raise SystemExit(exc.returncode) from exc
    try:
        parsed = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"MemorySources feedback context did not return JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise SystemExit("MemorySources feedback context returned non-object JSON")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
