"""
Private asset backup policy for Memory-OS.

Defines which files in docs/internal-memory-os/ are "must-backup" vs
"rebuildable/discardable".  Provides a backup plan generator and
verification helpers.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PRIVATE_BACKUP_SCHEMA_VERSION = "memory-os.private_backup.v1"
BACKUP_MANIFEST_NAME = ".memory-os-backup-manifest.json"


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
    AssetPolicy(pattern="*.md", category="must_backup", description="Private governance/documentation source"),
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
    manifest_path: str = ""
    manifest_verified: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PRIVATE_BACKUP_SCHEMA_VERSION,
            "status": self.status,
            "files_copied": self.files_copied,
            "error_count": len(self.errors),
            "hash_mismatch_count": len(self.hash_mismatches),
            "target_path": self.target_path,
            "manifest_path": self.manifest_path,
            "manifest_verified": self.manifest_verified,
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
            if Path(rel).match(policy.pattern) or Path(rel).name.endswith(policy.pattern.lstrip("*")):
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

    manifest = build_backup_manifest(private_root, plan=plan)
    for rel_path in plan.must_backup:
        source = private_root / rel_path
        target = target_path / rel_path
        temporary = target.with_name(f".{target.name}.tmp")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, temporary)
            os.replace(temporary, target)
            # Verify hash
            source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            target_hash = hashlib.sha256(target.read_bytes()).hexdigest()
            if source_hash != target_hash:
                result.hash_mismatches.append(rel_path)
            result.files_copied += 1
        except OSError as exc:
            result.errors.append(f"failed to backup {rel_path}: {exc}")
            if temporary.exists():
                temporary.unlink()

    manifest_path = target_path / BACKUP_MANIFEST_NAME
    try:
        target_path.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        result.errors.append(f"manifest_write_failed:{type(exc).__name__}")
        result.status = "fail"
        return result
    result.manifest_path = str(manifest_path)
    verification = verify_backup_manifest(target_path)
    result.manifest_verified = verification["status"] == "ok"
    result.hash_mismatches = list(verification["hash_mismatches"])
    result.errors.extend(str(item) for item in verification["errors"])
    result.status = "ok" if not result.errors and not result.hash_mismatches else "fail"
    return result


def build_backup_manifest(private_root: Path, *, plan: BackupPlan | None = None) -> dict[str, Any]:
    selected = plan or generate_backup_plan(private_root)
    files: dict[str, str] = {}
    for rel_path in sorted(selected.must_backup):
        source = private_root / rel_path
        if source.is_file():
            files[rel_path] = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
    return {
        "schema_version": "memory-os.private_backup_manifest.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files": files,
    }


def verify_backup_manifest(root: Path, manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    errors: list[str] = []
    hash_mismatches: list[str] = []
    if manifest is None:
        manifest_path = root / BACKUP_MANIFEST_NAME
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            return {"status": "fail", "errors": [f"manifest_read_failed:{type(exc).__name__}"], "hash_mismatches": []}
    files = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(files, dict):
        return {"status": "fail", "errors": ["manifest_files_invalid"], "hash_mismatches": []}
    root_resolved = root.resolve()
    for rel_path, expected in sorted(files.items()):
        try:
            target = (root_resolved / str(rel_path)).resolve()
            target.relative_to(root_resolved)
        except (OSError, ValueError):
            errors.append(f"unsafe_path:{rel_path}")
            continue
        if not target.is_file():
            errors.append(f"missing:{rel_path}")
            continue
        observed = "sha256:" + hashlib.sha256(target.read_bytes()).hexdigest()
        if observed != expected:
            hash_mismatches.append(str(rel_path))
    return {
        "status": "ok" if not errors and not hash_mismatches else "fail",
        "errors": errors,
        "hash_mismatches": hash_mismatches,
    }