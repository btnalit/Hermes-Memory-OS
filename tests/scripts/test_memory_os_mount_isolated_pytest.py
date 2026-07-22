from __future__ import annotations

from pathlib import Path

from scripts.memory_os_mount_isolated_pytest import (
    absolute_without_resolving,
    build_namespace_command,
)


def test_python_symlink_is_not_resolved_out_of_its_virtualenv(tmp_path: Path) -> None:
    target = tmp_path / "base-python"
    target.write_text("", encoding="utf-8")
    venv_python = tmp_path / "venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.symlink_to(target)

    assert absolute_without_resolving(venv_python) == venv_python.absolute()
    assert absolute_without_resolving(venv_python) != target.resolve()


def test_root_command_bind_mounts_empty_home_over_real_root(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    isolated_home = tmp_path / "isolated-home"
    report = tmp_path / "policy.json"
    python = Path("/venv/bin/python")

    command = build_namespace_command(
        repo_root=repo_root,
        isolated_home=isolated_home,
        python=python,
        report_path=report,
        effective_uid=0,
    )

    assert command[:3] == ["unshare", "--mount", "--fork"]
    rendered = " ".join(command)
    assert "mount --bind" in rendered
    assert "/root/.hermes" in rendered
    assert str(isolated_home) in command
    assert str(repo_root) in command
    assert str(python) in command
    assert str(report) in command
    assert "HERMES_HOME" in rendered
    assert "PYTHONPATH" in rendered


def test_non_root_command_uses_user_namespace_mapping(tmp_path: Path) -> None:
    command = build_namespace_command(
        repo_root=tmp_path / "repo",
        isolated_home=tmp_path / "isolated-home",
        python=Path("/venv/bin/python"),
        report_path=tmp_path / "policy.json",
        effective_uid=1000,
    )

    assert command[:5] == [
        "unshare",
        "--mount",
        "--user",
        "--map-root-user",
        "--fork",
    ]


def test_command_uses_explicit_paths_not_ambient_configuration(tmp_path: Path) -> None:
    command = build_namespace_command(
        repo_root=tmp_path / "repo",
        isolated_home=tmp_path / "isolated-home",
        python=Path("/venv/bin/python"),
        report_path=tmp_path / "policy.json",
        effective_uid=0,
    )

    shell_index = command.index("sh")
    assert command[shell_index + 1] == "-c"
    assert command[-4:] == [
        str(tmp_path / "isolated-home"),
        str(tmp_path / "repo"),
        "/venv/bin/python",
        str(tmp_path / "policy.json"),
    ]
