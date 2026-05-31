from plugins.modules.evidence.confabulation import ConfabulationDetectorModule


def test_confabulation_detector_flags_high_maturity_thin_inference(tmp_path):
    module = ConfabulationDetectorModule(tmp_path, profile="main")

    result = module.evaluate_records(
        [
            {
                "subject_ref": "event:1",
                "maturity_score": 0.91,
                "evidence_profile": {
                    "derivation": "inference",
                    "coverage": {"source_diversity": 1, "recurrence": 0},
                    "provenance": "observed",
                },
            }
        ]
    )

    assert result["flag_count"] == 1
    assert result["actual_execute"] is False
    assert result["score_live_applied"] is False
    assert result["flags"][0]["action"] == "report_only"
    assert result["flags"][0]["audit_action"] == "confabulation_flagged"


def test_confabulation_detector_does_not_flag_well_covered_owner_assertion(tmp_path):
    module = ConfabulationDetectorModule(tmp_path, profile="main")

    result = module.evaluate_records(
        [
            {
                "subject_ref": "crystallized:stable",
                "maturity_score": 0.96,
                "evidence_profile": {
                    "derivation": "owner_assertion",
                    "coverage": {"source_diversity": 3, "recurrence": 4},
                    "provenance": "observed",
                },
            }
        ]
    )

    assert result["flag_count"] == 0
    assert module.read_flags() == []
    status = module.status()
    assert status["status"] == "ok"
    assert status["run_count"] == 1
