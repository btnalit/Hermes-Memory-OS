from __future__ import annotations

import json
import sqlite3

from plugins.memory.memory_os.config import save_config
from plugins.memory.memory_os.crystallized import CrystallizedCandidate, append_candidate_queue
from plugins.memory.memory_os import MemoryOSProvider
from plugins.memory.memory_os.memory_sources import append_memory_source_record, memory_sources_feedback_path
from plugins.memory.memory_os.owner_actions import (
    approved_proposal_followups_report,
    apply_owner_action,
    deliver_owner_review_digest_once,
    owner_actions_path,
    owner_review_deliveries_path,
    owner_review_rendered_digests_path,
    owner_review_aging_report,
    owner_review_cron_helper_path,
    owner_review_cron_integration_report,
    owner_review_delivery_gate_report,
    owner_review_delivery_status_report,
    owner_review_digest_preview,
    owner_review_queue_report,
    owner_review_status_report,
    parse_owner_review_reply,
    render_owner_review_digest,
    resolve_owner_review_channel,
)
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.modules.governance.proposal_queue import ProposalQueueModule


def _store(tmp_path, *, profile: str = "main") -> MemoryOSStore:
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile=profile)
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def _candidate() -> CrystallizedCandidate:
    return CrystallizedCandidate(
        candidate_id="cand_owner_001",
        kind="preference",
        body="User prefers concise owner-review summaries with clear approve or reject choices.",
        source_event_ids=["evt_owner_001"],
        sensitivity="private",
        tags=["owner-review"],
    )


def _jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _review_command(rendered, anchor: str, action_type: str) -> str:
    for items in (rendered.get("sections") or {}).values():
        for item in items:
            if item.get("anchor") == anchor:
                tokens = item.get("action_tokens") or {}
                token = tokens[action_type]
                verb = {
                    "approve_candidate": "approve",
                    "reject_candidate": "reject",
                    "approve_proposal": "approve",
                    "reject_proposal": "reject",
                    "mark_feedback": "feedback",
                    "allow_speak_once": "allow",
                }[action_type]
                if action_type == "mark_feedback":
                    return f"memory {verb} {token} too_mechanistic"
                return f"memory {verb} {token}"
    raise AssertionError(f"missing anchor {anchor}")


def test_review_queue_lists_bounded_candidates_without_raw_body(tmp_path):
    store = _store(tmp_path)
    append_candidate_queue(store, _candidate())
    proposal = ProposalQueueModule(tmp_path, profile="main")
    proposal.create_candidate(store=store, title="Review bounded proposal", body="RAW PROPOSAL BODY")

    report = owner_review_queue_report(store, limit=10)
    serialized = json.dumps(report, ensure_ascii=False)

    assert report["pending_count"] == 2
    assert report["review_aging"]["raw_action_required_count"] == 2
    assert report["action_required_count"] == 1
    assert report["review_suggested_count"] == 1
    assert [item["anchor"] for item in report["items"]] == ["A1", "R1"]
    assert all(item["raw_body_included"] is False for item in report["items"])
    assert "Candidate kind=" not in serialized
    assert "RAW PROPOSAL BODY" not in serialized


def test_review_aging_projects_old_and_unknown_items_without_mutating_state(tmp_path):
    store = _store(tmp_path)
    append_candidate_queue(store, _candidate())
    proposal = ProposalQueueModule(tmp_path, profile="main")
    proposal.create_candidate(store=store, title="Old proposal", body="RAW PROPOSAL BODY")
    queue = proposal.read_queue()
    queue["items"][0]["created_at"] = "2000-01-01T00:00:00Z"
    proposal.queue_path.write_text(json.dumps(queue), encoding="utf-8")

    report = owner_review_queue_report(store, limit=10)
    aging = owner_review_aging_report(store)
    serialized = json.dumps(report, ensure_ascii=False)

    assert aging["schema_version"] == "memory-os.owner_review_aging.v0"
    assert aging["raw_action_required_count"] == 2
    assert aging["effective_action_required_count"] == 0
    assert aging["aged_to_review_suggested_count"] == 1
    assert aging["aged_to_fyi_count"] == 1
    assert aging["unknown_timestamp_count"] == 1
    assert aging["canonical_state_changed"] is False
    assert aging["owner_action_created"] is False
    assert report["action_required_count"] == 0
    assert report["review_suggested_count"] == 1
    assert report["fyi_count"] == 1
    assert {item["source_priority"] for item in report["items"]} == {"action_required"}
    assert {item["effective_priority"] for item in report["items"]} == {"review_suggested", "fyi"}
    assert "Candidate kind=" not in serialized
    assert "RAW PROPOSAL BODY" not in serialized


def test_approve_candidate_requires_apply_and_is_idempotent(tmp_path):
    store = _store(tmp_path)
    append_candidate_queue(store, _candidate())

    dry_run = apply_owner_action(
        store,
        action_type="approve_candidate",
        target="candidate:cand_owner_001",
        owner_id="owner",
        channel="cli",
        apply=False,
    )

    assert dry_run["status"] == "ok"
    assert dry_run["dry_run"] is True
    assert not owner_actions_path(store.roots).exists()
    assert not (store.roots.crystallized_root / "owner_approved.md").exists()

    applied = apply_owner_action(
        store,
        action_type="approve_candidate",
        target="candidate:cand_owner_001",
        owner_id="owner",
        channel="cli",
        note="Approved.",
        apply=True,
    )

    assert applied["status"] == "ok"
    record = applied["record"]
    assert record["idempotency_key"] == "owner|candidate|cand_owner_001|approve_candidate"
    assert record["boundary"]["actual_unapproved_crystallized_approval"] is False
    assert record["owner_effect"]["owner_approved_crystallized_write"] is True
    assert (store.roots.crystallized_root / "owner_approved.md").exists()

    duplicate = apply_owner_action(
        store,
        action_type="approve_candidate",
        target="cand_owner_001",
        owner_id="owner",
        channel="cli",
        apply=True,
    )

    records = _jsonl(owner_actions_path(store.roots))
    crystallized_text = (store.roots.crystallized_root / "owner_approved.md").read_text(encoding="utf-8")
    assert duplicate["status"] == "duplicate_ignored"
    assert len(records) == 2
    assert sum(1 for record in records if record["result"] == "applied") == 1
    assert sum(1 for record in records if record["result"] == "duplicate_ignored") == 1
    assert crystallized_text.count("candidate_id: cand_owner_001") == 1


def test_owner_actions_status_counts_queue_and_owner_effects(tmp_path):
    store = _store(tmp_path)
    append_candidate_queue(store, _candidate())
    apply_owner_action(
        store,
        action_type="approve_candidate",
        target="cand_owner_001",
        owner_id="owner",
        channel="cli",
        apply=True,
    )

    status = owner_review_status_report(store)

    assert status["review_queue"]["pending_count"] == 0
    assert status["owner_actions"]["count"] == 1
    assert status["owner_actions"]["owner_approved_crystallized_write_count"] == 1
    assert status["owner_actions"]["unapproved_crystallized_write_count"] == 0
    assert status["digest_burden"]["owner_active_period"] is True


def test_proposal_actions_transition_without_execution_or_crystallized_approval(tmp_path):
    store = _store(tmp_path)
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    candidate = proposal_queue.create_candidate(store=store, title="Run a proposal", body="Proposal body")

    result = apply_owner_action(
        store,
        action_type="approve_proposal",
        target=f"proposal:{candidate['candidate_id']}",
        owner_id="owner",
        channel="cli",
        apply=True,
    )

    updated = proposal_queue.read_queue()["items"][0]
    assert result["status"] == "ok"
    assert updated["state"] == "approved_for_proposal"
    assert updated["crystallized_approved"] is False
    assert result["record"]["boundary"]["actual_execute"] is False
    assert result["record"]["owner_effect"]["owner_approved_crystallized_write"] is False


def test_approved_proposal_followups_project_state_without_execution_ticket(tmp_path):
    store = _store(tmp_path)
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    candidate = proposal_queue.create_candidate(store=store, title="Run a proposal", body="PRIVATE RAW BODY")

    apply_owner_action(
        store,
        action_type="approve_proposal",
        target=f"proposal:{candidate['candidate_id']}",
        owner_id="owner",
        channel="cli",
        apply=True,
    )

    report = approved_proposal_followups_report(store)

    assert report["schema_version"] == "memory-os.approved_proposal_followups.v0"
    assert report["pending_followup_count"] == 1
    assert report["execution_ticket_count"] == 0
    assert report["raw_body_included"] is False
    assert report["boundary"]["actual_execute"] is False
    assert report["items"][0]["proposal_id"] == candidate["candidate_id"]
    assert report["items"][0]["followup_state"] == "awaiting_human_controlled_followup"
    assert report["items"][0]["execution_ticket_created"] is False
    assert "PRIVATE RAW BODY" not in json.dumps(report, ensure_ascii=False)

    status = owner_review_status_report(store)
    assert status["approved_proposal_followups"]["pending_followup_count"] == 1


def test_mark_feedback_records_memory_source_feedback_without_route_mutation(tmp_path):
    store = _store(tmp_path)
    append_memory_source_record(
        store.roots,
        {
            "schema_version": "memory-os.memory_sources.v0",
            "record_id": "msrc_test_001",
            "created_at": "2026-05-25T00:00:00Z",
            "route": "ambiguous_recall",
            "query_class": "ambiguous_recall",
        },
    )

    result = apply_owner_action(
        store,
        action_type="mark_feedback",
        target="memory_source:msrc_test_001",
        owner_id="owner",
        channel="cli",
        rating="too_mechanistic",
        note="Too report-like.",
        apply=True,
    )

    feedback = _jsonl(memory_sources_feedback_path(store.roots))[0]
    assert result["status"] == "ok"
    assert feedback["memory_source_record_id"] == "msrc_test_001"
    assert feedback["rating"] == "too_mechanistic"
    assert feedback["source"] == "owner_action"
    assert result["record"]["boundary"]["actual_send"] is False


def test_review_channel_uses_explicit_config_and_never_reads_body(tmp_path):
    store = _store(tmp_path)
    save_config(
        {
            "owner_review": {
                "enabled": True,
                "mode": "dry_run",
                "owner_id": "owner",
                "channel": "telegram",
                "target_ref": "telegram:12345",
                "direct_message": True,
            }
        },
        tmp_path,
    )
    (tmp_path / "sessions").mkdir()
    (tmp_path / "sessions" / "session_private.json").write_text(
        json.dumps(
            {
                "id": "private_session",
                "platform": "telegram",
                "chat_id": "12345",
                "direct_message": True,
                "messages": [{"role": "user", "content": "PRIVATE BODY SHOULD NOT APPEAR"}],
            }
        ),
        encoding="utf-8",
    )

    report = resolve_owner_review_channel(store)
    serialized = json.dumps(report, ensure_ascii=False)

    assert report["schema_version"] == "memory-os.owner_review_channel.v0"
    assert report["status"] == "selected"
    assert report["configured_by_owner"] is True
    assert report["channel"] == "telegram"
    assert report["target_ref"] == "telegram:12345"
    assert "PRIVATE BODY" not in serialized


def test_review_channel_uses_metadata_candidate_as_dry_run_only(tmp_path):
    store = _store(tmp_path)
    db_path = tmp_path / "state.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "create table sessions (id text, platform text, chat_id text, updated_at text, is_direct integer)"
        )
        conn.execute(
            "insert into sessions values (?, ?, ?, ?, ?)",
            ("sess_1", "telegram", "98765", "2026-05-25T00:00:00Z", 1),
        )
        conn.execute("create table messages (session_id text, role text, content text)")
        conn.execute("insert into messages values (?, ?, ?)", ("sess_1", "user", "PRIVATE BODY SHOULD NOT APPEAR"))

    report = resolve_owner_review_channel(store)
    serialized = json.dumps(report, ensure_ascii=False)

    assert report["status"] == "dry_run_only"
    assert report["reason"] == "single_owner_direct_metadata_candidate"
    assert report["channel"] == "telegram"
    assert report["target_ref"] == "telegram:98765"
    assert report["raw_body_included"] is False
    assert "PRIVATE BODY" not in serialized


def test_review_channel_ignores_session_json_body_files_and_falls_back_to_cli(tmp_path):
    store = _store(tmp_path)
    (tmp_path / "sessions").mkdir()
    (tmp_path / "sessions" / "session_private.json").write_text(
        json.dumps(
            {
                "id": "private_session",
                "platform": "telegram",
                "chat_id": "12345",
                "direct_message": True,
                "messages": [{"role": "user", "content": "PRIVATE BODY SHOULD NOT APPEAR"}],
            }
        ),
        encoding="utf-8",
    )

    report = resolve_owner_review_channel(store)
    serialized = json.dumps(report, ensure_ascii=False)

    assert report["status"] == "dry_run_only"
    assert report["reason"] == "cli_preview_fallback"
    assert report["channel"] == "cli"
    assert report["candidate_count"] == 0
    assert "PRIVATE BODY" not in serialized


def test_digest_preview_is_bounded_no_send_and_no_raw_body(tmp_path):
    store = _store(tmp_path)
    append_candidate_queue(store, _candidate())
    proposal = ProposalQueueModule(tmp_path, profile="main")
    proposal.create_candidate(store=store, title="Review bounded proposal", body="RAW PROPOSAL BODY")

    preview = owner_review_digest_preview(store, max_action_required=1, max_review_suggested=1, max_fyi=1)
    serialized = json.dumps(preview, ensure_ascii=False)

    assert preview["schema_version"] == "memory-os.owner_review_digest_preview.v0"
    assert preview["will_send"] is False
    assert preview["delivery_skipped"] is True
    assert preview["actions_enabled"] is False
    assert preview["raw_body_included"] is False
    assert preview["counts"]["raw_action_required_total"] == 2
    assert preview["counts"]["action_required_total"] == 1
    assert preview["counts"]["action_required_shown"] == 1
    assert preview["overflow"]["action_required"] == 0
    assert preview["sections"]["action_required"][0]["anchor"] == "A1"
    assert preview["review_aging"]["aged_to_review_suggested_count"] == 1
    assert "Candidate kind=" not in serialized
    assert "RAW PROPOSAL BODY" not in serialized


def test_render_digest_turns_schema_items_into_owner_readable_review_items(tmp_path):
    store = _store(tmp_path)
    append_candidate_queue(store, _candidate())
    proposal = ProposalQueueModule(tmp_path, profile="main")
    proposal.create_candidate(store=store, title="Review bounded proposal", body="RAW PROPOSAL BODY")

    rendered = render_owner_review_digest(store, max_action_required=1, max_review_suggested=1, max_fyi=1)
    serialized = json.dumps(rendered, ensure_ascii=False)
    text = rendered["text"]
    item = rendered["sections"]["action_required"][0]

    assert rendered["schema_version"] == "memory-os.owner_review_rendered_digest.v0"
    assert item["anchor"] == "A1"
    assert item["source_module"] in {"proposal_queue", "crystallized_candidates"}
    assert item["question"]
    assert item["suggested_action"]
    assert item["reason"]
    assert item["consequence"]
    assert item["action_commands"]
    assert all(command.startswith("memory ") for command in item["action_commands"])
    assert item["raw_body_included"] is False
    assert "memory approve oa_" in text or "memory reject oa_" in text
    assert "User prefers concise owner-review summaries" in text
    assert "proposed_memory_text" in serialized
    assert "Candidate kind=" not in text
    assert "source_events=" not in text
    assert "sensitivity=" not in text
    assert "RAW PROPOSAL BODY" not in serialized


def test_render_digest_downgrades_transcript_like_candidate_to_cleanup_fyi(tmp_path):
    store = _store(tmp_path)
    append_candidate_queue(
        store,
        CrystallizedCandidate(
            candidate_id="cand_transcript_001",
            kind="moment",
            body="User: 你了解我们记忆系统吗？ | Assistant: 是的，我非常了解。目前的记忆系统是由 Memory-OS 驱动的。",
            source_event_ids=["evt_transcript_001"],
            sensitivity="private",
            tags=["owner-review"],
        ),
    )

    rendered = render_owner_review_digest(store, max_action_required=0, max_review_suggested=0, max_fyi=2)
    text = rendered["text"]
    fyi = rendered["sections"]["fyi"][0]

    assert fyi["target_type"] == "candidate_cleanup"
    assert fyi["available_actions"] == []
    assert "needs consolidation" in text
    assert "User:" not in text
    assert "Assistant:" not in text


def test_render_digest_keeps_telegram_text_bounded_without_partial_item(tmp_path):
    store = _store(tmp_path)
    proposal = ProposalQueueModule(tmp_path, profile="main")
    for index in range(12):
        proposal.create_candidate(store=store, title=f"Verbose proposal {index}", body="RAW PROPOSAL BODY")

    rendered = render_owner_review_digest(store)
    text = rendered["text"]

    assert len(text) <= 2400
    assert not text.endswith("owner-")
    assert rendered["counts"]["action_required_shown"] <= 3
    assert "RAW PROPOSAL BODY" not in text


def test_reply_parser_maps_delivered_digest_anchor_to_owner_action_processor(tmp_path):
    store = _store(tmp_path)
    append_candidate_queue(store, _candidate())
    delivered = render_owner_review_digest(
        store,
        channel="telegram",
        max_action_required=0,
        max_review_suggested=1,
        max_fyi=0,
        record_active=True,
    )

    # The queue changes after delivery. The reply must still bind to the
    # delivered digest, not a freshly rendered digest with shifted anchors.
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    proposal_queue.create_candidate(store=store, title="Newer proposal", body="RAW PROPOSAL BODY")

    dry_run = parse_owner_review_reply(
        store,
        _review_command(delivered, "R1", "approve_candidate"),
        owner_id="owner",
        channel="telegram",
        digest_id=delivered["digest_id"],
        apply=False,
    )

    assert dry_run["schema_version"] == "memory-os.owner_review_reply.v0"
    assert dry_run["status"] == "ok"
    assert dry_run["dry_run"] is True
    assert dry_run["active_digest"]["binding"] == "recorded_digest"
    assert dry_run["parsed"]["action_type"] == "approve_candidate"
    assert dry_run["parsed"]["target_type"] == "candidate"
    assert dry_run["parsed"]["target_id"] == "cand_owner_001"
    assert dry_run["owner_action_result"]["status"] == "ok"
    assert not owner_actions_path(store.roots).exists()

    applied = parse_owner_review_reply(
        store,
        _review_command(delivered, "R1", "approve_candidate"),
        owner_id="owner",
        channel="telegram",
        digest_id=delivered["digest_id"],
        apply=True,
    )

    assert applied["status"] == "ok"
    assert applied["owner_action_result"]["record"]["owner_effect"]["owner_approved_crystallized_write"] is True
    assert (store.roots.crystallized_root / "owner_approved.md").exists()
    assert owner_review_rendered_digests_path(store.roots).exists()


def test_reply_parser_uses_latest_recorded_digest_without_rerendering_current_queue(tmp_path):
    store = _store(tmp_path)
    append_candidate_queue(store, _candidate())
    rendered = render_owner_review_digest(
        store,
        channel="telegram",
        max_action_required=0,
        max_review_suggested=1,
        max_fyi=0,
        record_active=True,
    )
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    proposal_queue.create_candidate(store=store, title="Newer proposal", body="RAW PROPOSAL BODY")

    result = parse_owner_review_reply(
        store,
        _review_command(rendered, "R1", "reject_candidate"),
        owner_id="owner",
        channel="telegram",
        apply=False,
    )

    assert result["status"] == "ok"
    assert result["active_digest"]["binding"] == "latest_recorded_digest"
    assert result["parsed"]["action_type"] == "reject_candidate"
    assert result["parsed"]["target_id"] == "cand_owner_001"


def test_provider_owner_review_reply_ingress_processes_recorded_digest_before_prefetch(tmp_path):
    store = _store(tmp_path)
    append_candidate_queue(store, _candidate())
    rendered = render_owner_review_digest(
        store,
        channel="telegram",
        max_action_required=0,
        max_review_suggested=1,
        max_fyi=0,
        record_active=True,
    )

    provider = MemoryOSProvider()
    provider.initialize(
        "session-owner-review",
        hermes_home=str(tmp_path),
        platform="telegram",
        agent_identity="main",
        worker_autostart=False,
    )
    command = _review_command(rendered, "R1", "reject_candidate")
    provider.on_turn_start(1, command)
    context = provider.prefetch(command, session_id="session-owner-review")
    prompt_block = provider.system_prompt_block()

    records = _jsonl(owner_actions_path(store.roots))
    assert len(records) == 1
    assert records[0]["action_type"] == "reject_candidate"
    assert records[0]["target_id"] == "cand_owner_001"
    assert records[0]["channel"] == "telegram"
    assert "Owner Review Reply" in context
    assert "processed action: reject_candidate" in prompt_block
    assert "Do not ask the owner to choose another review anchor" in prompt_block


def test_provider_owner_review_reply_sync_fallback_is_idempotent(tmp_path):
    store = _store(tmp_path)
    append_candidate_queue(store, _candidate())
    rendered = render_owner_review_digest(
        store,
        channel="telegram",
        max_action_required=0,
        max_review_suggested=1,
        max_fyi=0,
        record_active=True,
    )

    provider = MemoryOSProvider()
    provider.initialize(
        "session-owner-review",
        hermes_home=str(tmp_path),
        platform="telegram",
        agent_identity="main",
        worker_autostart=False,
    )
    command = _review_command(rendered, "R1", "reject_candidate")
    provider.on_turn_start(1, command)
    provider.sync_turn(command, "ack", session_id="session-owner-review")

    records = _jsonl(owner_actions_path(store.roots))
    assert len(records) == 1
    assert records[0]["action_type"] == "reject_candidate"
    audit = _jsonl(store.roots.audit_path)
    ingress = [item for item in audit if item.get("action") == "owner_review_reply_ingress"]
    assert {item["details"]["phase"] for item in ingress} == {"turn_start"}


def test_provider_owner_review_reply_sync_fallback_processes_when_turn_start_missed(tmp_path):
    store = _store(tmp_path)
    append_candidate_queue(store, _candidate())
    rendered = render_owner_review_digest(
        store,
        channel="telegram",
        max_action_required=0,
        max_review_suggested=1,
        max_fyi=0,
        record_active=True,
    )

    provider = MemoryOSProvider()
    provider.initialize(
        "session-owner-review",
        hermes_home=str(tmp_path),
        platform="telegram",
        agent_identity="main",
        worker_autostart=False,
    )
    command = _review_command(rendered, "R1", "reject_candidate")
    provider.sync_turn(command, "ack", session_id="session-owner-review")

    records = _jsonl(owner_actions_path(store.roots))
    assert len(records) == 1
    assert records[0]["action_type"] == "reject_candidate"
    audit = _jsonl(store.roots.audit_path)
    ingress = [item for item in audit if item.get("action") == "owner_review_reply_ingress"]
    assert {item["details"]["phase"] for item in ingress} == {"sync_turn"}


def test_provider_owner_review_reply_ingress_falls_back_to_recurring_delivery_channel(tmp_path):
    store = _store(tmp_path)
    save_config(
        {
            "owner_review": {
                "owner_id": "owner",
                "recurring_delivery_channel": "cli",
            }
        },
        str(tmp_path),
    )
    render_owner_review_digest(
        store,
        channel="telegram",
        max_action_required=0,
        max_review_suggested=0,
        max_fyi=0,
        record_active=True,
    )
    append_candidate_queue(store, _candidate())
    rendered = render_owner_review_digest(
        store,
        channel="cli",
        max_action_required=0,
        max_review_suggested=1,
        max_fyi=0,
        record_active=True,
    )

    provider = MemoryOSProvider()
    provider.initialize(
        "session-owner-review",
        hermes_home=str(tmp_path),
        platform="telegram",
        agent_identity="main",
        worker_autostart=False,
    )
    provider.on_turn_start(1, _review_command(rendered, "R1", "reject_candidate"))

    records = _jsonl(owner_actions_path(store.roots))
    assert len(records) == 1
    assert records[0]["action_type"] == "reject_candidate"
    assert records[0]["target_id"] == "cand_owner_001"
    assert records[0]["channel"] == "cli"


def test_provider_owner_review_reply_ingress_uses_owner_home_binding_not_platform_label(tmp_path):
    store = _store(tmp_path)
    save_config(
        {
            "owner_review": {
                "owner_id": "owner",
                "recurring_delivery_enabled": True,
                "recurring_delivery_mode": "hermes_cron",
                "recurring_delivery_channel": "origin",
                "recurring_delivery_target_class": "origin",
            }
        },
        str(tmp_path),
    )
    append_candidate_queue(store, _candidate())
    render_owner_review_digest(
        store,
        channel="cli",
        max_action_required=0,
        max_review_suggested=1,
        max_fyi=0,
        record_active=True,
    )
    rendered = render_owner_review_digest(
        store,
        channel="origin",
        max_action_required=0,
        max_review_suggested=1,
        max_fyi=0,
        record_active=True,
    )

    provider = MemoryOSProvider()
    provider.initialize(
        "session-owner-review",
        hermes_home=str(tmp_path),
        platform="telegram",
        agent_identity="main",
        worker_autostart=False,
    )
    command = _review_command(rendered, "R1", "reject_candidate")
    provider.on_turn_start(1, command)
    context = provider.prefetch(command, session_id="session-owner-review")

    records = _jsonl(owner_actions_path(store.roots))
    assert len(records) == 1
    assert records[0]["action_type"] == "reject_candidate"
    assert records[0]["channel"] == "telegram"
    assert "latest_owner_home_digest" in context


def test_provider_owner_review_reply_ingress_requires_recorded_digest(tmp_path):
    store = _store(tmp_path)
    provider = MemoryOSProvider()
    provider.initialize(
        "session-owner-review",
        hermes_home=str(tmp_path),
        platform="telegram",
        agent_identity="main",
        worker_autostart=False,
    )

    provider.on_turn_start(1, "memory reject oa_deadbeef")
    context = provider.prefetch("memory reject oa_deadbeef", session_id="session-owner-review")

    assert "digest_not_found_or_expired" in context
    assert not owner_actions_path(store.roots).exists()


def test_provider_owner_review_reply_ingress_accepts_punctuation_and_ignores_chatter(tmp_path):
    store = _store(tmp_path)
    append_candidate_queue(store, _candidate())
    rendered = render_owner_review_digest(
        store,
        channel="telegram",
        max_action_required=0,
        max_review_suggested=1,
        max_fyi=0,
        record_active=True,
    )

    chatter = MemoryOSProvider()
    chatter.initialize(
        "session-owner-review",
        hermes_home=str(tmp_path),
        platform="telegram",
        agent_identity="main",
        worker_autostart=False,
    )
    chatter.on_turn_start(1, "普通聊天里提到 memory reject oa_deadbeef")
    assert not owner_actions_path(store.roots).exists()

    legacy = MemoryOSProvider()
    legacy.initialize(
        "session-owner-review",
        hermes_home=str(tmp_path),
        platform="telegram",
        agent_identity="main",
        worker_autostart=False,
    )
    legacy.on_turn_start(2, "reject R1")
    assert not owner_actions_path(store.roots).exists()

    provider = MemoryOSProvider()
    provider.initialize(
        "session-owner-review",
        hermes_home=str(tmp_path),
        platform="telegram",
        agent_identity="main",
        worker_autostart=False,
    )
    command = _review_command(rendered, "R1", "reject_candidate") + "。"
    provider.on_turn_start(3, command)
    context = provider.prefetch(command, session_id="session-owner-review")

    records = _jsonl(owner_actions_path(store.roots))
    assert len(records) == 1
    assert records[0]["action_type"] == "reject_candidate"
    assert records[0]["target_id"] == "cand_owner_001"
    assert "Owner Review Reply" in context


def test_reply_parser_handles_feedback_anchor_without_route_mutation(tmp_path):
    store = _store(tmp_path)
    append_memory_source_record(
        store.roots,
        {
            "schema_version": "memory-os.memory_sources.v0",
            "record_id": "msrc_test_001",
            "created_at": "2026-05-25T00:00:00Z",
            "route": "ambiguous_recall",
            "query_class": "ambiguous_recall",
        },
    )

    rendered = render_owner_review_digest(store, max_action_required=0, max_review_suggested=0, max_fyi=1)
    result = parse_owner_review_reply(
        store,
        _review_command(rendered, "F1", "mark_feedback"),
        owner_id="owner",
        channel="telegram",
        apply=True,
        max_fyi=1,
    )

    feedback = _jsonl(memory_sources_feedback_path(store.roots))[0]
    assert result["status"] == "ok"
    assert result["parsed"]["action_type"] == "mark_feedback"
    assert result["parsed"]["target_type"] == "memory_source"
    assert result["parsed"]["target_id"] == "msrc_test_001"
    assert feedback["rating"] == "too_mechanistic"
    assert result["owner_action_result"]["record"]["boundary"]["actual_send"] is False


def test_reply_parser_unknown_anchor_needs_clarification_without_mutation(tmp_path):
    store = _store(tmp_path)
    append_candidate_queue(store, _candidate())

    result = parse_owner_review_reply(store, "memory approve oa_deadbeef", owner_id="owner", channel="telegram", apply=True)

    assert result["status"] == "needs_clarification"
    assert result["reason"] == "action_token_not_found_in_recorded_digest"
    assert not owner_actions_path(store.roots).exists()


def test_delivery_gate_is_disabled_by_default_and_never_sends(tmp_path):
    store = _store(tmp_path)
    append_candidate_queue(store, _candidate())

    gate = owner_review_delivery_gate_report(store)

    assert gate["schema_version"] == "memory-os.owner_review_delivery_gate.v0"
    assert gate["status"] == "disabled"
    assert gate["ready_for_delivery"] is False
    assert gate["delivery_enabled"] is False
    assert "delivery_not_enabled" in gate["blocked_reasons"]
    assert gate["boundary"] == {
        "actual_send": False,
        "actual_execute": False,
        "actual_identity_write": False,
        "actual_unapproved_crystallized_approval": False,
    }


def test_delivery_gate_can_be_ready_only_with_explicit_owner_channel_and_adapter(tmp_path):
    store = _store(tmp_path)
    append_candidate_queue(store, _candidate())
    save_config(
        {
            "owner_review": {
                "enabled": True,
                "mode": "dry_run",
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

    gate = owner_review_delivery_gate_report(store)

    assert gate["status"] == "ready"
    assert gate["ready_for_delivery"] is True
    assert gate["blocked_reasons"] == []
    assert gate["review_channel"]["configured_by_owner"] is True
    assert gate["review_channel"]["channel"] == "telegram"
    assert gate["digest"]["raw_body_included"] is False
    assert gate["digest"]["will_send"] is False
    assert gate["boundary"]["actual_send"] is False


def test_delivery_gate_blocks_unconfigured_adapter_even_with_channel(tmp_path):
    store = _store(tmp_path)
    save_config(
        {
            "owner_review": {
                "enabled": True,
                "channel": "telegram",
                "target_ref": "telegram:12345",
                "direct_message": True,
                "delivery_enabled": True,
                "delivery_adapter": "none",
            }
        },
        tmp_path,
    )

    gate = owner_review_delivery_gate_report(store)

    assert gate["status"] == "blocked"
    assert "delivery_adapter_not_configured" in gate["blocked_reasons"]
    assert gate["boundary"]["actual_send"] is False


def test_deliver_once_requires_owner_trigger_and_does_not_send_by_default(tmp_path):
    store = _store(tmp_path)
    append_candidate_queue(store, _candidate())

    result = deliver_owner_review_digest_once(
        store,
        owner_id="owner",
        delivery_key="rh34d-test",
        owner_triggered=False,
        apply=True,
    )

    assert result["status"] == "skipped"
    assert "owner_trigger_required" in result["record"]["blocked_reasons"]
    assert "delivery_not_enabled" in result["record"]["blocked_reasons"]
    assert result["record"]["boundary"]["actual_unapproved_send"] is False
    assert result["record"]["owner_effect"]["owner_approved_digest_delivery"] is False
    assert owner_review_deliveries_path(store.roots).exists()
    status = owner_review_delivery_status_report(store)
    assert status["delivery_count"] == 1
    assert status["sent_count"] == 0
    assert status["skipped_count"] == 1
    assert status["unapproved_send_count"] == 0


def test_deliver_once_is_legacy_smoke_only_even_when_gate_ready_and_owner_triggered(tmp_path):
    store = _store(tmp_path)
    append_candidate_queue(store, _candidate())
    proposal = ProposalQueueModule(tmp_path, profile="main")
    proposal.create_candidate(store=store, title="Review bounded proposal", body="RAW PROPOSAL BODY")
    save_config(
        {
            "owner_review": {
                "enabled": True,
                "mode": "dry_run",
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
    result = deliver_owner_review_digest_once(
        store,
        owner_id="owner",
        delivery_key="rh34d-test",
        owner_triggered=True,
        apply=True,
    )
    duplicate = deliver_owner_review_digest_once(
        store,
        owner_id="owner",
        delivery_key="rh34d-test",
        owner_triggered=True,
        apply=True,
    )

    assert result["status"] == "smoke_only"
    assert duplicate["status"] == "duplicate_ignored"
    assert "legacy_smoke_only_use_hermes_cron" in result["record"]["blocked_reasons"]

    status = owner_review_delivery_status_report(store)
    assert status["delivery_count"] == 2
    assert status["sent_count"] == 0
    assert status["duplicate_ignored_count"] == 1
    assert status["owner_approved_digest_delivery_count"] == 0
    assert status["unapproved_send_count"] == 0
    assert status["raw_body_included_count"] == 0


def test_cron_integration_status_reports_helper_and_redacted_delivery_target(tmp_path):
    store = _store(tmp_path)
    save_config(
        {
            "owner_review": {
                "recurring_delivery_enabled": True,
                "recurring_delivery_mode": "hermes_cron",
                "cron_job_name": "memory-os-owner-review-digest",
            }
        },
        tmp_path,
    )
    helper = owner_review_cron_helper_path(store.roots)
    helper.parent.mkdir(parents=True)
    helper.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    jobs_path = tmp_path / "cron" / "jobs.json"
    jobs_path.parent.mkdir(parents=True)
    jobs_path.write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "id": "job_owner_review",
                        "name": "memory-os-owner-review-digest",
                        "enabled": True,
                        "script": "memory_os_owner_review_digest.py",
                        "deliver": "telegram:-100123",
                        "schedule": {"display": "0 9 * * *"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    report = owner_review_cron_integration_report(store)

    assert report["schema_version"] == "memory-os.owner_review_cron_integration.v0"
    assert report["status"] == "ok"
    assert report["enabled"] is True
    assert report["job_present"] is True
    assert report["job_enabled"] is True
    assert report["helper_script_present"] is True
    assert report["hermes_delivery_configured"] is True
    assert report["hermes_delivery_target_class"] == "explicit_target"
    assert report["raw_body_included_count"] == 0
    assert report["boundary"]["actual_send"] is False
    assert "telegram:-100123" not in json.dumps(report, ensure_ascii=False)
