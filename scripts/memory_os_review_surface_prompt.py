#!/usr/bin/env python3
"""Render a bounded owner-review surface interaction smoke prompt.

Hermes agent owns the conversation. This script only tells the agent what
read-only surface operations are available for a live owner-channel smoke.
"""

from __future__ import annotations

import json
import subprocess
import sys


def main() -> int:
    next_page = _run_json(
        [
            "hermes",
            "memory-os-agent-os",
            "review",
            "surface",
            "--operation",
            "next_page",
            "--section",
            "review_suggested",
            "--limit",
            "3",
        ]
    )
    item_count = sum(len(value or []) for value in (next_page.get("sections") or {}).values())
    print("Memory-OS review surface interaction smoke")
    print()
    print("请用中文、自然地告诉用户：Memory-OS 现在支持展开/下一页/详情这类只读 review surface。")
    print("这不是审批，不会写状态；只有 owner 明确给 action token 后才调用 memory_os_review_reply。")
    print()
    print(f"当前 next_page 可返回的项目数：{item_count}")
    print()
    print("请让用户选一个测试指令，例如：")
    print("- 下一页")
    print("- 查看建议项")
    print("- 展开 R1")
    print()
    print("用户回复后，你应该调用只读工具，例如：")
    print('memory_os_review_surface({ "operation": "next_page", "section": "review_suggested", "limit": 3 })')
    print('memory_os_review_surface({ "operation": "detail", "anchor": "R1" })')
    print()
    print("拿到结果后，用人话总结，不要倾倒 JSON，不要编造不存在的条目。")
    return 0


def _run_json(command: list[str]) -> dict[str, object]:
    try:
        completed = subprocess.run(command, check=True, text=True, capture_output=True)
    except FileNotFoundError as exc:
        raise SystemExit("hermes command not found; cannot render review surface prompt") from exc
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(exc.stderr or exc.stdout or str(exc))
        raise SystemExit(exc.returncode) from exc
    try:
        parsed = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"review surface context did not return JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise SystemExit("review surface context returned non-object JSON")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
