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
    if bool(item.get("outcome_silent")):
        return 0
    existing_feedback = report.get("existing_feedback") if isinstance(report.get("existing_feedback"), dict) else {}
    if int(existing_feedback.get("count") or 0) > 0:
        return 0
    preview = str(item.get("expression_preview") or item.get("outcome_preview") or "").strip()
    tokens = item.get("action_tokens") if isinstance(item.get("action_tokens"), dict) else {}
    if not tokens:
        return 0

    print("Memory-OS right-brain expression feedback request")
    print()
    print("请用中文、自然地向用户询问最近一次右脑表达是否像她/是否有帮助。")
    print("不要称呼 Owner，不要展示内部 outcome id，不要替用户判断。")
    print("这是一条 Memory-OS 表达反馈任务，不是普通偏好采集。")
    print("必须向用户展示 token 化选项：每个反馈含义都要带 stable oa_ token 和完整回复示例。")
    print("用户只回复“喜欢/太机械/不像我”等自然词时，不要直接调用工具；请追问或提示复制对应 token。")
    print("不要调用普通 memory/user/profile 工具，不要把这条反馈写入 identity。")
    print("只有用户给出 oa_ token 或完整 memory feedback 命令后，才调用 memory_os_review_reply。")
    print()
    if preview:
        print("最近一次表达预览：")
        print(preview)
        print()
    print("请展示这些 token 化选项：")
    labels = {
        "like_expression": "喜欢/像她/有温度",
        "too_mechanical": "太机械/太报告味",
        "off_voice": "不像她/语气不对",
        "too_frequent": "太频繁",
        "boundary_private": "边界或隐私不舒服",
        "mute_period": "暂时少说/静音一段",
    }
    for rating, label in labels.items():
        token = str(tokens.get(rating) or "")
        if not token:
            continue
        print(f"- {label}: memory feedback {token} {rating}")
    print()
    print("结构化工具调用模板（只给 agent 执行，不要让用户进 shell）：")
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
