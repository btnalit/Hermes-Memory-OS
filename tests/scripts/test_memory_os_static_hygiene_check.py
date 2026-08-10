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
        "memory_os_provider_agnostic",
        "memory_os_host_boundary",
    }
    assert all(item["status"] == "pass" for item in report["checks"].values())
    assert len(calls) == 5
    compile_argv = next(argv for argv, _cwd in calls if "compileall" in argv)
    assert "-X" in compile_argv
    assert any(part.startswith("pycache_prefix=") for part in compile_argv)
    probe_argv = next(
        argv
        for argv, _cwd in calls
        if any("memory_os_public_checkout_probe.py" in part for part in argv)
    )
    assert "--strict" in probe_argv
    assert "working-tree" in probe_argv


def test_static_hygiene_fails_when_any_repo_native_check_fails(tmp_path):
    def fake_runner(argv, cwd):
        if "git" in argv and "diff" in argv:
            return {"exit_code": 1, "stdout": "", "stderr": "whitespace error"}
        return {"exit_code": 0, "stdout": "", "stderr": ""}

    report = run_static_hygiene(tmp_path, runner=fake_runner)

    assert report["status"] == "fail"
    assert report["checks"]["diff_check"]["status"] == "fail"


def test_static_hygiene_compile_failure_is_release_fatal(tmp_path):
    def fake_runner(argv, cwd):
        if "compileall" in argv:
            return {"exit_code": 1, "stdout": "", "stderr": "SyntaxError"}
        return {"exit_code": 0, "stdout": "", "stderr": ""}

    report = run_static_hygiene(tmp_path, runner=fake_runner)

    assert report["status"] == "fail"
    assert report["checks"]["compileall"]["status"] == "fail"


# ── N2: host-boundary static guard (memory_os must not import transport /
# channel-resolution / scheduling from the Hermes host or onboarding seam) ──


def test_boundary_scan_flags_owner_cron_onboarding_import():
    from scripts.memory_os_static_hygiene_check import scan_source_boundary_violations

    src = "from scripts.memory_os_owner_cron_onboarding import discover_owner_channels\n"
    violations = scan_source_boundary_violations("plugins/memory/memory_os/x.py", src)
    kinds = {v["kind"] for v in violations}
    assert violations, "must flag host-boundary import"
    assert {"forbidden_import_module", "forbidden_import_name"} & kinds


def test_boundary_scan_flags_plain_import_of_onboarding():
    from scripts.memory_os_static_hygiene_check import scan_source_boundary_violations

    src = "import scripts.memory_os_owner_cron_onboarding as onboarding\n"
    violations = scan_source_boundary_violations("plugins/memory/memory_os/x.py", src)
    assert any(v["kind"] == "forbidden_import_module" for v in violations)


def test_boundary_scan_flags_channel_directory_literal():
    from scripts.memory_os_static_hygiene_check import scan_source_boundary_violations

    src = "path = home / 'channel_directory.json'\n"
    violations = scan_source_boundary_violations("plugins/memory/memory_os/x.py", src)
    assert any(v["kind"] == "forbidden_path_literal" for v in violations)


def test_boundary_scan_flags_core_import_of_hermes_host_adapter():
    from scripts.memory_os_static_hygiene_check import scan_source_boundary_violations

    src = "from plugins.seam.hermes_memory_os.owner_channel_adapter import resolve_owner_review_channel\n"
    violations = scan_source_boundary_violations("plugins/memory/memory_os/x.py", src)

    assert any(v["kind"] == "forbidden_import_module" for v in violations)


def test_boundary_scan_allows_internal_delivery_helpers():
    from scripts.memory_os_static_hygiene_check import scan_source_boundary_violations

    # Internal "delivery" seam functions and relative imports are NOT violations.
    src = (
        "from .permanent_promotion import prepare_permanent_promotion_delivery\n"
        "def build(): return owner_review_deliveries_path()\n"
    )
    violations = scan_source_boundary_violations("plugins/memory/memory_os/x.py", src)
    assert violations == []


def test_boundary_scan_flags_hermes_send_subprocess_semantics():
    from scripts.memory_os_static_hygiene_check import scan_source_boundary_violations

    src = "import subprocess\nsubprocess.run(['hermes', 'send', '--to', target, message])\n"
    violations = scan_source_boundary_violations("plugins/memory/memory_os/x.py", src)

    assert any(v["kind"] == "forbidden_host_invocation" and v["detail"] == "hermes send" for v in violations)


def test_boundary_scan_flags_hermes_cron_and_version_semantics_without_banning_subprocess_import():
    from scripts.memory_os_static_hygiene_check import scan_source_boundary_violations

    safe = scan_source_boundary_violations(
        "plugins/memory/memory_os/x.py",
        "import subprocess\nsubprocess.run(['git', 'status'])\n",
    )
    cron = scan_source_boundary_violations(
        "plugins/memory/memory_os/x.py",
        "import subprocess\nsubprocess.run([hermes_bin, 'cron', 'create', '--help'])\n",
    )
    version = scan_source_boundary_violations(
        "plugins/memory/memory_os/x.py",
        "import subprocess\nsubprocess.run([hermes_bin, '--version'])\n",
    )

    assert safe == []
    assert any(v["detail"] == "hermes cron" for v in cron)
    assert any(v["detail"] == "hermes --version" for v in version)


def test_boundary_scan_flags_channel_resolution_ownership_symbols():
    from scripts.memory_os_static_hygiene_check import scan_source_boundary_violations

    src = "CHANNEL_PRIORITY = ('telegram',)\ndef resolve_owner_review_channel(store): return {}\n"
    violations = scan_source_boundary_violations("plugins/memory/memory_os/x.py", src)

    details = {v["detail"] for v in violations if v["kind"] == "forbidden_host_symbol"}
    assert details == {"CHANNEL_PRIORITY", "resolve_owner_review_channel"}


def test_real_memory_os_tree_has_only_declared_frozen_host_boundary_debt():
    from scripts.memory_os_static_hygiene_check import partition_boundary_violations, scan_source_boundary_violations

    repo_root = Path(__file__).resolve().parents[2]
    root = repo_root / "plugins" / "memory" / "memory_os"
    violations = []
    for path in root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        violations.extend(
            scan_source_boundary_violations(
                path.relative_to(repo_root).as_posix(),
                path.read_text(encoding="utf-8"),
            )
        )
    unapproved, declared = partition_boundary_violations(violations)

    assert unapproved == [], f"unapproved host-boundary violations: {unapproved}"
    assert declared, "current legacy debt must remain visible until S0.4 migration completes"
    assert {item["path"] for item in declared} == {
        "plugins/memory/memory_os/cli.py",
        "plugins/memory/memory_os/hermes_cron_adapter.py",
        "plugins/memory/memory_os/host_capability_probe.py",
        "plugins/memory/memory_os/owner_actions.py",
    }


def test_run_static_hygiene_flags_host_boundary_violation(tmp_path):
    mo = tmp_path / "plugins" / "memory" / "memory_os"
    mo.mkdir(parents=True)
    (mo / "offender.py").write_text(
        "from scripts.memory_os_owner_cron_onboarding import discover_owner_channels\n",
        encoding="utf-8",
    )

    def fake_runner(argv, cwd):
        return {"exit_code": 0, "stdout": "", "stderr": ""}

    report = run_static_hygiene(tmp_path, runner=fake_runner)

    assert report["checks"]["memory_os_host_boundary"]["status"] == "fail"
    assert report["checks"]["memory_os_host_boundary"]["violations"]
    assert report["status"] == "fail"
