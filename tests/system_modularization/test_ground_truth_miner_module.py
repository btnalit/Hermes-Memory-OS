import json
from datetime import datetime, timedelta, timezone

from plugins.memory.memory_os.execution_gate import start_execution_gate_envelope
from plugins.memory.memory_os.owner_actions import owner_actions_path
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.modules.governance.ground_truth_miner import (
    REVERSIBLE_LABELS_LANE_ID,
    REVERSIBLE_LABELS_RISK_CLASS,
    GroundTruthMinerModule,
    reversible_labels_scope,
)


def test_ground_truth_miner_writes_retractable_owner_label(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="main"))
    store.initialize()
    module = GroundTruthMinerModule(tmp_path, profile="main")

    result = module.mine(
        store=store,
        audit_entries=[
            {
                "action": "owner_action_reply_processed",
                "status": "ok",
                "target": "oa_123",
                "details": {"action_type": "approve_candidate", "target_id": "cand_1"},
            }
        ],
    )

    assert result["status"] == "ok"
    assert result["label_count"] == 1
    assert result["actual_execute"] is False
    assert module.read_labels()[0]["label_state"] == "active"
    assert module.read_labels()[0]["retractable"] is True
    assert module.read_labels()[0]["ttl_days"] == 90
    assert module.read_labels()[0]["source_scope_ref"] == "crystallized_candidate:cand_1"
    assert module.read_labels()[0]["actual_route_score_write"] is False
    assert module.read_labels()[0]["hindsight_write"] is False


def test_ground_truth_miner_mines_real_owner_action_ledger_input(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="main"))
    store.initialize()
    module = GroundTruthMinerModule(tmp_path, profile="main")
    path = owner_actions_path(store.roots)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "memory-os.owner_action.v0",
                "owner_action_id": "oa_real_1",
                "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "action_type": "approve_candidate",
                "target_type": "candidate",
                "target_id": "cand_real",
                "result": "applied",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    result = module.run_once(store=store)
    labels = module.read_labels()

    assert result["label_count"] == 1
    assert labels[0]["target_id"] == "cand_real"
    assert labels[0]["source_audit_target"] == "oa_real_1"
    assert labels[0]["source_scope_ref"] == "crystallized_candidate:cand_real"
    assert labels[0]["actual_route_score_write"] is False


def test_ground_truth_miner_automatic_write_uses_structural_write_gate(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="main"))
    store.initialize()
    module = GroundTruthMinerModule(tmp_path, profile="main")
    scope = reversible_labels_scope("main")
    permit = start_execution_gate_envelope(
        store,
        lane_id=REVERSIBLE_LABELS_LANE_ID,
        trigger_surface="cognitive_loop",
        risk_class=REVERSIBLE_LABELS_RISK_CLASS,
        human_approval_required=False,
        why_no_human_approval="retractable labels only",
        scope=scope,
        boundary={"actual_send": False, "actual_execute": False},
    )

    result = module.mine(
        store=store,
        audit_entries=[
            {
                "action": "owner_action_reply_processed",
                "status": "ok",
                "target": "oa_123",
                "details": {"action_type": "approve_candidate", "target_id": "cand_1"},
            }
        ],
        execution_envelope_id=permit["execution_gate_envelope_id"],
        expected_scope=scope,
    )
    labels = [json.loads(line) for line in module.labels_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    runs = [json.loads(line) for line in module.runs_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert result["status"] == "ok"
    assert result["execution_gate_resolution"]["status"] == "valid"
    assert result["structural_write_gate_bound"] is True
    assert labels[0]["structural_write_governance"]["lane_id"] == REVERSIBLE_LABELS_LANE_ID
    assert labels[0]["structural_write_governance"]["risk_class"] == REVERSIBLE_LABELS_RISK_CLASS
    assert labels[0]["structural_write_governance"]["boundary_true"] is False
    assert runs[0]["structural_write_governance"]["lane_id"] == REVERSIBLE_LABELS_LANE_ID


def test_ground_truth_miner_status_is_ok_after_zero_label_run(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="main"))
    store.initialize()
    module = GroundTruthMinerModule(tmp_path, profile="main")

    result = module.run_once(store=store)

    assert result["label_count"] == 0
    status = module.status()
    assert status["status"] == "ok"
    assert status["run_count"] == 1
    assert status["score_live_applied"] is False


def test_ground_truth_miner_retracts_label_without_deleting_record(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="main"))
    store.initialize()
    module = GroundTruthMinerModule(tmp_path, profile="main")
    module.mine(
        store=store,
        audit_entries=[
            {
                "action": "owner_action_reply_processed",
                "status": "ok",
                "target": "oa_123",
                "details": {"action_type": "approve_candidate", "target_id": "cand_1"},
            }
        ],
    )
    label_id = module.read_labels()[0]["label_id"]

    result = module.retract_label(label_id, reason="crystallized_regression")

    assert result["status"] == "ok"
    labels = module.read_labels()
    assert labels[0]["label_state"] == "retracted"
    assert labels[0]["retraction_reason"] == "crystallized_regression"
    assert len([line for line in module.labels_path.read_text(encoding="utf-8").splitlines() if line.strip()]) == 2
    assert "label_retracted" in module.runs_path.read_text(encoding="utf-8")


def test_ground_truth_miner_expires_ttl_labels_from_active_read_model(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="main"))
    store.initialize()
    module = GroundTruthMinerModule(tmp_path, profile="main")
    expired_at = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat().replace("+00:00", "Z")
    module.labels_path.parent.mkdir(parents=True, exist_ok=True)
    module.labels_path.write_text(
        json.dumps(
            {
                "schema_version": "hermes.ground_truth_label.v0",
                "label_id": "gt_label_expired",
                "profile": "main",
                "subject_ref": "crystallized_candidate:cand_expired",
                "source_scope_ref": "crystallized_candidate:cand_expired",
                "target_id": "cand_expired",
                "label_kind": "owner_approved_candidate",
                "label_state": "active",
                "retractable": True,
                "ttl_days": 90,
                "expires_at": expired_at,
                "actual_route_score_write": False,
                "hindsight_write": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    assert module.read_labels() == []
    all_labels = module.read_labels(include_expired=True)
    status = module.status()

    assert all_labels[0]["label_state"] == "expired"
    assert all_labels[0]["expired"] is True
    assert status["active_label_count"] == 0
    assert status["expired_label_count"] == 1


def test_ground_truth_miner_refreshes_expired_label_from_new_owner_action(tmp_path):
    store = MemoryOSStore(MemoryOSRoots.from_hermes_home(tmp_path, profile="main"))
    store.initialize()
    module = GroundTruthMinerModule(tmp_path, profile="main")
    expired_at = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat().replace("+00:00", "Z")
    module.mine(
        store=store,
        audit_entries=[
            {
                "action": "owner_action_reply_processed",
                "status": "ok",
                "target": "oa_original",
                "details": {"action_type": "approve_candidate", "target_id": "cand_refresh"},
            }
        ],
    )
    original = module.read_labels()[0]
    expired_record = dict(original)
    expired_record["expires_at"] = expired_at
    module.labels_path.write_text(
        json.dumps(expired_record, ensure_ascii=False, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    assert module.read_labels() == []
    owner_actions_path(store.roots).parent.mkdir(parents=True, exist_ok=True)
    owner_actions_path(store.roots).write_text(
        json.dumps(
            {
                "schema_version": "memory-os.owner_action.v0",
                "owner_action_id": "oa_refresh",
                "action_type": "approve_candidate",
                "target_id": "cand_refresh",
                "result": "applied",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    result = module.run_once(store=store)

    labels = module.read_labels()
    all_labels = module.read_labels(include_expired=True)
    assert result["label_count"] == 1
    assert labels[0]["target_id"] == "cand_refresh"
    assert labels[0]["label_state"] == "active"
    assert all_labels[0].get("expired") is not True
    assert len(module.labels_path.read_text(encoding="utf-8").splitlines()) == 2
