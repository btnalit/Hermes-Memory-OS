"""Living Memory V2-0 delivery-boundary contract tests."""
from __future__ import annotations

from plugins.memory.memory_os import owner_actions as owner_actions_module
from plugins.memory.memory_os.crystallized import CrystallizedCandidate, CrystallizedMemoryService
from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore


def _store(tmp_path: object) -> MemoryOSStore:
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="test")
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def _item(target_type: str, target_id: str) -> dict[str, object]:
    return {
        "schema_version": "memory-os.review_item.v0",
        "review_item_id": f"review:{target_type}:{target_id}",
        "target_type": target_type,
        "target_id": target_id,
        "priority": "action_required",
        "created_at": "2026-07-10T00:00:00Z",
        "summary": "safe summary",
        "raw_body_included": False,
    }


def _fake_queue(items: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": "memory-os.owner_review_queue.v0",
        "pending_count": len(items),
        "action_required_count": len(items),
        "review_suggested_count": 0,
        "fyi_count": 0,
        "overflow_count": 0,
        "review_aging": {},
        "items": items,
    }


def test_living_memory_choke_point_filters_nonpromotion_but_keeps_other_systems():
    items = [
        _item("candidate_cluster", "cluster_1"),
        _item("crystallized_record", "cry_1"),
        _item("provisional_crystallized_record", "cry_2"),
        _item("permanent_memory_promotion", "ppm_1"),
        _item("speak_permission", "speak_1"),
        _item("knob_override", "knob_1"),
    ]

    delivery_items, diagnostics = owner_actions_module._assemble_living_memory_delivery_items(items)

    assert [item["target_type"] for item in delivery_items] == [
        "candidate_cluster", "permanent_memory_promotion", "speak_permission", "knob_override"
    ]
    assert diagnostics["living_memory_nonpromotion_filtered_count"] == 2
    assert diagnostics["permanent_promotion_review_item_count"] == 1


def test_queue_preserves_provisional_visibility_and_marks_delivery_ineligible(tmp_path):
    store = _store(tmp_path)
    service = CrystallizedMemoryService(store)
    candidate = CrystallizedCandidate("cand_1", "fact", "Stable provisional fact", ["evt_1"])
    decision = ApprovalDecision(
        "cand_1", ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED, "resolver",
        "2026-07-10T00:00:00Z", provisional=True, expires_at="2026-08-01T00:00:00Z",
    )
    service.write_approved_record(candidate, decision, file_name="owner_approved.md")

    queue = owner_actions_module.owner_review_queue_report(store, limit=20)

    provisional = next(item for item in queue["items"] if item["target_type"] == "provisional_crystallized_record")
    assert provisional["delivery_eligible"] is False


def test_digest_delivery_filters_every_nonpromotion_living_memory_target(tmp_path, monkeypatch):
    store = _store(tmp_path)
    items = [
        _item("provisional_crystallized_record", "cry_1"),
        _item("candidate_cluster", "cluster_1"),
        _item("permanent_memory_promotion", "ppm_1"),
        _item("speak_permission", "speak_1"),
    ]
    monkeypatch.setattr(owner_actions_module, "owner_review_queue_report", lambda *_args, **_kwargs: _fake_queue(items))

    preview = owner_actions_module.owner_review_digest_preview(store, max_action_required=10)
    target_types = [item["target_type"] for item in preview["sections"]["action_required"]]

    assert target_types == ["candidate_cluster", "permanent_memory_promotion", "speak_permission"]
    assert preview["delivery_diagnostics"]["living_memory_nonpromotion_filtered_count"] == 1


def test_digest_has_no_expiring_provisional_delivery_or_legacy_expiry_tokens(tmp_path):
    store = _store(tmp_path)
    rendered = owner_actions_module.render_owner_review_digest(store)

    assert "即将过期的 Provisional" not in rendered["text"]
    assert "oa_confirm_" not in rendered["text"]
    assert "oa_let_expire_" not in rendered["text"]
    assert not hasattr(owner_actions_module, "_render_expiring_provisional_section")


def test_legacy_expiry_tokens_are_not_a_direct_permanent_write_route(tmp_path):
    store = _store(tmp_path)

    result = owner_actions_module.parse_owner_review_reply(
        store, "memory approve oa_confirm_cry_1", owner_id="owner", channel="cli", apply=True
    )

    assert result["status"] in {"needs_clarification", "unsupported", "error"}
    assert result.get("reason") != ""
