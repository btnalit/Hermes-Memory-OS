"""Shared test isolation helpers.

**Canonical-write authority is not granted automatically.**  A test that writes
permanent crystallized memory has to say so, by requesting
``crystallized_test_write_authority`` or declaring it at module level::

    pytestmark = pytest.mark.usefixtures("crystallized_test_write_authority")

This used to be an autouse fixture applied to the entire suite.  That is the
shape of the problem it was meant to solve: a blanket grant means a new test can
drive a production caller that has *lost* its Owner binding and still go green,
because the fixture quietly supplied the authority the caller failed to prove.
Making the grant explicit turns "this test writes canonical memory" into
something a reviewer can see in the diff, and makes the default fail-closed —
an undeclared permanent write now raises ``CrystallizedApprovalError``.

The grant is also narrow in a second way: it only applies to calls made
*directly from a test module*.  Production callers such as ``owner_actions.py``
and ``candidate_aggregation.py`` still have to pass real authority, so Owner
ingress, security, and caller tests continue to exercise the real recorded
digest path.  A test-only fixture must never be able to satisfy a boundary that
production has to satisfy for itself.

Individual tests can opt back out of a module-level grant with
``@pytest.mark.require_explicit_crystallized_capability``.
"""

from pathlib import Path
import inspect

import pytest


_TESTS_ROOT = Path(__file__).resolve().parent


@pytest.fixture
def crystallized_test_write_authority(request, monkeypatch):
    """Authorize canonical writes issued directly by a test module."""

    if request.node.get_closest_marker("require_explicit_crystallized_capability"):
        return

    from plugins.memory.memory_os.crystallized import (
        CrystallizedMemoryService,
        _RESOLVER_PROVISIONAL_WRITE_CAPABILITY,
    )
    import plugins.memory.memory_os.crystallized as crystallized_module

    original_write = CrystallizedMemoryService.write_approved_record
    original_validate_context = crystallized_module.validate_consumed_owner_write_context
    test_context = {"schema_version": "memory-os.test-owner-write-context.v0"}

    def validate_context(store, context, *, candidate_id, reviewer):
        if context is test_context:
            return True
        return original_validate_context(store, context, candidate_id=candidate_id, reviewer=reviewer)

    def authorized_write(self, candidate, decision, *, capability=None, owner_action_context=None, **kwargs):
        caller = inspect.currentframe().f_back
        caller_path = Path(caller.f_code.co_filename).resolve() if caller is not None else Path("/")
        direct_test_call = caller_path == _TESTS_ROOT or _TESTS_ROOT in caller_path.parents
        if direct_test_call:
            if decision.provisional and capability is None:
                capability = _RESOLVER_PROVISIONAL_WRITE_CAPABILITY
            elif not decision.provisional and owner_action_context is None:
                owner_action_context = test_context
        return original_write(
            self,
            candidate,
            decision,
            capability=capability,
            owner_action_context=owner_action_context,
            **kwargs,
        )

    monkeypatch.setattr(crystallized_module, "validate_consumed_owner_write_context", validate_context)
    monkeypatch.setattr(CrystallizedMemoryService, "write_approved_record", authorized_write)


@pytest.fixture(autouse=True)
def isolate_candidate_aggregation_from_real_graph_gate(request, monkeypatch):
    if request.node.get_closest_marker("use_real_crystallization_gate"):
        return

    import plugins.modules.governance.candidate_aggregation as aggregation

    monkeypatch.setattr(
        aggregation,
        "_resolver_candidate_gate_result",
        lambda store, candidate: {
            "status": "ok",
            "candidate_count": 1,
            "flagged_count": 0,
            "flagged_candidates": [],
            "error_count": 0,
            "error_code": "",
            "error_records": [],
        },
    )


_FAKE_HERMES_CONFIG = '''import os
from pathlib import Path


def get_env_value(key):
    # Shape of the real hermes_cli.config.get_env_value: os.environ first,
    # then <HERMES_HOME>/.env through a tokenizer imported lazily at CALL
    # time (the real load_env imports agent.secret_scope inside the call), so
    # a caller that restores sys.path before calling breaks here too.
    if os.environ.get(key) is not None:
        return os.environ[key]
    from hermes_cli.dotenv_reader import read_env
    return read_env(Path(os.environ["HERMES_HOME"]) / ".env").get(key)
'''

_FAKE_HERMES_DOTENV_READER = '''def read_env(path):
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    values = {}
    for line in text.splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key and not key.startswith("#"):
            values[key.strip()] = value.strip()
    return values
'''


@pytest.fixture
def hermes_env_root(tmp_path, monkeypatch):
    """Point Memory-OS' Hermes import scope at a fake Hermes checkout.

    Returns ``install(dotenv=None, *, loader="ok")``. ``dotenv`` is the text of
    ``<HERMES_HOME>/.env`` (``None`` = no file). ``loader`` is ``"ok"`` (a fake
    ``hermes_cli.config.get_env_value``), ``"absent"`` (``HERMES_AGENT_ROOT``
    is an existing empty directory -- a *nonexistent* path would be skipped and
    fall through to ``/usr/local/lib/hermes-agent``), or ``"raises"``.

    Any test that exercises a missing Jev key must request this: without it
    the key lookup falls back to whatever Hermes install the test host has.
    """
    import sys

    def install(dotenv=None, *, loader="ok"):
        home = tmp_path / "fake-hermes-home"
        home.mkdir(exist_ok=True)
        if dotenv is not None:
            (home / ".env").write_text(dotenv, encoding="utf-8")
        root = tmp_path / f"fake-hermes-agent-{loader}"
        root.mkdir(exist_ok=True)
        if loader != "absent":
            (root / "hermes_cli").mkdir(exist_ok=True)
            (root / "hermes_cli" / "__init__.py").write_text("", encoding="utf-8")
            (root / "hermes_cli" / "dotenv_reader.py").write_text(_FAKE_HERMES_DOTENV_READER, encoding="utf-8")
            config = _FAKE_HERMES_CONFIG
            if loader == "raises":
                config = (
                    "def get_env_value(key):\n"
                    "    raise RuntimeError('reader-message-must-not-leak')\n"
                )
            (root / "hermes_cli" / "config.py").write_text(config, encoding="utf-8")
        for name in [n for n in list(sys.modules) if n == "hermes_cli" or n.startswith("hermes_cli.")]:
            monkeypatch.delitem(sys.modules, name, raising=False)
        monkeypatch.setenv("HERMES_HOME", str(home))
        monkeypatch.setenv("HERMES_AGENT_ROOT", str(root))
        return home

    return install
