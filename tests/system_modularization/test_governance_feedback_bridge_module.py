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
        available_dependencies=("memory_os", "scheduler", "evidence_scoring", "ops_gate", "proposal_queue", "self_evolution"),
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
        assert event.safe_ref["source_class"] == "governance"
        assert event.safe_ref["drive_policy"] == "evidence_only"
        assert event.safe_ref["candidate_allowed"] is False
        assert event.safe_ref["body_policy"] == "summary_only"


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
