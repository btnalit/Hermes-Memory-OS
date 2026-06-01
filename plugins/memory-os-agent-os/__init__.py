"""Official Hermes plugin shell for Memory-OS Agent OS.

The shell is intentionally thin. It exposes operator-facing aliases while the
Memory-OS provider and runtime remain the source of truth.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any


_ALLOWED_ALIASES = {
    "status",
    "doctor",
    "hindsight",
    "low-clue-recall",
    "memory-sources",
    "metadata-retention",
    "review",
    "modules",
    "eval",
}
_PLUGIN_NAME = "memory-os-agent-os"
_LOGGER = logging.getLogger(__name__)


def register(ctx: Any) -> None:
    """Register the official shell CLI alias and minimal session markers.

    v0.1 deliberately registers no slash commands and no LLM-call hooks.
    Conversation carryover remains owned by the MemoryProvider.prefetch path.
    """

    ctx.register_cli_command(
        name="memory-os-agent-os",
        help="Memory-OS Agent OS operator aliases",
        setup_fn=register_cli,
        handler_fn=memory_os_agent_os_command,
        description=(
            "Thin official Hermes plugin shell for Memory-OS status and doctor "
            "aliases. The memory_os provider/runtime remains authoritative."
        ),
    )
    ctx.register_hook("on_session_start", _on_session_start)
    ctx.register_hook("on_session_reset", _on_session_reset)
    ctx.register_hook("on_session_finalize", _on_session_finalize)
    ctx.register_hook("pre_tool_call", _on_pre_tool_call)


_OWNER_ACTION_TOKEN_RE = re.compile(r"\boa_[0-9a-f]{8,32}\b", re.IGNORECASE)
_OWNER_REVIEW_COMMAND_RE = re.compile(
    r"\b(?:memory|mos)\s+(?:approve|reject|revoke|allow|feedback|apply)\s+oa_[0-9a-f]{8,32}\b",
    re.IGNORECASE,
)
_DIRECT_OWNER_ACTION_BYPASS_MARKERS = (
    "apply_approved_proposal_execution_decision",
    "apply_owner_action",
    "parse_owner_review_reply",
)
_TOKEN_OWNER_ACTION_BYPASS_MARKERS = (
    "memory-os-agent-os review apply",
    "memory_os_review_reply_tool_input",
    "plugins.memory.memory_os.owner_actions",
    "memory_os/owner_actions.py",
    "memory_os\\owner_actions.py",
)
_OWNER_ACTION_BYPASS_TOOLS = {"terminal", "execute_code"}
_OWNER_ACTION_BYPASS_BLOCK_MESSAGE = (
    "Memory-OS owner-action bypass blocked. Use the structured "
    "memory_os_review_reply tool with action=approve|reject|revoke|allow|feedback|apply "
    "and the stable action_token, or use memory_os_review_surface for read-only "
    "context. Do not process Memory-OS owner-review tokens through terminal, "
    "execute_code, CLI fallback, or direct Python calls."
)


def _on_pre_tool_call(tool_name: str = "", args: dict[str, Any] | None = None, **_: object) -> dict[str, str] | None:
    """Block shell/code bypasses for Memory-OS owner-review action tokens.

    This hook is safety-only. It does not interpret owner intent or mutate
    Memory-OS state; the normal path remains Hermes agent ->
    memory_os_review_reply -> OwnerActionProcessor.
    """

    if str(tool_name) not in _OWNER_ACTION_BYPASS_TOOLS:
        return None
    args_text = _bounded_args_text(args)
    if not _looks_like_owner_action_bypass(args_text):
        return None
    _append_session_marker(
        action="owner_review_tool_bypass_blocked",
        hook="pre_tool_call",
        status="blocked",
        tool_name=str(tool_name),
        args_sha256=_sha256(args_text),
    )
    return {"action": "block", "message": _OWNER_ACTION_BYPASS_BLOCK_MESSAGE}


def _bounded_args_text(args: Any) -> str:
    try:
        text = json.dumps(args if isinstance(args, dict) else {}, ensure_ascii=False, sort_keys=True)
    except Exception:
        text = str(args or "")
    return text[:12000]


def _looks_like_owner_action_bypass(args_text: str) -> bool:
    if not args_text:
        return False
    lowered = args_text.lower()
    if _OWNER_REVIEW_COMMAND_RE.search(args_text):
        return True
    if any(marker in lowered for marker in _DIRECT_OWNER_ACTION_BYPASS_MARKERS):
        return True
    if "memory-os-agent-os review apply" in lowered:
        return True
    if "review apply" in lowered and "--action" in lowered:
        return True
    if _OWNER_ACTION_TOKEN_RE.search(args_text) and any(marker in lowered for marker in _TOKEN_OWNER_ACTION_BYPASS_MARKERS):
        return True
    if "apply_proposal" in lowered and any(marker in lowered for marker in ("python3 -c", "python -c")):
        return True
    return False


def _on_session_start(session_id: str = "", model: str = "", platform: str = "", **_: object) -> None:
    _append_session_marker(
        action="agent_os_shell_session_started",
        hook="on_session_start",
        session_id=session_id,
        platform=platform,
        model=model,
    )


def _on_session_reset(session_id: str = "", platform: str = "", **_: object) -> None:
    _append_session_marker(
        action="agent_os_shell_session_reset",
        hook="on_session_reset",
        session_id=session_id,
        platform=platform,
    )


def _on_session_finalize(session_id: str = "", platform: str = "", **_: object) -> None:
    _append_session_marker(
        action="agent_os_shell_session_finalized",
        hook="on_session_finalize",
        session_id=session_id,
        platform=platform,
    )


def _load_memory_os_audit_api() -> tuple[Any, Any]:
    _ensure_memory_os_runtime_path()
    importlib.invalidate_caches()
    try:
        from memory_os.audit import append_audit
        from memory_os.roots import MemoryOSRoots
    except ModuleNotFoundError:
        from plugins.memory.memory_os.audit import append_audit
        from plugins.memory.memory_os.roots import MemoryOSRoots
    return MemoryOSRoots, append_audit


def _resolve_profile() -> str:
    return (
        os.environ.get("HERMES_PROFILE")
        or os.environ.get("HERMES_AGENT_IDENTITY")
        or os.environ.get("HERMES_AGENT_NAME")
        or "default"
    )


def register_cli(subparser: argparse.ArgumentParser) -> None:
    subs = subparser.add_subparsers(dest="agent_os_command")
    subs.add_parser("status")
    subs.add_parser("doctor")
    hindsight_parser = subs.add_parser("hindsight")
    hindsight_subs = hindsight_parser.add_subparsers(dest="hindsight_command", required=True)
    hindsight_subs.add_parser("status")
    hindsight_adopt = hindsight_subs.add_parser("adopt")
    hindsight_adopt.add_argument("--apply", action="store_true")
    hindsight_retain = hindsight_subs.add_parser("retain-pending")
    hindsight_retain.add_argument("--apply", action="store_true")
    hindsight_retract = hindsight_subs.add_parser("retract")
    hindsight_retract.add_argument("--record-id", required=True)
    hindsight_retract.add_argument("--reason", required=True)
    hindsight_retract.add_argument("--apply", action="store_true")
    hindsight_reflect = hindsight_subs.add_parser("reflect")
    hindsight_reflect.add_argument("--query", required=True)
    hindsight_reflect.add_argument("--apply", action="store_true")
    low_clue_parser = subs.add_parser("low-clue-recall")
    low_clue_subs = low_clue_parser.add_subparsers(dest="low_clue_recall_command", required=True)
    low_clue_dry_run = low_clue_subs.add_parser("dry-run")
    low_clue_dry_run.add_argument("--query", required=True)
    low_clue_dry_run.add_argument("--limit", type=int, default=4)
    low_clue_dry_run.add_argument("--llm-judge", choices=["config", "none", "report-only"], default="config")
    memory_sources_parser = subs.add_parser("memory-sources")
    memory_sources_subs = memory_sources_parser.add_subparsers(dest="memory_sources_command", required=True)
    memory_sources_subs.add_parser("last")
    memory_sources_history = memory_sources_subs.add_parser("history")
    memory_sources_history.add_argument("--limit", type=int, default=20)
    memory_sources_stats = memory_sources_subs.add_parser("stats")
    memory_sources_stats.add_argument("--hours", type=int, default=24)
    memory_sources_feedback = memory_sources_subs.add_parser("feedback")
    memory_sources_feedback_subs = memory_sources_feedback.add_subparsers(
        dest="memory_sources_feedback_command",
        required=True,
    )
    memory_sources_feedback_last = memory_sources_feedback_subs.add_parser("last")
    memory_sources_feedback_last.add_argument("--rating", required=True)
    memory_sources_feedback_last.add_argument("--note", default="")
    memory_sources_feedback_history = memory_sources_feedback_subs.add_parser("history")
    memory_sources_feedback_history.add_argument("--limit", type=int, default=20)
    review_parser = subs.add_parser("review")
    review_subs = review_parser.add_subparsers(dest="review_command", required=True)
    review_subs.add_parser("status")
    review_subs.add_parser("aging-report")
    review_subs.add_parser("channel")
    review_subs.add_parser("cron-status")
    review_subs.add_parser("delivery-status")
    review_delivery_gate = review_subs.add_parser("delivery-gate")
    review_delivery_gate.add_argument("--owner", default="")
    review_deliver_once = review_subs.add_parser("deliver-once")
    review_deliver_once.add_argument("--owner", default="")
    review_deliver_once.add_argument("--delivery-key", default="")
    review_deliver_once.add_argument("--owner-triggered", action="store_true")
    review_deliver_once.add_argument("--apply", action="store_true")
    review_queue = review_subs.add_parser("queue")
    review_queue.add_argument("--limit", type=int, default=20)
    review_surface = review_subs.add_parser("surface")
    review_surface.add_argument(
        "--operation",
        choices=[
            "overview",
            "page",
            "next_page",
            "detail",
            "proposal_followups",
            "expression_feedback_context",
            "memory_sources_feedback_context",
        ],
        default="overview",
    )
    review_surface.add_argument("--section", choices=["all", "action_required", "review_suggested", "fyi"], default="all")
    review_surface.add_argument("--anchor", default="")
    review_surface.add_argument("--action-token", default="")
    review_surface.add_argument("--offset", type=int, default=0)
    review_surface.add_argument("--limit", type=int, default=5)
    review_surface.add_argument("--owner", default="owner")
    review_surface.add_argument("--channel", default="agent")
    review_followups = review_subs.add_parser("proposal-followups")
    review_followups.add_argument("--limit", type=int, default=20)
    review_followups.add_argument("--proposal-id", default="")
    review_followups.add_argument("--ops-gate", action="store_true")
    review_followups.add_argument("--all-pending", action="store_true")
    review_followups.add_argument("--execution-apply", action="store_true")
    review_followups.add_argument("--owner-approved", action="store_true")
    review_followups.add_argument("--evidence-ref", action="append", default=[])
    review_followups.add_argument("--evidence-summary", default="")
    review_followups.add_argument("--owner", default="owner")
    review_followups.add_argument("--channel", default="cli")
    review_followups.add_argument("--apply", action="store_true")
    review_preview = review_subs.add_parser("preview-digest")
    review_preview.add_argument("--owner", default="")
    review_preview.add_argument("--max-action-required", type=int)
    review_preview.add_argument("--max-review-suggested", type=int)
    review_preview.add_argument("--max-fyi", type=int)
    review_preview.add_argument("--mode", choices=["review", "agenda", "debug"], default="review")
    review_render = review_subs.add_parser("render-digest")
    review_render.add_argument("--owner", default="")
    review_render.add_argument("--channel", default="cli")
    review_render.add_argument("--max-action-required", type=int)
    review_render.add_argument("--max-review-suggested", type=int)
    review_render.add_argument("--max-fyi", type=int)
    review_render.add_argument("--mode", choices=["review", "agenda", "debug"], default="review")
    review_render.add_argument("--format", choices=["json", "text"], default="json")
    review_render.add_argument("--bounded", action="store_true")
    review_render.add_argument("--record-active", action="store_true")
    review_reply = review_subs.add_parser("reply")
    review_reply.add_argument("reply", nargs="+")
    review_reply.add_argument("--owner", default="owner")
    review_reply.add_argument("--channel", default="cli")
    review_reply.add_argument("--digest-id", default="")
    review_reply.add_argument("--apply", action="store_true")
    review_reply.add_argument("--max-action-required", type=int)
    review_reply.add_argument("--max-review-suggested", type=int)
    review_reply.add_argument("--max-fyi", type=int)
    review_apply = review_subs.add_parser("apply")
    review_apply.add_argument(
        "--action",
        required=True,
        choices=[
            "approve_candidate",
            "reject_candidate",
            "revoke_crystallized",
            "mark_feedback",
            "approve_proposal",
            "reject_proposal",
            "apply_proposal",
            "allow_speak_once",
            "like_expression",
            "too_mechanical",
            "too_frequent",
            "boundary_private",
            "off_voice",
            "mute_period",
        ],
    )
    review_apply.add_argument("--target", required=True)
    review_apply.add_argument("--owner", default="owner")
    review_apply.add_argument("--channel", default="cli")
    review_apply.add_argument("--note", default="")
    review_apply.add_argument("--rating", default="")
    review_apply.add_argument("--apply", action="store_true")
    metadata_retention_parser = subs.add_parser("metadata-retention")
    metadata_retention_parser.add_argument("--memory-sources-days", type=int, default=30)
    metadata_retention_parser.add_argument("--feedback-days", type=int, default=30)
    metadata_retention_parser.add_argument("--suggestion-days", type=int, default=30)
    metadata_retention_parser.add_argument("--eval-report-root", default="")
    metadata_retention_parser.add_argument("--eval-report-days", type=int, default=30)
    metadata_retention_parser.add_argument("--eval-report-keep-latest", type=int, default=20)
    metadata_retention_parser.add_argument("--suggestion-report-root", default="")
    metadata_retention_parser.add_argument("--suggestion-report-days", type=int, default=30)
    metadata_retention_parser.add_argument("--suggestion-report-keep-latest", type=int, default=20)
    modules_parser = subs.add_parser("modules")
    modules_subs = modules_parser.add_subparsers(dest="modules_command", required=True)
    modules_subs.add_parser("status")
    modules_subs.add_parser("doctor")
    modules_run_once = modules_subs.add_parser("run-once")
    modules_run_once.add_argument("--module", required=True)
    modules_run_once.add_argument("--dry-run", action="store_true")
    modules_run_once.add_argument("--apply", action="store_true")
    modules_subs.add_parser("validate-no-send")
    modules_deep_reflection = modules_subs.add_parser("deep_reflection")
    deep_reflection_subs = modules_deep_reflection.add_subparsers(
        dest="deep_reflection_command",
        required=True,
    )
    deep_reflection_subs.add_parser("preview-current")
    deep_reflection_history = deep_reflection_subs.add_parser("history")
    deep_reflection_history.add_argument("--days", type=int, default=7)
    eval_parser = subs.add_parser("eval")
    eval_subs = eval_parser.add_subparsers(dest="eval_command", required=True)
    eval_rh31 = eval_subs.add_parser("rh31")
    eval_rh31_subs = eval_rh31.add_subparsers(dest="rh31_command", required=True)
    eval_rh31_run = eval_rh31_subs.add_parser("run")
    eval_rh31_run.add_argument("--fixture", default="synthetic")
    eval_rh31_run.add_argument("--adapter", action="append", default=[])
    eval_rh31_run.add_argument("--report-root", default="")
    eval_rh31_run.add_argument("--no-write-report", action="store_true")
    eval_rh31_run.add_argument("--keep-latest", type=int, default=20)
    eval_rh31_run.add_argument("--retention-days", type=int, default=30)
    eval_rh31_summary = eval_rh31_subs.add_parser("summary")
    eval_rh31_summary.add_argument("--report-root", default="")
    eval_rh31_failures = eval_rh31_subs.add_parser("failures")
    eval_rh31_failures.add_argument("--report-root", default="")
    eval_rh31_failures.add_argument("--class", dest="failure_class", default="")


def memory_os_agent_os_command(args: argparse.Namespace) -> None:
    raise SystemExit(_memory_os_agent_os_exit_code(args))


def _memory_os_agent_os_exit_code(args: argparse.Namespace) -> int:
    command = str(getattr(args, "agent_os_command", "") or "")
    if command not in _ALLOWED_ALIASES:
        return 2
    delegated_args = argparse.Namespace(**vars(args))
    delegated_args.memory_os_command = command
    return _delegate_to_memory_os_cli(delegated_args)


def _delegate_to_memory_os_cli(args: argparse.Namespace) -> int:
    try:
        memory_os_command = _load_memory_os_command()
    except ModuleNotFoundError as exc:
        print(
            json.dumps(
                {
                    "schema_version": "memory-os.agent_os_shell.v0",
                    "status": "error",
                    "code": "memory_os_provider_missing",
                    "message": "Memory-OS provider/runtime is not importable by the shell plugin.",
                    "error": str(exc),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    return int(memory_os_command(args))


def _load_memory_os_command() -> Any:
    _ensure_memory_os_runtime_path()
    importlib.invalidate_caches()
    try:
        from plugins.memory.memory_os.cli import memory_os_command
    except ModuleNotFoundError:
        from memory_os.cli import memory_os_command

    return memory_os_command


def _append_session_marker(
    *,
    action: str,
    hook: str,
    status: str = "ok",
    session_id: str = "",
    platform: str = "",
    model: str = "",
    **extra_details: str,
) -> None:
    hermes_home = _resolve_hermes_home()
    if hermes_home is None:
        return
    try:
        roots_class, append_audit = _load_memory_os_audit_api()
        roots = roots_class.from_hermes_home(hermes_home)
        details = {
            "hook": hook,
            "session_id": str(session_id or ""),
            "platform": str(platform or ""),
        }
        if model:
            details["model"] = str(model)
        for key, value in extra_details.items():
            details[str(key)] = str(value)
        append_audit(
            roots.audit_path,
            action=action,
            status=status,
            target="memory-os-agent-os",
            details=details,
        )
    except Exception as exc:
        _LOGGER.debug("Memory-OS Agent OS session marker skipped: %s", exc)


def _ensure_memory_os_runtime_path() -> None:
    hermes_home = _resolve_hermes_home()
    if hermes_home is None:
        return
    runtime_root = hermes_home / "memory-os" / "runtime" / "python"
    if runtime_root.exists():
        runtime_text = str(runtime_root)
        if runtime_text not in sys.path:
            sys.path.insert(0, runtime_text)
        _extend_existing_plugins_namespace(runtime_root / "plugins")
        _extend_existing_package_namespace("plugins.memory", runtime_root / "plugins" / "memory")
    flat_plugins_root = hermes_home / "plugins"
    flat_provider = flat_plugins_root / "memory_os"
    if flat_provider.exists():
        flat_plugins_root_text = str(flat_plugins_root)
        if flat_plugins_root_text not in sys.path:
            sys.path.insert(0, flat_plugins_root_text)


def _resolve_hermes_home() -> Path | None:
    hermes_home = os.environ.get("HERMES_HOME", "").strip()
    if hermes_home:
        return Path(hermes_home).expanduser().resolve()

    try:
        plugin_dir = Path(__file__).resolve().parent
    except NameError:
        plugin_dir = Path()
    if plugin_dir.name == _PLUGIN_NAME and plugin_dir.parent.name == "plugins":
        return plugin_dir.parent.parent

    default_home = Path.home() / ".hermes"
    if default_home.exists():
        return default_home
    return None


def _extend_existing_plugins_namespace(runtime_plugins: Path) -> None:
    _extend_existing_package_namespace("plugins", runtime_plugins)


def _extend_existing_package_namespace(package_name: str, package_path: Path) -> None:
    module = sys.modules.get(package_name)
    module_path = getattr(module, "__path__", None)
    if module_path is None or not package_path.exists():
        return
    package_path_text = str(package_path)
    if package_path_text not in module_path:
        module_path.append(package_path_text)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
