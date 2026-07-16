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
    ledger = {content_fingerprint(repeated.content): "rev-current"}

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
    ledger: dict[str, str] = {}
    record_session_injection(ledger, applied, task_revision="rev-1")

    assert applied[RecallType.CRYSTALLIZED.value][0].content == obj.content
    assert ledger == {content_fingerprint(obj.content): "rev-1"}


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
        content_fingerprint(flask.content): "rev-current",
        content_fingerprint(postgres.content): "rev-current",
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
        content_fingerprint(flask.content): "rev-current",
        content_fingerprint(postgres.content): "rev-current",
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
        content_fingerprint(target.content): "rev-current",
        content_fingerprint(control.content): "rev-current",
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
            content_fingerprint(target.content): "rev-current",
            content_fingerprint(control.content): "rev-current",
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
                content_fingerprint(target.content): "rev-current",
                content_fingerprint(control.content): "rev-current",
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
        session_ledger={content_fingerprint(target.content): "rev-current"},
    )

    assert plan["selected_count"] == 1
    assert plan["selected"][0]["cooldown_escape_reason"] == "explicit_recall"


def test_current_query_entity_reference_escapes_session_cooldown_for_implicit_continuation():
    repeated = _obj("Flask deployment uses a blue-green boundary", ref="entity")
    repeated.metadata["entity_refs"] = ["Flask"]
    ledger = {content_fingerprint(repeated.content): "rev-current"}

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
    ledger = {content_fingerprint(repeated.content): "rev-current"}

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
        ledger = {content_fingerprint(repeated.content): "rev-current"}

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
            session_ledger={content_fingerprint(spoof.content): "rev-current"},
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
            session_ledger={content_fingerprint(repeated.content): "rev-current"},
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
            session_ledger={content_fingerprint(repeated.content): "rev-current"},
        )

        assert plan["selected_count"] == 0
        assert plan["suppressed"][0]["reason"] == "session_duplicate"
