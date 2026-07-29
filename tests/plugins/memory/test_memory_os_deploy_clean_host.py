"""Tests for clean-host deployment."""

import sys

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
        package = src / "plugins" / "memory" / "memory_os"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("")
        report = preflight_check(src, tmp_path / "tgt")
        assert report.status == "ok"

    def test_preflight_is_read_only_and_rejects_non_package_source(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        target = tmp_path / "tgt"

        report = preflight_check(src, target)

        assert report.status == "fail"
        assert target.exists() is False


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

    def test_atomic_apply_does_not_preserve_stale_target_files(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        (src / "plugins").mkdir(parents=True)
        (src / "plugins" / "current.py").write_text("current")
        tgt = tmp_path / "tgt"
        tgt.mkdir()
        (tgt / "stale.py").write_text("stale")

        report = apply_deploy(src, tgt)

        assert report.status == "ok"
        assert (tgt / "plugins" / "current.py").exists()
        assert not (tgt / "stale.py").exists()


class TestFullPipeline:
    def test_pipeline(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        (src / "plugins" / "memory" / "memory_os").mkdir(parents=True)
        (src / "plugins" / "memory" / "memory_os" / "__init__.py").write_text("")
        tgt = tmp_path / "tgt"
        result = run_deploy_pipeline(src, tgt, python_executable=sys.executable)
        assert result["status"] == "ok"

    def test_pipeline_never_imports_ambient_repo_instead_of_target(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        package = src / "plugins" / "memory" / "memory_os"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("raise RuntimeError('target package imported')\n")

        result = run_deploy_pipeline(src, tmp_path / "tgt", python_executable=sys.executable)

        assert result["status"] != "ok"
        assert result["preflight"]["status"] == "fail"

    def test_postcheck_detects_target_hash_drift(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        package = src / "plugins" / "memory" / "memory_os"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("")
        tgt = tmp_path / "tgt"
        plan = plan_deployment(src, tgt)
        assert apply_deploy(src, tgt, plan=plan).status == "ok"
        (tgt / "plugins" / "memory" / "memory_os" / "__init__.py").write_text("# drift\n")

        report = postcheck_deploy(
            tgt,
            python_executable=sys.executable,
            source_root=src,
            plan=plan,
        )

        assert report.status == "fail"
        assert report.hash_mismatches == ["plugins/memory/memory_os/__init__.py"]