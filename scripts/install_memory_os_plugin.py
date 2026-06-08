#!/usr/bin/env python3
"""Install Memory-OS as a Hermes user memory provider plugin."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import stat
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SOURCE_PLUGIN_DIR = REPO_ROOT / "plugins" / "memory" / "memory_os"
SOURCE_AGENT_OS_SHELL_DIR = REPO_ROOT / "plugins" / "memory-os-agent-os"
SOURCE_PACKAGE_DIR = REPO_ROOT / "plugins"
SOURCE_AGENT_DIR = REPO_ROOT / "agent"
SOURCE_EVAL_DIR = REPO_ROOT / "eval"
SOURCE_OWNER_REVIEW_CRON_HELPER = REPO_ROOT / "scripts" / "memory_os_owner_review_digest.py"
SOURCE_OWNER_REVIEW_CRON_GATE = REPO_ROOT / "scripts" / "memory_os_owner_review_cron_gate.py"
SOURCE_RIGHT_BRAIN_EXPRESSION_CRON_HELPER = REPO_ROOT / "scripts" / "memory_os_right_brain_expression.py"
SOURCE_RIGHT_BRAIN_EXPRESSION_CRON_GATE = REPO_ROOT / "scripts" / "memory_os_right_brain_expression_cron_gate.py"
SOURCE_RIGHT_BRAIN_EXPRESSION_OUTCOME = REPO_ROOT / "scripts" / "memory_os_right_brain_expression_outcome.py"
SOURCE_RIGHT_BRAIN_EXPRESSION_OUTCOME_CRON = REPO_ROOT / "scripts" / "memory_os_right_brain_expression_outcome_cron.py"
SOURCE_MODULE_CADENCE_REPORT = REPO_ROOT / "scripts" / "memory_os_module_cadence_report.py"
SOURCE_MODULE_CADENCE_REPORT_CRON = REPO_ROOT / "scripts" / "memory_os_module_cadence_report_cron.py"
SOURCE_EXPRESSION_FEEDBACK_PROMPT = REPO_ROOT / "scripts" / "memory_os_expression_feedback_prompt.py"
SOURCE_MEMORY_SOURCES_FEEDBACK_PROMPT = REPO_ROOT / "scripts" / "memory_os_memory_sources_feedback_prompt.py"
SOURCE_PROPOSAL_FOLLOWUPS_OPS_GATE = REPO_ROOT / "scripts" / "memory_os_proposal_followups_ops_gate.py"
SOURCE_EXECUTION_REPORT_HELPER = REPO_ROOT / "scripts" / "memory_os_execution_report.py"
SOURCE_OWNER_CRON_ONBOARDING = REPO_ROOT / "scripts" / "memory_os_owner_cron_onboarding.py"
SOURCE_EXECUTION_GATE_RUNNER = REPO_ROOT / "scripts" / "memory_os_execution_gate_runner.py"
SOURCE_CANDIDATE_AGGREGATION_LANE = REPO_ROOT / "scripts" / "memory_os_candidate_aggregation_lane.py"
AGENT_OS_SHELL_PLUGIN_NAME = "memory-os-agent-os"
MEMORY_PROVIDER_PLUGIN_NAME = "memory_os"


DEEP_REFLECTION_PRESETS: dict[str, dict[str, object]] = {
    "production-safe": {
        "enabled": False,
        "injection_mode": "disabled",
        "working_updates_enabled": False,
        "self_evolution_proposals_enabled": False,
        "wandering_seed_enabled": False,
    },
    "observe": {
        "enabled": True,
        "injection_mode": "dry_run",
        "working_updates_enabled": False,
        "self_evolution_proposals_enabled": False,
        "wandering_seed_enabled": False,
    },
    "auto-bounded": {
        "enabled": True,
        "injection_mode": "auto_bounded",
        "working_updates_enabled": False,
        "self_evolution_proposals_enabled": False,
        "wandering_seed_enabled": False,
    },
    "test-host": {
        "enabled": True,
        "injection_mode": "auto_bounded",
        "working_updates_enabled": False,
        "self_evolution_proposals_enabled": True,
        "wandering_seed_enabled": True,
        "max_optional_outputs": 2,
        "max_self_evolution_proposals": 1,
        "max_wandering_seeds": 1,
    },
    "operational": {
        "enabled": True,
        "injection_mode": "auto_bounded",
        "working_updates_enabled": False,
        "self_evolution_proposals_enabled": True,
        "wandering_seed_enabled": True,
        "max_optional_outputs": 2,
        "max_self_evolution_proposals": 1,
        "max_wandering_seeds": 1,
    },
}


DEEP_REFLECTION_CONFIG_DEFAULTS: dict[str, object] = {
    "enabled": False,
    "injection_mode": "disabled",
    "max_cards": 2,
    "max_chars_total": 600,
    "max_chars_per_card": 260,
    "ttl_hours": 24,
    "analysis_mode": "deterministic",
    "llm_enabled": False,
    "working_updates_enabled": False,
    "self_evolution_proposals_enabled": False,
    "wandering_seed_enabled": False,
}


MEMORY_SOURCES_PRESETS: dict[str, dict[str, object]] = {
    "production-safe": {
        "enabled": False,
        "mode": "metadata_only",
        "retention_days": 30,
        "record_live_prefetch": True,
        "record_dry_run": False,
    },
    "test-host": {
        "enabled": True,
        "mode": "metadata_only",
        "retention_days": 30,
        "record_live_prefetch": True,
        "record_dry_run": False,
    },
    "operational": {
        "enabled": True,
        "mode": "metadata_only",
        "retention_days": 30,
        "record_live_prefetch": True,
        "record_dry_run": False,
    },
}


LLM_JUDGE_PRESETS: dict[str, dict[str, object]] = {
    "none": {
        "enabled": True,
        "candidate_limit": 4,
        "llm_judge": {
            "enabled": False,
            "mode": "none",
            "provider": "hermes_default",
            "model": None,
            "temperature": 0,
            "timeout_ms": 8000,
            "max_tokens": 1024,
            "max_candidates": 4,
            "on_error": "deterministic_fallback",
        },
    },
    "report-only": {
        "enabled": True,
        "candidate_limit": 4,
        "llm_judge": {
            "enabled": True,
            "mode": "report_only",
            "provider": "hermes_default",
            "model": None,
            "temperature": 0,
            "timeout_ms": 8000,
            "max_tokens": 1024,
            "max_candidates": 4,
            "on_error": "deterministic_fallback",
        },
    },
    "bounded-vote": {
        "enabled": True,
        "candidate_limit": 4,
        "llm_judge": {
            "enabled": True,
            "mode": "bounded_vote",
            "provider": "hermes_default",
            "model": None,
            "temperature": 0,
            "timeout_ms": 8000,
            "max_tokens": 1024,
            "max_candidates": 4,
            "on_error": "deterministic_fallback",
        },
    },
    "active": {
        "enabled": True,
        "candidate_limit": 4,
        "llm_judge": {
            "enabled": True,
            "mode": "bounded_vote",
            "provider": "hermes_default",
            "model": None,
            "temperature": 0,
            "timeout_ms": 8000,
            "max_tokens": 1024,
            "max_candidates": 4,
            "on_error": "deterministic_fallback",
        },
    },
}


def install_plugin(
    *,
    hermes_home: Path,
    source: Path = SOURCE_PLUGIN_DIR,
    shell_source: Path = SOURCE_AGENT_OS_SHELL_DIR,
    install_shell: bool = True,
    enable: bool = False,
    enable_shell: bool = False,
    install_runtime: bool = False,
    install_system_modules: bool = False,
    enable_runtime: bool = False,
    runtime_interval: str = "5min",
    install_cognitive_loop: bool = False,
    enable_cognitive_loop: bool = False,
    cognitive_loop_interval: str = "6h",
    install_owner_review_cron_helper: bool = False,
    install_right_brain_expression_cron_helper: bool = False,
    install_owner_cron_onboarding: bool = False,
    run_owner_cron_onboarding: bool = False,
    owner_cron_owner_approved: bool = False,
    owner_review_deliver: str = "auto",
    right_brain_deliver: str = "origin",
    owner_review_owner: str = "owner",
    owner_review_channel: str = "owner_review_cron",
    owner_review_schedule: str = "0 9 * * *",
    owner_cron_profile: str = "active-closure",
    right_brain_schedule: str = "30 4 * * 0",
    module_cadence_schedule: str = "15 */6 * * *",
    right_brain_outcome_schedule: str = "45 4 * * 0",
    proposal_followups_schedule: str = "*/30 * * * *",
    expression_feedback_schedule: str = "0 5 * * 0",
    memory_sources_feedback_schedule: str = "30 10 * * *",
    hermes_bin: str = "hermes",
    deep_reflection_preset: str | None = None,
    memory_sources_preset: str | None = None,
    llm_judge_preset: str | None = None,
    systemd_dir: Path | None = None,
    hindsight_mode: str = "auto",
    dry_run: bool = False,
) -> dict[str, object]:
    source = source.expanduser().resolve()
    shell_source = shell_source.expanduser().resolve()
    hermes_home = hermes_home.expanduser().resolve()
    target = hermes_home / "plugins" / "memory_os"
    shell_target = hermes_home / "plugins" / AGENT_OS_SHELL_PLUGIN_NAME
    _guard_plugin_scan_tree_backups(hermes_home)
    _validate_source(source)
    if install_shell:
        _validate_agent_os_shell_source(shell_source)
    if enable_shell and not install_shell and not (shell_target / "plugin.yaml").is_file():
        raise SystemExit(
            f"Cannot enable {AGENT_OS_SHELL_PLUGIN_NAME}: shell plugin is not installed at {shell_target}"
        )

    copied_files = _copy_tree(source, target, dry_run=dry_run)
    shell_files: list[Path] = []
    if install_shell:
        shell_files = _copy_tree(shell_source, shell_target, dry_run=dry_run)
    system_module_files: list[Path] = []
    system_module_root = hermes_home / "memory-os" / "runtime" / "python"
    system_module_target = system_module_root / "plugins"
    agent_runtime_target = system_module_root / "agent"
    eval_runtime_target = system_module_root / "eval"
    agent_runtime_files: list[Path] = []
    eval_runtime_files: list[Path] = []
    if install_system_modules:
        _validate_system_module_source(SOURCE_PACKAGE_DIR)
        system_module_files = _copy_tree(SOURCE_PACKAGE_DIR, system_module_target, dry_run=dry_run)
        _validate_agent_source(SOURCE_AGENT_DIR)
        agent_runtime_files = _copy_tree(SOURCE_AGENT_DIR, agent_runtime_target, dry_run=dry_run)
        _validate_eval_source(SOURCE_EVAL_DIR)
        eval_runtime_files = _copy_tree(SOURCE_EVAL_DIR, eval_runtime_target, dry_run=dry_run)
    deep_reflection_config: dict[str, object] | None = None
    deep_reflection_config_path: Path | None = None
    if deep_reflection_preset is not None:
        deep_reflection_config_path, deep_reflection_config = _write_deep_reflection_config(
            hermes_home,
            preset=deep_reflection_preset,
            dry_run=dry_run,
        )
    memory_sources_config: dict[str, object] | None = None
    memory_sources_config_path: Path | None = None
    if memory_sources_preset is not None:
        memory_sources_config_path, memory_sources_config = _write_memory_sources_config(
            hermes_home,
            preset=memory_sources_preset,
            dry_run=dry_run,
        )
    session_mirror_config: dict[str, object] | None = None
    session_mirror_config_path: Path | None = None
    session_mirror_preset = _session_mirror_preset_for_install(
        deep_reflection_preset=deep_reflection_preset,
        memory_sources_preset=memory_sources_preset,
    )
    if session_mirror_preset is not None:
        session_mirror_config_path, session_mirror_config = _write_session_mirror_config(
            hermes_home,
            preset=session_mirror_preset,
            dry_run=dry_run,
        )
    low_clue_recall_config: dict[str, object] | None = None
    low_clue_recall_config_path: Path | None = None
    if llm_judge_preset is not None:
        low_clue_recall_config_path, low_clue_recall_config = _write_low_clue_recall_config(
            hermes_home,
            preset=llm_judge_preset,
            dry_run=dry_run,
        )
    hindsight_adoption = _configure_hindsight_substrate(
        hermes_home,
        mode=hindsight_mode,
        dry_run=dry_run,
    )
    runtime_artifacts: list[Path] = []
    if install_runtime or enable_runtime:
        runtime_artifacts = _write_runtime_artifacts(
            hermes_home,
            interval=runtime_interval,
            dry_run=dry_run,
        )
    cognitive_loop_artifacts: list[Path] = []
    if install_cognitive_loop or enable_cognitive_loop:
        cognitive_loop_artifacts = _write_cognitive_loop_artifacts(
            hermes_home,
            interval=cognitive_loop_interval,
            dry_run=dry_run,
        )
    owner_review_cron_helper: dict[str, Path] = {}
    if install_owner_review_cron_helper:
        owner_review_cron_helper = _write_owner_review_cron_helper(hermes_home, dry_run=dry_run)
    right_brain_expression_cron_helper: dict[str, Path] = {}
    if install_right_brain_expression_cron_helper:
        right_brain_expression_cron_helper = _write_right_brain_expression_cron_helper(
            hermes_home,
            dry_run=dry_run,
        )
    owner_cron_onboarding_path: Path | None = None
    if install_owner_cron_onboarding or run_owner_cron_onboarding:
        owner_cron_onboarding_path = _write_owner_cron_onboarding_script(hermes_home, dry_run=dry_run)
    module_cadence_report: Path | None = None
    operational_helper_paths: dict[str, Path] = {}
    if install_system_modules:
        module_cadence_report = _write_module_cadence_report_script(hermes_home, dry_run=dry_run)
        operational_helper_paths = _write_operational_helper_scripts(hermes_home, dry_run=dry_run)
    owner_cron_onboarding_report: dict[str, object] = {}
    enabled = False
    enable_command: list[str] = []
    if enable:
        enable_command = ["hermes", "config", "set", "memory.provider", "memory_os"]
        if not dry_run:
            _enable_memory_provider(hermes_home, enable_command)
            enabled = True

    shell_enabled = False
    shell_enable_action = ""
    if enable_shell:
        shell_enable_action = "config_yaml"
        if not dry_run:
            _enable_agent_os_shell(hermes_home)
            shell_enabled = True
    if run_owner_cron_onboarding:
        if not owner_review_cron_helper:
            owner_review_cron_helper = _write_owner_review_cron_helper(hermes_home, dry_run=dry_run)
        if not right_brain_expression_cron_helper:
            right_brain_expression_cron_helper = _write_right_brain_expression_cron_helper(
                hermes_home,
                dry_run=dry_run,
            )
        if module_cadence_report is None:
            module_cadence_report = _write_module_cadence_report_script(hermes_home, dry_run=dry_run)
        if not operational_helper_paths:
            operational_helper_paths = _write_operational_helper_scripts(hermes_home, dry_run=dry_run)
        if not dry_run:
            owner_cron_onboarding_report = _run_owner_cron_onboarding(
                hermes_home=hermes_home,
                hermes_bin=hermes_bin,
                owner_approved=owner_cron_owner_approved,
                owner_review_deliver=owner_review_deliver,
                right_brain_deliver=right_brain_deliver,
                owner_review_owner=owner_review_owner,
                owner_review_channel=owner_review_channel,
                owner_review_schedule=owner_review_schedule,
                owner_cron_profile=owner_cron_profile,
                right_brain_schedule=right_brain_schedule,
                module_cadence_schedule=module_cadence_schedule,
                right_brain_outcome_schedule=right_brain_outcome_schedule,
                proposal_followups_schedule=proposal_followups_schedule,
                expression_feedback_schedule=expression_feedback_schedule,
                memory_sources_feedback_schedule=memory_sources_feedback_schedule,
            )
        else:
            owner_cron_onboarding_report = {"status": "dry_run"}

    runtime_enabled = False
    runtime_enable_command: list[str] = []
    if enable_runtime:
        if not install_runtime:
            runtime_artifacts = _write_runtime_artifacts(
                hermes_home,
                interval=runtime_interval,
                dry_run=dry_run,
            )
        unit_dir = (systemd_dir or (Path.home() / ".config" / "systemd" / "user")).expanduser().resolve()
        service_src = hermes_home / "memory-os" / "systemd" / "hermes-memory-os-heartbeat.service"
        timer_src = hermes_home / "memory-os" / "systemd" / "hermes-memory-os-heartbeat.timer"
        runtime_enable_command = [
            "systemctl",
            "--user",
            "enable",
            "--now",
            "hermes-memory-os-heartbeat.timer",
        ]
        if not dry_run:
            unit_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(service_src, unit_dir / service_src.name)
            shutil.copy2(timer_src, unit_dir / timer_src.name)
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
            subprocess.run(runtime_enable_command, check=True)
            runtime_enabled = True

    cognitive_loop_enabled = False
    cognitive_loop_enable_command: list[str] = []
    if enable_cognitive_loop:
        if not install_cognitive_loop:
            cognitive_loop_artifacts = _write_cognitive_loop_artifacts(
                hermes_home,
                interval=cognitive_loop_interval,
                dry_run=dry_run,
            )
        unit_dir = (systemd_dir or (Path.home() / ".config" / "systemd" / "user")).expanduser().resolve()
        service_src = hermes_home / "memory-os" / "systemd" / "hermes-memory-os-cognitive-loop.service"
        timer_src = hermes_home / "memory-os" / "systemd" / "hermes-memory-os-cognitive-loop.timer"
        cognitive_loop_enable_command = [
            "systemctl",
            "--user",
            "enable",
            "--now",
            "hermes-memory-os-cognitive-loop.timer",
        ]
        if not dry_run:
            unit_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(service_src, unit_dir / service_src.name)
            shutil.copy2(timer_src, unit_dir / timer_src.name)
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
            subprocess.run(cognitive_loop_enable_command, check=True)
            cognitive_loop_enabled = True

    return {
        "schema_version": "memory-os.install.v0",
        "provider": "memory_os",
        "source": str(source),
        "target": str(target),
        "copied_file_count": len(copied_files),
        "copied_files": [str(path.relative_to(target)) for path in copied_files],
        "agent_os_shell": AGENT_OS_SHELL_PLUGIN_NAME,
        "agent_os_shell_install_requested": install_shell,
        "agent_os_shell_installed": bool(shell_files) and not dry_run,
        "agent_os_shell_source": str(shell_source),
        "agent_os_shell_target": str(shell_target),
        "agent_os_shell_file_count": len(shell_files),
        "agent_os_shell_files": [str(path.relative_to(shell_target)) for path in shell_files],
        "agent_os_shell_enable_requested": enable_shell,
        "agent_os_shell_enabled": shell_enabled,
        "agent_os_shell_enable_action": shell_enable_action,
        "system_modules_install_requested": install_system_modules,
        "system_modules_installed": bool(system_module_files) and not dry_run,
        "system_module_target": str(system_module_target),
        "system_module_file_count": len(system_module_files),
        "system_module_files": [str(path.relative_to(system_module_target)) for path in system_module_files],
        "agent_runtime_target": str(agent_runtime_target),
        "agent_runtime_file_count": len(agent_runtime_files),
        "agent_runtime_files": [str(path.relative_to(agent_runtime_target)) for path in agent_runtime_files],
        "eval_runtime_target": str(eval_runtime_target),
        "eval_runtime_file_count": len(eval_runtime_files),
        "eval_runtime_files": [str(path.relative_to(eval_runtime_target)) for path in eval_runtime_files],
        "enable_requested": enable,
        "enabled": enabled,
        "enable_command": enable_command,
        "runtime_artifacts_installed": bool(runtime_artifacts) and not dry_run,
        "runtime_artifacts": [str(path) for path in runtime_artifacts],
        "runtime_interval": runtime_interval,
        "runtime_enable_requested": enable_runtime,
        "runtime_enabled": runtime_enabled,
        "runtime_enable_command": runtime_enable_command,
        "cognitive_loop_artifacts_installed": bool(cognitive_loop_artifacts) and not dry_run,
        "cognitive_loop_artifacts": [str(path) for path in cognitive_loop_artifacts],
        "cognitive_loop_interval": cognitive_loop_interval,
        "cognitive_loop_enable_requested": enable_cognitive_loop,
        "cognitive_loop_enabled": cognitive_loop_enabled,
        "cognitive_loop_enable_command": cognitive_loop_enable_command,
        "owner_review_cron_helper_install_requested": install_owner_review_cron_helper,
        "owner_review_cron_helper_installed": bool(owner_review_cron_helper.get("helper")) and not dry_run,
        "owner_review_cron_helper_path": str(owner_review_cron_helper.get("helper") or ""),
        "owner_review_cron_gate_path": str(owner_review_cron_helper.get("gate") or ""),
        "right_brain_expression_cron_helper_install_requested": install_right_brain_expression_cron_helper,
        "right_brain_expression_cron_helper_installed": bool(right_brain_expression_cron_helper.get("helper")) and not dry_run,
        "right_brain_expression_cron_helper_path": str(right_brain_expression_cron_helper.get("helper") or ""),
        "right_brain_expression_cron_gate_path": str(right_brain_expression_cron_helper.get("gate") or ""),
        "right_brain_expression_outcome_path": str(right_brain_expression_cron_helper.get("outcome") or ""),
        "owner_cron_onboarding_install_requested": install_owner_cron_onboarding or run_owner_cron_onboarding,
        "owner_cron_onboarding_installed": bool(owner_cron_onboarding_path) and not dry_run,
        "owner_cron_onboarding_path": str(owner_cron_onboarding_path or ""),
        "owner_cron_onboarding_run_requested": run_owner_cron_onboarding,
        "owner_cron_onboarding_run_status": str(owner_cron_onboarding_report.get("status") or ""),
        "owner_cron_profile": owner_cron_profile,
        "owner_cron_onboarding_report": owner_cron_onboarding_report,
        "module_cadence_report_path": str(module_cadence_report or ""),
        "module_cadence_report_cron_path": str(operational_helper_paths.get("module_cadence_report_cron") or ""),
        "right_brain_expression_outcome_cron_path": str(operational_helper_paths.get("right_brain_expression_outcome_cron") or ""),
        "expression_feedback_prompt_path": str(operational_helper_paths.get("expression_feedback_prompt") or ""),
        "memory_sources_feedback_prompt_path": str(operational_helper_paths.get("memory_sources_feedback_prompt") or ""),
        "proposal_followups_ops_gate_path": str(operational_helper_paths.get("proposal_followups_ops_gate") or ""),
        "deep_reflection_preset": deep_reflection_preset,
        "deep_reflection_config_written": bool(deep_reflection_config_path) and not dry_run,
        "deep_reflection_config_path": str(deep_reflection_config_path) if deep_reflection_config_path else "",
        "deep_reflection_config": deep_reflection_config or {},
        "memory_sources_preset": memory_sources_preset,
        "memory_sources_config_written": bool(memory_sources_config_path) and not dry_run,
        "memory_sources_config_path": str(memory_sources_config_path) if memory_sources_config_path else "",
        "memory_sources_config": memory_sources_config or {},
        "session_mirror_preset": session_mirror_preset,
        "session_mirror_config_written": bool(session_mirror_config_path) and not dry_run,
        "session_mirror_config_path": str(session_mirror_config_path) if session_mirror_config_path else "",
        "session_mirror_config": session_mirror_config or {},
        "llm_judge_preset": llm_judge_preset,
        "low_clue_recall_config_written": bool(low_clue_recall_config_path) and not dry_run,
        "low_clue_recall_config_path": str(low_clue_recall_config_path) if low_clue_recall_config_path else "",
        "low_clue_recall_config": low_clue_recall_config or {},
        "hindsight_mode": hindsight_mode,
        "hindsight_adoption": hindsight_adoption,
        "dry_run": dry_run,
    }


def _validate_source(source: Path) -> None:
    required = ("__init__.py", "plugin.yaml", "cli.py")
    missing = [name for name in required if not (source / name).is_file()]
    if missing:
        raise SystemExit(f"Memory-OS plugin source is missing: {', '.join(missing)}")


def _validate_agent_os_shell_source(source: Path) -> None:
    required = ("__init__.py", "plugin.yaml")
    missing = [name for name in required if not (source / name).is_file()]
    if missing:
        raise SystemExit(f"Memory-OS Agent OS shell source is missing: {', '.join(missing)}")
    text = (source / "plugin.yaml").read_text(encoding="utf-8")
    if f"name: {AGENT_OS_SHELL_PLUGIN_NAME}" not in text:
        raise SystemExit("Memory-OS Agent OS shell plugin.yaml has the wrong plugin name")


def _validate_system_module_source(source: Path) -> None:
    required = (
        "system/lifecycle.py",
        "system/scheduler.py",
        "modules/context/digest_consolidation.py",
        "modules/cognition/deep_reflection.py",
        "modules/cognition/inner_drive.py",
        "modules/expression/speak_gate.py",
        "modules/governance/feedback_bridge.py",
        "memory/memory_os/store.py",
    )
    missing = [name for name in required if not (source / name).is_file()]
    if missing:
        raise SystemExit(f"Memory-OS system module source is missing: {', '.join(missing)}")


def _validate_agent_source(source: Path) -> None:
    required = ("__init__.py", "memory_provider.py")
    missing = [name for name in required if not (source / name).is_file()]
    if missing:
        raise SystemExit(f"Memory-OS agent compatibility source is missing: {', '.join(missing)}")


def _validate_eval_source(source: Path) -> None:
    required = (
        "__init__.py",
        "memory_os/__init__.py",
        "memory_os/runner/run.py",
        "memory_os/runner/inventory.py",
        "memory_os/adapters/grep.py",
    )
    missing = [name for name in required if not (source / name).is_file()]
    if missing:
        raise SystemExit(f"Memory-OS eval source is missing: {', '.join(missing)}")


def _copy_tree(source: Path, target: Path, *, dry_run: bool) -> list[Path]:
    files = [
        path for path in sorted(source.rglob("*"))
        if path.is_file() and not _is_excluded(path)
    ]
    copied: list[Path] = []
    for src in files:
        rel = src.relative_to(source)
        dst = target / rel
        copied.append(dst)
        if dry_run:
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    return copied


def _is_excluded(path: Path) -> bool:
    return (
        "__pycache__" in path.parts
        or (("eval" in path.parts) and ("reports" in path.parts))
        or path.suffix in {".pyc", ".pyo"}
    )


def _guard_plugin_scan_tree_backups(hermes_home: Path) -> None:
    plugins_root = hermes_home / "plugins"
    if not plugins_root.exists():
        return
    for manifest in sorted(plugins_root.rglob("plugin.yaml")):
        rel = manifest.relative_to(plugins_root)
        top_level = rel.parts[0] if rel.parts else ""
        if top_level in {MEMORY_PROVIDER_PLUGIN_NAME, AGENT_OS_SHELL_PLUGIN_NAME}:
            continue
        if not _looks_like_memory_os_backup_path(rel):
            continue
        raise SystemExit(
            "plugin backup manifest inside plugin scan tree: "
            f"{rel}. Move backups to {hermes_home / 'plugin-backups'}."
        )


def _looks_like_memory_os_backup_path(rel: Path) -> bool:
    text = str(rel).lower()
    backup_markers = (".bak", ".backup", ".bad", "backup", "old")
    memory_os_names = (MEMORY_PROVIDER_PLUGIN_NAME.lower(), AGENT_OS_SHELL_PLUGIN_NAME.lower())
    return any(name in text for name in memory_os_names) and any(marker in text for marker in backup_markers)


def _enable_memory_provider(hermes_home: Path, enable_command: list[str]) -> None:
    _run_required_command(
        enable_command,
        missing_message=(
            "Cannot enable memory.provider=memory_os because the `hermes` command "
            "was not found in PATH. Use scripts/install_memory_os.sh for preflight "
            "checks, or install/copy files without --enable."
        ),
        env={**dict(os.environ), "HERMES_HOME": str(hermes_home)},
        stdout=subprocess.DEVNULL,
    )


def _run_required_command(command: list[str], *, missing_message: str, **kwargs: object) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(command, check=True, **kwargs)
    except FileNotFoundError as exc:
        raise SystemExit(missing_message) from exc


def _enable_agent_os_shell(hermes_home: Path) -> None:
    config_path = hermes_home / "config.yaml"
    config = _read_yaml_config(config_path)
    plugins_config = config.get("plugins")
    if not isinstance(plugins_config, dict):
        plugins_config = {}
    enabled = plugins_config.get("enabled")
    if not isinstance(enabled, list):
        enabled = []
    disabled = plugins_config.get("disabled")
    if isinstance(disabled, list):
        disabled_normalized = [
            str(item)
            for item in disabled
            if str(item) != AGENT_OS_SHELL_PLUGIN_NAME
        ]
        if disabled_normalized:
            plugins_config["disabled"] = disabled_normalized
        else:
            plugins_config.pop("disabled", None)
    normalized: list[str] = []
    for item in enabled:
        value = str(item)
        if value == MEMORY_PROVIDER_PLUGIN_NAME:
            continue
        if value not in normalized:
            normalized.append(value)
    if AGENT_OS_SHELL_PLUGIN_NAME not in normalized:
        normalized.append(AGENT_OS_SHELL_PLUGIN_NAME)
    plugins_config["enabled"] = normalized
    config["plugins"] = plugins_config
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _read_yaml_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        return {}
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        return {}
    return dict(loaded)


def _write_runtime_artifacts(hermes_home: Path, *, interval: str, dry_run: bool) -> list[Path]:
    runtime_root = hermes_home / "memory-os"
    wrapper = runtime_root / "bin" / "memory_os_heartbeat.sh"
    service = runtime_root / "systemd" / "hermes-memory-os-heartbeat.service"
    timer = runtime_root / "systemd" / "hermes-memory-os-heartbeat.timer"
    artifacts = [wrapper, service, timer]
    if dry_run:
        return artifacts
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    service.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"export HERMES_HOME={_shell_quote(str(hermes_home))}\n"
        "export PYTHONPATH=\"${HERMES_HOME}/memory-os/runtime/python:${HERMES_HOME}/plugins:${PYTHONPATH:-}\"\n"
        "exec python3 -m plugins.memory.memory_os heartbeat --max-events 100\n",
        encoding="utf-8",
    )
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)
    service.write_text(
        "[Unit]\n"
        "Description=Hermes Memory-OS heartbeat\n\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"ExecStart={wrapper}\n",
        encoding="utf-8",
    )
    timer.write_text(
        "[Unit]\n"
        "Description=Run Hermes Memory-OS heartbeat periodically\n\n"
        "[Timer]\n"
        f"OnBootSec={interval}\n"
        f"OnUnitActiveSec={interval}\n"
        "AccuracySec=30s\n\n"
        "[Install]\n"
        "WantedBy=timers.target\n",
        encoding="utf-8",
    )
    return artifacts


def _write_cognitive_loop_artifacts(hermes_home: Path, *, interval: str, dry_run: bool) -> list[Path]:
    runtime_root = hermes_home / "memory-os"
    wrapper = runtime_root / "bin" / "memory_os_cognitive_loop.sh"
    service = runtime_root / "systemd" / "hermes-memory-os-cognitive-loop.service"
    timer = runtime_root / "systemd" / "hermes-memory-os-cognitive-loop.timer"
    artifacts = [wrapper, service, timer]
    if dry_run:
        return artifacts
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    service.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"export HERMES_HOME={_shell_quote(str(hermes_home))}\n"
        "export PYTHONPATH=\"${HERMES_HOME}/memory-os/runtime/python:${HERMES_HOME}/plugins:${PYTHONPATH:-}\"\n"
        "exec python3 -m plugins.memory.memory_os cognitive-loop run-once --test-host --apply\n",
        encoding="utf-8",
    )
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)
    service.write_text(
        "[Unit]\n"
        "Description=Hermes Memory-OS test-host cognitive loop\n\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"ExecStart={wrapper}\n",
        encoding="utf-8",
    )
    timer.write_text(
        "[Unit]\n"
        "Description=Run Hermes Memory-OS test-host cognitive loop periodically\n\n"
        "[Timer]\n"
        f"OnBootSec={interval}\n"
        f"OnUnitActiveSec={interval}\n"
        "AccuracySec=30s\n"
        "Persistent=true\n\n"
        "[Install]\n"
        "WantedBy=timers.target\n",
        encoding="utf-8",
    )
    return artifacts


def _write_owner_review_cron_helper(hermes_home: Path, *, dry_run: bool) -> dict[str, Path]:
    if not SOURCE_OWNER_REVIEW_CRON_HELPER.is_file():
        raise SystemExit(f"Owner review cron helper source is missing: {SOURCE_OWNER_REVIEW_CRON_HELPER}")
    if not SOURCE_OWNER_REVIEW_CRON_GATE.is_file():
        raise SystemExit(f"Owner review cron gate source is missing: {SOURCE_OWNER_REVIEW_CRON_GATE}")
    helper_target = hermes_home / "scripts" / SOURCE_OWNER_REVIEW_CRON_HELPER.name
    gate_target = hermes_home / "scripts" / SOURCE_OWNER_REVIEW_CRON_GATE.name
    if dry_run:
        return {"helper": helper_target, "gate": gate_target}
    helper_target.parent.mkdir(parents=True, exist_ok=True)
    for source, target in (
        (SOURCE_OWNER_REVIEW_CRON_HELPER, helper_target),
        (SOURCE_OWNER_REVIEW_CRON_GATE, gate_target),
    ):
        shutil.copy2(source, target)
        target.chmod(target.stat().st_mode | stat.S_IXUSR)
    return {"helper": helper_target, "gate": gate_target}


def _write_right_brain_expression_cron_helper(hermes_home: Path, *, dry_run: bool) -> dict[str, Path]:
    if not SOURCE_RIGHT_BRAIN_EXPRESSION_CRON_HELPER.is_file():
        raise SystemExit(f"Right-brain expression cron helper source is missing: {SOURCE_RIGHT_BRAIN_EXPRESSION_CRON_HELPER}")
    if not SOURCE_RIGHT_BRAIN_EXPRESSION_CRON_GATE.is_file():
        raise SystemExit(f"Right-brain expression cron gate source is missing: {SOURCE_RIGHT_BRAIN_EXPRESSION_CRON_GATE}")
    if not SOURCE_RIGHT_BRAIN_EXPRESSION_OUTCOME.is_file():
        raise SystemExit(f"Right-brain expression outcome source is missing: {SOURCE_RIGHT_BRAIN_EXPRESSION_OUTCOME}")
    helper_target = hermes_home / "scripts" / SOURCE_RIGHT_BRAIN_EXPRESSION_CRON_HELPER.name
    gate_target = hermes_home / "scripts" / SOURCE_RIGHT_BRAIN_EXPRESSION_CRON_GATE.name
    outcome_target = hermes_home / "scripts" / SOURCE_RIGHT_BRAIN_EXPRESSION_OUTCOME.name
    if dry_run:
        return {"helper": helper_target, "gate": gate_target, "outcome": outcome_target}
    helper_target.parent.mkdir(parents=True, exist_ok=True)
    for source, target in (
        (SOURCE_RIGHT_BRAIN_EXPRESSION_CRON_HELPER, helper_target),
        (SOURCE_RIGHT_BRAIN_EXPRESSION_CRON_GATE, gate_target),
        (SOURCE_RIGHT_BRAIN_EXPRESSION_OUTCOME, outcome_target),
    ):
        shutil.copy2(source, target)
        target.chmod(target.stat().st_mode | stat.S_IXUSR)
    return {"helper": helper_target, "gate": gate_target, "outcome": outcome_target}


def _write_module_cadence_report_script(hermes_home: Path, *, dry_run: bool) -> Path:
    if not SOURCE_MODULE_CADENCE_REPORT.is_file():
        raise SystemExit(f"Module cadence report source is missing: {SOURCE_MODULE_CADENCE_REPORT}")
    target = hermes_home / "scripts" / SOURCE_MODULE_CADENCE_REPORT.name
    if dry_run:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE_MODULE_CADENCE_REPORT, target)
    target.chmod(target.stat().st_mode | stat.S_IXUSR)
    return target


def _write_operational_helper_scripts(hermes_home: Path, *, dry_run: bool) -> dict[str, Path]:
    sources = {
        "module_cadence_report_cron": SOURCE_MODULE_CADENCE_REPORT_CRON,
        "right_brain_expression_outcome_cron": SOURCE_RIGHT_BRAIN_EXPRESSION_OUTCOME_CRON,
        "expression_feedback_prompt": SOURCE_EXPRESSION_FEEDBACK_PROMPT,
        "memory_sources_feedback_prompt": SOURCE_MEMORY_SOURCES_FEEDBACK_PROMPT,
        "proposal_followups_ops_gate": SOURCE_PROPOSAL_FOLLOWUPS_OPS_GATE,
        "execution_report_helper": SOURCE_EXECUTION_REPORT_HELPER,
        "candidate_aggregation_lane": SOURCE_CANDIDATE_AGGREGATION_LANE,
    }
    targets: dict[str, Path] = {}
    for key, source in sources.items():
        if not source.is_file():
            raise SystemExit(f"Operational helper source is missing: {source}")
        targets[key] = hermes_home / "scripts" / source.name
    if dry_run:
        return targets
    for key, source in sources.items():
        target = targets[key]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        target.chmod(target.stat().st_mode | stat.S_IXUSR)
    return targets


def _write_owner_cron_onboarding_script(hermes_home: Path, *, dry_run: bool) -> Path:
    if not SOURCE_OWNER_CRON_ONBOARDING.is_file():
        raise SystemExit(f"Owner cron onboarding source is missing: {SOURCE_OWNER_CRON_ONBOARDING}")
    if not SOURCE_EXECUTION_GATE_RUNNER.is_file():
        raise SystemExit(f"Execution gate runner source is missing: {SOURCE_EXECUTION_GATE_RUNNER}")
    target = hermes_home / "scripts" / SOURCE_OWNER_CRON_ONBOARDING.name
    if dry_run:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE_OWNER_CRON_ONBOARDING, target)
    target.chmod(target.stat().st_mode | stat.S_IXUSR)
    runner_target = hermes_home / "scripts" / SOURCE_EXECUTION_GATE_RUNNER.name
    shutil.copy2(SOURCE_EXECUTION_GATE_RUNNER, runner_target)
    runner_target.chmod(runner_target.stat().st_mode | stat.S_IXUSR)
    return target


def _run_owner_cron_onboarding(
    *,
    hermes_home: Path,
    hermes_bin: str,
    owner_approved: bool,
    owner_review_deliver: str,
    right_brain_deliver: str,
    owner_review_owner: str,
    owner_review_channel: str,
    owner_review_schedule: str,
    owner_cron_profile: str,
    right_brain_schedule: str,
    module_cadence_schedule: str,
    right_brain_outcome_schedule: str,
    proposal_followups_schedule: str,
    expression_feedback_schedule: str,
    memory_sources_feedback_schedule: str,
) -> dict[str, object]:
    module = _load_python_script_module(SOURCE_OWNER_CRON_ONBOARDING)
    argv = [
        "--hermes-home",
        str(hermes_home),
        "--hermes-bin",
        hermes_bin,
        "--owner-review-deliver",
        owner_review_deliver,
        "--right-brain-deliver",
        right_brain_deliver,
        "--owner",
        owner_review_owner,
        "--channel",
        owner_review_channel,
        "--owner-review-schedule",
        owner_review_schedule,
        "--cron-profile",
        owner_cron_profile,
        "--right-brain-schedule",
        right_brain_schedule,
        "--module-cadence-schedule",
        module_cadence_schedule,
        "--right-brain-outcome-schedule",
        right_brain_outcome_schedule,
        "--proposal-followups-schedule",
        proposal_followups_schedule,
        "--expression-feedback-schedule",
        expression_feedback_schedule,
        "--memory-sources-feedback-schedule",
        memory_sources_feedback_schedule,
        "--candidate-aggregation-schedule",
        "0 */6 * * *",
        "--apply",
    ]
    if owner_approved:
        argv.append("--owner-approved")
    args = module.build_parser().parse_args(argv)
    report = module.run_onboarding(args)
    if isinstance(report, dict):
        return dict(report)
    return {"status": "error", "error": "owner cron onboarding returned a non-dict report"}


def _load_python_script_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _write_deep_reflection_config(
    hermes_home: Path,
    *,
    preset: str,
    dry_run: bool,
) -> tuple[Path, dict[str, object]]:
    if preset not in DEEP_REFLECTION_PRESETS:
        choices = ", ".join(sorted(DEEP_REFLECTION_PRESETS))
        raise SystemExit(f"Unsupported DeepReflection preset: {preset}. Choices: {choices}")
    config = {
        **DEEP_REFLECTION_CONFIG_DEFAULTS,
        **DEEP_REFLECTION_PRESETS[preset],
        "preset": preset,
    }
    config_path = hermes_home / "system-modules" / "deep_reflection" / "config.json"
    if not dry_run:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return config_path, config


def _write_memory_sources_config(
    hermes_home: Path,
    *,
    preset: str,
    dry_run: bool,
) -> tuple[Path, dict[str, object]]:
    if preset not in MEMORY_SOURCES_PRESETS:
        choices = ", ".join(sorted(MEMORY_SOURCES_PRESETS))
        raise SystemExit(f"Unsupported Memory Sources preset: {preset}. Choices: {choices}")
    config_path = hermes_home / "memory-os" / "config.json"
    config = _read_json_config(config_path)
    memory_sources_config = {
        **MEMORY_SOURCES_PRESETS[preset],
        "preset": preset,
    }
    config["memory_sources"] = memory_sources_config
    if not dry_run:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return config_path, memory_sources_config


def _session_mirror_preset_for_install(
    *,
    deep_reflection_preset: str | None,
    memory_sources_preset: str | None,
) -> str | None:
    presets = {str(item) for item in (deep_reflection_preset, memory_sources_preset) if item}
    if "test-host" in presets:
        return "test-host"
    if "production-safe" in presets:
        return "production-safe"
    return None


def _write_session_mirror_config(
    hermes_home: Path,
    *,
    preset: str,
    dry_run: bool,
) -> tuple[Path, dict[str, object]]:
    if preset not in {"production-safe", "test-host"}:
        raise SystemExit(f"Unsupported SessionMirror preset: {preset}. Choices: production-safe, test-host")
    config_path = hermes_home / "memory-os" / "config.json"
    config = _read_json_config(config_path)
    session_mirror_config = {
        "preset": preset,
        "test_host_apply_allowed": preset == "test-host",
        "test_host_marker": "install_preset:test-host" if preset == "test-host" else "",
        "production_apply_owner_ref_required": True,
    }
    config["session_mirror"] = session_mirror_config
    if not dry_run:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return config_path, session_mirror_config


def _write_low_clue_recall_config(
    hermes_home: Path,
    *,
    preset: str,
    dry_run: bool,
) -> tuple[Path, dict[str, object]]:
    if preset not in LLM_JUDGE_PRESETS:
        choices = ", ".join(sorted(LLM_JUDGE_PRESETS))
        raise SystemExit(f"Unsupported Low-Clue LLM judge preset: {preset}. Choices: {choices}")
    config_path = hermes_home / "memory-os" / "config.json"
    config = _read_json_config(config_path)
    low_clue_recall_config = {
        **LLM_JUDGE_PRESETS[preset],
        "preset": preset,
    }
    config["low_clue_recall"] = low_clue_recall_config
    if not dry_run:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return config_path, low_clue_recall_config


def _read_json_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        return {}
    loaded = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        return {}
    return dict(loaded)


def _configure_hindsight_substrate(hermes_home: Path, *, mode: str, dry_run: bool) -> dict[str, Any]:
    if mode not in {"auto", "off", "adopt", "active", "wizard"}:
        raise SystemExit("--hindsight must be one of: auto, off, adopt, active, wizard")
    if mode == "off":
        planned = _hindsight_disabled_config()
        if not dry_run:
            _save_memory_os_config({"substrate_providers": {"hindsight": planned}}, hermes_home)
        return {"status": "disabled", "mode": mode, "planned_config": _redacted_hindsight_config(planned)}
    if mode == "wizard":
        return {"status": "wizard_deferred", "mode": mode}

    provider_config = _load_hindsight_provider_config(hermes_home)
    provider_path = provider_config["path"]
    if not provider_config["exists"]:
        if mode == "adopt":
            raise SystemExit("Cannot adopt Hindsight: existing provider hindsight/config.json not found")
        return {"status": "not_configured", "mode": mode}
    raw = provider_config["raw"]
    selection = provider_config["selection"]
    selected_bank_id = str(selection.get("selected_bank_id") or "")
    if not selected_bank_id:
        if mode == "adopt":
            raise SystemExit(f"Cannot adopt Hindsight: provider bank is ambiguous in {provider_path}")
        return {
            "status": "ambiguous_provider_bank",
            "mode": mode,
            "detected": _redacted_hindsight_detected(provider_config),
        }

    existing_config = _read_json_config(hermes_home / "memory-os" / "config.json")
    existing_substrates = (
        existing_config.get("substrate_providers") if isinstance(existing_config.get("substrate_providers"), dict) else {}
    )
    existing_hindsight = (
        existing_substrates.get("hindsight") if isinstance(existing_substrates.get("hindsight"), dict) else {}
    )
    same_adopted_bank = (
        bool(existing_hindsight.get("enabled"))
        and str(existing_hindsight.get("adoption_source") or "") == "hermes_hindsight_config"
        and str(existing_hindsight.get("bank_id") or "") == selected_bank_id
        and str(existing_hindsight.get("provider_bank_id") or selected_bank_id) == selected_bank_id
    )
    preserve_existing_active = mode == "auto" and same_adopted_bank and str(existing_hindsight.get("recall_mode") or "") == "active"
    active_requested = mode == "active"

    planned = {
        "enabled": True,
        "adoption_source": "hermes_hindsight_config",
        "api_url": str(raw.get("api_url") or ""),
        "bank_id": selected_bank_id,
        "provider_config_path": str(provider_path),
        "provider_bank_id": selected_bank_id,
        "bank_selection_reason": str(selection.get("reason") or "provider_config"),
        "configured_provider_bank_ids": list(selection.get("configured_bank_ids") or []),
        "non_provider_configured_bank_count": int(selection.get("non_provider_configured_bank_count") or 0),
        "api_key": "",
        "api_key_env_var": "HINDSIGHT_API_KEY",
        "retain_enabled": True if active_requested else bool(existing_hindsight.get("retain_enabled")) if preserve_existing_active else False,
        "recall_mode": "active" if active_requested or preserve_existing_active else "shadow",
        "reflect_enabled": True if active_requested else bool(existing_hindsight.get("reflect_enabled")) if preserve_existing_active else False,
        "legacy_provider_was_hindsight": _memory_provider_is_hindsight(hermes_home),
        "legacy_auto_retain_observed_disabled": raw.get("auto_retain") is False,
    }
    if not dry_run:
        _save_memory_os_config({"substrate_providers": {"hindsight": planned}}, hermes_home)
    status = "adopted_active" if active_requested else "preserved_active" if preserve_existing_active else "adopted_shadow"
    return {
        "status": status,
        "mode": mode,
        "detected": _redacted_hindsight_detected(provider_config),
        "planned_config": _redacted_hindsight_config(planned),
    }


def _load_hindsight_provider_config(hermes_home: Path) -> dict[str, Any]:
    path = hermes_home / "hindsight" / "config.json"
    if not path.exists():
        return {"exists": False, "path": path, "raw": {}, "selection": _select_hindsight_provider_bank({})}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Cannot adopt Hindsight: invalid JSON in {path}") from exc
    if not isinstance(raw, dict):
        raise SystemExit(f"Cannot adopt Hindsight: expected JSON object in {path}")
    return {"exists": True, "path": path, "raw": raw, "selection": _select_hindsight_provider_bank(raw)}


def _select_hindsight_provider_bank(raw: dict[str, Any]) -> dict[str, Any]:
    banks = raw.get("banks") if isinstance(raw.get("banks"), dict) else {}
    configured_bank_ids: list[str] = []
    enabled_bank_ids: list[str] = []
    for key, value in banks.items():
        bank_id = str(key)
        enabled = True
        if isinstance(value, dict):
            bank_id = str(value.get("bankId") or key)
            enabled = value.get("enabled") is not False
        if bank_id and bank_id not in configured_bank_ids:
            configured_bank_ids.append(bank_id)
        if enabled and bank_id and bank_id not in enabled_bank_ids:
            enabled_bank_ids.append(bank_id)

    top_level_bank_id = str(raw.get("bank_id") or "").strip()
    selected_bank_id = ""
    reason = "not_selected"
    if top_level_bank_id:
        selected_bank_id = top_level_bank_id
        reason = "top_level_provider_bank_id"
    elif len(enabled_bank_ids) == 1:
        selected_bank_id = enabled_bank_ids[0]
        reason = "single_enabled_provider_bank"
    elif len(configured_bank_ids) == 1:
        selected_bank_id = configured_bank_ids[0]
        reason = "single_configured_provider_bank"
    elif configured_bank_ids or enabled_bank_ids:
        reason = "ambiguous_provider_bank"

    return {
        "selected_bank_id": selected_bank_id,
        "reason": reason,
        "configured_bank_ids": configured_bank_ids,
        "enabled_bank_ids": enabled_bank_ids,
        "non_provider_configured_bank_count": len(
            [bank_id for bank_id in configured_bank_ids if bank_id != selected_bank_id]
        ),
    }


def _redacted_hindsight_detected(provider_config: dict[str, Any]) -> dict[str, Any]:
    raw = provider_config.get("raw") if isinstance(provider_config.get("raw"), dict) else {}
    selection = provider_config.get("selection") if isinstance(provider_config.get("selection"), dict) else {}
    return {
        "provider_config_path": str(provider_config.get("path") or ""),
        "api_url_configured": bool(raw.get("api_url")),
        "bank_id": str(selection.get("selected_bank_id") or ""),
        "provider_bank_id": str(selection.get("selected_bank_id") or ""),
        "bank_selection_reason": str(selection.get("reason") or "not_selected"),
        "configured_provider_bank_ids": list(selection.get("configured_bank_ids") or []),
        "non_provider_configured_bank_count": int(selection.get("non_provider_configured_bank_count") or 0),
        "auto_retain": raw.get("auto_retain"),
        "api_key_configured": bool(raw.get("apiKey") or raw.get("api_key")),
    }


def _hindsight_disabled_config() -> dict[str, Any]:
    return {
        "enabled": False,
        "adoption_source": "none",
        "api_url": "",
        "bank_id": "",
        "provider_config_path": "",
        "provider_bank_id": "",
        "bank_selection_reason": "not_selected",
        "configured_provider_bank_ids": [],
        "non_provider_configured_bank_count": 0,
        "api_key": "",
        "api_key_env_var": "HINDSIGHT_API_KEY",
        "retain_enabled": False,
        "recall_mode": "off",
        "reflect_enabled": False,
        "legacy_provider_was_hindsight": False,
        "legacy_auto_retain_observed_disabled": False,
    }


def _redacted_hindsight_config(config: dict[str, Any]) -> dict[str, Any]:
    redacted = dict(config)
    redacted.pop("api_key", None)
    return redacted


def _save_memory_os_config(values: dict[str, Any], hermes_home: Path) -> None:
    from plugins.memory.memory_os.config import save_config

    save_config(values, hermes_home)


def _memory_provider_is_hindsight(hermes_home: Path) -> bool:
    config = _read_yaml_config(hermes_home / "config.yaml")
    memory = config.get("memory") if isinstance(config.get("memory"), dict) else {}
    return str(memory.get("provider") or "") == "hindsight"


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hermes-home", required=True, help="Target HERMES_HOME")
    parser.add_argument("--source", default=str(SOURCE_PLUGIN_DIR), help="Plugin source directory")
    parser.add_argument("--shell-source", default=str(SOURCE_AGENT_OS_SHELL_DIR), help="Agent OS shell plugin source directory")
    parser.add_argument("--no-install-shell", action="store_true", help="Do not copy the memory-os-agent-os shell plugin")
    parser.add_argument("--enable", action="store_true", help="Set memory.provider=memory_os after install")
    parser.add_argument("--enable-shell", action="store_true", help="Add memory-os-agent-os to plugins.enabled")
    parser.add_argument("--install-runtime", action="store_true", help="Write heartbeat wrapper and systemd timer artifacts")
    parser.add_argument("--install-system-modules", action="store_true", help="Install portable L2-L4 module runtime package")
    parser.add_argument("--enable-runtime", action="store_true", help="Install and enable the user systemd heartbeat timer")
    parser.add_argument("--runtime-interval", default="5min", help="Heartbeat timer interval, default: 5min")
    parser.add_argument("--install-cognitive-loop", action="store_true", help="Write test-host cognitive loop wrapper and systemd timer artifacts")
    parser.add_argument("--enable-cognitive-loop", action="store_true", help="Install and enable the user systemd cognitive-loop timer")
    parser.add_argument("--cognitive-loop-interval", default="6h", help="Cognitive-loop timer interval, default: 6h")
    parser.add_argument(
        "--install-owner-review-cron-helper",
        action="store_true",
        help="Copy the Memory-OS owner review render helper and explicit recurring-enable gate into HERMES_HOME/scripts. Does not create or enable a cron job.",
    )
    parser.add_argument(
        "--install-right-brain-expression-cron-helper",
        action="store_true",
        help="Copy the Memory-OS right-brain expression helper and explicit recurring-enable gate into HERMES_HOME/scripts. Does not create or enable a cron job.",
    )
    parser.add_argument(
        "--install-owner-cron-onboarding",
        action="store_true",
        help="Copy the Memory-OS Hermes cron onboarding script into HERMES_HOME/scripts. Does not create cron jobs.",
    )
    parser.add_argument(
        "--run-owner-cron-onboarding",
        action="store_true",
        help="Run Memory-OS cron onboarding after installing helper scripts. Requires --owner-cron-owner-approved for actual cron creation.",
    )
    parser.add_argument(
        "--owner-cron-owner-approved",
        action="store_true",
        help="Explicit owner/operator approval for owner cron onboarding to create or update Hermes cron jobs.",
    )
    parser.add_argument("--hermes-bin", default="hermes", help="Hermes command used for cron onboarding")
    parser.add_argument("--owner-review-deliver", default="auto", help="Owner-review deliver target; auto discovers the owner home channel")
    parser.add_argument("--right-brain-deliver", default="origin", help="Right-brain expression deliver target, default: origin")
    parser.add_argument("--owner-review-owner", default="owner", help="Owner id used by the owner review helper")
    parser.add_argument("--owner-review-channel", default="owner_review_cron", help="Channel label used for owner review active digest binding")
    parser.add_argument("--owner-review-schedule", default="0 9 * * *", help="Owner review cron schedule")
    parser.add_argument(
        "--owner-cron-profile",
        choices=("active-closure", "full"),
        default="active-closure",
        help=(
            "Memory-OS cron onboarding profile. active-closure creates only owner digest "
            "and proposal follow-up jobs; full also creates optional feedback/right-brain/report jobs."
        ),
    )
    parser.add_argument("--right-brain-schedule", default="30 4 * * 0", help="Right-brain expression cron schedule")
    parser.add_argument("--module-cadence-schedule", default="15 */6 * * *", help="Module cadence report cron schedule")
    parser.add_argument("--right-brain-outcome-schedule", default="45 4 * * 0", help="Right-brain outcome capture cron schedule")
    parser.add_argument("--proposal-followups-schedule", default="*/30 * * * *", help="Proposal follow-up OpsGate cron schedule")
    parser.add_argument("--expression-feedback-schedule", default="0 5 * * 0", help="Right-brain expression feedback cron schedule")
    parser.add_argument("--memory-sources-feedback-schedule", default="30 10 * * *", help="MemorySources feedback cron schedule")
    parser.add_argument(
        "--deep-reflection-preset",
        choices=sorted(DEEP_REFLECTION_PRESETS),
        help=(
            "Write a DeepReflection config preset. Default is no config write; "
            "use production-safe for explicit off, observe for dry-run, "
            "auto-bounded for injection only, or test-host for no-send test observation."
        ),
    )
    parser.add_argument(
        "--memory-sources-preset",
        choices=sorted(MEMORY_SOURCES_PRESETS),
        help=(
            "Write Memory Sources Attribution config. Default is no config write; "
            "use production-safe for explicit off or test-host for metadata-only observation."
        ),
    )
    parser.add_argument(
        "--llm-judge-preset",
        choices=sorted(LLM_JUDGE_PRESETS),
        default="active",
        help=(
            "Write Low-Clue Recall LLM judge config. Default active reuses Hermes provider/model "
            "for bounded_vote; use none for deterministic-only or report-only for report-only probes."
        ),
    )
    parser.add_argument(
        "--hindsight",
        choices=["auto", "off", "adopt", "active", "wizard"],
        default="auto",
        help=(
            "Hindsight adoption mode. auto adopts new configs into shadow mode and preserves an already-active "
            "Memory-OS adoption; active adopts an existing provider bank with retain/recall/reflect enabled."
        ),
    )
    parser.add_argument("--dry-run", action="store_true", help="Report actions without copying or enabling")
    args = parser.parse_args()

    report = install_plugin(
        hermes_home=Path(args.hermes_home),
        source=Path(args.source),
        shell_source=Path(args.shell_source),
        install_shell=not args.no_install_shell,
        enable=args.enable,
        enable_shell=args.enable_shell,
        install_runtime=args.install_runtime,
        install_system_modules=args.install_system_modules,
        enable_runtime=args.enable_runtime,
        runtime_interval=args.runtime_interval,
        install_cognitive_loop=args.install_cognitive_loop,
        enable_cognitive_loop=args.enable_cognitive_loop,
        cognitive_loop_interval=args.cognitive_loop_interval,
        install_owner_review_cron_helper=args.install_owner_review_cron_helper,
        install_right_brain_expression_cron_helper=args.install_right_brain_expression_cron_helper,
        install_owner_cron_onboarding=args.install_owner_cron_onboarding,
        run_owner_cron_onboarding=args.run_owner_cron_onboarding,
        owner_cron_owner_approved=args.owner_cron_owner_approved,
        owner_review_deliver=args.owner_review_deliver,
        right_brain_deliver=args.right_brain_deliver,
        owner_review_owner=args.owner_review_owner,
        owner_review_channel=args.owner_review_channel,
        owner_review_schedule=args.owner_review_schedule,
        owner_cron_profile=args.owner_cron_profile,
        right_brain_schedule=args.right_brain_schedule,
        module_cadence_schedule=args.module_cadence_schedule,
        right_brain_outcome_schedule=args.right_brain_outcome_schedule,
        proposal_followups_schedule=args.proposal_followups_schedule,
        expression_feedback_schedule=args.expression_feedback_schedule,
        memory_sources_feedback_schedule=args.memory_sources_feedback_schedule,
        hermes_bin=args.hermes_bin,
        deep_reflection_preset=args.deep_reflection_preset,
        memory_sources_preset=args.memory_sources_preset,
        llm_judge_preset=args.llm_judge_preset,
        hindsight_mode=args.hindsight,
        dry_run=args.dry_run,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
