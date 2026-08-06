"""
Memory-OS clean-host deployment plan/preflight/dry-run/apply/postcheck.

For clean-host / full installer qualification only.  Not used on
production hosts with existing Hermes configuration.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CLEAN_HOST_DEPLOY_SCHEMA_VERSION = "memory-os.clean_host_deploy.v1"
EXCLUDED_SOURCE_PARTS = frozenset({".git", ".pytest_cache", ".venv", "__pycache__", "build", "dist"})


@dataclass
class DeployPlan:
    """A deployment plan for a clean host."""

    source_root: str = ""
    target_root: str = ""
    files_to_copy: list[str] = field(default_factory=list)
    files_to_skip: list[str] = field(default_factory=list)
    total_bytes: int = 0
    file_count: int = 0
    requires_gateway_reload: bool = False
    requires_dashboard_restart: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CLEAN_HOST_DEPLOY_SCHEMA_VERSION,
            "source_root": self.source_root,
            "target_root": self.target_root,
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
            "requires_gateway_reload": self.requires_gateway_reload,
            "requires_dashboard_restart": self.requires_dashboard_restart,
        }


@dataclass
class DeployReport:
    """Result of a deployment run."""

    status: str = "ok"
    phase: str = ""
    files_copied: int = 0
    files_skipped: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    hash_mismatches: list[str] = field(default_factory=list)
    completed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CLEAN_HOST_DEPLOY_SCHEMA_VERSION,
            "status": self.status,
            "phase": self.phase,
            "files_copied": self.files_copied,
            "files_skipped": self.files_skipped,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "hash_mismatch_count": len(self.hash_mismatches),
        }


def plan_deployment(
    source_root: Path,
    target_root: Path,
    *,
    gateway_reload: bool = False,
    dashboard_restart: bool = False,
) -> DeployPlan:
    """Plan a deployment from source to target.

    Identifies files to copy, skipping __pycache__ and .pyc files.
    """
    plan = DeployPlan(
        source_root=str(source_root),
        target_root=str(target_root),
        requires_gateway_reload=gateway_reload,
        requires_dashboard_restart=dashboard_restart,
    )

    for directory, dirnames, filenames in os.walk(source_root, followlinks=False):
        base = Path(directory)
        retained_dirs: list[str] = []
        for dirname in dirnames:
            child = base / dirname
            relative = child.relative_to(source_root)
            if dirname in EXCLUDED_SOURCE_PARTS or child.is_symlink():
                plan.files_to_skip.append(relative.as_posix() + "/")
            else:
                retained_dirs.append(dirname)
        dirnames[:] = retained_dirs
        for filename in filenames:
            f = base / filename
            relative = f.relative_to(source_root)
            if f.is_symlink() or f.suffix == ".pyc":
                plan.files_to_skip.append(relative.as_posix())
                continue
            plan.files_to_copy.append(relative.as_posix())
            plan.total_bytes += f.stat().st_size
            plan.file_count += 1

    return plan


def preflight_check(
    source_root: Path,
    target_root: Path,
    *,
    python_executable: str = sys.executable,
) -> DeployReport:
    """Validate source and target prerequisites without mutating either tree."""
    report = DeployReport(phase="preflight", completed_at=datetime.now(timezone.utc).isoformat())

    if not source_root.exists():
        report.status = "fail"
        report.errors.append(f"source root not found: {source_root}")
        return report
    package = source_root / "plugins" / "memory" / "memory_os" / "__init__.py"
    if not package.is_file():
        report.status = "fail"
        report.errors.append("source root does not contain plugins/memory/memory_os/__init__.py")
        return report
    if target_root.is_symlink():
        report.status = "fail"
        report.errors.append("target root must not be a symlink")
        return report
    source_resolved = source_root.resolve()
    target_resolved = target_root.resolve()
    try:
        target_resolved.relative_to(source_resolved)
    except ValueError:
        pass
    else:
        report.status = "fail"
        report.errors.append("target root must not be inside source root")
        return report

    writable_parent = target_root
    while not writable_parent.exists() and writable_parent != writable_parent.parent:
        writable_parent = writable_parent.parent
    if not writable_parent.is_dir() or not os.access(writable_parent, os.W_OK | os.X_OK):
        report.status = "fail"
        report.errors.append(f"target parent not writable: {writable_parent}")
        return report

    result = _import_probe(source_root, python_executable=python_executable)
    if result.returncode != 0:
        report.status = "fail"
        report.errors.append(f"source import check failed: {result.stderr.strip()[-300:]}")

    return report


def dry_run_deploy(
    source_root: Path,
    target_root: Path,
) -> DeployReport:
    """Simulate a deployment without copying files."""
    report = DeployReport(phase="dry_run", completed_at=datetime.now(timezone.utc).isoformat())
    plan = plan_deployment(source_root, target_root)
    report.files_copied = plan.file_count
    report.files_skipped = len(plan.files_to_skip)
    return report


def apply_deploy(
    source_root: Path,
    target_root: Path,
    *,
    plan: DeployPlan | None = None,
) -> DeployReport:
    """Stage, hash-verify, and atomically publish a deployment tree."""
    report = DeployReport(phase="apply", completed_at=datetime.now(timezone.utc).isoformat())
    if plan is None:
        plan = plan_deployment(source_root, target_root)
    if target_root.is_symlink():
        report.status = "fail"
        report.errors.append("target root must not be a symlink")
        return report

    source_root = source_root.resolve()
    target_root = target_root.resolve()
    target_root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target_root.name}.staging-", dir=target_root.parent))
    backup_root = Path(tempfile.mkdtemp(prefix=f".{target_root.name}.rollback-", dir=target_root.parent))
    backup = backup_root / target_root.name
    published = False
    try:
        for rel_path in plan.files_to_copy:
            relative = Path(rel_path)
            if relative.is_absolute() or ".." in relative.parts:
                report.errors.append(f"unsafe deployment path: {rel_path}")
                continue
            source = (source_root / relative).resolve()
            try:
                source.relative_to(source_root)
            except ValueError:
                report.errors.append(f"source escapes deployment root: {rel_path}")
                continue
            target = staging / relative
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
                target_hash = hashlib.sha256(target.read_bytes()).hexdigest()
                if source_hash != target_hash:
                    report.hash_mismatches.append(rel_path)
                report.files_copied += 1
            except OSError as exc:
                report.errors.append(f"failed to stage {rel_path}: {exc}")
        if report.errors or report.hash_mismatches:
            report.status = "fail"
            return report
        if target_root.exists():
            os.replace(target_root, backup)
        try:
            os.replace(staging, target_root)
            published = True
        except OSError:
            if backup.exists() and not target_root.exists():
                os.replace(backup, target_root)
            raise
        if backup.exists():
            shutil.rmtree(backup)
        report.status = "ok"
    except OSError as exc:
        report.errors.append(f"atomic publish failed: {exc}")
        report.status = "fail"
    finally:
        if not published and staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(backup_root, ignore_errors=True)
    return report


def postcheck_deploy(
    target_root: Path,
    *,
    python_executable: str = sys.executable,
    source_root: Path | None = None,
    plan: DeployPlan | None = None,
) -> DeployReport:
    """Verify that a fresh neutral process imports from the target tree."""
    report = DeployReport(phase="postcheck", completed_at=datetime.now(timezone.utc).isoformat())
    if target_root.is_symlink():
        report.status = "fail"
        report.errors.append("target root must not be a symlink")
        return report
    result = _import_probe(target_root, python_executable=python_executable)
    if result.returncode != 0 or "import-ok" not in result.stdout:
        report.errors.append(f"target import verification failed: {result.stderr.strip()[-300:]}")
    if source_root is not None and plan is not None:
        source_root = source_root.resolve()
        target_root = target_root.resolve()
        expected = set(plan.files_to_copy)
        actual = _deployed_file_paths(target_root)
        for rel_path in sorted(expected - actual):
            report.errors.append(f"target missing deployed file: {rel_path}")
        for rel_path in sorted(actual - expected):
            report.errors.append(f"target contains stale file: {rel_path}")
        for rel_path in sorted(expected & actual):
            try:
                source_digest = hashlib.sha256((source_root / rel_path).read_bytes()).hexdigest()
                target_digest = hashlib.sha256((target_root / rel_path).read_bytes()).hexdigest()
            except OSError as exc:
                report.errors.append(f"target hash read failed: {rel_path}: {exc}")
                continue
            if source_digest != target_digest:
                report.hash_mismatches.append(rel_path)
    report.status = "fail" if report.errors or report.hash_mismatches else "ok"
    return report


def _deployed_file_paths(root: Path) -> set[str]:
    paths: set[str] = set()
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        base = Path(directory)
        retained_dirs: list[str] = []
        for name in dirnames:
            child = base / name
            if name in EXCLUDED_SOURCE_PARTS:
                continue
            if child.is_symlink():
                paths.add(child.relative_to(root).as_posix() + "/")
                continue
            retained_dirs.append(name)
        dirnames[:] = retained_dirs
        for filename in filenames:
            path = base / filename
            if path.is_symlink():
                paths.add(path.relative_to(root).as_posix())
                continue
            if path.suffix == ".pyc":
                continue
            paths.add(path.relative_to(root).as_posix())
    return paths


def _import_probe(root: Path, *, python_executable: str) -> subprocess.CompletedProcess[str]:
    resolved = root.expanduser().resolve()
    code = (
        "import importlib, pathlib, sys; "
        f"root=pathlib.Path({str(resolved)!r}).resolve(); "
        "sys.path[:]=[str(root)]+[p for p in sys.path if p and pathlib.Path(p).resolve()!=root]; "
        "m=importlib.import_module('plugins.memory.memory_os'); "
        "origin=pathlib.Path(m.__file__).resolve(); origin.relative_to(root); print('import-ok')"
    )
    env = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "HERMES_HOME"}}
    try:
        return subprocess.run(
            [python_executable, "-I", "-c", code],
            cwd="/",
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            args=[python_executable, "-I", "-c", code],
            returncode=124,
            stdout="",
            stderr="import probe timed out after 60s",
        )


def run_deploy_pipeline(
    source_root: Path,
    target_root: Path,
    *,
    python_executable: str = sys.executable,
    gateway_reload: bool = False,
    dashboard_restart: bool = False,
) -> dict[str, Any]:
    """Run the full deploy pipeline: plan → preflight → dry-run → apply → postcheck."""
    plan = plan_deployment(source_root, target_root, gateway_reload=gateway_reload, dashboard_restart=dashboard_restart)
    preflight = preflight_check(source_root, target_root, python_executable=python_executable)
    if preflight.status == "fail":
        return {"status": "preflight_failed", "plan": plan.to_dict(), "preflight": preflight.to_dict()}

    dry_run_result = dry_run_deploy(source_root, target_root)
    target_root.parent.mkdir(parents=True, exist_ok=True)
    rollback_root = Path(tempfile.mkdtemp(prefix=f".{target_root.name}.pipeline-", dir=target_root.parent))
    target_existed = target_root.exists()
    rollback_copy = rollback_root / "target"
    if target_existed:
        shutil.copytree(target_root, rollback_copy)
    try:
        apply_result = apply_deploy(source_root, target_root, plan=plan)
        postcheck = (
            postcheck_deploy(
                target_root,
                python_executable=python_executable,
                source_root=source_root,
                plan=plan,
            )
            if apply_result.status == "ok"
            else DeployReport(status="fail", phase="postcheck", errors=["apply failed; postcheck not run"])
        )
        if apply_result.status == "ok" and postcheck.status != "ok":
            if target_root.exists():
                shutil.rmtree(target_root)
            if target_existed:
                shutil.copytree(rollback_copy, target_root)
    finally:
        shutil.rmtree(rollback_root, ignore_errors=True)

    return {
        "schema_version": CLEAN_HOST_DEPLOY_SCHEMA_VERSION,
        "status": "ok" if apply_result.status == "ok" and postcheck.status == "ok" else "fail",
        "plan": plan.to_dict(),
        "preflight": preflight.to_dict(),
        "dry_run": dry_run_result.to_dict(),
        "apply": apply_result.to_dict(),
        "postcheck": postcheck.to_dict(),
    }