#!/usr/bin/env python3
"""Render a bounded right-brain expression feedback prompt for Hermes agent.

This script does not send messages and does not write Memory-OS state. Hermes
cron owns delivery and the Hermes agent owns the owner interaction.
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
            "expression_feedback_context",
            "--limit",
            "1",
        ]
    )
    if report.get("status") != "ok":
        return 0
    item = report.get("latest_expression_outcome")
    if not isinstance(item, dict):
        item = report.get("latest_outcome")
    if not isinstance(item, dict):
        return 0
    preview = str(item.get("expression_preview") or item.get("outcome_preview") or "").strip()
    tokens = item.get("action_tokens") if isinstance(item.get("action_tokens"), dict) else {}
    if not tokens:
        return 0

    print("Memory-OS right-brain expression feedback request")
    print()
    print("请用中文、自然地向用户询问最近一次右脑表达是否像她/是否有帮助。")
    print("不要称呼 Owner，不要展示内部 outcome id，不要替用户判断。")
    print("如果用户没有明确选择反馈类型，先反问；明确后再调用 memory_os_review_reply。")
    print()
    if preview:
        print("最近一次表达预览：")
        print(preview)
        print()
    print("可接受反馈：")
    print("- like_expression: 喜欢/像她/有温度")
    print("- too_mechanical: 太机械/太报告味")
    print("- off_voice: 不像她/语气不对")
    print("- too_frequent: 太频繁")
    print("- boundary_private: 边界或隐私不舒服")
    print("- mute_period: 暂时少说/静音一段")
    print()
    print("结构化工具调用模板：")
    for rating, token in tokens.items():
        if rating == "allow_speak_once":
            continue
        print(
            'memory_os_review_reply({ "action": "feedback", '
            f'"action_token": "{token}", "rating": "{rating}" }})'
        )
    return 0


def _run_json(command: list[str]) -> dict[str, object]:
    try:
        completed = subprocess.run(command, check=True, text=True, capture_output=True)
    except FileNotFoundError as exc:
        raise SystemExit("hermes command not found; cannot render expression feedback prompt") from exc
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(exc.stderr or exc.stdout or str(exc))
        raise SystemExit(exc.returncode) from exc
    try:
        parsed = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"expression feedback context did not return JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise SystemExit("expression feedback context returned non-object JSON")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
