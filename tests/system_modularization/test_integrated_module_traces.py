from plugins.memory.memory_os.fixtures import build_event
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.schema import EventEnvelope
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.modules.cognition.inner_drive import InnerDriveRuntimeModule
from plugins.modules.cognition.wandering_mind import WanderingMindModule
from plugins.modules.context.household_digest import HouseholdDigestModule
from plugins.modules.evidence.scoring import EvidenceScoringModule
from plugins.modules.expression.speak_gate import SpeakGateModule
from plugins.modules.governance.ops_gate import OpsGateModule
from plugins.modules.governance.proposal_queue import ProposalQueueModule
from plugins.modules.governance.self_evolution import SelfEvolutionGovernorModule


def _store(tmp_path, *, profile="main"):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile=profile)
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def _append_events(store, *, count: int, profile: str = "main"):
    for seed in range(count):
        store.append_event(EventEnvelope.from_dict(build_event(seed=seed, profile=profile)))


def test_integrated_user_message_trace_stays_reviewed_and_no_send(tmp_path):
    store = _store(tmp_path, profile="main")
    _append_events(store, count=3)
    digest = HouseholdDigestModule(tmp_path, profile="main")
    inner_drive = InnerDriveRuntimeModule(tmp_path, profile="main")
    scoring = EvidenceScoringModule(tmp_path, profile="main")
    ops_gate = OpsGateModule(tmp_path, profile="main")
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    governor = SelfEvolutionGovernorModule(tmp_path, profile="main")
    speak_gate = SpeakGateModule(tmp_path, profile="main", delivery_mode="would-send")

    digest_result = digest.build_digest(store=store, min_events=1)
    inner_result = inner_drive.run_once(store=store, min_events=1)
    score_result = scoring.score_all(store=store, proposal_queue=proposal_queue)
    governor_result = governor.run_once(
        store=store,
        ops_gate=ops_gate,
        proposal_queue=proposal_queue,
        evidence_scoring=scoring,
    )
    before_owner_review = speak_gate.evaluate_proposal(
        governor_result["proposal_id"],
        proposal_queue=proposal_queue,
    )
    proposal_queue.transition(
        store=store,
        candidate_id=governor_result["proposal_id"],
        decision="approve",
        reviewer="owner",
    )
    after_owner_review = speak_gate.evaluate_proposal(
        governor_result["proposal_id"],
        proposal_queue=proposal_queue,
    )

    assert digest_result["event_count"] == 3
    assert inner_result["processed_event_count"] == 3
    assert score_result["score_count"] >= 3
    assert governor_result["proposal_created"] is True
    assert governor_result["direct_self_modify"] is False
    assert governor_result["actual_execute"] is False
    assert before_owner_review["decision"] == "no_send"
    assert before_owner_review["actual_send"] is False
    assert after_owner_review["decision"] == "would_send"
    assert after_owner_review["actual_send"] is False


def test_integrated_wandering_mind_trace_routes_expression_through_speak_gate(tmp_path):
    store = _store(tmp_path, profile="main")
    _append_events(store, count=2)
    digest = HouseholdDigestModule(tmp_path, profile="main")
    wandering = WanderingMindModule(tmp_path, profile="main")
    speak_gate = SpeakGateModule(tmp_path, profile="main", delivery_mode="would-send")

    digest.build_digest(store=store, min_events=1)
    wandering_result = wandering.run_once(store=store, min_events=1)
    delivery = speak_gate.evaluate_wandering_output(wandering_result["output"], channel="origin")
    silent_delivery = speak_gate.evaluate_wandering_output("[SILENT]", channel="origin")

    assert wandering_result["would_send"] is True
    assert wandering_result["actual_send"] is False
    assert delivery["decision"] == "would_send"
    assert delivery["actual_send"] is False
    assert silent_delivery["decision"] == "no_send"
    assert silent_delivery["actual_send"] is False
