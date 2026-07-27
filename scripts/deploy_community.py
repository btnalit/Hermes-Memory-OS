#!/usr/bin/env python3
"""Portable, non-destructive deployment for Hermes Community."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

COMMUNITY_DEPLOY_SCHEMA_VERSION = "memory-os.community.deploy.v2"
COMMUNITY_MODULES = [
    "jsonl_io.py",
    "cron_registry.py",
    "legacy_right_brain_retirement.py",
    "community.py",
    "partner_create.py",
    "community_shared.py",
    "community_triggers.py",
    "community_snapshot.py",
    "state_overlay.py",
    "state_overlay_schema.py",
    "state_overlay_renderer.py",
    "cognitive_loop.py",
]
_DEFAULT_BUDGET = """global:
  max_active_partners: 1
  weekly_token_budget: 500000
per_partner_default:
  weekly_token_budget: 200000
  max_unsolicited_messages_per_day: 3
enforcement: fail-closed
"""


@dataclass(frozen=True)
class DeployFile:
    name: str
    source: Path
    targets: tuple[Path, ...]


@dataclass(frozen=True)
class CommunityDeployPlan:
    repo_root: Path
    hermes_home: Path
    memory_os_root: Path
    files: tuple[DeployFile, ...]
    directories: tuple[Path, ...]


@dataclass
class CommunityDeployResult:
    status: str
    phase: str
    file_count: int = 0
    copied: list[str] = field(default_factory=list)
    preserved: list[str] = field(default_factory=list)
    backups: list[str] = field(default_factory=list)
    hash_failures: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    completed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": COMMUNITY_DEPLOY_SCHEMA_VERSION,
            "status": self.status,
            "phase": self.phase,
            "file_count": self.file_count,
            "copied": list(self.copied),
            "preserved": list(self.preserved),
            "backups": list(self.backups),
            "hash_failures": list(self.hash_failures),
            "errors": list(self.errors),
            "completed_at": self.completed_at,
        }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _default_repo_root() -> Path:
    current = Path(__file__).resolve().parent
    for candidate in [current, *current.parents]:
        if (candidate / "pyproject.toml").is_file() and (candidate / "plugins" / "memory" / "memory_os").is_dir():
            return candidate
    raise ValueError("repo root could not be resolved; pass --repo-root")


def build_deploy_plan(*, repo_root: Path, hermes_home: Path) -> CommunityDeployPlan:
    repo = Path(repo_root).expanduser().resolve()
    home = Path(hermes_home).expanduser().resolve()
    plugin_source = repo / "plugins" / "memory" / "memory_os"
    script_source = repo / "scripts" / "deploy_community.py"
    if not (repo / "pyproject.toml").is_file() and not plugin_source.is_dir():
        raise ValueError(f"invalid repo root: {repo}")
    files: list[DeployFile] = []
    flat_plugin = home / "plugins" / "memory_os"
    runtime_plugin = home / "memory-os" / "runtime" / "python" / "plugins" / "memory" / "memory_os"
    for module in COMMUNITY_MODULES:
        source = plugin_source / module
        if not source.is_file():
            raise ValueError(f"community source missing: {source}")
        files.append(DeployFile(module, source, (flat_plugin / module, runtime_plugin / module)))
    shell_source = repo / "plugins" / "memory-os-agent-os" / "__init__.py"
    if not shell_source.is_file():
        raise ValueError(f"community agent-os shell missing: {shell_source}")
    files.append(
        DeployFile(
            "memory-os-agent-os/__init__.py",
            shell_source,
            (home / "plugins" / "memory-os-agent-os" / "__init__.py",),
        )
    )
    if not script_source.is_file():
        raise ValueError(f"community deploy script missing: {script_source}")
    files.append(DeployFile(script_source.name, script_source, (home / "scripts" / script_source.name,)))
    memory_os_root = home / "memory-os"
    community_root = memory_os_root / "community"
    return CommunityDeployPlan(
        repo_root=repo,
        hermes_home=home,
        memory_os_root=memory_os_root,
        files=tuple(files),
        directories=(
            community_root,
            community_root / "charters",
            community_root / "shared",
            community_root / "partners",
            community_root / "system",
        ),
    )


def _verify(plan: CommunityDeployPlan) -> list[str]:
    failures: list[str] = []
    for item in plan.files:
        expected = _sha256(item.source)
        for target in item.targets:
            if not target.is_file() or _sha256(target) != expected:
                failures.append(str(target))
    for directory in plan.directories:
        if not directory.is_dir():
            failures.append(str(directory))
    if not (plan.memory_os_root / "community" / "roster.jsonl").is_file():
        failures.append(str(plan.memory_os_root / "community" / "roster.jsonl"))
    if not (plan.memory_os_root / "community" / "budget.yaml").is_file():
        failures.append(str(plan.memory_os_root / "community" / "budget.yaml"))
    import_failure = _runtime_import_failure(plan)
    if import_failure:
        failures.append(import_failure)
    return failures


def _runtime_import_failure(plan: CommunityDeployPlan) -> str:
    python_root = plan.memory_os_root / "runtime" / "python"
    module_names = [
        f"plugins.memory.memory_os.{Path(name).stem}"
        for name in COMMUNITY_MODULES
    ]
    code = (
        "import importlib,sys;"
        f"sys.path.insert(0,{str(python_root)!r});"
        f"mods={module_names!r};"
        "[importlib.import_module(name) for name in mods]"
    )
    try:
        completed = subprocess.run(
            [sys.executable, "-B", "-c", code],
            cwd="/",
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"runtime import probe: {type(exc).__name__}"
    if completed.returncode == 0:
        return ""
    detail = (completed.stderr or completed.stdout or "runtime import failed").strip().splitlines()[-1]
    return f"runtime import probe: {detail[:300]}"


def _base_install_failures(plan: CommunityDeployPlan) -> list[str]:
    required = (
        plan.hermes_home / "plugins" / "memory_os" / "plugin.yaml",
        plan.memory_os_root / "runtime" / "python" / "plugins" / "memory" / "memory_os" / "store.py",
    )
    return [str(path) for path in required if not path.is_file()]


def _rollback_files(changed: list[tuple[Path, Path | None]], result: CommunityDeployResult) -> None:
    rollback_errors: list[str] = []
    for target, backup in reversed(changed):
        try:
            if backup is None:
                target.unlink(missing_ok=True)
            else:
                shutil.copy2(backup, target)
        except OSError as exc:
            rollback_errors.append(f"rollback {target}: {type(exc).__name__}")
    result.errors.extend(rollback_errors)
    result.errors.append("deployment rolled back" if not rollback_errors else "deployment rollback incomplete")


def deploy_community(
    *,
    repo_root: Path,
    hermes_home: Path,
    dry_run: bool = False,
    postcheck: bool = False,
    force_budget: bool = False,
) -> CommunityDeployResult:
    plan = build_deploy_plan(repo_root=repo_root, hermes_home=hermes_home)
    now = datetime.now(timezone.utc)
    result = CommunityDeployResult(
        status="planned" if dry_run else "checking" if postcheck else "applied",
        phase="dry-run" if dry_run else "postcheck" if postcheck else "apply",
        file_count=len(plan.files),
        completed_at=now.isoformat(),
    )
    if dry_run:
        return result
    base_failures = _base_install_failures(plan)
    if base_failures:
        result.status = "fail"
        result.errors.extend(f"Memory-OS prerequisite missing: {path}" for path in base_failures)
        return result
    if postcheck:
        result.hash_failures = _verify(plan)
        result.status = "pass" if not result.hash_failures else "fail"
        return result

    backup_root = plan.hermes_home / "backups" / f"community-deploy-{now.strftime('%Y%m%dT%H%M%SZ')}"
    changed: list[tuple[Path, Path | None]] = []
    for item in plan.files:
        for target in item.targets:
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists() and _sha256(target) == _sha256(item.source):
                    result.preserved.append(str(target))
                    continue
                backup: Path | None = None
                if target.exists():
                    backup = backup_root / target.relative_to(plan.hermes_home)
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target, backup)
                    result.backups.append(str(backup))
                changed.append((target, backup))
                shutil.copy2(item.source, target)
                result.copied.append(str(target))
            except OSError as exc:
                result.errors.append(f"{target}: {type(exc).__name__}")
                _rollback_files(changed, result)
                result.status = "fail"
                return result

    file_hash_failures = [
        str(target)
        for item in plan.files
        for target in item.targets
        if not target.is_file() or _sha256(target) != _sha256(item.source)
    ]
    if file_hash_failures:
        result.hash_failures.extend(file_hash_failures)
        _rollback_files(changed, result)
        result.status = "fail"
        return result

    import_failure = _runtime_import_failure(plan)
    if import_failure:
        result.hash_failures.append(import_failure)
        _rollback_files(changed, result)
        result.status = "fail"
        return result

    created_directories: list[Path] = []
    for directory in plan.directories:
        try:
            existed = directory.exists()
            directory.mkdir(parents=True, exist_ok=True)
            if not existed:
                created_directories.append(directory)
        except OSError as exc:
            result.errors.append(f"{directory}: {type(exc).__name__}")

    roster = plan.memory_os_root / "community" / "roster.jsonl"
    budget = plan.memory_os_root / "community" / "budget.yaml"
    roster_existed = roster.exists()
    budget_existed = budget.exists()
    try:
        roster.touch(exist_ok=True)
        if budget.exists() and not force_budget:
            result.preserved.append(str(budget))
        else:
            budget_backup: Path | None = None
            if budget.exists():
                budget_backup = backup_root / budget.relative_to(plan.hermes_home)
                budget_backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(budget, budget_backup)
                result.backups.append(str(budget_backup))
            changed.append((budget, budget_backup))
            budget.write_text(_DEFAULT_BUDGET, encoding="utf-8")
    except OSError as exc:
        result.errors.append(f"community layout: {type(exc).__name__}")

    result.hash_failures = _verify(plan)
    if result.errors or result.hash_failures:
        if not roster_existed:
            roster.unlink(missing_ok=True)
        if not budget_existed:
            budget.unlink(missing_ok=True)
        for directory in reversed(created_directories):
            try:
                directory.rmdir()
            except OSError:
                pass
        _rollback_files(changed, result)
        result.status = "fail"
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--hermes-home", type=Path, required=True)
    parser.add_argument("--phase", choices=("dry-run", "apply", "postcheck"), default="dry-run")
    parser.add_argument("--force-budget", action="store_true")
    parser.add_argument("--output", choices=("json", "summary"), default="summary")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        repo_root = args.repo_root or _default_repo_root()
        result = deploy_community(
            repo_root=repo_root,
            hermes_home=args.hermes_home,
            dry_run=args.phase == "dry-run",
            postcheck=args.phase == "postcheck",
            force_budget=bool(args.force_budget),
        )
    except (OSError, ValueError) as exc:
        result = CommunityDeployResult(
            status="fail",
            phase=str(args.phase),
            errors=[str(exc)],
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
    payload = result.to_dict()
    if args.output == "json":
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"community deploy {result.phase}: {result.status}; files={result.file_count}; errors={len(result.errors)}; hash_failures={len(result.hash_failures)}")
    return 0 if result.status in {"planned", "applied", "pass"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
