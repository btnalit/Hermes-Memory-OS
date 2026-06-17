import json

from plugins.memory.memory_os.fixtures import build_event, build_sannai_multi_root_fixture
from plugins.memory.memory_os.inner_drive import classify_event_for_inner_drive
from plugins.memory.memory_os.prefetch import build_prefetch, continuity_selector_report
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.schema import EventEnvelope
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.modules.evidence.scoring import EvidenceScoringModule
from plugins.modules.governance.feedback_bridge import (
    GovernanceFeedbackBridgeModule,
    governance_feedback_manifest,
)
from plugins.modules.governance.ops_gate import OpsGateModule
from plugins.modules.governance.proposal_queue import ProposalQueueModule
from plugins.modules.governance.self_evolution import SelfEvolutionGovernorModule
from plugins.system.lifecycle import ModuleLifecycle


def _store(tmp_path, *, profile="main"):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile=profile)
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def _append_foreground_event(store, *, seed=1, summary="Owner asked for a governance feedback bridge."):
    event = EventEnvelope.from_dict(
        {
            **build_event(seed=seed, profile="main"),
            "source": "telegram",
            "kind": "conversation_turn",
            "summary": summary,
        }
    )
    store.append_event(event)
    return event


def _seed_governance_artifacts(tmp_path, store):
    _append_foreground_event(store)
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    evidence = EvidenceScoringModule(tmp_path, profile="main")
    evidence.score_all(store=store, proposal_queue=proposal_queue)
    ops_gate = OpsGateModule(tmp_path, profile="main")
    ops_gate.run_once(
        store=store,
        proposed_actions=[
            {"id": "restart-main", "kind": "gateway_restart", "target": "10.20.2.88 hermes-gateway.service"}
        ],
    )
    proposal = proposal_queue.create_candidate(
        store=store,
        title="Bridge should surface governance state",
        body="PRIVATE proposal body must not be mirrored into Memory-OS governance feedback.",
        source_refs=["score:score_a", "event:event_a"],
    )
    proposal_queue.transition(
        store=store,
        candidate_id=proposal["candidate_id"],
        decision="approve",
        reviewer="owner",
        note="visible to proposal queue only",
    )
    governor = SelfEvolutionGovernorModule(tmp_path, profile="main")
    governor.run_once(
        store=store,
        ops_gate=ops_gate,
        proposal_queue=proposal_queue,
        evidence_scoring=evidence,
    )
    return {
        "proposal_queue": proposal_queue,
        "evidence": evidence,
        "ops_gate": ops_gate,
        "governor": governor,
    }


def test_governance_feedback_manifest_installs_through_lifecycle(tmp_path):
    lifecycle = ModuleLifecycle(
        tmp_path,
        profile="main",
        available_dependencies=("memory_os", "scheduler", "evidence_scoring", "ops_gate", "proposal_queue", "self_evolution", "speak_gate"),
    )

    status = lifecycle.install(governance_feedback_manifest())
    enabled = lifecycle.enable("governance_feedback")

    assert status.installed is True
    assert enabled.enabled is True
    assert enabled.delivery_mode == "no-send"
    assert lifecycle.doctor("governance_feedback").status == "ok"


def test_governance_feedback_dry_run_does_not_write_events(tmp_path):
    store = _store(tmp_path)
    modules = _seed_governance_artifacts(tmp_path, store)
    before = len(store.read_events())
    bridge = GovernanceFeedbackBridgeModule(tmp_path, profile="main")

    result = bridge.run_once(store=store, dry_run=True, **modules)

    assert result["status"] == "ok"
    assert result["dry_run"] is True
    assert result["would_write_event_count"] >= 4
    assert len(store.read_events()) == before


def test_governance_feedback_writes_summary_only_events_and_is_idempotent(tmp_path):
    store = _store(tmp_path)
    modules = _seed_governance_artifacts(tmp_path, store)
    bridge = GovernanceFeedbackBridgeModule(tmp_path, profile="main")

    first = bridge.run_once(store=store, dry_run=False, **modules)
    second = bridge.run_once(store=store, dry_run=False, **modules)
    governance_events = [event for event in store.read_events() if event.source == "governance_feedback"]

    assert first["written_event_count"] >= 4
    assert second["written_event_count"] == 0
    assert second["already_emitted_count"] == first["written_event_count"]
    assert {event.kind for event in governance_events} >= {
        "governance_evidence_scored",
        "governance_ops_gate_decision",
        "governance_proposal_transitioned",
        "governance_self_evolution_reported",
    }
    rendered = json.dumps([event.to_dict() for event in governance_events], ensure_ascii=False)
    assert "PRIVATE proposal body" not in rendered
    for event in governance_events:
        assert event.body_policy == "summary_only"
        if event.kind in ("governance_ops_gate_decision",):
            assert event.safe_ref["source_class"] == "self_activity"
        else:
            assert event.safe_ref["source_class"] == "governance"
        assert event.safe_ref["drive_policy"] == "evidence_only"
        assert event.safe_ref["candidate_allowed"] is False
        assert event.safe_ref["body_policy"] == "summary_only"


def test_governance_feedback_skips_when_no_new_events_are_pending(tmp_path):
    store = _store(tmp_path)
    modules = _seed_governance_artifacts(tmp_path, store)
    bridge = GovernanceFeedbackBridgeModule(tmp_path, profile="main")

    first = bridge.run_once(store=store, dry_run=False, **modules)
    second = bridge.run_once(store=store, dry_run=False, **modules)
    status = bridge.status()

    assert first["status"] == "ok"
    assert second["status"] == "skipped"
    assert second["skipped"] is True
    assert second["cadence_skipped"] is True
    assert second["reason"] == "no_new_governance_feedback_events"
    assert second["written_event_count"] == 0
    assert status["generated_count"] == 1
    assert status["skipped_count"] == 1


def test_governance_feedback_ignores_duplicate_self_evolution_noop_reports(tmp_path):
    class DuplicateSelfEvolution:
        def read_reports(self):
            return [
                {
                    "schema_version": "hermes.self_evolution.report.v0",
                    "profile": "main",
                    "status": "ok",
                    "proposal_created": False,
                    "skipped": True,
                    "novelty_skipped": True,
                    "reason": "duplicate_unresolved_proposal",
                    "score_refs": ["score:1"],
                }
            ]

    store = _store(tmp_path)
    bridge = GovernanceFeedbackBridgeModule(tmp_path, profile="main")

    result = bridge.run_once(store=store, dry_run=False, self_evolution=DuplicateSelfEvolution())

    assert result["status"] == "skipped"
    assert result["source_event_count"] == 0
    assert result["written_event_count"] == 0
    assert result["event_kinds"] == {}
    assert not [event for event in store.read_events() if event.kind == "governance_self_evolution_reported"]


def test_governance_feedback_consumes_expression_feedback_without_live_mutation(tmp_path):
    store = _store(tmp_path)
    expression_ledger = tmp_path / "memory-os" / "system" / "expression_feedback_ledger.jsonl"
    expression_ledger.parent.mkdir(parents=True, exist_ok=True)
    expression_ledger.write_text(
        json.dumps(
            {
                "schema_version": "hermes.memory_os.expression_feedback.v0",
                "feedback_id": "efb_1",
                "created_at": "2026-05-26T00:00:00+00:00",
                "profile": "main",
                "draft_id": "expr_1",
                "action_type": "too_mechanical",
                "raw_body_included": False,
                "live_policy_changed": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    bridge = GovernanceFeedbackBridgeModule(tmp_path, profile="main")

    result = bridge.run_once(store=store, dry_run=False)
    governance_events = [event for event in store.read_events() if event.kind == "governance_expression_feedback"]

    assert result["written_event_count"] == 1
    assert result["event_kinds"]["governance_expression_feedback"] == 1
    assert governance_events
    assert governance_events[0].safe_ref["candidate_allowed"] is False
    assert governance_events[0].safe_ref["body_policy"] == "summary_only"
    assert "raw_body" not in json.dumps(governance_events[0].to_dict(), ensure_ascii=False)


def test_governance_feedback_consumes_memory_sources_feedback_without_route_mutation(tmp_path):
    store = _store(tmp_path)
    feedback_ledger = tmp_path / "memory-os" / "system" / "memory_sources_feedback.jsonl"
    feedback_ledger.parent.mkdir(parents=True, exist_ok=True)
    feedback_ledger.write_text(
        json.dumps(
            {
                "schema_version": "memory-os.memory_sources_feedback.v0",
                "feedback_id": "msfb_1",
                "created_at": "2026-05-26T00:00:00Z",
                "profile": "main",
                "memory_source_record_id": "msrc_1",
                "route": "ordinary_memory",
                "query_class": "ordinary_memory",
                "rating": "missing_context",
                "note": "bounded feedback note",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    bridge = GovernanceFeedbackBridgeModule(tmp_path, profile="main")

    result = bridge.run_once(store=store, dry_run=False)
    governance_events = [event for event in store.read_events() if event.kind == "governance_memory_sources_feedback"]

    assert result["written_event_count"] == 1
    assert result["event_kinds"]["governance_memory_sources_feedback"] == 1
    assert governance_events
    safe_ref = governance_events[0].safe_ref
    assert safe_ref["candidate_allowed"] is False
    assert safe_ref["body_policy"] == "summary_only"
    assert safe_ref["memory_source_record_id"] == "msrc_1"
    assert safe_ref["memory_sources_feedback_rating"] == "missing_context"
    rendered = json.dumps(governance_events[0].to_dict(), ensure_ascii=False)
    assert "live_route_changed=false" in rendered
    assert "raw_body" not in rendered


def test_governance_feedback_enters_continuity_but_not_inner_drive_working(tmp_path):
    store = _store(tmp_path)
    modules = _seed_governance_artifacts(tmp_path, store)
    bridge = GovernanceFeedbackBridgeModule(tmp_path, profile="main")
    bridge.run_once(store=store, dry_run=False, **modules)

    report = continuity_selector_report(store)
    context = build_prefetch("治理反馈现在有什么？", budget_chars=4000, store=store)
    governance_events = [event for event in store.read_events() if event.source == "governance_feedback"]
    decisions = [classify_event_for_inner_drive(event) for event in governance_events]

    assert report["selected_by_source_class"]["governance"] >= 1
    assert "Continuity Bridge" in context
    assert "governance/" in context
    assert all(decision.drive_policy == "evidence_only" for decision in decisions)
    assert all(decision.working_kind == "" for decision in decisions)
    assert all(decision.candidate_allowed is False for decision in decisions)


def test_governance_feedback_does_not_touch_sannai_shape_fixture(tmp_path):
    fixture = build_sannai_multi_root_fixture(tmp_path / "fixture")
    soul = fixture.hermes_home / "SOUL.md"
    before = soul.stat().st_mtime_ns
    store = _store(tmp_path / "main", profile="main")
    modules = _seed_governance_artifacts(tmp_path / "main", store)
    bridge = GovernanceFeedbackBridgeModule(tmp_path / "main", profile="main")

    bridge.run_once(store=store, dry_run=False, **modules)

    assert soul.stat().st_mtime_ns == before
    assert not (fixture.hermes_home / "system-modules").exists()


def test_governance_feedback_consumes_speak_gate_deliveries(tmp_path):
    store = _store(tmp_path)
    deliveries_dir = tmp_path / "system-modules" / "speak_gate"
    deliveries_dir.mkdir(parents=True, exist_ok=True)
    deliveries_path = deliveries_dir / "deliveries.jsonl"
    deliveries_path.write_text(
        json.dumps(
            {
                "schema_version": "hermes.speak_gate_delivery.v0",
                "id": "sgd_20260617T120000000Z_abc123def0",
                "ts": "2026-06-17T12:00:00+00:00",
                "created_at": "2026-06-17T12:00:00+00:00",
                "profile": "main",
                "module": "speak_gate",
                "source_module": "wandering_mind",
                "delivery_mode": "owner-send",
                "actual_send": True,
                "channel": "telegram",
                "payload_ref": "local://wandering_mind/output/abc123",
                "reason": "wandering_mind_right_brain",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    bridge = GovernanceFeedbackBridgeModule(tmp_path, profile="main")

    result = bridge.run_once(store=store, dry_run=False)
    governance_events = [event for event in store.read_events() if event.kind == "governance_speak_gate_delivery"]

    assert result["written_event_count"] == 1
    assert result["event_kinds"]["governance_speak_gate_delivery"] == 1
    assert len(governance_events) == 1
    safe_ref = governance_events[0].safe_ref
    assert safe_ref["source_module"] == "speak_gate"
    assert safe_ref["candidate_allowed"] is False
    assert safe_ref["body_policy"] == "summary_only"
    assert safe_ref["speak_gate_delivery_id"] == "sgd_20260617T120000000Z_abc123def0"
    assert safe_ref["speak_gate_source_module"] == "wandering_mind"
    assert safe_ref["speak_gate_delivery_channel"] == "telegram"
    rendered = json.dumps(governance_events[0].to_dict(), ensure_ascii=False)
    assert "wandering_mind" in rendered
    assert "telegram" in rendered
    assert "raw_body" not in rendered


def test_governance_feedback_speak_gate_delivery_idempotent(tmp_path):
    store = _store(tmp_path)
    deliveries_dir = tmp_path / "system-modules" / "speak_gate"
    deliveries_dir.mkdir(parents=True, exist_ok=True)
    deliveries_path = deliveries_dir / "deliveries.jsonl"
    deliveries_path.write_text(
        json.dumps(
            {
                "schema_version": "hermes.speak_gate_delivery.v0",
                "id": "sgd_20260617T130000000Z_def456abc1",
                "ts": "2026-06-17T13:00:00+00:00",
                "created_at": "2026-06-17T13:00:00+00:00",
                "profile": "main",
                "module": "speak_gate",
                "source_module": "expression_draft",
                "delivery_mode": "owner-send",
                "actual_send": True,
                "channel": "telegram",
                "payload_ref": "local://expression_draft/expr_1",
                "reason": "expression_draft_test_host_observation",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    bridge = GovernanceFeedbackBridgeModule(tmp_path, profile="main")

    first = bridge.run_once(store=store, dry_run=False)
    second = bridge.run_once(store=store, dry_run=False)

    assert first["written_event_count"] == 1
    assert second["written_event_count"] == 0
    assert second["already_emitted_count"] == 1
    governance_events = [event for event in store.read_events() if event.kind == "governance_speak_gate_delivery"]
    assert len(governance_events) == 1


def test_governance_feedback_skips_non_profile_speak_gate_deliveries(tmp_path):
    store = _store(tmp_path)
    deliveries_dir = tmp_path / "system-modules" / "speak_gate"
    deliveries_dir.mkdir(parents=True, exist_ok=True)
    deliveries_path = deliveries_dir / "deliveries.jsonl"
    deliveries_path.write_text(
        json.dumps(
            {
                "schema_version": "hermes.speak_gate_delivery.v0",
                "id": "sgd_20260617T140000000Z_ghi789jkl2",
                "ts": "2026-06-17T14:00:00+00:00",
                "created_at": "2026-06-17T14:00:00+00:00",
                "profile": "sannai",
                "module": "speak_gate",
                "source_module": "wandering_mind",
                "delivery_mode": "owner-send",
                "actual_send": True,
                "channel": "origin",
                "payload_ref": "local://wandering_mind/output/def456",
                "reason": "other_profile",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    bridge = GovernanceFeedbackBridgeModule(tmp_path, profile="main")

    result = bridge.run_once(store=store, dry_run=False)
    governance_events = [event for event in store.read_events() if event.kind == "governance_speak_gate_delivery"]

    assert result["status"] == "skipped"
    assert len(governance_events) == 0


def test_to_event_reads_source_class_and_subtype_from_record(tmp_path):
    """V2.4: _to_event reads source_class/subtype from record dict, defaults to governance."""
    bridge = GovernanceFeedbackBridgeModule(tmp_path, profile="main")
    # Record WITHOUT source_class -> defaults to "governance"
    default_record = {
        "kind": "test_default",
        "source_module": "test_mod",
        "source_key": "test_key",
        "state_hash": "abc",
        "artifact_ref": "local://test/default",
        "summary": "default source_class test",
    }
    event_default = bridge._to_event(default_record)
    assert event_default.safe_ref["source_class"] == "governance"
    assert "self_activity_subtype" not in event_default.safe_ref

    # Record WITH source_class="self_activity" + subtype
    sa_record = {
        "kind": "test_self_activity",
        "source_module": "test_mod",
        "source_key": "test_key_sa",
        "state_hash": "def",
        "artifact_ref": "local://test/sa",
        "summary": "self_activity test",
        "source_class": "self_activity",
        "subtype": "resolver",
    }
    event_sa = bridge._to_event(sa_record)
    assert event_sa.safe_ref["source_class"] == "self_activity"
    assert event_sa.safe_ref["self_activity_subtype"] == "resolver"

    # Record WITH source_class="" -> defaults to "governance" (empty string treated as absent)
    empty_record = {
        "kind": "test_empty",
        "source_module": "test_mod",
        "source_key": "test_key_empty",
        "state_hash": "ghi",
        "artifact_ref": "local://test/empty",
        "summary": "empty source_class test",
        "source_class": "",
    }
    event_empty = bridge._to_event(empty_record)
    assert event_empty.safe_ref["source_class"] == "governance", (
        "empty source_class must default to 'governance'"
    )
    assert "self_activity_subtype" not in event_empty.safe_ref


def test_speak_gate_and_ops_gate_events_are_self_activity(tmp_path):
    """V2.5: speech/ops_gate events are tagged source_class='self_activity' with correct subtypes."""
    from plugins.modules.governance.feedback_bridge import GovernanceFeedbackBridgeModule

    bridge = GovernanceFeedbackBridgeModule(tmp_path, profile="main")

    # Verify _speak_gate_events records carry self_activity + speech subtype
    speak_records = bridge._speak_gate_events()
    for record in speak_records:
        assert record.get("source_class") == "self_activity", (
            f"speak_gate record {record.get('kind')} missing source_class=self_activity"
        )
        assert record.get("subtype") == "speech", (
            f"speak_gate record {record.get('kind')} missing subtype=speech"
        )

    # Verify _ops_gate_events records carry self_activity + execution subtype
    # (need a live ops_gate instance to produce records)
    from plugins.modules.governance.ops_gate import OpsGateModule
    from plugins.memory.memory_os.store import MemoryOSStore
    from plugins.memory.memory_os.roots import MemoryOSRoots

    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile="main")
    store = MemoryOSStore(roots)
    store.initialize()
    ops_gate = OpsGateModule(tmp_path, profile="main")
    ops_gate.run_once(
        store=store,
        proposed_actions=[{"id": "test-v2", "kind": "test_action", "target": "test"}],
    )
    ops_records = bridge._ops_gate_events(ops_gate)
    for record in ops_records:
        assert record.get("source_class") == "self_activity", (
            f"ops_gate record {record.get('kind')} missing source_class=self_activity"
        )
        assert record.get("subtype") == "execution", (
            f"ops_gate record {record.get('kind')} missing subtype=execution"
        )
