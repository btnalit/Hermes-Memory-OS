import json

from plugins.memory.memory_os.fixtures import build_sannai_multi_root_fixture
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.modules.governance.proposal_queue import ProposalQueueModule, proposal_queue_manifest
from plugins.system.lifecycle import ModuleLifecycle


def _store(tmp_path, *, profile="main"):
    roots = MemoryOSRoots.from_hermes_home(tmp_path, profile=profile)
    store = MemoryOSStore(roots)
    store.initialize()
    return store


def test_proposal_queue_manifest_installs_through_lifecycle(tmp_path):
    lifecycle = ModuleLifecycle(
        tmp_path,
        profile="main",
        available_dependencies=("memory_os", "scheduler"),
    )

    status = lifecycle.install(proposal_queue_manifest())
    enabled = lifecycle.enable("proposal_queue")

    assert status.installed is True
    assert enabled.enabled is True
    assert enabled.delivery_mode == "no-send"
    assert lifecycle.doctor("proposal_queue").status == "ok"


def test_proposal_queue_creates_profile_local_candidate_and_audit(tmp_path):
    store = _store(tmp_path)
    module = ProposalQueueModule(tmp_path, profile="main")

    candidate = module.create_candidate(
        store=store,
        title="Test governance proposal",
        body="Try a dry-run governance change.",
        source_refs=["event:abc"],
        kind="governance",
    )

    assert candidate["state"] == "candidate"
    assert candidate["crystallized_approved"] is False
    queue = module.read_queue()
    assert queue["items"][0]["candidate_id"] == candidate["candidate_id"]
    assert queue["items"][0]["body"] == "Try a dry-run governance change."
    audit_lines = store.roots.audit_path.read_text(encoding="utf-8").splitlines()
    assert any("proposal_queue_candidate_created" in line for line in audit_lines)


def test_proposal_queue_transitions_defer_reject_and_approve_without_crystallized_approval(tmp_path):
    store = _store(tmp_path)
    module = ProposalQueueModule(tmp_path, profile="main")
    first = module.create_candidate(store=store, title="A", body="A body")
    second = module.create_candidate(store=store, title="B", body="B body")
    third = module.create_candidate(store=store, title="C", body="C body")

    deferred = module.transition(store=store, candidate_id=first["candidate_id"], decision="defer", reviewer="owner")
    rejected = module.transition(store=store, candidate_id=second["candidate_id"], decision="reject", reviewer="owner")
    approved = module.transition(store=store, candidate_id=third["candidate_id"], decision="approve", reviewer="owner")

    assert deferred["state"] == "owner_defer"
    assert rejected["state"] == "owner_declined"
    assert approved["state"] == "approved_for_proposal"
    assert approved["crystallized_approved"] is False
    assert approved["approval_purpose"] == "proposal_queue_only"


def test_proposal_queue_maps_cw019_states_without_crystallized_approval(tmp_path):
    store = _store(tmp_path)
    module = ProposalQueueModule(tmp_path, profile="main")

    imported = module.import_legacy_candidate(
        store=store,
        legacy_record={
            "id": "cw019-1",
            "status": "owner_eligible",
            "text": "Synthetic owner review candidate",
        },
        source="cw-019-shadow",
    )

    assert imported["candidate_id"] == "cw019-1"
    assert imported["state"] == "owner_eligible"
    assert imported["legacy_state"] == "owner_eligible"
    assert imported["approval_purpose"] == "legacy_owner_review_visibility"
    assert imported["crystallized_approved"] is False


def test_proposal_queue_legacy_import_is_idempotent(tmp_path):
    store = _store(tmp_path)
    module = ProposalQueueModule(tmp_path, profile="main")
    legacy_record = {
        "id": "cw019-1",
        "status": "owner_eligible",
        "text": "Synthetic owner review candidate",
    }

    first = module.import_legacy_candidate(store=store, legacy_record=legacy_record, source="cw-019-shadow")
    second = module.import_legacy_candidate(store=store, legacy_record=legacy_record, source="cw-019-shadow")

    queue = module.read_queue()
    assert first == second
    assert len(queue["items"]) == 1
    audit_lines = store.roots.audit_path.read_text(encoding="utf-8").splitlines()
    assert sum("proposal_queue_legacy_candidate_imported" in line for line in audit_lines) == 1
    assert sum("proposal_queue_legacy_candidate_import_skipped" in line for line in audit_lines) == 1


def test_proposal_queue_status_and_doctor_report_queue_health(tmp_path):
    store = _store(tmp_path)
    module = ProposalQueueModule(tmp_path, profile="main")
    candidate = module.create_candidate(store=store, title="Needs owner", body="Pending body")

    status = module.status()
    doctor = module.doctor()

    assert status["candidate_count"] == 1
    assert status["state_counts"] == {"candidate": 1}
    assert doctor["status"] == "warning"
    assert doctor["findings"][0]["code"] == "pending_candidates_present"
    assert candidate["body"] not in json.dumps(status, ensure_ascii=False)


def test_proposal_queue_does_not_touch_sannai_shape_fixture(tmp_path):
    fixture = build_sannai_multi_root_fixture(tmp_path / "fixture")
    soul = fixture.hermes_home / "SOUL.md"
    before = soul.stat().st_mtime_ns
    store = _store(tmp_path / "main", profile="main")
    module = ProposalQueueModule(tmp_path / "main", profile="main")

    module.create_candidate(store=store, title="Main profile only", body="Local queue only")

    assert soul.stat().st_mtime_ns == before
    assert not (fixture.hermes_home / "system-modules").exists()
