from __future__ import annotations

import json
import sqlite3
import hashlib

import pytest

from plugins.memory.memory_os.audit import read_audit_entries
from plugins.memory.memory_os.config import save_config
from plugins.memory.memory_os.crystallized import (
    CrystallizedCandidate,
    CrystallizedMemoryService,
    append_candidate_queue,
    read_candidate_queue,
)
from plugins.memory.memory_os import MemoryOSProvider
from plugins.memory.memory_os import owner_actions as owner_actions_module
from plugins.memory.memory_os.context_router import ContextSection
from plugins.memory.memory_os.memory_sources import (
    append_memory_source_record,
    build_memory_source_record,
    memory_sources_feedback_path,
    memory_sources_policy_path,
    memory_sources_stats_report,
)
from plugins.memory.memory_os.legacy_right_brain_retirement import (
    load_retirement_manifest,
    retire_legacy_right_brain,
)
from plugins.memory.memory_os.owner_actions import (
    approved_proposal_followups_report,
    apply_owner_action,
    approved_proposal_execution_tickets_path,
    deep_reflection_policy_applies_path,
    deep_reflection_policy_path,
    deliver_owner_review_digest_once,
    expression_feedback_ledger_path,
    hindsight_curation_decisions_path,
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
    owner_review_surface_report,
    parse_owner_review_reply,
    render_owner_review_digest,
    resolve_owner_review_channel,
    speak_permission_tickets_path,
    auto_route_safe_proposal_followups_to_ops_gate,
    apply_approved_proposal_execution_decision,
    route_approved_proposal_followup_to_ops_gate,
    route_pending_approved_proposal_followups_to_ops_gate,
)
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.runtime import MemoryOSRuntime
from plugins.memory.memory_os.schema import EVENT_SCHEMA_VERSION, EventEnvelope
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.memory.memory_os.substrates.local_artifact import LocalArtifactProvider
from plugins.memory.memory_os.substrates.ledger import SubstrateOperationLedger
from plugins.memory.memory_os.substrates.projection import ProjectionLedger, derive_projection_coherence
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


def _apply_candidate_via_recorded_digest(
    store: MemoryOSStore,
    candidate_id: str,
    *,
    owner_id: str = "owner",
    channel: str = "telegram",
) -> dict:
    save_config(
        {
            "owner_review": {
                "enabled": True,
                "actions_enabled": True,
                "recurring_delivery_enabled": True,
                "recurring_delivery_mode": "hermes_cron",
                "recurring_delivery_channel": channel,
                "recurring_delivery_target_class": "owner_home",
            }
        },
        store.roots.hermes_home,
    )
    rendered = render_owner_review_digest(
        store,
        owner_id=owner_id,
        channel=channel,
        max_action_required=20,
        max_review_suggested=20,
        max_fyi=20,
        record_active=True,
    )
    item = next(
        item
        for section in rendered["sections"].values()
        for item in section
        if item.get("target_type") == "candidate"
        and item.get("target_id") == candidate_id
    )
    token = str(item["action_tokens"]["approve_candidate"])
    result = parse_owner_review_reply(
        store,
        f"memory approve {token}",
        owner_id=owner_id,
        channel=channel,
        apply=True,
        digest_id=str(rendered["digest_id"]),
        require_recorded_digest=True,
    )
    assert result["status"] == "ok", result
    return dict(result["owner_action_result"])


def test_retired_right_brain_outcomes_do_not_reenter_active_owner_surface(tmp_path):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="main")
    live = tmp_path / "system-modules" / "right_brain_expression_adapter" / "outcomes.jsonl"
    live.parent.mkdir(parents=True)
    live.write_text('{"outcome_id":"legacy-outcome","outcome_preview":"PRIVATE"}\n', encoding="utf-8")
    retire_legacy_right_brain(tmp_path, apply=True)
    retirement = load_retirement_manifest(tmp_path)
    archived = tmp_path / retirement["archive_relative_path"] / live.relative_to(tmp_path)

    resolved = owner_actions_module.right_brain_expression_outcomes_path(roots)

    assert archived.is_file()
    assert resolved == live
    assert not resolved.exists()


def test_retired_right_brain_blocks_speak_permission_ticket_and_delivery(tmp_path):
    store = _store(tmp_path)
    retire_legacy_right_brain(tmp_path, apply=True)

    with pytest.raises(RuntimeError, match="speak permission is retired"):
        owner_actions_module._append_speak_ticket(
            store,
            {"target_id": "legacy-would-send", "owner_action_id": "oa_legacy", "boundary": {}},
        )

    assert owner_actions_module.read_speak_permission_tickets(store.roots) == []
    assert not (tmp_path / "memory-os" / "system" / "speak_permission_tickets.jsonl").exists()


def test_retired_right_brain_blocks_expression_policy_write(tmp_path):
    store = _store(tmp_path)
    retire_legacy_right_brain(tmp_path, apply=True)

    with pytest.raises(RuntimeError, match="retired"):
        owner_actions_module._write_right_brain_expression_policy(
            store,
            proposal={"candidate_id": "legacy-proposal"},
            policy={"created_at": "2026-07-14T00:00:00Z"},
        )

    assert not (tmp_path / "system-modules" / "right_brain_expression_adapter").exists()


def test_rendered_digest_records_audit_when_edge_error_record_write_fails(tmp_path, monkeypatch):
    store = _store(tmp_path)
    store.roots.index_path.parent.mkdir(parents=True, exist_ok=True)
    store.roots.index_path.write_text("not a sqlite database", encoding="utf-8")
    audit_calls = []

    def fail_append_jsonl(path, record):
        raise OSError("synthetic error-record write failure")

    def capture_append_audit(*args, **kwargs):
        audit_calls.append(kwargs)

    monkeypatch.setattr(owner_actions_module, "_append_jsonl", fail_append_jsonl)
    monkeypatch.setattr(owner_actions_module, "append_audit", capture_append_audit)

    owner_actions_module._rendered_digest_text(
        {"action_required": [], "review_suggested": [], "fyi": []},
        store=store,
    )

    assert audit_calls
    assert audit_calls[-1]["action"] == "owner_digest_error_record_failed"
    assert audit_calls[-1]["status"] == "warning"
    assert audit_calls[-1]["details"]["error_record_write_error_type"] == "OSError"


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
                "approve_session_mirror_apply": "approve",
                "like_expression": "feedback",
                "too_mechanical": "feedback",
                "too_frequent": "feedback",
                    "boundary_private": "feedback",
                    "off_voice": "feedback",
                    "mute_period": "feedback",
                }[action_type]
                if action_type == "mark_feedback":
                    return f"memory {verb} {token} too_mechanistic"
                if action_type in {
                    "like_expression",
                    "too_mechanical",
                    "too_frequent",
                    "boundary_private",
                    "off_voice",
                    "mute_period",
                }:
                    return f"memory {verb} {token} {action_type}"
                return f"memory {verb} {token}"
    raise AssertionError(f"missing anchor {anchor}")


def _session_mirror_review_command(rendered) -> str:
    for item in (rendered.get("sections") or {}).get("action_required", []):
        if item.get("target_type") == "session_mirror_apply":
            return f"memory approve {item['action_tokens']['approve_session_mirror_apply']}"
    raise AssertionError("missing SessionMirror approval item")


def _create_session_state_db(path, *, session_id="session-owner-1", platform="telegram"):
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            create table sessions (
                id text primary key,
                source text,
                created_at text,
                updated_at text
            )
            """
        )
        conn.execute(
            """
            create table messages (
                id integer primary key autoincrement,
                session_id text,
                role text,
                content text,
                created_at text
            )
            """
        )
        conn.execute(
            "insert into sessions(id, source, created_at, updated_at) values (?, ?, ?, ?)",
            (session_id, platform, "2026-06-02T08:00:00+00:00", "2026-06-02T08:01:00+00:00"),
        )
        conn.executemany(
            "insert into messages(session_id, role, content, created_at) values (?, ?, ?, ?)",
            [
                (session_id, "user", "SessionMirror owner approval smoke uses safe public text", "2026-06-02T08:00:01+00:00"),
                (session_id, "assistant", "Safe bounded summary response", "2026-06-02T08:00:02+00:00"),
            ],
        )


def test_review_queue_lists_bounded_candidates_without_raw_body(tmp_path):
    store = _store(tmp_path)
    append_candidate_queue(store, _candidate())
    proposal = ProposalQueueModule(tmp_path, profile="main")
    proposal.create_candidate(store=store, title="Review bounded proposal", body="RAW PROPOSAL BODY")

    report = owner_review_queue_report(store, limit=10)
    serialized = json.dumps(report, ensure_ascii=False)

    assert report["pending_count"] == 2
    assert report["review_aging"]["raw_action_required_count"] == 2
    assert report["review_aging"]["unknown_timestamp_count"] == 0
    assert report["review_aging"]["created_at_coverage_ratio"] == 1.0
    assert report["action_required_count"] == 2
    assert report["review_suggested_count"] == 0
    assert [item["anchor"] for item in report["items"]] == ["A1", "A2"]
    assert all(item["raw_body_included"] is False for item in report["items"])
    assert "Candidate kind=" not in serialized
    assert "RAW PROPOSAL BODY" not in serialized


def test_review_queue_derives_legacy_candidate_created_at_from_source_event(tmp_path):
    store = _store(tmp_path)
    event_ts = "2026-05-20T02:30:01.000000+00:00"
    store.append_event(
        EventEnvelope(
            schema_version=EVENT_SCHEMA_VERSION,
            id="evt_owner_001",
            ts=event_ts,
            profile="main",
            source="test",
            kind="foreground_conversation_turn",
            summary="safe bounded test summary",
            sensitivity="private",
            body_policy="summary_only",
            promotion_state="raw",
        )
    )
    append_candidate_queue(store, _candidate())

    # Simulate a pre-P1-P candidate record that did not carry created_at yet.
    candidate_path = store.roots.crystallized_root / "candidates.jsonl"
    records = _jsonl(candidate_path)
    records[0].pop("created_at", None)
    candidate_path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False, sort_keys=True) for record in records) + "\n",
        encoding="utf-8",
    )

    report = owner_review_queue_report(store)

    assert report["items"][0]["created_at"] == event_ts
    assert report["items"][0]["created_at_source"] == "safe_source_ref"
    assert report["review_aging"]["unknown_timestamp_count"] == 0
    assert report["review_aging"]["created_at_coverage_ratio"] == 1.0
    assert report["review_aging"]["created_at_source_distribution"] == {"safe_source_ref": 1}


def test_review_aging_projects_old_and_unknown_items_without_mutating_state(tmp_path):
    store = _store(tmp_path)
    append_candidate_queue(store, _candidate())
    candidate_path = store.roots.crystallized_root / "candidates.jsonl"
    candidate_lines = _jsonl(candidate_path)
    candidate_lines[0].pop("created_at", None)
    candidate_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False, sort_keys=True) for item in candidate_lines) + "\n",
        encoding="utf-8",
    )
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
    assert aging["unknown_timestamp_by_item_type"] == {"candidate": 1}
    assert aging["true_aged_count"] == 1
    assert aging["unknown_aged_count"] == 1
    assert aging["created_at_coverage_ratio"] == 0.5
    assert aging["created_at_source_distribution"] == {"missing": 1, "producer": 1}
    assert aging["created_at_source_by_item_type"] == {"candidate": {"missing": 1}, "proposal": {"producer": 1}}
    assert aging["canonical_state_changed"] is False
    assert aging["owner_action_created"] is False
    assert report["action_required_count"] == 0
    assert report["review_suggested_count"] == 1
    assert report["fyi_count"] == 1
    assert {item["source_priority"] for item in report["items"]} == {"action_required"}
    assert {item["effective_priority"] for item in report["items"]} == {"review_suggested", "fyi"}
    assert "Candidate kind=" not in serialized
    assert "RAW PROPOSAL BODY" not in serialized


def test_review_aging_reports_stale_informational_items_without_mutating_state(tmp_path):
    store = _store(tmp_path)
    advisor_root = tmp_path / "system-modules" / "left_brain_advisor"
    advisor_root.mkdir(parents=True)
    advisor_root.joinpath("reports.jsonl").write_text(
        json.dumps(
            {
                "schema_version": "memory-os.left_brain_advisor.v0",
                "report_id": "lba_old_info",
                "created_at": "2000-01-01T00:00:00Z",
                "findings": [
                    {
                        "finding_id": "lbf_old_review",
                        "target_type": "left_brain_advisor_finding",
                        "source_key": "runtime_logs",
                        "owner_visible": True,
                        "priority": "review_suggested",
                        "summary": "old review suggested",
                        "reason": "fixture",
                    },
                    {
                        "finding_id": "lbf_old_fyi",
                        "target_type": "left_brain_advisor_finding",
                        "source_key": "runtime_logs",
                        "owner_visible": True,
                        "priority": "fyi",
                        "summary": "old fyi",
                        "reason": "fixture",
                    },
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    aging = owner_review_aging_report(store)

    assert aging["informational_retention_days"] == aging["fyi_days"]
    assert aging["stale_informational_count"] == 2
    assert aging["stale_review_suggested_count"] == 1
    assert aging["stale_fyi_count"] == 1
    assert aging["owner_action_created"] is False
    assert aging["canonical_state_changed"] is False


def test_digest_preview_suppresses_stale_informational_items_without_mutating_state(tmp_path):
    store = _store(tmp_path)
    advisor_root = tmp_path / "system-modules" / "left_brain_advisor"
    advisor_root.mkdir(parents=True)
    advisor_root.joinpath("reports.jsonl").write_text(
        json.dumps(
            {
                "schema_version": "memory-os.left_brain_advisor.v0",
                "report_id": "lba_old_info_digest",
                "created_at": "2000-01-01T00:00:00Z",
                "findings": [
                    {
                        "finding_id": "lbf_old_review_digest",
                        "target_type": "left_brain_advisor_finding",
                        "source_key": "runtime_logs",
                        "owner_visible": True,
                        "priority": "review_suggested",
                        "summary": "old review suggested",
                        "reason": "fixture",
                    },
                    {
                        "finding_id": "lbf_old_fyi_digest",
                        "target_type": "left_brain_advisor_finding",
                        "source_key": "runtime_logs",
                        "owner_visible": True,
                        "priority": "fyi",
                        "summary": "old fyi",
                        "reason": "fixture",
                    },
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    preview = owner_review_digest_preview(store, max_action_required=0, max_review_suggested=5, max_fyi=5)
    serialized = json.dumps(preview, ensure_ascii=False)

    assert preview["review_aging"]["stale_informational_count"] == 2
    assert preview["counts"]["stale_informational_suppressed"] == 2
    assert preview["aging_behavior"]["stale_informational_action"] == "suppress_from_digest"
    assert preview["overflow"]["review_suggested"] == 0
    assert preview["overflow"]["fyi"] == 0
    assert "lbf_old_review_digest" not in serialized
    assert "lbf_old_fyi_digest" not in serialized
    assert preview["review_aging"]["owner_action_created"] is False
    assert preview["review_aging"]["canonical_state_changed"] is False


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

    applied = _apply_candidate_via_recorded_digest(
        store,
        "cand_owner_001",
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
    _apply_candidate_via_recorded_digest(store, "cand_owner_001")

    status = owner_review_status_report(store)

    assert status["review_queue"]["pending_count"] == 0
    assert status["owner_actions"]["count"] == 1
    assert status["owner_actions"]["owner_approved_crystallized_write_count"] == 1
    assert status["owner_actions"]["unapproved_crystallized_write_count"] == 0
    assert status["digest_burden"]["owner_active_period"] is True


def test_owner_actions_status_exposes_owner_burden_budget_counters(tmp_path):
    store = _store(tmp_path)
    append_candidate_queue(store, _candidate())
    advisor_root = tmp_path / "system-modules" / "left_brain_advisor"
    advisor_root.mkdir(parents=True)
    advisor_root.joinpath("reports.jsonl").write_text(
        json.dumps(
            {
                "schema_version": "memory-os.left_brain_advisor.v0",
                "report_id": "lba_budget",
                "created_at": "2026-06-03T01:00:00Z",
                "findings": [
                    {
                        "finding_id": "lbf_review",
                        "target_type": "left_brain_advisor_finding",
                        "source_key": "runtime_logs",
                        "owner_visible": True,
                        "priority": "review_suggested",
                        "summary": "review suggested",
                        "reason": "fixture",
                    },
                    {
                        "finding_id": "lbf_fyi",
                        "target_type": "left_brain_advisor_finding",
                        "source_key": "runtime_logs",
                        "owner_visible": True,
                        "priority": "fyi",
                        "summary": "fyi",
                        "reason": "fixture",
                    },
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    status = owner_review_status_report(store)
    burden = status["digest_burden"]

    assert burden["schema_version"] == "memory-os.owner_burden_budget.v0"
    assert burden["pending_total"] == 3
    assert burden["action_required_count"] == 1
    assert burden["review_suggested_count"] == 1
    assert burden["fyi_count"] == 1
    assert burden["informational_count"] == 2
    assert burden["budget_status"] == "ok"
    assert burden["budget"]["action_required_cap"] >= 1
    assert burden["budget"]["fyi_cap"] >= 1


def test_revoke_crystallized_owner_action_marks_canonical_and_invalidates_projection(tmp_path):
    store = _store(tmp_path)
    append_candidate_queue(
        store,
        CrystallizedCandidate(
            candidate_id="cand_public_revoke_001",
            kind="preference",
            body="User prefers Borealis summaries.",
            source_event_ids=["evt_public_revoke_001"],
            sensitivity="public",
            tags=["owner-review"],
        ),
    )
    approve = _apply_candidate_via_recorded_digest(
        store,
        "cand_public_revoke_001",
    )
    assert approve["status"] == "ok"
    record = CrystallizedMemoryService(store).read_records("owner_approved.md")[0]
    record_id = str(record.frontmatter["id"])
    ledger = ProjectionLedger(store.roots.memory_os_root / "system" / "projection_ledger.jsonl")
    ledger.record_retain(
        provider="hindsight",
        source_record_ref=record_id,
        source_version="current",
        substrate_record_id="hindsight-1",
        substrate_snapshot_id="hindsight:bank:v1",
    )

    revoked = apply_owner_action(
        store,
        action_type="revoke_crystallized",
        target=f"crystallized:{record_id}",
        owner_id="owner",
        channel="cli",
        note="Owner revoked stale memory.",
        apply=True,
    )

    assert revoked["status"] == "ok"
    assert revoked["dry_run"] is False
    assert revoked["record"]["boundary"]["actual_unapproved_crystallized_approval"] is False
    assert revoked["record"]["owner_effect"]["owner_revoked_crystallized_record"] is True
    assert revoked["record"]["owner_effect"]["projection_invalidation_recorded"] is True
    assert revoked["result_ref"]["actual_delete"] is False
    assert revoked["result_ref"]["projection_invalidated"] is True
    refreshed = CrystallizedMemoryService(store).read_records("owner_approved.md")[0]
    assert refreshed.frontmatter["canonical_state"] == "owner_revoked"
    assert refreshed.frontmatter["revoked_by"] == "owner"
    assert refreshed.body == "User prefers Borealis summaries."
    coherence = derive_projection_coherence(ledger.read_all(), provider="hindsight")
    assert coherence["active_projection_count"] == 0
    assert coherence["retract_count"] == 1
    assert LocalArtifactProvider(store).recall("Borealis", consumer="test") == []


def test_demote_crystallized_owner_action_marks_canonical_and_invalidates_projection(tmp_path):
    store = _store(tmp_path)
    append_candidate_queue(
        store,
        CrystallizedCandidate(
            candidate_id="cand_public_demote_001",
            kind="preference",
            body="User prefers Meridian summaries.",
            source_event_ids=["evt_public_demote_001"],
            sensitivity="public",
            tags=["owner-review"],
        ),
    )
    approve = _apply_candidate_via_recorded_digest(
        store,
        "cand_public_demote_001",
    )
    assert approve["status"] == "ok"
    record = CrystallizedMemoryService(store).read_records("owner_approved.md")[0]
    record_id = str(record.frontmatter["id"])
    ledger = ProjectionLedger(store.roots.memory_os_root / "system" / "projection_ledger.jsonl")
    ledger.record_retain(
        provider="hindsight",
        source_record_ref=record_id,
        source_version="current",
        substrate_record_id="hindsight-demote-1",
        substrate_snapshot_id="hindsight:bank:v1",
    )

    demoted = apply_owner_action(
        store,
        action_type="demote_crystallized",
        target=f"crystallized:{record_id}",
        owner_id="owner",
        channel="cli",
        note="Owner demoted stale memory.",
        apply=True,
    )

    assert demoted["status"] == "ok"
    assert demoted["record"]["owner_effect"]["owner_demoted_crystallized_record"] is True
    assert demoted["record"]["owner_effect"]["projection_invalidation_recorded"] is True
    assert demoted["result_ref"]["actual_delete"] is False
    assert demoted["result_ref"]["projection_invalidated"] is True
    refreshed = CrystallizedMemoryService(store).read_records("owner_approved.md")[0]
    assert refreshed.frontmatter["canonical_state"] == "demoted"
    assert refreshed.frontmatter["demoted_by"] == "owner"
    assert refreshed.frontmatter["demotion_reason"] == "Owner demoted stale memory."
    assert refreshed.body == "User prefers Meridian summaries."
    coherence = derive_projection_coherence(ledger.read_all(), provider="hindsight", demoted_source_refs={record_id})
    assert coherence["active_projection_count"] == 0
    assert coherence["projection_stale_count"] == 0
    assert coherence["retract_count"] == 1
    substrate_records = SubstrateOperationLedger(
        store.roots.memory_os_root / "system" / "substrate_operations.jsonl"
    ).read_all()
    assert substrate_records[-1]["operation"] == "invalidate"
    assert substrate_records[-1]["reason"] == "owner_demoted"
    assert LocalArtifactProvider(store).recall("Meridian", consumer="test") == []


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
    assert report["approved_proposal_count"] == 1
    assert report["pending_followup_count"] == 1
    assert report["open_followup_count"] == 1
    assert report["awaiting_explicit_execution_count"] == 0
    assert report["execution_ticket_count"] == 0
    assert report["actual_execute"] is False
    assert report["raw_body_included"] is False
    assert report["boundary"]["actual_execute"] is False
    assert report["items"][0]["proposal_id"] == candidate["candidate_id"]
    assert report["items"][0]["followup_state"] == "awaiting_ops_gate_review"
    assert report["items"][0]["execution_ticket_created"] is False
    assert "PRIVATE RAW BODY" not in json.dumps(report, ensure_ascii=False)

    status = owner_review_status_report(store)
    assert status["approved_proposal_followups"]["approved_proposal_count"] == 1
    assert status["approved_proposal_followups"]["pending_followup_count"] == 1


def test_approved_proposal_followup_routes_to_ops_gate_without_execution(tmp_path):
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

    dry_run = route_approved_proposal_followup_to_ops_gate(
        store,
        proposal_id=candidate["candidate_id"],
        owner_id="owner",
        channel="cli",
        apply=False,
    )

    assert dry_run["schema_version"] == "memory-os.approved_proposal_ops_gate.v0"
    assert dry_run["status"] == "ok"
    assert dry_run["dry_run"] is True
    assert dry_run["ops_gate_report_written"] is False
    assert dry_run["execution_ticket_created"] is False
    assert dry_run["boundary"]["actual_execute"] is False
    assert not (tmp_path / "system-modules" / "ops_gate" / "reports.jsonl").exists()
    assert "PRIVATE RAW BODY" not in json.dumps(dry_run, ensure_ascii=False)

    applied = route_approved_proposal_followup_to_ops_gate(
        store,
        proposal_id=candidate["candidate_id"],
        owner_id="owner",
        channel="cli",
        apply=True,
    )

    reports = _jsonl(tmp_path / "system-modules" / "ops_gate" / "reports.jsonl")
    assert applied["status"] == "ok"
    assert applied["dry_run"] is False
    assert applied["ops_gate_report_written"] is True
    assert applied["execution_ticket_created"] is False
    assert applied["boundary"]["actual_execute"] is False
    assert reports[0]["actual_execute"] is False
    assert reports[0]["decisions"][0]["action_id"] == f"proposal_followup:{candidate['candidate_id']}"
    assert "PRIVATE RAW BODY" not in json.dumps(applied, ensure_ascii=False)

    followups = approved_proposal_followups_report(store)
    assert followups["ops_gate_reviewed_count"] == 1
    assert followups["awaiting_ops_gate_count"] == 0
    assert followups["pending_followup_count"] == 0
    assert followups["open_followup_count"] == 1
    assert followups["awaiting_explicit_execution_count"] == 1
    assert followups["unsupported_requires_execution_ticket_count"] == 1
    assert followups["execution_ticket_count"] == 0
    assert followups["actual_execute"] is False
    assert followups["items"][0]["followup_state"] == "unsupported_requires_execution_ticket"

    duplicate = route_approved_proposal_followup_to_ops_gate(
        store,
        proposal_id=candidate["candidate_id"],
        owner_id="owner",
        channel="cli",
        apply=True,
    )

    reports_after_duplicate = _jsonl(tmp_path / "system-modules" / "ops_gate" / "reports.jsonl")
    assert duplicate["status"] == "duplicate_ignored"
    assert duplicate["ops_gate_report_written"] is False
    assert duplicate["execution_ticket_created"] is False
    assert duplicate["boundary"]["actual_execute"] is False
    assert len(reports_after_duplicate) == 1


def test_approved_proposal_followup_batch_routes_pending_to_ops_gate_without_execution(tmp_path):
    store = _store(tmp_path)
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    candidates = [
        proposal_queue.create_candidate(store=store, title=f"Run proposal {index}", body="PRIVATE RAW BODY")
        for index in range(2)
    ]
    for candidate in candidates:
        apply_owner_action(
            store,
            action_type="approve_proposal",
            target=f"proposal:{candidate['candidate_id']}",
            owner_id="owner",
            channel="cli",
            apply=True,
        )

    dry_run = route_pending_approved_proposal_followups_to_ops_gate(
        store,
        owner_id="owner",
        channel="cli",
        apply=False,
    )
    applied = route_pending_approved_proposal_followups_to_ops_gate(
        store,
        owner_id="owner",
        channel="cli",
        apply=True,
    )
    duplicate = route_pending_approved_proposal_followups_to_ops_gate(
        store,
        owner_id="owner",
        channel="cli",
        apply=True,
    )
    followups = approved_proposal_followups_report(store)
    reports = _jsonl(tmp_path / "system-modules" / "ops_gate" / "reports.jsonl")

    assert dry_run["schema_version"] == "memory-os.approved_proposal_ops_gate_batch.v0"
    assert dry_run["eligible_count"] == 2
    assert dry_run["ops_gate_report_written_count"] == 0
    assert applied["status"] == "ok"
    assert applied["ops_gate_report_written_count"] == 2
    assert applied["execution_ticket_created"] is False
    assert applied["actual_execute"] is False
    assert applied["boundary"]["actual_execute"] is False
    assert duplicate["eligible_count"] == 0
    assert duplicate["ops_gate_report_written_count"] == 0
    assert len(reports) == 2
    assert followups["pending_followup_count"] == 0
    assert followups["awaiting_ops_gate_count"] == 0
    assert followups["ops_gate_reviewed_count"] == 2
    assert followups["awaiting_explicit_execution_count"] == 2
    assert followups["execution_ticket_count"] == 0
    assert followups["actual_execute"] is False
    assert "PRIVATE RAW BODY" not in json.dumps(applied, ensure_ascii=False)


def test_auto_route_safe_proposal_followups_to_ops_gate_without_owner_action(tmp_path):
    store = _store(tmp_path)
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    safe = proposal_queue.create_candidate(store=store, title="Adjust report-only follow-up", body="Bounded proposal")
    mature_later = proposal_queue.create_candidate(
        store=store,
        title="self-evolution dry-run proposal",
        body="use the highest evidence signal to prepare a reviewed governance improvement.",
    )

    dry_run = auto_route_safe_proposal_followups_to_ops_gate(store, apply=False)
    applied = auto_route_safe_proposal_followups_to_ops_gate(store, apply=True)
    queue = {item["candidate_id"]: item for item in proposal_queue.read_queue()["items"]}
    reports = _jsonl(tmp_path / "system-modules" / "ops_gate" / "reports.jsonl")
    owner_record_path = owner_actions_path(store.roots)
    owner_records = _jsonl(owner_record_path) if owner_record_path.exists() else []

    assert dry_run["schema_version"] == "memory-os.proposal_followup_auto_route.v0"
    assert dry_run["dry_run"] is True
    assert dry_run["eligible_count"] == 1
    assert dry_run["lane_mode"] == "live_shadow_calibration"
    assert dry_run["shadow_decision_count"] == 0
    assert dry_run["owner_agreement_count"] == 0
    assert dry_run["owner_disagreement_count"] == 0
    assert dry_run["owner_agreement_rate"] == 0.0
    assert dry_run["wilson_95_lower_bound"] == 0.0
    assert dry_run["continue_shadow_comparison"] is True
    assert dry_run["auto_demote_on_first_boundary_or_owner_disagreement"] is True
    assert dry_run["limited_auto_first_canary_max_auto_routes_per_day"] == 1
    assert dry_run["full_auto_eligible"] is False
    assert dry_run["auto_followup_routed_count"] == 0
    assert applied["status"] == "ok"
    assert applied["dry_run"] is False
    assert applied["eligible_count"] == 1
    assert applied["effective_limit"] == 1
    assert applied["current_auto_route_cap_per_day"] == 1
    assert applied["auto_followup_routed_count"] == 1
    assert applied["auto_followup_actual_execute_count"] == 0
    assert applied["auto_followup_policy_write_count"] == 0
    assert applied["auto_followup_actual_send_count"] == 0
    assert applied["boundary"]["actual_execute"] is False
    assert applied["ops_gate"]["ops_gate_report_written_count"] == 1
    assert queue[safe["candidate_id"]]["state"] == "approved_for_proposal"
    assert queue[safe["candidate_id"]]["followup_state"] == "awaiting_ops_gate"
    assert queue[mature_later["candidate_id"]]["state"] == "candidate"
    assert len(reports) == 1
    assert reports[0]["actual_execute"] is False
    assert owner_records == []
    assert "Bounded proposal" not in json.dumps(applied, ensure_ascii=False)

    veto = apply_owner_action(
        store,
        action_type="reject_proposal",
        target=f"proposal:{safe['candidate_id']}",
        owner_id="owner",
        channel="cli",
        apply=True,
    )
    assert veto["status"] == "ok"
    assert proposal_queue.read_queue()["items"][0]["state"] == "owner_declined"


def test_auto_route_safe_proposal_followups_reports_limited_auto_probation_metrics(tmp_path):
    store = _store(tmp_path)
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    for index in range(3):
        sample = proposal_queue.create_candidate(
            store=store,
            title=f"Report-only process motion {index}",
            body="Bounded proposal",
        )
        apply_owner_action(
            store,
            action_type="approve_proposal",
            target=f"proposal:{sample['candidate_id']}",
            owner_id="owner",
            channel="cli",
            apply=True,
        )
    proposal_queue.create_candidate(
        store=store,
        title="Report-only process motion live",
        body="Bounded proposal",
    )

    report = auto_route_safe_proposal_followups_to_ops_gate(store, apply=False)
    applied = auto_route_safe_proposal_followups_to_ops_gate(store, apply=True, limit=10)

    assert report["lane_mode"] == "limited_auto"
    assert report["eligible_sample_count"] == 1
    assert report["shadow_decision_count"] == 3
    assert report["owner_agreement_count"] == 3
    assert report["limited_auto_eligible"] is True
    assert report["full_auto_eligible"] is False
    assert report["owner_disagreement_count"] == 0
    assert report["proposal_kind_coverage"] == ["proposal"]
    assert applied["effective_limit"] == 1
    assert applied["auto_followup_routed_count"] == 1
    assert applied["auto_followup_actual_execute_count"] == 0
    assert applied["auto_followup_policy_write_count"] == 0
    assert applied["auto_followup_actual_send_count"] == 0


def test_auto_route_safe_proposal_followups_full_auto_requires_wilson_evidence(tmp_path):
    store = _store(tmp_path)
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    for index in range(20):
        sample = proposal_queue.create_candidate(
            store=store,
            title=f"Report-only process motion sample {index}",
            body="Bounded proposal",
        )
        action = "reject_proposal" if index >= 18 else "approve_proposal"
        apply_owner_action(
            store,
            action_type=action,
            target=f"proposal:{sample['candidate_id']}",
            owner_id="owner",
            channel="cli",
            apply=True,
        )
    proposal_queue.create_candidate(
        store=store,
        title="Report-only process motion live",
        body="Bounded proposal",
    )

    report = auto_route_safe_proposal_followups_to_ops_gate(store, apply=False)

    assert report["shadow_decision_count"] == 20
    assert report["owner_agreement_count"] == 18
    assert report["owner_disagreement_count"] == 2
    assert report["owner_agreement_rate"] == 0.9
    assert report["wilson_95_lower_bound"] < report["wilson_95_lower_bound_required"]
    assert report["full_auto_eligible"] is False
    assert report["lane_mode"] == "live_shadow_calibration"


def test_auto_route_safe_proposal_followups_reports_limited_auto_idle_after_graduation(tmp_path):
    store = _store(tmp_path)
    for _index in range(3):
        owner_actions_module.append_audit(
            store.roots.audit_path,
            action="proposal_followup_auto_route_to_ops_gate",
            status="ok",
            target="proposal_queue",
            details={
                "auto_followup_routed_count": 1,
                "actual_execute": False,
                "policy_write_count": 0,
            },
        )

    report = auto_route_safe_proposal_followups_to_ops_gate(store, apply=False)
    applied = auto_route_safe_proposal_followups_to_ops_gate(store, apply=True, limit=10)

    assert report["lane_mode"] == "limited_auto"
    assert report["eligible_sample_count"] == 0
    assert report["limited_auto_eligible"] is True
    assert report["limited_auto_graduated"] is True
    assert report["limited_auto_evidence_source"] == "historical_successful_routes"
    assert report["current_auto_route_cap_per_day"] == 3
    assert applied["auto_followup_routed_count"] == 0
    assert applied["actual_execute"] is False
    assert applied["auto_followup_policy_write_count"] == 0
    assert applied["auto_followup_actual_send_count"] == 0


def test_auto_route_safe_proposal_followups_rejects_boundary_and_apply_kind_proposals(tmp_path):
    store = _store(tmp_path)
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    safe = proposal_queue.create_candidate(store=store, title="Report-only process motion", body="Bounded proposal")
    unsafe_send = proposal_queue.create_candidate(store=store, title="Unsafe send", body="Should stay pending")
    unsafe_identity = proposal_queue.create_candidate(store=store, title="Unsafe identity", body="Should stay pending")
    unsafe_policy = proposal_queue.create_candidate(
        store=store,
        title="Unsafe policy",
        body="Should stay pending",
        kind="expression_policy",
        proposal_class="expression_policy:too_frequent",
    )
    unsafe_ticket = proposal_queue.create_candidate(store=store, title="Unsafe ticket", body="Should stay pending")
    queue = proposal_queue.read_queue()
    by_id = {item["candidate_id"]: item for item in queue["items"]}
    by_id[unsafe_send["candidate_id"]]["actual_send"] = True
    by_id[unsafe_identity["candidate_id"]]["boundary"] = {"actual_identity_write": True}
    by_id[unsafe_ticket["candidate_id"]]["execution_ticket_count"] = 1
    proposal_queue._write_queue(queue)

    report = auto_route_safe_proposal_followups_to_ops_gate(store, apply=True)
    updated = {item["candidate_id"]: item for item in proposal_queue.read_queue()["items"]}

    assert report["eligible_count"] == 1
    assert report["auto_followup_routed_count"] == 1
    assert report["owner_action_required_boundary_count"] == 4
    assert report["auto_followup_boundary_rejected_count"] == 4
    assert report["auto_followup_actual_execute_count"] == 0
    assert report["auto_followup_policy_write_count"] == 0
    assert updated[safe["candidate_id"]]["state"] == "approved_for_proposal"
    assert updated[unsafe_send["candidate_id"]]["state"] == "candidate"
    assert updated[unsafe_identity["candidate_id"]]["state"] == "candidate"
    assert updated[unsafe_policy["candidate_id"]]["state"] == "candidate"
    assert updated[unsafe_ticket["candidate_id"]]["state"] == "candidate"


def test_approved_expression_policy_proposal_can_be_explicitly_applied_after_ops_gate(tmp_path):
    store = _store(tmp_path)
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    candidate = proposal_queue.create_candidate(
        store=store,
        title="调整右脑表达策略：too_mechanical 反馈",
        body=(
            "具体改动：降低报告腔，增加自然陪伴式表达。\n"
            "证据：owner 标记 too_mechanical。\n"
            "验收标准：下一次右脑表达提示词包含自然表达约束。\n"
            "后续状态：approved_for_proposal -> OpsGate report-only -> owner manual apply decision。\n"
            "边界：不自动发送，不自动改身份。"
        ),
        kind="expression_policy",
        source_refs=["expression_feedback:too_mechanical"],
    )
    apply_owner_action(
        store,
        action_type="approve_proposal",
        target=f"proposal:{candidate['candidate_id']}",
        owner_id="owner",
        channel="cli",
        apply=True,
    )
    route_approved_proposal_followup_to_ops_gate(
        store,
        proposal_id=candidate["candidate_id"],
        owner_id="owner",
        channel="cli",
        apply=True,
    )

    dry_run = apply_approved_proposal_execution_decision(
        store,
        proposal_id=candidate["candidate_id"],
        owner_id="owner",
        channel="cli",
        owner_approved=True,
        apply=False,
    )

    assert dry_run["schema_version"] == "memory-os.approved_proposal_execution_apply.v0"
    assert dry_run["status"] == "ready"
    assert dry_run["dry_run"] is True
    assert dry_run["apply_kind"] == "expression_policy"
    assert dry_run["policy_write_planned"] is True
    assert dry_run["actual_execute"] is False
    assert dry_run["boundary"]["actual_execute"] is False
    assert not (tmp_path / "system-modules" / "right_brain_expression_adapter" / "policy.json").exists()

    applied = apply_approved_proposal_execution_decision(
        store,
        proposal_id=candidate["candidate_id"],
        owner_id="owner",
        channel="cli",
        owner_approved=True,
        apply=True,
    )

    policy_path = tmp_path / "system-modules" / "right_brain_expression_adapter" / "policy.json"
    apply_log_path = tmp_path / "system-modules" / "right_brain_expression_adapter" / "policy_applies.jsonl"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    apply_records = _jsonl(apply_log_path)
    followups = approved_proposal_followups_report(store)

    assert applied["status"] == "applied"
    assert applied["dry_run"] is False
    assert applied["policy_written"] is True
    assert applied["actual_policy_write"] is True
    assert applied["actual_execute"] is False
    assert applied["execution_ticket_created"] is False
    assert applied["boundary"]["actual_execute"] is False
    assert policy["schema_version"] == "memory-os.right_brain_expression_policy.v0"
    assert policy["applied_from_proposal_id"] == candidate["candidate_id"]
    assert policy["active"] is True
    assert any("少报告腔" in item or "自然" in item for item in policy["tone_guidance"])
    assert apply_records[0]["proposal_id"] == candidate["candidate_id"]
    assert apply_records[0]["actual_policy_write"] is True
    assert apply_records[0]["actual_execute"] is False
    assert followups["policy_apply_count"] == 1
    assert followups["pending_followup_count"] == 0
    assert followups["items"][0]["followup_state"] == "applied_expression_policy"

    duplicate = apply_approved_proposal_execution_decision(
        store,
        proposal_id=candidate["candidate_id"],
        owner_id="owner",
        channel="cli",
        owner_approved=True,
        apply=True,
    )

    assert duplicate["status"] == "duplicate_ignored"
    assert duplicate["policy_written"] is False
    assert len(_jsonl(apply_log_path)) == 1


def test_proposal_followup_surface_exposes_tokenized_explicit_apply(tmp_path):
    store = _store(tmp_path)
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    candidate = proposal_queue.create_candidate(
        store=store,
        title="调整右脑表达策略：too_frequent 反馈",
        body=(
            "具体改动：降低右脑表达触发频次。\n"
            "证据：owner 标记 too_frequent。\n"
            "验收标准：policy.json 写入并保留 rollback。\n"
            "后续状态：approved_for_proposal -> OpsGate report-only -> owner manual apply decision。\n"
            "边界：不创建 generic executor。"
        ),
        kind="expression_policy",
        proposal_class="expression_policy:too_frequent",
        dedupe_key="expression_policy:too_frequent",
        source_refs=["expression_feedback:too_frequent"],
    )
    apply_owner_action(
        store,
        action_type="approve_proposal",
        target=f"proposal:{candidate['candidate_id']}",
        owner_id="owner",
        channel="telegram",
        apply=True,
    )
    route_approved_proposal_followup_to_ops_gate(
        store,
        proposal_id=candidate["candidate_id"],
        owner_id="owner",
        channel="telegram",
        apply=True,
    )

    surface = owner_review_surface_report(
        store,
        operation="proposal_followups",
        owner_id="owner",
        channel="telegram",
    )
    item = surface["proposal_followups"]["items"][0]
    apply_token = item["action_tokens"]["apply_proposal"]

    assert item["followup_state"] == "supported_apply_ready"
    assert item["owner_utterance_examples"] == [f"memory apply {apply_token}"]
    assert item["agent_tool_calls"] == [
        {
            "tool_name": "memory_os_review_reply",
            "arguments": {"action": "apply", "action_token": apply_token},
        }
    ]
    assert surface["boundary"]["actual_execute"] is False

    rendered = render_owner_review_digest(
        store,
        owner_id="owner",
        channel="telegram",
        digest_mode="agenda",
    )
    digest_item = rendered["sections"]["action_required"][0]

    assert digest_item["target_type"] == "proposal_apply"
    assert digest_item["action_tokens"]["apply_proposal"] == apply_token
    assert digest_item["owner_utterance_examples"] == [f"memory apply {apply_token}"]
    assert "显式应用" in digest_item["question"]
    assert "generic executor" in digest_item["consequence"]

    result = parse_owner_review_reply(
        store,
        f"memory apply {apply_token}",
        owner_id="owner",
        channel="telegram",
        apply=True,
    )

    policy_path = tmp_path / "system-modules" / "right_brain_expression_adapter" / "policy.json"
    followups = approved_proposal_followups_report(store)
    owner_actions = _jsonl(owner_actions_path(store.roots))

    assert result["status"] == "ok"
    assert result["parsed"]["action_type"] == "apply_proposal"
    assert result["owner_action_result"]["result_ref"]["status"] == "applied"
    assert result["owner_action_result"]["result_ref"]["policy_written"] is True
    assert result["owner_action_result"]["result_ref"]["actual_execute"] is False
    assert policy_path.exists()
    assert followups["policy_apply_count"] == 1
    assert followups["items"][0]["followup_state"] == "applied_expression_policy"
    assert owner_actions[-1]["action_type"] == "apply_proposal"
    assert owner_actions[-1]["result_ref"]["execution_ticket_created"] is False


def test_approved_memory_sources_policy_proposal_can_be_explicitly_applied_after_ops_gate(tmp_path):
    store = _store(tmp_path)
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    candidate = proposal_queue.create_candidate(
        store=store,
        title="调整记忆来源/召回策略：missing_context 反馈",
        body=(
            "具体改动：记录 MemorySources missing_context policy，后续 record 带 policy_ref 供评估。\n"
            "证据：owner 对 candidate_review 的 MemorySources 反馈 missing_context。\n"
            "验收标准：policy.json 写入，后续 MemorySources record 带 policy_version。\n"
            "后续状态：approved_for_proposal -> OpsGate report-only -> owner manual apply decision。\n"
            "边界：不自动改 route，不执行外部任务。"
        ),
        source_refs=["feature_score:memory_sources_feedback_001"],
        kind="memory_sources_policy",
        proposal_class="memory_sources_policy:missing_context",
        dedupe_key="memory_sources_policy:missing_context:candidate_review:candidate_review",
        proposal_quality={
            "quality_gate": "linked_corrective_memory_sources_feedback",
            "runtime_target": "context_retrieval_policy_review",
            "feedback_rating": "missing_context",
            "routes": ["candidate_review"],
            "query_classes": ["candidate_review"],
            "memory_source_record_refs": ["msrc_policy_001"],
            "linked_memory_source_count": 1,
            "agenda_candidate_id": "agc_memory_sources_001",
            "agenda_promotion_status": "promoted_to_proposal",
            "agenda_maturity_gate": "linked_corrective_memory_sources_feedback",
        },
    )
    apply_owner_action(
        store,
        action_type="approve_proposal",
        target=f"proposal:{candidate['candidate_id']}",
        owner_id="owner",
        channel="telegram",
        apply=True,
    )
    route_approved_proposal_followup_to_ops_gate(
        store,
        proposal_id=candidate["candidate_id"],
        owner_id="owner",
        channel="telegram",
        apply=True,
    )

    dry_run = apply_approved_proposal_execution_decision(
        store,
        proposal_id=candidate["candidate_id"],
        owner_id="owner",
        channel="telegram",
        owner_approved=True,
        apply=False,
    )

    assert dry_run["status"] == "ready"
    assert dry_run["apply_kind"] == "memory_sources_policy"
    assert dry_run["runtime_target"] == "context_retrieval_policy_review"
    assert dry_run["policy_write_planned"] is True
    assert dry_run["actual_execute"] is False
    assert not memory_sources_policy_path(store.roots).exists()

    applied = apply_approved_proposal_execution_decision(
        store,
        proposal_id=candidate["candidate_id"],
        owner_id="owner",
        channel="telegram",
        owner_approved=True,
        apply=True,
    )

    policy = json.loads(memory_sources_policy_path(store.roots).read_text(encoding="utf-8"))
    record = build_memory_source_record(
        roots=store.roots,
        route_report={
            "route": "candidate_review",
            "selected_sections": [{"section": "Current Foreground Task"}],
            "dropped_sections": [],
        },
        selected_sections=[
            ContextSection(
                section="Current Foreground Task",
                text="bounded context",
                source_class="foreground",
                metadata={"source_ids": ["event:evt_policy_001"]},
            )
        ],
        context_router_config={"mode": "apply", "apply_routes": ["all"]},
        router_applied=True,
        prefetch_mode="indexed",
    )
    append_memory_source_record(store.roots, record)
    stats = memory_sources_stats_report(store.roots, hours=24)
    followups = approved_proposal_followups_report(store)

    assert applied["status"] == "applied"
    assert applied["policy_written"] is True
    assert applied["actual_policy_write"] is True
    assert applied["actual_execute"] is False
    assert applied["execution_ticket_created"] is False
    assert policy["schema_version"] == "memory-os.memory_sources_policy.v0"
    assert policy["applied_from_proposal_id"] == candidate["candidate_id"]
    assert policy["selection_policy_changed"] is False
    assert record["policy_ref"]["policy_version"] == policy["policy_version"]
    assert stats["policy_present"] is True
    assert stats["policy_apply_count"] == 1
    assert stats["policy_actual_execute_count"] == 0
    assert stats["policy_raw_body_included_count"] == 0
    assert followups["memory_sources_policy_apply_count"] == 1
    assert followups["items"][0]["followup_state"] == "applied_memory_sources_policy"

    duplicate = apply_approved_proposal_execution_decision(
        store,
        proposal_id=candidate["candidate_id"],
        owner_id="owner",
        channel="telegram",
        owner_approved=True,
        apply=True,
    )

    assert duplicate["status"] == "duplicate_ignored"
    assert duplicate["policy_written"] is False


def test_approved_legacy_template_cleanup_only_closes_legacy_templates_after_ops_gate(tmp_path):
    store = _store(tmp_path)
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    legacy_one = proposal_queue.create_candidate(
        store=store,
        title="Self-Evolution dry-run proposal",
        body="Use the highest feature-maturity evidence signal to prepare a reviewed governance improvement.",
        source_refs=["feature_score:legacy_001"],
        kind="self_evolution",
    )
    legacy_two = proposal_queue.create_candidate(
        store=store,
        title="Self-Evolution dry-run proposal",
        body="Use the highest feature-maturity evidence signal to prepare a reviewed governance improvement.",
        source_refs=["feature_score:legacy_002"],
        kind="self_evolution",
    )
    concrete = proposal_queue.create_candidate(
        store=store,
        title="调整右脑表达策略：too_mechanical 反馈",
        body="具体改动: tune policy\n证据: linked feedback\n验收标准: policy visible\n后续状态: report-only",
        source_refs=["feature_score:concrete"],
        kind="expression_policy",
        proposal_class="expression_policy:too_mechanical",
        dedupe_key="expression_policy:too_mechanical",
    )
    cleanup = proposal_queue.create_candidate(
        store=store,
        title="清理旧 Self-Evolution 模板 proposal",
        body=(
            "具体改动: close only legacy Self-Evolution dry-run proposal backlog.\n"
            "证据: pipeline checker classifies these as legacy template duplicates.\n"
            "验收标准: legacy templates are pressure_blocked; concrete proposals remain open.\n"
            "后续状态: approved_for_proposal -> OpsGate report-only -> owner manual apply decision.\n"
            "边界: no execution ticket and no generic executor."
        ),
        source_refs=["left_brain_pipeline:legacy_template_duplicate_group"],
        kind="proposal_queue_cleanup",
        proposal_class="proposal_queue_legacy_template_cleanup",
        dedupe_key="proposal_queue_legacy_template_cleanup",
    )
    apply_owner_action(
        store,
        action_type="approve_proposal",
        target=f"proposal:{cleanup['candidate_id']}",
        owner_id="owner",
        channel="cli",
        apply=True,
    )
    route_approved_proposal_followup_to_ops_gate(
        store,
        proposal_id=cleanup["candidate_id"],
        owner_id="owner",
        channel="cli",
        apply=True,
    )

    dry_run = apply_approved_proposal_execution_decision(
        store,
        proposal_id=cleanup["candidate_id"],
        owner_id="owner",
        channel="cli",
        owner_approved=True,
        apply=False,
    )

    queue_after_dry_run = {item["candidate_id"]: item for item in proposal_queue.read_queue()["items"]}
    assert dry_run["status"] == "ready"
    assert dry_run["apply_kind"] == "proposal_queue_legacy_template_cleanup"
    assert dry_run["legacy_template_candidate_count"] == 2
    assert dry_run["legacy_template_closed_count"] == 0
    assert queue_after_dry_run[legacy_one["candidate_id"]]["state"] == "candidate"
    assert queue_after_dry_run[legacy_two["candidate_id"]]["state"] == "candidate"

    applied = apply_approved_proposal_execution_decision(
        store,
        proposal_id=cleanup["candidate_id"],
        owner_id="owner",
        channel="cli",
        owner_approved=True,
        apply=True,
    )

    queue = {item["candidate_id"]: item for item in proposal_queue.read_queue()["items"]}
    apply_log_path = tmp_path / "system-modules" / "proposal_queue" / "legacy_template_cleanup_applies.jsonl"
    apply_records = _jsonl(apply_log_path)
    followups = approved_proposal_followups_report(store)

    assert applied["status"] == "applied"
    assert applied["apply_kind"] == "proposal_queue_legacy_template_cleanup"
    assert applied["legacy_template_closed_count"] == 2
    assert applied["non_legacy_touched_count"] == 0
    assert applied["execution_ticket_created"] is False
    assert applied["actual_execute"] is False
    assert applied["boundary"]["actual_execute"] is False
    assert queue[legacy_one["candidate_id"]]["state"] == "pressure_blocked"
    assert queue[legacy_one["candidate_id"]]["followup_state"] == "closed"
    assert queue[legacy_two["candidate_id"]]["state"] == "pressure_blocked"
    assert queue[concrete["candidate_id"]]["state"] == "candidate"
    assert queue[cleanup["candidate_id"]]["followup_state"] == "applied_legacy_template_cleanup"
    assert followups["legacy_template_cleanup_apply_count"] == 1
    assert followups["open_followup_count"] == 0
    assert apply_records[0]["closed_count"] == 2
    assert apply_records[0]["actual_execute"] is False

    duplicate = apply_approved_proposal_execution_decision(
        store,
        proposal_id=cleanup["candidate_id"],
        owner_id="owner",
        channel="cli",
        owner_approved=True,
        apply=True,
    )

    assert duplicate["status"] == "duplicate_ignored"
    assert duplicate["legacy_template_closed_count"] == 0
    assert len(_jsonl(apply_log_path)) == 1


def test_generic_self_evolution_proposal_still_cannot_be_execution_applied(tmp_path):
    store = _store(tmp_path)
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    candidate = proposal_queue.create_candidate(
        store=store,
        title="Self-Evolution dry-run proposal",
        body="Use the highest feature-maturity evidence signal to prepare a reviewed governance improvement.",
        source_refs=["feature_score:legacy"],
        kind="self_evolution",
    )
    apply_owner_action(
        store,
        action_type="approve_proposal",
        target=f"proposal:{candidate['candidate_id']}",
        owner_id="owner",
        channel="cli",
        apply=True,
    )
    route_approved_proposal_followup_to_ops_gate(
        store,
        proposal_id=candidate["candidate_id"],
        owner_id="owner",
        channel="cli",
        apply=True,
    )

    result = apply_approved_proposal_execution_decision(
        store,
        proposal_id=candidate["candidate_id"],
        owner_id="owner",
        channel="cli",
        owner_approved=True,
        apply=True,
    )

    assert result["status"] == "error"
    assert result["reason"] == "unsupported_apply_kind"
    assert result["apply_kind"] == ""
    assert result["actual_execute"] is False
    assert result["execution_ticket_created"] is False


def test_unsupported_approved_proposals_create_typed_execution_tickets_without_execution(tmp_path):
    store = _store(tmp_path)
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    specs = [
        (
            "deep_reflection_self_evolution",
            "Review reflection continuity behavior",
            "event:evt_gov_1",
        ),
        (
            "weekly_consolidation",
            "Weekly consolidation: foreground_conversation_turn",
            "event:evt_weekly_1",
        ),
        (
            "proposal",
            "Fresh deployment proposal queue validation",
            "event:evt_deploy_1",
        ),
    ]
    proposal_ids = []
    for kind, title, source_ref in specs:
        candidate = proposal_queue.create_candidate(
            store=store,
            title=title,
            body="PRIVATE RAW BODY SHOULD NOT LEAK",
            source_refs=[source_ref],
            kind=kind,
        )
        proposal_ids.append(candidate["candidate_id"])
        apply_owner_action(
            store,
            action_type="approve_proposal",
            target=f"proposal:{candidate['candidate_id']}",
            owner_id="owner",
            channel="cli",
            apply=True,
        )
        route_approved_proposal_followup_to_ops_gate(
            store,
            proposal_id=candidate["candidate_id"],
            owner_id="owner",
            channel="cli",
            apply=True,
        )

    results = [
        apply_approved_proposal_execution_decision(
            store,
            proposal_id=proposal_id,
            owner_id="owner",
            channel="cli",
            owner_approved=True,
            apply=True,
            evidence_refs=["commit:73b8b33", "monitor:FAIL=[]"],
            evidence_summary="P0 fresh HEAD archive and monitor closure evidence.",
        )
        for proposal_id in proposal_ids
    ]
    tickets = _jsonl(approved_proposal_execution_tickets_path(store.roots))
    report = approved_proposal_followups_report(store)
    by_title = {item["title"]: item for item in report["items"]}

    assert [result["status"] for result in results] == ["ticket_created", "ticket_created", "evidence_resolved"]
    assert all(result["execution_ticket_created"] is True for result in results)
    assert all(result["actual_execute"] is False for result in results)
    assert all(result["actual_send"] is False for result in results)
    assert len(tickets) == 3
    assert {ticket["proposal_id"] for ticket in tickets} == set(proposal_ids)
    assert all(ticket["raw_body_included"] is False for ticket in tickets)
    assert "PRIVATE RAW BODY" not in json.dumps(tickets, ensure_ascii=False)
    assert report["execution_ticket_count"] == 3
    assert report["ticket_created_count"] == 3
    assert report["unsupported_requires_execution_ticket_count"] == 0
    assert report["supported_apply_ready_count"] == 0
    assert report["awaiting_explicit_execution_count"] == 0
    assert report["awaiting_typed_execution_plan_count"] == 2
    assert report["evidence_resolved_count"] == 1
    assert report["open_followup_count"] == 2
    assert by_title["Review reflection continuity behavior"]["followup_state"] == "awaiting_typed_execution_plan"
    assert by_title["Weekly consolidation: foreground_conversation_turn"]["followup_state"] == "awaiting_typed_execution_plan"
    assert by_title["Fresh deployment proposal queue validation"]["followup_state"] == "evidence_resolved"
    assert by_title["Fresh deployment proposal queue validation"]["evidence_refs"] == [
        "commit:73b8b33",
        "monitor:FAIL=[]",
    ]


def test_typed_execution_tickets_close_weekly_and_deep_reflection_without_execution(tmp_path):
    store = _store(tmp_path)
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    specs = [
        (
            "deep_reflection_self_evolution",
            "Review reflection continuity behavior",
            "Use continuity behavior evidence only.",
            "event:evt_gov_1",
        ),
        (
            "weekly_consolidation",
            "Weekly consolidation: foreground_conversation_turn",
            "PRIVATE WEEKLY RAW BODY",
            "event:evt_weekly_1",
        ),
        (
            "deep_reflection_self_evolution",
            "Tune ordinary memory conversation tone",
            "Keep normal chat tone less report-like.",
            "working:lingering:wrk_1",
        ),
    ]
    proposal_ids: list[str] = []
    for kind, title, body, source_ref in specs:
        candidate = proposal_queue.create_candidate(
            store=store,
            title=title,
            body=body,
            source_refs=[source_ref],
            kind=kind,
        )
        proposal_ids.append(candidate["candidate_id"])
        apply_owner_action(
            store,
            action_type="approve_proposal",
            target=f"proposal:{candidate['candidate_id']}",
            owner_id="owner",
            channel="cli",
            apply=True,
        )
        route_approved_proposal_followup_to_ops_gate(
            store,
            proposal_id=candidate["candidate_id"],
            owner_id="owner",
            channel="cli",
            apply=True,
        )
        created = apply_approved_proposal_execution_decision(
            store,
            proposal_id=candidate["candidate_id"],
            owner_id="owner",
            channel="cli",
            owner_approved=True,
            apply=True,
        )
        assert created["status"] == "ticket_created"

    resolved = [
        apply_approved_proposal_execution_decision(
            store,
            proposal_id=proposal_ids[0],
            owner_id="owner",
            channel="cli",
            owner_approved=True,
            apply=True,
            evidence_refs=["deep_reflection_policy:bounded_fields", "monitor:actual_execute=false"],
            evidence_summary="Continuity behavior policy surface written without runtime execution.",
        ),
        apply_approved_proposal_execution_decision(
            store,
            proposal_id=proposal_ids[1],
            owner_id="owner",
            channel="cli",
            owner_approved=True,
            apply=True,
            evidence_refs=[
                "digest_consolidation:weekly/2026-W21.json",
                "source_event:evt_weekly_1",
                "raw_body_not_included",
            ],
            evidence_summary="Weekly artifact and source event are traceable without raw body exposure.",
        ),
        apply_approved_proposal_execution_decision(
            store,
            proposal_id=proposal_ids[2],
            owner_id="owner",
            channel="cli",
            owner_approved=True,
            apply=True,
            evidence_refs=["deep_reflection_policy:bounded_fields", "monitor:actual_execute=false"],
            evidence_summary="Ordinary tone policy surface written without runtime execution.",
        ),
    ]
    policy = json.loads(deep_reflection_policy_path(store.roots).read_text(encoding="utf-8"))
    applies = _jsonl(deep_reflection_policy_applies_path(store.roots))
    tickets = _jsonl(approved_proposal_execution_tickets_path(store.roots))
    report = approved_proposal_followups_report(store)

    assert [item["status"] for item in resolved] == [
        "bounded_policy_written",
        "evidence_resolved",
        "bounded_policy_written",
    ]
    assert all(item["actual_execute"] is False for item in resolved)
    assert all(item["raw_body_included"] is False for item in resolved)
    assert policy["schema_version"] == "memory-os.deep_reflection_policy.v0"
    assert policy["policy_version"] == 2
    assert policy["live_applied"] is False
    assert policy["actual_execute"] is False
    assert set(policy["applied_from_proposal_ids"]) == {proposal_ids[0], proposal_ids[2]}
    assert policy["continuity_behavior"]["mode"] == "bounded_review_only"
    assert policy["ordinary_tone"]["mode"] == "bounded_review_only"
    assert len(applies) == 2
    assert all(item["actual_execute"] is False for item in applies)
    assert "PRIVATE WEEKLY RAW BODY" not in json.dumps(tickets, ensure_ascii=False)
    assert report["open_followup_count"] == 0
    assert report["awaiting_typed_execution_plan_count"] == 0
    assert report["evidence_resolved_count"] == 1
    assert report["bounded_policy_written_count"] == 2
    assert report["deep_reflection_policy_apply_count"] == 2
    assert report["actual_execute"] is False


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


def test_mark_feedback_allows_distinct_ratings_for_same_memory_source(tmp_path):
    store = _store(tmp_path)
    append_memory_source_record(
        store.roots,
        {
            "schema_version": "memory-os.memory_sources.v0",
            "record_id": "msrc_test_002",
            "created_at": "2026-05-25T00:00:00Z",
            "route": "active_task",
            "query_class": "active_task",
        },
    )

    first = apply_owner_action(
        store,
        action_type="mark_feedback",
        target="memory_source:msrc_test_002",
        owner_id="owner",
        channel="cli",
        rating="too_mechanistic",
        apply=True,
    )
    same_rating = apply_owner_action(
        store,
        action_type="mark_feedback",
        target="memory_source:msrc_test_002",
        owner_id="owner",
        channel="cli",
        rating="too_mechanistic",
        apply=True,
    )
    different_rating = apply_owner_action(
        store,
        action_type="mark_feedback",
        target="memory_source:msrc_test_002",
        owner_id="owner",
        channel="cli",
        rating="missing_context",
        apply=True,
    )

    feedback = _jsonl(memory_sources_feedback_path(store.roots))
    assert first["status"] == "ok"
    assert same_rating["status"] == "duplicate_ignored"
    assert different_rating["status"] == "ok"
    assert [item["rating"] for item in feedback] == ["too_mechanistic", "missing_context"]
    assert first["idempotency_key"].endswith("|mark_feedback:too_mechanistic")
    assert different_rating["idempotency_key"].endswith("|mark_feedback:missing_context")


def test_expression_feedback_records_quality_signal_without_policy_mutation(tmp_path):
    store = _store(tmp_path)

    result = apply_owner_action(
        store,
        action_type="too_mechanical",
        target="expression:expr_test_001",
        owner_id="owner",
        channel="cli",
        note="This sounded like a report.",
        apply=True,
    )

    feedback = _jsonl(expression_feedback_ledger_path(store.roots))[0]
    assert result["status"] == "ok"
    assert result["record"]["target_type"] == "expression"
    assert feedback["draft_id"] == "expr_test_001"
    assert feedback["action_type"] == "too_mechanical"
    assert feedback["live_policy_changed"] is False
    assert feedback["raw_body_included"] is False
    assert result["record"]["boundary"]["actual_send"] is False




def test_expression_feedback_links_to_right_brain_outcome_without_raw_body(tmp_path):
    store = _store(tmp_path)
    outcome_path = tmp_path / "system-modules" / "right_brain_expression_adapter" / "outcomes.jsonl"
    outcome_path.parent.mkdir(parents=True, exist_ok=True)
    outcome_path.write_text(
        json.dumps(
            {
                "schema_version": "memory-os.right_brain_expression_outcome.v0",
                "outcome_id": "rbout_test_001",
                "request_id": "rbexpr_test_001",
                "observed_at": "2026-05-26T12:00:00Z",
                "policy_version": 3,
                "silent": False,
                "outcome_preview": "今天这边很安静，我就在。",
                "outcome_preview_chars": 12,
                "raw_body_included": False,
                "actual_send": False,
                "actual_execute": False,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    result = apply_owner_action(
        store,
        action_type="too_mechanical",
        target="expression:rbout_test_001",
        owner_id="owner",
        channel="telegram",
        note="这句还是有点报告感。",
        apply=True,
    )

    feedback = _jsonl(expression_feedback_ledger_path(store.roots))[0]
    assert result["status"] == "ok"
    assert result["result_ref"]["outcome_id"] == "rbout_test_001"
    assert result["result_ref"]["request_id"] == "rbexpr_test_001"
    assert feedback["draft_id"] == "rbout_test_001"
    assert feedback["outcome_feedback_linked"] is True
    assert feedback["outcome_id"] == "rbout_test_001"
    assert feedback["request_id"] == "rbexpr_test_001"
    assert feedback["policy_version"] == 3
    assert feedback["outcome_silent"] is False
    assert feedback["outcome_preview_chars"] == 12
    assert feedback["outcome_preview"] == ""
    assert feedback["raw_body_included"] is False
    assert feedback["live_policy_changed"] is False
    assert result["record"]["boundary"]["actual_send"] is False


def test_expression_feedback_latest_outcome_alias_links_to_latest_record(tmp_path):
    store = _store(tmp_path)
    outcome_path = tmp_path / "system-modules" / "right_brain_expression_adapter" / "outcomes.jsonl"
    outcome_path.parent.mkdir(parents=True, exist_ok=True)
    records = [
        {"outcome_id": "rbout_old", "request_id": "rbexpr_old", "observed_at": "2026-05-26T10:00:00Z"},
        {
            "outcome_id": "rbout_latest",
            "request_id": "rbexpr_latest",
            "observed_at": "2026-05-26T13:00:00Z",
            "policy_version": 4,
            "silent": False,
            "outcome_preview_chars": 18,
            "raw_body_included": False,
            "actual_send": False,
            "actual_execute": False,
        },
    ]
    outcome_path.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records), encoding="utf-8")

    result = apply_owner_action(
        store,
        action_type="off_voice",
        target="expression:latest_outcome",
        owner_id="owner",
        channel="telegram",
        note="刚才那句不像右脑。",
        apply=True,
    )

    feedback = _jsonl(expression_feedback_ledger_path(store.roots))[0]
    assert result["status"] == "ok"
    assert result["result_ref"]["outcome_id"] == "rbout_latest"
    assert feedback["draft_id"] == "rbout_latest"
    assert feedback["expression_target_id"] == "latest_outcome"
    assert feedback["outcome_feedback_linked"] is True
    assert feedback["policy_version"] == 4


def test_expression_feedback_latest_outcome_alias_is_idempotent_per_resolved_outcome(tmp_path):
    store = _store(tmp_path)
    outcome_path = tmp_path / "system-modules" / "right_brain_expression_adapter" / "outcomes.jsonl"
    outcome_path.parent.mkdir(parents=True, exist_ok=True)
    outcome_path.write_text(
        json.dumps(
            {
                "outcome_id": "rbout_first",
                "request_id": "rbexpr_first",
                "observed_at": "2026-05-26T13:00:00Z",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    first = apply_owner_action(
        store,
        action_type="too_mechanical",
        target="expression:latest_outcome",
        owner_id="owner",
        channel="telegram",
        apply=True,
    )
    with outcome_path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "outcome_id": "rbout_second",
                    "request_id": "rbexpr_second",
                    "observed_at": "2026-05-26T14:00:00Z",
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    second = apply_owner_action(
        store,
        action_type="too_mechanical",
        target="expression:latest_outcome",
        owner_id="owner",
        channel="telegram",
        apply=True,
    )

    feedback = _jsonl(expression_feedback_ledger_path(store.roots))
    assert first["status"] == "ok"
    assert second["status"] == "ok"
    assert [item["outcome_id"] for item in feedback] == ["rbout_first", "rbout_second"]


def test_review_surface_exposes_latest_expression_feedback_context_tokens(tmp_path):
    store = _store(tmp_path)
    outcome_path = tmp_path / "system-modules" / "right_brain_expression_adapter" / "outcomes.jsonl"
    outcome_path.parent.mkdir(parents=True, exist_ok=True)
    outcome_path.write_text(
        json.dumps(
            {
                "schema_version": "memory-os.right_brain_expression_outcome.v0",
                "outcome_id": "rbout_latest_context",
                "request_id": "rbexpr_latest_context",
                "observed_at": "2026-05-26T13:00:00Z",
                "policy_version": 5,
                "silent": False,
                "outcome_preview": "今天这边很安静，我就在。",
                "outcome_preview_chars": 12,
                "raw_body_included": False,
                "actual_send": False,
                "actual_execute": False,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    report = owner_review_surface_report(store, operation="expression_feedback_context", limit=6)

    assert report["status"] == "ok"
    assert report["operation"] == "expression_feedback_context"
    assert report["latest_outcome"]["target_id"] == "rbout_latest_context"
    assert report["latest_outcome"]["expression_preview"] == "今天这边很安静，我就在。"
    assert report["latest_outcome"]["raw_body_included"] is False
    assert report["feedback_actions"]["too_mechanical"]["action"] == "feedback"
    assert report["feedback_actions"]["too_mechanical"]["target_id"] == "rbout_latest_context"
    assert report["feedback_actions"]["too_mechanical"]["owner_utterance_example"].startswith("memory feedback oa_")
    assert report["feedback_actions"]["too_mechanical"]["agent_tool_call"]["tool_name"] == "memory_os_review_reply"
    assert "command" not in report["feedback_actions"]["too_mechanical"]
    assert report["boundary"]["actual_execute"] is False


def test_expression_feedback_context_token_applies_without_digest_binding(tmp_path):
    store = _store(tmp_path)
    outcome_path = tmp_path / "system-modules" / "right_brain_expression_adapter" / "outcomes.jsonl"
    outcome_path.parent.mkdir(parents=True, exist_ok=True)
    outcome_path.write_text(
        json.dumps(
            {
                "schema_version": "memory-os.right_brain_expression_outcome.v0",
                "outcome_id": "rbout_context_token",
                "request_id": "rbexpr_context_token",
                "observed_at": "2026-05-26T13:00:00Z",
                "policy_version": 5,
                "silent": False,
                "outcome_preview_chars": 12,
                "raw_body_included": False,
                "actual_send": False,
                "actual_execute": False,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    surface = owner_review_surface_report(store, operation="expression_feedback_context", limit=6)
    token = surface["feedback_actions"]["too_mechanical"]["action_token"]

    result = parse_owner_review_reply(
        store,
        f"memory feedback {token} too_mechanical",
        owner_id="owner",
        channel="telegram",
        apply=True,
        require_recorded_digest=True,
    )

    feedback = _jsonl(expression_feedback_ledger_path(store.roots))[0]
    assert result["status"] == "ok"
    assert result["parsed"]["target_type"] == "expression"
    assert result["parsed"]["target_id"] == "rbout_context_token"
    assert result["active_digest"]["binding"] == "digest_not_found"
    assert feedback["outcome_id"] == "rbout_context_token"
    assert feedback["outcome_feedback_linked"] is True
    assert feedback["raw_body_included"] is False


def test_provider_expression_feedback_context_supports_structured_tool_reply(tmp_path):
    store = _store(tmp_path)
    outcome_path = tmp_path / "system-modules" / "right_brain_expression_adapter" / "outcomes.jsonl"
    outcome_path.parent.mkdir(parents=True, exist_ok=True)
    outcome_path.write_text(
        json.dumps(
            {
                "schema_version": "memory-os.right_brain_expression_outcome.v0",
                "outcome_id": "rbout_provider_context",
                "request_id": "rbexpr_provider_context",
                "observed_at": "2026-05-26T13:00:00Z",
                "policy_version": 5,
                "silent": False,
                "outcome_preview": "今天这边很安静，我就在。",
                "outcome_preview_chars": 12,
                "raw_body_included": False,
                "actual_send": False,
                "actual_execute": False,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    provider = MemoryOSProvider()
    provider.initialize(
        "session-owner-review",
        hermes_home=str(tmp_path),
        platform="telegram",
        agent_identity="main",
        worker_autostart=False,
    )

    surface = json.loads(
        provider.handle_tool_call(
            "memory_os_review_surface",
            {"operation": "expression_feedback_context", "owner_utterance": "刚才那句还是太机械"},
        )
    )
    token = surface["feedback_actions"]["too_mechanical"]["action_token"]
    result = json.loads(
        provider.handle_tool_call(
            "memory_os_review_reply",
            {
                "action": "feedback",
                "action_token": token,
                "rating": "too_mechanical",
                "owner_utterance": "刚才那句还是太机械",
            },
        )
    )

    feedback = _jsonl(expression_feedback_ledger_path(store.roots))[0]
    assert surface["status"] == "ok"
    assert result["status"] == "ok"
    assert result["tool_input"]["mode"] == "structured"
    assert result["parsed"]["target_id"] == "rbout_provider_context"
    assert feedback["outcome_id"] == "rbout_provider_context"
    assert feedback["outcome_feedback_linked"] is True


def test_review_surface_exposes_latest_memory_sources_feedback_context_tokens(tmp_path):
    store = _store(tmp_path)
    append_memory_source_record(
        store.roots,
        {
            "schema_version": "memory-os.memory_sources.v0",
            "record_id": "msrc_context_001",
            "created_at": "2026-05-27T01:00:00Z",
            "profile": "main",
            "route": "low_clue_recall",
            "query_class": "low_clue_recall",
            "route_reason_codes": ["low_clue_query"],
            "selected": [{"source_class": "memory", "chars": 72, "safe_source_ids": ["evt_context_001"]}],
            "boundary": {"raw_body_included": False},
        },
    )

    report = owner_review_surface_report(store, operation="memory_sources_feedback_context", limit=5)

    assert report["status"] == "ok"
    assert report["operation"] == "memory_sources_feedback_context"
    assert report["latest_memory_source"]["target_id"] == "msrc_context_001"
    assert report["latest_memory_source"]["raw_body_included"] is False
    assert report["latest_memory_source"]["owner_utterance_scope"] == "owner_chat_utterance"
    assert report["latest_memory_source"]["agent_tool_calls"][0]["rating"] == "useful"
    assert report["latest_memory_source"]["agent_tool_calls"][0]["agent_tool_call"] == {
        "tool_name": "memory_os_review_reply",
        "arguments": {
            "action": "feedback",
            "action_token": report["latest_memory_source"]["action_tokens"]["mark_feedback"],
            "rating": "useful",
        },
    }
    assert report["latest_memory_source"]["owner_utterance_examples"][0].startswith("memory feedback oa_")
    assert "action_commands" not in report["latest_memory_source"]
    assert "available_actions" not in report["latest_memory_source"]
    assert report["feedback_actions"]["too_mechanistic"]["action"] == "feedback"
    assert report["feedback_actions"]["too_mechanistic"]["rating"] == "too_mechanistic"
    assert report["feedback_actions"]["too_mechanistic"]["target_id"] == "msrc_context_001"
    assert "memory feedback" in report["feedback_actions"]["too_mechanistic"]["owner_utterance_example"]
    assert report["feedback_actions"]["too_mechanistic"]["owner_utterance_scope"] == "owner_chat_utterance"
    assert report["feedback_actions"]["too_mechanistic"]["agent_tool_call"] == {
        "tool_name": "memory_os_review_reply",
        "arguments": {
            "action": "feedback",
            "action_token": report["feedback_actions"]["too_mechanistic"]["action_token"],
            "rating": "too_mechanistic",
        },
    }
    assert "operator_cli" not in report["feedback_actions"]["too_mechanistic"]
    assert "command" not in report["feedback_actions"]["too_mechanistic"]
    assert report["boundary"]["actual_execute"] is False


def test_memory_sources_feedback_context_token_applies_without_digest_binding(tmp_path):
    store = _store(tmp_path)
    append_memory_source_record(
        store.roots,
        {
            "schema_version": "memory-os.memory_sources.v0",
            "record_id": "msrc_context_token",
            "created_at": "2026-05-27T01:00:00Z",
            "profile": "main",
            "route": "low_clue_recall",
            "query_class": "low_clue_recall",
            "selected": [{"source_class": "memory", "chars": 72, "safe_source_ids": ["evt_context_001"]}],
            "boundary": {"raw_body_included": False},
        },
    )
    surface = owner_review_surface_report(store, operation="memory_sources_feedback_context", limit=5)
    token = surface["feedback_actions"]["too_mechanistic"]["action_token"]

    result = parse_owner_review_reply(
        store,
        f"memory feedback {token} too_mechanistic",
        owner_id="owner",
        channel="telegram",
        apply=True,
        require_recorded_digest=True,
    )

    feedback = _jsonl(memory_sources_feedback_path(store.roots))[0]
    assert result["status"] == "ok"
    assert result["parsed"]["action_type"] == "mark_feedback"
    assert result["parsed"]["target_type"] == "memory_source"
    assert result["parsed"]["target_id"] == "msrc_context_token"
    assert result["active_digest"]["binding"] == "digest_not_found"
    assert feedback["memory_source_record_id"] == "msrc_context_token"
    assert feedback["rating"] == "too_mechanistic"


def test_provider_memory_sources_feedback_context_supports_structured_tool_reply(tmp_path):
    store = _store(tmp_path)
    append_memory_source_record(
        store.roots,
        {
            "schema_version": "memory-os.memory_sources.v0",
            "record_id": "msrc_provider_context",
            "created_at": "2026-05-27T01:00:00Z",
            "profile": "main",
            "route": "context_router",
            "query_class": "ordinary_chat",
            "selected": [{"source_class": "memory", "chars": 50, "safe_source_ids": ["evt_context_002"]}],
            "boundary": {"raw_body_included": False},
        },
    )
    provider = MemoryOSProvider()
    provider.initialize(
        "session-owner-review",
        hermes_home=str(tmp_path),
        platform="telegram",
        agent_identity="main",
        worker_autostart=False,
    )

    surface = json.loads(
        provider.handle_tool_call(
            "memory_os_review_surface",
            {"operation": "memory_sources_feedback_context", "owner_utterance": "这次上下文太机械"},
        )
    )
    token = surface["feedback_actions"]["too_mechanistic"]["action_token"]
    result = json.loads(
        provider.handle_tool_call(
            "memory_os_review_reply",
            {
                "action": "feedback",
                "action_token": token,
                "rating": "too_mechanistic",
                "owner_utterance": "这次上下文太机械",
            },
        )
    )

    feedback = _jsonl(memory_sources_feedback_path(store.roots))[0]
    assert surface["status"] == "ok"
    assert result["status"] == "ok"
    assert result["tool_input"]["mode"] == "structured"
    assert result["parsed"]["target_id"] == "msrc_provider_context"
    assert feedback["memory_source_record_id"] == "msrc_provider_context"
    assert feedback["rating"] == "too_mechanistic"


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
    assert preview["counts"]["action_required_total"] == 2
    assert preview["counts"]["action_required_shown"] == 1
    assert preview["overflow"]["action_required"] == 1
    assert preview["sections"]["action_required"][0]["anchor"] == "A1"
    assert preview["review_aging"]["aged_to_review_suggested_count"] == 0
    assert "Candidate kind=" not in serialized
    assert "RAW PROPOSAL BODY" not in serialized


def test_digest_actions_enabled_is_config_derived_without_auto_execute(tmp_path):
    store = _store(tmp_path)
    append_candidate_queue(store, _candidate())
    save_config({"owner_review": {"enabled": True, "actions_enabled": True}}, tmp_path)

    preview = owner_review_digest_preview(store)
    rendered = render_owner_review_digest(store)

    assert preview["actions_enabled"] is True
    assert rendered["actions_enabled"] is True
    assert rendered["boundary"]["actual_execute"] is False
    assert rendered["sections"]["action_required"][0]["action_tokens"]["approve_candidate"].startswith("oa_")


def test_owner_review_reply_can_revoke_crystallized_record_by_token(tmp_path):
    store = _store(tmp_path)
    append_candidate_queue(store, _candidate())
    _apply_candidate_via_recorded_digest(store, "cand_owner_001")
    record = CrystallizedMemoryService(store).read_records("owner_approved.md")[0]
    record_id = str(record.frontmatter["id"])
    token = "oa_" + hashlib.sha256(
        f"revoke_crystallized|crystallized_record|{record_id}".encode("utf-8")
    ).hexdigest()[:14]

    result = parse_owner_review_reply(store, f"memory revoke {token}", owner_id="owner", channel="cli", apply=True)
    revoked = CrystallizedMemoryService(store).find_record(record_id)
    projection = derive_projection_coherence(
        ProjectionLedger(store.roots.memory_os_root / "system" / "projection_ledger.jsonl").read_all(),
        provider="hindsight",
    )

    assert result["status"] == "ok"
    assert result["parsed"]["action_type"] == "revoke_crystallized"
    assert revoked is not None
    assert revoked.frontmatter["canonical_state"] == "owner_revoked"
    assert result["owner_action_result"]["result_ref"]["projection_invalidated"] is True
    assert projection["retract_count"] == 1


def test_owner_review_reply_can_demote_crystallized_record_by_token(tmp_path):
    store = _store(tmp_path)
    append_candidate_queue(store, _candidate())
    _apply_candidate_via_recorded_digest(store, "cand_owner_001")
    record = CrystallizedMemoryService(store).read_records("owner_approved.md")[0]
    record_id = str(record.frontmatter["id"])
    token = "oa_" + hashlib.sha256(
        f"demote_crystallized|crystallized_record|{record_id}".encode("utf-8")
    ).hexdigest()[:14]

    result = parse_owner_review_reply(store, f"memory demote {token}", owner_id="owner", channel="cli", apply=True)
    demoted = CrystallizedMemoryService(store).find_record(record_id)
    projection = derive_projection_coherence(
        ProjectionLedger(store.roots.memory_os_root / "system" / "projection_ledger.jsonl").read_all(),
        provider="hindsight",
        demoted_source_refs={record_id},
    )

    assert result["status"] == "ok"
    assert result["parsed"]["action_type"] == "demote_crystallized"
    assert demoted is not None
    assert demoted.frontmatter["canonical_state"] == "demoted"
    assert result["owner_action_result"]["result_ref"]["projection_invalidated"] is True
    assert projection["retract_count"] == 1
    assert projection["projection_stale_count"] == 0


def _crystallized_record_id_for_forgery(store) -> str:
    append_candidate_queue(store, _candidate())
    _apply_candidate_via_recorded_digest(store, "cand_owner_001")
    record = CrystallizedMemoryService(store).read_records("owner_approved.md")[0]
    owner_review_rendered_digests_path(store.roots).unlink(missing_ok=True)
    return str(record.frontmatter["id"])


def _legacy_scheme_action_token(action_type: str, target_type: str, target_id: str) -> str:
    """Reproduce the pre-fix keyless oa_ token an attacker can compute offline."""

    return "oa_" + hashlib.sha256(
        f"{action_type}|{target_type}|{target_id}".encode("utf-8")
    ).hexdigest()[:14]


def test_repro_offline_forged_revoke_token_is_refused_without_recorded_digest(tmp_path):
    store = _store(tmp_path)
    record_id = _crystallized_record_id_for_forgery(store)
    forged = _legacy_scheme_action_token("revoke_crystallized", "crystallized_record", record_id)

    result = parse_owner_review_reply(
        store,
        f"memory revoke {forged}",
        owner_id="owner",
        channel="telegram",
        apply=True,
        require_recorded_digest=True,
    )

    after = CrystallizedMemoryService(store).find_record(record_id)
    assert result["status"] == "needs_clarification"
    assert result["reason"] == "digest_not_found_or_expired"
    assert result["active_digest"]["binding"] == "digest_not_found"
    assert after is not None
    assert after.frontmatter.get("canonical_state") != "owner_revoked"


def test_repro_offline_forged_demote_token_is_refused_when_recorded_digest_lacks_it(tmp_path):
    store = _store(tmp_path)
    record_id = _crystallized_record_id_for_forgery(store)
    rendered = render_owner_review_digest(store, owner_id="owner", channel="telegram")
    owner_actions_module._append_owner_review_rendered_digest(store, rendered, channel="telegram")
    forged = _legacy_scheme_action_token("demote_crystallized", "crystallized_record", record_id)
    recorded = _jsonl(owner_review_rendered_digests_path(store.roots))[-1]
    assert forged not in json.dumps(recorded, ensure_ascii=False)

    result = parse_owner_review_reply(
        store,
        f"memory demote {forged}",
        owner_id="owner",
        channel="telegram",
        apply=True,
        require_recorded_digest=True,
    )

    after = CrystallizedMemoryService(store).find_record(record_id)
    assert result["active_digest"]["binding"] == "latest_recorded_digest"
    assert result["status"] == "needs_clarification"
    assert result["reason"] == "action_token_not_found_in_recorded_digest"
    assert after is not None
    assert after.frontmatter.get("canonical_state") != "demoted"


def test_surface_token_digest_optional_allowlist_refuses_ownergate_action_types():
    allowed = owner_actions_module._surface_token_allowed_without_recorded_digest
    for action_type, target_type in (
        ("mark_feedback", "memory_source"),
        ("too_mechanical", "expression"),
        ("apply_proposal", "proposal"),
    ):
        assert allowed({"action_type": action_type, "target_type": target_type}) is True
    for action_type, target_type in (
        ("revoke_crystallized", "crystallized_record"),
        ("demote_crystallized", "crystallized_record"),
        ("approve_candidate", "candidate"),
        ("allow_speak_once", "speak"),
        ("approve_session_mirror_apply", "session_mirror_apply"),
        ("confirm_provisional_crystallized_record", "provisional_crystallized_record"),
        # A future surface map must not widen the hole by reusing a low-risk
        # action type against a governed target, or vice versa.
        ("mark_feedback", "crystallized_record"),
        ("revoke_crystallized", "memory_source"),
    ):
        assert allowed({"action_type": action_type, "target_type": target_type}) is False
    assert allowed({}) is False
    assert allowed(None) is False


def test_proposal_followup_apply_token_still_applies_with_require_recorded_digest(tmp_path):
    store = _store(tmp_path)
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    candidate = proposal_queue.create_candidate(
        store=store,
        title="调整右脑表达策略：too_frequent 反馈",
        body=(
            "具体改动：降低右脑表达触发频次。\n"
            "证据：owner 标记 too_frequent。\n"
            "验收标准：policy.json 写入并保留 rollback。\n"
            "后续状态：approved_for_proposal -> OpsGate report-only -> owner manual apply decision。\n"
            "边界：不创建 generic executor。"
        ),
        kind="expression_policy",
        proposal_class="expression_policy:too_frequent",
        dedupe_key="expression_policy:too_frequent",
        source_refs=["expression_feedback:too_frequent"],
    )
    apply_owner_action(
        store,
        action_type="approve_proposal",
        target=f"proposal:{candidate['candidate_id']}",
        owner_id="owner",
        channel="telegram",
        apply=True,
    )
    route_approved_proposal_followup_to_ops_gate(
        store,
        proposal_id=candidate["candidate_id"],
        owner_id="owner",
        channel="telegram",
        apply=True,
    )
    surface = owner_review_surface_report(
        store,
        operation="proposal_followups",
        owner_id="owner",
        channel="telegram",
    )
    apply_token = surface["proposal_followups"]["items"][0]["action_tokens"]["apply_proposal"]

    result = parse_owner_review_reply(
        store,
        f"memory apply {apply_token}",
        owner_id="owner",
        channel="telegram",
        apply=True,
        require_recorded_digest=True,
    )

    assert result["active_digest"]["binding"] == "digest_not_found"
    assert result["status"] == "ok"
    assert result["parsed"]["action_type"] == "apply_proposal"
    assert result["owner_action_result"]["result_ref"]["status"] == "applied"


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
    assert text.startswith("Memory-OS 审批摘要")
    assert "全貌" in text
    assert "待处理" in text
    assert "未展示" in text
    assert "没展示的不是丢失" in text
    assert "回复方式" in text
    assert "A1/R1/F1 只是列表编号" in text
    assert "Hermes 会继续问你要 approve/reject/allow/feedback" in text
    assert item["anchor"] == "A1"
    assert item["source_module"] in {"proposal_queue", "crystallized_candidates"}
    assert item["question"]
    assert item["suggested_action"]
    assert item["reason"]
    assert item["consequence"]
    assert item["owner_utterance_examples"]
    assert all(example.startswith("memory ") for example in item["owner_utterance_examples"])
    assert "action_commands" not in item
    assert item["raw_body_included"] is False
    assert "memory approve oa_" in text or "memory reject oa_" in text
    assert "完整命令" not in text
    assert "操作:" not in text
    assert "会话回复示例:" in text
    assert "User prefers concise owner-review summaries" in text
    assert "proposed_memory_text" in serialized
    assert "Candidate kind=" not in text
    assert "source_events=" not in text
    assert "sensitivity=" not in text
    assert "RAW PROPOSAL BODY" not in serialized


def test_render_digest_agenda_mode_pushes_only_decisions_not_backlog(tmp_path):
    store = _store(tmp_path)
    append_candidate_queue(store, _candidate())
    append_candidate_queue(
        store,
        CrystallizedCandidate(
            candidate_id="cand_cleanup_001",
            kind="moment",
            body="User: 旧聊天记录 | Assistant: 旧回复内容",
            source_event_ids=["evt_cleanup_001"],
            sensitivity="private",
            tags=["owner-review"],
        ),
    )
    proposal = ProposalQueueModule(tmp_path, profile="main")
    proposal.create_candidate(store=store, title="Agenda proposal", body="RAW PROPOSAL BODY")

    rendered = render_owner_review_digest(store, digest_mode="agenda")
    text = rendered["text"]

    assert rendered["digest_mode"] == "agenda"
    assert rendered["counts"]["action_required_shown"] <= 3
    assert rendered["counts"]["review_suggested_shown"] == 0
    assert rendered["counts"]["fyi_shown"] == 0
    assert text.startswith("Memory-OS 今日审批议程")
    assert "待处理" not in text
    assert "建议你看:" not in text
    assert "仅供了解:" not in text
    assert "本推送只包含审批项和真实告警" in text
    assert "memory approve oa_" in text or "memory reject oa_" in text


def test_agenda_suppresses_generic_self_evolution_template_proposals(tmp_path):
    store = _store(tmp_path)
    proposal = ProposalQueueModule(tmp_path, profile="main")
    proposal.create_candidate(
        store=store,
        title="Self-Evolution dry-run proposal",
        body="Use the highest evidence signal to prepare a reviewed governance improvement.",
        source_refs=["score:one", "score:two", "score:three"],
        kind="self_evolution",
    )

    rendered = render_owner_review_digest(store, digest_mode="agenda")
    review = render_owner_review_digest(store, max_action_required=0, max_review_suggested=1, max_fyi=0)

    assert rendered["counts"]["action_required_shown"] == 0
    assert rendered["counts"]["review_suggested_shown"] == 0
    assert "Self-Evolution dry-run proposal" not in rendered["text"]
    item = review["sections"]["review_suggested"][0]
    assert item["requires_maturation"] is True
    assert item["owner_utterance_examples"] == []
    assert "action_commands" not in item
    assert "缺少具体要调整什么" in item["proposal_detail"]
    assert "不会进入今日审批" in review["text"]


def test_concrete_proposal_agenda_shows_bounded_detail(tmp_path):
    store = _store(tmp_path)
    proposal = ProposalQueueModule(tmp_path, profile="main")
    proposal.create_candidate(
        store=store,
        title="Tune right-brain expression policy",
        body=(
            "基于 owner 标记 too_mechanical，准备一份右脑表达 prompt/cadence 调整方案；"
            "只进入人工 follow-up，不直接修改策略。"
        ),
        source_refs=["feedback:efb_001"],
        kind="expression_policy",
    )

    rendered = render_owner_review_digest(store, digest_mode="agenda")
    item = rendered["sections"]["action_required"][0]

    assert item["requires_maturation"] is False
    assert "too_mechanical" in item["proposal_detail"]
    assert "内容:" in rendered["text"]
    assert "memory approve oa_" in rendered["text"]


def test_agenda_omits_ascii_chinese_transcript_markers_from_proposal_detail(tmp_path):
    store = _store(tmp_path)
    proposal = ProposalQueueModule(tmp_path, profile="main")
    proposal.create_candidate(
        store=store,
        title="Review raw chat shaped proposal",
        body="用户: 私密原始提问\n助手: 私密原始回答",
        source_refs=["feedback:raw_chat"],
        kind="memory_sources_policy",
    )

    rendered = render_owner_review_digest(store, digest_mode="agenda")
    text = rendered["text"]

    assert rendered["counts"]["action_required_shown"] == 1
    assert "用户:" not in text
    assert "助手:" not in text
    assert "私密原始" not in text


def test_agenda_omits_transcript_markers_from_proposal_summary(tmp_path):
    store = _store(tmp_path)
    proposal = ProposalQueueModule(tmp_path, profile="main")
    proposal.create_candidate(
        store=store,
        title="User: raw user line | Assistant: raw assistant line",
        body="具体改动: 只记录为人工处理候选，不直接执行。",
        source_refs=["feedback:raw_title"],
        kind="memory_sources_policy",
    )

    rendered = render_owner_review_digest(store, digest_mode="agenda")
    text = rendered["text"]

    assert rendered["counts"]["action_required_shown"] == 1
    assert "User:" not in text
    assert "Assistant:" not in text
    assert "| Assistant:" not in text
    assert "raw assistant" not in text


def test_agenda_count_matches_rendered_items_when_proposals_are_long(tmp_path):
    store = _store(tmp_path)
    proposal = ProposalQueueModule(tmp_path, profile="main")
    body = (
        "具体改动: 根据用户反馈形成一条可复核策略候选，不直接改变运行时。"
        "证据: " + "长证据片段 " * 80 + " "
        "验收标准: 必须列出影响面、monitor 字段、rollback 和停止条件。"
        "后续状态: approved_for_proposal -> OpsGate report-only -> explicit apply gate."
    )
    for index in range(3):
        proposal.create_candidate(
            store=store,
            title=f"Concrete policy proposal {index + 1}",
            body=body,
            source_refs=[f"feedback:item_{index}"],
            kind="memory_sources_policy",
        )

    rendered = render_owner_review_digest(store, digest_mode="agenda")
    text = rendered["text"]

    assert "本条展示 3 项" in text
    assert "[A1]" in text
    assert "[A2]" in text
    assert "[A3]" in text
    assert "未展示 0 项" in text


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
    assert fyi["owner_utterance_examples"] == []
    assert "available_actions" not in fyi
    assert "需要先整理" in text
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
    assert "全貌" in text
    assert "未展示" in text
    assert "回复方式" in text
    assert not text.endswith("owner-")
    assert rendered["counts"]["action_required_shown"] <= 3
    assert "RAW PROPOSAL BODY" not in text


def test_render_digest_shows_bounded_speak_expression_preview(tmp_path):
    import datetime as _dt

    store = _store(tmp_path)
    module_root = tmp_path / "system-modules" / "wandering_mind"
    module_root.mkdir(parents=True)
    now = _dt.datetime.now(_dt.timezone.utc)
    output_record = {
        "schema_version": "hermes.wandering_mind_output.v0",
        "id": "wout_owner_preview_001",
        "ts": now.isoformat(),
        "profile": "main",
        "module": "wandering_mind",
        "source_event_id": "evt_preview_001",
        "output": "今天我想轻轻提醒你：这条右脑表达需要你看过内容后再决定是否允许一次。",
        "output_ref": "local://wandering_mind/wout_owner_preview_001",
    }
    would_send = {
        "schema_version": "hermes.delivery_would_send.v0",
        "id": "wsend_owner_preview_001",
        "ts": now.isoformat(),
        "profile": "main",
        "module": "wandering_mind",
        "mode": "would_send",
        "actual_send": False,
        "channel": "origin",
        "payload_ref": "local://wandering_mind/wout_owner_preview_001",
        "reason": "wandering_mind_no_send",
    }
    (module_root / "outputs.jsonl").write_text(json.dumps(output_record, ensure_ascii=False) + "\n", encoding="utf-8")
    (module_root / "would_send.jsonl").write_text(json.dumps(would_send, ensure_ascii=False) + "\n", encoding="utf-8")

    rendered = render_owner_review_digest(store, max_action_required=0, max_review_suggested=1, max_fyi=0)
    item = rendered["sections"]["review_suggested"][0]
    text = rendered["text"]

    assert item["target_type"] == "speak"
    assert item["expression_preview"] == output_record["output"]
    assert item["raw_body_included"] is False
    assert "内容: 今天我想轻轻提醒你" in text
    assert "payload_ref=" not in text
    assert "memory allow oa_" in text
    assert "memory feedback oa_" in text
    assert "too_mechanical" in text
    assert "actual_send" not in text

    command = _review_command(rendered, "R1", "too_mechanical")
    result = parse_owner_review_reply(
        store,
        command,
        owner_id="owner",
        channel="cli",
        apply=True,
        max_action_required=0,
        max_review_suggested=1,
        max_fyi=0,
    )
    feedback = _jsonl(expression_feedback_ledger_path(store.roots))[0]

    assert result["status"] == "ok"
    assert result["parsed"]["action_type"] == "too_mechanical"
    assert result["parsed"]["target_type"] == "expression"
    assert result["parsed"]["target_id"] == "wsend_owner_preview_001"
    assert feedback["draft_id"] == "wsend_owner_preview_001"
    assert feedback["action_type"] == "too_mechanical"
    assert feedback["live_policy_changed"] is False
    assert feedback["raw_body_included"] is False


def test_render_digest_hides_transcript_like_speak_expression_preview(tmp_path):
    import datetime as _dt

    store = _store(tmp_path)
    module_root = tmp_path / "system-modules" / "wandering_mind"
    module_root.mkdir(parents=True)
    now = _dt.datetime.now(_dt.timezone.utc)
    output_record = {
        "schema_version": "hermes.wandering_mind_output.v0",
        "id": "wout_raw_preview_001",
        "ts": now.isoformat(),
        "profile": "main",
        "module": "wandering_mind",
        "source_event_id": "evt_preview_001",
        "output": "User: private owner question | Assistant: private assistant answer",
        "output_ref": "local://wandering_mind/wout_raw_preview_001",
    }
    would_send = {
        "schema_version": "hermes.delivery_would_send.v0",
        "id": "wsend_raw_preview_001",
        "ts": now.isoformat(),
        "profile": "main",
        "module": "wandering_mind",
        "mode": "would_send",
        "actual_send": False,
        "channel": "origin",
        "payload_ref": "local://wandering_mind/wout_raw_preview_001",
        "reason": "wandering_mind_no_send",
    }
    (module_root / "outputs.jsonl").write_text(json.dumps(output_record, ensure_ascii=False) + "\n", encoding="utf-8")
    (module_root / "would_send.jsonl").write_text(json.dumps(would_send, ensure_ascii=False) + "\n", encoding="utf-8")

    rendered = render_owner_review_digest(store, max_action_required=0, max_review_suggested=1, max_fyi=0)
    item = rendered["sections"]["review_suggested"][0]
    text = rendered["text"]

    assert item["target_type"] == "speak"
    assert item["expression_preview_suppressed"] is True
    assert "User:" not in item["expression_preview"]
    assert "Assistant:" not in item["expression_preview"]
    assert "private owner question" not in text
    assert "private assistant answer" not in text
    assert "摘要已隐藏" in text
    assert "memory allow" not in text
    assert "allow_speak_once" not in item["action_tokens"]
    assert "memory feedback" in text

    blocked = apply_owner_action(
        store,
        action_type="allow_speak_once",
        target="speak:wsend_raw_preview_001",
        owner_id="owner",
        channel="cli",
        apply=True,
    )
    assert blocked["status"] == "error"
    assert blocked["code"] == "speak_payload_transcript_marker"
    assert not speak_permission_tickets_path(store.roots).exists()


def test_allow_speak_once_sends_once_when_explicit_delivery_enabled(tmp_path, monkeypatch):
    import datetime as _dt

    store = _store(tmp_path)
    module_root = tmp_path / "system-modules" / "wandering_mind"
    module_root.mkdir(parents=True)
    now = _dt.datetime.now(_dt.timezone.utc)
    output_record = {
        "schema_version": "hermes.wandering_mind_output.v0",
        "id": "wout_live_001",
        "ts": now.isoformat(),
        "profile": "main",
        "module": "wandering_mind",
        "output": "今晚别忘了给自己留一点安静的时间。",
        "output_ref": "local://wandering_mind/wout_live_001",
    }
    would_send = {
        "schema_version": "hermes.delivery_would_send.v0",
        "id": "wsend_live_001",
        "ts": now.isoformat(),
        "profile": "main",
        "module": "wandering_mind",
        "mode": "would_send",
        "actual_send": False,
        "channel": "origin",
        "payload_ref": "local://wandering_mind/wout_live_001",
        "reason": "wandering_mind_no_send",
    }
    (module_root / "outputs.jsonl").write_text(json.dumps(output_record, ensure_ascii=False) + "\n", encoding="utf-8")
    (module_root / "would_send.jsonl").write_text(json.dumps(would_send, ensure_ascii=False) + "\n", encoding="utf-8")
    save_config(
        {
            "right_brain_expression": {
                "speak_once_delivery_enabled": True,
                "delivery_adapter": "hermes_send",
                "target_ref": "telegram:12345",
                "hermes_bin": "fake-hermes",
            }
        },
        tmp_path,
    )
    calls = []

    def fake_send(*, hermes_bin, target_ref, message):
        calls.append({"hermes_bin": hermes_bin, "target_ref": target_ref, "message": message})
        return {
            "ok": True,
            "delivery_ref": {
                "adapter": "hermes_send",
                "message_id": "rb-speak-001",
                "target_class": "explicit_target",
            },
        }

    monkeypatch.setattr(owner_actions_module, "_send_owner_review_digest_via_hermes", fake_send)

    result = apply_owner_action(
        store,
        action_type="allow_speak_once",
        target="speak:wsend_live_001",
        owner_id="owner",
        channel="telegram",
        apply=True,
    )
    duplicate = apply_owner_action(
        store,
        action_type="allow_speak_once",
        target="speak:wsend_live_001",
        owner_id="owner",
        channel="telegram",
        apply=True,
    )

    tickets = _jsonl(speak_permission_tickets_path(store.roots))
    assert result["status"] == "ok"
    assert duplicate["status"] == "duplicate_ignored"
    assert len(calls) == 1
    assert calls[0]["hermes_bin"] == "fake-hermes"
    assert calls[0]["target_ref"] == "telegram:12345"
    assert calls[0]["message"] == output_record["output"]
    assert result["record"]["boundary"]["actual_send"] is True
    assert result["record"]["boundary"].get("actual_unapproved_send") is not True
    assert result["result_ref"]["actual_send"] is True
    assert result["result_ref"]["delivery_ref"]["message_id"] == "rb-speak-001"
    assert tickets[0]["status"] == "sent"
    assert tickets[0]["actual_send"] is True
    assert tickets[0]["delivery_ref"]["message_id"] == "rb-speak-001"
    assert tickets[0]["raw_body_included"] is False


def test_review_surface_next_page_uses_latest_owner_home_digest_offsets(tmp_path):
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
    proposal = ProposalQueueModule(tmp_path, profile="main")
    for index in range(5):
        proposal.create_candidate(store=store, title=f"Proposal {index}", body="RAW PROPOSAL BODY")
    delivered = render_owner_review_digest(
        store,
        channel="origin",
        max_action_required=2,
        max_review_suggested=0,
        max_fyi=0,
        record_active=True,
    )

    report = owner_review_surface_report(store, operation="next_page", section="action_required", limit=2)
    serialized = json.dumps(report, ensure_ascii=False)

    assert delivered["counts"]["action_required_shown"] == 2
    assert report["schema_version"] == "memory-os.owner_review_surface.v0"
    assert report["status"] == "ok"
    assert report["operation"] == "next_page"
    assert report["source"] == "latest_owner_home_digest"
    assert report["offsets"]["action_required"] == 2
    assert [item["anchor"] for item in report["sections"]["action_required"]] == ["A3", "A4"]
    assert report["boundary"]["actual_execute"] is False
    assert report["raw_body_included"] is False
    assert "RAW PROPOSAL BODY" not in serialized


def test_review_surface_detail_expands_latest_digest_anchor_without_applying_action(tmp_path):
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
        channel="origin",
        max_action_required=1,
        max_review_suggested=1,
        max_fyi=0,
        record_active=True,
    )

    report = owner_review_surface_report(store, operation="detail", anchor="A1", channel="telegram")
    missing = owner_review_surface_report(store, operation="detail", anchor="R9", channel="telegram")

    assert report["status"] == "ok"
    assert report["binding"] == "latest_owner_home_digest"
    assert report["item"]["anchor"] == "A1"
    assert report["item"]["action_tokens"]["approve_candidate"].startswith("oa_")
    assert "这条候选记忆" in report["text"]
    assert report["boundary"]["actual_send"] is False
    assert not owner_actions_path(store.roots).exists()
    assert missing["status"] == "needs_clarification"
    assert missing["reason"] == "digest_not_found_or_expired"


def test_review_surface_detail_scrubs_actions_from_stale_digest(tmp_path):
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
    first = render_owner_review_digest(
        store,
        channel="origin",
        max_action_required=1,
        max_review_suggested=1,
        max_fyi=0,
        record_active=True,
    )
    old_reject_token = first["sections"]["action_required"][0]["action_tokens"]["reject_candidate"]

    parse_owner_review_reply(
        store,
        _review_command(first, "A1", "reject_candidate"),
        owner_id="owner",
        channel="origin",
        digest_id=first["digest_id"],
        apply=True,
    )
    ProposalQueueModule(tmp_path, profile="main").create_candidate(
        store=store,
        title="Newer proposal",
        body="RAW PROPOSAL BODY",
    )
    render_owner_review_digest(
        store,
        channel="origin",
        max_action_required=1,
        max_review_suggested=1,
        max_fyi=0,
        record_active=True,
    )

    report = owner_review_surface_report(
        store,
        operation="detail",
        action_token=old_reject_token,
        channel="telegram",
    )
    serialized = json.dumps(report, ensure_ascii=False)

    assert report["status"] == "report_only"
    assert report["actions_stale"] is True
    assert report["stale_reason"] == "detail_from_non_latest_digest"
    assert report["item"]["actions_stale"] is True
    assert "action_tokens" not in report["item"]
    assert "agent_tool_calls" not in report["item"]
    assert "owner_utterance_examples" not in report["item"]
    assert old_reject_token not in serialized
    assert "只能查看" in report["text"]
    assert "旧 digest" in report["agent_instruction"]
    assert report["boundary"]["actual_execute"] is False


def test_reply_parser_maps_delivered_digest_anchor_to_owner_action_processor(tmp_path):
    store = _store(tmp_path)
    append_candidate_queue(store, _candidate())
    delivered = render_owner_review_digest(
        store,
        channel="telegram",
        max_action_required=1,
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
        _review_command(delivered, "A1", "approve_candidate"),
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
        _review_command(delivered, "A1", "approve_candidate"),
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
        max_action_required=1,
        max_review_suggested=1,
        max_fyi=0,
        record_active=True,
    )
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    proposal_queue.create_candidate(store=store, title="Newer proposal", body="RAW PROPOSAL BODY")

    result = parse_owner_review_reply(
        store,
        _review_command(rendered, "A1", "reject_candidate"),
        owner_id="owner",
        channel="telegram",
        apply=False,
    )

    assert result["status"] == "ok"
    assert result["active_digest"]["binding"] == "latest_recorded_digest"
    assert result["parsed"]["action_type"] == "reject_candidate"
    assert result["parsed"]["target_id"] == "cand_owner_001"


def test_owner_channel_reply_approves_session_mirror_apply_with_digest_binding(tmp_path):
    store = _store(tmp_path)
    _create_session_state_db(tmp_path / "state.db")
    save_config(
        {
            "owner_review": {
                "recurring_delivery_enabled": True,
                "recurring_delivery_mode": "hermes_cron_agent",
                "recurring_delivery_channel": "telegram",
                "recurring_delivery_target_class": "explicit_target",
            }
        },
        tmp_path,
    )
    rendered = render_owner_review_digest(
        store,
        channel="telegram",
        max_action_required=10,
        max_review_suggested=0,
        max_fyi=0,
        record_active=True,
    )
    command = _session_mirror_review_command(rendered)

    result = parse_owner_review_reply(
        store,
        command,
        owner_id="owner",
        channel="telegram",
        apply=True,
    )

    assert result["status"] == "ok"
    assert result["active_digest"]["delivery_scope"] == "owner_home"
    assert result["parsed"]["action_type"] == "approve_session_mirror_apply"
    record = result["owner_action_result"]["record"]
    assert record["action_type"] == "approve_session_mirror_apply"
    assert record["target_type"] == "session_mirror_apply"
    assert record["target_id"].startswith("production_bounded:")
    assert record["source"] == "latest_owner_home_digest"
    assert record["channel"] == "telegram"
    assert record["digest_id"] == rendered["digest_id"]
    assert record["reply_ingress_id"]
    assert record["token_binding"]["scope"] == "owner_home"
    assert record["token_binding"]["digest_id"] == rendered["digest_id"]
    assert record["token_binding"]["review_item_id"].startswith("review:session_mirror_apply:")
    assert record["token_binding"]["action_token_hash"]
    assert record["owner_effect"]["owner_approved_session_mirror_apply"] is True
    assert record["result_ref"]["approval_scope"] == "session_mirror_production_bounded_apply"
    assert record["result_ref"]["max_sessions"] == 1
    assert record["result_ref"]["stable_scope_id"]
    assert record["result_ref"]["selected_pending_session_fingerprint"]
    assert record["result_ref"]["actual_send"] is False
    assert record["result_ref"]["actual_execute"] is False


def test_provider_owner_review_reply_tool_processes_recorded_digest_before_prefetch(tmp_path):
    store = _store(tmp_path)
    append_candidate_queue(store, _candidate())
    rendered = render_owner_review_digest(
        store,
        channel="telegram",
        max_action_required=1,
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
    command = _review_command(rendered, "A1", "reject_candidate")
    tool_result = json.loads(provider.handle_tool_call("memory_os_review_reply", {"reply": command}))
    context = provider.prefetch(command, session_id="session-owner-review")
    prompt_block = provider.system_prompt_block()

    assert tool_result["status"] == "ok"
    records = _jsonl(owner_actions_path(store.roots))
    assert len(records) == 1
    assert records[0]["action_type"] == "reject_candidate"
    assert records[0]["target_id"] == "cand_owner_001"
    assert records[0]["channel"] == "telegram"
    assert "Owner Review Reply" in context
    assert "processed action: reject_candidate" in prompt_block
    assert "Do not ask the owner to choose another review anchor" in prompt_block


def test_provider_owner_review_reply_tool_accepts_structured_action_token(tmp_path):
    store = _store(tmp_path)
    append_candidate_queue(store, _candidate())
    rendered = render_owner_review_digest(
        store,
        channel="telegram",
        max_action_required=1,
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
    command = _review_command(rendered, "A1", "reject_candidate")
    token = command.split()[2]
    tool_result = json.loads(
        provider.handle_tool_call(
            "memory_os_review_reply",
            {
                "action": "reject",
                "action_token": token,
                "owner_utterance": "reject R1",
            },
        )
    )
    provider.sync_turn("reject R1", "Rejected.", session_id="session-owner-review")

    assert tool_result["status"] == "ok"
    assert tool_result["tool_input"]["mode"] == "structured"
    assert tool_result["tool_input"]["owner_utterance"] == "reject R1"
    records = _jsonl(owner_actions_path(store.roots))
    assert len(records) == 1
    assert records[0]["action_type"] == "reject_candidate"
    assert records[0]["target_id"] == "cand_owner_001"
    assert store.read_events() == []
    heartbeat = MemoryOSRuntime(store).heartbeat()
    assert heartbeat["processed_event_count"] == 0
    assert heartbeat["working_created_count"] == 0
    assert heartbeat["candidate_created_count"] == 0


def test_provider_owner_review_surface_tool_is_read_only_for_next_page(tmp_path):
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
    proposal = ProposalQueueModule(tmp_path, profile="main")
    for index in range(4):
        proposal.create_candidate(store=store, title=f"Proposal {index}", body="RAW PROPOSAL BODY")
    render_owner_review_digest(
        store,
        channel="origin",
        max_action_required=1,
        max_review_suggested=0,
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

    result = json.loads(
        provider.handle_tool_call(
            "memory_os_review_surface",
            {"operation": "next_page", "section": "action_required", "limit": 2},
        )
    )

    assert result["status"] == "ok"
    assert result["operation"] == "next_page"
    assert [item["anchor"] for item in result["sections"]["action_required"]] == ["A2", "A3"]
    assert result["boundary"]["actual_execute"] is False
    assert not owner_actions_path(store.roots).exists()
    assert "RAW PROPOSAL BODY" not in json.dumps(result, ensure_ascii=False)


def test_provider_owner_review_reply_tool_rejects_incomplete_structured_input(tmp_path):
    store = _store(tmp_path)
    provider = MemoryOSProvider()
    provider.initialize(
        "session-owner-review",
        hermes_home=str(tmp_path),
        platform="telegram",
        agent_identity="main",
        worker_autostart=False,
    )

    result = json.loads(
        provider.handle_tool_call(
            "memory_os_review_reply",
            {
                "action": "approve",
                "owner_utterance": "approve A1",
            },
        )
    )
    provider.sync_turn("approve A1", "Which item?", session_id="session-owner-review")

    assert result["status"] == "needs_clarification"
    assert result["reason"] == "missing_or_invalid_action_token"
    assert result["tool_input"]["mode"] == "structured"
    assert not owner_actions_path(store.roots).exists()
    assert store.read_events() == []


def test_provider_owner_review_reply_tool_makes_sync_turn_idempotent(tmp_path):
    store = _store(tmp_path)
    append_candidate_queue(store, _candidate())
    rendered = render_owner_review_digest(
        store,
        channel="telegram",
        max_action_required=1,
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
    command = _review_command(rendered, "A1", "reject_candidate")
    provider.handle_tool_call("memory_os_review_reply", {"reply": command})
    provider.sync_turn(command, "ack", session_id="session-owner-review")

    records = _jsonl(owner_actions_path(store.roots))
    assert len(records) == 1
    assert records[0]["action_type"] == "reject_candidate"
    assert store.read_events() == []
    heartbeat = MemoryOSRuntime(store).heartbeat()
    assert heartbeat["processed_event_count"] == 0
    assert heartbeat["working_created_count"] == 0
    assert heartbeat["candidate_created_count"] == 0
    assert [item.candidate_id for item in read_candidate_queue(store)] == ["cand_owner_001"]
    audit = read_audit_entries(store.roots.audit_path)
    ingress = [item for item in audit if item.get("action") == "owner_review_reply_ingress"]
    assert {item["details"]["phase"] for item in ingress} == {"tool_call"}


def test_provider_owner_review_reply_tool_skips_unprefixed_token_sync_capture(tmp_path):
    store = _store(tmp_path)
    append_candidate_queue(store, _candidate())
    rendered = render_owner_review_digest(
        store,
        channel="telegram",
        max_action_required=1,
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
    command = _review_command(rendered, "A1", "reject_candidate").removeprefix("memory ")
    tool_result = json.loads(provider.handle_tool_call("memory_os_review_reply", {"reply": command}))
    provider.sync_turn(command, "Approved.", session_id="session-owner-review")

    assert tool_result["status"] == "ok"
    assert len(_jsonl(owner_actions_path(store.roots))) == 1
    assert store.read_events() == []
    heartbeat = MemoryOSRuntime(store).heartbeat()
    assert heartbeat["processed_event_count"] == 0
    assert heartbeat["working_created_count"] == 0
    assert heartbeat["candidate_created_count"] == 0


def test_provider_owner_review_reply_sync_turn_warns_and_skips_when_tool_was_not_called(tmp_path):
    store = _store(tmp_path)
    append_candidate_queue(store, _candidate())
    rendered = render_owner_review_digest(
        store,
        channel="telegram",
        max_action_required=1,
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
    command = _review_command(rendered, "A1", "reject_candidate")
    provider.sync_turn(command, "ack", session_id="session-owner-review")

    assert not owner_actions_path(store.roots).exists()
    assert store.read_events() == []
    heartbeat = MemoryOSRuntime(store).heartbeat()
    assert heartbeat["processed_event_count"] == 0
    assert heartbeat["working_created_count"] == 0
    assert heartbeat["candidate_created_count"] == 0
    assert [item.candidate_id for item in read_candidate_queue(store)] == ["cand_owner_001"]
    audit = read_audit_entries(store.roots.audit_path)
    warnings = [item for item in audit if item.get("action") == "owner_review_reply_tool_not_called"]
    assert len(warnings) == 1


def test_provider_owner_review_reply_tool_falls_back_to_recurring_delivery_channel(tmp_path):
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
        max_action_required=1,
        max_review_suggested=0,
        max_fyi=0,
        record_active=True,
    )
    append_candidate_queue(store, _candidate())
    rendered = render_owner_review_digest(
        store,
        channel="cli",
        max_action_required=1,
        max_review_suggested=0,
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
    provider.handle_tool_call("memory_os_review_reply", {"reply": _review_command(rendered, "A1", "reject_candidate")})

    records = _jsonl(owner_actions_path(store.roots))
    assert len(records) == 1
    assert records[0]["action_type"] == "reject_candidate"
    assert records[0]["target_id"] == "cand_owner_001"
    assert records[0]["channel"] == "cli"


def test_provider_owner_review_reply_tool_uses_owner_home_binding_not_platform_label(tmp_path):
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
        max_action_required=1,
        max_review_suggested=1,
        max_fyi=0,
        record_active=True,
    )
    rendered = render_owner_review_digest(
        store,
        channel="origin",
        max_action_required=1,
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
    command = _review_command(rendered, "A1", "reject_candidate")
    provider.handle_tool_call("memory_os_review_reply", {"reply": command})
    context = provider.prefetch(command, session_id="session-owner-review")

    records = _jsonl(owner_actions_path(store.roots))
    assert len(records) == 1
    assert records[0]["action_type"] == "reject_candidate"
    assert records[0]["channel"] == "telegram"
    assert "latest_owner_home_digest" in context


def test_provider_owner_review_reply_tool_requires_recorded_digest(tmp_path):
    store = _store(tmp_path)
    provider = MemoryOSProvider()
    provider.initialize(
        "session-owner-review",
        hermes_home=str(tmp_path),
        platform="telegram",
        agent_identity="main",
        worker_autostart=False,
    )

    result = json.loads(provider.handle_tool_call("memory_os_review_reply", {"reply": "memory reject oa_deadbeef"}))
    context = provider.prefetch("memory reject oa_deadbeef", session_id="session-owner-review")

    assert result["status"] == "needs_clarification"
    assert "digest_not_found_or_expired" in context
    assert not owner_actions_path(store.roots).exists()


def test_provider_owner_review_reply_tool_accepts_punctuation_and_ignores_chatter(tmp_path):
    store = _store(tmp_path)
    append_candidate_queue(store, _candidate())
    rendered = render_owner_review_digest(
        store,
        channel="telegram",
        max_action_required=1,
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
    chatter_result = json.loads(
        chatter.handle_tool_call("memory_os_review_reply", {"reply": "普通聊天里提到 memory reject oa_deadbeef"})
    )
    assert chatter_result["status"] == "ignored"
    assert not owner_actions_path(store.roots).exists()

    legacy = MemoryOSProvider()
    legacy.initialize(
        "session-owner-review",
        hermes_home=str(tmp_path),
        platform="telegram",
        agent_identity="main",
        worker_autostart=False,
    )
    legacy_result = json.loads(legacy.handle_tool_call("memory_os_review_reply", {"reply": "reject R1"}))
    assert legacy_result["status"] == "ignored"
    assert not owner_actions_path(store.roots).exists()

    provider = MemoryOSProvider()
    provider.initialize(
        "session-owner-review",
        hermes_home=str(tmp_path),
        platform="telegram",
        agent_identity="main",
        worker_autostart=False,
    )
    command = _review_command(rendered, "A1", "reject_candidate") + "。"
    provider.handle_tool_call("memory_os_review_reply", {"reply": command})
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


def test_hindsight_curation_finding_gets_owner_gated_decision_tokens(tmp_path):
    from datetime import datetime as _dt, timezone as _tz

    store = _store(tmp_path)
    advisor_root = tmp_path / "system-modules" / "left_brain_advisor"
    advisor_root.mkdir(parents=True)
    advisor_root.joinpath("reports.jsonl").write_text(
        json.dumps(
            {
                "schema_version": "memory-os.left_brain_advisor.v0",
                "report_id": "lba_hcur",
                "created_at": _dt.now(_tz.utc).isoformat(),
                "findings": [
                    {
                        "schema_version": "memory-os.left_brain_advisor_finding.v0",
                        "finding_id": "lbf_hcur_1",
                        "target_type": "hindsight_curation",
                        "source_key": "hindsight_governance_signals",
                        "projection_id": "mproj_hcur",
                        "owner_visible": True,
                        "priority": "review_suggested",
                        "summary": "Hindsight governance metadata reports suggestion_count=1.",
                        "reason": "review-only curation suggestion",
                        "safe_source_ids": ["mproj_hcur"],
                        "actions_suppressed": False,
                        "allowed_action_type": "owner_gated_hindsight_curation_decision",
                        "actual_execute": False,
                        "hindsight_write": False,
                    }
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    rendered = render_owner_review_digest(store, max_action_required=0, max_review_suggested=3, max_fyi=0)
    item = rendered["sections"]["review_suggested"][0]
    result = apply_owner_action(
        store,
        action_type="retain_hindsight_curation",
        target="hindsight_curation:lbf_hcur_1",
        owner_id="owner",
        channel="telegram",
        apply=True,
    )
    decisions = _jsonl(hindsight_curation_decisions_path(store.roots))

    assert item["target_type"] == "hindsight_curation"
    assert set(item["action_tokens"]) == {
        "retain_hindsight_curation",
        "reject_hindsight_curation",
        "demote_hindsight_curation",
    }
    assert result["status"] == "ok"
    assert result["result_ref"]["actual_hindsight_write"] is False
    assert result["result_ref"]["actual_hindsight_delete"] is False
    assert result["result_ref"]["actual_execute"] is False
    assert decisions[0]["curation_decision"] == "retain"
    assert decisions[0]["actual_hindsight_write"] is False
    assert decisions[0]["actual_hindsight_delete"] is False
    assert decisions[0]["actual_hindsight_demote"] is False
    assert decisions[0]["actual_execute"] is False
    assert decisions[0]["actual_send"] is False
    assert decisions[0]["actual_policy_write"] is False
    assert decisions[0]["actual_route_score_write"] is False
    assert decisions[0]["hindsight_authoritative"] is False
    assert decisions[0]["advisory_only"] is True
    assert decisions[0]["boundary"]["hindsight_write"] is False
    assert decisions[0]["boundary"]["actual_send"] is False
    assert decisions[0]["boundary"]["actual_execute"] is False
    assert decisions[0]["boundary"]["actual_identity_write"] is False
    assert decisions[0]["boundary"]["actual_relationship_write"] is False
    assert decisions[0]["boundary"]["actual_crystallized_approval"] is False
    assert decisions[0]["boundary"]["actual_policy_write"] is False
    assert decisions[0]["boundary"]["actual_route_score_write"] is False


def test_hindsight_curation_rejects_forged_target(tmp_path):
    store = _store(tmp_path)

    result = apply_owner_action(
        store,
        action_type="reject_hindsight_curation",
        target="hindsight_curation:lbf_missing",
        owner_id="owner",
        channel="telegram",
        apply=True,
    )

    assert result["status"] == "error"
    assert result["code"] == "hindsight_curation_finding_not_found"
    assert not hindsight_curation_decisions_path(store.roots).exists()


def test_left_brain_review_items_aggregate_repeated_source_findings(tmp_path):
    store = _store(tmp_path)
    advisor_root = tmp_path / "system-modules" / "left_brain_advisor"
    advisor_root.mkdir(parents=True)
    findings = [
        {
            "finding_id": f"lbf_noise_{index}",
            "target_type": "left_brain_advisor_finding",
            "source_key": "runtime_logs",
            "owner_visible": True,
            "priority": "review_suggested",
            "summary": f"runtime_logs finding {index}",
            "reason": "fixture",
            "actions_suppressed": True,
        }
        for index in range(4)
    ]
    advisor_root.joinpath("reports.jsonl").write_text(
        json.dumps(
            {
                "schema_version": "memory-os.left_brain_advisor.v0",
                "report_id": "lba_burden",
                "created_at": "2026-06-03T01:00:00Z",
                "findings": findings,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    queue = owner_review_queue_report(store, limit=20)
    items = queue["items"]

    assert len([item for item in items if item.get("target_id", "").startswith("lbf_noise_")]) == 2
    aggregates = [item for item in items if item.get("owner_burden_aggregate")]
    assert len(aggregates) == 1
    assert aggregates[0]["aggregated_source_key"] == "runtime_logs"
    assert aggregates[0]["aggregated_count"] == 2
    assert aggregates[0]["priority"] == "fyi"


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


def test_deliver_once_sends_bounded_digest_through_hermes_owner_channel_when_owner_triggered(
    tmp_path, monkeypatch
):
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
                "hermes_bin": "fake-hermes",
            }
        },
        tmp_path,
    )
    calls = []

    def fake_send(*, hermes_bin, target_ref, message):
        calls.append({"hermes_bin": hermes_bin, "target_ref": target_ref, "message": message})
        return {
            "ok": True,
            "delivery_ref": {
                "adapter": "hermes_send",
                "message_id": "msg-owner-review-001",
                "target_class": "explicit_target",
            },
        }

    monkeypatch.setattr(owner_actions_module, "_send_owner_review_digest_via_hermes", fake_send)

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

    assert result["status"] == "sent"
    assert duplicate["status"] == "duplicate_ignored"
    assert result["record"]["blocked_reasons"] == []
    assert result["record"]["boundary"]["actual_send"] is True
    assert result["record"]["boundary"]["actual_unapproved_send"] is False
    assert result["record"]["owner_effect"]["owner_approved_digest_delivery"] is True
    assert result["record"]["delivery_ref"]["message_id"] == "msg-owner-review-001"
    assert calls[0]["hermes_bin"] == "fake-hermes"
    assert calls[0]["target_ref"] == "telegram:12345"
    assert "Memory-OS 审批摘要" in calls[0]["message"]
    assert "RAW PROPOSAL BODY" not in calls[0]["message"]

    status = owner_review_delivery_status_report(store)
    assert status["delivery_count"] == 2
    assert status["sent_count"] == 1
    assert status["duplicate_ignored_count"] == 1
    assert status["owner_approved_digest_delivery_count"] == 1
    assert status["unapproved_send_count"] == 0
    assert status["raw_body_included_count"] == 0
    sent_records = [record for record in _jsonl(owner_review_deliveries_path(store.roots)) if record["result"] == "sent"]
    assert sent_records[0]["delivery_ref"]["message_id"] == "msg-owner-review-001"


def test_deliver_once_dry_run_returns_ready_without_sending(tmp_path, monkeypatch):
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

    def fail_send(**_kwargs):
        raise AssertionError("dry-run must not call Hermes send")

    monkeypatch.setattr(owner_actions_module, "_send_owner_review_digest_via_hermes", fail_send)
    files_before = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    result = deliver_owner_review_digest_once(
        store,
        owner_id="owner",
        delivery_key="rh34d-dry-run",
        owner_triggered=True,
        apply=False,
    )

    assert result["status"] == "ready"
    assert result["dry_run"] is True
    assert result["record"]["boundary"]["actual_send"] is False
    assert not owner_review_deliveries_path(store.roots).exists()
    files_after = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert files_after == files_before


def test_delivery_gate_blocks_unsupported_delivery_adapter(tmp_path):
    store = _store(tmp_path)
    append_candidate_queue(store, _candidate())
    save_config(
        {
            "owner_review": {
                "enabled": True,
                "channel": "telegram",
                "target_ref": "telegram:12345",
                "direct_message": True,
                "delivery_enabled": True,
                "delivery_adapter": "custom_shell",
            }
        },
        tmp_path,
    )

    gate = owner_review_delivery_gate_report(store)

    assert gate["status"] == "blocked"
    assert "delivery_adapter_unsupported" in gate["blocked_reasons"]
    assert gate["boundary"]["actual_send"] is False


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


# ── P5: provisional crystallized record review items and owner actions ──


def test_provisional_crystallized_review_items_generates_queue_items(tmp_path):
    """Provisional records appear as review items with countdown and actions."""
    import datetime as _dt

    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose

    store = _store(tmp_path)
    service = CrystallizedMemoryService(store)

    now = _dt.datetime.now(_dt.timezone.utc)
    expires_at = (now + _dt.timedelta(days=7)).isoformat()

    candidate = CrystallizedCandidate(
        candidate_id="cand_p5_001",
        kind="moment",
        body="Provisional memory for review.",
        source_event_ids=["evt_001"],
    )
    decision = ApprovalDecision(
        candidate_id="cand_p5_001",
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="resolver",
        reviewed_at=now.isoformat(),
        source_state="resolver_approved",
        provisional=True,
        expires_at=expires_at,
    )
    service.write_approved_record(candidate, decision, file_name="owner_approved.md")

    items = owner_actions_module._provisional_crystallized_review_items(store, closed=set())
    assert len(items) == 1
    item = items[0]
    assert item["target_type"] == "provisional_crystallized_record"
    assert "confirm_provisional_crystallized_record" in item["action_tokens"]
    assert "reject_provisional_crystallized_record" in item["action_tokens"]
    assert "剩" in item["summary"]
    assert "d)" in item["summary"]
    # remaining_days uses int(seconds/86400), so a 7-day window may floor to 6
    assert item["remaining_days"] >= 6


def test_provisional_review_items_priority_based_on_expiry(tmp_path):
    """Priority escalates as expiry approaches — <=3d is action_required."""
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
    import datetime as _dt

    store = _store(tmp_path)
    service = CrystallizedMemoryService(store)

    soon = (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=2)).isoformat()
    far = (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=10)).isoformat()

    for idx, (expires, _expected_priority) in enumerate([
        (soon, "action_required"),
        (far, "fyi"),
    ]):
        candidate = CrystallizedCandidate(
            candidate_id=f"cand_prio_{idx}",
            kind="moment",
            body=f"Priority test body {idx}.",
            source_event_ids=[f"evt_{idx}"],
        )
        decision = ApprovalDecision(
            candidate_id=f"cand_prio_{idx}",
            purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
            reviewer="resolver",
            reviewed_at="2026-06-17T00:00:00Z",
            source_state="resolver_approved",
            provisional=True,
            expires_at=expires,
        )
        service.write_approved_record(candidate, decision, file_name="owner_approved.md")

    items = owner_actions_module._provisional_crystallized_review_items(store, closed=set())
    assert len(items) == 2
    for item in items:
        if "cand_prio_0" in item["provisional_body"] or "Priority test body 0" in item["summary"]:
            assert item["priority"] == "action_required", f"Expected action_required, got {item['priority']}"
        elif "cand_prio_1" in item["provisional_body"] or "Priority test body 1" in item["summary"]:
            assert item["priority"] == "fyi", f"Expected fyi, got {item['priority']}"


def test_provisional_review_items_recurrence_escalation(tmp_path):
    """Records with same body >=3 times get action_required regardless of expiry."""
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
    import datetime as _dt

    store = _store(tmp_path)
    service = CrystallizedMemoryService(store)
    far = (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=10)).isoformat()

    for idx in range(3):
        candidate = CrystallizedCandidate(
            candidate_id=f"cand_recur_{idx}",
            kind="moment",
            body="Same content appears three times.",
            source_event_ids=[f"evt_{idx}"],
        )
        decision = ApprovalDecision(
            candidate_id=f"cand_recur_{idx}",
            purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
            reviewer="resolver",
            reviewed_at="2026-06-17T00:00:00Z",
            source_state="resolver_approved",
            provisional=True,
            expires_at=far,
        )
        service.write_approved_record(candidate, decision, file_name="owner_approved.md")

    items = owner_actions_module._provisional_crystallized_review_items(store, closed=set())
    assert len(items) == 3
    for item in items:
        assert item["priority"] == "action_required", f"Expected action_required for recurrence, got {item['priority']}"
        assert item["recurrence_count"] == 3
        assert "high-recurrence" in item["summary"]


def test_confirm_provisional_through_owner_action(tmp_path):
    """Owner can confirm a provisional record via apply_owner_action."""
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose

    store = _store(tmp_path)
    service = CrystallizedMemoryService(store)

    candidate = CrystallizedCandidate(
        candidate_id="cand_confirm_001",
        kind="moment",
        body="Will be confirmed by owner.",
        source_event_ids=["evt_001"],
    )
    decision = ApprovalDecision(
        candidate_id="cand_confirm_001",
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="resolver",
        reviewed_at="2026-06-17T00:00:00Z",
        source_state="resolver_approved",
        provisional=True,
        expires_at="2026-06-24T00:00:00Z",
    )
    service.write_approved_record(candidate, decision, file_name="owner_approved.md")
    records = service.read_records("owner_approved.md")
    record_id = records[0].frontmatter["id"]

    result = apply_owner_action(
        store,
        action_type="confirm_provisional_crystallized_record",
        target=f"provisional_crystallized_record:{record_id}",
        owner_id="owner",
        apply=True,
    )
    assert result["status"] in {"applied", "ok"}
    assert result.get("result_ref", {}).get("reason") == "legacy_permanent_action_rejected"

    records_after = service.read_records("owner_approved.md")
    fm = records_after[0].frontmatter
    assert fm.get("provisional") is True


def test_reject_provisional_through_owner_action(tmp_path):
    """Owner can reject a provisional record via apply_owner_action."""
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose

    store = _store(tmp_path)
    service = CrystallizedMemoryService(store)

    candidate = CrystallizedCandidate(
        candidate_id="cand_reject_001",
        kind="moment",
        body="Will be rejected by owner.",
        source_event_ids=["evt_001"],
    )
    decision = ApprovalDecision(
        candidate_id="cand_reject_001",
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="resolver",
        reviewed_at="2026-06-17T00:00:00Z",
        source_state="resolver_approved",
        provisional=True,
        expires_at="2026-06-24T00:00:00Z",
    )
    service.write_approved_record(candidate, decision, file_name="owner_approved.md")
    records = service.read_records("owner_approved.md")
    record_id = records[0].frontmatter["id"]

    result = apply_owner_action(
        store,
        action_type="reject_provisional_crystallized_record",
        target=f"provisional_crystallized_record:{record_id}",
        owner_id="owner",
        apply=True,
    )
    assert result["status"] in {"applied", "ok"}

    records_after = service.read_records("owner_approved.md")
    fm = records_after[0].frontmatter
    from plugins.memory.memory_os.crystallized import is_active_crystallized_frontmatter

    assert is_active_crystallized_frontmatter(fm) is False
    assert fm["canonical_state"] == "provisional_rejected"


def test_reject_provisional_sets_provisional_rejected_state(tmp_path):
    """invalidate_provisional_record with reason='owner_rejected' sets state correctly."""
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
    from plugins.memory.memory_os.crystallized import (
        is_active_crystallized_frontmatter,
        INACTIVE_CANONICAL_STATES,
    )

    store = _store(tmp_path)
    service = CrystallizedMemoryService(store)

    candidate = CrystallizedCandidate(
        candidate_id="cand_rejstate_001",
        kind="moment",
        body="Rejected state test.",
        source_event_ids=["evt_001"],
    )
    decision = ApprovalDecision(
        candidate_id="cand_rejstate_001",
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="resolver",
        reviewed_at="2026-06-17T00:00:00Z",
        source_state="resolver_approved",
        provisional=True,
        expires_at="2026-06-24T00:00:00Z",
    )
    service.write_approved_record(candidate, decision, file_name="owner_approved.md")
    records = service.read_records("owner_approved.md")
    record_id = records[0].frontmatter["id"]

    result = service.invalidate_provisional_record(
        record_id, reason="owner_rejected", invalidated_by="owner",
    )
    assert result["canonical_state_changed"] is True
    assert "provisional_rejected" in INACTIVE_CANONICAL_STATES

    records_after = service.read_records("owner_approved.md")
    fm = records_after[0].frontmatter
    assert fm["canonical_state"] == "provisional_rejected"
    assert is_active_crystallized_frontmatter(fm) is False


# ── Transcript marker leak counterfactuals ──────────────────────────


def test_provisional_crystallized_body_with_transcript_marker_is_suppressed(tmp_path):
    """Counterfactual: provisional body with 'User:' must be suppressed in queue item."""
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
    import datetime as _dt

    store = _store(tmp_path)
    service = CrystallizedMemoryService(store)
    now = _dt.datetime.now(_dt.timezone.utc)
    expires_at = (now + _dt.timedelta(days=2)).isoformat()

    candidate = CrystallizedCandidate(
        candidate_id="cand_transcript_body",
        kind="moment",
        body="User: 这段对话包含原始转录标记 | Assistant: 应该被摘要隐藏",
        source_event_ids=["evt_transcript_body"],
    )
    decision = ApprovalDecision(
        candidate_id="cand_transcript_body",
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="resolver",
        reviewed_at=now.isoformat(),
        source_state="resolver_approved",
        provisional=True,
        expires_at=expires_at,
    )
    service.write_approved_record(candidate, decision, file_name="owner_approved.md")

    items = owner_actions_module._provisional_crystallized_review_items(store, closed=set())
    assert len(items) == 1
    item = items[0]
    # Counterfactual: without the fix, summary would contain "User:" / "Assistant:"
    assert "User:" not in item["summary"]
    assert "Assistant:" not in item["summary"]
    assert "摘要隐藏" in item["summary"]


def test_provisional_crystallized_clean_body_passed_through(tmp_path):
    """Clean provisional body is rendered normally (not falsely suppressed)."""
    from plugins.memory.memory_os.approval import ApprovalDecision, ApprovalPurpose
    import datetime as _dt

    store = _store(tmp_path)
    service = CrystallizedMemoryService(store)
    now = _dt.datetime.now(_dt.timezone.utc)
    expires_at = (now + _dt.timedelta(days=2)).isoformat()

    candidate = CrystallizedCandidate(
        candidate_id="cand_clean",
        kind="moment",
        body="这个候选记忆描述了一个用户偏好：喜欢简洁的中文回答。",
        source_event_ids=["evt_clean"],
    )
    decision = ApprovalDecision(
        candidate_id="cand_clean",
        purpose=ApprovalPurpose.APPROVE_FOR_CRYSTALLIZED,
        reviewer="resolver",
        reviewed_at=now.isoformat(),
        source_state="resolver_approved",
        provisional=True,
        expires_at=expires_at,
    )
    service.write_approved_record(candidate, decision, file_name="owner_approved.md")

    items = owner_actions_module._provisional_crystallized_review_items(store, closed=set())
    assert len(items) == 1
    item = items[0]
    # Clean body should pass through normally
    assert "摘要隐藏" not in item["summary"]
    assert "简洁的中文回答" in item["summary"]


def test_contains_transcript_marker_includes_all_consolidation_markers():
    """_contains_transcript_marker must detect all markers that _candidate_needs_consolidation used."""
    # Markers that were previously only in _candidate_needs_consolidation
    for marker in ("菸草:", "菸草：", "agentcoco:", "agentcoco："):
        assert owner_actions_module._contains_transcript_marker(
            f"some text {marker} more text"
        ), f"_contains_transcript_marker should detect {marker!r}"


def test_candidate_needs_consolidation_delegates_to_contains_transcript_marker():
    """_candidate_needs_consolidation delegates to _contains_transcript_marker for markers."""
    # Every standard transcript marker triggers both functions
    for text in (
        "User: hello",
        "Assistant: hi there",
        "用户: 你好",
        "用户：你好",
        "助手: 你好",
        "助手：你好",
        "| assistant: response",
        "| user: query",
    ):
        assert owner_actions_module._candidate_needs_consolidation(text) is True, \
            f"_candidate_needs_consolidation should return True for {text!r}"
        assert owner_actions_module._contains_transcript_marker(text) is True, \
            f"_contains_transcript_marker should return True for {text!r}"


def test_proposal_body_with_transcript_marker_not_in_agenda_text(tmp_path):
    """Counterfactual: proposal body with transcript markers must not leak into agenda digest."""
    store = _store(tmp_path)
    proposal = ProposalQueueModule(tmp_path, profile="main")
    proposal.create_candidate(
        store=store,
        title="一个正常的 proposal 标题",
        body="具体改动: User: 这是原始对话 | Assistant: 不应该出现在 digest 里",
        source_refs=["feedback:raw_body"],
        kind="memory_sources_policy",
    )

    rendered = render_owner_review_digest(store, digest_mode="agenda")
    text = rendered["text"]

    # Counterfactual: without the fix, "User:" / "Assistant:" in body would leak
    assert "User:" not in text
    assert "Assistant:" not in text
    # Clean title should still appear
    assert "正常的 proposal 标题" in text


# ── Fix 3: candidate_aggregation outcome surfaces in owner digest ───────────


def test_status_report_exposes_candidate_aggregation_block(tmp_path):
    store = _store(tmp_path)
    from plugins.memory.memory_os.crystallized import write_candidate_aggregation_status

    # No lane run yet → available=False
    status = owner_review_status_report(store)
    assert status["candidate_aggregation"]["available"] is False

    write_candidate_aggregation_status(
        store,
        summary={
            "candidates_read": 10,
            "pending": 2,
            "already_triaged": 8,
            "promoted_count": 3,
            "rejected_demoted_count": 1,
            "demoted_count": 2,
            "fleeting_count": 2,
            "compacted_count": 4,
        },
    )

    status = owner_review_status_report(store)
    block = status["candidate_aggregation"]
    assert block["available"] is True
    assert block["promoted_count"] == 3
    assert block["compacted_count"] == 4
    assert block["last_tick"] is not None


def test_digest_fyi_includes_candidate_aggregation_when_available(tmp_path):
    store = _store(tmp_path)
    from plugins.memory.memory_os.crystallized import write_candidate_aggregation_status

    write_candidate_aggregation_status(
        store,
        summary={
            "candidates_read": 10,
            "pending": 2,
            "already_triaged": 8,
            "promoted_count": 3,
            "rejected_demoted_count": 1,
            "demoted_count": 2,
            "fleeting_count": 2,
            "compacted_count": 4,
        },
    )

    preview = owner_review_digest_preview(store)
    fyi_items = preview.get("sections", {}).get("fyi", [])
    aggr_item = next(
        (it for it in fyi_items if it.get("target_id") == "candidate_aggregation"),
        None,
    )
    assert aggr_item is not None, "candidate_aggregation fyi item must appear when a lane has run"
    assert "promoted=3" in aggr_item["summary"]
    assert aggr_item["source_module"] == "candidate_aggregation"


# ── P2 fix: _review_consequence / _review_question / _review_suggested_action ──
# must not lie for provisional_crystallized_record / knob_override, whose
# approval DOES change state (see owner_actions.py ~3639-3651 apply_owner_action
# dispatch and ~3821-3839 _validate_action_target for the actual apply semantics).


def test_review_consequence_truthful_for_provisional_crystallized_record():
    """confirm_provisional_crystallized_record is a deterministically-rejected
    legacy no-op (apply_owner_action dispatch at owner_actions.py:3639-3641
    always returns status=rejected/legacy_permanent_action_rejected), while
    reject_provisional_crystallized_record DOES invalidate the provisional
    record (:3642-3647). The old generic fallback ('仅供了解；不需要状态变更。')
    was false for this type — reject is a real, material state change."""
    text = owner_actions_module._review_consequence("provisional_crystallized_record")
    assert text != "仅供了解；不需要状态变更。"
    assert "confirm" in text
    assert "reject" in text


def test_review_consequence_truthful_for_knob_override():
    """Both confirm_provisional_knob_override (writes a permanent override
    record, owner_actions.py:3669-3724) and reject_provisional_knob_override
    (reverts to prior_value, :3727-3741) are real state changes — the
    generic 'no state change' fallback was false for this type too."""
    text = owner_actions_module._review_consequence("knob_override")
    assert text != "仅供了解；不需要状态变更。"
    assert "confirm" in text
    assert "reject" in text


def test_review_question_has_specific_branch_for_provisional_and_knob_override():
    item_provisional = {"remaining_days": 4}
    question = owner_actions_module._review_question("provisional_crystallized_record", item_provisional)
    assert question != "请看一下这条 Memory-OS 状态信号。"
    assert "4" in question

    item_knob = {"knob_name": "clearance_pair_top_k"}
    question2 = owner_actions_module._review_question("knob_override", item_knob)
    assert question2 != "请看一下这条 Memory-OS 状态信号。"
    assert "clearance_pair_top_k" in question2


def test_review_suggested_action_does_not_claim_no_action_needed():
    """The default fallback ('不需要操作' — 'no action needed') is false for
    both types: real confirm/reject actions exist and change state (for
    provisional_crystallized_record, confirm specifically is a disabled
    no-op that must be called out, not silently defaulted past)."""
    actions_provisional = [
        {"owner_utterance_example": "confirm the provisional record"},
        {"owner_utterance_example": "reject the provisional record"},
    ]
    suggestion = owner_actions_module._review_suggested_action(
        actions_provisional, "provisional_crystallized_record",
    )
    assert suggestion != "不需要操作"
    assert "reject the provisional record" in suggestion

    actions_knob = [
        {"owner_utterance_example": "confirm the knob override"},
        {"owner_utterance_example": "reject the knob override"},
    ]
    suggestion2 = owner_actions_module._review_suggested_action(actions_knob, "knob_override")
    assert suggestion2 != "不需要操作"
    assert "confirm the knob override" in suggestion2
    assert "reject the knob override" in suggestion2


# ── P2 fix: repeat_decision_item_count was hardcoded to 0 ──────────────────


def test_repeat_decision_item_count_zero_with_no_prior_digest(tmp_path):
    """No rendered digest ever recorded → nothing can repeat."""
    store = _store(tmp_path)
    count = owner_actions_module._repeat_decision_item_count(store, [{"review_item_id": "review:candidate:x"}])
    assert count == 0


def test_repeat_decision_item_count_counts_by_stable_review_item_id(tmp_path):
    """Counts by the stable review_item_id key, not display text — an item
    whose summary/question text changed between renders (but whose identity
    is the same target_type:target_id) must still be counted as a repeat."""
    store = _store(tmp_path)
    rendered = {
        "digest_id": "d1",
        "created_at": "2026-07-01T00:00:00Z",
        "profile": "main",
        "owner_id": "owner",
        "status": "ok",
        "sections": {
            "action_required": [{"review_item_id": "review:candidate:cand_1", "summary": "old wording"}],
            "review_suggested": [{"review_item_id": "review:knob_override:ko_1"}],
            "fyi": [],
        },
    }
    owner_actions_module._append_owner_review_rendered_digest(store, rendered, channel="test")

    current_items = [
        {"review_item_id": "review:candidate:cand_1", "summary": "brand new wording, does not matter"},
        {"review_item_id": "review:candidate:cand_2"},
        {"review_item_id": "review:knob_override:ko_1"},
    ]
    count = owner_actions_module._repeat_decision_item_count(store, current_items)
    assert count == 2


def test_repeat_decision_item_count_integration_across_two_digest_renders(tmp_path):
    """End-to-end: a candidate that is still pending across two rendered
    digests must be counted as a repeat in the second digest's burden."""
    store = _store(tmp_path)
    append_candidate_queue(store, _candidate())

    # First render — persisted as the "latest previously-rendered digest".
    render_owner_review_digest(store, owner_id="owner", channel="cli", record_active=True)

    # Candidate is still pending (not approved/rejected) — it reappears in
    # the freshly generated agenda, with the SAME review_item_id.
    report = owner_review_queue_report(store)
    burden = report["burden"]
    assert burden["repeat_decision_item_count"] >= 1


def _raise_candidate_aggregation_status(monkeypatch):
    from plugins.memory.memory_os import crystallized as crystallized_module

    def _boom(_store):
        raise RuntimeError("aggregation status unavailable")

    monkeypatch.setattr(crystallized_module, "latest_candidate_aggregation_status", _boom)


def test_candidate_aggregation_status_error_record_uses_warning_severity(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _raise_candidate_aggregation_status(monkeypatch)

    report = owner_review_status_report(store)

    records = _jsonl(store.roots.memory_os_root / "system" / "error_records.jsonl")
    matching = [
        record
        for record in records
        if record.get("error_code") == "candidate_aggregation_status_read_failed"
    ]
    assert report["candidate_aggregation"]["available"] is False
    assert matching
    # Downstream consumers filter on exact severity == "warning"; "warn" is
    # silently dropped.
    assert matching[-1]["severity"] == "warning"


def test_candidate_aggregation_error_record_write_failure_falls_back_to_audit(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _raise_candidate_aggregation_status(monkeypatch)
    original_append = owner_actions_module._append_jsonl

    def _refuse_error_record_writes(path, record):
        if str(path).endswith("error_records.jsonl"):
            raise OSError("error record surface unavailable")
        return original_append(path, record)

    monkeypatch.setattr(owner_actions_module, "_append_jsonl", _refuse_error_record_writes)

    report = owner_review_status_report(store)

    entries = [
        entry
        for entry in read_audit_entries(store.roots.audit_path)
        if entry.get("action") == "owner_digest_error_record_failed"
        and (entry.get("details") or {}).get("operation") == "candidate_aggregation_status_read"
    ]
    assert report["candidate_aggregation"]["available"] is False
    # Without the fallback both the original failure and the recording failure
    # vanish into `except Exception: pass`.
    assert entries
    details = entries[-1]["details"]
    assert entries[-1]["status"] == "warning"
    assert details["component"] == "owner_actions._candidate_aggregation_status_block"
    assert details["original_error_type"] == "RuntimeError"
    assert details["error_record_write_error_type"] == "OSError"
