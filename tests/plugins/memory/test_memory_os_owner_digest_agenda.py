"""Owner agenda digest honesty contracts.

Production symptom these cover: the daily agenda reported "需要你决定 25 项;
本条展示 1 项, 未展示 24 项" while the only deliverable item was the single one
shown.  The other 24 were non-promotion Living Memory records that
``_assemble_living_memory_delivery_items`` removes from every delivery render by
design, so they could never appear in that channel — and "下一页" resumed by
*count* into the unfiltered queue, returning an item the Owner had never seen.
"""
from __future__ import annotations

from plugins.memory.memory_os import owner_actions as owner_actions_module
from plugins.memory.memory_os.config import save_config
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore

import pytest

pytestmark = pytest.mark.usefixtures("crystallized_test_write_authority")

CHANNEL = "owner_review_cron"


def _store(tmp_path: object) -> MemoryOSStore:
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="test")
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def _owner_home_config(tmp_path: object) -> None:
    save_config(
        {
            "owner_review": {
                "enabled": True,
                "actions_enabled": True,
                "recurring_delivery_enabled": True,
                "recurring_delivery_mode": "hermes_cron",
                "recurring_delivery_channel": CHANNEL,
                "recurring_delivery_target_class": "owner_home",
            }
        },
        str(tmp_path),
    )


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


def _production_shaped_items() -> list[dict[str, object]]:
    """24 undeliverable provisional records sorting ahead of 1 deliverable item."""
    items: list[dict[str, object]] = [
        _item("provisional_crystallized_record", f"cry_{index:02d}") for index in range(24)
    ]
    items.append(_item("session_mirror_apply", "production_bounded:scope_x"))
    return items


def _fake_queue(items: list[dict[str, object]]) -> dict[str, object]:
    anchored = owner_actions_module._with_anchors(items)
    return {
        "schema_version": "memory-os.owner_review_queue.v0",
        "pending_count": len(anchored),
        "action_required_count": len(anchored),
        "review_suggested_count": 0,
        "fyi_count": 0,
        "overflow_count": 0,
        "review_aging": {},
        "items": anchored,
    }


def _patch_queue(monkeypatch, items: list[dict[str, object]]) -> None:
    monkeypatch.setattr(
        owner_actions_module,
        "owner_review_queue_report",
        lambda *_args, **_kwargs: _fake_queue(items),
    )


def test_agenda_header_counts_only_the_deliverable_population(tmp_path, monkeypatch):
    """Counterfactual: without the fix the header claims 25 decisions / 24 hidden."""
    store = _store(tmp_path)
    _patch_queue(monkeypatch, _production_shaped_items())

    rendered = owner_actions_module.render_owner_review_digest(
        store, channel=CHANNEL, max_action_required=1, digest_mode="agenda"
    )
    text = rendered["text"]

    assert "需要你决定 1 项；本条展示 1 项，未展示 0 项。" in text
    assert "需要你决定 25 项" not in text
    assert "未展示 24 项" not in text


def test_agenda_discloses_the_nondeliverable_provisional_backlog(tmp_path, monkeypatch):
    """The 24 filtered records must be disclosed, not silently dropped."""
    store = _store(tmp_path)
    _patch_queue(monkeypatch, _production_shaped_items())

    rendered = owner_actions_module.render_owner_review_digest(
        store, channel=CHANNEL, max_action_required=1, digest_mode="agenda"
    )

    assert rendered["counts"]["nondeliverable_living_memory_total"] == 24
    assert "另有 24 条临时记忆(provisional)不需要你在这里决定" in rendered["text"]


def test_backlog_disclosure_invites_no_reply_it_cannot_route(tmp_path, monkeypatch):
    """No surface operation returns just the filtered provisional records, so
    the disclosure must not name a reply for them — that would repeat the very
    defect this section fixes (advertising a path that does not reach).
    """
    store = _store(tmp_path)
    _patch_queue(monkeypatch, _production_shaped_items())

    text = owner_actions_module.render_owner_review_digest(
        store, channel=CHANNEL, max_action_required=1, digest_mode="agenda"
    )["text"]

    assert "查看临时记忆" not in text


def test_deliverable_only_agenda_does_not_advertise_a_next_page(tmp_path, monkeypatch):
    """With nothing deliverable withheld, the agenda must not tell the Owner to page."""
    store = _store(tmp_path)
    _patch_queue(monkeypatch, _production_shaped_items())

    rendered = owner_actions_module.render_owner_review_digest(
        store, channel=CHANNEL, max_action_required=1, digest_mode="agenda"
    )

    assert "想继续处理可回复：下一页" not in rendered["text"]


def test_next_page_resumes_by_identity_not_by_shown_count(tmp_path, monkeypatch):
    """Counterfactual: offsetting by action_required_shown skips A1 and never
    reaches the items the delivery filter withheld — the Owner is handed an item
    that was never displayed while the first queue item is silently stepped over.
    """
    store = _store(tmp_path)
    _owner_home_config(tmp_path)
    items = _production_shaped_items()
    _patch_queue(monkeypatch, items)

    rendered = owner_actions_module.render_owner_review_digest(
        store,
        owner_id="owner",
        channel=CHANNEL,
        max_action_required=1,
        digest_mode="agenda",
        record_active=True,
    )
    shown_ids = {
        item["review_item_id"] for item in rendered["sections"]["action_required"]
    }
    assert shown_ids == {"review:session_mirror_apply:production_bounded:scope_x"}

    page = owner_actions_module.owner_review_surface_report(
        store,
        owner_id="owner",
        operation="next_page",
        section="action_required",
        limit=3,
    )
    returned = [item["review_item_id"] for item in page["sections"]["action_required"]]

    # Nothing already displayed may repeat ...
    assert not shown_ids.intersection(returned)
    # ... and nothing undisplayed may be skipped: the first queue item leads.
    assert returned[0] == "review:provisional_crystallized_record:cry_00"


def test_next_page_cursor_lands_just_past_the_last_returned_item(tmp_path, monkeypatch):
    """`next_offsets` is fed back as `offset` on a follow-up `page`, so it must
    not skip an item.  The shown item here is *last* in the queue, which is
    exactly where `start + len(selected)` goes wrong.
    """
    store = _store(tmp_path)
    _owner_home_config(tmp_path)
    _patch_queue(monkeypatch, _production_shaped_items())

    owner_actions_module.render_owner_review_digest(
        store,
        owner_id="owner",
        channel=CHANNEL,
        max_action_required=1,
        digest_mode="agenda",
        record_active=True,
    )
    page = owner_actions_module.owner_review_surface_report(
        store, owner_id="owner", operation="next_page", section="action_required", limit=3
    )
    returned = [item["target_id"] for item in page["sections"]["action_required"]]
    assert returned == ["cry_00", "cry_01", "cry_02"]

    # Resuming at the advertised cursor must continue at cry_03, not cry_04.
    following = owner_actions_module.owner_review_surface_report(
        store,
        owner_id="owner",
        operation="page",
        section="action_required",
        offset=page["next_offsets"]["action_required"],
        limit=1,
    )
    assert [item["target_id"] for item in following["sections"]["action_required"]] == ["cry_03"]


def test_next_page_falls_back_to_offsets_without_recorded_identities(tmp_path, monkeypatch):
    """Legacy digests carry no review_item_id; the count path must still work."""
    store = _store(tmp_path)
    _patch_queue(monkeypatch, _production_shaped_items())

    page = owner_actions_module.owner_review_surface_report(
        store,
        owner_id="owner",
        operation="next_page",
        section="action_required",
        limit=3,
    )

    assert page["status"] == "ok"
    assert len(page["sections"]["action_required"]) == 3


class _FakeSessionMirror:
    def __init__(self, store: object) -> None:
        self._store = store

    def scan(self, *, dry_run: bool = True, max_sessions: int = 1) -> dict[str, object]:
        return {
            "selected_sessions": [
                {
                    "fingerprint": "smfp_abc123",
                    "platform": "telegram",
                    "source_kind": "chat",
                    "source_group_id": "sess_1",
                    "summary": "讨论了 Memory-OS 审批摘要的可读性问题",
                    "message_count": 42,
                    "tool_count": 3,
                    "raw_private_body_printed": False,
                    "secret_redaction_applied": True,
                }
            ]
        }


def _session_mirror_item(tmp_path, monkeypatch) -> dict[str, object]:
    from plugins.memory.memory_os import session_mirror as session_mirror_module

    monkeypatch.setattr(session_mirror_module, "SessionMirror", _FakeSessionMirror)
    items = owner_actions_module._session_mirror_apply_review_items(_store(tmp_path), set())
    assert len(items) == 1
    return items[0]


def test_session_mirror_item_describes_the_session_not_the_fingerprint(tmp_path, monkeypatch):
    """Counterfactual: the Owner previously saw only 'fingerprint=smfp_...',
    which is not a decision anybody can make."""
    item = _session_mirror_item(tmp_path, monkeypatch)

    assert "telegram" in item["summary"]
    assert "42 条消息" in item["summary"]
    assert "3 次工具调用" in item["summary"]
    assert "讨论了 Memory-OS 审批摘要的可读性问题" in item["summary"]
    assert "fingerprint=" not in item["summary"]


def test_session_preview_survives_the_bounded_digest_copy(tmp_path, monkeypatch):
    """_digest_item() drops any field it does not name; the rendered 原因 line
    falls back to the fingerprint wording if the preview is lost in transit."""
    item = _session_mirror_item(tmp_path, monkeypatch)

    bounded = owner_actions_module._digest_item(item)
    assert bounded["pending_session_preview"]

    rendered = owner_actions_module._render_review_item(bounded, section="action_required")
    assert "42 条消息" in rendered["question"]
    assert "42 条消息" in rendered["reason"]
    assert "fingerprint=" not in rendered["reason"]


def test_session_mirror_item_offers_no_action_it_cannot_honour(tmp_path, monkeypatch):
    """reject_session_mirror_apply does not exist; the digest must not imply it."""
    item = _session_mirror_item(tmp_path, monkeypatch)
    rendered = owner_actions_module._render_review_item(
        owner_actions_module._digest_item(item), section="action_required"
    )

    assert set(rendered["action_tokens"]) == {"approve_session_mirror_apply"}
