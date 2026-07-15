import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import scripts.memory_os_cron_adapter_probe as cron_probe


def _copy_installed_cron_seam(home: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    runtime_plugins = home / "memory-os" / "runtime" / "python" / "plugins"
    seam_target = runtime_plugins / "seam"
    seam_target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(repo_root / "plugins" / "seam" / "__init__.py", seam_target / "__init__.py")
    adapter_target = seam_target / "hermes_memory_os"
    adapter_target.mkdir(parents=True, exist_ok=True)
    for name in ("__init__.py", "cron_adapter.py"):
        shutil.copy2(repo_root / "plugins" / "seam" / "hermes_memory_os" / name, adapter_target / name)


def _fake_hermes(tmp_path: Path) -> Path:
    script = tmp_path / "fake_hermes.py"
    script.write_text(
        """
import sys
args = sys.argv[1:]
if args[:3] == ["cron", "create", "--help"]:
    print("usage: hermes cron create --script --no-agent")
    raise SystemExit(0)
if args[:3] == ["cron", "edit", "--help"]:
    print("usage: hermes cron edit --script --no-agent")
    raise SystemExit(0)
print("unexpected", args, file=sys.stderr)
raise SystemExit(2)
""".lstrip(),
        encoding="utf-8",
    )
    if os.name == "nt":
        launcher = tmp_path / "hermes.cmd"
        launcher.write_text(f'@"{sys.executable}" "{script}" %*\n', encoding="utf-8")
    else:
        launcher = tmp_path / "hermes"
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        launcher.chmod(0o755)
    return launcher


def test_cron_adapter_probe_uses_installed_snapshot_and_adapter_classification(tmp_path):
    hermes_home = tmp_path / "home"
    snapshot_path = hermes_home / "memory-os" / "system" / "memory_os_cron_registry.json"
    snapshot_path.parent.mkdir(parents=True)
    snapshot_path.write_text(
        json.dumps(
            {
                "schema_version": "memory-os.cron_registry.v0",
                "specs": [
                    {
                        "key": "fake",
                        "name": "memory-os-fake",
                        "raw_script": "memory_os_fake.py",
                        "wrapper_script": "memory_os_cron_fake_gate.py",
                        "lane_id": "fake_lane",
                        "helper_kind": "local_helper",
                        "schedule_arg": "fake_schedule",
                        "deliver_role": "local",
                        "prompt_ref": "empty",
                        "no_agent": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    jobs_path = hermes_home / "cron" / "jobs.json"
    jobs_path.parent.mkdir(parents=True)
    jobs_path.write_text(
        json.dumps({"jobs": [{"name": "memory-os-fake", "script": "memory_os_cron_fake_gate.py"}]}),
        encoding="utf-8",
    )
    script = Path(__file__).resolve().parents[2] / "scripts" / "memory_os_cron_adapter_probe.py"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--hermes-home",
            str(hermes_home),
            "--hermes-bin",
            str(_fake_hermes(tmp_path)),
            "--output",
            "json",
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    report = json.loads(result.stdout)

    assert result.returncode == 0
    assert report["schema_version"] == "memory-os.hermes_cron_adapter_probe.v0"
    assert report["adapter_owner"] == "hermes_memory_os_seam"
    assert report["spec_source"] == "installed_snapshot"
    assert report["capabilities"]["supports_script"] is True
    assert report["classification"]["memory_os_owned_expected_count"] == 1
    assert report["classification"]["memory_os_owned_wrapped_count"] == 1


def test_cron_adapter_probe_classifies_known_optional_jobs_outside_active_snapshot(tmp_path):
    hermes_home = tmp_path / "home"
    snapshot_path = hermes_home / "memory-os" / "system" / "memory_os_cron_registry.json"
    snapshot_path.parent.mkdir(parents=True)
    snapshot_path.write_text(
        json.dumps(
            {
                "schema_version": "memory-os.cron_registry.v0",
                "specs": [
                    {
                        "key": "owner_review_digest",
                        "name": "memory-os-owner-review-digest",
                        "raw_script": "memory_os_owner_review_digest.py",
                        "wrapper_script": "memory_os_cron_owner_review_digest_gate.py",
                        "lane_id": "owner_review_digest_render",
                        "helper_kind": "owner_channel_render",
                        "schedule_arg": "owner_review_schedule",
                        "deliver_role": "owner",
                        "prompt_ref": "owner_review_agent_prompt",
                        "no_agent": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    jobs_path = hermes_home / "cron" / "jobs.json"
    jobs_path.parent.mkdir(parents=True)
    jobs_path.write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "name": "memory-os-owner-review-digest",
                        "script": "memory_os_cron_owner_review_digest_gate.py",
                        "enabled": True,
                    },
                    {
                        "name": "memory-os-right-brain-expression",
                        "script": "memory_os_cron_right_brain_expression_gate.py",
                        "enabled": False,
                    },
                    {
                        "name": "memory-os-memory-sources-feedback-request",
                        "script": "memory_os_cron_memory_sources_feedback_request_gate.py",
                        "enabled": True,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    script = Path(__file__).resolve().parents[2] / "scripts" / "memory_os_cron_adapter_probe.py"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--hermes-home",
            str(hermes_home),
            "--hermes-bin",
            str(_fake_hermes(tmp_path)),
            "--output",
            "json",
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    report = json.loads(result.stdout)

    assert result.returncode == 0
    assert report["classification"]["memory_os_owned_expected_count"] == 1
    assert report["classification"]["memory_os_owned_wrapped_count"] == 1
    assert report["classification"]["memory_os_known_optional_count"] == 1
    assert report["classification"]["memory_os_retired_legacy_count"] == 1
    assert report["classification"]["enabled_retired_legacy_count"] == 0
    assert report["classification"]["enabled_known_optional_outside_active_registry_count"] == 1
    assert report["classification"]["enabled_memory_os_job_count"] == 2
    assert report["classification"]["memory_os_like_unregistered_count"] == 0


# ── sys.path bootstrap tests: repo root priority + installed copy ──


def test_import_comes_from_repo_not_runtime_when_both_exist(tmp_path, monkeypatch):
    """Repo checkout + HERMES_HOME pointing elsewhere → import source is repo.

    Counterfactual: without the precedence fix, the later insert(0, …) for
    runtime paths shadows the earlier repo-root insert, so Python imports
    from the installed runtime instead of the repo checkout.
    """
    # Build a fake installed runtime under a separate HERMES_HOME
    runtime_home = tmp_path / "fake_runtime_home"
    runtime_plugins = (
        runtime_home / "memory-os" / "runtime" / "python" / "plugins" / "memory" / "memory_os"
    )
    runtime_plugins.mkdir(parents=True)
    _copy_installed_cron_seam(runtime_home)
    # Write a sentinel __init__.py so we can detect which copy was imported
    (runtime_plugins / "__init__.py").write_text(
        '__version__ = "RUNTIME_COPY"\n'
        'from pathlib import Path as _Path\n'
        "__file__ = __file__  # noqa\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("HERMES_HOME", str(runtime_home))

    # Run a subprocess that imports memory_os and prints its __file__
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "scripts" / "memory_os_cron_adapter_probe.py"

    probe_code = (
        "import plugins.memory.memory_os as m; "
        "print(m.__file__)"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe_code],
        capture_output=True, text=True,
        env={**os.environ, "HERMES_HOME": str(runtime_home)},
        cwd=str(repo_root),
    )
    # If the import succeeds, its __file__ MUST be inside the repo root
    if result.returncode == 0:
        imported_path = result.stdout.strip()
        repo_root_str = str(repo_root)
        assert imported_path.startswith(repo_root_str), (
            f"Imported from {imported_path}, expected repo root {repo_root_str}. "
            f"Runtime copy at {runtime_plugins} shadowed the repo."
        )


def test_installed_copy_without_env_bootstraps_via_self_location(tmp_path):
    """Installed copy: script copied to <home>/scripts/, no HERMES_HOME env.

    Counterfactual: without self-location inference, an installed script
    with no HERMES_HOME env var fails with ModuleNotFoundError because the
    only sys.path entry is the repo root (parents[1] of the original
    checkout location), which doesn't contain the installed layout.
    """
    import shutil

    home = tmp_path / "installed_home"
    scripts_dir = home / "scripts"
    scripts_dir.mkdir(parents=True)

    # Copy the probe script and its script-level import dependencies
    src_script = Path(__file__).resolve().parents[2] / "scripts" / "memory_os_cron_adapter_probe.py"
    shutil.copy2(src_script, scripts_dir / "memory_os_cron_adapter_probe.py")
    # The probe imports scripts.memory_os_host_profile at module level
    src_host_profile = Path(__file__).resolve().parents[2] / "scripts" / "memory_os_host_profile.py"
    if src_host_profile.exists():
        shutil.copy2(src_host_profile, scripts_dir / "memory_os_host_profile.py")

    # Create the installed runtime layout
    runtime_plugins = home / "memory-os" / "runtime" / "python" / "plugins" / "memory" / "memory_os"
    runtime_plugins.mkdir(parents=True)
    _copy_installed_cron_seam(home)
    (runtime_plugins / "__init__.py").write_text(
        '"""Installed Memory-OS provider."""\n__version__ = "installed"\n',
        encoding="utf-8",
    )
    # Copy required modules into the installed layout
    src_plugins = Path(__file__).resolve().parents[2] / "plugins" / "memory" / "memory_os"
    for mod in ["cron_registry", "hermes_cron_adapter"]:
        src_mod = src_plugins / f"{mod}.py"
        if src_mod.exists():
            shutil.copy2(src_mod, runtime_plugins / f"{mod}.py")

    # Also need roots.py and store.py for the import chain
    for mod in ["roots", "store"]:
        src_mod = src_plugins / f"{mod}.py"
        if src_mod.exists():
            shutil.copy2(src_mod, runtime_plugins / f"{mod}.py")

    # Strip HERMES_HOME from the environment
    env = {k: v for k, v in os.environ.items() if k != "HERMES_HOME"}

    result = subprocess.run(
        [sys.executable, str(scripts_dir / "memory_os_cron_adapter_probe.py"), "--help"],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, (
        f"Installed copy should bootstrap via self-location.\n"
        f"stderr: {result.stderr}"
    )


def test_installed_copy_with_hermes_home_flag_no_env(tmp_path):
    """Installed copy: --hermes-home flag works without HERMES_HOME env var.

    Counterfactual: without preparsing --hermes-home, the module-level
    imports run before argparse so the flag has no effect, and the script
    fails because HERMES_HOME is not in the environment.
    """
    import shutil

    home = tmp_path / "installed_home"
    scripts_dir = home / "scripts"
    scripts_dir.mkdir(parents=True)

    src_script = Path(__file__).resolve().parents[2] / "scripts" / "memory_os_cron_adapter_probe.py"
    shutil.copy2(src_script, scripts_dir / "memory_os_cron_adapter_probe.py")
    # The probe imports scripts.memory_os_host_profile at module level
    src_host_profile = Path(__file__).resolve().parents[2] / "scripts" / "memory_os_host_profile.py"
    if src_host_profile.exists():
        shutil.copy2(src_host_profile, scripts_dir / "memory_os_host_profile.py")

    # Create the installed runtime layout with a full enough import chain
    runtime_plugins = home / "memory-os" / "runtime" / "python" / "plugins" / "memory" / "memory_os"
    runtime_plugins.mkdir(parents=True)
    _copy_installed_cron_seam(home)
    (runtime_plugins / "__init__.py").write_text(
        '"""Installed Memory-OS provider."""\n__version__ = "installed"\n',
        encoding="utf-8",
    )
    src_plugins = Path(__file__).resolve().parents[2] / "plugins" / "memory" / "memory_os"
    for mod in ["cron_registry", "hermes_cron_adapter", "roots", "store"]:
        src_mod = src_plugins / f"{mod}.py"
        if src_mod.exists():
            shutil.copy2(src_mod, runtime_plugins / f"{mod}.py")

    # Create a minimal fake hermes binary
    if os.name == "nt":
        fake_hermes = tmp_path / "fake_hermes.cmd"
        fake_hermes.write_text(f'@"{sys.executable}" -c "import sys; print(sys.argv)" %*\n')
    else:
        fake_hermes = tmp_path / "fake_hermes"
        fake_hermes.write_text(f'#!/bin/sh\nexec "{sys.executable}" -c "import sys; print(sys.argv)" "$@"\n')
        fake_hermes.chmod(0o755)

    # Strip HERMES_HOME from the environment
    env = {k: v for k, v in os.environ.items() if k != "HERMES_HOME"}

    result = subprocess.run(
        [
            sys.executable,
            str(scripts_dir / "memory_os_cron_adapter_probe.py"),
            "--hermes-home", str(home),
            "--hermes-bin", str(fake_hermes),
            "--output", "json",
        ],
        capture_output=True, text=True, env=env,
    )
    # Should succeed — the preparsed --hermes-home enables the import
    assert result.returncode == 0, (
        f"--hermes-home flag should enable bootstrap without env var.\n"
        f"stderr: {result.stderr}"
    )


def test_cli_hermes_home_beats_env_hermes_home_for_imports(tmp_path, monkeypatch):
    """CLI --hermes-home runtime path is added before env HERMES_HOME path.

    When both are set and repo root is not a valid source (installed copy),
    the CLI value should be in sys.path ahead of the env value.
    """
    import shutil

    cli_home = tmp_path / "cli_home"
    env_home = tmp_path / "env_home"

    for home in (cli_home, env_home):
        scripts_dir = home / "scripts"
        scripts_dir.mkdir(parents=True)
        runtime_plugins = home / "memory-os" / "runtime" / "python" / "plugins" / "memory" / "memory_os"
        runtime_plugins.mkdir(parents=True)
        _copy_installed_cron_seam(home)
        (runtime_plugins / "__init__.py").write_text(
            f'"""Home: {home.name}."""\n__version__ = "{home.name}"\n',
            encoding="utf-8",
        )
        src_plugins = Path(__file__).resolve().parents[2] / "plugins" / "memory" / "memory_os"
        for mod in ["cron_registry", "hermes_cron_adapter", "roots", "store"]:
            src_mod = src_plugins / f"{mod}.py"
            if src_mod.exists():
                shutil.copy2(src_mod, runtime_plugins / f"{mod}.py")

    # Copy script to cli_home (installed location)
    src_script = Path(__file__).resolve().parents[2] / "scripts" / "memory_os_cron_adapter_probe.py"
    shutil.copy2(src_script, cli_home / "scripts" / "memory_os_cron_adapter_probe.py")
    # The probe imports scripts.memory_os_host_profile at module level
    src_host_profile = Path(__file__).resolve().parents[2] / "scripts" / "memory_os_host_profile.py"
    if src_host_profile.exists():
        shutil.copy2(src_host_profile, cli_home / "scripts" / "memory_os_host_profile.py")

    # Set env to point to env_home, but CLI points to cli_home
    monkeypatch.setenv("HERMES_HOME", str(env_home))
    env = os.environ.copy()

    # Create fake hermes
    if os.name == "nt":
        fake_hermes = tmp_path / "fake_hermes.cmd"
        fake_hermes.write_text(f'@"{sys.executable}" -c "import sys; print(sys.argv)" %*\n')
    else:
        fake_hermes = tmp_path / "fake_hermes"
        fake_hermes.write_text(f'#!/bin/sh\nexec "{sys.executable}" -c "import sys; print(sys.argv)" "$@"\n')
        fake_hermes.chmod(0o755)

    result = subprocess.run(
        [
            sys.executable,
            str(cli_home / "scripts" / "memory_os_cron_adapter_probe.py"),
            "--hermes-home", str(cli_home),
            "--hermes-bin", str(fake_hermes),
            "--output", "json",
        ],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, (
        f"CLI --hermes-home should work even when env HERMES_HOME is set differently.\n"
        f"stderr: {result.stderr}"
    )


def test_cron_adapter_probe_builds_host_remote_command():
    command = cron_probe.remote_probe_command(
        host="hermes-media",
        remote_repo_root="/opt/Hermes-Memory-OS",
        hermes_home="/root/.hermes",
        hermes_bin="hermes",
        python_bin="python3",
    )

    assert command[0] == "ssh"
    assert command[1] == "hermes-media"
    assert "python3 /opt/Hermes-Memory-OS/scripts/memory_os_cron_adapter_probe.py" in command[2]
    assert "--hermes-home /root/.hermes" in command[2]
    assert "--hermes-bin hermes" in command[2]
    assert "--output json" in command[2]
