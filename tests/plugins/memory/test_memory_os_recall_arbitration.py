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
