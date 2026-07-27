"""
Deploy the community feature to a Hermes profile.

Standardized deployment for the Hermes Community feature.
Automates: directory creation, module deployment, roster init, channel config.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json
import shutil

COMMUNITY_DEPLOY_SCHEMA_VERSION = "memory-os.community.deploy.v1"


@dataclass
class CommunityDeployPlan:
    """Deployment plan for community feature."""

    target_root: str = ""
    memory_os_root: str = ""
    modules_deployed: list[str] = field(default_factory=list)
    dirs_created: list[str] = field(default_factory=list)
    roster_initialized: bool = False
    budget_deployed: bool = False
    requires_gateway_reload: bool = False


@dataclass
class CommunityDeployResult:
    """Result of a community deployment."""

    status: str = "ok"
    phase: str = ""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    completed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": COMMUNITY_DEPLOY_SCHEMA_VERSION,
            "status": self.status,
            "phase": self.phase,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
        }


def deploy_community_module(
    source_module: Path,
    target_plugin_dir: Path,
) -> CommunityDeployResult:
    """Deploy the community.py module to a target plugin directory."""
    result = CommunityDeployResult(phase="module", completed_at=datetime.now(timezone.utc).isoformat())

    if not source_module.exists():
        result.status = "fail"
        result.errors.append(f"source module not found: {source_module}")
        return result

    target = target_plugin_dir / "community.py"
    try:
        target_plugin_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_module, target)
        # Verify import
        import subprocess
        r = subprocess.run(
            ["python3", "-c", f"import sys; sys.path.insert(0, '{target_plugin_dir.parent.parent}'); from plugins.memory.memory_os.community import ROSTER_SCHEMA_VERSION; print(ROSTER_SCHEMA_VERSION)"],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode != 0:
            result.warnings.append(f"import verification: {r.stderr.strip()[:100]}")
    except OSError as exc:
        result.status = "fail"
        result.errors.append(f"deploy failed: {exc}")

    return result


def create_community_directory(
    memory_os_root: Path,
) -> CommunityDeployResult:
    """Create the community directory structure."""
    result = CommunityDeployResult(phase="directory", completed_at=datetime.now(timezone.utc).isoformat())

    dirs = [
        memory_os_root / "community",
        memory_os_root / "community" / "charters",
        memory_os_root / "community" / "shared",
        memory_os_root / "community" / "partners",
    ]
    for d in dirs:
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            result.errors.append(f"failed to create {d}: {exc}")

    if result.errors:
        result.status = "fail"

    return result


def init_roster(
    memory_os_root: Path,
) -> CommunityDeployResult:
    """Initialize an empty roster file."""
    result = CommunityDeployResult(phase="roster", completed_at=datetime.now(timezone.utc).isoformat())

    roster_path = memory_os_root / "community" / "roster.jsonl"
    if not roster_path.exists():
        try:
            roster_path.touch()
        except OSError as exc:
            result.errors.append(f"failed to create roster: {exc}")
            result.status = "fail"

    return result


def deploy_budget(
    memory_os_root: Path,
) -> CommunityDeployResult:
    """Deploy the default budget configuration."""
    result = CommunityDeployResult(phase="budget", completed_at=datetime.now(timezone.utc).isoformat())

    budget_path = memory_os_root / "community" / "budget.yaml"
    budget_content = """global:
  max_active_partners: 1
  weekly_token_budget: 500000
per_partner_default:
  weekly_token_budget: 200000
  max_unsolicited_messages_per_day: 3
enforcement: fail-closed
"""
    try:
        budget_path.write_text(budget_content, encoding="utf-8")
    except OSError as exc:
        result.errors.append(f"failed to write budget: {exc}")
        result.status = "fail"

    return result


def deploy_community(
    memory_os_root: Path,
    plugin_dir: Path,
    *,
    source_module: Path | None = None,
) -> list[CommunityDeployResult]:
    """Run full community deployment pipeline."""
    results: list[CommunityDeployResult] = []

    # 1. Deploy module
    mod_src = source_module or Path(__file__).parent / "community.py"
    results.append(deploy_community_module(mod_src, plugin_dir))

    # 2. Create directories
    results.append(create_community_directory(memory_os_root))

    # 3. Init roster
    results.append(init_roster(memory_os_root))

    # 4. Deploy budget
    results.append(deploy_budget(memory_os_root))

    return results


def get_deploy_summary(results: list[CommunityDeployResult]) -> dict[str, Any]:
    """Get a summary of the deployment results."""
    errors = [e for r in results for e in r.errors]
    warnings = [w for r in results for w in r.warnings]
    return {
        "schema_version": COMMUNITY_DEPLOY_SCHEMA_VERSION,
        "status": "ok" if not errors else "fail",
        "phases": {r.phase: r.status for r in results},
        "total_errors": len(errors),
        "total_warnings": len(warnings),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }