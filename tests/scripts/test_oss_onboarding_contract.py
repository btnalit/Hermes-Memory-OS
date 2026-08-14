"""Onboarding contract: the documented first-run path must actually exist.

Before this, the only documented install path required a Linux host with a
pre-existing Hermes profile, so a newcomer — or an AI agent following the
README — could not run anything at all. A self-contained blank-machine smoke
(`scripts/memory_os_blank_host_smoke.py`) already existed but was documented
nowhere, and `pip install` produced no console command because pyproject
declared no `[project.scripts]`.

These guards pin the two claims the docs now make. They are deliberately
cheap and structural: they assert the referenced script exists and the
declared entry point resolves to a real callable, so documentation cannot
rot into instructions that fail on a stranger's machine.
"""

from __future__ import annotations

import importlib
import tomllib
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BLANK_HOST_SMOKE = _REPO_ROOT / "scripts" / "memory_os_blank_host_smoke.py"


def _pyproject() -> dict:
    with (_REPO_ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def test_console_entry_point_is_declared_and_resolves():
    scripts = _pyproject().get("project", {}).get("scripts", {})
    assert "memory-os" in scripts, (
        "pyproject declares no `memory-os` console script; a pip install would "
        "again leave the CLI reachable only through the Hermes host"
    )

    target = scripts["memory-os"]
    module_path, _, attribute = target.partition(":")
    assert module_path and attribute, f"malformed entry point: {target!r}"

    module = importlib.import_module(module_path)
    entry = getattr(module, attribute, None)
    assert callable(entry), f"entry point {target!r} does not resolve to a callable"


def test_documented_blank_machine_smoke_script_exists():
    assert _BLANK_HOST_SMOKE.is_file(), (
        "README/quickstart tell a newcomer to run "
        "scripts/memory_os_blank_host_smoke.py, but it is missing"
    )


def test_readme_and_quickstart_document_the_blank_machine_lane():
    readme = (_REPO_ROOT / "README.md").read_text(encoding="utf-8")
    quickstart = (_REPO_ROOT / "docs" / "quickstart.md").read_text(encoding="utf-8")

    for name, text in (("README.md", readme), ("docs/quickstart.md", quickstart)):
        assert "memory_os_blank_host_smoke.py" in text, (
            f"{name} no longer documents the blank-machine lane — the only path "
            f"a reader without a Hermes host can run"
        )
        assert "pip install -e ." in text, f"{name} lost the install command"

    # The CLI command the docs promise after that install.
    assert "memory-os doctor" in readme, (
        "README no longer shows a runnable command for the installed CLI"
    )


def test_scripts_index_names_only_scripts_that_exist():
    """The scripts/ index is the map a newcomer or agent reads before
    touching 95 operational files. A dangling name in it is worse than no
    index — it sends the reader at something that was renamed or removed."""
    import re

    index_path = _REPO_ROOT / "scripts" / "README.md"
    assert index_path.is_file(), "scripts/README.md index is missing"

    text = index_path.read_text(encoding="utf-8")
    named = sorted(set(re.findall(r"`([A-Za-z0-9_./-]+\.(?:py|sh))`", text)))
    assert named, "index names no scripts at all — the regex or the file changed"

    # A bare filename means scripts/<name>; anything with a slash is a
    # repo-relative path (the index also cites a couple of plugin modules).
    missing = [
        name
        for name in named
        if not (_REPO_ROOT / name if "/" in name else _REPO_ROOT / "scripts" / name).is_file()
    ]
    assert not missing, f"scripts/README.md points at nonexistent paths: {missing}"


def test_scripts_index_covers_the_entry_points_a_human_runs():
    text = (_REPO_ROOT / "scripts" / "README.md").read_text(encoding="utf-8")
    for entry in (
        "memory_os_blank_host_smoke.py",
        "install_memory_os.sh",
        "deploy_memory_os.py",
        "memory_os_loop_health_view.py",
    ):
        assert entry in text, f"scripts index no longer lists the entry point {entry}"


def test_blank_host_smoke_declares_its_isolation_guarantees():
    # The lane's value is that a stranger can run it safely; the report says
    # so on its face. If these fields disappear, the docs' safety claim
    # ("never touches an existing profile / no network / no gateway restart")
    # would be unbacked.
    source = _BLANK_HOST_SMOKE.read_text(encoding="utf-8")
    for field in ("production_touched", "network_used", "gateway_restart_attempted"):
        assert field in source, f"blank-host smoke no longer reports {field}"
