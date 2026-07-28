"""Tests for private asset backup policy."""

import pytest
from pathlib import Path
from plugins.memory.memory_os.private_backup import (
    generate_backup_plan, backup_private_assets, verify_backup_manifest,
    AssetPolicy, PRIVATE_ASSET_POLICIES
)


class TestAssetPolicies:
    def test_must_backup_patterns(self):
        assert any(p.category == "must_backup" for p in PRIVATE_ASSET_POLICIES)

    def test_discardable_patterns(self):
        assert any(p.category == "discardable" for p in PRIVATE_ASSET_POLICIES)


class TestGenerateBackupPlan:
    def test_empty_dir(self, tmp_path: Path) -> None:
        plan = generate_backup_plan(tmp_path)
        assert plan.file_count == 0

    def test_classify_files(self, tmp_path: Path) -> None:
        (tmp_path / "config.json").write_text("{}")
        (tmp_path / "doc.md").write_text("# doc")
        (tmp_path / "temp.tmp").write_text("")
        plan = generate_backup_plan(tmp_path)
        assert len(plan.must_backup) == 2  # config.json + private doc.md
        assert len(plan.rebuildable) == 0
        assert len(plan.discardable) == 1  # temp.tmp


class TestBackupPrivateAssets:
    def test_backup_must_backup(self, tmp_path: Path) -> None:
        private = tmp_path / "private"
        private.mkdir()
        (private / "secret.json").write_text("secret")
        (private / "notes.md").write_text("notes")
        target = tmp_path / "backup"
        result = backup_private_assets(private, target)
        assert result.files_copied >= 1
        assert (target / "secret.json").exists()
        assert (target / "notes.md").exists()
        assert result.manifest_verified is True
        assert verify_backup_manifest(target)["status"] == "ok"

    def test_independent_restore_verification_detects_corruption(self, tmp_path: Path) -> None:
        private = tmp_path / "private"
        private.mkdir()
        (private / "secret.json").write_text("secret")
        target = tmp_path / "backup"
        result = backup_private_assets(private, target)
        assert result.status == "ok"

        (target / "secret.json").write_text("corrupted")
        verification = verify_backup_manifest(target)

        assert verification["status"] == "fail"
        assert verification["hash_mismatches"] == ["secret.json"]