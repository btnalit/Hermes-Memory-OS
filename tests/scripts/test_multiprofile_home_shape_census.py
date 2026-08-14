"""Census: every copy of the profiles/<name> home-shape derivation agrees.

The multi-profile work grew EIGHT independent implementations of one rule
("is this HERMES_HOME a profiles/<name> home, and if so what is the profile
called?"): the ExecutionGate runner (stdlib-only, cannot import the plugin),
roots, the plugin installer's unit suffix, the monitor's embedded probe, the
upgrade compat probe, the dashboard installer's default unit name, the l3
probe's log slug, and the agent-os shell. Only runner<->roots were pinned to
each other.

That is the same shape as the producer/gate vocabulary drift this project
keeps paying for: N copies of a predicate, one guard. This census pins all
of them to a single behavior table, so a future edit to any one copy fails
here instead of silently splitting behavior across surfaces (e.g. units
suffixed but attribution not, or vice versa).

The bash copy in install_memory_os.sh cannot be imported, so it is checked
by source scan for the same parent=="profiles" rule.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO_ROOT / "scripts"


def _load(script_name: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, _SCRIPTS / script_name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _no_ambient_profile(monkeypatch):
    # Every derivation below must answer from the HOME SHAPE alone.
    monkeypatch.delenv("HERMES_PROFILE", raising=False)
    monkeypatch.delenv("HERMES_AGENT_IDENTITY", raising=False)
    monkeypatch.delenv("HERMES_AGENT_NAME", raising=False)


def _expected(shaped: bool) -> dict[str, object]:
    from scripts.install_memory_os_monitor_dashboard_service import DEFAULT_SERVICE_NAME

    if shaped:
        return {
            "roots_derive": "sannai",
            "roots_resolve": "sannai",
            "runner": "sannai",
            "unit_suffix": "-sannai",
            "compat_suffix": "-sannai",
            "dashboard_unit": "hermes-memory-os-monitor-dashboard-sannai.service",
            "probe_slug": "_sannai",
            "agent_os": "sannai",
        }
    return {
        "roots_derive": "",
        "roots_resolve": "default",
        "runner": "default",
        "unit_suffix": "",
        "compat_suffix": "",
        "dashboard_unit": DEFAULT_SERVICE_NAME,
        "probe_slug": "",
        "agent_os": "default",
    }


def _observed(home: Path, monkeypatch) -> dict[str, object]:
    from plugins.memory.memory_os.roots import _derive_profile_from_home, resolve_profile_name
    from scripts.install_memory_os_monitor_dashboard_service import _default_service_name
    from scripts.install_memory_os_plugin import _runtime_unit_suffix
    from scripts.memory_os_upgrade_compat_check import _unit_suffix_for_home

    runner = _load("memory_os_execution_gate_runner.py", "_census_runner")
    probe = _load("probe_l3_prefetch_behavior.py", "_census_l3_probe")

    # agent-os lives under a dash-named package dir, so it is loaded by path
    # like the script modules above. Its _resolve_profile() reads HERMES_HOME
    # at call time, hence the env set here.
    monkeypatch.setenv("HERMES_HOME", str(home))
    agent_os_spec = importlib.util.spec_from_file_location(
        "_census_agent_os", _REPO_ROOT / "plugins" / "memory-os-agent-os" / "__init__.py"
    )
    agent_os = importlib.util.module_from_spec(agent_os_spec)
    agent_os_spec.loader.exec_module(agent_os)

    return {
        "roots_derive": _derive_profile_from_home(home.expanduser().resolve()),
        "roots_resolve": resolve_profile_name(home, environ={}),
        "runner": runner._resolve_profile(home)[0],
        "unit_suffix": _runtime_unit_suffix(home),
        "compat_suffix": _unit_suffix_for_home(str(home)),
        "dashboard_unit": _default_service_name(home),
        "probe_slug": probe._probe_log_slug(home),
        "agent_os": agent_os._resolve_profile(),
    }


def test_all_home_shape_derivations_agree_on_a_plain_home(tmp_path, monkeypatch):
    assert _observed(tmp_path / ".hermes", monkeypatch) == _expected(shaped=False)


def test_all_home_shape_derivations_agree_on_a_profile_shaped_home(tmp_path, monkeypatch):
    home = tmp_path / ".hermes" / "profiles" / "sannai"
    assert _observed(home, monkeypatch) == _expected(shaped=True)


def test_a_directory_merely_named_profiles_is_not_a_profile_home(tmp_path, monkeypatch):
    # Only the PARENT being "profiles" makes a home profile-shaped; a home
    # called "profiles" is a plain home, and every copy must agree on that.
    observed = _observed(tmp_path / "profiles", monkeypatch)
    assert observed == _expected(shaped=False)


def test_bash_installer_carries_the_same_rule(tmp_path):
    # install_memory_os.sh cannot be imported; pin its predicate by source.
    source = (_SCRIPTS / "install_memory_os.sh").read_text(encoding="utf-8")
    assert "unit_suffix()" in source, "bash unit_suffix helper disappeared"
    assert 'home_parent}" == "profiles"' in source, (
        "bash unit_suffix no longer keys on the parent directory being 'profiles' — "
        "it has drifted from the Python copies pinned above"
    )
