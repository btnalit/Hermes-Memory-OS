"""Installed-layout import resolution for scripts that import ``plugins.*``.

A script that unconditionally does ``sys.path.insert(0, parents[1])`` works in
the repo checkout and breaks on a deployed host: there ``parents[1]`` is
``$HERMES_HOME``, whose ``plugins/`` directory is the *Hermes* plugin dir, not
the memory-os package root. It shadows the runtime namespace and the script
dies with ``ModuleNotFoundError: No module named 'plugins.memory'``.

This happened on the 3.200 production host with ``deploy_l3_probe.py``. Three
more deployed scripts had the identical pattern, so these tests pin the whole
class rather than the one instance that happened to be run.

There is more than one correct bootstrap (resolve the repo root when it holds
the package and fall back to the runtime tree; or target the runtime tree
directly). These tests therefore assert the *defect* is absent rather than
requiring one specific idiom.
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
INSTALLER = SCRIPTS_DIR / "install_memory_os_plugin.py"

# Scripts that resolve ``plugins.*`` lazily inside try/except and prefer an
# installed registry snapshot. They degrade gracefully when the package is
# unavailable, so they need no sys.path fallback.
SOFT_IMPORT_SCRIPTS = {
    "memory_os_cron_group_runner.py",
    "memory_os_execution_gate_runner.py",
}

HARD_PLUGIN_IMPORT = re.compile(r"^\s*from plugins\.\w", re.MULTILINE)
UNCONDITIONAL_REPO_ROOT_INSERT = re.compile(
    r"REPO_ROOT\s*=\s*Path\(__file__\)\.resolve\(\)\.parents\[1\]\s*\n"
    r"\s*if str\(REPO_ROOT\) not in sys\.path:\s*\n"
    r"\s*sys\.path\.insert\(0, str\(REPO_ROOT\)\)"
)


def _deployed_script_names() -> set[str]:
    """Scripts the installer copies into ``$HERMES_HOME/scripts/``.

    Read from the installer's own ``SOURCE_* = REPO_ROOT / "scripts" / "x.py"``
    declarations so the deployed set cannot drift away from this test.
    """
    text = INSTALLER.read_text(encoding="utf-8", errors="replace")
    names = set(re.findall(r'REPO_ROOT\s*/\s*"scripts"\s*/\s*"([^"]+\.py)"', text))
    assert names, "could not read the installer's deployed-script declarations"
    return names


def _scripts_with_hard_plugin_imports():
    for path in sorted(SCRIPTS_DIR.glob("*.py")):
        if path.name in SOFT_IMPORT_SCRIPTS:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if HARD_PLUGIN_IMPORT.search(text):
            yield path, text


def test_no_deployed_script_unconditionally_shadows_the_runtime_namespace():
    """Counterfactual for the class, not just the script that happened to break.

    Reverting any of the four fixed scripts to the bare
    ``sys.path.insert(0, REPO_ROOT)`` form makes this fail.
    """
    deployed = _deployed_script_names()
    offenders = [
        path.name
        for path, text in _scripts_with_hard_plugin_imports()
        if path.name in deployed and UNCONDITIONAL_REPO_ROOT_INSERT.search(text)
    ]

    assert not offenders, (
        f"{offenders} are deployed to $HERMES_HOME/scripts/ and import plugins.*, "
        "but insert parents[1] on sys.path unconditionally. On a host that is "
        "$HERMES_HOME, whose plugins/ dir shadows the memory-os runtime namespace."
    )


def test_repo_only_tools_with_unconditional_insert_are_not_deployed():
    """The exemption is verified, not asserted.

    A few repo-side tools (installer, deploy wrapper, remote probes) legitimately
    insert parents[1] unconditionally because they only ever run from a checkout.
    That is safe *only* while they are not shipped to a host, so this test fails
    the moment one of them starts being deployed.
    """
    deployed = _deployed_script_names()
    unconditional = {
        path.name
        for path, text in _scripts_with_hard_plugin_imports()
        if UNCONDITIONAL_REPO_ROOT_INSERT.search(text)
    }

    newly_deployed = sorted(unconditional & deployed)
    assert not newly_deployed, (
        f"{newly_deployed} now ship to $HERMES_HOME/scripts/ but still resolve "
        "imports as if running from a repo checkout; give them the conditional "
        "runtime-root fallback before deploying them."
    )


SHADOW_ERROR = "No module named 'plugins.memory'"

# The old, broken bootstrap. Injected into a copy of the script to prove this
# test actually detects the defect it claims to guard against.
LEGACY_BOOTSTRAP = (
    "REPO_ROOT = Path(__file__).resolve().parents[1]\n"
    "if str(REPO_ROOT) not in sys.path:\n"
    "    sys.path.insert(0, str(REPO_ROOT))\n"
)


def _installed_layout_home(tmp_path: Path) -> Path:
    """Reproduce the production shape that caused the failure.

    The deployed script sits in ``$HERMES_HOME/scripts/``,
    ``$HERMES_HOME/plugins/`` is the *Hermes* plugin dir (no ``memory/``
    subpackage), and the real package lives under
    ``$HERMES_HOME/memory-os/runtime/python/plugins/``.
    """
    home = tmp_path / "hermes"
    (home / "plugins" / "memory_os").mkdir(parents=True)
    (home / "plugins" / "memory_os" / "__init__.py").write_text("", encoding="utf-8")
    runtime_python = home / "memory-os" / "runtime" / "python"
    runtime_python.mkdir(parents=True)
    shutil.copytree(REPO_ROOT / "plugins", runtime_python / "plugins")
    (home / "scripts").mkdir()
    return home


def _run_from_installed_layout(home: Path, cwd: Path, script_name: str) -> str:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["HERMES_HOME"] = str(home)
    completed = subprocess.run(
        [sys.executable, str(home / "scripts" / script_name), "--help"],
        cwd=str(cwd),  # neutral cwd: the repo must not be discoverable
        env=env,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=180,
    )
    return completed.stderr or ""


@pytest.mark.parametrize(
    "script_name",
    ["memory_os_export_shadow.py", "deploy_l3_probe.py"],
)
def test_script_resolves_plugins_package_under_a_shadowing_installed_layout(tmp_path, script_name):
    """The fixed script must reach the runtime package, not the shadowing dir.

    Only the shadowing failure is asserted. These scripts pull in the wider
    memory-os package, which needs the Hermes agent runtime (``agent`` /
    ``memory_os_agent``); that is absent in CI and is a separate, expected
    environment limitation. Getting far enough to fail on *that* import proves
    ``plugins.memory`` resolved.
    """
    home = _installed_layout_home(tmp_path)
    shutil.copy2(SCRIPTS_DIR / script_name, home / "scripts" / script_name)

    stderr = _run_from_installed_layout(home, tmp_path, script_name)

    assert SHADOW_ERROR not in stderr, stderr
    assert "No module named 'plugins'" not in stderr, stderr


def test_the_shadowing_failure_is_actually_reproducible(tmp_path):
    """Counterfactual for the test above.

    Restores the legacy bootstrap in a copy of the script and asserts the
    installed layout really does produce the production error. Without this,
    the test above could pass simply because the layout never shadowed.
    """
    script_name = "memory_os_export_shadow.py"
    home = _installed_layout_home(tmp_path)
    source = (SCRIPTS_DIR / script_name).read_text(encoding="utf-8")

    start = source.index("# Location-agnostic import resolution.")
    end = source.index("from plugins.", start)
    legacy = source[:start] + LEGACY_BOOTSTRAP + "\n" + source[end:]
    (home / "scripts" / script_name).write_text(legacy, encoding="utf-8")

    stderr = _run_from_installed_layout(home, tmp_path, script_name)

    assert SHADOW_ERROR in stderr, (
        "the installed-layout fixture no longer reproduces the shadowing "
        f"failure, so the guard above proves nothing:\n{stderr}"
    )
