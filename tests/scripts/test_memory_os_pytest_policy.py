from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.memory_os_pytest_policy import (
    evaluate_policy,
    normalize_skip_reason,
)


def test_policy_allows_known_skip_reasons_without_locking_total_passed_count(tmp_path: Path) -> None:
    report = evaluate_policy(
        skips=[
            {
                "nodeid": "tests/plugins/memory/test_memory_os_embedder.py::TestLocalEmbedderEmbed::test_embed_returns_bytes",
                "reason": "Skipped: sentence-transformers not installed",
            },
            {
                "nodeid": "tests/scripts/test_memory_os_closure_matrix_check.py::test_closure_matrix_check_passes_for_current_repo",
                "reason": "internal closure matrix docs are not included in public checkouts",
            },
        ],
        warnings=[],
        repo_root=tmp_path,
    )

    assert report["status"] == "pass"
    assert report["unknown_skip_count"] == 0
    assert "passed_count" not in report
    assert "expected_total_skip_count" not in report


def test_policy_fails_unknown_skip_reason(tmp_path: Path) -> None:
    report = evaluate_policy(
        skips=[{"nodeid": "tests/test_x.py::test_x", "reason": "network unavailable"}],
        warnings=[],
        repo_root=tmp_path,
    )

    assert report["status"] == "fail"
    assert report["unknown_skip_count"] == 1


def test_policy_fails_when_known_skip_class_exceeds_bound(tmp_path: Path) -> None:
    nodeids = [
        "tests/plugins/memory/test_memory_os_embedder.py::TestLocalEmbedderEmbed::test_embed_returns_bytes",
        "tests/plugins/memory/test_memory_os_embedder.py::TestLocalEmbedderEmbed::test_embed_deterministic",
        "tests/plugins/memory/test_memory_os_embedder.py::TestLocalEmbedderEmbed::test_embed_different_texts_different_vectors",
        "tests/plugins/memory/test_memory_os_embedder.py::TestLocalEmbedderEmbed::test_embed_query_returns_ndarray",
        "tests/plugins/memory/test_memory_os_embedder.py::TestLocalEmbedderEmbed::test_embed_returns_bytes",
    ]
    report = evaluate_policy(
        skips=[
            {
                "nodeid": nodeid,
                "reason": "sentence-transformers not installed",
            }
            for nodeid in nodeids
        ],
        warnings=[],
        repo_root=tmp_path,
    )

    assert report["status"] == "fail"
    assert report["skip_allowlist_overflow_count"] == 1


def test_policy_fails_project_owned_warning(tmp_path: Path) -> None:
    source = tmp_path / "plugins" / "memory" / "memory_os" / "knob_overrides.py"
    report = evaluate_policy(
        skips=[],
        warnings=[
            {
                "nodeid": "tests/test_knob.py::test_knob",
                "message": "resolve_knob called without roots",
                "category": "RuntimeWarning",
                "filename": str(source),
            }
        ],
        repo_root=tmp_path,
    )

    assert report["status"] == "fail"
    assert report["project_owned_warning_count"] == 1
    assert report["unknown_warning_count"] == 0


def test_policy_allows_bounded_swig_dependency_warnings(tmp_path: Path) -> None:
    report = evaluate_policy(
        skips=[],
        warnings=[
            {
                "nodeid": "tests/test_cli.py::test_status",
                "message": "builtin type SwigPyPacked has no __module__ attribute",
                "category": "DeprecationWarning",
                "filename": "<frozen importlib._bootstrap>",
            },
            {
                "nodeid": "tests/test_cli.py::test_status",
                "message": "builtin type SwigPyObject has no __module__ attribute",
                "category": "DeprecationWarning",
                "filename": "<frozen importlib._bootstrap>",
            },
        ],
        repo_root=tmp_path,
    )

    assert report["status"] == "pass"
    assert report["allowed_dependency_warning_count"] == 2
    assert report["unknown_warning_count"] == 0


def test_policy_rejects_allowlisted_reason_at_collection_stage(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    test_root = tmp_path / "tests" / "plugins" / "memory"
    test_root.mkdir(parents=True)
    test_file = test_root / "test_memory_os_embedder.py"
    report_path = tmp_path / "policy.json"
    test_file.write_text(
        "import pytest\n"
        "pytest.skip('sentence-transformers not installed', allow_module_level=True)\n"
        "def test_hidden_failure(): assert False\n",
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root)
    completed = subprocess.run(
        [
            sys.executable, "-B", "-m", "pytest", "-p", "no:cacheprovider",
            "-p", "scripts.memory_os_pytest_policy",
            "--memory-os-policy-report", str(report_path), str(test_file), "-q",
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert completed.returncode != 0
    assert report["status"] == "fail"
    assert report["unknown_skip_count"] == 1
    assert report["skips"][0]["stage"] == "collect"


def test_policy_rejects_spoofed_runtest_nodeid_with_allowlisted_reason(tmp_path: Path) -> None:
    report = evaluate_policy(
        skips=[{
            "nodeid": "tests/plugins/memory/test_memory_os_embedder.py::TestLocalEmbedderEmbed::test_embed_spoof_hides_failure",
            "reason": "sentence-transformers not installed",
            "stage": "runtest",
        }],
        warnings=[],
        repo_root=tmp_path,
    )

    assert report["status"] == "fail"
    assert report["unknown_skip_count"] == 1


def test_policy_rejects_allowlisted_test_hidden_by_setup_fixture(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    test_root = tmp_path / "tests" / "plugins" / "memory"
    test_root.mkdir(parents=True)
    test_file = test_root / "test_memory_os_embedder.py"
    report_path = tmp_path / "policy.json"
    test_file.write_text(
        "import pytest\n"
        "@pytest.fixture(autouse=True)\n"
        "def hide(): pytest.skip('sentence-transformers not installed')\n"
        "class TestLocalEmbedderEmbed:\n"
        "    def test_embed_returns_bytes(self): assert False\n",
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root)
    completed = subprocess.run(
        [
            sys.executable, "-B", "-m", "pytest", "-p", "no:cacheprovider",
            "-p", "scripts.memory_os_pytest_policy",
            "--memory-os-policy-report", str(report_path), str(test_file), "-q",
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert completed.returncode != 0
    assert report["status"] == "fail"
    assert report["unknown_skip_count"] == 1
    assert report["skips"][0]["stage"] == "setup"


def test_dependency_warning_allowlist_binds_category_and_source(tmp_path: Path) -> None:
    message = "builtin type SwigPyPacked has no __module__ attribute"
    wrong_category = evaluate_policy(
        skips=[],
        warnings=[{
            "nodeid": "tests/test_x.py::test_x",
            "message": message,
            "category": "RuntimeWarning",
            "filename": "<frozen importlib._bootstrap>",
        }],
        repo_root=tmp_path / "repo",
    )
    wrong_source = evaluate_policy(
        skips=[],
        warnings=[{
            "nodeid": "tests/test_x.py::test_x",
            "message": message,
            "category": "DeprecationWarning",
            "filename": str(tmp_path / "rogue_dependency.py"),
        }],
        repo_root=tmp_path / "repo",
    )

    assert wrong_category["status"] == "fail"
    assert wrong_category["unknown_warning_count"] == 1
    assert wrong_source["status"] == "fail"
    assert wrong_source["unknown_warning_count"] == 1


def test_skip_reason_normalization_removes_pytest_prefix() -> None:
    assert normalize_skip_reason("Skipped: optional dependency absent") == "optional dependency absent"


def test_policy_captures_unknown_collection_stage_skip(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    test_file = tmp_path / "test_collection_skip.py"
    report_path = tmp_path / "policy.json"
    test_file.write_text(
        "import pytest\n"
        "pytest.skip('unknown collection skip', allow_module_level=True)\n",
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root)
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "-p",
            "scripts.memory_os_pytest_policy",
            "--memory-os-policy-report",
            str(report_path),
            str(test_file),
            "-q",
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert completed.returncode != 0
    assert report["skip_count"] == 1
    assert report["unknown_skip_count"] == 1
    assert report["skips"][0]["reason"] == "unknown collection skip"
