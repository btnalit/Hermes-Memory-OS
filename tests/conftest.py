"""Shared test isolation helpers.

The canonical-write adapter below is deliberately restricted to *direct calls
from test modules*.  It never adds authority to a production caller such as
``owner_actions.py`` or ``candidate_aggregation.py``; those paths must pass the
real authorization object themselves.  This preserves historical fixture setup
without allowing a global pytest patch to hide a missing production boundary.
"""

from pathlib import Path
import inspect

import pytest


_TESTS_ROOT = Path(__file__).resolve().parent


@pytest.fixture(autouse=True)
def authorize_direct_crystallized_test_writes(request, monkeypatch):
    if request.node.get_closest_marker("require_explicit_crystallized_capability"):
        return

    from plugins.memory.memory_os.crystallized import (
        CrystallizedMemoryService,
        _RESOLVER_PROVISIONAL_WRITE_CAPABILITY,
    )
    import plugins.memory.memory_os.crystallized as crystallized_module

    original_write = CrystallizedMemoryService.write_approved_record
    original_validate_context = crystallized_module._validate_consumed_owner_write_context
    test_context = {"schema_version": "memory-os.test-owner-write-context.v0"}

    def validate_context(store, context, *, candidate, decision):
        if context is test_context:
            return True
        return original_validate_context(store, context, candidate=candidate, decision=decision)

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

    monkeypatch.setattr(crystallized_module, "_validate_consumed_owner_write_context", validate_context)
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
