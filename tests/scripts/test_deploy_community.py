"""Standard deployment contract for Hermes Community."""

from __future__ import annotations

import json
from pathlib import Path

import scripts.deploy_community as deploy_module
from scripts.deploy_community import COMMUNITY_MODULES, build_deploy_plan, deploy_community, main


def _source_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    plugin = repo / "plugins" / "memory" / "memory_os"
    scripts = repo / "scripts"
    plugin.mkdir(parents=True)
    scripts.mkdir()
    for module in COMMUNITY_MODULES:
        (plugin / module).write_text(f"# {module}\n", encoding="utf-8")
    shell = repo / "plugins" / "memory-os-agent-os"
    shell.mkdir()
    (shell / "__init__.py").write_text("# agent-os community cli\n", encoding="utf-8")
    (scripts / "deploy_community.py").write_text("# deploy\n", encoding="utf-8")
    return repo


def _installed_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    flat = home / "plugins" / "memory_os"
    runtime = home / "memory-os" / "runtime" / "python" / "plugins" / "memory" / "memory_os"
    flat.mkdir(parents=True)
    runtime.mkdir(parents=True)
    (flat / "plugin.yaml").write_text("name: memory_os\n", encoding="utf-8")
    (runtime / "store.py").write_text("# installed Memory-OS\n", encoding="utf-8")
    return home


def test_deploy_plan_contains_all_modules_and_script(tmp_path: Path) -> None:
    assert {"jsonl_io.py", "cron_registry.py", "legacy_right_brain_retirement.py"}.issubset(COMMUNITY_MODULES)
    repo = _source_repo(tmp_path)
    home = tmp_path / "home"
    plan = build_deploy_plan(repo_root=repo, hermes_home=home)
    assert [item.name for item in plan.files] == [
        *COMMUNITY_MODULES,
        "memory-os-agent-os/__init__.py",
        "deploy_community.py",
    ]
    assert plan.memory_os_root == home / "memory-os"


def test_dry_run_is_no_write(tmp_path: Path) -> None:
    repo = _source_repo(tmp_path)
    home = tmp_path / "home"
    result = deploy_community(repo_root=repo, hermes_home=home, dry_run=True)
    assert result.status == "planned"
    assert not home.exists()


def test_apply_deploys_every_module_and_script_with_hash_verification(tmp_path: Path) -> None:
    repo = _source_repo(tmp_path)
    home = _installed_home(tmp_path)
    result = deploy_community(repo_root=repo, hermes_home=home)
    assert result.status == "applied"
    assert result.hash_failures == []
    for module in COMMUNITY_MODULES:
        assert (home / "plugins" / "memory_os" / module).is_file()
        assert (home / "memory-os" / "runtime" / "python" / "plugins" / "memory" / "memory_os" / module).is_file()
    assert (home / "scripts" / "deploy_community.py").is_file()
    assert (home / "plugins" / "memory-os-agent-os" / "__init__.py").is_file()
    assert (home / "memory-os" / "community" / "roster.jsonl").is_file()


def test_apply_preserves_existing_budget_by_default(tmp_path: Path) -> None:
    repo = _source_repo(tmp_path)
    home = _installed_home(tmp_path)
    budget = home / "memory-os" / "community" / "budget.yaml"
    budget.parent.mkdir(parents=True)
    budget.write_text("owner_custom: true\n", encoding="utf-8")
    result = deploy_community(repo_root=repo, hermes_home=home)
    assert result.status == "applied"
    assert budget.read_text(encoding="utf-8") == "owner_custom: true\n"


def test_apply_refuses_partial_install_without_memory_os_prerequisites(tmp_path: Path) -> None:
    repo = _source_repo(tmp_path)
    home = tmp_path / "home"
    result = deploy_community(repo_root=repo, hermes_home=home)
    assert result.status == "fail"
    assert all("Memory-OS prerequisite missing" in error for error in result.errors)
    assert not home.exists()


def test_apply_rolls_back_when_runtime_dependency_closure_cannot_import(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[2]
    home = _installed_home(tmp_path)
    result = deploy_community(repo_root=repo, hermes_home=home)
    assert result.status == "fail"
    assert any("runtime import probe" in failure for failure in result.hash_failures)
    assert "deployment rolled back" in result.errors
    assert not (home / "plugins" / "memory_os" / "community.py").exists()


def test_force_budget_is_restored_when_post_layout_verification_fails(tmp_path: Path, monkeypatch) -> None:
    repo = _source_repo(tmp_path)
    home = _installed_home(tmp_path)
    budget = home / "memory-os" / "community" / "budget.yaml"
    budget.parent.mkdir(parents=True)
    budget.write_text("owner_custom: true\n", encoding="utf-8")
    monkeypatch.setattr(deploy_module, "_verify", lambda _plan: ["injected-post-layout-failure"])

    result = deploy_community(repo_root=repo, hermes_home=home, force_budget=True)

    assert result.status == "fail"
    assert budget.read_text(encoding="utf-8") == "owner_custom: true\n"
    assert "deployment rolled back" in result.errors


def test_apply_rolls_back_every_changed_file_on_copy_failure(tmp_path: Path, monkeypatch) -> None:
    repo = _source_repo(tmp_path)
    home = _installed_home(tmp_path)
    flat_community = home / "plugins" / "memory_os" / "community.py"
    runtime_community = home / "memory-os" / "runtime" / "python" / "plugins" / "memory" / "memory_os" / "community.py"
    flat_community.write_text("# old flat\n", encoding="utf-8")
    runtime_community.write_text("# old runtime\n", encoding="utf-8")
    original_copy2 = deploy_module.shutil.copy2
    failed = False

    def flaky_copy(source, target, *args, **kwargs):
        nonlocal failed
        target_path = Path(target)
        if not failed and target_path.name == "partner_create.py" and "runtime/python" in str(target_path):
            failed = True
            raise OSError("injected")
        return original_copy2(source, target, *args, **kwargs)

    monkeypatch.setattr(deploy_module.shutil, "copy2", flaky_copy)
    result = deploy_community(repo_root=repo, hermes_home=home)

    assert result.status == "fail"
    assert "deployment rolled back" in result.errors
    assert flat_community.read_text(encoding="utf-8") == "# old flat\n"
    assert runtime_community.read_text(encoding="utf-8") == "# old runtime\n"
    assert not (home / "plugins" / "memory_os" / "partner_create.py").exists()


def test_cli_uses_repo_layout_and_emits_json(tmp_path: Path, capsys) -> None:
    repo = _source_repo(tmp_path)
    home = tmp_path / "home"
    code = main([
        "--repo-root", str(repo),
        "--hermes-home", str(home),
        "--phase", "dry-run",
        "--output", "json",
    ])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["status"] == "planned"
    assert payload["file_count"] == len(COMMUNITY_MODULES) + 2


def test_memory_os_installer_includes_community_deploy_helper(tmp_path: Path) -> None:
    from scripts.install_memory_os_plugin import _write_operational_helper_scripts

    targets = _write_operational_helper_scripts(tmp_path / "home", dry_run=True)
    assert targets["community_deploy"].name == "deploy_community.py"


def test_memory_os_installer_initializes_community_layout_without_overwrite(tmp_path: Path) -> None:
    from scripts.install_memory_os_plugin import _initialize_community_layout

    home = tmp_path / "home"
    budget = home / "memory-os" / "community" / "budget.yaml"
    budget.parent.mkdir(parents=True)
    budget.write_text("owner_custom: true\n", encoding="utf-8")
    report = _initialize_community_layout(home, dry_run=False)
    assert report["status"] == "ok"
    assert budget.read_text(encoding="utf-8") == "owner_custom: true\n"
    assert (budget.parent / "roster.jsonl").is_file()
