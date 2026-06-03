from pathlib import Path

from scripts.memory_os_static_hygiene_check import run_static_hygiene


def test_static_hygiene_reports_repo_native_pass_without_ruff(tmp_path):
    calls = []

    def fake_runner(argv, cwd):
        calls.append((tuple(argv), Path(cwd)))
        return {"exit_code": 0, "stdout": "", "stderr": ""}

    report = run_static_hygiene(tmp_path, runner=fake_runner)

    assert report["schema_version"] == "memory-os.static_hygiene.v0"
    assert report["status"] == "pass"
    assert report["ruff_required"] is False
    assert set(report["checks"]) == {
        "compileall",
        "diff_check",
        "closure_matrix",
        "public_checkout_probe",
        "write_surface_check",
    }
    assert all(item["status"] == "pass" for item in report["checks"].values())
    assert len(calls) == 5


def test_static_hygiene_fails_when_any_repo_native_check_fails(tmp_path):
    def fake_runner(argv, cwd):
        if "git" in argv and "diff" in argv:
            return {"exit_code": 1, "stdout": "", "stderr": "whitespace error"}
        return {"exit_code": 0, "stdout": "", "stderr": ""}

    report = run_static_hygiene(tmp_path, runner=fake_runner)

    assert report["status"] == "fail"
    assert report["checks"]["diff_check"]["status"] == "fail"
