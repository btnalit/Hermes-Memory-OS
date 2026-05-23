"""Official Hermes plugin shell for Memory-OS Agent OS.

The shell is intentionally thin. It exposes operator-facing aliases while the
Memory-OS provider and runtime remain the source of truth.
"""

from __future__ import annotations

import argparse
import importlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any


_ALLOWED_ALIASES = {"status", "doctor", "memory-sources"}
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


def register_cli(subparser: argparse.ArgumentParser) -> None:
    subs = subparser.add_subparsers(dest="agent_os_command")
    subs.add_parser("status")
    subs.add_parser("doctor")
    memory_sources_parser = subs.add_parser("memory-sources")
    memory_sources_subs = memory_sources_parser.add_subparsers(dest="memory_sources_command", required=True)
    memory_sources_subs.add_parser("last")
    memory_sources_history = memory_sources_subs.add_parser("history")
    memory_sources_history.add_argument("--limit", type=int, default=20)
    memory_sources_stats = memory_sources_subs.add_parser("stats")
    memory_sources_stats.add_argument("--hours", type=int, default=24)


def memory_os_agent_os_command(args: argparse.Namespace) -> int:
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
    session_id: str = "",
    platform: str = "",
    model: str = "",
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
        append_audit(
            roots.audit_path,
            action=action,
            status="ok",
            target="memory-os-agent-os",
            details=details,
        )
    except Exception as exc:
        _LOGGER.debug("Memory-OS Agent OS session marker skipped: %s", exc)


def _load_memory_os_audit_api() -> tuple[Any, Any]:
    _ensure_memory_os_runtime_path()
    importlib.invalidate_caches()
    try:
        from plugins.memory.memory_os.audit import append_audit
        from plugins.memory.memory_os.roots import MemoryOSRoots
    except ModuleNotFoundError:
        from memory_os.audit import append_audit
        from memory_os.roots import MemoryOSRoots
    return MemoryOSRoots, append_audit


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
