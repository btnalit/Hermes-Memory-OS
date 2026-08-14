#!/usr/bin/env python3
"""Prepare a bounded right-brain expression prompt for Hermes cron.

Hermes agent owns the final expression, conversation judgment, and delivery.
Memory-OS only supplies bounded context and records that an adapter request was
made. Empty stdout means Hermes cron stays silent.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from memory_os_execution_report import write_helper_execution_report
except ModuleNotFoundError:
    from scripts.memory_os_execution_report import write_helper_execution_report


SCHEMA_VERSION = "memory-os.right_brain_expression_adapter_request.v0"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hermes-home", default=os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
    # Legacy paused per-lane surface: keeps its host-calibrated "main" default
    # on purpose — its historical score/feedback ledgers are stamped "main",
    # and rewiring the fallback would split their attribution. Active lanes
    # resolve via roots.resolve_profile_name instead.
    parser.add_argument("--profile", default=os.environ.get("HERMES_PROFILE", "main"))
    parser.add_argument("--channel", default=os.environ.get("MEMORY_OS_RIGHT_BRAIN_CHANNEL", "origin"))
    parser.add_argument("--max-refs", type=int, default=int(os.environ.get("MEMORY_OS_RIGHT_BRAIN_MAX_REFS", "6")))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    hermes_home = Path(args.hermes_home).expanduser().resolve()
    _ensure_runtime_path(hermes_home)

    from plugins.memory.memory_os.legacy_right_brain_retirement import (
        legacy_right_brain_is_retired,
        legacy_right_brain_read_lock,
    )
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore
    from plugins.modules.expression.expression_draft import ExpressionDraftModule

    if legacy_right_brain_is_retired(hermes_home):
        return 0
    with legacy_right_brain_read_lock(hermes_home):
        if legacy_right_brain_is_retired(hermes_home):
            return 0
        roots = MemoryOSRoots.from_hermes_home(hermes_home, profile=args.profile)
        store = MemoryOSStore(roots)
        store.initialize()
        module = ExpressionDraftModule(hermes_home, profile=args.profile)
        context = module.build_context(store=store, max_refs=max(int(args.max_refs), 1))
        summaries = [str(item).strip() for item in context.get("summaries", []) if str(item).strip()]
        if not summaries:
            return 0
        policy = _read_expression_policy(hermes_home)

        request = _record_request(
            hermes_home=hermes_home,
            profile=args.profile,
            channel=args.channel,
            source_refs=[str(ref) for ref in context.get("source_refs", [])],
            summary_count=len(summaries),
            policy=policy,
        )
        print(
            _render_prompt(
                profile=args.profile,
                channel=args.channel,
                request=request,
                summaries=summaries,
                policy=policy,
            )
        )
    return 0


def _ensure_runtime_path(hermes_home: Path) -> None:
    runtime = hermes_home / "memory-os" / "runtime" / "python"
    if runtime.exists():
        text = str(runtime)
        if text not in sys.path:
            sys.path.insert(0, text)
    repo_root = Path(__file__).resolve().parents[1]
    if (repo_root / "plugins" / "memory" / "memory_os").is_dir():
        text = str(repo_root)
        if text not in sys.path:
            sys.path.insert(0, text)


def _record_request(
    *,
    hermes_home: Path,
    profile: str,
    channel: str,
    source_refs: list[str],
    summary_count: int,
    policy: dict[str, Any],
) -> dict[str, Any]:
    created_at = datetime.now(timezone.utc).isoformat()
    request = {
        "schema_version": SCHEMA_VERSION,
        "request_id": f"rbexpr_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}",
        "created_at": created_at,
        "profile": profile,
        "channel": channel,
        "delivery_mode": "hermes_cron_agent",
        "source_refs": source_refs[:12],
        "summary_count": summary_count,
        "policy_version": int(policy.get("policy_version") or 0) if policy else 0,
        "policy_id": str(policy.get("policy_id") or "") if policy else "",
        "raw_body_included": False,
        "actual_send": False,
        "actual_execute": False,
        "actual_identity_write": False,
        "actual_unapproved_crystallized_approval": False,
    }
    path = hermes_home / "system-modules" / "right_brain_expression_adapter" / "requests.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(request, ensure_ascii=False, sort_keys=True))
        handle.write("\n")
    return request


def _read_expression_policy(hermes_home: Path) -> dict[str, Any]:
    path = hermes_home / "system-modules" / "right_brain_expression_adapter" / "policy.json"
    if not path.exists():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict) or parsed.get("active") is not True:
        return {}
    if parsed.get("schema_version") != "memory-os.right_brain_expression_policy.v0":
        return {}
    return parsed


def _render_policy(policy: dict[str, Any]) -> str:
    if not policy:
        return ""
    guidance = [str(item).strip() for item in policy.get("tone_guidance", []) if str(item).strip()]
    constraints = [str(item).strip() for item in policy.get("safety_constraints", []) if str(item).strip()]
    lines = [
        "已应用的右脑表达策略：",
        f"policy_version: {int(policy.get('policy_version') or 0)}",
    ]
    if guidance:
        lines.append("语气策略：")
        lines.extend(f"- {item}" for item in guidance[:6])
    if constraints:
        lines.append("安全约束：")
        lines.extend(f"- {item}" for item in constraints[:5])
    return "\n".join(lines) + "\n\n"


def _render_prompt(
    *,
    profile: str,
    channel: str,
    request: dict[str, Any],
    summaries: list[str],
    policy: dict[str, Any],
) -> str:
    bullets = "\n".join(f"- {summary}" for summary in summaries[:8])
    return (
        "Hermes agent 右脑低频表达任务。\n\n"
        "Memory-OS 只提供 bounded context；你负责理解、取舍、表达和保持沉默判断。\n"
        "请用中文输出给 owner。不要执行任务，不要创建计划，不要调用工具，不要自称在改系统。\n"
        "如果这些上下文不足以产生自然、真诚、非任务化的一句话，请只回复 [SILENT]。\n\n"
        "表达要求：\n"
        "- 像一个有记忆的 Hermes agent 自然说话，不要写系统报告。\n"
        "- 只写 1 到 3 句，低频、轻、不打扰。\n"
        "- 不要泄露内部 schema、id、source_ref、审计字段。\n"
        "- 不要承诺已经执行、审批、写入记忆或改变策略。\n\n"
        f"adapter_request_id: {request['request_id']}\n"
        f"profile: {profile}\n"
        f"delivery_channel: {channel}\n\n"
        f"{_render_policy(policy)}"
        "Bounded context summaries:\n"
        f"{bullets}\n"
    )


if __name__ == "__main__":
    result = main()
    write_helper_execution_report(result_summary={"returncode": result, "helper": "right_brain_expression"})
    raise SystemExit(result)
