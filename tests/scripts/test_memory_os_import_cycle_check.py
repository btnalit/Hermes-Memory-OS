from pathlib import Path

from scripts.memory_os_import_cycle_check import run_import_cycle_check


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_import_cycle_check_detects_synthetic_cycle(tmp_path):
    package = tmp_path / "pkg"
    package.mkdir()
    package.joinpath("__init__.py").write_text("", encoding="utf-8")
    package.joinpath("a.py").write_text("from pkg import b\n", encoding="utf-8")
    package.joinpath("b.py").write_text("from pkg import a\n", encoding="utf-8")

    report = run_import_cycle_check(tmp_path, scan_roots=["pkg"])

    assert report["status"] == "fail"
    assert report["cycle_count"] == 1
    assert report["cycles"][0]["modules"] == ["pkg.a", "pkg.b"]


def test_memory_os_core_import_cycle_check_passes_current_repo():
    report = run_import_cycle_check(REPO_ROOT)

    assert report["status"] == "pass"
    assert report["cycle_count"] == 0
