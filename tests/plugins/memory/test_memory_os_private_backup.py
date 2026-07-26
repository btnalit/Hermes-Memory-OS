"""Tests for private asset backup policy."""

import pytest
from pathlib import Path
from plugins.memory.memory_os.private_backup import (
    generate_backup_plan, backup_private_assets, AssetPolicy, PRIVATE_ASSET_POLICIES
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
        assert len(plan.must_backup) == 1  # config.json
        assert len(plan.rebuildable) == 1  # doc.md
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