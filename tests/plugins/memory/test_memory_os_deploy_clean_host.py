"""Tests for clean-host deployment."""

import pytest
from pathlib import Path
from plugins.memory.memory_os.deploy_clean_host import (
    plan_deployment, preflight_check, dry_run_deploy, apply_deploy, postcheck_deploy, run_deploy_pipeline
)


class TestPlanDeployment:
    def test_plan_empty(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        plan = plan_deployment(src, tmp_path / "tgt")
        assert plan.file_count == 0

    def test_plan_with_files(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        (src / "plugins").mkdir(parents=True)
        (src / "plugins" / "a.py").write_text("x")
        (src / "plugins" / "__pycache__").mkdir()
        (src / "plugins" / "__pycache__" / "a.cpython.pyc").write_text("")
        plan = plan_deployment(src, tmp_path / "tgt")
        assert plan.file_count == 1  # __pycache__ excluded
        assert plan.files_to_copy == ["plugins/a.py"]


class TestPreflightCheck:
    def test_source_missing(self, tmp_path: Path) -> None:
        report = preflight_check(tmp_path / "nonexistent", tmp_path / "tgt")
        assert report.status == "fail"

    def test_target_writable(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        report = preflight_check(src, tmp_path / "tgt")
        assert report.status == "ok"


class TestApplyDeploy:
    def test_copy_files(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        (src / "plugins").mkdir(parents=True)
        (src / "plugins" / "a.py").write_text("test")
        tgt = tmp_path / "tgt"
        report = apply_deploy(src, tgt)
        assert report.files_copied == 1
        assert (tgt / "plugins" / "a.py").exists()
        assert report.hash_mismatches == []


class TestFullPipeline:
    def test_pipeline(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        (src / "plugins" / "memory" / "memory_os").mkdir(parents=True)
        (src / "plugins" / "memory" / "memory_os" / "__init__.py").write_text("")
        tgt = tmp_path / "tgt"
        result = run_deploy_pipeline(src, tgt, python_executable="/usr/bin/python3")
        assert result["status"] == "ok"