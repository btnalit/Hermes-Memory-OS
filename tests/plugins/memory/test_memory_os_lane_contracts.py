"""Freeze-gate census for plugins/memory/memory_os/lane_contracts.py.

Every cron lane in cron_registry.MEMORY_OS_CRON_LANES and every step name
CognitiveLoopRunner can produce (base steps plus the three legacy-right-brain
conditional ones) must have exactly one LANE_CONTRACTS entry -- no more, no
fewer -- and every declared consumer module must actually import. This is
the freeze gate: a new lane or loop step, or a typo'd/renamed one, fails
these tests rather than silently going unclassified.
"""

from __future__ import annotations

import importlib

import pytest

from plugins.memory.memory_os.cognitive_loop import CognitiveLoopRunner
from plugins.memory.memory_os.cron_registry import MEMORY_OS_CRON_LANES
from plugins.memory.memory_os.lane_contracts import (
    DISPOSITIONS,
    LANE_CONTRACTS,
    LaneContract,
    cognitive_loop_step_contract_keys,
    cron_lane_contract_keys,
)
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore


def _real_cron_lane_keys() -> set[str]:
    return {lane.key for lane in MEMORY_OS_CRON_LANES}


def _real_cognitive_loop_step_names(tmp_path) -> set[str]:
    """The full closed vocabulary _step_functions can ever emit.

    Building the tuple of (name, callable) pairs never calls the callables
    (they are deferred lambdas/bound methods), so this is safe against a
    throwaway hermes_home that has no config.yaml and no retirement marker
    -- both loaders fail open to "disabled"/"not retired" for a missing
    path, which gives the base (non-legacy) step set. The three
    legacy-right-brain conditional steps are unioned in separately from the
    existing public helper, so no cognitive_loop.py change was needed to
    make the vocabulary enumerable.
    """
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="default")
    store = MemoryOSStore(roots)
    runner = CognitiveLoopRunner(store)
    base_names = {name for name, _ in runner._step_functions(max_events=0, apply=False)}
    legacy_names = set(CognitiveLoopRunner._legacy_right_brain_step_names())
    return base_names | legacy_names


def test_every_real_cron_lane_has_a_contract_entry():
    real = _real_cron_lane_keys()
    missing = sorted(real - cron_lane_contract_keys())
    assert not missing, f"cron lane(s) missing a lane_contracts entry: {missing}"


def test_no_cron_lane_contract_entry_names_a_lane_that_does_not_exist():
    real = _real_cron_lane_keys()
    stale = sorted(cron_lane_contract_keys() - real)
    assert not stale, f"lane_contracts names cron lane(s) that no longer exist: {stale}"


def test_every_real_cognitive_loop_step_has_a_contract_entry(tmp_path):
    real = _real_cognitive_loop_step_names(tmp_path)
    missing = sorted(real - cognitive_loop_step_contract_keys())
    assert not missing, f"cognitive-loop step(s) missing a lane_contracts entry: {missing}"


def test_no_cognitive_loop_step_contract_entry_names_a_step_that_does_not_exist(tmp_path):
    real = _real_cognitive_loop_step_names(tmp_path)
    stale = sorted(cognitive_loop_step_contract_keys() - real)
    assert not stale, f"lane_contracts names cognitive-loop step(s) that no longer exist: {stale}"


def test_cron_lane_and_cognitive_loop_step_keys_do_not_collide():
    overlap = cron_lane_contract_keys() & cognitive_loop_step_contract_keys()
    assert not overlap, f"a name is registered as both a cron lane and a loop step: {sorted(overlap)}"


def test_lane_contracts_table_is_exactly_the_union_of_both_namespaces():
    assert set(LANE_CONTRACTS) == cron_lane_contract_keys() | cognitive_loop_step_contract_keys()


@pytest.mark.parametrize("key", sorted(LANE_CONTRACTS))
def test_every_entry_declares_consumers_or_a_valid_disposition(key):
    contract = LANE_CONTRACTS[key]
    assert contract.consumers or contract.disposition in DISPOSITIONS, (
        f"{key!r} has neither consumers nor a disposition in {sorted(DISPOSITIONS)}"
    )
    if contract.disposition:
        assert contract.disposition in DISPOSITIONS, f"{key!r} has an unregistered disposition {contract.disposition!r}"


@pytest.mark.parametrize("key", sorted(LANE_CONTRACTS))
def test_every_entry_has_non_empty_reads_and_produces(key):
    contract = LANE_CONTRACTS[key]
    assert contract.reads, f"{key!r} has empty reads"
    assert contract.produces, f"{key!r} has empty produces"


def test_every_declared_consumer_module_imports():
    """A declared consumer that cannot import means the contract is either
    stale (the module was renamed/deleted) or was never a real module in the
    first place -- both are exactly what this freeze gate exists to catch.
    """
    failures: list[tuple[str, str, str]] = []
    for key, contract in LANE_CONTRACTS.items():
        for module_name in contract.consumers:
            try:
                importlib.import_module(module_name)
            except Exception as exc:  # noqa: BLE001 - report every failure, not just the first
                failures.append((key, module_name, repr(exc)))
    assert not failures, f"lane_contracts consumer module(s) failed to import: {failures}"


def test_every_declared_monitor_code_is_emitted_by_the_monitor():
    """A monitor code the monitor never emits gates on vocabulary with no
    producer (CLAUDE.md: "A gate whose vocabulary drifts from its producer's
    checks nothing, silently"). Each declared code/field must appear as a
    quoted literal on a non-comment line of the monitor -- comments are
    excluded because naming a key in prose is not emitting it.
    """
    from pathlib import Path

    from plugins.memory.memory_os.lane_contracts import UNVERIFIED

    monitor_path = Path(__file__).resolve().parents[3] / "scripts" / "memory_os_3_200_monitor.py"
    code_lines = "\n".join(
        line for line in monitor_path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )
    missing = sorted(
        (key, code)
        for key, contract in LANE_CONTRACTS.items()
        for code in contract.monitor_codes
        if code != UNVERIFIED and f'"{code}"' not in code_lines and f"'{code}'" not in code_lines
    )
    assert not missing, f"lane_contracts monitor_codes with no emitter in the monitor: {missing}"


def test_lane_contract_rejects_neither_consumers_nor_disposition():
    """Counterfactual for the freeze gate's own constructor guard.

    Without __post_init__'s check, an entry with no consumers and no
    disposition would silently mean "nothing reads this, for no stated
    reason" -- indistinguishable from an entry nobody finished writing.
    """
    with pytest.raises(ValueError, match="needs consumers or a disposition"):
        LaneContract(
            kind="cron_lane",
            reads=("something",),
            produces=("something",),
        )


def test_lane_contract_rejects_unregistered_disposition():
    with pytest.raises(ValueError, match="unknown disposition"):
        LaneContract(
            kind="cron_lane",
            reads=("something",),
            produces=("something",),
            disposition="not_a_real_disposition",
        )


def test_lane_contract_rejects_unknown_kind():
    with pytest.raises(ValueError, match="unknown kind"):
        LaneContract(
            kind="not_a_real_kind",
            reads=("something",),
            produces=("something",),
            disposition="report_only",
        )


def test_lane_contract_rejects_empty_reads_or_produces():
    with pytest.raises(ValueError, match="reads must be non-empty"):
        LaneContract(kind="cron_lane", reads=(), produces=("x",), disposition="report_only")
    with pytest.raises(ValueError, match="produces must be non-empty"):
        LaneContract(kind="cron_lane", reads=("x",), produces=(), disposition="report_only")


def test_l3_probe_verification_is_watchdog_per_owner_ruling():
    """Owner ruling (see task background): l3_probe_verification is a
    6-hourly self-test that alerts only on failure -- keep it, classify it
    watchdog, do not expect a forward consumer."""
    assert LANE_CONTRACTS["l3_probe_verification"].disposition == "watchdog"
