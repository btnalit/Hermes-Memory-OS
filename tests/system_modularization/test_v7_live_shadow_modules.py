from plugins.modules.context.abstraction_distillation import AbstractionDistillationModule
from plugins.modules.governance.candidate_review import CandidateReviewModule, FeaturePreRouter
from plugins.modules.governance.cascade_routing_policy import CascadeRoutingPolicyModule
from plugins.modules.governance.judge_calibration import JudgeCalibrationMonitor
from plugins.modules.governance.migration_controller import MigrationControllerModule
from plugins.modules.governance.provisional import ProvisionalModule
from plugins.modules.governance.shadow_recall import ShadowRecallModule


def test_judge_calibration_tracks_consistency_drift_and_canary_without_apply(tmp_path):
    module = JudgeCalibrationMonitor(tmp_path, profile="main")

    result = module.evaluate(
        decisions=[
            {"case_id": "c1", "verdict": "keep"},
            {"case_id": "c1", "verdict": "keep"},
            {"case_id": "c2", "verdict": "discard"},
        ],
        canaries=[{"case_id": "canary_bad", "expected": "discard", "verdict": "discard"}],
    )

    assert result["status"] == "ok"
    assert result["consistency_rate"] == 1.0
    assert result["canary_passed"] is True
    assert result["calibration_live_applied"] is False
    assert result["actual_execute"] is False
    assert module.status()["run_count"] == 1


def test_candidate_review_preroutes_and_reviews_mid_band_without_mutation(tmp_path):
    prerouter = FeaturePreRouter()
    routes = [
        {"subject_ref": "memory:low", "band": "low", "maturity_score": 0.2},
        {"subject_ref": "memory:mid", "band": "mid", "maturity_score": 0.55},
        {"subject_ref": "memory:high", "band": "high", "maturity_score": 0.9},
    ]

    preroute_result = prerouter.route(routes)
    review_result = CandidateReviewModule(tmp_path, profile="main").review(preroute_result["items"])

    assert [item["pre_route"] for item in preroute_result["items"]] == [
        "fast_discard",
        "needs_review",
        "fast_merge",
    ]
    assert review_result["decision_count"] == 3
    assert {item["decision"] for item in review_result["decisions"]} >= {"downgrade", "recollect", "keep"}
    assert review_result["candidate_review_live_applied"] is False
    assert review_result["actual_execute"] is False
    assert review_result["canonical_state_changed"] is False


def test_shadow_recall_flags_discard_side_misses_without_enabling_auto_discard(tmp_path):
    module = ShadowRecallModule(tmp_path, profile="main")
    result = module.record_discards(
        [
            {
                "subject_ref": "memory:discarded",
                "text": "rare deployment failure signature",
                "route_intent": "auto_discard_candidate",
            }
        ]
    )
    miss = module.evaluate_recall_misses([{"query": "deployment failure", "text": "rare deployment failure signature"}])

    assert result["fingerprint_count"] == 1
    assert miss["miss_hit_count"] == 1
    assert miss["auto_discard_live_applied"] is False
    assert miss["actual_execute"] is False


def test_provisional_writes_shadow_records_and_would_promote_only(tmp_path):
    module = ProvisionalModule(tmp_path, profile="main")
    result = module.write_provisional(
        [
            {
                "subject_ref": "memory:high",
                "decision": "keep",
                "maturity_score": 0.93,
                "source_refs": ["event:1"],
            }
        ]
    )
    promotion = module.evaluate_promotions(min_maturity=0.9)

    assert result["provisional_count"] == 1
    assert promotion["would_promote_count"] == 1
    assert promotion["auto_promote_live_applied"] is False
    assert promotion["actual_crystallized_approval"] is False
    assert promotion["canonical_state_changed"] is False


def test_cascade_routing_policy_proposes_guarded_policy_without_apply(tmp_path):
    module = CascadeRoutingPolicyModule(tmp_path, profile="main")

    result = module.propose_policy(
        band_metrics={
            "low": {"n": 50, "error_rate": 0.01},
            "mid": {"n": 10, "error_rate": 0.15},
        },
        guardrails={"aa_passed": True, "honesty_passed": True, "min_n": 30},
    )

    assert result["status"] == "ok"
    assert result["policy"]["low"]["automation_candidate"] is True
    assert result["policy"]["mid"]["automation_candidate"] is False
    assert result["route_strategy_live_applied"] is False
    assert result["actual_execute"] is False


def test_migration_controller_keeps_cold_start_shadow_only(tmp_path):
    module = MigrationControllerModule(tmp_path, profile="main", label_floor=5)

    result = module.evaluate(
        signals={
            "owner_label_count": 2,
            "simulation_preheated": True,
            "confidence_router_green": True,
        }
    )

    assert result["regime"] == "cold_start"
    assert result["effective_mode"] == "live-shadow"
    assert result["automation_allowed"] is False
    assert result["migration_live_applied"] is False
    assert result["actual_execute"] is False


def test_abstraction_distillation_keeps_l0_refs_and_never_treats_distillation_as_truth(tmp_path):
    module = AbstractionDistillationModule(tmp_path, profile="main")

    result = module.distill(
        source_ref="event:1",
        source_text="User said the NAS media host is 10.20.3.200 and should stay shadow-live first.",
    )

    assert result["distillation_count"] == 3
    assert result["distillation_live_applied"] is False
    assert result["truth_status"] == "candidate_only"
    assert result["canonical_state_changed"] is False
    assert all(item["source_ref"] == "event:1" for item in result["items"])
    assert module.recall_source(result["items"][0]["source_checksum"])["text"].startswith("User said")
