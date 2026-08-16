"""Attribution contract tests (backlog items 16a / 16b).

16b: exposure_rollup gated on a hardcoded set of source_class names, four of
which (entity_graph, indexed_recall, vector, hindsight) had no producer anywhere
in the project, while the names the producer really emits were absent. Measured
consequence on production: the gate counted 69 attribution gaps and silently
skipped 1093.

16a: prefetch populated section_source_ids at exactly ONE site (crystallized),
so twelve content-bearing classes disclosed chars/count with no source_ids at
all -- working was 0/69, never populated once.
"""

from __future__ import annotations

from datetime import datetime, timezone

from plugins.memory.memory_os.exposure_rollup import (
    ATTRIBUTABLE_SOURCE_CLASSES,
    CANONICAL_SOURCE_ID_PREFIXES,
    NON_ATTRIBUTABLE_SOURCE_CLASSES,
    _extract_record_ids_from_section,
    _memory_source_has_attribution_gap,
    exposure_monitor_stats,
)
from plugins.memory.memory_os.memory_sources import (
    ATTRIBUTION_SCHEMA_VERSION,
    build_memory_source_record,
    read_memory_source_records,
)
from plugins.memory.memory_os.prefetch import (
    SECTION_SOURCE_CLASS_BY_TITLE,
    SECTION_SOURCE_CLASS_FALLBACK,
    _section_source_class,
)


def _producer_vocabulary() -> set[str]:
    return set(SECTION_SOURCE_CLASS_BY_TITLE.values()) | {SECTION_SOURCE_CLASS_FALLBACK}


# ── 16b: the gate's vocabulary must match the producer's ─────────────────


def test_attributable_source_classes_cover_the_producer_vocabulary():
    """Every class the producer can emit must be explicitly classified.

    This is the guard that the original defect could not trip: an unclassified
    class is silently never checked, and a configured class with no producer
    silently checks nothing.

    Counterfactual: restoring any of entity_graph / indexed_recall / vector /
    hindsight to ATTRIBUTABLE_SOURCE_CLASSES fails the no-dead-names assertion;
    adding a section title to SECTION_SOURCE_CLASS_BY_TITLE without classifying
    its class fails the coverage assertion.
    """
    producer = _producer_vocabulary()
    classified = ATTRIBUTABLE_SOURCE_CLASSES | NON_ATTRIBUTABLE_SOURCE_CLASSES

    unclassified = producer - classified
    assert not unclassified, (
        "source_class(es) the producer emits but the attribution contract does "
        f"not classify (silently never checked): {sorted(unclassified)}"
    )

    dead_names = classified - producer
    assert not dead_names, (
        "source_class name(s) in the attribution contract that NO producer "
        f"emits (the check silently does nothing for them): {sorted(dead_names)}"
    )

    assert not (ATTRIBUTABLE_SOURCE_CLASSES & NON_ATTRIBUTABLE_SOURCE_CLASSES), (
        "a class cannot be both attributable and exempt"
    )


def test_every_attributable_class_has_a_recognised_id_prefix():
    """A class required to carry IDs whose IDs the rollup cannot recognise is
    the other half of the same defect: working could not be classified even if
    it were populated, which is where classified_ratio 0.7018 came from.
    """
    # crystallized/candidate/working/event own a literal prefix; indexed and
    # graph_layer emit "<record_type>:<record_id>" where record_type is itself
    # one of those canonical types, so they are covered transitively.
    # recall_facade is the same shape: prefetch._recall_object_canonical_ids
    # translates each RecallObject's lane-specific source_ref (e.g.
    # "entity_graph:<id>") through the same record_type -> canonical prefix
    # table _canonical_source_id uses for graph_layer, rather than passing
    # the retriever's own ad hoc prefix through verbatim.
    direct = {prefix.rstrip(":") for prefix in CANONICAL_SOURCE_ID_PREFIXES}
    transitive = {"indexed", "graph_layer", "recall_facade"}
    uncovered = ATTRIBUTABLE_SOURCE_CLASSES - direct - transitive
    assert not uncovered, (
        f"attributable class(es) with no recognised source_id prefix: {sorted(uncovered)}"
    )


def test_extractor_recognises_working_and_event_ids():
    """Counterfactual: with the old crystallized/candidate-only prefix filter
    these return [], which is why working sections were unclassifiable.
    """
    section = {
        "source_class": "working",
        "chars": 100,
        "source_ids": ["working:task/anchor:item-1", "event:evt-9"],
        "reason_codes": [],
    }
    assert _extract_record_ids_from_section(section) == [
        "working:task/anchor:item-1",
        "event:evt-9",
    ]


def test_non_canonical_source_ids_are_still_ignored():
    """The prefix filter must stay a filter, not become "accept anything"."""
    section = {
        "source_class": "working",
        "chars": 100,
        "source_ids": ["", "not-a-canonical-ref", "prefix_without_colon"],
        "reason_codes": [],
    }
    assert _extract_record_ids_from_section(section) == []


def test_working_section_without_ids_is_now_an_attribution_gap():
    """The 69 production gaps in one assertion."""
    record = {
        "attribution_schema": ATTRIBUTION_SCHEMA_VERSION,
        "selected": [
            {"source_class": "working", "chars": 120, "source_ids": [], "reason_codes": []}
        ],
        "dropped": [],
    }
    assert _memory_source_has_attribution_gap(record) is True

    attributed = {
        "attribution_schema": ATTRIBUTION_SCHEMA_VERSION,
        "selected": [
            {
                "source_class": "working",
                "chars": 120,
                "source_ids": ["working:notes:item-1"],
                "reason_codes": [],
            }
        ],
        "dropped": [],
    }
    assert _memory_source_has_attribution_gap(attributed) is False


def test_exempt_class_without_ids_is_not_a_gap():
    """Derived aggregate views have no 1:1 record to cite, so requiring IDs
    would be unsatisfiable rather than merely unmet.
    """
    for exempt in sorted(NON_ATTRIBUTABLE_SOURCE_CLASSES):
        record = {
            "attribution_schema": ATTRIBUTION_SCHEMA_VERSION,
            "selected": [
                {"source_class": exempt, "chars": 120, "source_ids": [], "reason_codes": []}
            ],
            "dropped": [],
        }
        assert _memory_source_has_attribution_gap(record) is False, exempt


# ── 16a: the producer must actually populate what the gate requires ──────


def test_section_source_class_mapping_is_the_single_source_of_truth():
    """_section_source_class must read from the introspectable mapping, so the
    guard above is testing the real producer rather than a copy of it.
    """
    for title, expected in SECTION_SOURCE_CLASS_BY_TITLE.items():
        assert _section_source_class(title) == expected
    assert _section_source_class("Some Title Nobody Mapped") == SECTION_SOURCE_CLASS_FALLBACK
    # Degradation suffixes must still resolve to the base title's class.
    assert _section_source_class("Crystallized Memory (deterministic floor recall)") == (
        "crystallized"
    )


def test_every_emitted_section_title_is_mapped_in_the_producer_vocabulary(tmp_path):
    """Closes the blind direction that let "Recent Cross-Session" drift.

    test_section_source_class_mapping_is_the_single_source_of_truth (above)
    only proves the map's VALUES are all classified against
    _section_source_class -- it says nothing about whether the map's KEYS
    cover every title the real producer actually emits. "Recent
    Cross-Session" was a live injected section (_build_prefetch_sections,
    prefetch.py) absent from SECTION_SOURCE_CLASS_BY_TITLE for exactly that
    reason: nothing ever checked the other direction, so it silently fell
    through to the unattributable fallback forever.

    This runs the real producer (_build_prefetch_sections) against a
    populated store rather than a hand-written list of titles -- a
    hardcoded fixture would make this pass vacuously, which is exactly how
    the original gap survived.

    Counterfactual: remove the "Recent Cross-Session" entry from
    SECTION_SOURCE_CLASS_BY_TITLE and this fails, because the seeded store
    below makes the real producer emit that exact title.
    """
    import json
    from datetime import timedelta

    from plugins.memory.memory_os.crystallized import (
        CrystallizedCandidate,
        append_candidate_queue,
    )
    from plugins.memory.memory_os.prefetch import _build_prefetch_sections
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.schema import EVENT_SCHEMA_VERSION, EventEnvelope
    from plugins.memory.memory_os.store import MemoryOSStore

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    store = MemoryOSStore(roots)
    store.initialize()

    current_session_id = "sess_guard_current"
    other_session_id = "sess_guard_other"

    # Recent Event Summaries: an event in the current session.
    store.append_event(EventEnvelope(
        schema_version=EVENT_SCHEMA_VERSION,
        id="evt_guard_current",
        ts=datetime.now(timezone.utc).isoformat(),
        profile="memoryos-test",
        source="test",
        kind="conversation_turn",
        summary="User: guard-test current session content | Assistant: ack",
        safe_ref={"session_id": current_session_id},
        tags=[],
    ))

    # Recent Cross-Session: a source-gate-passed event from another session
    # within the recency window -- the exact section under test.
    cross_event_id = "evt_guard_cross"
    store.append_event(EventEnvelope(
        schema_version=EVENT_SCHEMA_VERSION,
        id=cross_event_id,
        ts=(datetime.now(timezone.utc) - timedelta(hours=3)).isoformat(),
        profile="memoryos-test",
        source="test",
        kind="conversation_turn",
        summary="User: guard-test cross-session content | Assistant: ack",
        safe_ref={"session_id": other_session_id},
        tags=[],
    ))
    candidates_path = store.roots.crystallized_root / "candidates.jsonl"
    candidates_path.parent.mkdir(parents=True, exist_ok=True)
    candidates_path.write_text(
        json.dumps({
            "candidate_id": "cand_guard_gate",
            "kind": "moment",
            "body": "source-gate candidate for the guard test",
            "source_event_ids": [cross_event_id],
            "tags": [],
            "sensitivity": "private",
            "bridge_state": "inner_drive_candidate",
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Crystallized Review Candidates: a queue row surfaced via magic word.
    append_candidate_queue(
        store,
        CrystallizedCandidate(
            candidate_id="cand_guard_review",
            kind="moment",
            body="review-queue candidate for the guard test",
            source_event_ids=["evt_guard_review"],
            sensitivity="private",
            tags=["synthetic"],
            bridge_state="inner_drive_candidate",
        ),
    )

    sections, _source_ids = _build_prefetch_sections(
        "candidate 候选 review guard-test content",
        store=store,
        index=None,
        session_id=current_session_id,
    )

    emitted_titles = [title for title, _lines in sections]
    assert "Recent Cross-Session" in emitted_titles, (
        f"seed did not exercise the section under test; emitted: {emitted_titles}"
    )
    assert len(emitted_titles) >= 3, (
        f"guard is checking too little of the real producer's surface: {emitted_titles}"
    )

    for title in emitted_titles:
        base_title = title.split(" (")[0] if " (" in title else title
        assert base_title in SECTION_SOURCE_CLASS_BY_TITLE, (
            f"{title!r} is emitted by the real producer but absent from "
            f"SECTION_SOURCE_CLASS_BY_TITLE -- it falls through to the "
            f"unattributable {SECTION_SOURCE_CLASS_FALLBACK!r} fallback and "
            f"the disclosure audit can never see it. Emitted titles: {emitted_titles}"
        )


def test_recall_facade_section_is_mapped_and_source_ids_are_wired(tmp_path):
    """The Recall Facade section is only emitted when a recall_facade whose
    plan resolves to apply_canary is passed in (default recall_facade=None),
    which is exactly why the "Recent Cross-Session" guard above -- driven
    without a facade -- could not catch this sibling defect: the section
    ``sections.append(("Recall Facade (unified)", [facade_text]))`` bypasses
    ``_append_section`` entirely, so its title was absent from
    SECTION_SOURCE_CLASS_BY_TITLE (falls through to the unattributable
    "other" fallback) and from _budget_keep_priority (silent default 50).

    This drives the real producer (_build_prefetch_sections) with a fake
    facade whose retrieve() returns real RecallObjects across three lanes
    that DO resolve to a canonical record (crystallized, entity_graph,
    indexed_fts) plus one lane that does NOT (state_overlay, an aggregate
    projection with no 1:1 record) -- proving both that attribution is wired
    and that it is not fabricated for content that cannot honestly carry it.

    Counterfactual: removing the "Recall Facade" entry from
    SECTION_SOURCE_CLASS_BY_TITLE fails the mapping assertions below (falls
    back to "other"); removing the source_ids wiring in
    _build_prefetch_sections's facade block, or reverting
    _recall_object_canonical_ids to a verbatim source_ref pass-through, fails
    the source_ids assertions; leaving _budget_keep_priority unmodified fails
    the priority assertion (silent default 50).
    """
    from plugins.memory.memory_os.prefetch import (
        _budget_keep_priority,
        _build_prefetch_sections,
        _section_source_class,
    )
    from plugins.memory.memory_os.recall_types import RecallObject
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    store = MemoryOSStore(roots)
    store.initialize()

    class _ApplyCanaryFacadeWithRealObjects:
        last_recall_plan = {"mode": "apply_canary"}

        def retrieve(self, store, query, *, top_k=10, scope=None):
            return {
                "crystallized": [
                    RecallObject(
                        recall_type="crystallized",
                        content="guard-test crystallized facade content",
                        source_ref="crystallized:cryst_guard_facade",
                    )
                ],
                "entity_graph": [
                    RecallObject(
                        recall_type="entity_graph",
                        content="guard-test entity-graph facade content",
                        source_ref="entity_graph:cryst_guard_facade",
                        metadata={"related_record_id": "cryst_guard_facade"},
                    )
                ],
                "indexed_fts": [
                    RecallObject(
                        recall_type="indexed_fts",
                        content="guard-test fts facade content",
                        source_ref="fts5:evt_guard_facade",
                        metadata={"kind": "event", "record_id": "evt_guard_facade"},
                    )
                ],
                "state_overlay": [
                    RecallObject(
                        recall_type="state_overlay",
                        content="guard-test overlay facade content (no 1:1 record)",
                        source_ref="active_projects",
                    )
                ],
            }

        def format_context(self, results, *, budget=800):
            return "bounded canary recall spanning multiple lanes"

    sections, section_source_ids = _build_prefetch_sections(
        "guard-test facade content", store=store, index=None,
        recall_facade=_ApplyCanaryFacadeWithRealObjects(),
    )

    emitted_titles = [title for title, _lines in sections]
    assert "Recall Facade (unified)" in emitted_titles, (
        f"fake facade did not exercise the section under test; emitted: {emitted_titles}"
    )

    # (d) real-producer coverage: every emitted title, not a hardcoded list.
    for title in emitted_titles:
        base_title = title.split(" (")[0] if " (" in title else title
        assert base_title in SECTION_SOURCE_CLASS_BY_TITLE, (
            f"{title!r} is emitted by the real producer but absent from "
            f"SECTION_SOURCE_CLASS_BY_TITLE. Emitted titles: {emitted_titles}"
        )

    # (a) explicit, non-fallback classification.
    assert _section_source_class("Recall Facade (unified)") == "recall_facade"
    assert _section_source_class("Recall Facade (unified)") != SECTION_SOURCE_CLASS_FALLBACK

    # (b) source_ids wired at the append site, translated to the canonical
    # vocabulary -- and NOT fabricated for the state_overlay object, which
    # has no 1:1 canonical record.
    facade_ids = section_source_ids.get("Recall Facade (unified)")
    assert facade_ids == [
        "crystallized:cryst_guard_facade",
        "crystallized:cryst_guard_facade",
        "event:evt_guard_facade",
    ], facade_ids

    # (c) explicit budget priority, not the silent default.
    assert _budget_keep_priority("Recall Facade (unified)") == 58
    assert _budget_keep_priority("Recall Facade (unified)") != 50


def test_new_records_carry_the_attribution_era_marker(tmp_path):
    """Without the marker the gate cannot tell a fixed-producer record from a
    pre-fix one, and the FAIL could never clear.
    """
    from plugins.memory.memory_os.roots import MemoryOSRoots

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="main")
    record = build_memory_source_record(
        roots=roots,
        route_report={},
        selected_sections=[],
        context_router_config={},
        router_applied=False,
        prefetch_mode="live",
    )
    assert record["attribution_schema"] == ATTRIBUTION_SCHEMA_VERSION
# ── 16a end-to-end: the real producer must leave no attribution gap ──────


def _seed_store_with_attributable_content(tmp_path):
    """Seed working + event + candidate content through the real writers."""
    from plugins.memory.memory_os.crystallized import CrystallizedCandidate, append_candidate_queue
    from plugins.memory.memory_os.fixtures import build_event, build_working_item
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.schema import WORKING_SCHEMA_VERSION, EventEnvelope
    from plugins.memory.memory_os.store import MemoryOSStore

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="memoryos-test")
    store = MemoryOSStore(roots)
    store.initialize()

    event = EventEnvelope.from_dict(build_event(seed=1, profile="memoryos-test"))
    store.append_event(event)

    working_item = build_working_item(seed=2, source_event_id=event.id)
    store.write_working_document(
        "lingering",
        {
            "schema_version": WORKING_SCHEMA_VERSION,
            "updated_at": working_item.updated_at,
            "items": [
                {
                    **working_item.__dict__,
                    "text": "Synthetic memory working item about a candidate decision",
                }
            ],
        },
    )

    append_candidate_queue(
        store,
        CrystallizedCandidate(
            candidate_id="cand_attribution_e2e",
            kind="moment",
            body="A candidate memory body for attribution coverage.",
            source_event_ids=[event.id],
            sensitivity="private",
            tags=["synthetic"],
            bridge_state="inner_drive_candidate",
        ),
    )
    return store


def test_real_prefetch_leaves_no_attribution_gap(tmp_path):
    """The outcome-level guard for item 16a.

    source_ids is collected through an OPTIONAL out-parameter, which by
    construction cannot force a caller to pass it -- so the real protection is
    this test, asserting that a genuine prefetch produces a disclosure record
    with zero attribution gaps.

    Counterfactual: drop any `source_ids=` argument in
    _build_prefetch_sections, or any `source_ids.append(...)` in a section
    builder, and the corresponding class discloses chars with no IDs -- exactly
    the production state where working was 0/69 -- and this fails.
    """
    from plugins.memory.memory_os.prefetch import build_prefetch

    store = _seed_store_with_attributable_content(tmp_path)

    context = build_prefetch(
        "candidate memory",
        budget_chars=6000,
        store=store,
        index=None,
        memory_sources_config={"enabled": True},
    )
    assert context, "prefetch produced no context, so this would prove nothing"

    records = read_memory_source_records(store.roots, limit=10)
    assert len(records) == 1
    record = records[0]

    # The record must be inside the gated era, or a gap would not be checked.
    assert record["attribution_schema"] == ATTRIBUTION_SCHEMA_VERSION

    # Guard against a vacuous pass: the attributable classes this test exists to
    # cover must actually be present with content.
    present_attributable = {
        str(section.get("source_class") or "")
        for key in ("selected", "dropped")
        for section in (record.get(key) or [])
        if isinstance(section, dict)
        and str(section.get("source_class") or "") in ATTRIBUTABLE_SOURCE_CLASSES
        and (int(section.get("chars") or 0) > 0 or int(section.get("count") or 0) > 0)
    }
    for expected in ("working", "event", "candidate"):
        assert expected in present_attributable, (
            f"{expected} section absent, so this test would pass vacuously; "
            f"present: {sorted(present_attributable)}"
        )

    assert _memory_source_has_attribution_gap(record) is False, (
        "a real prefetch disclosed an attributable section without naming the "
        "records it drew from"
    )

    # And the IDs must be in the canonical form the rollup can classify --
    # populated-but-unrecognisable is the other half of the same defect.
    for key in ("selected", "dropped"):
        for section in record.get(key) or []:
            if not isinstance(section, dict):
                continue
            if str(section.get("source_class") or "") not in ATTRIBUTABLE_SOURCE_CLASSES:
                continue
            if int(section.get("chars") or 0) <= 0 and int(section.get("count") or 0) <= 0:
                continue
            assert _extract_record_ids_from_section(section), (
                f"{section.get('source_class')} carries source_ids the rollup "
                f"cannot classify: {section.get('source_ids')}"
            )


def test_real_prefetch_record_is_gated_and_clean_end_to_end(tmp_path):
    """Ties both halves together: a fixed-producer record is IN the gated era
    AND passes, so schema_era_health is PASS on real output rather than because
    the era filter excluded everything.
    """
    from plugins.memory.memory_os.prefetch import build_prefetch

    store = _seed_store_with_attributable_content(tmp_path)
    build_prefetch(
        "candidate memory",
        budget_chars=6000,
        store=store,
        index=None,
        memory_sources_config={"enabled": True},
    )

    stats = exposure_monitor_stats(store, now=datetime(2026, 8, 4, tzinfo=timezone.utc))
    assert stats["attribution_era_record_count"] >= 1, (
        "the real producer's record must land inside the gated era"
    )
    assert stats["schema_era_attribution_gap_count"] == 0
    assert stats["legacy_unattributed_record_count"] == 0
