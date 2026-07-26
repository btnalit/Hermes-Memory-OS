"""
Private asset backup policy for Memory-OS.

Defines which files in docs/internal-memory-os/ are "must-backup" vs
"rebuildable/discardable".  Provides a backup plan generator and
verification helpers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PRIVATE_BACKUP_SCHEMA_VERSION = "memory-os.private_backup.v1"


@dataclass
class AssetPolicy:
    """Policy for a single asset type."""

    pattern: str = ""
    category: str = "must_backup"  # must_backup | rebuildable | discardable
    description: str = ""
    estimated_size: str = ""


# Predefined policies for docs/internal-memory-os/
PRIVATE_ASSET_POLICIES: list[AssetPolicy] = [
    AssetPolicy(pattern="*.json", category="must_backup", description="Contract and schema files"),
    AssetPolicy(pattern="*.yaml", category="must_backup", description="Configuration files"),
    AssetPolicy(pattern="*.md", category="rebuildable", description="Documentation (can be regenerated from code)"),
    AssetPolicy(pattern="*.pem", category="must_backup", description="Private keys and certificates"),
    AssetPolicy(pattern="*.env", category="must_backup", description="Environment secrets"),
    AssetPolicy(pattern="__pycache__/*", category="discardable", description="Python bytecode cache"),
    AssetPolicy(pattern="*.pyc", category="discardable", description="Python bytecode"),
    AssetPolicy(pattern="*.log", category="discardable", description="Log files"),
    AssetPolicy(pattern="*.tmp", category="discardable", description="Temporary files"),
]


@dataclass
class BackupPlan:
    """A backup plan for private assets."""

    must_backup: list[str] = field(default_factory=list)
    rebuildable: list[str] = field(default_factory=list)
    discardable: list[str] = field(default_factory=list)
    total_bytes: int = 0
    file_count: int = 0
    generated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PRIVATE_BACKUP_SCHEMA_VERSION,
            "must_backup_count": len(self.must_backup),
            "rebuildable_count": len(self.rebuildable),
            "discardable_count": len(self.discardable),
            "total_bytes": self.total_bytes,
            "file_count": self.file_count,
            "generated_at": self.generated_at,
        }


@dataclass
class BackupResult:
    """Result of a backup operation."""

    status: str = "ok"
    files_copied: int = 0
    errors: list[str] = field(default_factory=list)
    hash_mismatches: list[str] = field(default_factory=list)
    target_path: str = ""
    completed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PRIVATE_BACKUP_SCHEMA_VERSION,
            "status": self.status,
            "files_copied": self.files_copied,
            "error_count": len(self.errors),
            "hash_mismatch_count": len(self.hash_mismatches),
            "target_path": self.target_path,
        }


def generate_backup_plan(
    private_root: Path,
) -> BackupPlan:
    """Generate a backup plan for the private assets directory."""
    plan = BackupPlan(
        generated_at=datetime.now(timezone.utc).isoformat(),
    )

    if not private_root.exists():
        return plan

    for f in private_root.rglob("*"):
        if not f.is_file():
            continue
        rel = str(f.relative_to(private_root))
        plan.file_count += 1
        plan.total_bytes += f.stat().st_size

        # Classify by pattern
        categorized = False
        for policy in PRIVATE_ASSET_POLICIES:
            if any(rel.endswith(policy.pattern.lstrip("*")) for part in [rel]):
                if policy.category == "must_backup":
                    plan.must_backup.append(rel)
                elif policy.category == "rebuildable":
                    plan.rebuildable.append(rel)
                else:
                    plan.discardable.append(rel)
                categorized = True
                break

        if not categorized:
            plan.must_backup.append(rel)  # default: must_backup

    return plan


def backup_private_assets(
    private_root: Path,
    target_path: Path,
    *,
    plan: BackupPlan | None = None,
) -> BackupResult:
    """Backup must_backup assets to a target path."""
    result = BackupResult(
        target_path=str(target_path),
        completed_at=datetime.now(timezone.utc).isoformat(),
    )

    if plan is None:
        plan = generate_backup_plan(private_root)

    import hashlib
    import shutil

    for rel_path in plan.must_backup:
        source = private_root / rel_path
        target = target_path / rel_path
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            # Verify hash
            source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            target_hash = hashlib.sha256(target.read_bytes()).hexdigest()
            if source_hash != target_hash:
                result.hash_mismatches.append(rel_path)
            result.files_copied += 1
        except OSError as exc:
            result.errors.append(f"failed to backup {rel_path}: {exc}")

    result.status = "ok" if not result.errors else "fail"
    return result