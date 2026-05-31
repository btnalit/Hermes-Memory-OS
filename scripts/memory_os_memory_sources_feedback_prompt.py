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
    existing_feedback = report.get("existing_feedback") if isinstance(report.get("existing_feedback"), dict) else {}
    if int(existing_feedback.get("count") or 0) > 0:
        return 0
    token = str((item.get("action_tokens") or {}).get("mark_feedback") or "").strip()
    if not token:
        return 0

    source_classes = ", ".join(str(value) for value in item.get("source_classes") or []) or "unknown"
    route = str(item.get("route") or item.get("query_class") or "unknown")
    selected_count = int(item.get("selected_count") or 0)
    selected_chars = int(item.get("selected_chars_total") or 0)
    source_label = _human_source_classes(source_classes)
    route_label = _human_route(route)

    print("OWNER_MESSAGE_BEGIN")
    print("我想确认一下刚才 Memory-OS 选出来的上下文来源是否帮到你判断。")
    print(f"这次主要用了{source_label}，用于{route_label}，数量约 {selected_count} 段。")
    if selected_chars:
        print(f"总长度约 {selected_chars} 字，所以这里只问来源质量，不展开原文。")
    print("请只选一个反馈：")
    print("1. 有帮助")
    print("2. 缺了关键上下文")
    print("3. 太机制化/程序味")
    print("4. 需要更具体的召回")
    print("你可以直接回：有帮助、缺上下文、太机制化、要更具体。")
    print("OWNER_MESSAGE_END")
    return 0


def _human_source_classes(source_classes: str) -> str:
    labels = {
        "foreground": "当前任务/前台上下文",
        "event": "近期事件",
        "carryover": "会话延续摘要",
        "candidate": "候选记忆",
        "crystallized": "已批准记忆",
        "indexed": "索引召回结果",
        "recall_guard": "低线索召回保护提示",
        "diagnostic": "运行状态事实",
    }
    parts = [part.strip() for part in source_classes.split(",") if part.strip()]
    rendered = [labels.get(part, part) for part in parts]
    return "、".join(rendered) if rendered else "记忆来源摘要"


def _human_route(route: str) -> str:
    labels = {
        "foreground_control": "判断当前任务/继续事项",
        "casual_continuity": "保持普通对话延续",
        "candidate_review": "辅助候选记忆/审批判断",
        "low_clue_recall": "处理低线索召回",
        "ambiguous_recall": "处理不明确的召回请求",
    }
    return labels.get(route, "辅助当前判断")


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
