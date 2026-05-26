import json

from plugins.memory.memory_os.fixtures import build_event, build_sannai_multi_root_fixture
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.schema import EventEnvelope
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.modules.evidence.scoring import EvidenceScoringModule
from plugins.modules.governance.ops_gate import OpsGateModule
from plugins.modules.governance.proposal_queue import ProposalQueueModule
from plugins.modules.governance.self_evolution import SelfEvolutionGovernorModule, self_evolution_manifest
from plugins.system.lifecycle import ModuleLifecycle


def _store(tmp_path, *, profile="main"):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile=profile)
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def _seed_evidence(tmp_path, store):
    event = EventEnvelope.from_dict(
        {**build_event(seed=1, profile="main"), "summary": "The test host needs a safer dry-run workflow."}
    )
    store.append_event(event)
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    evidence = EvidenceScoringModule(tmp_path, profile="main")
    evidence.score_all(store=store, proposal_queue=proposal_queue)
    return proposal_queue, evidence


def test_self_evolution_manifest_requires_governance_dependencies(tmp_path):
    lifecycle = ModuleLifecycle(
        tmp_path,
        profile="main",
        available_dependencies=("memory_os", "scheduler", "ops_gate", "proposal_queue", "evidence_scoring"),
    )

    status = lifecycle.install(self_evolution_manifest())
    enabled = lifecycle.enable("self_evolution")

    assert status.installed is True
    assert enabled.enabled is True
    assert enabled.delivery_mode == "no-send"
    assert lifecycle.doctor("self_evolution").status == "ok"


def test_self_evolution_dry_run_writes_digest_and_proposal_through_queue(tmp_path):
    store = _store(tmp_path)
    proposal_queue, evidence = _seed_evidence(tmp_path, store)
    ops_gate = OpsGateModule(tmp_path, profile="main")
    module = SelfEvolutionGovernorModule(tmp_path, profile="main")

    result = module.run_once(
        store=store,
        ops_gate=ops_gate,
        proposal_queue=proposal_queue,
        evidence_scoring=evidence,
    )

    assert result["status"] == "ok"
    assert result["execution_mode"] == "dry-run"
    assert result["direct_self_modify"] is False
    assert result["actual_execute"] is False
    assert result["proposal_created"] is True
    queue = proposal_queue.read_queue()
    assert len(queue["items"]) == 1
    proposal = queue["items"][0]
    assert proposal["kind"] == "self_evolution"
    assert proposal["state"] == "candidate"
    assert proposal["crystallized_approved"] is False
    assert all(ref.startswith("feature_score:") for ref in proposal["source_refs"])
    digest = module.digest_path.read_text(encoding="utf-8")
    assert "The test host needs a safer dry-run workflow." in digest
    assert "maturity_score=" in digest
    assert "hard-coded focus" not in digest
    audit_lines = store.roots.audit_path.read_text(encoding="utf-8").splitlines()
    assert any("self_evolution_dry_run_written" in line for line in audit_lines)


def test_self_evolution_does_not_create_proposal_without_scores(tmp_path):
    store = _store(tmp_path)
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    evidence = EvidenceScoringModule(tmp_path, profile="main")
    ops_gate = OpsGateModule(tmp_path, profile="main")
    module = SelfEvolutionGovernorModule(tmp_path, profile="main")

    result = module.run_once(
        store=store,
        ops_gate=ops_gate,
        proposal_queue=proposal_queue,
        evidence_scoring=evidence,
    )

    assert result["status"] == "warning"
    assert result["proposal_created"] is False
    assert proposal_queue.read_queue()["items"] == []


def test_self_evolution_routes_action_through_ops_gate_report_only(tmp_path):
    store = _store(tmp_path)
    proposal_queue, evidence = _seed_evidence(tmp_path, store)
    ops_gate = OpsGateModule(tmp_path, profile="main")
    module = SelfEvolutionGovernorModule(tmp_path, profile="main")

    result = module.run_once(
        store=store,
        ops_gate=ops_gate,
        proposal_queue=proposal_queue,
        evidence_scoring=evidence,
    )

    assert result["ops_gate_decision"]["decision"] == "would_allow"
    assert result["ops_gate_decision"]["actual_execute"] is False
    assert ops_gate.read_reports()[0]["actual_execute"] is False


def test_self_evolution_skips_duplicate_unresolved_proposal(tmp_path):
    store = _store(tmp_path)
    proposal_queue, evidence = _seed_evidence(tmp_path, store)
    ops_gate = OpsGateModule(tmp_path, profile="main")
    module = SelfEvolutionGovernorModule(tmp_path, profile="main")

    first = module.run_once(
        store=store,
        ops_gate=ops_gate,
        proposal_queue=proposal_queue,
        evidence_scoring=evidence,
    )
    second = module.run_once(
        store=store,
        ops_gate=ops_gate,
        proposal_queue=proposal_queue,
        evidence_scoring=evidence,
    )
    status = module.status()
    queue = proposal_queue.read_queue()

    assert first["proposal_created"] is True
    assert second["proposal_created"] is False
    assert second["novelty_skipped"] is True
    assert second["reason"] == "duplicate_unresolved_proposal"
    assert second["existing_proposal_id"] == first["proposal_id"]
    assert len(queue["items"]) == 1
    assert status["proposal_count"] == 1
    assert status["novelty_skipped_count"] == 1
    assert status["duplicate_unresolved_proposal_count"] == 1
    assert len(ops_gate.read_reports()) == 1


def test_self_evolution_creates_expression_policy_proposal_from_expression_feedback(tmp_path):
    store = _store(tmp_path)
    proposal_queue = ProposalQueueModule(tmp_path, profile="main")
    feedback_path = store.roots.memory_os_root / "system" / "expression_feedback_ledger.jsonl"
    feedback_path.parent.mkdir(parents=True, exist_ok=True)
    feedback_path.write_text(
        json.dumps(
            {
                "schema_version": "hermes.memory_os.expression_feedback.v0",
                "feedback_id": "efb_1",
                "profile": "main",
                "target_type": "expression",
                "target_id": "expr_1",
                "rating": "too_mechanical",
                "source_module": "owner_action",
                "live_policy_changed": False,
                "raw_body_included": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    evidence = EvidenceScoringModule(tmp_path, profile="main")
    evidence.score_all(store=store, proposal_queue=proposal_queue)
    module = SelfEvolutionGovernorModule(tmp_path, profile="main")

    result = module.run_once(
        store=store,
        ops_gate=OpsGateModule(tmp_path, profile="main"),
        proposal_queue=proposal_queue,
        evidence_scoring=evidence,
    )

    assert result["proposal_created"] is True
    proposal = proposal_queue.read_queue()["items"][0]
    assert proposal["kind"] == "expression_policy"
    assert "right-brain expression policy" in proposal["title"]
    assert "prompt/cadence/policy proposal" in proposal["body"]
    assert proposal["actual_execute"] is False


def test_self_evolution_doctor_reports_missing_dependencies_and_stale_digest(tmp_path):
    module = SelfEvolutionGovernorModule(tmp_path, profile="main")

    missing = module.doctor()
    stale = module.doctor(
        ops_gate=OpsGateModule(tmp_path, profile="main"),
        proposal_queue=ProposalQueueModule(tmp_path, profile="main"),
        evidence_scoring=EvidenceScoringModule(tmp_path, profile="main"),
    )

    assert missing["status"] == "error"
    assert missing["findings"][0]["code"] == "missing_required_runtime_dependency"
    assert stale["status"] == "warning"
    assert stale["findings"][0]["code"] == "runtime_digest_missing"


def test_self_evolution_status_does_not_expose_proposal_body(tmp_path):
    store = _store(tmp_path)
    proposal_queue, evidence = _seed_evidence(tmp_path, store)
    module = SelfEvolutionGovernorModule(tmp_path, profile="main")
    module.run_once(
        store=store,
        ops_gate=OpsGateModule(tmp_path, profile="main"),
        proposal_queue=proposal_queue,
        evidence_scoring=evidence,
    )

    status = module.status()

    rendered = json.dumps(status, ensure_ascii=False)
    assert status["proposal_count"] == 1
    assert "Use the highest evidence signal" not in rendered


def test_self_evolution_does_not_touch_sannai_shape_fixture(tmp_path):
    fixture = build_sannai_multi_root_fixture(tmp_path / "fixture")
    soul = fixture.hermes_home / "SOUL.md"
    before = soul.stat().st_mtime_ns
    store = _store(tmp_path / "main", profile="main")
    proposal_queue, evidence = _seed_evidence(tmp_path / "main", store)
    module = SelfEvolutionGovernorModule(tmp_path / "main", profile="main")

    module.run_once(
        store=store,
        ops_gate=OpsGateModule(tmp_path / "main", profile="main"),
        proposal_queue=proposal_queue,
        evidence_scoring=evidence,
    )

    assert soul.stat().st_mtime_ns == before
    assert not (fixture.hermes_home / "system-modules").exists()
