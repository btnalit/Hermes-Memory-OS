import re
import tomllib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_github_ci_runs_mount_isolated_suite_and_governance_gates() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "python-version: '3.11'" in workflow
    assert "fetch-depth: 0" in workflow
    assert "scripts/memory_os_mount_isolated_pytest.py" in workflow
    assert "sudo \"$(command -v python)\"" in workflow
    assert "scripts/memory_os_import_cycle_check.py" in workflow
    assert "scripts/memory_os_write_surface_check.py" in workflow
    assert "scripts/memory_os_static_hygiene_check.py" in workflow
    assert "scripts/memory_os_public_checkout_probe.py --repo-root . --source working-tree --strict" in workflow
    assert "scripts/memory_os_closure_matrix_check.py --repo-root ." in workflow
    assert "uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262" in workflow
    assert "uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065" in workflow
    assert "uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02" in workflow
    assert not re.search(r"uses:\s+[^\s]+@v\d+", workflow)
    assert 'git diff --check "$BASE_SHA...HEAD"' in workflow
    assert 'git diff --check "$BASE_SHA" HEAD' in workflow
    assert "python -m pip wheel --no-deps" in workflow
    assert "wheel-venv" in workflow
    assert "importlib.metadata" in workflow
    assert "upload-artifact" in workflow


def test_dev_install_declares_explicit_package_discovery_and_ci_dependencies() -> None:
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["build-system"]["build-backend"] == "setuptools.build_meta"
    assert project["tool"]["setuptools"]["packages"]["find"]["include"] == [
        "plugins*",
        "memory_os_agent*",
    ]
    dev = {requirement.lower().split(">=")[0] for requirement in project["project"]["optional-dependencies"]["dev"]}
    assert {"pytest", "pyyaml", "numpy"} <= dev
    assert project["tool"]["setuptools"]["package-data"] == {
        "plugins.memory.memory_os": ["plugin.yaml"],
        "plugins.memory-os-agent-os": ["plugin.yaml"],
        "plugins.seam.ragflow_evidence": ["config.json"],
    }
