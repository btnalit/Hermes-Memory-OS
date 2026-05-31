from plugins.modules.governance.crystallized_revalidator import CrystallizedRevalidatorModule


def test_crystallized_revalidator_flags_but_does_not_demote(tmp_path):
    module = CrystallizedRevalidatorModule(tmp_path, profile="main")

    result = module.evaluate(
        records=[{"record_id": "cr_1", "subject_ref": "crystallized:cr_1"}],
        observations=[
            {
                "source_ref": "event:later",
                "contradicts_record_id": "cr_1",
                "evidence_profile": {"derivation": "direct_observation", "provenance": "observed"},
            }
        ],
    )

    assert result["flag_count"] == 1
    assert result["actual_crystallized_approval"] is False
    assert result["actual_execute"] is False
    assert result["flags"][0]["action"] == "would_demote"
    assert result["flags"][0]["audit_action"] == "crystallized_regression_flagged"
    assert module.read_flags()[0]["live_applied"] is False


def test_crystallized_revalidator_status_is_ok_after_zero_flag_run(tmp_path):
    module = CrystallizedRevalidatorModule(tmp_path, profile="main")

    result = module.evaluate(records=[], observations=[])

    assert result["flag_count"] == 0
    status = module.status()
    assert status["status"] == "ok"
    assert status["run_count"] == 1
    assert status["demotion_live_applied"] is False
