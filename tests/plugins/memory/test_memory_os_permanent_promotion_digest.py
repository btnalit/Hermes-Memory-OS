"""V2-0.5 permanent-promotion producer and fair-delivery counterfactuals."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


def test_real_production_migration_fixture_is_desensitised_and_non_mutating():
    import json

    fixture = (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "fixtures"
        / "living_memory_v2_0_5"
        / "production_migration_dry_run_2026-07-10.json"
    )
    report = json.loads(fixture.read_text(encoding="utf-8"))

    assert report["source_kind"] == "real_production_dry_run"
    assert report["desensitised"] is True
    assert report["production_store_unchanged"] is True
    assert report["result"]["dry_run"] is True
    assert report["result"]["promoted_count"] == 0
    assert report["result"]["error_records"] == []
    assert report["runtime_module"].startswith("<HERMES_HOME>/")


def _store(tmp_path):
    from plugins.memory.memory_os.roots import MemoryOSRoots
    from plugins.memory.memory_os.store import MemoryOSStore

    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="test"))
    store.initialize()
    return store


def _automatic_context(store, scope):
    from plugins.memory.memory_os.execution_gate import execution_gate_scope_hash, start_execution_gate_envelope
    from plugins.memory.memory_os.permanent_promotion import AutomaticWriteContext

    permit = start_execution_gate_envelope(
        store,
        lane_id="permanent_promotion_producer",
        trigger_surface="test",
        risk_class="bounded_reversible_queue",
        human_approval_required=False,
        why_no_human_approval="test automatic proposal queue bookkeeping",
        scope=scope,
        boundary={
            "actual_send": False,
            "actual_unapproved_crystallized_approval": False,
            "automatic_permanent_promotion": False,
        },
    )
    return AutomaticWriteContext(
        store=store,
        envelope_id=permit["execution_gate_envelope_id"],
        scope_hash=execution_gate_scope_hash(scope),
    )


def _proposal_batch(store, *, count, now):
    from plugins.memory.memory_os.permanent_promotion import ProposalLedger

    ledger = ProposalLedger(store.roots.memory_os_root, clock=lambda: now)
    proposals = []
    for index in range(count):
        proposal, _ = ledger.create_or_get(
            target_id=f"cry_{index:02d}",
            candidate_id=f"cand_{index:02d}",
            body=f"durable body {index:02d}",
            channel="cli",
        )
        proposals.append(proposal)
    return proposals


def _add_aged_provisional(store, *, candidate_id, body, now):
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
    from plugins.memory.memory_os.crystallized import CrystallizedCandidate, CrystallizedMemoryService

    candidate = CrystallizedCandidate(candidate_id, "fact", body, [f"evt_{candidate_id}"])
    decision = ApprovalDecision(
        candidate_id,
        ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        "resolver",
        (now - timedelta(days=10)).isoformat(),
        provisional=True,
        expires_at=(now + timedelta(days=30)).isoformat(),
    )
    service = CrystallizedMemoryService(store)
    service.write_approved_record(candidate, decision, file_name="owner_approved.md", now=now - timedelta(days=10))
    return service.read_records("owner_approved.md")[-1].frontmatter["id"]


def test_fair_queue_surfaces_never_delivered_items_before_non_due_reminders(tmp_path):
    from plugins.memory.memory_os.permanent_promotion import PermanentPromotionDeliveryLedger

    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    store = _store(tmp_path)
    proposals = _proposal_batch(store, count=8, now=now)
    ledger = PermanentPromotionDeliveryLedger(store.roots.memory_os_root, clock=lambda: now)

    first = ledger.select_due(proposals, now=now, cap=5, new_reserve=3, reminder_reserve=2)
    assert [item["target_id"] for item in first["selected"]] == [f"cry_{index:02d}" for index in range(5)]

    scope = {"operation": "test_delivery_ack", "delivery_id": "odig_first"}
    ledger.acknowledge(
        [item["proposal_id"] for item in first["selected"]],
        owner_digest_delivery_id="odig_first",
        ack_source="hermes_send_receipt",
        delivery_receipt_id="msg-first",
        digest_id="digest-first",
        now=now,
        write_context=_automatic_context(store, scope),
    )

    second = ledger.select_due(
        proposals,
        now=now + timedelta(days=1),
        cap=5,
        new_reserve=3,
        reminder_reserve=2,
    )
    assert [item["target_id"] for item in second["selected"]] == ["cry_05", "cry_06", "cry_07"]
    assert second["due_reminder_count"] == 0


def test_fair_queue_never_exceeds_cap_when_reserves_exceed_cap(tmp_path):
    from plugins.memory.memory_os.permanent_promotion import PermanentPromotionDeliveryLedger

    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    store = _store(tmp_path)
    proposals = _proposal_batch(store, count=8, now=now)
    ledger = PermanentPromotionDeliveryLedger(store.roots.memory_os_root, clock=lambda: now)
    scope = {"operation": "test_small_cap_delivery_ack", "delivery_id": "odig_small_cap"}
    ledger.acknowledge(
        [proposal["proposal_id"] for proposal in proposals[:2]],
        owner_digest_delivery_id="odig_small_cap",
        ack_source="hermes_send_receipt",
        delivery_receipt_id="msg-small-cap",
        digest_id="digest-small-cap",
        now=now - timedelta(days=4),
        write_context=_automatic_context(store, scope),
    )

    selected = ledger.select_due(
        proposals,
        now=now,
        cap=3,
        new_reserve=3,
        reminder_reserve=2,
    )

    assert len(selected["selected"]) == 3
    assert selected["selected_new_count"] == 2
    assert selected["selected_reminder_count"] == 1


@pytest.mark.parametrize(
    ("cap", "new_reserve", "reminder_reserve"),
    [(0, 3, 2), (1, 3, 2), (2, 9, 9), (3, 0, 8), (4, 8, 0), (5, 20, 20)],
)
def test_fair_queue_reserve_combinations_never_break_owner_cap(
    tmp_path,
    cap,
    new_reserve,
    reminder_reserve,
):
    from plugins.memory.memory_os.permanent_promotion import PermanentPromotionDeliveryLedger

    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    store = _store(tmp_path)
    proposals = _proposal_batch(store, count=10, now=now)
    selected = PermanentPromotionDeliveryLedger(
        store.roots.memory_os_root,
        clock=lambda: now,
    ).select_due(
        proposals,
        now=now,
        cap=cap,
        new_reserve=new_reserve,
        reminder_reserve=reminder_reserve,
    )

    assert len(selected["selected"]) <= cap


def test_delivery_ack_is_idempotent_for_same_digest_and_proposal(tmp_path):
    from plugins.memory.memory_os.permanent_promotion import PermanentPromotionDeliveryLedger

    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    store = _store(tmp_path)
    proposal = _proposal_batch(store, count=1, now=now)[0]
    ledger = PermanentPromotionDeliveryLedger(store.roots.memory_os_root, clock=lambda: now)
    scope = {"operation": "test_delivery_ack", "delivery_id": "odig_same"}
    context = _automatic_context(store, scope)

    first = ledger.acknowledge(
        [proposal["proposal_id"]],
        owner_digest_delivery_id="odig_same",
        ack_source="hermes_send_receipt",
        delivery_receipt_id="msg-same",
        digest_id="digest-same",
        now=now,
        write_context=context,
    )
    second = ledger.acknowledge(
        [proposal["proposal_id"]],
        owner_digest_delivery_id="odig_same",
        ack_source="hermes_send_receipt",
        delivery_receipt_id="msg-same",
        digest_id="digest-same",
        now=now,
        write_context=context,
    )

    assert first["acknowledged_count"] == 1
    assert second["acknowledged_count"] == 0
    assert second["duplicate_delivery_suppressed_count"] == 1
    assert ledger.states()[proposal["proposal_id"]]["delivery_count"] == 1


def test_automatic_rejected_content_does_not_reopen_and_body_drift_revokes_old(tmp_path):
    from plugins.memory.memory_os.permanent_promotion import PermanentPromotionError, ProposalLedger

    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    store = _store(tmp_path)
    ledger = ProposalLedger(store.roots.memory_os_root, clock=lambda: now)
    scope = {"operation": "test_auto_proposal", "delivery_id": "odig_rules"}
    context = _automatic_context(store, scope)

    first, _ = ledger.create_or_get(
        target_id="cry_rule",
        candidate_id="cand_rule",
        body="original durable body",
        channel="owner_digest",
        origin="automatic",
        write_context=context,
    )
    ledger.append_terminal(first["proposal_id"], "rejected")
    with pytest.raises(PermanentPromotionError, match="automatic_reproposal_rejected"):
        ledger.create_or_get(
            target_id="cry_rule",
            candidate_id="cand_rule",
            body="original durable body",
            channel="owner_digest",
            origin="automatic",
            write_context=context,
        )

    second, _ = ledger.create_or_get(
        target_id="cry_drift",
        candidate_id="cand_drift",
        body="before drift",
        channel="owner_digest",
        origin="automatic",
        write_context=context,
    )
    replacement, created = ledger.create_or_get(
        target_id="cry_drift",
        candidate_id="cand_drift",
        body="after drift",
        channel="owner_digest",
        origin="automatic",
        write_context=context,
    )

    states = ledger._states()
    assert created is True
    assert states[second["proposal_id"]]["status"] == "revoked"
    assert states[second["proposal_id"]]["reason"] == "content_drift"
    assert replacement["proposal_id"] != second["proposal_id"]


def test_producer_treats_owner_rejected_content_as_stable_skip_not_error(tmp_path):
    from plugins.memory.memory_os.permanent_promotion import (
        PermanentPromotionService,
        prepare_permanent_promotion_delivery,
    )

    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    store = _store(tmp_path)
    _add_aged_provisional(store, candidate_id="cand_rejected_skip", body="Durable rejected fact.", now=now)
    first = prepare_permanent_promotion_delivery(store, delivery_ref="odig_rejected_1", now=now)
    PermanentPromotionService(store, clock=lambda: now).reject(first["items"][0]["action_token"])

    second = prepare_permanent_promotion_delivery(store, delivery_ref="odig_rejected_2", now=now)

    assert second["status"] == "ok"
    assert second["proposal_skipped_count"] == 1
    assert second["error_records"] == []
    assert second["items"] == []


def test_v2e_flag_rejects_automatic_proposal_without_clear_receipt(tmp_path):
    from plugins.memory.memory_os.permanent_promotion import PermanentPromotionError, ProposalLedger

    store = _store(tmp_path)
    scope = {"operation": "test_v2e", "delivery_id": "odig_v2e"}
    with pytest.raises(PermanentPromotionError, match="automatic_clearance_required"):
        ProposalLedger(store.roots.memory_os_root).create_or_get(
            target_id="cry_v2e",
            candidate_id="cand_v2e",
            body="durable body",
            channel="owner_digest",
            origin="automatic",
            v2e_enabled=True,
            write_context=_automatic_context(store, scope),
        )


def test_producer_creates_only_permanent_review_items_and_never_confirms(tmp_path):
    from plugins.memory.memory_os.permanent_promotion import prepare_permanent_promotion_delivery

    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    store = _store(tmp_path)
    record_ids = [
        _add_aged_provisional(store, candidate_id=f"cand_{index}", body=f"Durable fact {index}.", now=now)
        for index in range(7)
    ]

    report = prepare_permanent_promotion_delivery(
        store,
        delivery_ref="odig_prepare",
        now=now,
        cap=5,
    )

    assert report["status"] == "ok"
    assert len(report["items"]) == 5
    assert {item["target_type"] for item in report["items"]} == {"permanent_memory_promotion"}
    assert all(item["action_token"].startswith("ppmt_") for item in report["items"])
    assert report["open_proposal_backlog_count"] == 7
    assert report["never_delivered_open_count"] == 7
    from plugins.memory.memory_os.crystallized import CrystallizedMemoryService

    service = CrystallizedMemoryService(store)
    assert all(service.find_record(record_id).frontmatter["provisional"] is True for record_id in record_ids)
    assert report["automatic_permanent_promotion_count"] == 0


def test_permanent_items_render_with_raw_token_only_in_ephemeral_delivery(tmp_path):
    from plugins.memory.memory_os.owner_actions import (
        owner_review_rendered_digests_path,
        render_owner_review_digest,
    )
    from plugins.memory.memory_os.permanent_promotion import prepare_permanent_promotion_delivery

    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    store = _store(tmp_path)
    _add_aged_provisional(store, candidate_id="cand_render", body="Durable owner preference.", now=now)
    prepared = prepare_permanent_promotion_delivery(store, delivery_ref="odig_render", now=now)
    token = prepared["items"][0]["action_token"]

    rendered = render_owner_review_digest(
        store,
        permanent_promotion_items=prepared["items"],
        max_action_required=5,
        max_review_suggested=0,
        max_fyi=0,
        record_active=True,
    )

    assert token in rendered["text"]
    item = next(
        value for value in rendered["sections"]["action_required"]
        if value["target_type"] == "permanent_memory_promotion"
    )
    assert set(item["action_tokens"]) == {
        "approve_permanent_promotion",
        "reject_permanent_promotion",
        "defer_permanent_promotion",
    }
    persisted = owner_review_rendered_digests_path(store.roots).read_text(encoding="utf-8")
    assert token not in persisted
    assert "ppmt_[redacted]" in persisted


def test_ppmt_owner_reply_uses_same_host_ingress_and_preserves_token_case(tmp_path):
    import json

    from plugins.memory.memory_os.crystallized import CrystallizedMemoryService
    from plugins.memory.memory_os.owner_actions import parse_owner_review_reply, read_owner_action_records
    from plugins.memory.memory_os.permanent_promotion import prepare_permanent_promotion_delivery

    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    store = _store(tmp_path)
    record_id = _add_aged_provisional(
        store,
        candidate_id="cand_reply",
        body="Owner likes concise technical summaries.",
        now=now,
    )
    prepared = prepare_permanent_promotion_delivery(store, delivery_ref="odig_reply", now=now)
    token = prepared["items"][0]["action_token"]
    assert any(char.isupper() for char in token.removeprefix("ppmt_"))

    dry_run = parse_owner_review_reply(
        store,
        f"memory approve {token}",
        owner_id="owner",
        channel="telegram",
        apply=False,
        require_recorded_digest=True,
    )
    assert dry_run["status"] == "ok"
    assert dry_run["dry_run"] is True
    assert token not in json.dumps(dry_run, ensure_ascii=False)
    assert CrystallizedMemoryService(store).find_record(record_id).frontmatter["provisional"] is True

    applied = parse_owner_review_reply(
        store,
        f"memory approve {token}",
        owner_id="owner",
        channel="telegram",
        apply=True,
        require_recorded_digest=True,
    )
    assert applied["status"] == "ok"
    assert applied["owner_action_result"]["status"] == "approved"
    assert token not in json.dumps(applied, ensure_ascii=False)
    assert CrystallizedMemoryService(store).find_record(record_id).frontmatter["provisional"] is False
    owner_actions = read_owner_action_records(store.roots)
    assert len(owner_actions) == 1
    assert owner_actions[0]["action_type"] == "approve_permanent_promotion"
    assert owner_actions[0]["target_type"] == "permanent_memory_promotion"
    assert token not in json.dumps(owner_actions, ensure_ascii=False)


def test_recurring_render_does_not_ack_before_host_delivery_receipt(tmp_path):
    from plugins.memory.memory_os.owner_actions import render_owner_review_delivery_digest
    from plugins.memory.memory_os.permanent_promotion import PermanentPromotionDeliveryLedger

    now = datetime.now(timezone.utc)
    store = _store(tmp_path)
    for index in range(7):
        _add_aged_provisional(
            store,
            candidate_id=f"cand_recurring_{index}",
            body=f"Durable recurring fact {index}.",
            now=now,
        )

    rendered = render_owner_review_delivery_digest(
        store,
        owner_id="owner",
        channel="telegram",
        delivery_ref="cron_delivery_1",
        max_action_required=3,
        max_review_suggested=0,
        max_fyi=0,
        digest_mode="agenda",
    )

    delivery = rendered["permanent_promotion_delivery"]
    assert len(delivery["shown_proposal_ids"]) == 3
    assert delivery["ack"]["status"] == "pending_host_receipt"
    assert delivery["ack"]["acknowledged_count"] == 0
    states = PermanentPromotionDeliveryLedger(store.roots.memory_os_root).states()
    assert states == {}


def test_delivery_ack_requires_persisted_digest_claim(tmp_path):
    from plugins.memory.memory_os.owner_actions import (
        acknowledge_owner_review_delivery_receipt,
        render_owner_review_delivery_digest,
    )
    from plugins.memory.memory_os.permanent_promotion import PermanentPromotionDeliveryLedger

    store = _store(tmp_path)
    now = datetime.now(timezone.utc)
    _add_aged_provisional(
        store,
        candidate_id="cand_bound_receipt",
        body="Durable claim-bound receipt fact.",
        now=now,
    )
    rendered = render_owner_review_delivery_digest(
        store,
        owner_id="owner",
        channel="telegram",
        delivery_ref="cron_delivery_bound",
        max_action_required=5,
        max_review_suggested=0,
        max_fyi=0,
        digest_mode="agenda",
    )
    with pytest.raises(ValueError, match="status_not_success"):
        acknowledge_owner_review_delivery_receipt(
            store,
            delivery_ref="cron_delivery_bound",
            digest_id=str(rendered["digest_id"]),
            receipt_id="msg-failed",
            receipt_status="failed",
        )
    with pytest.raises(ValueError, match="host_delivery_claim_not_found"):
        acknowledge_owner_review_delivery_receipt(
            store,
            delivery_ref="not-a-real-delivery",
            digest_id=str(rendered["digest_id"]),
            receipt_id="fake",
            receipt_status="sent",
        )
    acknowledged = acknowledge_owner_review_delivery_receipt(
        store,
        delivery_ref="cron_delivery_bound",
        digest_id=str(rendered["digest_id"]),
        receipt_id="msg-bound",
        receipt_status="delivered",
        now=now,
    )
    assert acknowledged["acknowledged_count"] == 1
    state = next(iter(PermanentPromotionDeliveryLedger(store.roots.memory_os_root).states().values()))
    assert state["delivery_receipt_id"] == "msg-bound"
    assert state["digest_id"] == rendered["digest_id"]
    next_render = render_owner_review_delivery_digest(
        store,
        owner_id="owner",
        channel="telegram",
        delivery_ref="cron_delivery_next",
        max_action_required=5,
        max_review_suggested=0,
        max_fyi=0,
        digest_mode="agenda",
    )
    assert next_render["permanent_promotion_delivery"]["shown_proposal_ids"] == []


def test_low_level_delivery_ack_rejects_unverified_dict(tmp_path):
    from plugins.memory.memory_os.permanent_promotion import (
        PermanentPromotionError,
        acknowledge_permanent_promotion_delivery,
    )

    store = _store(tmp_path)
    with pytest.raises(PermanentPromotionError, match="verified_delivery_receipt_required"):
        acknowledge_permanent_promotion_delivery(
            store,
            verified_receipt={"id": "fake"},
        )


def test_one_shot_dry_run_with_eligible_permanent_item_writes_nothing(tmp_path):
    from plugins.memory.memory_os.config import save_config
    from plugins.memory.memory_os.owner_actions import deliver_owner_review_digest_once

    now = datetime.now(timezone.utc)
    store = _store(tmp_path)
    _add_aged_provisional(
        store,
        candidate_id="cand_dry_run_no_write",
        body="Durable dry-run fact.",
        now=now,
    )
    save_config(
        {
            "owner_review": {
                "enabled": True,
                "owner_id": "owner",
                "channel": "telegram",
                "target_ref": "telegram:12345",
                "direct_message": True,
                "delivery_enabled": True,
                "delivery_adapter": "hermes_owner_channel",
            }
        },
        tmp_path,
    )
    files_before = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    result = deliver_owner_review_digest_once(
        store,
        owner_id="owner",
        delivery_key="eligible_dry_run_no_write",
        owner_triggered=True,
        apply=False,
    )

    files_after = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert result["status"] == "ready"
    assert result["dry_run"] is True
    assert result["record"]["digest"]["counts"]["action_required_shown"] == 1
    assert result["record"]["permanent_promotion_preassembly_status"] == "preview"
    assert result["record"]["permanent_promotion_proposal_ids"]
    assert files_after == files_before


def test_failed_one_shot_send_does_not_ack_permanent_delivery(tmp_path, monkeypatch):
    from plugins.memory.memory_os.config import save_config
    from plugins.memory.memory_os.owner_actions import deliver_owner_review_digest_once
    from plugins.memory.memory_os.permanent_promotion import PermanentPromotionDeliveryLedger
    import plugins.memory.memory_os.owner_actions as owner_actions_module

    now = datetime.now(timezone.utc)
    store = _store(tmp_path)
    _add_aged_provisional(store, candidate_id="cand_send_fail", body="Durable failed-send fact.", now=now)
    save_config(
        {
            "owner_review": {
                "enabled": True,
                "owner_id": "owner",
                "channel": "telegram",
                "target_ref": "telegram:12345",
                "direct_message": True,
                "delivery_enabled": True,
                "delivery_adapter": "hermes_owner_channel",
            }
        },
        tmp_path,
    )
    send_results = [
        {"ok": False, "code": "hermes_send_failed", "delivery_ref": {}},
        {"ok": True, "delivery_ref": {"message_id": "msg-retry-ok"}},
    ]
    monkeypatch.setattr(
        owner_actions_module,
        "_send_owner_review_digest_via_hermes",
        lambda **_kwargs: send_results.pop(0),
    )

    result = deliver_owner_review_digest_once(
        store,
        owner_id="owner",
        delivery_key="send_fail_no_ack",
        owner_triggered=True,
        apply=True,
    )

    assert result["status"] == "error"
    assert result["permanent_promotion_delivery_ack"] == {}
    assert PermanentPromotionDeliveryLedger(store.roots.memory_os_root).states() == {}

    retry = deliver_owner_review_digest_once(
        store,
        owner_id="owner",
        delivery_key="send_fail_no_ack",
        owner_triggered=True,
        apply=True,
    )
    assert retry["status"] == "sent"
    assert retry["record"]["retry_of_delivery_id"] == result["record"]["delivery_id"]
    assert retry["permanent_promotion_delivery_ack"]["acknowledged_count"] == 1
    assert len(PermanentPromotionDeliveryLedger(store.roots.memory_os_root).states()) == 1


def test_receiptless_one_shot_success_does_not_advance_reminder_state(tmp_path, monkeypatch):
    from plugins.memory.memory_os.config import save_config
    from plugins.memory.memory_os.owner_actions import deliver_owner_review_digest_once
    from plugins.memory.memory_os.permanent_promotion import PermanentPromotionDeliveryLedger
    import plugins.memory.memory_os.owner_actions as owner_actions_module

    now = datetime.now(timezone.utc)
    store = _store(tmp_path)
    _add_aged_provisional(
        store,
        candidate_id="cand_receiptless_send",
        body="Durable receiptless-send fact.",
        now=now,
    )
    save_config(
        {
            "owner_review": {
                "enabled": True,
                "owner_id": "owner",
                "channel": "telegram",
                "target_ref": "telegram:12345",
                "direct_message": True,
                "delivery_enabled": True,
                "delivery_adapter": "hermes_owner_channel",
            }
        },
        tmp_path,
    )
    monkeypatch.setattr(
        owner_actions_module,
        "_send_owner_review_digest_via_hermes",
        lambda **_kwargs: {"ok": True, "delivery_ref": {"status": "ok"}},
    )

    result = deliver_owner_review_digest_once(
        store,
        owner_id="owner",
        delivery_key="receiptless_send_no_ack",
        owner_triggered=True,
        apply=True,
    )

    assert result["status"] == "sent"
    assert result["permanent_promotion_delivery_ack"]["status"] == "pending_host_receipt"
    assert result["permanent_promotion_delivery_ack"]["acknowledged_count"] == 0
    assert PermanentPromotionDeliveryLedger(store.roots.memory_os_root).states() == {}


def test_successful_one_shot_send_and_duplicate_replay_ack_exactly_once(tmp_path, monkeypatch):
    import re
    from plugins.memory.memory_os.config import save_config
    from plugins.memory.memory_os.crystallized import CrystallizedMemoryService
    from plugins.memory.memory_os.owner_actions import (
        deliver_owner_review_digest_once,
        owner_review_deliveries_path,
        owner_review_rendered_digests_path,
    )
    from plugins.memory.memory_os.permanent_promotion import PermanentPromotionDeliveryLedger
    import plugins.memory.memory_os.owner_actions as owner_actions_module

    now = datetime.now(timezone.utc)
    store = _store(tmp_path)
    record_id = _add_aged_provisional(
        store,
        candidate_id="cand_send_ok",
        body="Durable successful-send fact.",
        now=now,
    )
    save_config(
        {
            "owner_review": {
                "enabled": True,
                "owner_id": "owner",
                "channel": "telegram",
                "target_ref": "telegram:12345",
                "direct_message": True,
                "delivery_enabled": True,
                "delivery_adapter": "hermes_owner_channel",
            }
        },
        tmp_path,
    )
    sent_messages = []

    def successful_send(**kwargs):
        sent_messages.append(kwargs["message"])
        return {"ok": True, "delivery_ref": {"message_id": "msg-permanent-1"}}

    monkeypatch.setattr(owner_actions_module, "_send_owner_review_digest_via_hermes", successful_send)

    first = deliver_owner_review_digest_once(
        store,
        owner_id="owner",
        delivery_key="send_ok_once",
        owner_triggered=True,
        apply=True,
    )
    duplicate = deliver_owner_review_digest_once(
        store,
        owner_id="owner",
        delivery_key="send_ok_once",
        owner_triggered=True,
        apply=True,
    )

    assert first["status"] == "sent"
    assert first["permanent_promotion_delivery_ack"]["acknowledged_count"] == 1
    assert duplicate["status"] == "duplicate_ignored"
    assert duplicate["permanent_promotion_delivery_ack"]["acknowledged_count"] == 0
    assert duplicate["permanent_promotion_delivery_ack"]["duplicate_delivery_suppressed_count"] == 1
    assert len(sent_messages) == 1
    assert "memory approve ppmt_" in sent_messages[0]
    states = PermanentPromotionDeliveryLedger(store.roots.memory_os_root).states()
    assert len(states) == 1
    assert next(iter(states.values()))["delivery_count"] == 1
    assert CrystallizedMemoryService(store).find_record(record_id).frontmatter["provisional"] is True
    persisted = owner_review_deliveries_path(store.roots).read_text(encoding="utf-8")
    persisted += owner_review_rendered_digests_path(store.roots).read_text(encoding="utf-8")
    delivered_token = re.search(
        r"(?<![A-Za-z0-9_-])ppmt_[A-Za-z0-9_-]+(?![A-Za-z0-9_-])",
        sent_messages[0],
    )
    assert delivered_token is not None
    assert delivered_token.group(0) not in persisted


def test_delivery_render_fails_closed_for_promotion_producer_without_blocking_digest(tmp_path, monkeypatch):
    from plugins.memory.memory_os.owner_actions import render_owner_review_delivery_digest
    import plugins.memory.memory_os.permanent_promotion as permanent_module

    store = _store(tmp_path)
    monkeypatch.setattr(
        permanent_module,
        "prepare_permanent_promotion_delivery",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("injected producer failure")),
    )

    rendered = render_owner_review_delivery_digest(
        store,
        delivery_ref="cron_fail_closed",
        digest_mode="agenda",
    )

    assert rendered["status"] == "ok"
    assert rendered["permanent_promotion_delivery"]["status"] == "error"
    assert rendered["permanent_promotion_delivery"]["shown_proposal_ids"] == []
    assert rendered["permanent_promotion_delivery"]["automatic_permanent_promotion_count"] == 0
