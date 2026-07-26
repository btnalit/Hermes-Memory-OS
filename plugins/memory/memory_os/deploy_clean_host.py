"""
Memory-OS clean-host deployment plan/preflight/dry-run/apply/postcheck.

For clean-host / full installer qualification only.  Not used on
production hosts with existing Hermes configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CLEAN_HOST_DEPLOY_SCHEMA_VERSION = "memory-os.clean_host_deploy.v1"


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

    for f in source_root.rglob("*"):
        if f.is_file() and "__pycache__" not in f.parts and not f.suffix == ".pyc":
            plan.files_to_copy.append(str(f.relative_to(source_root)))
            plan.total_bytes += f.stat().st_size
            plan.file_count += 1

    return plan


def preflight_check(
    source_root: Path,
    target_root: Path,
    *,
    python_executable: str = "python3",
) -> DeployReport:
    """Run preflight checks before deployment.

    Verifies source exists, target is writable, Python is available,
    and imports resolve.
    """
    report = DeployReport(phase="preflight", completed_at=datetime.now(timezone.utc).isoformat())

    if not source_root.exists():
        report.status = "fail"
        report.errors.append(f"source root not found: {source_root}")
        return report

    try:
        target_root.mkdir(parents=True, exist_ok=True)
        test_file = target_root / ".preflight_test"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink()
    except OSError as exc:
        report.status = "fail"
        report.errors.append(f"target root not writable: {exc}")
        return report

    import subprocess
    result = subprocess.run(
        [python_executable, "-c", "import plugins.memory.memory_os"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        report.warnings.append(f"import check failed: {result.stderr.strip()[:100]}")

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
    """Apply a deployment: copy files and verify hashes."""
    report = DeployReport(phase="apply", completed_at=datetime.now(timezone.utc).isoformat())

    if plan is None:
        plan = plan_deployment(source_root, target_root)

    import hashlib
    import shutil

    for rel_path in plan.files_to_copy:
        source = source_root / rel_path
        target = target_root / rel_path
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            # Verify hash
            source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            target_hash = hashlib.sha256(target.read_bytes()).hexdigest()
            if source_hash != target_hash:
                report.hash_mismatches.append(rel_path)
            report.files_copied += 1
        except OSError as exc:
            report.errors.append(f"failed to copy {rel_path}: {exc}")

    report.status = "ok" if not report.errors else "fail"
    return report


def postcheck_deploy(
    target_root: Path,
    *,
    python_executable: str = "python3",
) -> DeployReport:
    """Post-deployment verification."""
    report = DeployReport(phase="postcheck", completed_at=datetime.now(timezone.utc).isoformat())

    import subprocess
    result = subprocess.run(
        [python_executable, "-c", "import plugins.memory.memory_os; print('import-ok')"],
        capture_output=True, text=True,
    )
    if "import-ok" not in result.stdout:
        report.errors.append("import verification failed")
        report.status = "fail"
    else:
        report.status = "ok"

    return report


def run_deploy_pipeline(
    source_root: Path,
    target_root: Path,
    *,
    python_executable: str = "python3",
    gateway_reload: bool = False,
    dashboard_restart: bool = False,
) -> dict[str, Any]:
    """Run the full deploy pipeline: plan → preflight → dry-run → apply → postcheck."""
    plan = plan_deployment(source_root, target_root, gateway_reload=gateway_reload, dashboard_restart=dashboard_restart)
    preflight = preflight_check(source_root, target_root, python_executable=python_executable)
    if preflight.status == "fail":
        return {"status": "preflight_failed", "plan": plan.to_dict(), "preflight": preflight.to_dict()}

    dry_run_result = dry_run_deploy(source_root, target_root)
    apply_result = apply_deploy(source_root, target_root, plan=plan)
    postcheck = postcheck_deploy(target_root, python_executable=python_executable)

    return {
        "schema_version": CLEAN_HOST_DEPLOY_SCHEMA_VERSION,
        "status": "ok" if apply_result.status == "ok" and postcheck.status == "ok" else "fail",
        "plan": plan.to_dict(),
        "preflight": preflight.to_dict(),
        "dry_run": dry_run_result.to_dict(),
        "apply": apply_result.to_dict(),
        "postcheck": postcheck.to_dict(),
    }