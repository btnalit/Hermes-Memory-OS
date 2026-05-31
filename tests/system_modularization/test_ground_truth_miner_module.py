from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore
from plugins.modules.governance.ground_truth_miner import GroundTruthMinerModule


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
    assert "label_retracted" in module.runs_path.read_text(encoding="utf-8")
