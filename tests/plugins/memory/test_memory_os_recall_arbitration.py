from __future__ import annotations

from plugins.memory.memory_os.recall_arbitration import (
    apply_recall_plan,
    build_recall_plan,
    content_fingerprint,
    record_session_injection,
)
from plugins.memory.memory_os.recall_types import RecallObject, RecallType


def _obj(content: str, *, recall_type=RecallType.INDEXED_FTS.value, authority="indexed_derived", score=0.5, revision="", claim="", ref=""):
    return RecallObject(
        recall_type=recall_type,
        content=content,
        score=score,
        source_ref=ref or content[:8],
        authority_class=authority,
        task_revision=revision,
        claim_key=claim,
    )


def _ledger_value(task_revision: str, *, source_rev: str = "") -> dict[str, str]:
    """FIX 4 new-format session-ledger value: suppression requires BOTH
    task_revision and source_rev to match. `source_rev=""` matches objects
    with no `metadata["source_updated_at"]`, which is the default for
    every fixture built by `_obj` unless a test sets it explicitly."""
    return {"task_revision": task_revision, "source_rev": source_rev}


def test_recall_plan_deduplicates_then_ranks_globally_before_budget():
    low = _obj("deployment boundary legacy", score=0.4, authority="indexed_derived", ref="low")
    duplicate = _obj("deployment boundary legacy", score=0.9, authority="approved_canonical", ref="canonical")
    high = _obj("current owner deployment boundary", score=0.8, authority="direct_current_task", ref="high")

    plan = build_recall_plan([low, duplicate, high], budget_chars=len(high.content), mode="shadow")

    assert plan["exact_duplicate_count"] == 1
    assert plan["selected_count"] == 1
    assert plan["selected"][0]["object"]["source_ref"] == "high"
    assert any(item["reason"] == "budget_exceeded" for item in plan["suppressed"])
    assert plan["would_change_live_recall"] is True


def test_recall_plan_suppresses_stale_overlay_and_session_duplicate():
    overlay = _obj(
        "old task projection",
        recall_type=RecallType.STATE_OVERLAY.value,
        authority="state_projection",
        revision="rev-old",
    )
    repeated = _obj("already injected", revision="rev-current")
    ledger = {content_fingerprint(repeated.content): _ledger_value("rev-current")}

    plan = build_recall_plan(
        [overlay, repeated],
        current_task_revision="rev-current",
        session_ledger=ledger,
    )

    assert plan["selected_count"] == 0
    assert {item["reason"] for item in plan["suppressed"]} == {"stale_task_revision", "session_duplicate"}


def test_two_owner_confirmed_claims_are_not_silently_decided():
    left = _obj("timezone is UTC", authority="owner_confirmed", claim="profile.timezone", ref="left")
    right = _obj("timezone is Asia Shanghai", authority="owner_confirmed", claim="profile.timezone", ref="right")

    plan = build_recall_plan(
        [left, right],
        mode="apply_canary",
        conflict_resolution_mode="apply_canary",
    )

    assert plan["selected_count"] == 0
    assert plan["conflicts"] == [{
        "claim_key": "profile.timezone",
        "status": "owner_conflict_requires_clarification",
        "source_refs": ["left", "right"],
    }]


def test_owner_conflict_subgate_shadow_reports_without_changing_apply_canary_results():
    left = _obj("timezone is UTC", authority="owner_confirmed", claim="profile.timezone", ref="left")
    right = _obj("timezone is Asia Shanghai", authority="owner_confirmed", claim="profile.timezone", ref="right")

    plan = build_recall_plan(
        [left, right],
        mode="apply_canary",
        conflict_resolution_mode="shadow",
    )

    assert plan["selected_count"] == 2
    assert plan["suppressed"] == []
    assert {
        item["source_ref"]
        for item in plan["shadow_findings"]
        if item["reason"] == "owner_conflict_requires_clarification"
    } == {"left", "right"}
    applied = apply_recall_plan(plan)
    assert {obj.source_ref for obj in applied[RecallType.INDEXED_FTS.value]} == {"left", "right"}


def test_apply_plan_and_session_ledger_are_provider_local_structures():
    obj = _obj("approved canonical memory", recall_type=RecallType.CRYSTALLIZED.value, authority="approved_canonical")
    plan = build_recall_plan([obj], mode="apply_canary", current_task_revision="rev-1")
    applied = apply_recall_plan(plan)
    ledger: dict[str, object] = {}
    record_session_injection(ledger, applied, task_revision="rev-1")

    assert applied[RecallType.CRYSTALLIZED.value][0].content == obj.content
    assert ledger == {content_fingerprint(obj.content): _ledger_value("rev-1")}


def test_recall_plan_binds_a_versioned_authority_freshness_matrix():
    from plugins.memory.memory_os.recall_policy import (
        AUTHORITY_FRESHNESS_MATRIX,
        AUTHORITY_FRESHNESS_MATRIX_DIGEST,
        AUTHORITY_FRESHNESS_MATRIX_VERSION,
        OBSERVATION_WINDOW_ID,
    )

    plan = build_recall_plan([_obj("matrix-bound recall")], mode="shadow")

    assert AUTHORITY_FRESHNESS_MATRIX["ranking_precedence"] == [
        "authority_rank",
        "freshness",
        "relevance_score",
        "stable_input_order",
    ]
    assert plan["authority_freshness_matrix_version"] == AUTHORITY_FRESHNESS_MATRIX_VERSION
    assert plan["authority_freshness_matrix_digest"] == AUTHORITY_FRESHNESS_MATRIX_DIGEST
    assert plan["observation_window_id"] == OBSERVATION_WINDOW_ID


def test_matrix_change_invalidates_old_observation_window():
    from copy import deepcopy

    from plugins.memory.memory_os.recall_policy import (
        AUTHORITY_FRESHNESS_MATRIX,
        AUTHORITY_FRESHNESS_MATRIX_DIGEST,
        AUTHORITY_FRESHNESS_MATRIX_VERSION,
        OBSERVATION_WINDOW_ID,
        authority_freshness_matrix_digest,
        evaluate_observation_window,
    )

    changed_matrix = deepcopy(AUTHORITY_FRESHNESS_MATRIX)
    changed_matrix["authority_rank"]["indexed_derived"] += 1
    old_digest = authority_freshness_matrix_digest(changed_matrix)
    assert old_digest != AUTHORITY_FRESHNESS_MATRIX_DIGEST

    observations = [
        {
            "observation_window_id": f"{AUTHORITY_FRESHNESS_MATRIX_VERSION}:{old_digest}",
            "sample": "old-1",
        },
        {"observation_window_id": OBSERVATION_WINDOW_ID, "sample": "new-1"},
        {"observation_window_id": OBSERVATION_WINDOW_ID, "sample": "new-2"},
    ]
    status = evaluate_observation_window(observations)

    assert status["current_matrix_digest"] == AUTHORITY_FRESHNESS_MATRIX_DIGEST
    assert status["window_reset_required"] is True
    assert status["invalidated_observation_count"] == 1
    assert [row["sample"] for row in status["current_observations"]] == ["new-1", "new-2"]


def test_explicit_recall_escapes_only_query_relevant_objects_from_session_cooldown():
    flask = _obj("Flask deployment boundary", ref="flask")
    flask.metadata["entity_refs"] = ["Flask"]
    postgres = _obj("PostgreSQL deployment boundary", ref="postgres")
    postgres.metadata["entity_refs"] = ["PostgreSQL"]
    ledger = {
        content_fingerprint(flask.content): _ledger_value("rev-current"),
        content_fingerprint(postgres.content): _ledger_value("rev-current"),
    }

    plan = build_recall_plan(
        [flask, postgres],
        current_query="还记得 Flask 的部署边界吗？",
        current_task_revision="rev-current",
        session_ledger=ledger,
    )

    assert [entry["object"]["source_ref"] for entry in plan["selected"]] == ["flask"]
    assert plan["selected"][0]["cooldown_escape_reason"] == "explicit_recall"
    assert plan["suppressed"][0]["source_ref"] == "postgres"
    assert plan["suppressed"][0]["reason"] == "session_duplicate"


def test_explicit_recall_without_entity_refs_requires_full_query_term_coverage():
    flask = _obj("Flask deployment boundary", ref="flask-no-refs")
    postgres = _obj("PostgreSQL deployment boundary", ref="postgres-no-refs")
    ledger = {
        content_fingerprint(flask.content): _ledger_value("rev-current"),
        content_fingerprint(postgres.content): _ledger_value("rev-current"),
    }

    plan = build_recall_plan(
        [flask, postgres],
        current_query="Do you remember Flask deployment boundary?",
        current_task_revision="rev-current",
        session_ledger=ledger,
    )

    assert [entry["object"]["source_ref"] for entry in plan["selected"]] == ["flask-no-refs"]
    assert plan["selected"][0]["cooldown_escape_reason"] == "explicit_recall"
    assert [entry["source_ref"] for entry in plan["suppressed"]] == ["postgres-no-refs"]
    assert plan["suppressed"][0]["reason"] == "session_duplicate"


def test_explicit_recall_without_refs_requires_ascii_and_cjk_topics_to_match():
    target = _obj("Flask 部署边界", ref="mixed-target")
    control = _obj("Flask 数据库备份", ref="mixed-control")
    ledger = {
        content_fingerprint(target.content): _ledger_value("rev-current"),
        content_fingerprint(control.content): _ledger_value("rev-current"),
    }

    plan = build_recall_plan(
        [target, control],
        current_query="还记得 Flask 的部署边界吗？",
        current_task_revision="rev-current",
        session_ledger=ledger,
    )

    assert [entry["object"]["source_ref"] for entry in plan["selected"]] == ["mixed-target"]
    assert [entry["source_ref"] for entry in plan["suppressed"]] == ["mixed-control"]


def test_claim_key_contributes_identity_without_bypassing_topic_coverage():
    target = _obj("数据库备份", ref="claim-target")
    control = _obj("部署边界", ref="claim-control")
    target.claim_key = "Flask"
    control.claim_key = "Flask"
    plan = build_recall_plan(
        [target, control],
        current_query="还记得 Flask 的数据库备份吗？",
        current_task_revision="rev-current",
        session_ledger={
            content_fingerprint(target.content): _ledger_value("rev-current"),
            content_fingerprint(control.content): _ledger_value("rev-current"),
        },
    )

    assert [entry["object"]["source_ref"] for entry in plan["selected"]] == ["claim-target"]
    assert [entry["source_ref"] for entry in plan["suppressed"]] == ["claim-control"]


def test_explicit_recall_preserves_short_ascii_identifiers_in_mixed_queries():
    cases = [
        ("Go", "Rust"),
        ("AI", "ML"),
        ("R", "C"),
        ("IT", "HR"),
        ("US", "EU"),
    ]
    for wanted, other in cases:
        target = _obj(f"{wanted} 部署边界", ref=f"{wanted}-target")
        control = _obj(f"{other} 部署边界", ref=f"{other}-control")
        plan = build_recall_plan(
            [target, control],
            current_query=f"还记得 {wanted} 的部署边界吗？",
            current_task_revision="rev-current",
            session_ledger={
                content_fingerprint(target.content): _ledger_value("rev-current"),
                content_fingerprint(control.content): _ledger_value("rev-current"),
            },
        )

        assert [entry["object"]["source_ref"] for entry in plan["selected"]] == [f"{wanted}-target"]
        assert [entry["source_ref"] for entry in plan["suppressed"]] == [f"{other}-control"]


def test_explicit_recall_ignores_bounded_english_possessive_stopword():
    target = _obj("Flask deployment boundary", ref="our-target")
    plan = build_recall_plan(
        [target],
        current_query="Do you remember our Flask deployment boundary?",
        current_task_revision="rev-current",
        session_ledger={content_fingerprint(target.content): _ledger_value("rev-current")},
    )

    assert plan["selected_count"] == 1
    assert plan["selected"][0]["cooldown_escape_reason"] == "explicit_recall"


def test_current_query_entity_reference_escapes_session_cooldown_for_implicit_continuation():
    repeated = _obj("Flask deployment uses a blue-green boundary", ref="entity")
    repeated.metadata["entity_refs"] = ["Flask"]
    ledger = {content_fingerprint(repeated.content): _ledger_value("rev-current")}

    plan = build_recall_plan(
        [repeated],
        current_query="继续 Flask 部署的下一步",
        current_task_revision="rev-current",
        session_ledger=ledger,
    )

    assert plan["selected_count"] == 1
    assert plan["selected"][0]["cooldown_escape_reason"] == "current_query_entity"


def test_unrelated_implicit_continuation_remains_in_session_cooldown():
    repeated = _obj("Flask deployment uses a blue-green boundary", ref="entity")
    repeated.metadata["entity_refs"] = ["Flask"]
    ledger = {content_fingerprint(repeated.content): _ledger_value("rev-current")}

    plan = build_recall_plan(
        [repeated],
        current_query="继续处理下一步",
        current_task_revision="rev-current",
        session_ledger=ledger,
    )

    assert plan["selected_count"] == 0
    assert plan["suppressed"][0]["reason"] == "session_duplicate"


def test_critical_recall_classes_escape_session_cooldown_only_from_trusted_lanes():
    cases = [
        (RecallType.TEMPORAL.value, "direct_current_task", {"critical_recall_class": "task_boundary"}, "task_boundary"),
        (
            RecallType.CRYSTALLIZED.value,
            "owner_confirmed",
            {"owner_approved_permanent": True, "owner_pinned": True},
            "owner_pin",
        ),
        (
            RecallType.CRYSTALLIZED.value,
            "owner_confirmed",
            {"owner_approved_permanent": True, "safety_rule": True},
            "safety_rule",
        ),
    ]
    for recall_type, authority, metadata, expected_reason in cases:
        repeated = _obj(
            f"critical {expected_reason}",
            recall_type=recall_type,
            authority=authority,
            ref=expected_reason,
        )
        repeated.metadata.update(metadata)
        ledger = {content_fingerprint(repeated.content): _ledger_value("rev-current")}

        plan = build_recall_plan(
            [repeated],
            current_query="继续",
            current_task_revision="rev-current",
            session_ledger=ledger,
        )

        assert plan["selected_count"] == 1
        assert plan["selected"][0]["cooldown_escape_reason"] == expected_reason


def test_untrusted_lane_cannot_spoof_owner_pin_or_safety_rule_escape():
    cases = [
        (RecallType.INDEXED_FTS.value, "indexed_derived", {"owner_pinned": True}),
        (RecallType.INDEXED_FTS.value, "indexed_derived", {"safety_rule": True}),
        (RecallType.INDEXED_FTS.value, "indexed_derived", {"critical_recall_class": "owner_pin"}),
        (RecallType.CRYSTALLIZED.value, "owner_confirmed", {"owner_pinned": True}),
    ]
    for recall_type, authority, metadata in cases:
        spoof = _obj(
            "untrusted claimed critical memory",
            recall_type=recall_type,
            authority=authority,
            ref="spoof",
        )
        spoof.metadata.update(metadata)
        plan = build_recall_plan(
            [spoof],
            current_query="继续",
            current_task_revision="rev-current",
            session_ledger={content_fingerprint(spoof.content): _ledger_value("rev-current")},
        )

        assert plan["selected_count"] == 0
        assert plan["suppressed"][0]["reason"] == "session_duplicate"


def test_entity_escape_uses_fail_closed_boundaries_for_ascii_special_and_cjk_refs():
    cases = [
        ("C++", "C++++ guide", False),
        ("C++", "C++ guide", True),
        ("memory os", "memory oscillator status", False),
        ("memory os", "memory os status", True),
        ("上海", "上海市天气", False),
        ("上海", "继续 上海 的部署", True),
    ]
    for entity_ref, query, should_escape in cases:
        repeated = _obj(f"record for {entity_ref}", ref=entity_ref)
        repeated.metadata["entity_refs"] = [entity_ref]
        plan = build_recall_plan(
            [repeated],
            current_query=query,
            current_task_revision="rev-current",
            session_ledger={content_fingerprint(repeated.content): _ledger_value("rev-current")},
        )

        assert (plan["selected_count"] == 1) is should_escape
        if should_escape:
            assert plan["selected"][0]["cooldown_escape_reason"] == "current_query_entity"
        else:
            assert plan["suppressed"][0]["reason"] == "session_duplicate"


def test_explicit_recall_cannot_override_structured_entity_boundary_mismatch():
    cases = [
        ("C++", "Do you remember C++++ guide?"),
        ("memory os", "Do you remember memory oscillator status?"),
        ("上海", "还记得上海市天气吗？"),
    ]
    for entity_ref, query in cases:
        repeated = _obj(f"record guide status weather for {entity_ref}", ref=entity_ref)
        repeated.metadata["entity_refs"] = [entity_ref]
        plan = build_recall_plan(
            [repeated],
            current_query=query,
            current_task_revision="rev-current",
            session_ledger={content_fingerprint(repeated.content): _ledger_value("rev-current")},
        )

        assert plan["selected_count"] == 0
        assert plan["suppressed"][0]["reason"] == "session_duplicate"


# --- FIX 4: session-ledger dedup key granularity (task_revision + source_rev) ---


def test_source_updated_mid_task_is_not_suppressed_even_with_same_task_revision():
    """Counterfactual for FIX 4: the pre-fix ledger only stored
    task_revision, so a source object edited mid-task (same rendered
    content/fingerprint, newer source_updated_at) was wrongly suppressed
    as a session duplicate. The ledger entry now also carries source_rev,
    and suppression requires BOTH to match."""
    ledger = {
        content_fingerprint("source object body original"): _ledger_value(
            "rev-1", source_rev="2026-07-15T00:00:00Z"
        ),
    }
    updated = _obj("source object body original", ref="src-1")
    updated.metadata["source_updated_at"] = "2026-07-15T01:00:00Z"

    plan = build_recall_plan(
        [updated],
        current_task_revision="rev-1",
        session_ledger=ledger,
    )

    assert plan["selected_count"] == 1
    assert plan["suppressed"] == []


def test_unchanged_task_and_source_rev_still_suppresses_session_duplicate():
    """Regression guard: when BOTH task_revision and source_rev are
    unchanged, session_duplicate suppression must still fire."""
    obj = _obj("stable unchanged source body", ref="src-stable")
    obj.metadata["source_updated_at"] = "2026-07-15T00:00:00Z"
    ledger = {
        content_fingerprint(obj.content): _ledger_value("rev-1", source_rev="2026-07-15T00:00:00Z"),
    }

    plan = build_recall_plan(
        [obj],
        current_task_revision="rev-1",
        session_ledger=ledger,
    )

    assert plan["selected_count"] == 0
    assert plan["suppressed"][0]["reason"] == "session_duplicate"


def test_legacy_string_ledger_entry_is_treated_as_changed_then_upgraded_on_rerecord():
    """Old-format ledger values (plain strings, the pre-FIX-4 shape) must
    be handled gracefully: treated as changed (never suppress), then
    upgraded to the new {task_revision, source_rev} shape the next time
    record_session_injection runs for that fingerprint."""
    obj = _obj("legacy ledger format object", ref="legacy-1")
    legacy_ledger: dict[str, object] = {content_fingerprint(obj.content): "rev-current"}

    plan = build_recall_plan(
        [obj],
        current_task_revision="rev-current",
        session_ledger=legacy_ledger,
    )
    assert plan["selected_count"] == 1
    assert plan["suppressed"] == []

    record_session_injection(
        legacy_ledger,
        {RecallType.INDEXED_FTS.value: [obj]},
        task_revision="rev-current",
    )
    assert legacy_ledger == {content_fingerprint(obj.content): _ledger_value("rev-current")}

    plan_two = build_recall_plan(
        [obj],
        current_task_revision="rev-current",
        session_ledger=legacy_ledger,
    )
    assert plan_two["selected_count"] == 0
    assert plan_two["suppressed"][0]["reason"] == "session_duplicate"


# --- FIX 5: L0 exact source_ref dedup + L4 ambiguity marking ---


def test_l0_exact_source_ref_dedup_runs_across_recall_types_before_near_dup_logic():
    """Counterfactual for FIX 5(a): two entries sharing the identical
    source_ref (surfaced by two different recall_type lanes) with
    DIFFERENT content -- so L1 content-digest dedup would NOT catch this,
    and their jaccard similarity is far below the near-duplicate band, so
    L3 would not catch it either -- must still collapse to one via L0.
    Reverting FIX 5(a) would leave both selected."""
    low = _obj(
        "deployment note early draft",
        recall_type=RecallType.WORKING.value,
        score=0.4,
        ref="shared:1",
    )
    high = _obj(
        "deployment note later revision with more detail",
        recall_type=RecallType.INDEXED_FTS.value,
        score=0.9,
        ref="shared:1",
    )

    plan = build_recall_plan([low, high], budget_chars=10_000)

    assert plan["selected_count"] == 1
    assert plan["selected"][0]["object"]["source_ref"] == "shared:1"
    assert plan["selected"][0]["object"]["score"] == 0.9
    assert {item["reason"] for item in plan["suppressed"]} == {"exact_source_duplicate"}


def test_exact_duplicate_count_combines_l0_source_ref_and_l1_content_digest_dedup():
    """Counting decision for FIX 5: L0 (exact source_ref) and the
    pre-existing L1 (exact content digest) are both deterministic,
    non-fuzzy dedup layers, so both fold into `exact_duplicate_count`.
    recall_policy.append_recall_observation only exposes an exact/near
    split for shadow observability; keeping L0 out of `exact_duplicate_count`
    would under-report deterministic dedup work once L0 starts catching
    cases L1 does not."""
    l0_primary = _obj("l0 primary content", ref="shared:l0", score=0.9)
    l0_dup = _obj("l0 secondary content", ref="shared:l0", score=0.1)
    l1_primary = _obj("repeated content body", ref="l1-a", score=0.9)
    l1_dup = _obj("repeated content body", ref="l1-b", score=0.1)

    plan = build_recall_plan(
        [l0_primary, l0_dup, l1_primary, l1_dup],
        budget_chars=10_000,
    )

    assert plan["exact_duplicate_count"] == 2
    assert plan["selected_count"] == 2
    assert {item["reason"] for item in plan["suppressed"]} == {"exact_source_duplicate", "exact_duplicate"}


def test_l4_ambiguous_pair_neither_suppressed_and_cross_linked_by_fingerprint():
    """Counterfactual for FIX 5(b): pairs with jaccard similarity in
    [0.70, near_duplicate_threshold) must NOT be suppressed -- both survive
    and are cross-linked via `ambiguity_related`, and the plan exposes
    `ambiguous_pair_count`. Reverting FIX 5(b) removes both the field and
    the plan key entirely (KeyError), and the pre-fix code has no
    mechanism to record this relationship at all."""
    left = _obj("alpha beta gamma delta epsilon zeta eta", ref="amb-left")
    right = _obj("alpha beta gamma delta epsilon zeta theta", ref="amb-right")

    # Sanity: confirm the fixture actually lands in the intended [0.70, 0.88) band.
    from plugins.memory.memory_os.recall_arbitration import _token_jaccard
    assert 0.70 <= _token_jaccard(left.content, right.content) < 0.88

    plan = build_recall_plan([left, right], budget_chars=10_000)

    assert plan["ambiguous_pair_count"] == 1
    assert plan["suppressed"] == []
    selected_by_ref = {entry["object"]["source_ref"]: entry for entry in plan["selected"]}
    assert set(selected_by_ref) == {"amb-left", "amb-right"}
    left_fp = content_fingerprint(left.content)
    right_fp = content_fingerprint(right.content)
    assert selected_by_ref["amb-left"]["ambiguity_related"] == [right_fp]
    assert selected_by_ref["amb-right"]["ambiguity_related"] == [left_fp]


# --- Defect 2: substrates-vocabulary authority_class must not silently rank 0 ---


def test_substrate_vocabulary_authority_class_resolves_to_correct_rank_not_zero():
    """Counterfactual for Defect 2: a RecallObject carrying a SUBSTRATES-
    vocabulary authority_class ("local_canonical") -- as would be produced
    by a retriever built on LocalArtifactProvider/GroundingFact -- must be
    ranked using the alias bridge (recall_policy.SUBSTRATE_AUTHORITY_ALIASES),
    not looked up directly against the arbitration vocabulary's
    `authority_rank` table. Before the fix, `_AUTHORITY_RANK.get(authority, 0)`
    had no entry for "local_canonical" and silently fell back to rank 0 --
    the SAME rank as an intentionally-empty authority_class, and BELOW
    "external_unverified" (rank 1). This is a genuinely-authoritative claim
    that must never rank below an unverified external fact.
    """
    from plugins.memory.memory_os.recall_policy import AUTHORITY_FRESHNESS_MATRIX

    local_canonical_via_substrate = _obj(
        "genuinely local canonical fact",
        authority="local_canonical",
        ref="substrate-local",
    )
    external_unverified = _obj(
        "ordinary external unverified fact",
        authority="external_unverified",
        ref="substrate-external",
    )

    plan = build_recall_plan([local_canonical_via_substrate, external_unverified], budget_chars=10_000)

    by_ref = {entry["object"]["source_ref"]: entry for entry in plan["selected"]}
    assert by_ref["substrate-local"]["authority_rank"] > by_ref["substrate-external"]["authority_rank"]
    assert by_ref["substrate-local"]["authority_rank"] == AUTHORITY_FRESHNESS_MATRIX["authority_rank"]["approved_canonical"]
    assert plan["unknown_authority_classes"] == []


def test_unrecognized_authority_class_is_flagged_not_silently_zeroed():
    """Counterfactual for Defect 2: a value that matches NEITHER the
    arbitration vocabulary NOR the substrates-alias bridge must still be
    visible as an anomaly via `unknown_authority_classes`, instead of
    disappearing into an ordinary-looking rank 0. Reverting the
    `resolve_authority_rank` wiring (i.e. going back to a plain
    `_AUTHORITY_RANK.get(authority, 0)`) makes `unknown_authority_classes`
    disappear entirely (KeyError on the plan dict) while the bad value
    still silently ranks at 0."""
    mystery = _obj("value from an unrecognized authority vocabulary", authority="totally_unknown_authority", ref="mystery")

    plan = build_recall_plan([mystery], budget_chars=10_000)

    assert plan["selected"][0]["authority_rank"] == 0
    assert plan["unknown_authority_classes"] == ["totally_unknown_authority"]


def test_apply_recall_plan_ignores_ambiguity_related_and_still_returns_both_objects():
    """`apply_recall_plan` reads only the "object" key of each selected
    entry -- confirm it stays unbroken when entries also carry the new
    `ambiguity_related` sibling key."""
    left = _obj(
        "alpha beta gamma delta epsilon zeta eta",
        ref="amb-left-2",
        recall_type=RecallType.CRYSTALLIZED.value,
        authority="approved_canonical",
    )
    right = _obj(
        "alpha beta gamma delta epsilon zeta theta",
        ref="amb-right-2",
        recall_type=RecallType.CRYSTALLIZED.value,
        authority="approved_canonical",
    )

    plan = build_recall_plan([left, right], mode="apply_canary", budget_chars=10_000)
    assert plan["ambiguous_pair_count"] == 1

    applied = apply_recall_plan(plan)
    refs = {obj.source_ref for obj in applied[RecallType.CRYSTALLIZED.value]}
    assert refs == {"amb-left-2", "amb-right-2"}
