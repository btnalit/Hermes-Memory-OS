"""DC — provenance event-cache sharing (owner review build + aggregation lane).

``store.read_events()`` re-reads and re-parses the entire event corpus on every
call, and ``provenance`` resolves ``source_event_ids`` against it. Both taint
predicates used to load that corpus per *item*, so a batch cost
O(items x events) in file IO, JSON parsing and comparisons.

Measured on the production main profile before the fix: ``doctor`` took 45-72s,
of which ``_candidate_review_items`` was ~59s across 240 corpus reads and
1.87M ``json.loads`` calls. The monitor caps each probe command at 20s, so the
production host reported ``doctor_not_ok`` every night for a lane that was
merely slow, not unhealthy.

The counterfactual here is a **call count**, never wall clock: timing
assertions are flaky, and the defect is "how many times was the corpus read",
which is exactly what a spy can state.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from plugins.memory.memory_os.crystallized import (
    CrystallizedCandidate,
    append_candidate_queue,
)
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.schema import EVENT_SCHEMA_VERSION, EventEnvelope
from plugins.memory.memory_os.store import MemoryOSStore

pytestmark = pytest.mark.usefixtures("crystallized_test_write_authority")


_VALID_ENVELOPE_ID = "xgate_test_provenance_event_cache"


def _store(tmp_path) -> MemoryOSStore:
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def _grant_aggregation_envelope(store: MemoryOSStore) -> str:
    """Write the ExecutionGate permit the aggregation lane's triage writes need."""
    now = datetime.now(timezone.utc)
    envelope = {
        "schema_version": "memory-os.execution_gate_envelope.v0",
        "stage": "permit",
        "execution_gate_envelope_id": _VALID_ENVELOPE_ID,
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": now.replace(year=now.year + 1).isoformat().replace("+00:00", "Z"),
        "profile": "memoryos-test",
        "lane_id": "candidate_aggregation",
        "trigger_surface": "hermes_cron",
        "risk_class": "bounded_reversible_queue",
        "human_approval_required": False,
        "why_no_human_approval": "test",
        "scope": {"registry_key": "candidate_aggregation", "raw_script": "test"},
        "boundary": {
            "actual_send": False,
            "actual_execute": False,
            "actual_identity_write": False,
            "actual_unapproved_crystallized_approval": False,
        },
        "boundary_true": False,
        "precheck": {"helper_present": True},
        "permit_decision": "allowed",
        "permit_reason": "boundary_false",
    }
    gate_path = store.roots.hermes_home / "memory-os" / "system" / "execution_gate_envelopes.jsonl"
    gate_path.parent.mkdir(parents=True, exist_ok=True)
    with gate_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(envelope, sort_keys=True) + "\n")
    return _VALID_ENVELOPE_ID


def _append_event(store: MemoryOSStore, event_id: str, *, source_class: str = "", external_ref: str = "") -> EventEnvelope:
    safe_ref: dict[str, str] = {}
    if source_class:
        safe_ref["source_class"] = source_class
    if external_ref:
        safe_ref["external_ref"] = external_ref
    event = EventEnvelope(
        schema_version=EVENT_SCHEMA_VERSION,
        id=event_id,
        ts="2026-06-18T00:00:00+00:00",
        profile="memoryos-test",
        source="test",
        kind="conversation_turn",
        summary="synthetic event",
        safe_ref=safe_ref,
        tags=[],
        sensitivity="private",
        body_policy="summary_only",
        hashes={},
        promotion_state="raw",
    )
    store.append_event(event)
    return event


def _candidate(candidate_id: str, *, source_event_ids=None, provenance=None) -> CrystallizedCandidate:
    return CrystallizedCandidate(
        candidate_id=candidate_id,
        kind="moment",
        body=f"记住：这是候选 {candidate_id} 的正文，用于验证事件缓存不改变判定结果",
        source_event_ids=list(source_event_ids or []),
        sensitivity="private",
        tags=["test"],
        bridge_state="inner_drive_candidate",
        created_at="2026-06-18T00:00:01+00:00",
        provenance=provenance or {},
    )


class _CountingStore:
    """Wrap a real store, counting read_events() calls.

    Delegates everything else so the code under test operates on genuine
    canonical files written by the real producers.
    """

    def __init__(self, inner: MemoryOSStore) -> None:
        self._inner = inner
        self.read_events_calls = 0

    def read_events(self):
        self.read_events_calls += 1
        return self._inner.read_events()

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _seed_batch(store: MemoryOSStore, *, count: int = 4) -> None:
    """Seed events + candidates through the real producers.

    Hand-written fixtures are what let the event_stats path drift agree with
    its own bug for a whole deployment; every row here goes through
    ``store.append_event`` / ``append_candidate_queue``.
    """
    _append_event(store, "evt-clean-shared")
    _append_event(
        store,
        "evt-tainted-shared",
        source_class="external_evidence",
        external_ref="external:dataset:doc:chunk",
    )
    for i in range(count):
        # Alternate tainted/clean so the batch exercises both verdicts.
        source_ids = ["evt-tainted-shared"] if i % 2 else ["evt-clean-shared"]
        append_candidate_queue(store, _candidate(f"cand-batch-{i:03d}", source_event_ids=source_ids))


# ── The counterfactual: one corpus read per batch, not per item ──────────────


def test_candidate_review_items_reads_event_corpus_once_per_build(tmp_path):
    """Without the shared cache this is >= 2 * N reads (is_tainted + external_ref)."""
    from plugins.memory.memory_os.owner_actions import _candidate_review_items

    real = _store(tmp_path)
    _seed_batch(real, count=4)
    spy = _CountingStore(real)

    items = _candidate_review_items(spy, set())

    assert spy.read_events_calls == 1, (
        f"expected exactly one corpus read per report build, got {spy.read_events_calls}"
    )
    # Non-vacuous: the batch actually produced review items to check.
    assert items, "fixture produced no review items — the counterfactual would be vacuous"


def test_cluster_and_promote_taint_guard_reads_event_corpus_once_per_run(tmp_path):
    """The aggregation lane screens every candidate through the taint guard.

    Scoped deliberately to an all-tainted batch: those candidates are skipped
    before any promotion, so the only corpus reads are the guard's. That
    isolates what this fix owns. The crystallized *write* path
    (``write_approved_record`` / ``_ensure_crystallized_approval``) reads again
    per written record and is intentionally left uncached — see
    ``test_crystallized_write_path_is_deliberately_not_batch_cached``.

    Without the shared cache this is 2 * N reads (is_tainted + external_ref per
    candidate); with it, one.
    """
    from plugins.modules.governance.candidate_aggregation import _cluster_and_promote
    from plugins.memory.memory_os.crystallized import read_effective_candidates

    real = _store(tmp_path)
    _append_event(
        real,
        "evt-tainted-shared",
        source_class="external_evidence",
        external_ref="external:dataset:doc:chunk",
    )
    for i in range(4):
        append_candidate_queue(
            real,
            _candidate(f"cand-tainted-{i:03d}", source_event_ids=["evt-tainted-shared"]),
        )
    envelope_id = _grant_aggregation_envelope(real)
    candidates = [effective.candidate for effective in read_effective_candidates(real)]
    assert len(candidates) >= 3, "counterfactual needs several candidates to be non-vacuous"
    spy = _CountingStore(real)

    _cluster_and_promote(candidates, spy, set(), envelope_id=envelope_id, min_cluster_size=1)

    assert spy.read_events_calls == 1, (
        f"expected exactly one corpus read per lane run, got {spy.read_events_calls}"
    )


def test_crystallized_write_path_is_deliberately_not_batch_cached(tmp_path):
    """Pin the Rule-5 decision: the write boundary keeps reading fresh.

    ``crystallized.write_approved_record`` / ``_ensure_crystallized_approval``
    also call the taint predicates, and they were left uncached on purpose:
    crystallization appends events, so a cache built before a promotion loop
    could answer a *write-boundary* question from a stale corpus. Cheaper is
    not worth wrong at that boundary. This test fails if someone threads a
    batch cache through the signature without revisiting that reasoning.
    """
    import inspect

    from plugins.memory.memory_os import crystallized

    for name in ("write_approved_record", "_ensure_crystallized_approval"):
        source = inspect.getsource(getattr(crystallized.CrystallizedMemoryService, name))
        assert "events_cache" not in source, (
            f"{name} now passes a batch event cache into the taint gate; "
            "that is a write boundary — confirm freshness before allowing it"
        )


# ── Behaviour preservation: the cache is a cheaper spelling, not a new answer ─


def test_shared_cache_verdicts_match_per_call_verdicts(tmp_path):
    """Every taint verdict and external_ref is identical with and without cache."""
    from plugins.memory.memory_os.crystallized import read_effective_candidates
    from plugins.memory.memory_os.provenance import (
        candidate_external_ref,
        is_tainted,
        load_event_cache,
    )

    store = _store(tmp_path)
    _seed_batch(store, count=6)
    candidates = [effective.candidate for effective in read_effective_candidates(store)]
    assert candidates

    cache = load_event_cache(store)
    uncached = [(is_tainted(c, store=store), candidate_external_ref(c, store=store)) for c in candidates]
    cached = [
        (
            is_tainted(c, store=store, events_cache=cache),
            candidate_external_ref(c, store=store, events_cache=cache),
        )
        for c in candidates
    ]

    assert cached == uncached
    # Non-vacuous in both directions: the batch contains tainted and clean rows.
    assert any(verdict for verdict, _ in uncached), "no tainted candidate in fixture"
    assert any(not verdict for verdict, _ in uncached), "no clean candidate in fixture"


def test_event_lookup_first_occurrence_wins_like_the_linear_scan(tmp_path):
    """The index must resolve duplicate ids the way the replaced scan did."""
    from plugins.memory.memory_os.provenance import EventLookup

    class _E:
        def __init__(self, id_, tag):
            self.id = id_
            self.tag = tag

    events = [_E("dup", "first"), _E("dup", "second"), _E("other", "x")]
    lookup = EventLookup(events)

    assert lookup.get("dup").tag == "first"
    assert lookup.get("other").tag == "x"
    assert lookup.get("absent") is None


def test_events_without_ids_do_not_enter_the_index(tmp_path):
    from plugins.memory.memory_os.provenance import EventLookup

    class _E:
        def __init__(self, id_):
            self.id = id_

    lookup = EventLookup([_E(""), _E(None), _E("real")])
    assert lookup.get("") is None
    assert lookup.get("real") is not None


# ── Fail-closed semantics survive the cache ─────────────────────────────────


def test_unreadable_store_still_fails_closed_through_shared_cache(tmp_path):
    """A batch whose corpus cannot be read taints every item, never waves through."""
    from plugins.memory.memory_os.provenance import is_tainted, load_event_cache

    class _BrokenStore:
        def read_events(self):
            raise OSError("event corpus unreadable")

    broken = _BrokenStore()
    cache = load_event_cache(broken)
    candidate = _candidate("cand-broken", source_event_ids=["evt-anything"])

    # Both the uncached and the shared-cache path fail closed.
    assert is_tainted(candidate, store=broken) is True
    assert is_tainted(candidate, store=broken, events_cache=cache) is True


def test_load_event_cache_records_bounded_error_record_on_failure(tmp_path):
    from plugins.memory.memory_os.provenance import load_event_cache

    class _BrokenStore:
        def read_events(self):
            raise OSError("event corpus unreadable")

    error_records: list = []
    load_event_cache(_BrokenStore(), error_records=error_records)

    assert len(error_records) == 1
    record = error_records[0]
    assert record["component"] == "provenance"
    assert record["error_code"] == "store_read_events_failed"


def test_transitive_taint_still_resolves_through_shared_cache(tmp_path):
    """The recursion must keep threading the same cache, not reload per hop."""
    from plugins.memory.memory_os.provenance import is_tainted, load_event_cache

    real = _store(tmp_path)
    _append_event(
        real,
        "evt-tainted-root",
        source_class="external_evidence",
        external_ref="external:dataset:doc:chunk",
    )
    candidate = _candidate("cand-transitive", source_event_ids=["evt-tainted-root"])
    spy = _CountingStore(real)
    cache = load_event_cache(spy)
    calls_after_build = spy.read_events_calls

    assert is_tainted(candidate, store=spy, events_cache=cache) is True
    assert spy.read_events_calls == calls_after_build, "recursion re-read the corpus"


# -- The cache must stay lazy: no candidates => no corpus read ---------------


def test_candidate_review_items_reads_nothing_when_there_are_no_candidates(tmp_path):
    """Regression pin for a trap this fix walked into once.

    ``build_status_report`` reaches ``_candidate_review_items`` on its O(1)
    path, where a profile with no pending candidates must not touch the event
    corpus at all (test_build_status_report_uses_O1_index_health asserts zero
    reads). Hoisting the shared cache above the loop was correct for batches
    and wrong here: it spent one full corpus read on exactly the path that
    exists to avoid one. The full suite caught it; targeted runs did not.
    """
    from plugins.memory.memory_os.owner_actions import _candidate_review_items

    real = _store(tmp_path)
    _append_event(real, "evt-only-an-event")
    spy = _CountingStore(real)

    items = _candidate_review_items(spy, set())

    assert items == []
    assert spy.read_events_calls == 0, (
        f"empty candidate set must not read the event corpus, "
        f"got {spy.read_events_calls} read(s)"
    )


def test_cluster_and_promote_reads_nothing_when_there_is_no_work(tmp_path):
    """Same guard for the lane: an idle evidence tick pays no corpus read."""
    from plugins.modules.governance.candidate_aggregation import _cluster_and_promote

    real = _store(tmp_path)
    _append_event(real, "evt-only-an-event")
    spy = _CountingStore(real)

    _cluster_and_promote([], spy, set(), envelope_id="", min_cluster_size=1)

    assert spy.read_events_calls == 0, (
        f"idle lane run must not read the event corpus, got {spy.read_events_calls} read(s)"
    )
