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
