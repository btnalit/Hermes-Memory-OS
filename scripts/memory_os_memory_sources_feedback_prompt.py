#!/usr/bin/env python3
"""Render a bounded MemorySources feedback prompt for Hermes agent delivery.

This script does not send messages and does not write owner-facing Memory-OS
state. Hermes cron owns delivery and the Hermes agent owns the owner interaction.
Empty stdout means there is no suitable feedback context to ask about — and
the per-lane last-run evidence file (system/lane_last_run/) records WHY,
using the same skip_reason set --status-json reports.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

try:
    from memory_os_execution_report import write_helper_execution_report
except ModuleNotFoundError:
    from scripts.memory_os_execution_report import write_helper_execution_report

_HERMES_HOME_DEFAULT = str(Path.home() / ".hermes")
_repo_root = Path(__file__).absolute().parents[1]
if (_repo_root / "plugins" / "memory" / "memory_os").exists():
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
else:
    _runtime_root = Path(os.environ.get("HERMES_HOME", "") or _HERMES_HOME_DEFAULT) / "memory-os" / "runtime" / "python"
    if _runtime_root.exists() and str(_runtime_root) not in sys.path:
        sys.path.insert(0, str(_runtime_root))

try:
    from plugins.memory.memory_os.lane_last_run import record_lane_last_run
except ModuleNotFoundError:  # pragma: no cover - plugin tree unavailable
    def record_lane_last_run(*_args, **_kwargs) -> bool:  # type: ignore[misc]
        sys.stderr.write("lane_last_run unavailable: plugin tree not importable\n")
        return False

CANARY_TARGET = 20
STATUS_SCHEMA_VERSION = "memory-os.memory_sources_feedback_prompt_status.v0"
_LANE_ID = "memory_sources_feedback_request"


def _record_last_run(status: str, reason: str) -> None:
    hermes_home = os.environ.get("HERMES_HOME", "") or _HERMES_HOME_DEFAULT
    record_lane_last_run(hermes_home, _LANE_ID, status=status, reason=reason)


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or [])
    parser = argparse.ArgumentParser(
        description=(
            "Render a bounded MemorySources feedback prompt. The script prints "
            "nothing when no unrated MemorySources context is available and never sends messages."
        )
    )
    parser.add_argument("--status-json", action="store_true", help="Print prompt/canary status instead of owner text.")
    if "-h" in argv or "--help" in argv:
        parser.print_help()
        return 0
    args = parser.parse_args(argv)
    try:
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
    except SystemExit:
        _record_last_run("error", "hermes_cli_failed")
        raise
    if args.status_json:
        stats = _try_run_json(["hermes", "memory-os-agent-os", "memory-sources", "stats", "--hours", "24"])
        print(json.dumps(_status_report(report, stats), ensure_ascii=False, sort_keys=True))
        return 0
    # The skip_reason taxonomy below used to exist only behind --status-json,
    # which cron never passes — persist it on the cron path too so a silent
    # run is explainable from disk.
    if report.get("status") != "ok":
        _record_last_run("skipped", "surface_not_ok")
        return 0
    item = report.get("latest_memory_source")
    if not isinstance(item, dict):
        _record_last_run("skipped", "no_memory_source_context")
        return 0
    existing_feedback = report.get("existing_feedback") if isinstance(report.get("existing_feedback"), dict) else {}
    if int(existing_feedback.get("count") or 0) > 0:
        _record_last_run("skipped", "already_feedback_for_latest_source")
        return 0
    token = str((item.get("action_tokens") or {}).get("mark_feedback") or "").strip()
    if not token:
        _record_last_run("skipped", "feedback_token_missing")
        return 0

    source_classes = ", ".join(str(value) for value in item.get("source_classes") or []) or "unknown"
    route = str(item.get("route") or item.get("query_class") or "unknown")
    selected_count = int(item.get("selected_count") or 0)
    selected_chars = int(item.get("selected_chars_total") or 0)
    source_label = _human_source_classes(source_classes)
    route_label = _human_route(route)

    print("OWNER_MESSAGE_BEGIN")
    print("我想确认一下刚才 Memory-OS 自动补进来的上下文来源是否帮到你。")
    print(f"本次只问这一轮来源质量：主要用了{source_label}，用于{route_label}，数量约 {selected_count} 段。")
    if selected_chars:
        print(f"总长度约 {selected_chars} 字，所以这里只问来源质量，不展开原文。")
    print("请只选一个判断，不需要解释：")
    print("1. 有帮助")
    print("2. 缺了关键上下文")
    print("3. 太机制化/程序味")
    print("4. 需要更具体的召回")
    print("你可以直接回：有帮助、缺上下文、太机制化、要更具体。")
    print("OWNER_MESSAGE_END")
    _record_last_run("ok", "prompt_rendered")
    return 0


def _status_report(report: dict[str, object], stats: dict[str, object] | None) -> dict[str, object]:
    item = report.get("latest_memory_source")
    item = item if isinstance(item, dict) else {}
    existing_feedback = report.get("existing_feedback") if isinstance(report.get("existing_feedback"), dict) else {}
    existing_feedback_count = int(existing_feedback.get("count") or 0)
    token = str((item.get("action_tokens") or {}).get("mark_feedback") or "").strip()
    surface_status = str(report.get("status") or "")
    prompt_status = "ready"
    skip_reason = ""
    if surface_status != "ok":
        prompt_status = "skipped"
        skip_reason = "surface_not_ok"
    elif not item:
        prompt_status = "skipped"
        skip_reason = "no_memory_source_context"
    elif existing_feedback_count > 0:
        prompt_status = "skipped"
        skip_reason = "already_feedback_for_latest_source"
    elif not token:
        prompt_status = "skipped"
        skip_reason = "feedback_token_missing"

    total_feedback_count, total_feedback_source = _feedback_total(stats)
    return {
        "schema_version": STATUS_SCHEMA_VERSION,
        "surface_status": surface_status,
        "prompt_status": prompt_status,
        "skip_reason": skip_reason,
        "prompt_would_render": prompt_status == "ready",
        "latest_memory_source_id": str(item.get("id") or item.get("memory_source_id") or item.get("target_id") or ""),
        "existing_feedback_count": existing_feedback_count,
        "total_feedback_count": total_feedback_count,
        "total_feedback_count_source": total_feedback_source,
        "canary_target": CANARY_TARGET,
        "canary_remaining": max(0, CANARY_TARGET - total_feedback_count),
        "canary_complete": total_feedback_count >= CANARY_TARGET,
        "stats_available": stats is not None,
        "raw_body_included": bool(report.get("raw_body_included") is True),
        "forbidden_owner_command_field_count": int(report.get("forbidden_owner_command_field_count") or 0),
        "actual_send": False,
        "actual_execute": False,
    }


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


def _try_run_json(command: list[str]) -> dict[str, object] | None:
    try:
        return _run_json(command)
    except SystemExit:
        return None


def _feedback_total(stats: dict[str, object] | None) -> tuple[int, str]:
    if not stats:
        return 0, "unavailable"
    total = stats.get("total_feedback_count")
    if isinstance(total, int):
        return total, "stats_total_feedback_count"
    ledger_path = str(stats.get("feedback_ledger_path") or "").strip()
    if ledger_path:
        path = Path(ledger_path)
        if path.exists() and path.is_file():
            count = 0
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    count += 1
            return count, "feedback_ledger_line_count"
    return int(stats.get("feedback_count") or 0), "stats_window_feedback_count"


if __name__ == "__main__":
    result = main(sys.argv[1:])
    write_helper_execution_report(result_summary={"returncode": result, "helper": "memory_sources_feedback_request"})
    raise SystemExit(result)
