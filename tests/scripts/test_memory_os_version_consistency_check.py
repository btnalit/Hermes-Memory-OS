import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "memory_os_version_consistency_check.py"
_SPEC = importlib.util.spec_from_file_location("memory_os_version_consistency_check", _SCRIPT)
version_check = importlib.util.module_from_spec(_SPEC)
sys.modules.setdefault("memory_os_version_consistency_check", version_check)
_SPEC.loader.exec_module(version_check)

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_pyproject(tmp_path: Path, version_line: str) -> Path:
    (tmp_path / "pyproject.toml").write_text(
        "\n".join(
            [
                "[project]",
                'name = "hermes-memory-os"',
                version_line,
                "",
            ]
        ),
        encoding="utf-8",
    )
    return tmp_path


def test_repo_pyproject_version_is_readable():
    version = version_check.read_pyproject_version(_REPO_ROOT)
    assert version
    parts = version.split(".")
    assert len(parts) == 3 and all(part.isdigit() for part in parts)


def test_matching_tag_passes(tmp_path):
    root = _write_pyproject(tmp_path, 'version = "0.2.1"')
    assert version_check.main(["--repo-root", str(root), "--tag", "v0.2.1"]) == 0


def test_mismatched_tag_fails(tmp_path):
    # Counterfactual for the v0.2.0-release-vs-0.1.0-pyproject drift: without
    # this gate a tag cut from a stale pyproject sails through silently.
    root = _write_pyproject(tmp_path, 'version = "0.1.0"')
    assert version_check.main(["--repo-root", str(root), "--tag", "v0.2.0"]) == 1


def test_tag_without_v_prefix_fails(tmp_path):
    root = _write_pyproject(tmp_path, 'version = "0.2.1"')
    assert version_check.main(["--repo-root", str(root), "--tag", "0.2.1"]) == 1


def test_missing_version_key_fails(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")
    assert version_check.main(["--repo-root", str(tmp_path), "--tag", "v0.2.1"]) == 1


def test_print_mode_reports_version(tmp_path, capsys):
    root = _write_pyproject(tmp_path, 'version = "1.2.3"')
    assert version_check.main(["--repo-root", str(root), "--print"]) == 0
    assert capsys.readouterr().out.strip() == "1.2.3"


def test_check_tag_message_names_both_sides():
    error = version_check.check_tag("v0.2.0", "0.1.0")
    assert error is not None
    assert "v0.2.0" in error and "0.1.0" in error
